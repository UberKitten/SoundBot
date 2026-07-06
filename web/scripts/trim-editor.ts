/**
 * Trim editor modal — the admin centerpiece.
 *
 * Loads the full-length (pre-trim) audio into a WaveSurfer instance with a single
 * draggable/resizable Regions region spanning [start, end]. Provides edge-check
 * playback, loop, numeric inputs, nudge buttons, zoom, and a volume notch, plus
 * keyboard shortcuts (space / s / e / l). Saves via PUT /trim.
 */

import { stopAllButtonAudio, stopMainAudio } from "audio";
import {
  ApiError,
  WaveformInfo,
  fetchWaveform,
  redownloadSound,
  saveTrim,
} from "admin-api";
import { openModal, ModalController } from "modal";
import { showToast } from "toast";
import WaveSurfer from "wavesurfer";
import RegionsPlugin, { Region } from "wavesurfer-regions";

const EDGE_PREVIEW_SECONDS = 1.5;
const MIN_REGION_LENGTH = 0.05;
const VOLUME_MIN = -5;
const VOLUME_MAX = 3;

interface EditorState {
  name: string;
  duration: number;
  start: number;
  end: number;
  /** volume as an integer notch; dB = notch * 3. */
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

/**
 * Open the trim editor for `name`. `onSaved` fires after a successful save.
 * Returns immediately; the modal drives the rest of the flow.
 */
export function openTrimEditor(name: string, onSaved?: () => void): void {
  // Pause any soundboard playback while editing (avoids overlapping audio).
  stopMainAudio();
  stopAllButtonAudio();

  let wavesurfer: WaveSurfer | null = null;
  let region: Region | null = null;
  let regions: RegionsPlugin | null = null;
  let loop = false;
  let saving = false;
  let destroyed = false;
  // Guards the region<->input sync loop against feedback.
  let syncing = false;
  // When set, playback auto-stops once currentTime passes this point.
  let playStopAt: number | null = null;

  const state: EditorState = {
    name,
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
    state.volumeNotch !== state.initialVolumeNotch;

  const modal: ModalController = openModal({
    title: name,
    className: "trim-editor",
    beforeClose: () => {
      if (saving) return false;
      if (isDirty()) {
        return window.confirm("Discard unsaved trim changes?");
      }
      return true;
    },
    onClosed: () => {
      destroyed = true;
      document.removeEventListener("keydown", onKeydown, true);
      if (wavesurfer) {
        try {
          wavesurfer.destroy();
        } catch {
          /* ignore */
        }
        wavesurfer = null;
      }
    },
  });

  // ---- initial "loading" body ----
  const loading = document.createElement("div");
  loading.className = "trim-loading";
  loading.textContent = "preparing waveform…";
  modal.body.appendChild(loading);

  // ---- keyboard shortcuts (ignored while typing in inputs) ----
  const onKeydown = (e: KeyboardEvent) => {
    if (destroyed) return;
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
    playRange(state.start, state.end);
  }

  function playRange(from: number, to: number): void {
    if (!wavesurfer || state.duration <= 0) return;
    const start = clamp(from, 0, state.duration);
    const end = clamp(to, start + 0.001, state.duration);
    playStopAt = end;
    wavesurfer.setTime(start);
    wavesurfer.play().catch(() => {
      /* autoplay guards — ignore */
    });
    updatePlayButton();
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

  function buildUI(info: WaveformInfo): void {
    modal.body.innerHTML = "";

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

    // -- primary transport row --
    const transport = document.createElement("div");
    transport.className = "trim-transport";

    playBtn = document.createElement("button");
    playBtn.type = "button";
    playBtn.className = "trim-btn trim-btn-primary";
    playBtn.title = "Play region (Space)";
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

    // -- footer actions --
    const footer = document.createElement("div");
    footer.className = "trim-footer";

    const redownload = document.createElement("button");
    redownload.type = "button";
    redownload.className = "trim-btn trim-btn-subtle";
    redownload.title = "Re-download the original source and regenerate the waveform";
    redownload.textContent = "Redownload original";
    redownload.addEventListener("click", () => doRedownload(redownload));

    const spacer = document.createElement("div");
    spacer.className = "trim-footer-spacer";

    const cancelBtn = document.createElement("button");
    cancelBtn.type = "button";
    cancelBtn.className = "trim-btn";
    cancelBtn.textContent = "Cancel";
    cancelBtn.addEventListener("click", () => modal.close());

    const saveBtn = document.createElement("button");
    saveBtn.type = "button";
    saveBtn.className = "trim-btn trim-btn-primary";
    saveBtn.textContent = "Save";
    saveBtn.addEventListener("click", () => doSave(saveBtn));

    footer.appendChild(redownload);
    footer.appendChild(spacer);
    footer.appendChild(cancelBtn);
    footer.appendChild(saveBtn);
    modal.body.appendChild(footer);

    // -- hint line --
    const hint = document.createElement("div");
    hint.className = "trim-hint";
    hint.textContent =
      "Space play/pause · s / e check edges · l loop · , . nudge nearest edge";
    modal.body.appendChild(hint);

    // ---- create WaveSurfer ----
    const ws = WaveSurfer.create({
      container: waveContainer,
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
      console.error("[trim] wavesurfer error:", err);
      showToast("Failed to load audio for editing.", "error");
    });

    ws.on("ready", (duration: number) => {
      if (destroyed) return;
      state.duration = duration || info.duration || 0;

      // Untrimmed sounds arrive as start=null / end=null → full span.
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

      regions?.on("region-update", () => {
        if (syncing) return;
        applyRegionToState();
      });
      regions?.on("region-updated", () => {
        if (syncing) return;
        applyRegionToState();
      });
    });
  }

  function doRedownload(btn: HTMLButtonElement): void {
    if (saving) return;
    if (!window.confirm("Re-download the original source? This replaces the source file.")) {
      return;
    }
    const original = btn.textContent;
    btn.disabled = true;
    btn.textContent = "Redownloading…";
    redownloadSound(state.name)
      .then(() => reloadWaveform())
      .then(() => showToast("Re-downloaded original.", "success"))
      .catch((e) => handleError(e))
      .finally(() => {
        btn.disabled = false;
        btn.textContent = original;
      });
  }

  function reloadWaveform(): Promise<void> {
    // Destroy + rebuild against the fresh mp3 (mtime/url changes on redownload).
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
    return fetchWaveform(state.name).then((info) => {
      if (destroyed) return;
      buildUI(info);
    });
  }

  function doSave(btn: HTMLButtonElement): void {
    if (saving || destroyed) return;
    if (state.end - state.start < MIN_REGION_LENGTH) {
      showToast("Region is too short.", "error");
      return;
    }
    saving = true;
    btn.disabled = true;
    const original = btn.textContent;
    btn.textContent = "Saving…";
    modal.modal.classList.add("busy");

    // Only send volume_adjust when it actually changed.
    const payload = {
      start: state.start,
      end: state.end,
      ...(state.volumeNotch !== state.initialVolumeNotch
        ? { volume_adjust: state.volumeNotch }
        : {}),
    };

    saveTrim(state.name, payload)
      .then(() => {
        state.initialStart = state.start;
        state.initialEnd = state.end;
        state.initialVolumeNotch = state.volumeNotch;
        saving = false;
        modal.forceClose();
        showToast("Trim saved.", "success");
        onSaved?.();
      })
      .catch((e) => {
        saving = false;
        btn.disabled = false;
        btn.textContent = original;
        modal.modal.classList.remove("busy");
        handleError(e);
      });
  }

  function handleError(e: unknown): void {
    if (e instanceof ApiError) {
      showToast(e.message, "error", 6000);
    } else {
      showToast("Something went wrong.", "error");
      console.error("[trim] error:", e);
    }
  }

  // ---- kick off: fetch waveform info ----
  fetchWaveform(name)
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
}
