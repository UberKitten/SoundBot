import assert from "node:assert/strict";
import { registerHooks } from "node:module";
import test from "node:test";

function moduleUrl(source) {
  return `data:text/javascript,${encodeURIComponent(source)}`;
}

const stubs = new Map([
  [
    "add-sound-modal",
    moduleUrl("export function openAddSoundModal() {}"),
  ],
  [
    "admin-api",
    moduleUrl(`
      export class ApiError extends Error {}
      export async function fetchClipEmbedUrl(name) {
        globalThis.__embedRequests.push(name);
        if (globalThis.__embedError) throw globalThis.__embedError;
        return globalThis.__embedUrl;
      }
      export function soundVideoDownloadUrl(name) {
        return "/api/admin/sounds/" + encodeURIComponent(name) + "/video?download=true";
      }
    `),
  ],
  ["audio", moduleUrl("export const Sound = undefined;")],
  [
    "auth",
    moduleUrl(`
      export function isAdmin() { return globalThis.__isAdmin; }
      export function onAuthChange() {}
    `),
  ],
  [
    "clipboard",
    moduleUrl(
      "export function copyToClipboard(text) { return globalThis.__copyToClipboard(text); }"
    ),
  ],
  [
    "sound-actions",
    moduleUrl(`
      export function openDeleteModal(name) { globalThis.__otherActions.push(["delete", name]); }
      export function openRenameModal(name) { globalThis.__otherActions.push(["rename", name]); }
    `),
  ],
  [
    "trim-editor",
    moduleUrl(
      'export function openTrimEditor(name) { globalThis.__otherActions.push(["trim", name]); }'
    ),
  ],
  [
    "video-popover",
    moduleUrl(
      "export function openVideoPopover(name) { globalThis.__watched.push(name); }"
    ),
  ],
  [
    "toast",
    moduleUrl(
      "export function showToast(message, kind, duration) { globalThis.__toasts.push({ message, kind, duration }); }"
    ),
  ],
]);

registerHooks({
  resolve(specifier, context, nextResolve) {
    const stub = stubs.get(specifier);
    if (stub) return { url: stub, shortCircuit: true };
    return nextResolve(specifier, context);
  },
});

const clickedDownloads = [];
globalThis.document = {
  body: {
    appendChild() {},
    contains() {
      return false;
    },
  },
  createElement(tag) {
    assert.equal(tag, "a");
    return {
      href: "",
      download: undefined,
      click() {
        clickedDownloads.push(this.href);
      },
      remove() {},
    };
  },
  querySelector() {
    return null;
  },
};

globalThis.__isAdmin = false;
globalThis.__embedRequests = [];
globalThis.__embedUrl =
  "https://soundbot.example/clips/selected.mp4?exp=1&sig=signed";
globalThis.__embedError = null;
globalThis.__copied = [];
globalThis.__copyToClipboard = async (text) => {
  globalThis.__copied.push(text);
};
globalThis.__toasts = [];
globalThis.__watched = [];
globalThis.__otherActions = [];

const { getAdminMenuItems } = await import("../scripts/admin-ui.ts");

function sound(overrides = {}) {
  return { name: "selected", has_video: true, ...overrides };
}

async function settle() {
  await new Promise((resolve) => setImmediate(resolve));
  await new Promise((resolve) => setImmediate(resolve));
}

test("clip commands use the identical authenticated-viewer and clip condition", () => {
  globalThis.__isAdmin = false;
  assert.deepEqual(getAdminMenuItems(sound()), []);

  globalThis.__isAdmin = true;
  assert.deepEqual(
    getAdminMenuItems(sound({ has_video: false })).map((item) => item.label),
    ["Edit / Trim…", "Rename…", "Delete…"]
  );

  assert.deepEqual(
    getAdminMenuItems(sound()).map((item) => item.label),
    [
      "Edit / Trim…",
      "Watch clip",
      "Download clip",
      "Copy clip embed URL",
      "Rename…",
      "Delete…",
    ]
  );
});

test("clip commands keep selected identity and established menu actions intact", async () => {
  globalThis.__isAdmin = true;
  const items = getAdminMenuItems(sound());
  const byLabel = new Map(items.map((item) => [item.label, item.action]));

  byLabel.get("Watch clip")();
  byLabel.get("Download clip")();
  byLabel.get("Copy clip embed URL")();
  byLabel.get("Edit / Trim…")();
  byLabel.get("Rename…")();
  byLabel.get("Delete…")();
  await settle();

  assert.deepEqual(globalThis.__watched, ["selected"]);
  assert.deepEqual(clickedDownloads, [
    "/api/admin/sounds/selected/video?download=true",
  ]);
  assert.deepEqual(globalThis.__embedRequests, ["selected"]);
  assert.deepEqual(globalThis.__copied, [globalThis.__embedUrl]);
  assert.deepEqual(globalThis.__toasts, [
    { message: "Clip embed URL copied.", kind: "success", duration: undefined },
  ]);
  assert.deepEqual(globalThis.__otherActions, [
    ["trim", "selected"],
    ["rename", "selected"],
    ["delete", "selected"],
  ]);
});

test("clipboard failures use existing error feedback", async () => {
  globalThis.__isAdmin = true;
  globalThis.__toasts.length = 0;
  globalThis.__copyToClipboard = async () => {
    throw new Error("clipboard denied");
  };
  const originalConsoleError = console.error;
  const loggedErrors = [];
  console.error = (...args) => loggedErrors.push(args);

  const item = getAdminMenuItems(sound()).find(
    (candidate) => candidate.label === "Copy clip embed URL"
  );
  item.action();
  await settle();
  console.error = originalConsoleError;

  assert.deepEqual(globalThis.__toasts, [
    {
      message: "Could not copy clip embed URL.",
      kind: "error",
      duration: undefined,
    },
  ]);
  assert.equal(loggedErrors.length, 1);
});
