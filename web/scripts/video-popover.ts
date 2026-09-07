/**
 * Authenticated clip player.
 *
 * The first video-enabled sound click opens this persistent, movable, resizable
 * player and uses the clip as that click's playback. While visible, later
 * video-enabled sound clicks retarget the same player. Hiding or closing the
 * player suppresses automatic reopening for the rest of the page session;
 * the explicit Show video control restores the most recently selected clip.
 *
 * The video streams from GET /api/admin/sounds/{name}/video (same-origin
 * cookies). The first request per sound may take a few seconds while the
 * server transcodes, so a spinner overlays the stage until `canplay`.
 *
 * Drag (title bar) and resize (bottom grip strip) both use pointer events with
 * pointer capture. Geometry is clamped to keep the title bar reachable and is
 * retained in sessionStorage.
 *
 * Layering: z-index 90 — above page content, below context menus and modals.
 */

import { soundVideoUrl } from "admin-api";
import { Sound, stopAllButtonAudio, stopMainAudio } from "audio";
import { isAdmin, onAuthChange } from "auth";

const MIN_WIDTH = 240;
const MIN_HEIGHT = 180;
const DEFAULT_WIDTH = 420;
const MARGIN = 16;
/** Minimum sliver of the title bar that must stay visible horizontally. */
const HEADER_VISIBLE_X_PX = 60;
/** Minimum height of the title bar that must stay visible vertically. */
const HEADER_VISIBLE_Y_PX = 40;
const RECT_STORAGE_KEY = "soundbot-video-player-rect";

interface PlayerRect {
  left: number;
  top: number;
  width: number;
  height: number;
}

interface Player {
  wrap: HTMLElement;
  titleEl: HTMLElement;
  errorEl: HTMLElement;
  video: HTMLVideoElement;
  rect: PlayerRect;
  currentName: string | null;
  onWindowResize: () => void;
}

/** Single player instance — everything retargets this. */
let player: Player | null = null;
let videoControl: HTMLButtonElement | null = null;
let lastVideoName: string | null = null;
let automaticOpeningSuppressed = false;

function ensureVideoControl(): HTMLButtonElement {
  if (videoControl && document.body.contains(videoControl)) return videoControl;

  const btn = document.createElement("button");
  btn.type = "button";
  btn.id = "admin-video-toggle";
  btn.className = "admin-video-btn";
  btn.addEventListener("click", () => {
    if (player) {
      hidePlayer(true);
    } else {
      showLastVideo();
    }
  });

  const header = document.querySelector("header");
  const authControls = document.querySelector("#auth-controls");
  if (header) {
    if (authControls) header.insertBefore(btn, authControls);
    else header.appendChild(btn);
  } else {
    document.body.appendChild(btn);
  }

  videoControl = btn;
  updateVideoControl();
  return btn;
}

function updateVideoControl(): void {
  if (!videoControl) return;
  const visible = player !== null;
  const label = visible ? "Hide video" : "Show video";
  videoControl.textContent = label;
  videoControl.title = label;
  videoControl.setAttribute("aria-label", label);
  videoControl.setAttribute("aria-pressed", visible ? "true" : "false");
  videoControl.disabled = !visible && lastVideoName === null;
}

/**
 * Install the authenticated Show video / Hide video control.
 */
export function initVideoControl(): void {
  onAuthChange((state) => {
    const btn = ensureVideoControl();
    const allowed = state.authenticated && state.can_admin;
    btn.hidden = !allowed;
    if (!allowed) {
      hidePlayer(false);
      lastVideoName = null;
      automaticOpeningSuppressed = false;
    }
    updateVideoControl();
  });
}

/**
 * Handle a sound-button click with the clip player when appropriate.
 *
 * Returns true only when the clip is the playback for this click, so the
 * caller can avoid also playing the soundboard audio. Video-enabled clicks
 * made while explicitly hidden still remember the selection, but return false
 * and leave the player hidden.
 */
export function playClipForSoundClick(sound: Sound): boolean {
  if (!sound.has_video || !isAdmin()) return false;

  lastVideoName = sound.name;
  updateVideoControl();

  if (player) {
    loadSound(player, sound.name);
    return true;
  }
  if (automaticOpeningSuppressed) return false;

  loadSound(ensurePlayer(), sound.name);
  return true;
}

function showLastVideo(): void {
  if (!lastVideoName || !isAdmin()) return;
  automaticOpeningSuppressed = false;
  stopMainAudio();
  stopAllButtonAudio();
  loadSound(ensurePlayer(), lastVideoName);
}

/* ---- loading / retargeting ---- */

function loadSound(p: Player, name: string): void {
  if (
    p.currentName === name &&
    p.video.getAttribute("src") &&
    !p.wrap.classList.contains("video-error")
  ) {
    // Same sound again (and it loaded fine): restart rather than re-fetch.
    try {
      p.video.currentTime = 0;
    } catch {
      /* not seekable yet — play() below still applies */
    }
    p.video.play().catch(() => {
      /* autoplay guards — user can hit play via controls */
    });
    return;
  }

  p.currentName = name;
  p.titleEl.textContent = name;
  p.wrap.setAttribute("aria-label", `Video clip: ${name}`);

  // Fresh load state: spinner visible, video hidden, error cleared. Rapid
  // retargets are last-wins by construction: swapping `src` aborts the
  // previous fetch, and the single persistent canplay/error listeners always
  // refer to the element's CURRENT resource — nothing stale stacks up.
  p.wrap.classList.remove("video-ready", "video-error");
  p.video.pause();
  p.video.src = soundVideoUrl(name);
  p.video.load();
  p.video.play().catch(() => {
    /* autoplay guards — user can hit play via controls */
  });
}

/* ---- construction ---- */

function ensurePlayer(): Player {
  if (player) return player;

  const wrap = document.createElement("div");
  wrap.className = "video-player";
  wrap.setAttribute("role", "dialog");
  wrap.tabIndex = -1;

  const header = document.createElement("div");
  header.className = "video-player-header";

  const titleEl = document.createElement("span");
  titleEl.className = "video-player-title";

  const closeBtn = document.createElement("button");
  closeBtn.type = "button";
  closeBtn.className = "video-player-close";
  closeBtn.setAttribute("aria-label", "Close");
  closeBtn.textContent = "×";

  header.appendChild(titleEl);
  header.appendChild(closeBtn);

  const stage = document.createElement("div");
  stage.className = "video-player-stage";

  const spinner = document.createElement("div");
  spinner.className = "video-player-loading";
  spinner.innerHTML =
    '<span class="admin-spinner" aria-hidden="true"></span>preparing clip…';

  const video = document.createElement("video");
  video.className = "video-player-video";
  video.controls = true;
  video.autoplay = true;
  video.playsInline = true;
  video.preload = "auto";

  const errorEl = document.createElement("div");
  errorEl.className = "video-player-error";

  stage.appendChild(video);
  stage.appendChild(spinner);
  stage.appendChild(errorEl);

  const footer = document.createElement("div");
  footer.className = "video-player-footer";
  footer.setAttribute("aria-hidden", "true");

  wrap.appendChild(header);
  wrap.appendChild(stage);
  wrap.appendChild(footer);

  const p: Player = {
    wrap,
    titleEl,
    errorEl,
    video,
    rect: { left: 0, top: 0, width: DEFAULT_WIDTH, height: MIN_HEIGHT },
    currentName: null,
    onWindowResize: () => {
      p.rect = clampRect(p.rect);
      applyRect(p);
    },
  };

  closeBtn.addEventListener("click", () => hidePlayer(true));

  // Escape closes only when focus is within the player (no document listener).
  wrap.addEventListener("keydown", (e: KeyboardEvent) => {
    if (e.key === "Escape") {
      e.stopPropagation();
      hidePlayer(true);
    }
  });

  // One persistent pair of media listeners; both refer to the element's
  // current resource, so retargets never leave stale handlers behind.
  video.addEventListener("canplay", () => {
    if (!video.getAttribute("src")) return;
    wrap.classList.remove("video-error");
    wrap.classList.add("video-ready");
  });
  video.addEventListener("error", () => {
    // Ignore the synthetic error from unloading src on close, and stale
    // events from a resource that a retarget's load() already replaced
    // (load() clears video.error for the new resource).
    if (!video.getAttribute("src") || !video.error) return;
    errorEl.textContent = `Couldn't load the video for "${p.currentName ?? "this sound"}".`;
    wrap.classList.remove("video-ready");
    wrap.classList.add("video-error");
  });

  attachDrag(p, header);
  attachResize(p, footer);

  document.body.appendChild(wrap);

  // Geometry: last session rect if any, else default size at bottom-right.
  const saved = loadSavedRect();
  if (saved) {
    p.rect = clampRect(saved);
  } else {
    const width = Math.min(
      Math.max(DEFAULT_WIDTH, MIN_WIDTH),
      Math.max(MIN_WIDTH, window.innerWidth * 0.95)
    );
    wrap.style.width = `${width}px`;
    // Natural height = header + 16:9 stage + footer (stage has a CSS
    // aspect-ratio until the height is frozen here).
    const height = wrap.offsetHeight;
    p.rect = clampRect({
      left: window.innerWidth - width - MARGIN,
      top: window.innerHeight - height - MARGIN,
      width,
      height,
    });
  }
  applyRect(p);

  window.addEventListener("resize", p.onWindowResize);

  player = p;
  updateVideoControl();
  return p;
}

function hidePlayer(suppressAutomaticOpening: boolean): void {
  if (suppressAutomaticOpening) automaticOpeningSuppressed = true;
  if (!player) {
    updateVideoControl();
    return;
  }
  const p = player;
  player = null;
  window.removeEventListener("resize", p.onWindowResize);
  // Pause + unload so audio doesn't keep playing while hidden.
  try {
    p.video.pause();
    p.video.removeAttribute("src");
    p.video.load();
  } catch {
    /* ignore */
  }
  p.wrap.remove();
  updateVideoControl();
}

/* ---- drag / resize (pointer events with capture: mouse + touch) ---- */

function attachDrag(p: Player, header: HTMLElement): void {
  header.addEventListener("pointerdown", (e: PointerEvent) => {
    // The ✕ is inside the header; don't turn its press into a drag.
    if ((e.target as HTMLElement).closest(".video-player-close")) return;
    e.preventDefault();
    p.wrap.focus();
    trackPointer(p, header, e, (dx, dy, start) => {
      p.rect = clampRect({
        ...p.rect,
        left: start.left + dx,
        top: start.top + dy,
      });
      applyRect(p);
    });
  });
}

function attachResize(p: Player, grip: HTMLElement): void {
  grip.addEventListener("pointerdown", (e: PointerEvent) => {
    e.preventDefault();
    trackPointer(p, grip, e, (dx, dy, start) => {
      p.rect = clampRect({
        ...p.rect,
        width: start.width + dx,
        height: start.height + dy,
      });
      applyRect(p);
    });
  });
}

/**
 * Capture a pointer on `el` and report movement deltas (viewport client
 * coordinates — the player is a fixed-position child of <body>, untransformed,
 * so client deltas map 1:1 onto left/top/width/height). Listeners live on the
 * captured element and are removed on pointerup/cancel; the final rect is
 * persisted for the session.
 */
function trackPointer(
  p: Player,
  el: HTMLElement,
  down: PointerEvent,
  onDelta: (dx: number, dy: number, start: PlayerRect) => void
): void {
  const start = { ...p.rect };
  const startX = down.clientX;
  const startY = down.clientY;

  try {
    el.setPointerCapture(down.pointerId);
  } catch {
    /* capture can fail if the pointer is already gone — move events just
       won't be retargeted, which degrades gracefully */
  }

  const onMove = (e: PointerEvent) => {
    if (e.pointerId !== down.pointerId) return;
    onDelta(e.clientX - startX, e.clientY - startY, start);
  };
  const onEnd = (e: PointerEvent) => {
    if (e.pointerId !== down.pointerId) return;
    el.removeEventListener("pointermove", onMove);
    el.removeEventListener("pointerup", onEnd);
    el.removeEventListener("pointercancel", onEnd);
    saveRect(p.rect);
  };
  el.addEventListener("pointermove", onMove);
  el.addEventListener("pointerup", onEnd);
  el.addEventListener("pointercancel", onEnd);
}

/* ---- geometry ---- */

function clampRect(r: PlayerRect): PlayerRect {
  const maxW = Math.max(MIN_WIDTH, window.innerWidth * 0.95);
  const maxH = Math.max(MIN_HEIGHT, window.innerHeight * 0.7);
  const width = Math.min(Math.max(r.width, MIN_WIDTH), maxW);
  const height = Math.min(Math.max(r.height, MIN_HEIGHT), maxH);

  // Keep a grabbable sliver of the title bar on-screen in both axes.
  const minLeft = -(width - HEADER_VISIBLE_X_PX);
  const maxLeft = window.innerWidth - HEADER_VISIBLE_X_PX;
  const left = Math.min(Math.max(r.left, minLeft), maxLeft);
  const maxTop = Math.max(0, window.innerHeight - HEADER_VISIBLE_Y_PX);
  const top = Math.min(Math.max(r.top, 0), maxTop);

  return { left, top, width, height };
}

function applyRect(p: Player): void {
  p.wrap.style.left = `${p.rect.left}px`;
  p.wrap.style.top = `${p.rect.top}px`;
  p.wrap.style.width = `${p.rect.width}px`;
  p.wrap.style.height = `${p.rect.height}px`;
}

/* ---- session persistence ---- */

function saveRect(rect: PlayerRect): void {
  try {
    sessionStorage.setItem(RECT_STORAGE_KEY, JSON.stringify(rect));
  } catch {
    /* storage unavailable — position just won't persist */
  }
}

function loadSavedRect(): PlayerRect | null {
  try {
    const raw = sessionStorage.getItem(RECT_STORAGE_KEY);
    if (!raw) return null;
    const parsed = JSON.parse(raw) as Partial<Record<keyof PlayerRect, unknown>>;
    const nums = [parsed.left, parsed.top, parsed.width, parsed.height];
    if (nums.some((n) => typeof n !== "number" || !isFinite(n))) return null;
    return {
      left: parsed.left as number,
      top: parsed.top as number,
      width: parsed.width as number,
      height: parsed.height as number,
    };
  } catch {
    return null;
  }
}
