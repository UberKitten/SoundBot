/**
 * Trim editor for an EXISTING sound — a thin mode wrapper around the shared
 * waveform-editor core. Adds the redownload / cancel / save footer and saves
 * via PUT /trim. (The draft add-sound flow lives in draft-editor.ts.)
 */

import { stopAllButtonAudio, stopMainAudio } from "audio";
import { fetchWaveform, redownloadSound, saveTrim } from "admin-api";
import { buildTrimPayload } from "editor-payloads";
import { showToast } from "toast";
import {
  MIN_REGION_LENGTH,
  WaveformEditorCore,
  openWaveformEditor,
} from "waveform-editor";

/**
 * Open the trim editor for `name`. `onSaved` fires after a successful save.
 * Returns immediately; the modal drives the rest of the flow.
 */
export function openTrimEditor(name: string, onSaved?: () => void): void {
  // Pause any soundboard playback while editing (avoids overlapping audio).
  stopMainAudio();
  stopAllButtonAudio();

  openWaveformEditor({
    title: name,
    className: "trim-editor",
    confirmDismissMessage: "Discard unsaved trim changes?",
    load: () => fetchWaveform(name),
    buildFooter: (c) => buildFooter(c, name, onSaved),
  });
}

function buildFooter(
  core: WaveformEditorCore,
  name: string,
  onSaved?: () => void
): HTMLElement {
  const footer = document.createElement("div");
  footer.className = "trim-footer";

  const redownload = document.createElement("button");
  redownload.type = "button";
  redownload.className = "trim-btn trim-btn-subtle";
  redownload.title =
    "Re-download the original source and regenerate the waveform";
  redownload.textContent = "Redownload original";
  redownload.addEventListener("click", () => doRedownload(core, name, redownload));

  const spacer = document.createElement("div");
  spacer.className = "trim-footer-spacer";

  const cancelBtn = document.createElement("button");
  cancelBtn.type = "button";
  cancelBtn.className = "trim-btn";
  cancelBtn.textContent = "Cancel";
  cancelBtn.addEventListener("click", () => core.modal.close());

  const saveBtn = document.createElement("button");
  saveBtn.type = "button";
  saveBtn.className = "trim-btn trim-btn-primary";
  saveBtn.textContent = "Save";
  saveBtn.addEventListener("click", () => doSave(core, name, saveBtn, onSaved));

  footer.appendChild(redownload);
  footer.appendChild(spacer);
  footer.appendChild(cancelBtn);
  footer.appendChild(saveBtn);
  return footer;
}

function doRedownload(
  core: WaveformEditorCore,
  name: string,
  btn: HTMLButtonElement
): void {
  if (core.isBusy()) return;
  if (
    !window.confirm(
      "Re-download the original source? This replaces the source file."
    )
  ) {
    return;
  }
  const original = btn.textContent;
  btn.disabled = true;
  btn.textContent = "Redownloading…";
  redownloadSound(name)
    .then(() => core.reload(() => fetchWaveform(name)))
    .then(() => showToast("Re-downloaded original.", "success"))
    .catch((e) => core.handleError(e))
    .finally(() => {
      btn.disabled = false;
      btn.textContent = original;
    });
}

function doSave(
  core: WaveformEditorCore,
  name: string,
  btn: HTMLButtonElement,
  onSaved?: () => void
): void {
  if (core.isBusy()) return;
  const state = core.getState();
  if (state.end - state.start < MIN_REGION_LENGTH) {
    showToast("Region is too short.", "error");
    return;
  }
  core.setBusy(true);
  btn.disabled = true;
  const original = btn.textContent;
  btn.textContent = "Saving…";

  saveTrim(name, buildTrimPayload(state))
    .then(() => {
      core.complete();
      showToast("Trim saved.", "success");
      onSaved?.();
    })
    .catch((e) => {
      core.setBusy(false);
      btn.disabled = false;
      btn.textContent = original;
      core.handleError(e);
    });
}
