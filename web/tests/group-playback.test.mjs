import assert from "node:assert/strict";
import { readFileSync } from "node:fs";
import { registerHooks } from "node:module";
import test from "node:test";
import ts from "typescript";

const moduleUrl = (source) => `data:text/javascript,${encodeURIComponent(source)}`;
const stubs = new Map([
  ["admin-api", moduleUrl(`
    export function soundVideoUrl(name) {
      return "/api/admin/sounds/" + encodeURIComponent(name) + "/video";
    }
  `)],
  ["auth", moduleUrl(`
    export function isAdmin() { return globalThis.groupVideoAdmin; }
    export function onAuthChange(callback) { globalThis.groupVideoAuth = callback; }
  `)],
  ["clipboard", moduleUrl("export function copy() {}")],
  ["config", moduleUrl(`
    export const GROUPS_API_PATH = "/api/groups";
    export const SOUNDS_API_PATH = "/api/sounds";
    export const SOUNDS_PATH = "/sounds";
    export function getRandomPrefix() { return "!"; }
  `)],
  ["context-menu", moduleUrl(`
    export function showGroupContextMenu() {}
    export function showGroupContextMenuAt() {}
  `)],
  ["dom-init", moduleUrl("export function init() {}")],
  ["long-press", moduleUrl("export function attachLongPress() {}")],
  ["sound-live-update", moduleUrl(`
    export function applySoundLiveUpdate() {}
    export function findSoundInSnapshot() { return null; }
    export function soundMatchesFilter() { return true; }
  `)],
  ["utils", moduleUrl(`
    export function alphaSort() { return 0; }
    export function numericSort() { return 0; }
    export function cancelBackgroundTasks() {}
    export function clearError() {}
    export function clearInfo() {}
    export function fetchJson() { throw new Error("Unexpected API read"); }
    export function getCanonicalString(value) { return value?.toLowerCase(); }
    export function getElement() { return globalThis.document.grid; }
    export function parseInteger(value) {
      if (value === null) return undefined;
      const parsed = typeof value === "number" ? Math.floor(value) : parseInt(value, 10);
      return Number.isNaN(parsed) ? undefined : parsed;
    }
    export function scheduleBackgroundTask(task) { globalThis.scheduleGroupChange(task); }
    export function setError(error) { throw error; }
    export function setInfo() {}
  `)],
  ["websocket", moduleUrl(`
    export const GroupUpdateEvent = undefined;
    export const SoundUpdateEvent = undefined;
    export function onGroupUpdate() { return () => {}; }
    export function onSoundUpdate() { return () => {}; }
  `)],
]);
let audioModuleUrl;
let videoModuleUrl;
let moduleSequence = 0;
registerHooks({
  resolve(specifier, context, nextResolve) {
    if (specifier === "audio") return { url: audioModuleUrl, shortCircuit: true };
    if (specifier === "video-popover") return { url: videoModuleUrl, shortCircuit: true };
    if (specifier === "audio-platform") {
      return {
        url: new URL("../scripts/audio-platform.ts", import.meta.url).href,
        shortCircuit: true,
      };
    }
    const stub = stubs.get(specifier);
    return stub ? { url: stub, shortCircuit: true } : nextResolve(specifier, context);
  },
  load(url, context, nextLoad) {
    const appUrl = new URL("../scripts/soundboard-app.ts", import.meta.url).href;
    if (url.split("?")[0] === appUrl) {
      const { outputText } = ts.transpileModule(readFileSync(new URL(url), "utf8"), {
        compilerOptions: {
          module: ts.ModuleKind.ES2022,
          target: ts.ScriptTarget.ES2022,
        },
        fileName: "soundboard-app.ts",
      });
      return { format: "module", source: outputText, shortCircuit: true };
    }
    return nextLoad(url, context);
  },
});

class FakeClassList {
  values = new Set();
  add(...names) { names.forEach((name) => this.values.add(name)); }
  remove(...names) { names.forEach((name) => this.values.delete(name)); }
  contains(name) { return this.values.has(name); }
  toggle(name, force = !this.contains(name)) {
    if (force) this.add(name);
    else this.remove(name);
    return force;
  }
}

// Only DOM/media boundaries are adapted; group selection, click handling,
// playback generations, fallback, counting and events use production modules.
class FakeElement extends EventTarget {
  constructor(tagName = "div") {
    super();
    this.tagName = tagName;
    this.attributes = new Map();
    this.children = [];
    this.dataset = {};
    this.classList = new FakeClassList();
    const properties = new Map();
    this.style = {
      setProperty: (name, value) => properties.set(name, value),
      removeProperty: (name) => properties.delete(name),
      getPropertyValue: (name) => properties.get(name) ?? "",
    };
  }
  set className(value) { this.classList.values = new Set(value.split(/\s+/).filter(Boolean)); }
  get className() { return [...this.classList.values].join(" "); }
  set innerHTML(value) {
    this.children = [...value.matchAll(/<(?:span|svg) class="([^"]+)"/g)].map((match) => {
      const child = new FakeElement();
      child.className = match[1];
      return child;
    });
  }
  setAttribute(name, value) { this.attributes.set(name, String(value)); }
  getAttribute(name) { return this.attributes.get(name) ?? null; }
  removeAttribute(name) { this.attributes.delete(name); }
  querySelector(selector) {
    for (const child of this.children) {
      const matches = selector.startsWith(".")
        ? child.classList.contains(selector.slice(1))
        : selector.startsWith("#") ? child.id === selector.slice(1) : child.tagName === selector;
      if (matches) return child;
      const nested = child.querySelector(selector);
      if (nested) return nested;
    }
    return null;
  }
  appendChild(child) { child.parentElement = this; this.children.push(child); return child; }
  contains(child) { return this === child || this.children.some((entry) => entry.contains(child)); }
  insertBefore(child, before) {
    child.parentElement = this;
    this.children.splice(this.children.indexOf(before), 0, child);
    return child;
  }
  remove() {
    if (this.parentElement) {
      const siblings = this.parentElement.children;
      siblings.splice(siblings.indexOf(this), 1);
    }
  }
  click() { this.dispatchEvent(new Event("click")); }
}

function sound(name, overrides = {}) {
  return {
    name, audio_path: `${name}.ogg`, duration: 10, source_url: null,
    source_title: null, source_duration: null, trim_start: null, trim_end: null,
    volume: 0, created: null, modified: "2026-08-02T12:00:00Z", aliases: [],
    discord_plays: 0, twitch_plays: 0, web_plays: 0, discord_clips: 0,
    is_legacy: false, has_video: false, ...overrides,
  };
}
function group(name, members) {
  return { name, members, created: null, discord_plays: 0, twitch_plays: 0, web_plays: 0 };
}
function deferred() {
  let resolve;
  let reject;
  const promise = new Promise((yes, no) => { resolve = yes; reject = no; });
  return { promise, resolve, reject };
}
const decodedBuffer = () => ({ length: 48000, numberOfChannels: 2, duration: 10 });
async function settle() {
  await new Promise((resolve) => setImmediate(resolve));
  await new Promise((resolve) => setImmediate(resolve));
}

async function fixture(t, options = {}) {
  const scenario = { posts: [], fetches: [], sources: [], media: [], videos: [], frames: new Map(), changes: [], time: 0 };
  globalThis.scheduleGroupChange = options.deferChanges
    ? (task) => scenario.changes.push(task)
    : (task) => queueMicrotask(task);
  let nextFrame = 0;
  class FakeSource {
    started = false;
    stopped = false;
    connect() {}
    disconnect() {}
    start() { assert.ok(this.buffer); this.started = true; }
    stop() { this.stopped = true; }
    finish() { this.onended?.(new Event("ended")); }
  }
  class FakeMedia extends EventTarget {
    constructor() {
      super();
      this.paused = true;
      this.currentTime = 0;
      this.duration = 10;
      this.readyState = 4;
      scenario.media.push(this);
    }
    play() {
      this.paused = false;
      return options.playMedia?.(this) ?? Promise.resolve();
    }
    pause() { this.paused = true; }
    removeAttribute(name) { if (name === "src") this.src = ""; }
    load() {}
    finish() { this.paused = true; this.onended?.(new Event("ended")); }
    fail() { this.paused = true; this.onerror?.(new Event("error")); }
  }
  class FakeVideo extends FakeElement {
    constructor() {
      super("video");
      this.paused = true;
      this.currentTime = 0;
      this.duration = 10;
      this.readyState = 0;
      scenario.videos.push(this);
    }
    set src(value) { this.setAttribute("src", value); }
    get src() { return this.getAttribute("src") ?? ""; }
    play() { this.paused = false; return Promise.resolve(); }
    pause() { this.paused = true; }
    load() { this.readyState = 0; this.currentTime = 0; }
    canplay() { this.readyState = 4; this.dispatchEvent(new Event("canplay")); }
  }
  class FakeAudioContext {
    state = "running";
    destination = {};
    get currentTime() { return scenario.time; }
    createBufferSource() {
      const source = new FakeSource();
      scenario.sources.push(source);
      return source;
    }
    createGain() { return { gain: { value: 1 }, connect() {}, disconnect() {} }; }
    createMediaElementSource() { return { connect() {}, disconnect() {} }; }
    decodeAudioData(encoded) { return options.decodeAudio?.(encoded) ?? Promise.resolve(decodedBuffer()); }
  }
  globalThis.HTMLElement = FakeElement;
  const documentEvents = new EventTarget();
  globalThis.document = {
    grid: new FakeElement(),
    body: new FakeElement("body"),
    querySelector(selector) { return this.body.querySelector(selector); },
    createElement(tag) {
      if (tag === "audio") return new FakeMedia();
      if (tag === "video") return new FakeVideo();
      return new FakeElement(tag);
    },
    addEventListener: documentEvents.addEventListener.bind(documentEvents),
    removeEventListener: documentEvents.removeEventListener.bind(documentEvents),
  };
  globalThis.localStorage = { getItem() { return null; }, setItem() {} };
  globalThis.location = { origin: "https://soundbot.test" };
  globalThis.window = Object.assign(new EventTarget(), {
    location: { href: "https://soundbot.test/", search: "" }, innerWidth: 1200, innerHeight: 800,
  });
  globalThis.sessionStorage = { getItem() { return null; }, setItem() {} };
  globalThis.groupVideoAdmin = options.admin ?? true;
  globalThis.history = { replaceState() {} };
  Object.defineProperty(globalThis, "navigator", {
    configurable: true,
    value: options.mediaEngine
      ? { userAgent: "Mozilla/5.0 (iPhone; CPU iPhone OS 18_0 like Mac OS X) AppleWebKit/605.1.15 Version/18.0 Mobile Safari/604.1", platform: "iPhone", maxTouchPoints: 5 }
      : { userAgent: "Mozilla/5.0 Firefox/141.0", platform: "Linux x86_64", maxTouchPoints: 0 },
  });
  globalThis.AudioContext = FakeAudioContext;
  globalThis.requestAnimationFrame = (callback) => {
    scenario.frames.set(++nextFrame, callback);
    return nextFrame;
  };
  globalThis.cancelAnimationFrame = (id) => scenario.frames.delete(id);
  globalThis.fetch = async (url, init = {}) => {
    if (init.method === "POST") {
      scenario.posts.push(String(url));
      return { ok: true, status: 204 };
    }
    scenario.fetches.push(String(url));
    return { ok: true, status: 200, arrayBuffer: async () => new ArrayBuffer(1) };
  };
  const sequence = ++moduleSequence;
  audioModuleUrl = new URL(`../scripts/audio.ts?group-test=${sequence}`, import.meta.url).href;
  videoModuleUrl = new URL(`../scripts/video-popover.ts?group-test=${sequence}`, import.meta.url).href;
  const video = await import(videoModuleUrl);
  const audio = await import(audioModuleUrl);
  const { SoundboardApp } = await import(
    new URL(`../scripts/soundboard-app.ts?group-test=${sequence}`, import.meta.url).href
  );
  const app = new SoundboardApp();
  t.after(async () => {
    audio.stopMainAudio();
    document.body.querySelector(".video-player-close")?.click();
    await settle();
    scenario.frames.clear();
  });
  return { app, audio, video, scenario };
}

function assertIdle(button) {
  assert.equal(button.classList.contains("single-playing"), false);
  assert.equal(button.style.getPropertyValue("--progress"), "");
  assert.equal(button.dataset.playingSound, undefined);
}
function assertPlaying(button, name) {
  assert.equal(button.classList.contains("single-playing"), true);
  assert.equal(button.dataset.playingSound, name);
}
function seedGroup(app, name = "mix") {
  const first = sound("first");
  const second = sound("second");
  const mix = group(name, [first.name, second.name]);
  app.sounds = [first, second];
  app.groups = [mix];
  app.groupShuffleBags.set(mix.name, [second.name, first.name]);
  return { first, second, mix, button: app.createGroupButton(mix) };
}

test("group play-stop-play preserves the shuffle bag and both counters on stop", async (t) => {
  const { app, audio, scenario } = await fixture(t);
  const { button, mix } = seedGroup(app);
  button.click();
  await settle();
  assertPlaying(button, "first");
  assert.equal(scenario.sources[0].started, true);
  assert.deepEqual(scenario.posts, ["/api/sounds/first/play", "/api/groups/mix/play"]);
  const bag = [...app.groupShuffleBags.get(mix.name)];
  scenario.time = 4;
  const frames = [...scenario.frames.values()];
  scenario.frames.clear();
  frames.forEach((callback) => callback());
  assert.equal(button.style.getPropertyValue("--progress"), "40%");
  button.click();
  await settle();
  assert.equal(audio.isMainAudioActive(), false);
  assert.equal(scenario.sources[0].stopped, true);
  assertIdle(button);
  assert.equal(scenario.frames.size, 0);
  assert.deepEqual(app.groupShuffleBags.get(mix.name), bag);
  assert.deepEqual(scenario.posts, ["/api/sounds/first/play", "/api/groups/mix/play"]);
  button.click();
  await settle();
  assertPlaying(button, "second");
  assert.equal(scenario.sources.length, 2);
  assert.deepEqual(scenario.posts, [
    "/api/sounds/first/play", "/api/groups/mix/play",
    "/api/sounds/second/play", "/api/groups/mix/play",
  ]);
});

for (const lateResult of ["resolve", "reject"]) {
  test(`pending group click cancels before decode ${lateResult} without consuming another member`, async (t) => {
    const pending = deferred();
    let decodes = 0;
    const { app, audio, scenario } = await fixture(t, {
      decodeAudio: () => ++decodes === 1 ? pending.promise : Promise.resolve(decodedBuffer()),
    });
    const { button, mix } = seedGroup(app);
    button.click();
    button.click();
    await settle();
    assert.equal(audio.isMainAudioActive(), false);
    assertIdle(button);
    assert.deepEqual(app.groupShuffleBags.get(mix.name), ["second"]);
    assert.equal(scenario.posts.length, 2);
    button.click();
    await settle();
    assertPlaying(button, "second");
    if (lateResult === "resolve") pending.resolve(decodedBuffer());
    else pending.reject(new Error("late cancelled decode"));
    await settle();
    assert.equal(scenario.sources.length, 1, "cancelled generation cannot start a buffer voice");
    assert.equal(scenario.media.length, 0, "cancelled rejection cannot start fallback");
    assertPlaying(button, "second");
    assert.equal(scenario.posts.length, 4);
  });
}

test("natural end clears the group indicator and the next click starts playback", async (t) => {
  const { app, scenario } = await fixture(t);
  const { button } = seedGroup(app);
  button.click();
  await settle();
  scenario.sources[0].finish();
  await settle();
  assertIdle(button);
  assert.equal(scenario.frames.size, 0);
  button.click();
  await settle();
  assertPlaying(button, "second");
  assert.equal(scenario.sources.length, 2);
});

test("total decode and media failure clears ownership so the next click retries", async (t) => {
  let rejectMedia = true;
  const { app, audio, scenario } = await fixture(t, {
    decodeAudio: async () => { throw new Error("unsupported codec"); },
    playMedia: async () => { if (rejectMedia) throw new Error("media failed"); },
  });
  const { button } = seedGroup(app);
  button.click();
  await settle();
  assert.equal(audio.isMainAudioActive(), false);
  assertIdle(button);
  assert.equal(scenario.frames.size, 0);
  assert.equal(scenario.media[0].paused, true);
  rejectMedia = false;
  button.click();
  await settle();
  assertPlaying(button, "second");
  assert.equal(scenario.media.length, 2);
  assert.equal(scenario.posts.length, 4);
});

for (const sameMember of [false, true]) {
  test(`group replacement clears only the old indicator (${sameMember ? "same" : "different"} member)`, async (t) => {
    const { app, scenario } = await fixture(t);
    const { first, second, button } = seedGroup(app);
    const replacement = group("replacement", [sameMember ? first.name : second.name]);
    const other = app.createGroupButton(replacement);
    button.click();
    await settle();
    other.click();
    await settle();
    assertIdle(button);
    assertPlaying(other, replacement.members[0]);
    assert.equal(scenario.sources[0].stopped, true);
    assert.equal(scenario.sources[1].stopped, false);
    button.click();
    await settle();
    assertPlaying(button, second.name);
    assertIdle(other);
    assert.equal(scenario.sources.length, 3, "old group click starts a new play, not stop another owner");
  });

  test(`individual replacement invalidates group ownership (${sameMember ? "same Sound object" : "different sound"})`, async (t) => {
    const { app, audio, scenario } = await fixture(t);
    const { first, second, button } = seedGroup(app);
    button.click();
    await settle();
    const individual = audio.playMainAudio(sameMember ? first : second);
    await settle();
    assert.equal(individual.state, "playing");
    assertIdle(button);
    button.click();
    await settle();
    assert.equal(individual.state, "stopped");
    assertPlaying(button, second.name);
    assert.equal(scenario.sources.length, 3);
  });
}

test("global stop clears group ownership and permits a fresh play", async (t) => {
  const { app, audio, scenario } = await fixture(t);
  const { button } = seedGroup(app);
  button.click();
  await settle();
  audio.stopMainAudio();
  await settle();
  assertIdle(button);
  assert.equal(scenario.frames.size, 0);
  assert.equal(scenario.posts.length, 2);
  button.click();
  await settle();
  assertPlaying(button, "second");
});

test("decode fallback media playback toggles, ends, fails and restarts with one count per play", async (t) => {
  const { app, audio, scenario } = await fixture(t, {
    decodeAudio: async () => { throw new Error("use media fallback"); },
  });
  const item = sound("fallback");
  app.sounds = [item];
  const button = app.createGroupButton(group("media", [item.name]));
  button.click();
  await settle();
  assertPlaying(button, item.name);
  button.click();
  await settle();
  assert.equal(scenario.media[0].paused, true);
  assert.equal(audio.isMainAudioActive(), false);
  assertIdle(button);
  assert.equal(scenario.posts.length, 2);
  button.click();
  await settle();
  scenario.media[1].finish();
  await settle();
  assertIdle(button);
  button.click();
  await settle();
  scenario.media[2].fail();
  await settle();
  assertIdle(button);
  button.click();
  await settle();
  assertPlaying(button, item.name);
  assert.equal(scenario.media.length, 4);
  assert.equal(scenario.posts.length, 8);
});

test("global stop cancels pending media play and late resolution cannot revive its indicator", async (t) => {
  const pending = deferred();
  let plays = 0;
  const { app, audio, scenario } = await fixture(t, {
    decodeAudio: async () => { throw new Error("use media fallback"); },
    playMedia: () => ++plays === 1 ? pending.promise : Promise.resolve(),
  });
  const { button } = seedGroup(app);
  button.click();
  await settle();
  assert.equal(scenario.media.length, 1);
  audio.stopMainAudio();
  await settle();
  assertIdle(button);
  button.click();
  await settle();
  assertPlaying(button, "second");
  pending.resolve();
  await settle();
  assert.equal(scenario.media[0].paused, true);
  assertPlaying(button, "second");
  assert.equal(scenario.posts.length, 4);
});

test("dynamically added and deep-linked groups share the toggle factory and exact playback ownership", async (t) => {
  const { app, audio, scenario } = await fixture(t);
  const item = sound("shared");
  const mix = group("linked mix", [item.name]);
  app.sounds = [item];
  app.groups = [mix];
  app.addGroupButton(mix);
  const dynamic = app.grid.children[0];
  dynamic.click();
  await settle();
  assertPlaying(dynamic, item.name);
  globalThis.window.location = {
    href: "https://soundbot.test/?sound=linked%20mix",
    search: "?sound=linked%20mix",
  };
  app.handleDeepLink();
  const overlay = document.body.children[0];
  const deepLinked = overlay.children[0].children[0];
  deepLinked.click();
  await settle();
  assertIdle(dynamic);
  assertPlaying(deepLinked, item.name);
  const posts = [...scenario.posts];
  deepLinked.click();
  await settle();
  assert.equal(audio.isMainAudioActive(), false);
  assertIdle(deepLinked);
  assert.deepEqual(scenario.posts, posts);
  deepLinked.click();
  await settle();
  assertPlaying(deepLinked, item.name);
  overlay.click();
  await settle();
  assertIdle(deepLinked);
  assert.equal(document.body.children.length, 0);
});

function frame(scenario) {
  const callbacks = [...scenario.frames.values()];
  scenario.frames.clear();
  callbacks.forEach((callback) => callback());
}

for (const engine of ["buffer", "fallback", "media"]) {
  for (const replacement of ["standalone", "same sound", "group", "shared group"]) {
    test(`${engine}: frame clears interrupted group before deferred events (${replacement})`, async (t) => {
      const { app, audio, scenario } = await fixture(t, {
        deferChanges: true,
        mediaEngine: engine === "media",
        ...(engine === "fallback" ? {
          decodeAudio: async () => { throw new Error("use fallback"); },
        } : {}),
      });
      const { first, second, button } = seedGroup(app);
      button.click();
      await settle();
      scenario.time = 4;
      scenario.media.forEach((media) => { media.currentTime = 4; });
      frame(scenario);
      assert.equal(button.style.getPropertyValue("--progress"), "40%");
      const member = replacement === "same sound" || replacement === "shared group" ? first : second;
      let other;
      let clock;
      if (replacement.includes("group")) {
        other = app.createGroupButton(group("other", [member.name]));
        other.click();
      } else {
        clock = audio.playMainAudio(member);
      }
      await settle();
      scenario.time = 7;
      scenario.media.at(-1) && (scenario.media.at(-1).currentTime = 3);
      frame(scenario);
      assertIdle(button);
      if (other) {
        assertPlaying(other, member.name);
        assert.equal(other.style.getPropertyValue("--progress"), "30%");
      } else {
        assert.equal(clock.state, "playing");
      }
      assert.equal(scenario.frames.size, other ? 1 : 0);
      scenario.changes.splice(0).forEach((change) => change());
      assertIdle(button);
      if (other) assertPlaying(other, member.name);
      button.click();
      await settle();
      frame(scenario);
      assertPlaying(button, second.name);
      if (other) assertIdle(other);
      else assert.equal(clock.state, "stopped");
      audio.stopMainAudio();
      frame(scenario);
      assertIdle(button);
      assert.equal(scenario.frames.size, 0);
    });
  }

  test(`${engine}: pending replacement, failure and natural end cannot leave a group frame`, async (t) => {
    const pending = deferred();
    let attempts = 0;
    const { app, audio, scenario } = await fixture(t, {
      deferChanges: true,
      mediaEngine: engine === "media",
      decodeAudio: engine === "fallback"
        ? async () => { throw new Error("use fallback"); }
        : () => ++attempts === 2 ? pending.promise : Promise.resolve(decodedBuffer()),
      playMedia: engine === "buffer" ? undefined
        : () => ++attempts === 2 ? pending.promise : Promise.resolve(),
    });
    const { first, second, button } = seedGroup(app);
    button.click();
    await settle();
    const replacement = audio.playMainAudio(second);
    await settle();
    assert.equal(replacement.state, "pending");
    frame(scenario);
    assertIdle(button);
    assert.equal(scenario.frames.size, 0);
    // Retrigger the original member while the replacement is still pending.
    app.groupShuffleBags.set("mix", [first.name]);
    button.click();
    await settle();
    assertPlaying(button, first.name);
    pending.reject(new Error("late replaced request"));
    await settle();
    frame(scenario);
    assertPlaying(button, first.name);
    if (engine === "buffer") scenario.sources.at(-1).finish();
    else scenario.media.at(-1).fail();
    frame(scenario);
    assertIdle(button);
    assert.equal(scenario.frames.size, 0);
    button.click();
    await settle();
    if (engine === "buffer") scenario.sources.at(-1).finish();
    else scenario.media.at(-1).finish();
    frame(scenario);
    assertIdle(button);
    assert.equal(scenario.frames.size, 0);
  });
}

test("group clips open, wait for canonical audio and retarget the same muted viewer", async (t) => {
  const pending = deferred();
  let decodes = 0;
  const { app, scenario } = await fixture(t, {
    decodeAudio: () => ++decodes === 1 ? pending.promise : Promise.resolve(decodedBuffer()),
  });
  const { first, second, button } = seedGroup(app);
  first.has_video = second.has_video = true;
  button.click();
  const visual = scenario.videos[0];
  assert.ok(visual, "the real group handler opens the real viewer");
  assert.match(visual.src, /\/first\/video$/);
  assert.equal(visual.muted, true);
  visual.canplay();
  frame(scenario);
  assert.equal(visual.paused, true, "video cannot run ahead of pending audio");
  pending.resolve(decodedBuffer());
  await settle();
  scenario.time = 2.25;
  frame(scenario);
  assert.equal(visual.currentTime, 2.25);
  assert.equal(visual.paused, false);
  button.click();
  frame(scenario);
  assert.equal(visual.paused, true);
  assert.equal(visual.currentTime, 0);
  assert.equal(scenario.posts.length, 2, "stop does not count or select another member");
  button.click();
  await settle();
  assert.equal(scenario.videos.length, 1, "the viewer is retargeted, not duplicated");
  assert.match(visual.src, /\/second\/video$/);
  scenario.time = 3.5;
  visual.canplay();
  assert.equal(visual.currentTime, 1.25, "retarget follows the new request, not page or old audio time");
  assert.equal(visual.paused, false);
  assert.deepEqual(scenario.posts, [
    "/api/sounds/first/play", "/api/groups/mix/play",
    "/api/sounds/second/play", "/api/groups/mix/play",
  ]);
});

for (const action of ["hide", "close"]) {
  test(`group clip ${action} suppresses reopening but Show rejoins the newest member`, async (t) => {
    const { app, video, scenario } = await fixture(t);
    const { first, second, button } = seedGroup(app);
    first.has_video = second.has_video = true;
    video.initVideoControl();
    globalThis.groupVideoAuth({ authenticated: true, can_admin: true });
    button.click();
    await settle();
    const toggle = document.body.querySelector("#admin-video-toggle");
    const close = document.body.querySelector(".video-player-close");
    (action === "hide" ? toggle : close).click();
    assert.equal(document.body.querySelector(".video-player"), null);
    assert.equal(scenario.videos[0].src, "");
    button.click(); // Stop the first accepted request.
    button.click(); // Select the next member while suppressed.
    await settle();
    assert.equal(scenario.videos.length, 1);
    assert.equal(document.body.querySelector(".video-player"), null);
    scenario.time = 1.75;
    toggle.click();
    const reopened = scenario.videos[1];
    reopened.canplay();
    assert.match(reopened.src, /\/second\/video$/);
    assert.equal(reopened.currentTime, 1.75);
    assert.equal(reopened.paused, false);
  });
}

test("audio-only group member leaves an existing clip selected without creating a visual stream", async (t) => {
  const { app, scenario } = await fixture(t);
  const { first, button } = seedGroup(app);
  first.has_video = true;
  button.click();
  await settle();
  const visual = scenario.videos[0];
  button.click();
  button.click();
  await settle();
  frame(scenario);
  assertPlaying(button, "second");
  assert.equal(scenario.videos.length, 1);
  assert.match(visual.src, /\/first\/video$/);
  assert.equal(visual.paused, true);
  assert.equal(scenario.posts.length, 4);
});

test("non-admin group playback never opens the authenticated viewer", async (t) => {
  const { app, scenario } = await fixture(t, { admin: false });
  const { first, button } = seedGroup(app);
  first.has_video = true;
  button.click();
  await settle();
  assertPlaying(button, "first");
  assert.equal(scenario.sources[0].started, true);
  assert.equal(scenario.videos.length, 0);
});

test("shared group deep-link opens its selected clip through the same canonical handler", async (t) => {
  const { app, scenario } = await fixture(t);
  const { first } = seedGroup(app);
  first.has_video = true;
  window.location = { href: "https://soundbot.test/?sound=mix", search: "?sound=mix" };
  app.handleDeepLink();
  const overlay = document.body.querySelector(".deep-link-overlay");
  const button = overlay.querySelector(".group-button");
  button.click();
  await settle();
  const visual = scenario.videos[0];
  scenario.time = 0.8;
  visual.canplay();
  assert.match(visual.src, /\/first\/video$/);
  assert.equal(visual.currentTime, 0.8);
  assert.equal(visual.paused, false);
  assert.equal(scenario.sources[0].started, true);
});
