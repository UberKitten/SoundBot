import assert from "node:assert/strict";
import { readFileSync } from "node:fs";
import { registerHooks } from "node:module";
import test from "node:test";
import ts from "typescript";

const audioPlatformModule = new URL(
  "../scripts/audio-platform.ts",
  import.meta.url
).href;
const waveformPlaybackModule = new URL(
  "../scripts/waveform-playback.ts",
  import.meta.url
).href;
const typescriptModules = new Set([
  audioPlatformModule,
  waveformPlaybackModule,
]);

registerHooks({
  resolve(specifier, context, nextResolve) {
    if (specifier === "audio-platform") {
      return { url: audioPlatformModule, shortCircuit: true };
    }
    return nextResolve(specifier, context);
  },
  load(url, context, nextLoad) {
    if (!typescriptModules.has(url)) return nextLoad(url, context);
    const source = readFileSync(new URL(url), "utf8");
    const transpiled = ts.transpileModule(source, {
      compilerOptions: {
        module: ts.ModuleKind.ESNext,
        target: ts.ScriptTarget.ES2022,
      },
      fileName: new URL(url).pathname,
    });
    return {
      format: "module",
      shortCircuit: true,
      source: transpiled.outputText,
    };
  },
});

const {
  createWaveformPreviewPlayback,
  selectWaveformPlaybackBackend,
} = await import(waveformPlaybackModule);

function deferred() {
  let resolve;
  let reject;
  const promise = new Promise((resolvePromise, rejectPromise) => {
    resolve = resolvePromise;
    reject = rejectPromise;
  });
  return { promise, resolve, reject };
}

function installAudioHarness(t, options = {}) {
  const previousAudioContext = Object.getOwnPropertyDescriptor(
    globalThis,
    "AudioContext"
  );
  const contexts = [];
  const sources = [];
  const gains = [];

  class FakeMediaElementSourceNode {
    constructor(mediaElement) {
      this.mediaElement = mediaElement;
      this.connected = null;
      this.disconnectCalls = 0;
      sources.push(this);
    }

    connect(target) {
      this.connected = target;
      return target;
    }

    disconnect() {
      this.disconnectCalls += 1;
    }
  }

  class FakeGainNode {
    constructor() {
      this.gain = { value: 1 };
      this.connected = null;
      this.disconnectCalls = 0;
      gains.push(this);
    }

    connect(target) {
      this.connected = target;
      return target;
    }

    disconnect() {
      this.disconnectCalls += 1;
    }
  }

  class FakeAudioContext {
    constructor() {
      this.destination = { type: "destination", context: this };
      this.state = options.contextState ?? "running";
      this.resumeCalls = 0;
      this.closeCalls = 0;
      contexts.push(this);
    }

    createMediaElementSource(mediaElement) {
      return new FakeMediaElementSourceNode(mediaElement);
    }

    createGain() {
      return new FakeGainNode();
    }

    resume() {
      this.resumeCalls += 1;
      if (options.resume) return options.resume(this, this.resumeCalls);
      this.state = "running";
      return Promise.resolve();
    }

    close() {
      this.closeCalls += 1;
      this.state = "closed";
      return Promise.resolve();
    }
  }

  Object.defineProperty(globalThis, "AudioContext", {
    configurable: true,
    writable: true,
    value: FakeAudioContext,
  });
  t.after(() => {
    if (previousAudioContext) {
      Object.defineProperty(globalThis, "AudioContext", previousAudioContext);
    } else {
      delete globalThis.AudioContext;
    }
  });

  return { contexts, sources, gains };
}

function createPlayer(options = {}) {
  const media = options.media ?? { currentTime: 0, paused: true, volume: 1 };
  const volumeAssignments = [];
  const activationAtPlay = [];

  const player = {
    media,
    playCalls: 0,
    volumeAssignments,
    activationAtPlay,

    getMediaElement() {
      return media;
    },

    setVolume(volume) {
      if (options.enforceNativeVolume) {
        assert.ok(
          volume >= 0 && volume <= 1,
          `native media volume must stay in range, received ${volume}`
        );
      }
      volumeAssignments.push(volume);
      media.volume = volume;
    },

    play() {
      this.playCalls += 1;
      activationAtPlay.push(options.activationOpen?.() ?? true);
      media.paused = false;
      return options.play?.(this) ?? Promise.resolve();
    },
  };

  return player;
}

test("selects MediaElement only for iPhone and touch-Mac iPadOS", () => {
  const cases = [
    {
      name: "iPhone",
      nav: {
        userAgent:
          "Mozilla/5.0 (iPhone; CPU iPhone OS 18_6 like Mac OS X) AppleWebKit/605.1.15",
        platform: "iPhone",
        maxTouchPoints: 5,
      },
      expected: "MediaElement",
    },
    {
      name: "touch-Mac iPadOS",
      nav: {
        userAgent:
          "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15) AppleWebKit/605.1.15 Version/18.6 Mobile/15E148 Safari/604.1",
        platform: "MacIntel",
        maxTouchPoints: 5,
      },
      expected: "MediaElement",
    },
    {
      name: "desktop Firefox",
      nav: {
        userAgent:
          "Mozilla/5.0 (X11; Linux x86_64; rv:141.0) Gecko/20100101 Firefox/141.0",
        platform: "Linux x86_64",
        maxTouchPoints: 0,
      },
      expected: "WebAudio",
    },
    {
      name: "desktop Chromium",
      nav: {
        userAgent:
          "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 Chrome/138.0.0.0 Safari/537.36",
        platform: "Win32",
        maxTouchPoints: 0,
      },
      expected: "WebAudio",
    },
  ];

  for (const { name, nav, expected } of cases) {
    assert.equal(selectWaveformPlaybackBackend(nav), expected, name);
  }
});

test("MediaElement lazily bridges 200% gain, starts in activation, and reuses the graph after interruption", async (t) => {
  const firstResume = deferred();
  const secondResume = deferred();
  const resumeGates = [firstResume, secondResume];
  const harness = installAudioHarness(t, {
    contextState: "suspended",
    resume(_context, call) {
      return resumeGates[call - 1].promise;
    },
  });
  let activationOpen = true;
  const player = createPlayer({
    enforceNativeVolume: true,
    activationOpen: () => activationOpen,
  });
  const playback = createWaveformPreviewPlayback(player, "MediaElement", 2);

  assert.equal(playback.backend, "MediaElement");
  assert.equal(harness.contexts.length, 0, "the bridge is lazy");
  assert.ok(player.volumeAssignments.every((volume) => volume <= 1));
  assert.equal(player.media.volume, 1, "200% is clamped before the bridge exists");

  const firstPlay = playback.play();
  activationOpen = false;
  assert.deepEqual(player.activationAtPlay, [true]);
  assert.equal(player.playCalls, 1, "player.play runs in the activation turn");
  assert.equal(harness.contexts.length, 1);
  assert.equal(harness.sources.length, 1);
  assert.equal(harness.gains.length, 1);

  const context = harness.contexts[0];
  const source = harness.sources[0];
  const gain = harness.gains[0];
  assert.equal(source.connected, gain);
  assert.equal(gain.connected, context.destination);
  assert.equal(gain.gain.value, 2);
  assert.equal(context.resumeCalls, 1);

  let firstCompleted = false;
  void firstPlay.then(() => {
    firstCompleted = true;
  });
  await Promise.resolve();
  assert.equal(firstCompleted, false, "play waits while the context is suspended");
  context.state = "running";
  firstResume.resolve();
  await firstPlay;
  assert.equal(firstCompleted, true);
  assert.equal(context.state, "running");

  for (const volume of [0, 1, 2]) {
    playback.setVolume(volume);
    assert.equal(gain.gain.value, volume);
    assert.equal(player.media.volume, 1, "the bridge owns post-play gain");
  }
  assert.ok(player.volumeAssignments.every((volume) => volume <= 1));

  context.state = "suspended";
  activationOpen = true;
  const secondPlay = playback.play();
  activationOpen = false;
  assert.deepEqual(player.activationAtPlay, [true, true]);
  assert.equal(player.playCalls, 2);
  assert.equal(context.resumeCalls, 2);
  assert.equal(harness.contexts.length, 1);
  assert.equal(harness.sources.length, 1);
  assert.equal(harness.gains.length, 1);

  let secondCompleted = false;
  void secondPlay.then(() => {
    secondCompleted = true;
  });
  await Promise.resolve();
  assert.equal(secondCompleted, false);
  context.state = "running";
  secondResume.resolve();
  await secondPlay;
  assert.equal(secondCompleted, true);
  assert.equal(gain.gain.value, 2);

  playback.destroy();
});

test("MediaElement cleanup disconnects and closes before a reopened preview gets a fresh graph", async (t) => {
  const harness = installAudioHarness(t);
  const firstPlayer = createPlayer({ enforceNativeVolume: true });
  const firstPlayback = createWaveformPreviewPlayback(
    firstPlayer,
    "MediaElement",
    1.5
  );

  await firstPlayback.play();
  const firstContext = harness.contexts[0];
  const firstSource = harness.sources[0];
  const firstGain = harness.gains[0];
  firstPlayback.destroy();
  firstPlayback.destroy();

  assert.equal(firstSource.disconnectCalls, 1);
  assert.equal(firstGain.disconnectCalls, 1);
  assert.equal(firstContext.closeCalls, 1);
  assert.equal(firstContext.state, "closed");

  const reopenedPlayer = createPlayer({ enforceNativeVolume: true });
  const reopenedPlayback = createWaveformPreviewPlayback(
    reopenedPlayer,
    "MediaElement",
    2
  );
  assert.equal(harness.contexts.length, 1, "reopen remains lazy until play");
  await reopenedPlayback.play();

  assert.equal(harness.contexts.length, 2);
  assert.equal(harness.sources.length, 2);
  assert.equal(harness.gains.length, 2);
  assert.notEqual(harness.contexts[1], firstContext);
  assert.notEqual(harness.sources[1], firstSource);
  assert.notEqual(harness.gains[1], firstGain);
  assert.equal(harness.gains[1].gain.value, 2);

  reopenedPlayback.destroy();
  assert.equal(harness.contexts[1].closeCalls, 1);
});

test("WebAudio preserves direct WaveSurfer gain and resumes its existing context without a media bridge", async (t) => {
  const harness = installAudioHarness(t);
  const resumeGate = deferred();
  const existingContext = {
    state: "suspended",
    resumeCalls: 0,
    closeCalls: 0,
    resume() {
      this.resumeCalls += 1;
      return resumeGate.promise;
    },
    close() {
      this.closeCalls += 1;
      return Promise.resolve();
    },
  };
  let activationOpen = true;
  const player = createPlayer({
    media: {
      audioContext: existingContext,
      currentTime: 0,
      paused: true,
      volume: 1,
    },
    activationOpen: () => activationOpen,
  });
  const playback = createWaveformPreviewPlayback(player, "WebAudio", 2);

  assert.equal(playback.backend, "WebAudio");
  assert.equal(player.media.volume, 2, "WebAudio gain remains direct");
  assert.equal(harness.contexts.length, 0);
  assert.equal(harness.sources.length, 0);
  assert.equal(harness.gains.length, 0);

  const play = playback.play();
  activationOpen = false;
  assert.deepEqual(player.activationAtPlay, [true]);
  assert.equal(player.playCalls, 1);
  assert.equal(existingContext.resumeCalls, 1);

  let completed = false;
  void play.then(() => {
    completed = true;
  });
  await Promise.resolve();
  assert.equal(completed, false);
  existingContext.state = "running";
  resumeGate.resolve();
  await play;
  assert.equal(completed, true);

  for (const volume of [0, 1, 2]) playback.setVolume(volume);
  assert.deepEqual(player.volumeAssignments.slice(-3), [0, 1, 2]);
  assert.equal(harness.contexts.length, 0);
  assert.equal(harness.sources.length, 0);
  assert.equal(harness.gains.length, 0);

  playback.destroy();
  assert.equal(existingContext.closeCalls, 0, "WaveSurfer owns its context");
});

test("a rejected context resume rejects play instead of reporting completion", async (t) => {
  const resumeGate = deferred();
  const harness = installAudioHarness(t, {
    contextState: "suspended",
    resume() {
      return resumeGate.promise;
    },
  });
  const player = createPlayer({ enforceNativeVolume: true });
  const playback = createWaveformPreviewPlayback(player, "MediaElement", 1);
  let completionReports = 0;

  const play = playback.play().then(() => {
    completionReports += 1;
  });
  assert.equal(player.playCalls, 1);
  resumeGate.reject(new Error("audio activation denied"));
  await assert.rejects(play, /audio activation denied/);

  assert.equal(completionReports, 0);
  assert.equal(harness.contexts[0].state, "suspended");
  playback.destroy();
});

test("controller play cooperates with editor-owned seek, pause, region stop, and progress", async (t) => {
  const harness = installAudioHarness(t);
  const listeners = new Map();
  const media = { currentTime: 0, duration: 10, paused: true, volume: 1 };
  const volumeAssignments = [];
  let playing = false;
  let playCalls = 0;
  let pauseCalls = 0;
  let seekCalls = 0;

  function emit(event, value) {
    for (const listener of listeners.get(event) ?? []) listener(value);
  }

  const transport = {
    duration: media.duration,
    getMediaElement() {
      return media;
    },
    setVolume(volume) {
      assert.ok(volume >= 0 && volume <= 1);
      volumeAssignments.push(volume);
      media.volume = volume;
    },
    play() {
      playCalls += 1;
      playing = true;
      media.paused = false;
      emit("play");
      return Promise.resolve();
    },
    pause() {
      if (!playing) return;
      pauseCalls += 1;
      playing = false;
      media.paused = true;
      emit("pause");
    },
    isPlaying() {
      return playing;
    },
    getCurrentTime() {
      return media.currentTime;
    },
    setTime(time) {
      seekCalls += 1;
      media.currentTime = time;
      emit("timeupdate", time);
    },
    on(event, listener) {
      const eventListeners = listeners.get(event) ?? [];
      eventListeners.push(listener);
      listeners.set(event, eventListeners);
    },
  };

  const region = { start: 2, end: 4 };
  let playStopAt = region.end;
  let displayedTime = 0;
  let renderedProgress = 0;
  let pauseEvents = 0;
  transport.on("pause", () => {
    pauseEvents += 1;
  });
  transport.on("timeupdate", (currentTime) => {
    displayedTime = currentTime;
    renderedProgress = currentTime / transport.duration;
    if (playStopAt !== null && currentTime >= playStopAt) {
      playStopAt = null;
      if (transport.isPlaying()) transport.pause();
    }
  });

  const playback = createWaveformPreviewPlayback(
    transport,
    "MediaElement",
    0.8
  );
  transport.setTime(region.start);
  await playback.play();
  assert.equal(transport.getCurrentTime(), 2);
  assert.equal(transport.isPlaying(), true);
  assert.equal(playCalls, 1);
  assert.equal(seekCalls, 1);

  transport.setTime(3.25);
  assert.equal(displayedTime, 3.25);
  assert.equal(renderedProgress, 0.325);
  assert.equal(transport.isPlaying(), true);

  transport.setTime(region.end);
  assert.equal(displayedTime, 4);
  assert.equal(renderedProgress, 0.4);
  assert.equal(transport.isPlaying(), false);
  assert.equal(media.paused, true);
  assert.equal(pauseCalls, 1);
  assert.equal(pauseEvents, 1);
  assert.equal(harness.sources.length, 1);
  assert.equal(harness.gains.length, 1);
  assert.ok(volumeAssignments.every((volume) => volume <= 1));

  playback.destroy();
});
