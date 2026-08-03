import assert from "node:assert/strict";
import { registerHooks } from "node:module";
import test from "node:test";

const configModule =
  "data:text/javascript," +
  encodeURIComponent(
    'export const SOUNDS_API_PATH = "/api/sounds"; export const SOUNDS_PATH = "/sounds";'
  );
const utilsModule =
  "data:text/javascript," +
  encodeURIComponent(`
    export function parseInteger(value) {
      if (value === null) return undefined;
      const parsed = typeof value === "number" ? Math.floor(value) : parseInt(value, 10);
      return Number.isNaN(parsed) ? undefined : parsed;
    }
    export function scheduleBackgroundTask(task) { queueMicrotask(task); }
  `);

registerHooks({
  resolve(specifier, context, nextResolve) {
    if (specifier === "config") return { url: configModule, shortCircuit: true };
    if (specifier === "utils") return { url: utilsModule, shortCircuit: true };
    return nextResolve(specifier, context);
  },
});

let moduleSequence = 0;

function deferred() {
  let resolve;
  let reject;
  const promise = new Promise((resolvePromise, rejectPromise) => {
    resolve = resolvePromise;
    reject = rejectPromise;
  });
  return { promise, resolve, reject };
}

function sound(name, overrides = {}) {
  return {
    name,
    audio_path: `${name}.ogg`,
    source_url: null,
    source_title: null,
    source_duration: null,
    trim_start: null,
    trim_end: null,
    volume: 0,
    created: null,
    modified: "2026-08-02T12:00:00Z",
    aliases: [],
    discord_plays: 0,
    twitch_plays: 0,
    web_plays: 0,
    discord_clips: 0,
    is_legacy: false,
    has_video: false,
    ...overrides,
  };
}

function audioBuffer(mebibytes = 1, duration = 10) {
  return {
    length: (mebibytes * 1024 * 1024) / (2 * Float32Array.BYTES_PER_ELEMENT),
    numberOfChannels: 2,
    duration,
  };
}

async function settle() {
  await new Promise((resolve) => setImmediate(resolve));
  await new Promise((resolve) => setImmediate(resolve));
}

async function loadAudioModule(options = {}) {
  const stored = new Map();
  if (options.storedVolume !== undefined) {
    stored.set("volume", String(options.storedVolume));
  }
  const slider = { value: "100" };
  const counters = [];
  const audioFetches = [];
  const sources = [];
  const mediaElements = [];
  const mediaSources = [];
  const gains = [];
  const contexts = [];
  const encodedBuffers = new Map();
  let encodedSequence = 0;

  const scenario = {
    currentTime: 0,
    decodeCalls: 0,
    audioFetches,
    counters,
    sources,
    gains,
    mediaElements,
    mediaSources,
    resumeCalls: 0,
    mediaPlayCalls: 0,
    fetchAudio:
      options.fetchAudio ??
      (async (url) => {
        const encoded = new ArrayBuffer(1);
        encodedBuffers.set(encoded, audioBuffer());
        return { ok: true, status: 200, arrayBuffer: async () => encoded };
      }),
    decodeAudio:
      options.decodeAudio ??
      (async (encoded) => {
        const decoded = encodedBuffers.get(encoded);
        if (!decoded) throw new Error("No decoded test buffer registered");
        return decoded;
      }),
    responseFor(buffer) {
      const encoded = new ArrayBuffer(++encodedSequence);
      encodedBuffers.set(encoded, buffer);
      return { ok: true, status: 200, arrayBuffer: async () => encoded };
    },
  };

  class FakeGainNode {
    constructor() {
      this.gain = { value: 1 };
      this.connected = null;
      this.disconnected = false;
      gains.push(this);
    }

    connect(target) {
      this.connected = target;
      return target;
    }

    disconnect() {
      this.disconnected = true;
    }
  }

  class FakeBufferSourceNode {
    constructor() {
      this.buffer = null;
      this.connected = null;
      this.started = false;
      this.stopped = false;
      this.disconnected = false;
      this.onended = null;
      sources.push(this);
    }

    connect(target) {
      this.connected = target;
      return target;
    }

    disconnect() {
      this.disconnected = true;
    }

    start() {
      assert.ok(this.buffer, "a decoded AudioBuffer must be assigned before start");
      this.started = true;
    }

    stop() {
      this.stopped = true;
    }

    finish() {
      this.onended?.(new Event("ended"));
    }
  }

  class FakeAudioElement extends EventTarget {
    constructor() {
      super();
      this.src = "";
      this.preload = "";
      this.paused = true;
      this.currentTime = 0;
      this.duration = options.mediaDuration ?? 10;
      this.onended = null;
      this.onerror = null;
      mediaElements.push(this);
    }

    play() {
      scenario.mediaPlayCalls += 1;
      this.paused = false;
      if (options.playMedia) return options.playMedia(this, scenario);
      return Promise.resolve();
    }

    pause() {
      this.paused = true;
    }

    removeAttribute(name) {
      if (name === "src") this.src = "";
    }

    load() {}

    finish() {
      this.paused = true;
      this.onended?.(new Event("ended"));
    }

    fail() {
      this.paused = true;
      this.onerror?.(new Event("error"));
    }
  }

  class FakeMediaElementSourceNode {
    constructor(media) {
      this.mediaElement = media;
      this.connected = null;
      this.disconnected = false;
      mediaSources.push(this);
    }

    connect(target) {
      this.connected = target;
      return target;
    }

    disconnect() {
      this.disconnected = true;
    }
  }

  class FakeAudioContext {
    constructor() {
      this.destination = { kind: "destination" };
      this.state = options.contextState ?? "running";
      contexts.push(this);
    }

    get currentTime() {
      return scenario.currentTime;
    }

    createBufferSource() {
      return new FakeBufferSourceNode();
    }

    createGain() {
      return new FakeGainNode();
    }
    createMediaElementSource(media) {
      return new FakeMediaElementSourceNode(media);
    }


    decodeAudioData(encoded) {
      scenario.decodeCalls += 1;
      return scenario.decodeAudio(encoded);
    }

    async resume() {
      scenario.resumeCalls += 1;
      if (options.resumeAudio) {
        await options.resumeAudio(this, scenario);
      } else {
        this.state = "running";
      }
    }
  }

  globalThis.document = {
    querySelector(selector) {
      return selector === "input#volume" ? slider : null;
    },
    createElement(tagName) {
      assert.equal(tagName, "audio");
      return new FakeAudioElement();
    },
  };
  globalThis.localStorage = {
    getItem(key) {
      return stored.get(key) ?? null;
    },
    setItem(key, value) {
      stored.set(key, value);
    },
  };
  globalThis.location = { origin: "https://soundbot.test" };
  Object.defineProperty(globalThis, "navigator", {
    configurable: true,
    value: {
      userAgent:
        options.userAgent ??
        "Mozilla/5.0 (X11; Linux x86_64; rv:141.0) Gecko/20100101 Firefox/141.0",
      platform: options.platform ?? "Linux x86_64",
      maxTouchPoints: options.maxTouchPoints ?? 0,
    },
  });
  globalThis.AudioContext = FakeAudioContext;
  globalThis.fetch = async (url, init = {}) => {
    const href = String(url);
    if (init.method === "POST") {
      counters.push(href);
      return { ok: true, status: 204 };
    }
    audioFetches.push(href);
    return scenario.fetchAudio(href, scenario);
  };

  moduleSequence += 1;
  const moduleUrl = new URL(
    `../scripts/audio.ts?audio-test=${moduleSequence}`,
    import.meta.url
  );
  const audio = await import(moduleUrl.href);
  return { audio, scenario, slider, stored, contexts };
}

test("concurrent main and Chaos plays share one decode and preserve live 0-400% gain", async () => {
  const bees = sound("bees");
  const { audio, scenario, slider, stored, contexts } = await loadAudioModule({
    storedVolume: 100,
  });
  const changes = [];

  audio.playMainAudio(bees);
  audio.playButtonAudio(bees, (event) => changes.push(event.type));
  await settle();

  assert.equal(contexts.length, 1, "all playback must share one AudioContext");
  assert.equal(scenario.audioFetches.length, 1);
  assert.equal(scenario.decodeCalls, 1);
  assert.equal(scenario.sources.length, 2, "each accepted play gets a one-shot source");
  assert.equal(
    scenario.mediaElements.length,
    0,
    "desktop Firefox must remain on decoded-buffer playback"
  );
  assert.ok(scenario.sources.every((source) => source.started));
  assert.ok(scenario.gains.every((gain) => gain.gain.value === 1));
  assert.deepEqual(changes, ["play"]);

  audio.setVolume(400);
  assert.equal(audio.getVolume(), 400);
  assert.ok(scenario.gains.every((gain) => gain.gain.value === 4));
  assert.equal(slider.value, "400");
  assert.equal(stored.get("volume"), "400");

  audio.setVolume(900);
  assert.equal(audio.getVolume(), 400, "values above the slider range clamp to 4x");
  assert.ok(scenario.gains.every((gain) => gain.gain.value === 4));
  assert.equal(stored.get("volume"), "400");
  const mainSource = scenario.sources[0];
  const chaosSource = scenario.sources[1];
  audio.stopAllButtonAudio();
  await settle();
  assert.equal(chaosSource.stopped, true);
  assert.equal(mainSource.stopped, false, "stopping Chaos must not corrupt Main");
  assert.equal(audio.isMainAudioActive(bees), true);
  audio.stopMainAudio();
  assert.equal(mainSource.stopped, true);
  assert.equal(scenario.counters.length, 2, "each accepted user play counts once");
});

test("a stale main decode completion never starts over a newer request", async () => {
  const firstResponse = deferred();
  const secondResponse = deferred();
  const first = sound("first");
  const second = sound("second");
  const { audio, scenario } = await loadAudioModule({
    fetchAudio(url, currentScenario) {
      if (url.includes("first.ogg")) return firstResponse.promise;
      return secondResponse.promise;
    },
  });

  audio.playMainAudio(first);
  assert.equal(audio.isMainAudioActive(first), true, "pending playback is toggleable");
  audio.playMainAudio(second);
  assert.equal(audio.isMainAudioActive(first), false);
  assert.equal(audio.isMainAudioActive(second), true);

  secondResponse.resolve(scenario.responseFor(audioBuffer(1, 4)));
  await settle();
  assert.equal(scenario.sources.length, 1);
  assert.strictEqual(scenario.sources[0].buffer.duration, 4);

  firstResponse.resolve(scenario.responseFor(audioBuffer(1, 8)));
  await settle();
  assert.equal(scenario.sources.length, 1, "stale completion must not create a source");
  assert.equal(audio.isMainAudioActive(second), true);
  assert.equal(scenario.counters.length, 2, "stale completion must not double-count");
});

test("Single replacement, stop, progress, ended listeners, and replay stay coherent", async () => {
  const a = sound("single-a");
  const b = sound("single-b");
  const { audio, scenario } = await loadAudioModule();
  const events = [];
  audio.addMainAudioChangeListener((event) => events.push(event.type));

  scenario.currentTime = 10;
  audio.playMainAudio(a);
  await settle();
  scenario.currentTime = 12.5;
  assert.equal(audio.getMainAudioProgress(), 0.25);

  audio.playMainAudio(b);
  await settle();
  assert.equal(scenario.sources[0].stopped, true, "replacement stops the old voice");
  assert.equal(audio.isMainAudioActive(a), false);
  assert.equal(audio.isMainAudioActive(b), true);

  audio.stopMainAudio();
  await settle();
  assert.equal(scenario.sources[1].stopped, true);
  assert.equal(audio.isMainAudioActive(), false);
  assert.equal(audio.getMainAudioProgress(), 0);

  audio.playMainAudio(b);
  await settle();
  assert.equal(scenario.sources.length, 3, "replay uses a fresh one-shot source");
  scenario.sources[2].finish();
  await settle();
  assert.equal(audio.isMainAudioActive(), false);
  assert.equal(audio.getMainAudioProgress(), 0);
  assert.deepEqual(events, ["play", "pause", "play", "pause", "play", "ended"]);
  assert.equal(scenario.counters.length, 3);
});

test("Chaos overlaps fresh voices and stop-all cancels active and pending plays", async () => {
  const chaos = sound("chaos");
  const delayed = sound("delayed");
  const delayedResponse = deferred();
  const { audio, scenario } = await loadAudioModule({
    fetchAudio(url, currentScenario) {
      if (url.includes("delayed.ogg")) return delayedResponse.promise;
      return Promise.resolve(currentScenario.responseFor(audioBuffer(2, 3)));
    },
  });
  const events = [];

  audio.playButtonAudio(chaos, (event) => events.push(`one:${event.type}`));
  audio.playButtonAudio(chaos, (event) => events.push(`two:${event.type}`));
  audio.playButtonAudio(chaos, (event) => events.push(`three:${event.type}`));
  await settle();

  assert.equal(scenario.audioFetches.filter((url) => url.includes("chaos.ogg")).length, 1);
  assert.equal(scenario.decodeCalls, 1);
  assert.equal(scenario.sources.length, 3);
  assert.equal(audio.getActiveButtonAudioGroups(chaos).get(chaos).length, 3);

  audio.playButtonAudio(delayed, (event) => events.push(`pending:${event.type}`));
  assert.equal(audio.getActiveButtonAudioGroups(delayed).size, 1);
  audio.stopAllButtonAudio();
  await settle();
  assert.ok(scenario.sources.every((source) => source.stopped));
  assert.equal(audio.getActiveButtonAudioGroups().size, 0);
  assert.ok(events.includes("pending:pause"));

  delayedResponse.resolve(scenario.responseFor(audioBuffer()));
  await settle();
  assert.equal(scenario.sources.length, 3, "cancelled pending Chaos play never starts");
  assert.equal(scenario.counters.length, 4, "accepted clicks count once, independent of completion");
});

test("the 64 MiB decoded LRU evicts least-recently-used inactive buffers", async () => {
  const a = sound("cache-a");
  const b = sound("cache-b");
  const c = sound("cache-c");
  const fetchCounts = new Map();
  const { audio, scenario } = await loadAudioModule({
    fetchAudio(url, currentScenario) {
      fetchCounts.set(url, (fetchCounts.get(url) ?? 0) + 1);
      return Promise.resolve(currentScenario.responseFor(audioBuffer(24, 5)));
    },
  });

  for (const item of [a, b]) {
    audio.playMainAudio(item);
    await settle();
    audio.stopMainAudio();
  }
  audio.playMainAudio(a);
  await settle();
  audio.stopMainAudio();
  audio.playMainAudio(c);
  await settle();
  audio.stopMainAudio();
  audio.playMainAudio(b);
  await settle();

  const aUrl = scenario.audioFetches.find((url) => url.includes("cache-a.ogg"));
  const bUrl = scenario.audioFetches.find((url) => url.includes("cache-b.ogg"));
  const cUrl = scenario.audioFetches.find((url) => url.includes("cache-c.ogg"));
  assert.equal(fetchCounts.get(aUrl), 1, "recent cache hit must not refetch");
  assert.equal(fetchCounts.get(cUrl), 1);
  assert.equal(fetchCounts.get(bUrl), 2, "least-recently-used buffer must be evicted");
});

test("active buffers remain reusable when pinned voices fill the LRU", async () => {
  const largeMain = sound("large-main");
  const overlapping = sound("large-overlap");
  const fetchCounts = new Map();
  const { audio, scenario } = await loadAudioModule({
    fetchAudio(url, currentScenario) {
      fetchCounts.set(url, (fetchCounts.get(url) ?? 0) + 1);
      const size = url.includes("large-main.ogg") ? 48 : 24;
      return Promise.resolve(currentScenario.responseFor(audioBuffer(size, 20)));
    },
  });

  audio.playMainAudio(largeMain);
  await settle();
  audio.playButtonAudio(overlapping, () => {});
  await settle();
  audio.playButtonAudio(overlapping, () => {});
  await settle();

  const overlapUrl = scenario.audioFetches.find((url) =>
    url.includes("large-overlap.ogg")
  );
  assert.equal(
    fetchCounts.get(overlapUrl),
    1,
    "an active buffer outside the full LRU must not be decoded again"
  );
  assert.equal(
    audio.getActiveButtonAudioGroups(overlapping).get(overlapping).length,
    2
  );
  audio.stopAllButtonAudio();
  audio.stopMainAudio();
});

test("iOS WebKit uses the boosted media bridge with shared context and full lifecycle", async () => {
  const main = sound("ios-main");
  const chaos = sound("ios-chaos");
  const { audio, scenario, contexts } = await loadAudioModule({
    storedVolume: 400,
    contextState: "suspended",
    mediaDuration: 8,
    userAgent:
      "Mozilla/5.0 (iPhone; CPU iPhone OS 18_6 like Mac OS X) AppleWebKit/605.1.15 CriOS/138.0 Mobile/15E148 Safari/604.1",
    platform: "iPhone",
    maxTouchPoints: 5,
  });
  const mainEvents = [];
  const chaosEvents = [];
  audio.addMainAudioChangeListener((event) => mainEvents.push(event.type));

  audio.playMainAudio(main);
  audio.playButtonAudio(chaos, (event) => chaosEvents.push(`one:${event.type}`));
  audio.playButtonAudio(chaos, (event) => chaosEvents.push(`two:${event.type}`));
  await settle();

  assert.equal(contexts.length, 1, "both media paths share one bounded AudioContext");
  assert.equal(scenario.audioFetches.length, 0, "iOS selection happens before Web Audio decode");
  assert.equal(scenario.decodeCalls, 0);
  assert.equal(scenario.sources.length, 0);
  assert.equal(scenario.mediaElements.length, 3);
  assert.equal(scenario.mediaSources.length, 3);
  assert.equal(scenario.mediaPlayCalls, 3, "each accepted play starts exactly once");
  assert.ok(scenario.gains.every((gain) => gain.gain.value === 4));
  assert.deepEqual(mainEvents, ["play"]);
  assert.deepEqual(chaosEvents, ["one:play", "two:play"]);
  assert.equal(scenario.counters.length, 3);

  scenario.mediaElements[0].currentTime = 4;
  assert.equal(audio.getMainAudioProgress(), 0.5);
  audio.setVolume(275);
  assert.ok(scenario.gains.every((gain) => gain.gain.value === 2.75));

  scenario.mediaElements[1].fail();
  await settle();
  assert.equal(audio.getActiveButtonAudioGroups(chaos).get(chaos).length, 1);

  audio.stopAllButtonAudio();
  await settle();
  assert.equal(scenario.mediaElements[0].paused, false);
  assert.ok(scenario.mediaElements.slice(1).every((element) => element.paused));
  assert.deepEqual(chaosEvents, [
    "one:play",
    "two:play",
    "one:pause",
    "two:pause",
  ]);

  scenario.mediaElements[0].finish();
  await settle();
  assert.equal(audio.isMainAudioActive(), false);
  assert.deepEqual(mainEvents, ["play", "ended"]);
});

test("touch-capable iPadOS desktop mode also selects the media bridge", async () => {
  const item = sound("ipad");
  const { audio, scenario } = await loadAudioModule({
    userAgent:
      "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15) AppleWebKit/605.1.15 Version/18.6 Safari/605.1.15",
    platform: "MacIntel",
    maxTouchPoints: 5,
  });
  const events = [];
  audio.addMainAudioChangeListener((event) => events.push(event.type));

  audio.playMainAudio(item);
  await settle();
  assert.equal(scenario.mediaElements.length, 1);
  assert.equal(scenario.sources.length, 0);
  assert.equal(scenario.counters.length, 1);
  scenario.mediaElements[0].fail();
  await settle();
  assert.equal(audio.isMainAudioActive(), false);
  assert.deepEqual(events, ["play", "pause"]);
  assert.equal(scenario.mediaSources[0].disconnected, true);
});

test("decode failure falls back to one boosted media start without double counting", async () => {
  const main = sound("fallback-main");
  const chaos = sound("fallback-chaos");
  const { audio, scenario } = await loadAudioModule({
    decodeAudio: async () => {
      throw new Error("codec unavailable");
    },
  });
  const mainEvents = [];
  const chaosEvents = [];
  audio.addMainAudioChangeListener((event) => mainEvents.push(event.type));

  audio.playMainAudio(main);
  audio.playButtonAudio(chaos, (event) => chaosEvents.push(event.type));
  await settle();

  assert.equal(scenario.decodeCalls, 2);
  assert.equal(scenario.sources.length, 0);
  assert.equal(scenario.mediaElements.length, 2);
  assert.equal(scenario.mediaPlayCalls, 2, "fallback starts once per accepted request");
  assert.equal(scenario.counters.length, 2, "fallback never records a second play");
  assert.deepEqual(mainEvents, ["play"]);
  assert.deepEqual(chaosEvents, ["play"]);

  audio.setVolume(400);
  assert.ok(scenario.gains.every((gain) => gain.gain.value === 4));
  audio.stopMainAudio();
  audio.stopAllButtonAudio();
  await settle();
  assert.deepEqual(mainEvents, ["play", "pause"]);
  assert.deepEqual(chaosEvents, ["play", "pause"]);
  assert.ok(scenario.mediaElements.every((element) => element.paused));
  assert.ok(scenario.mediaSources.every((source) => source.disconnected));
});

test("cancelled decode failures cannot start a stale media fallback", async () => {
  const mainDecode = deferred();
  const chaosDecode = deferred();
  const main = sound("cancel-main");
  const chaos = sound("cancel-chaos");
  const { audio, scenario } = await loadAudioModule({
    decodeAudio(encoded) {
      return scenario.decodeCalls === 1 ? mainDecode.promise : chaosDecode.promise;
    },
  });
  const mainEvents = [];
  const chaosEvents = [];
  audio.addMainAudioChangeListener((event) => mainEvents.push(event.type));

  audio.playMainAudio(main);
  audio.playButtonAudio(chaos, (event) => chaosEvents.push(event.type));
  await settle();
  audio.stopMainAudio();
  audio.stopAllButtonAudio();
  mainDecode.reject(new Error("late main decode failure"));
  chaosDecode.reject(new Error("late Chaos decode failure"));
  await settle();

  assert.equal(scenario.mediaElements.length, 0);
  assert.equal(scenario.mediaPlayCalls, 0);
  assert.equal(scenario.counters.length, 2);
  assert.deepEqual(mainEvents, ["pause"]);
  assert.deepEqual(chaosEvents, ["pause"]);
});

test("a rejected AudioContext unlock never starts or leaks playback", async () => {
  const item = sound("unlock-failure");
  const { audio, scenario } = await loadAudioModule({
    contextState: "suspended",
    resumeAudio: async () => {
      throw new Error("activation denied");
    },
  });
  const events = [];
  audio.addMainAudioChangeListener((event) => events.push(event.type));

  audio.playMainAudio(item);
  await settle();

  assert.equal(scenario.resumeCalls, 1);
  assert.equal(scenario.sources.length, 0);
  assert.equal(scenario.mediaElements.length, 0);
  assert.equal(audio.isMainAudioActive(), false);
  assert.deepEqual(events, ["pause"]);
  assert.equal(scenario.counters.length, 1);
});

test("a versioned URL is the decode-cache identity", async () => {
  const original = sound("versioned", { modified: "2026-08-02T12:00:00Z" });
  const changed = { ...original, modified: "2026-08-02T12:00:01Z" };
  const { audio, scenario } = await loadAudioModule();

  audio.playMainAudio(original);
  await settle();
  audio.stopMainAudio();
  audio.playMainAudio(changed);
  await settle();

  assert.equal(scenario.audioFetches.length, 2);
  assert.notEqual(scenario.audioFetches[0], scenario.audioFetches[1]);
  assert.match(scenario.audioFetches[0], /[?&]v=\d+/);
  assert.match(scenario.audioFetches[1], /[?&]v=\d+/);
});
