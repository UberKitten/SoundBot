import assert from "node:assert/strict";
import { registerHooks } from "node:module";
import test from "node:test";

function moduleUrl(source) {
  return `data:text/javascript,${encodeURIComponent(source)}`;
}

const stubs = new Map([
  [
    "admin-api",
    moduleUrl(`
      export class ApiError extends Error {}
      export async function deleteSound() {}
      export async function patchSound() { return { name: "renamed" }; }
    `),
  ],
  ["modal", moduleUrl("export function openModal() { throw new Error('not used'); }")],
  ["toast", moduleUrl("export function showToast() {}")],
  [
    "audio",
    moduleUrl(`
      export const Sound = undefined;
      export const SoundGroup = undefined;
      export function addMainAudioChangeListener() {}
      export function getActiveAudioGroups() { return new Set(); }
      export function getMainAudioProgress() { return 0; }
      export function isSoundObject() { return true; }
      export function isMainAudioActive() { return false; }
      export function playButtonAudio() {}
      export function playMainAudio() {}
      export function stopMainAudio() {}
    `),
  ],
  ["clipboard", moduleUrl("export function copy() {}")],
  [
    "config",
    moduleUrl(`
      export const GROUPS_API_PATH = "/api/groups";
      export const SOUNDS_API_PATH = "/api/sounds";
      export function getRandomPrefix() { return "!"; }
    `),
  ],
  [
    "context-menu",
    moduleUrl(`
      export function showContextMenu() {}
      export function showContextMenuAt() {}
      export function showGroupContextMenu() {}
      export function showGroupContextMenuAt() {}
    `),
  ],
  ["dom-init", moduleUrl("export function init() {}")],
  ["long-press", moduleUrl("export function attachLongPress() {}")],
  [
    "sound-live-update",
    moduleUrl(`
      export function applySoundLiveUpdate() { return Promise.resolve("edited"); }
      export function findSoundInSnapshot() { return null; }
      export function mergeSoundRepresentation(target, source) { Object.assign(target, source); }
      export function soundMatchesFilter() { return true; }
    `),
  ],
  [
    "utils",
    moduleUrl(`
      export function alphaSort() { return 0; }
      export function cancelBackgroundTasks() {}
      export function clearError() {}
      export function clearInfo() {}
      export async function fetchJson() { return {}; }
      export function getCanonicalString(value) { return value.toLowerCase(); }
      export function getElement() { throw new Error("not used"); }
      export function numericSort() { return 0; }
      export function scheduleBackgroundTask() { return 0; }
      export function setError() {}
      export function setInfo() {}
    `),
  ],
  [
    "video-popover",
    moduleUrl(`
      export function showClipForSoundClick() {}
      export function stopClipDisplayForSound() {}
    `),
  ],
  [
    "websocket",
    moduleUrl(`
      export const GroupUpdateEvent = undefined;
      export const SoundUpdateEvent = undefined;
      export function onGroupUpdate() { return () => {}; }
      export function onSoundUpdate() { return () => {}; }
    `),
  ],
]);

registerHooks({
  resolve(specifier, context, nextResolve) {
    const stub = stubs.get(specifier);
    if (stub) return { url: stub, shortCircuit: true };
    return nextResolve(specifier, context);
  },
});

class FakeClassList {
  values = new Set();

  add(...names) {
    names.forEach((name) => this.values.add(name));
  }

  remove(...names) {
    names.forEach((name) => this.values.delete(name));
  }

  toggle(name, force) {
    if (force === undefined ? !this.values.has(name) : force) this.values.add(name);
    else this.values.delete(name);
  }

  contains(name) {
    return this.values.has(name);
  }
}

class FakeElement {
  constructor(tagName = "div") {
    this.tagName = tagName;
    this.attributes = new Map();
    this.children = [];
    this.dataset = {};
    this.classList = new FakeClassList();
    this.style = { setProperty() {}, removeProperty() {} };
    this.className = "";
    this.textContent = "";
    this.title = "";
  }

  setAttribute(name, value) {
    this.attributes.set(name, String(value));
  }

  getAttribute(name) {
    return this.attributes.get(name) ?? null;
  }

  removeAttribute(name) {
    this.attributes.delete(name);
  }

  replaceChildren(...children) {
    this.children = children;
  }

  querySelector(selector) {
    if (!selector.startsWith(".")) return null;
    const className = selector.slice(1);
    return this.children.find((child) =>
      child.className.split(/\s+/).includes(className)
    ) ?? null;
  }
}

globalThis.HTMLElement = FakeElement;
globalThis.document = {
  createElement(tagName) {
    return new FakeElement(tagName);
  },
};

const {
  SOUND_NAME_MAX_CODE_POINTS,
  soundNameCodePointLength,
  soundNameLengthError,
  soundNameRenameError,
} = await import("../scripts/sound-actions.ts");
const { SoundboardButton } = await import("../scripts/soundboard-button.ts");
const { findSoundButtonByName } = await import("../scripts/soundboard-app.ts");

test("web name limit counts Unicode code points rather than UTF-16 units", () => {
  const accepted = "😀".repeat(SOUND_NAME_MAX_CODE_POINTS);
  const rejected = accepted + "😀";

  assert.equal(accepted.length, 1000, "the browser string uses surrogate pairs");
  assert.equal(soundNameCodePointLength(accepted), 500);
  assert.equal(soundNameLengthError(accepted), null);
  assert.match(soundNameLengthError(rejected), /501 entered/);
});

test("unchanged over-limit legacy names remain a valid rename no-op", () => {
  const legacyName = "legacy".repeat(100);

  assert.equal(soundNameRenameError(legacyName, legacyName), null);
  assert.match(soundNameRenameError(legacyName, `${legacyName}x`), /601 entered/);
});

test("sound labels render hostile names as text with full hover and accessible text", () => {
  const name = `<img src=x onerror="globalThis.injected=true">[sound]`;
  const button = new SoundboardButton();
  button.sound = {
    name,
    discord_plays: 0,
    twitch_plays: 0,
    web_plays: 0,
  };
  button.updateLabel();

  assert.equal(button.children.length, 3);
  assert.equal(button.children[1].textContent, name);
  assert.equal(button.children[1].title, name);
  assert.equal(button.getAttribute("aria-label"), `Play sound ${name}`);
  assert.equal(globalThis.injected, undefined);
});

test("live-update lookup uses exact values without interpolating a CSS selector", () => {
  const hostileName = `quote'\"]\\name`;
  const wanted = new FakeElement("soundboard-button");
  wanted.setAttribute("sound", JSON.stringify({ name: hostileName }));
  const other = new FakeElement("soundboard-button");
  other.setAttribute("sound", JSON.stringify({ name: "other" }));
  const selectors = [];
  const grid = {
    querySelectorAll(selector) {
      selectors.push(selector);
      return [other, wanted];
    },
  };

  assert.strictEqual(findSoundButtonByName(grid, hostileName), wanted);
  assert.deepEqual(selectors, ["soundboard-button[sound]"]);
});
