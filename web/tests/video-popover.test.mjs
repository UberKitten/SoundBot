import assert from "node:assert/strict";
import { registerHooks } from "node:module";
import test from "node:test";

const moduleUrl = (source) => `data:text/javascript,${encodeURIComponent(source)}`;
let videoModule;
const stubs = new Map([
  ["admin-api", moduleUrl(`
    export function soundVideoUrl(name) {
      return "/api/admin/sounds/" + encodeURIComponent(name) + "/video";
    }
  `)],
  ["auth", moduleUrl(`
    export function isAdmin() { return globalThis.__videoAdmin; }
    export function onAuthChange(callback) { globalThis.__videoAuth = callback; }
  `)],
  ["audio", moduleUrl(`
    export const Sound = undefined;
    export function addMainAudioChangeListener(callback) { globalThis.__audioChange = callback; }
    export function getActiveAudioGroups() { return new Map(); }
    export function getMainAudioProgress() { return 0; }
    export function isMainAudioActive() { return globalThis.__mainActive; }
    export function playMainAudio(sound) {
      globalThis.__mainActive = true;
      return globalThis.__startAudio("main", sound);
    }
    export function playButtonAudio(sound) { return globalThis.__startAudio("chaos", sound); }
    export function stopMainAudio() {
      globalThis.__mainActive = false;
      globalThis.__selectedPlayback.state = "stopped";
    }
  `)],
  ["clipboard", moduleUrl("export function copy() {}")],
  ["context-menu", moduleUrl("export function showContextMenu() {} export function showContextMenuAt() {}")],
  ["long-press", moduleUrl("export function attachLongPress() {}")],
  ["sound-live-update", moduleUrl("export function mergeSoundRepresentation(target, source) { Object.assign(target, source); }")],
]);
registerHooks({
  resolve(specifier, context, nextResolve) {
    if (specifier === "video-popover") return { url: videoModule, shortCircuit: true };
    const stub = stubs.get(specifier);
    return stub ? { url: stub, shortCircuit: true } : nextResolve(specifier, context);
  },
});

class FakeElement extends EventTarget {
  constructor(tag = "div") {
    super();
    this.tagName = tag;
    this.children = [];
    this.attributes = new Map();
    this.classes = new Set();
    this.classList = {
      add: (...names) => names.forEach((name) => this.classes.add(name)),
      remove: (...names) => names.forEach((name) => this.classes.delete(name)),
      contains: (name) => this.classes.has(name),
      toggle: (name, force = !this.classes.has(name)) => {
        if (force) this.classes.add(name);
        else this.classes.delete(name);
        return force;
      },
    };
    this.style = { setProperty() {}, removeProperty() {} };
    this.offsetHeight = 280;
    this.textContent = "";
  }
  set className(value) { this.classes = new Set(value.split(/\s+/)); }
  get className() { return [...this.classes].join(" "); }
  setAttribute(name, value) { this.attributes.set(name, String(value)); }
  getAttribute(name) { return this.attributes.get(name) ?? null; }
  removeAttribute(name) { this.attributes.delete(name); }
  appendChild(child) { child.parent = this; this.children.push(child); return child; }
  replaceChildren(...children) { this.children = []; children.forEach((child) => this.appendChild(child)); }
  contains(child) { return child === this || this.children.some((entry) => entry.contains(child)); }
  remove() { this.parent.children = this.parent.children.filter((child) => child !== this); }
  querySelector(selector) {
    const matches = (child) => selector.startsWith(".")
      ? child.classList.contains(selector.slice(1))
      : selector.startsWith("#") ? child.id === selector.slice(1) : child.tagName === selector;
    for (const child of this.children) {
      if (matches(child)) return child;
      const nested = child.querySelector(selector);
      if (nested) return nested;
    }
    return null;
  }
}

class FakeVideo extends FakeElement {
  constructor() {
    super("video");
    this.paused = true;
    this.currentTime = 0;
    this.readyState = 0;
    this.duration = 10;
    this.playCalls = 0;
    this.loadCalls = 0;
  }
  set src(value) { this.setAttribute("src", value); }
  get src() { return this.getAttribute("src") ?? ""; }
  set currentTime(value) {
    this.seekCalls = (this.seekCalls ?? 0) + 1;
    this.position = value;
  }
  get currentTime() { return this.position; }
  play() { this.playCalls++; this.paused = false; return Promise.resolve(); }
  pause() { this.paused = true; }
  load() { this.loadCalls++; this.readyState = 0; this.currentTime = 0; }
  canplay() { this.readyState = 4; this.dispatchEvent(new Event("canplay")); }
}

let sequence = 0;
async function fixture() {
  const body = new FakeElement("body");
  const videos = [];
  const frames = new Map();
  let nextFrame = 0;
  globalThis.HTMLElement = FakeElement;
  globalThis.document = {
    body,
    createElement(tag) {
      if (tag !== "video") return new FakeElement(tag);
      const video = new FakeVideo();
      videos.push(video);
      return video;
    },
    querySelector: (selector) => body.querySelector(selector),
  };
  globalThis.window = Object.assign(new EventTarget(), { innerWidth: 1200, innerHeight: 800 });
  globalThis.sessionStorage = { getItem() { return null; }, setItem() {} };
  globalThis.requestAnimationFrame = (callback) => { frames.set(++nextFrame, callback); return nextFrame; };
  globalThis.cancelAnimationFrame = (id) => frames.delete(id);
  globalThis.__videoAdmin = true;
  globalThis.__mainActive = false;
  globalThis.__selectedPlayback = undefined;
  globalThis.__startAudio = () => { throw new Error("unexpected audio request"); };
  const id = ++sequence;
  videoModule = new URL(`../scripts/video-popover.ts?video-test=${id}`, import.meta.url).href;
  const video = await import(videoModule);
  const { SoundboardButton } = await import(`../scripts/soundboard-button.ts?video-test=${id}`);
  return {
    video, videos, body, frames, SoundboardButton,
    frame() {
      const callbacks = [...frames.values()];
      frames.clear();
      callbacks.forEach((callback) => callback());
    },
  };
}
const sound = (name = "selected") => ({ name, has_video: true });
const clock = (state = "pending", currentTime = 0) => ({ state, currentTime });

test("a ready video stays paused through canonical fetch/decode delay", async () => {
  const f = await fixture();
  const playback = clock();
  f.video.showClipForSoundClick(sound(), playback);
  const video = f.videos[0];
  assert.equal(video.autoplay, false);
  assert.equal(video.muted, true);
  assert.equal(video.defaultMuted, true);
  video.canplay();
  f.frame();
  assert.equal(video.playCalls, 0, "neither click nor canplay starts visuals before audio");
  playback.state = "playing";
  playback.currentTime = 0.3;
  f.frame();
  assert.equal(video.currentTime, 0.3);
  assert.equal(video.playCalls, 1);
  assert.equal(video.paused, false);
});

test("late video readiness and subsequent buffering catch up to canonical elapsed time", async () => {
  const f = await fixture();
  const playback = clock("playing", 0.1);
  f.video.showClipForSoundClick(sound(), playback);
  const video = f.videos[0];
  playback.currentTime = 1.8;
  f.frame();
  assert.equal(video.playCalls, 0);
  video.canplay();
  assert.equal(video.currentTime, 1.8, "late video must not start its own timeline at zero");
  assert.equal(video.playCalls, 1);
  video.readyState = 2;
  playback.currentTime = 2.6;
  f.frame();
  video.canplay();
  assert.equal(video.currentTime, 2.6, "video buffering must not leave a persistent lag");
  playback.state = "pending";
  f.frame();
  assert.equal(video.paused, true, "canonical media buffering pauses its visual");
  playback.currentTime = 2.9;
  playback.state = "playing";
  f.frame();
  assert.equal(video.currentTime, 2.9);
  assert.equal(video.paused, false);
  playback.state = "stopped";
  f.frame();
  assert.equal(video.currentTime, 0);
  assert.equal(video.paused, true);
  assert.equal(f.frames.size, 0);
  const stoppedSeeks = video.seekCalls;
  video.canplay();
  video.canplay();
  assert.equal(video.seekCalls, stoppedSeeks, "seek readiness events must not start a stopped-video seek loop");
});

test("same-clip Chaos retrigger waits for its own clock and ignores old voice termination", async () => {
  const f = await fixture();
  const older = clock("playing", 2);
  f.video.showClipForSoundClick(sound(), older);
  const video = f.videos[0];
  video.canplay();
  const latest = clock();
  f.video.showClipForSoundClick(sound(), latest);
  assert.equal(video.loadCalls, 1, "same clip restarts without a refetch");
  assert.equal(video.paused, true);
  assert.equal(video.currentTime, 0);
  older.state = "stopped";
  f.frame();
  assert.equal(video.paused, true);
  latest.state = "playing";
  latest.currentTime = 0.4;
  f.frame();
  assert.equal(video.currentTime, 0.4);
  assert.equal(video.paused, false);
  older.state = "playing";
  latest.state = "stopped";
  f.frame();
  assert.equal(video.paused, true, "an older overlapping voice cannot extend the selected visual");
  assert.equal(video.currentTime, 0);
});

test("switching clips before readiness cannot select the old clock", async () => {
  const f = await fixture();
  const old = clock("playing", 4);
  const latest = clock();
  f.video.showClipForSoundClick(sound("old"), old);
  f.video.showClipForSoundClick(sound("new"), latest);
  const video = f.videos[0];
  video.canplay();
  assert.match(video.src, /\/new\/video$/);
  assert.equal(video.playCalls, 0);
  latest.state = "playing";
  latest.currentTime = 0.2;
  f.frame();
  assert.equal(video.currentTime, 0.2);
  assert.equal(f.videos.length, 1);
});

test("hide suppresses automatic opening and Show rejoins the selected audio clock", async () => {
  const f = await fixture();
  f.video.initVideoControl();
  globalThis.__videoAuth({ authenticated: true, can_admin: true });
  const playback = clock("playing", 1);
  f.video.showClipForSoundClick(sound(), playback);
  f.videos[0].canplay();
  const toggle = f.body.querySelector("#admin-video-toggle");
  toggle.dispatchEvent(new Event("click"));
  assert.equal(f.frames.size, 0);
  assert.equal(f.videos[0].src, "");
  const latest = clock("playing", 2.25);
  f.video.showClipForSoundClick(sound("latest"), latest);
  assert.equal(f.videos.length, 1);
  toggle.dispatchEvent(new Event("click"));
  const reopened = f.videos[1];
  reopened.canplay();
  assert.equal(reopened.currentTime, 2.25);
  assert.match(reopened.src, /\/latest\/video$/);
  latest.state = "stopped";
  f.frame();
  assert.equal(reopened.paused, true);
  assert.equal(reopened.currentTime, 0);
});

for (const single of [true, false]) {
  test(`sound button binds the exact ${single ? "Single" : "Chaos"} request before displaying video`, async () => {
    const f = await fixture();
    const selected = sound();
    const playback = clock();
    const calls = [];
    globalThis.__selectedPlayback = playback;
    globalThis.__startAudio = (mode, requestedSound) => {
      calls.push(mode);
      assert.strictEqual(requestedSound, selected);
      assert.equal(f.videos.length, 0, "audio request must be selected before video display");
      return playback;
    };
    const button = new f.SoundboardButton();
    button.sound = selected;
    if (single) button.setAttribute("singleplay", "true");
    button.connectedCallback();
    button.onclick({ currentTarget: button });
    const video = f.videos[0];
    video.canplay();
    assert.deepEqual(calls, [single ? "main" : "chaos"]);
    assert.equal(video.playCalls, 0);
    playback.state = "playing";
    playback.currentTime = 0.5;
    f.frame();
    assert.equal(video.currentTime, 0.5);
    if (single) {
      button.onclick({ currentTarget: button });
      f.frame();
      assert.equal(video.paused, true);
      assert.equal(video.currentTime, 0);
      assert.equal(calls.length, 1, "Single toggle only stops, never starts another voice");
    }
  });
}
