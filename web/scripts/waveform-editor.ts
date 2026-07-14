/**
 * Shared waveform-editor core used by both the existing-sound trim editor
 * (trim-editor.ts) and the draft add-sound editor (draft-editor.ts).
 *
 * Owns the WaveSurfer instance, the single draggable/resizable trim region,
 * the transport buttons, numeric edge inputs with nudges, zoom + volume
 * controls, and the keyboard shortcuts (space / s / e / l / , / .).
 * Mode-specific chrome — banner, footer buttons, save behavior, dismissal
 * side effects — is injected by the callers.
 */

import { ApiError } from "admin-api";
import { openModal, ModalController } from "modal";
import { showToast } from "toast";
import WaveSurfer from "wavesurfer";
import RegionsPlugin, { Region } from "wavesurfer-regions";

const EDGE_PREVIEW_SECONDS = 1.5;
export const MIN_REGION_LENGTH = 0.05;
const VOLUME_MIN = -5;
const VOLUME_MAX = 3;
/** Pointer travel below this (px) between down/up counts as a click, not a drag. */
const CLICK_MOVE_TOLERANCE = 5;
/** Playhead within this many seconds of the region end → play the full region. */
const PLAYHEAD_END_EPSILON = 0.05;

/** Audio + trim metadata the editor operates on (WaveformInfo-compatible). */
export interface EditorInfo {
  audio_url: string;
  duration: number;
  start: number | null;
  end: number | null;
  volume_adjust: number;
  source_title: string | null;
  source_url: string | null;
}

/** Snapshot of the current trim/volume selection. */
export interface TrimState {
  duration: number;
  start: number;
  end: number;
  /** volume as an integer notch; dB = notch * 3. */
  volumeNotch: number;
  initialVolumeNotch: number;
}

export interface WaveformEditorCore {
  modal: ModalController;
  getState(): TrimState;
  /** True when region/volume differ from their initial values (or extraDirty). */
  isDirty(): boolean;
  isBusy(): boolean;
  /** Toggle the saving/busy state (blocks close + pointer events). */
  setBusy(busy: boolean): void;
  stopPlayback(): void;
  /** Re-fetch info and rebuild the waveform UI (used after redownload). */
  reload(load: () => Promise<EditorInfo>): Promise<void>;
  /** Close without guards or the onDismissed callback (after a save). */
  complete(): void;
  /** Toast an ApiError message (or a generic fallback). */
  handleError(e: unknown): void;
}

export interface WaveformEditorOptions {
  title: string | HTMLElement;
  className?: string;
  /** Banner text rendered at the top of the body (draft mode). */
  banner?: string;
  /** Confirm prompt shown when dismissing with unsaved changes. */
  confirmDismissMessage?: string;
  /** Fetch the audio + trim metadata to edit. */
  load: () => Promise<EditorInfo>;
  /** Build the mode-specific footer (name field / save / cancel etc.). */
  buildFooter: (core: WaveformEditorCore) => HTMLElement;
  /** Additional dirty state beyond region/volume (e.g. a typed name). */
  extraDirty?: () => boolean;
  /** Fires when the editor closes without complete() (cancel/Esc/backdrop). */
  onDismissed?: () => void;
}

interface EditorState {
  duration: number;
  start: number;
  end: number;
  volumeNotch: number;
  initialStart: number;
  initialEnd: number;
  initialVolumeNotch: number;
}

function clamp(v: number, lo: number, hi: number): number {
  return Math.max(lo, Math.min(hi, v));
}

function fmt(seconds: number): string {
  if (!Number.isFinite(seconds)) return "0.00";
  return seconds.toFixed(2);
}

/** m:ss.t clock format (tenths truncated so 59.99 → 0:59.9, not 1:00.0). */
function fmtClock(seconds: number): string {
  const safe = Number.isFinite(seconds) && seconds > 0 ? seconds : 0;
  const m = Math.floor(safe / 60);
  const tenths = Math.floor((safe - m * 60) * 10) / 10;
  return `${m}:${tenths < 10 ? "0" : ""}${tenths.toFixed(1)}`;
}

function svgIcon(paths: string): string {
  return `<svg class="icon" aria-hidden="true" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round">${paths}</svg>`;
}

const ICON_PLAY = svgIcon('<polygon points="6 3 20 12 6 21 6 3"/>');
const ICON_PAUSE = svgIcon(
  '<rect x="6" y="4" width="4" height="16" rx="1"/><rect x="14" y="4" width="4" height="16" rx="1"/>'
);
const ICON_LOOP = svgIcon(
  '<path d="m17 2 4 4-4 4"/><path d="M3 11v-1a4 4 0 0 1 4-4h14"/><path d="m7 22-4-4 4-4"/><path d="M21 13v1a4 4 0 0 1-4 4H3"/>'
);

export function openWaveformEditor(
  opts: WaveformEditorOptions
): WaveformEditorCore {
  let wavesurfer: WaveSurfer | null = null;
  let region: Region | null = null;
  let regions: RegionsPlugin | null = null;
  let loop = false;
  let busy = false;
  let destroyed = false;
  let completed = false;
  // Guards the region<->input sync loop against feedback.
  let syncing = false;
  // When set, playback auto-stops once currentTime passes this point.
  let playStopAt: number | null = null;
  // True once the regions plugin reports a drag/resize during the current
  // pointer press — used to tell region drags apart from plain clicks.
  let regionMovedDuringPointer = false;

  const state: EditorState = {
    duration: 0,
    start: 0,
    end: 0,
    volumeNotch: 0,
    initialStart: 0,
    initialEnd: 0,
    initialVolumeNotch: 0,
  };

  const isDirty = (): boolean =>
    state.start !== state.initialStart ||
    state.end !== state.initialEnd ||
    state.volumeNotch !== state.initialVolumeNotch ||
    (opts.extraDirty?.() ?? false);

  const modal: ModalController = openModal({
    title: opts.title,
    className: opts.className ?? "trim-editor",
    beforeClose: () => {
      if (busy) return false;
      if (isDirty()) {
        return window.confirm(
          opts.confirmDismissMessage ?? "Discard unsaved changes?"
        );
      }
      return true;
    },
    onClosed: () => {
      destroyed = true;
      document.removeEventListener("keydown", onKeydown, true);
      destroyWavesurfer();
      if (!completed) opts.onDismissed?.();
    },
  });

  // ---- initial "loading" body ----
  const loading = document.createElement("div");
  loading.className = "trim-loading";
  loading.textContent = "preparing waveform…";
  modal.body.appendChild(loading);

  // ---- keyboard shortcuts (ignored while typing in inputs) ----
  const onKeydown = (e: KeyboardEvent) => {
    if (destroyed || busy) return;
    const target = e.target as HTMLElement | null;
    const typing =
      target &&
      (target.tagName === "INPUT" ||
        target.tagName === "TEXTAREA" ||
        target.tagName === "SELECT");
    if (typing) return;
    if (e.metaKey || e.ctrlKey || e.altKey) return;

    switch (e.key) {
      case " ":
        e.preventDefault();
        togglePlayRegion();
        break;
      case "s":
      case "S":
        e.preventDefault();
        playEdge("start");
        break;
      case "e":
      case "E":
        e.preventDefault();
        playEdge("end");
        break;
      case "l":
      case "L":
        e.preventDefault();
        toggleLoop();
        break;
      case ",":
        e.preventDefault();
        nudgeNearest(-0.05);
        break;
      case ".":
        e.preventDefault();
        nudgeNearest(0.05);
        break;
      default:
        break;
    }
  };
  document.addEventListener("keydown", onKeydown, true);

  // Placeholders assigned once the UI is built.
  let startInput: HTMLInputElement | null = null;
  let endInput: HTMLInputElement | null = null;
  let playBtn: HTMLButtonElement | null = null;
  let loopBtn: HTMLButtonElement | null = null;
  let playheadReadout: HTMLSpanElement | null = null;
  let regionReadout: HTMLSpanElement | null = null;

  /** mm:ss.t for sources ≥60s, plain seconds below (matches the hover tip). */
  function fmtReadout(seconds: number): string {
    if (state.duration >= 60) return fmtClock(seconds);
    return `${Math.max(0, seconds).toFixed(2)}s`;
  }

  function updatePlayheadReadout(t: number): void {
    if (playheadReadout) playheadReadout.textContent = `⏱ ${fmtReadout(t)}`;
  }

  function updateRegionReadout(): void {
    if (!regionReadout) return;
    const len = Math.max(0, state.end - state.start);
    const text =
      len >= 60 ? fmtClock(len) : `${Math.round(len * 100) / 100}s`;
    regionReadout.textContent = `region ${text}`;
  }

  function destroyWavesurfer(): void {
    if (wavesurfer) {
      try {
        wavesurfer.destroy();
      } catch {
        /* ignore */
      }
      wavesurfer = null;
      region = null;
      regions = null;
    }
  }

  function applyRegionToState(): void {
    if (!region) return;
    const start = clamp(region.start, 0, state.duration);
    let end = clamp(region.end, 0, state.duration);
    if (end - start < MIN_REGION_LENGTH) {
      end = clamp(start + MIN_REGION_LENGTH, 0, state.duration);
    }
    state.start = start;
    state.end = end;
    syncInputs();
  }

  function syncInputs(): void {
    if (startInput) startInput.value = fmt(state.start);
    if (endInput) endInput.value = fmt(state.end);
    updateRegionReadout();
  }

  function setRegionBounds(start: number, end: number): void {
    // Keep start within [0, duration - MIN] so a valid-length region always fits.
    const maxStart = Math.max(0, state.duration - MIN_REGION_LENGTH);
    const s = clamp(start, 0, maxStart);
    let e = clamp(end, s + MIN_REGION_LENGTH, state.duration);
    if (e - s < MIN_REGION_LENGTH) {
      e = clamp(s + MIN_REGION_LENGTH, 0, state.duration);
    }
    state.start = s;
    state.end = e;
    syncing = true;
    region?.setOptions({ start: s, end: e });
    syncing = false;
    syncInputs();
  }

  function stopPlayback(): void {
    playStopAt = null;
    if (wavesurfer && wavesurfer.isPlaying()) wavesurfer.pause();
    updatePlayButton();
  }

  function updatePlayButton(): void {
    if (!playBtn) return;
    const playing = !!wavesurfer && wavesurfer.isPlaying();
    playBtn.innerHTML = playing
      ? `${ICON_PAUSE}<span>Region</span>`
      : `${ICON_PLAY}<span>Region</span>`;
    playBtn.setAttribute("aria-pressed", playing ? "true" : "false");
  }

  function togglePlayRegion(): void {
    if (!wavesurfer) return;
    if (wavesurfer.isPlaying()) {
      stopPlayback();
      return;
    }
    // If the playhead sits inside the region (and not right at its end),
    // audition from there to the region end; otherwise play the full region.
    const t = wavesurfer.getCurrentTime();
    if (t >= state.start && t < state.end - PLAYHEAD_END_EPSILON) {
      playRange(t, state.end);
    } else {
      playRange(state.start, state.end);
    }
  }

  function playRange(from: number, to: number): void {
    if (!wavesurfer || state.duration <= 0) return;
    const start = clamp(from, 0, state.duration);
    const end = clamp(to, start + 0.001, state.duration);
    playStopAt = end;
    wavesurfer.setTime(start);
    resumeAudioContext();
    wavesurfer.play().catch(() => {
      /* autoplay guards — ignore */
    });
    updatePlayButton();
  }

  /**
   * iOS unlock for the WebAudio backend: wavesurfer's WebAudio player creates
   * its own AudioContext at construction (outside any user gesture) and the
   * vendored build NEVER calls resume() — on iOS that context starts
   * "suspended" and plays pure silence (no error, so play() resolves fine).
   * Unlocking the soundboard's separate context doesn't help; each context
   * must be resumed within a gesture. playRange only ever runs from taps/
   * keydowns, so resuming here is always gesture-blessed.
   */
  function resumeAudioContext(): void {
    if (!wavesurfer) return;
    const media = wavesurfer.getMediaElement() as unknown as {
      audioContext?: AudioContext;
    };
    const ctx = media.audioContext;
    if (ctx && ctx.state === "suspended") {
      void ctx.resume();
    }
  }

  function playEdge(edge: "start" | "end"): void {
    if (edge === "start") {
      // Play from the region start through to the region end — auditioning the
      // start shouldn't cut off mid-sound. Stop manually (Space) when satisfied.
      playRange(state.start, state.end);
    } else {
      const from = Math.max(state.end - EDGE_PREVIEW_SECONDS, state.start);
      playRange(from, state.end);
    }
  }

  function toggleLoop(): void {
    loop = !loop;
    if (loopBtn) {
      loopBtn.classList.toggle("active", loop);
      loopBtn.setAttribute("aria-pressed", loop ? "true" : "false");
    }
  }

  function nudge(edge: "start" | "end", delta: number): void {
    if (edge === "start") {
      setRegionBounds(state.start + delta, state.end);
    } else {
      setRegionBounds(state.start, state.end + delta);
    }
  }

  function nudgeNearest(delta: number): void {
    // Nudge whichever edge is closer to the current playhead (fallback: end).
    const t = wavesurfer?.getCurrentTime() ?? state.end;
    const nearStart = Math.abs(t - state.start) <= Math.abs(t - state.end);
    nudge(nearStart ? "start" : "end", delta);
  }

  function onTimeupdate(currentTime: number): void {
    updatePlayheadReadout(currentTime);
    if (playStopAt === null) return;
    if (currentTime >= playStopAt) {
      if (loop) {
        // Loop region playback: jump back to region start.
        wavesurfer?.setTime(state.start);
        playStopAt = state.end;
      } else {
        stopPlayback();
      }
    }
  }

  function buildUI(info: EditorInfo): void {
    modal.body.innerHTML = "";

    // -- draft/banner note --
    if (opts.banner) {
      const banner = document.createElement("div");
      banner.className = "draft-banner";
      banner.textContent = opts.banner;
      modal.body.appendChild(banner);
    }

    // -- source meta line at the top of the body --
    if (info.source_title || info.source_url) {
      const meta = document.createElement("div");
      meta.className = "trim-source";
      if (info.source_url) {
        const a = document.createElement("a");
        a.href = info.source_url;
        a.target = "_blank";
        a.rel = "noopener noreferrer";
        a.textContent = info.source_title || info.source_url;
        meta.appendChild(a);
      } else if (info.source_title) {
        meta.textContent = info.source_title;
      }
      modal.body.appendChild(meta);
    }

    // -- waveform container --
    const waveContainer = document.createElement("div");
    waveContainer.className = "trim-waveform";
    modal.body.appendChild(waveContainer);

    // ---- click-to-seek + hover time tooltip ------------------------------
    //
    // The regions plugin's drag helper stopPropagation()s pointerdown on the
    // region element (and the trim region spans the full source by default),
    // so wavesurfer's own click→seek never sees interactions there. We listen
    // on the waveform container in the CAPTURE phase — ancestors' capture
    // listeners run before the region's target-phase stopPropagation — and
    // seek on plain clicks ourselves.
    //
    // Pointer state machine:
    //   pointerdown  → remember pointer id + position, clear "region moved"
    //   region-update (plugin) → flag "region moved" (body drag OR handle
    //                  resize; the plugin only emits this from real pointer
    //                  drags — programmatic setOptions never emits it)
    //   pointerup    → same pointer, moved < CLICK_MOVE_TOLERANCE px, and no
    //                  region-update in between ⇒ it was a click ⇒ setTime()
    //   pointercancel / pointermove with no buttons ⇒ reset stale state
    //
    // x→time uses the wrapper's bounding rect: the wrapper is the full-width
    // waveform element (wavesurfer sets its width to duration·pxPerSec under
    // zoom), so rect.left already accounts for horizontal scroll and
    // (clientX − rect.left) / rect.width is the fraction of the duration —
    // the exact math wavesurfer's own renderer click handler uses.

    /**
     * Time under a viewport point, or null before the waveform is ready or
     * when the point is vertically outside the waveform (e.g. the horizontal
     * scrollbar under a zoomed waveform — seeking from there would be wrong).
     */
    function timeAtClientPoint(clientX: number, clientY: number): number | null {
      if (!wavesurfer || state.duration <= 0) return null;
      const rect = wavesurfer.getWrapper().getBoundingClientRect();
      if (rect.width <= 0) return null;
      if (clientY < rect.top || clientY > rect.bottom) return null;
      const frac = clamp((clientX - rect.left) / rect.width, 0, 1);
      return frac * state.duration;
    }

    let pointerDown: { id: number; x: number; y: number } | null = null;
    regionMovedDuringPointer = false;

    const tooltip = document.createElement("div");
    tooltip.className = "trim-hover-time";
    tooltip.hidden = true;
    waveContainer.appendChild(tooltip);

    function hideTooltip(): void {
      tooltip.hidden = true;
    }

    waveContainer.addEventListener(
      "pointerdown",
      (e: PointerEvent) => {
        if (e.button !== 0) return; // primary button / touch only
        pointerDown = { id: e.pointerId, x: e.clientX, y: e.clientY };
        regionMovedDuringPointer = false;
        hideTooltip();
      },
      true
    );

    waveContainer.addEventListener(
      "pointerup",
      (e: PointerEvent) => {
        const down = pointerDown;
        pointerDown = null;
        if (!down || down.id !== e.pointerId) return;
        if (regionMovedDuringPointer) return;
        const moved = Math.hypot(e.clientX - down.x, e.clientY - down.y);
        if (moved >= CLICK_MOVE_TOLERANCE) return;
        const t = timeAtClientPoint(e.clientX, e.clientY);
        if (t === null) return;
        // setTime also emits "timeupdate", which refreshes the readout.
        wavesurfer?.setTime(t);
      },
      true
    );

    waveContainer.addEventListener(
      "pointercancel",
      () => {
        pointerDown = null;
      },
      true
    );

    // Hover tooltip: mouse only (no hover on touch), hidden while a pointer
    // is down (dragging a region edge/body), rAF-throttled.
    let hoverX = 0;
    let hoverY = 0;
    let tooltipRaf = 0;
    waveContainer.addEventListener("pointermove", (e: PointerEvent) => {
      // A pointerup outside the container leaves stale down-state; a
      // buttonless move means that press ended elsewhere.
      if (pointerDown && e.buttons === 0) pointerDown = null;
      if (e.pointerType !== "mouse" || pointerDown) return;
      hoverX = e.clientX;
      hoverY = e.clientY;
      if (tooltipRaf) return;
      tooltipRaf = requestAnimationFrame(() => {
        tooltipRaf = 0;
        if (destroyed) return;
        const t = timeAtClientPoint(hoverX, hoverY);
        if (t === null) {
          hideTooltip();
          return;
        }
        const rect = waveContainer.getBoundingClientRect();
        // Keep the (centered) label inside the container at the edges.
        const x = clamp(hoverX - rect.left, 28, Math.max(28, rect.width - 28));
        tooltip.textContent = fmtReadout(t);
        tooltip.style.left = `${x}px`;
        tooltip.hidden = false;
      });
    });
    waveContainer.addEventListener("pointerleave", hideTooltip);

    // -- primary transport row --
    const transport = document.createElement("div");
    transport.className = "trim-transport";

    playBtn = document.createElement("button");
    playBtn.type = "button";
    playBtn.className = "trim-btn trim-btn-primary";
    playBtn.title =
      "Play region (Space) — starts from the playhead when it's inside the region";
    playBtn.addEventListener("click", togglePlayRegion);

    const startEdgeBtn = document.createElement("button");
    startEdgeBtn.type = "button";
    startEdgeBtn.className = "trim-btn";
    startEdgeBtn.title = "Play from region start (s)";
    startEdgeBtn.innerHTML = `${ICON_PLAY}<span>Start</span>`;
    startEdgeBtn.addEventListener("click", () => playEdge("start"));

    const endEdgeBtn = document.createElement("button");
    endEdgeBtn.type = "button";
    endEdgeBtn.className = "trim-btn";
    endEdgeBtn.title = "Play last 1.5s of region (e)";
    endEdgeBtn.innerHTML = `${ICON_PLAY}<span>End</span>`;
    endEdgeBtn.addEventListener("click", () => playEdge("end"));

    loopBtn = document.createElement("button");
    loopBtn.type = "button";
    loopBtn.className = "trim-btn trim-btn-toggle";
    loopBtn.title = "Loop region playback (l)";
    loopBtn.setAttribute("aria-pressed", "false");
    loopBtn.innerHTML = `${ICON_LOOP}<span>Loop</span>`;
    loopBtn.addEventListener("click", toggleLoop);

    transport.appendChild(playBtn);
    transport.appendChild(startEdgeBtn);
    transport.appendChild(endEdgeBtn);
    transport.appendChild(loopBtn);

    // -- playhead position + region length readouts --
    const readouts = document.createElement("div");
    readouts.className = "trim-readouts";
    playheadReadout = document.createElement("span");
    playheadReadout.className = "trim-readout";
    playheadReadout.title = "Playhead position (click the waveform to move it)";
    regionReadout = document.createElement("span");
    regionReadout.className = "trim-readout";
    regionReadout.title = "Region length";
    readouts.appendChild(playheadReadout);
    readouts.appendChild(regionReadout);
    transport.appendChild(readouts);

    modal.body.appendChild(transport);
    updatePlayButton();

    // -- edge editors (start / end) with numeric input + nudges --
    const edges = document.createElement("div");
    edges.className = "trim-edges";

    const makeEdge = (label: string, which: "start" | "end") => {
      const wrap = document.createElement("div");
      wrap.className = "trim-edge";

      const heading = document.createElement("div");
      heading.className = "trim-edge-heading";
      heading.textContent = label;

      const inputRow = document.createElement("div");
      inputRow.className = "trim-edge-input";

      const input = document.createElement("input");
      input.type = "number";
      input.step = "0.01";
      input.min = "0";
      input.max = fmt(state.duration);
      input.inputMode = "decimal";
      input.className = "trim-number";
      input.setAttribute("aria-label", `${label} (seconds)`);

      const unit = document.createElement("span");
      unit.className = "trim-unit";
      unit.textContent = "s";

      const commit = () => {
        const parsed = parseFloat(input.value);
        if (Number.isNaN(parsed)) {
          syncInputs();
          return;
        }
        if (which === "start") setRegionBounds(parsed, state.end);
        else setRegionBounds(state.start, parsed);
      };
      input.addEventListener("change", commit);
      input.addEventListener("blur", commit);

      inputRow.appendChild(input);
      inputRow.appendChild(unit);

      const nudges = document.createElement("div");
      nudges.className = "trim-nudges";
      for (const delta of [-0.5, -0.05, 0.05, 0.5]) {
        const b = document.createElement("button");
        b.type = "button";
        b.className = "trim-nudge";
        b.textContent = delta > 0 ? `+${delta}` : `${delta}`;
        b.addEventListener("click", () => nudge(which, delta));
        nudges.appendChild(b);
      }

      wrap.appendChild(heading);
      wrap.appendChild(inputRow);
      wrap.appendChild(nudges);

      if (which === "start") startInput = input;
      else endInput = input;

      return wrap;
    };

    edges.appendChild(makeEdge("Start", "start"));
    edges.appendChild(makeEdge("End", "end"));
    modal.body.appendChild(edges);

    // -- zoom + volume row --
    const tools = document.createElement("div");
    tools.className = "trim-tools";

    const zoomWrap = document.createElement("label");
    zoomWrap.className = "trim-zoom";
    zoomWrap.textContent = "Zoom";
    const zoom = document.createElement("input");
    zoom.type = "range";
    zoom.min = "0";
    zoom.max = "300";
    zoom.value = "0";
    zoom.setAttribute("aria-label", "Zoom");
    zoom.addEventListener("input", () => {
      const pxPerSec = parseInt(zoom.value, 10) || 0;
      try {
        wavesurfer?.zoom(pxPerSec);
      } catch {
        /* zoom before ready — ignore */
      }
    });
    zoomWrap.appendChild(zoom);

    const volWrap = document.createElement("label");
    volWrap.className = "trim-volume";
    volWrap.textContent = "Volume";
    const vol = document.createElement("select");
    vol.className = "trim-volume-select";
    vol.setAttribute("aria-label", "Volume adjustment");
    for (let notch = VOLUME_MAX; notch >= VOLUME_MIN; notch--) {
      const opt = document.createElement("option");
      opt.value = String(notch);
      const db = notch * 3;
      opt.textContent = notch === 0 ? "0 dB" : `${db > 0 ? "+" : ""}${db} dB`;
      vol.appendChild(opt);
    }
    vol.value = String(state.volumeNotch);
    vol.addEventListener("change", () => {
      state.volumeNotch = clamp(
        parseInt(vol.value, 10) || 0,
        VOLUME_MIN,
        VOLUME_MAX
      );
    });
    volWrap.appendChild(vol);

    tools.appendChild(zoomWrap);
    tools.appendChild(volWrap);
    modal.body.appendChild(tools);

    // -- mode-specific footer --
    modal.body.appendChild(opts.buildFooter(core));

    // -- hint line --
    const hint = document.createElement("div");
    hint.className = "trim-hint";
    hint.textContent =
      "Click waveform to move playhead · Space play/pause (from playhead when inside region) · " +
      "s / e check edges · l loop · , . nudge nearest edge";
    modal.body.appendChild(hint);

    // ---- create WaveSurfer ----
    const ws = WaveSurfer.create({
      container: waveContainer,
      // WebAudio backend: playback comes from the same fully-decoded buffer the
      // waveform is drawn from, so seeks/edge previews are sample-accurate. The
      // default media-element backend seeks VBR MP3s via the Xing TOC (a 100-
      // entry estimate), which lands playback early/late relative to the
      // reported currentTime — that skew is why edge previews cut off tails.
      backend: "WebAudio",
      height: 160,
      waveColor: "rgba(255,255,255,0.35)",
      progressColor: "rgba(66,65,179,0.9)",
      cursorColor: "#bf0000",
      cursorWidth: 2,
      normalize: true,
      dragToSeek: true,
      autoScroll: true,
      url: info.audio_url,
    });
    wavesurfer = ws;
    regions = ws.registerPlugin(RegionsPlugin.create());

    ws.on("timeupdate", (t: number) => onTimeupdate(t));
    ws.on("pause", () => updatePlayButton());
    ws.on("play", () => updatePlayButton());
    ws.on("finish", () => stopPlayback());
    ws.on("error", (err: Error) => {
      console.error("[waveform-editor] wavesurfer error:", err);
      showToast("Failed to load audio for editing.", "error");
    });

    ws.on("ready", (duration: number) => {
      if (destroyed) return;
      state.duration = duration || info.duration || 0;

      // Untrimmed sounds / fresh drafts arrive as start/end null → full span.
      const initStart = clamp(info.start ?? 0, 0, state.duration);
      let initEnd = clamp(info.end ?? state.duration, 0, state.duration);
      if (initEnd - initStart < MIN_REGION_LENGTH) {
        initEnd = state.duration;
      }
      state.start = initStart;
      state.end = initEnd;
      state.initialStart = initStart;
      state.initialEnd = initEnd;

      if (startInput) startInput.max = fmt(state.duration);
      if (endInput) endInput.max = fmt(state.duration);

      const created = regions?.addRegion({
        id: "trim",
        start: initStart,
        end: initEnd,
        drag: true,
        resize: true,
        color: "rgba(66,65,179,0.28)",
        minLength: MIN_REGION_LENGTH,
      });
      region = created ?? null;
      syncInputs();
      updatePlayheadReadout(ws.getCurrentTime());

      regions?.on("region-update", () => {
        // Only real pointer drags emit this (programmatic setOptions doesn't),
        // so it doubles as the click-vs-drag discriminator for click-to-seek.
        regionMovedDuringPointer = true;
        if (syncing) return;
        applyRegionToState();
      });
      regions?.on("region-updated", () => {
        if (syncing) return;
        applyRegionToState();
      });
    });
  }

  function handleError(e: unknown): void {
    if (e instanceof ApiError) {
      showToast(e.message, "error", 6000);
    } else {
      showToast("Something went wrong.", "error");
      console.error("[waveform-editor] error:", e);
    }
  }

  const core: WaveformEditorCore = {
    modal,
    getState: () => ({
      duration: state.duration,
      start: state.start,
      end: state.end,
      volumeNotch: state.volumeNotch,
      initialVolumeNotch: state.initialVolumeNotch,
    }),
    isDirty,
    isBusy: () => busy,
    setBusy: (b: boolean) => {
      busy = b;
      modal.modal.classList.toggle("busy", b);
    },
    stopPlayback,
    reload: (load: () => Promise<EditorInfo>) =>
      // Fetch first, tear down after — if the fetch fails, the current
      // waveform stays usable.
      load().then((info) => {
        if (destroyed) return;
        destroyWavesurfer();
        buildUI(info);
      }),
    complete: () => {
      completed = true;
      modal.forceClose();
    },
    handleError,
  };

  // ---- kick off: fetch info, initialise volume (first load only), build ----
  opts
    .load()
    .then((info) => {
      if (destroyed) return;
      state.volumeNotch = clamp(
        Math.round(info.volume_adjust ?? 0),
        VOLUME_MIN,
        VOLUME_MAX
      );
      state.initialVolumeNotch = state.volumeNotch;
      buildUI(info);
    })
    .catch((e) => {
      if (destroyed) return;
      loading.textContent = "";
      const err = document.createElement("div");
      err.className = "trim-error";
      err.textContent =
        e instanceof ApiError ? e.message : "Failed to load the waveform.";
      modal.body.appendChild(err);
      handleError(e);
    });

  return core;
}
