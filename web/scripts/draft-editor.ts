/**
 * Draft-mode editor: trim + name a freshly-downloaded draft BEFORE anything is
 * saved to the sound list. Shares the waveform core with trim-editor.ts; the
 * mode-specific parts are the "Draft" banner, the name-at-the-end footer with a
 * live sanitized-name hint, commit-on-save (409 → inline error, editor stays
 * open), and fire-and-forget draft deletion on dismissal.
 */

import { ApiError, DraftInfo, commitDraft, discardDraft } from "admin-api";
import { buildDraftCommitPayload } from "editor-payloads";
import { stopAllButtonAudio, stopMainAudio } from "audio";
import { showToast } from "toast";
import {
  MIN_REGION_LENGTH,
  WaveformEditorCore,
  openWaveformEditor,
} from "waveform-editor";

const NAME_MAXLEN = 50;

/**
 * Mirror of the server's name sanitization (lowercase, spaces → underscores,
 * illegal chars stripped, max 50) — display-only; the server stays canonical.
 */
export function sanitizeName(raw: string): string {
  return raw
    .trim()
    .toLowerCase()
    .replace(/\s+/g, "_")
    .replace(/[^a-z0-9_-]/g, "")
    .slice(0, NAME_MAXLEN);
}

/** Open the draft editor for a just-created draft. */
export function openDraftEditor(draft: DraftInfo, onSaved?: () => void): void {
  // Pause any soundboard playback while editing (avoids overlapping audio).
  stopMainAudio();
  stopAllButtonAudio();

  let committed = false;
  let nameTouched = false;

  openWaveformEditor({
    title: "New sound (draft)",
    className: "trim-editor draft-editor",
    banner: "Draft — nothing is saved yet",
    confirmDismissMessage:
      "Discard this draft? The downloaded audio will be deleted.",
    load: () =>
      Promise.resolve({
        audio_url: draft.audio_url,
        duration: draft.duration,
        start: null, // region defaults to the full length
        end: null,
        source_title: draft.source_title,
        source_url: draft.source_url,
      }),
    extraDirty: () => nameTouched,
    buildFooter: (c) => buildDraftFooter(c),
    onDismissed: () => {
      if (!committed) discardDraft(draft.draft_id);
    },
  });

  function buildDraftFooter(c: WaveformEditorCore): HTMLElement {
    const footer = document.createElement("div");
    footer.className = "trim-footer draft-footer";

    // -- name field (chosen at the end, once you know what you clipped) --
    const nameField = document.createElement("div");
    nameField.className = "admin-field draft-name-field";

    const label = document.createElement("label");
    label.className = "admin-label";
    label.htmlFor = "draft-sound-name";
    label.textContent = "Name";

    const input = document.createElement("input");
    input.id = "draft-sound-name";
    input.type = "text";
    input.className = "admin-input";
    input.maxLength = NAME_MAXLEN;
    input.autocomplete = "off";
    input.placeholder = "e.g. airhorn";

    const hint = document.createElement("div");
    hint.className = "admin-hint draft-name-hint";
    hint.textContent = " ";

    const errorLine = document.createElement("div");
    errorLine.className = "admin-error";
    errorLine.hidden = true;

    const updateHint = () => {
      const sanitized = sanitizeName(input.value);
      if (input.value && sanitized) {
        hint.textContent = `Will be saved as "${sanitized}"`;
      } else if (input.value && !sanitized) {
        hint.textContent = "Name has no usable characters.";
      } else {
        hint.textContent = " ";
      }
    };

    input.addEventListener("input", () => {
      nameTouched = input.value.trim().length > 0;
      errorLine.hidden = true;
      updateHint();
    });
    input.addEventListener("keydown", (e) => {
      if (e.key === "Enter") {
        e.preventDefault();
        doCommit();
      }
    });

    nameField.appendChild(label);
    nameField.appendChild(input);
    nameField.appendChild(hint);

    // -- actions --
    const actions = document.createElement("div");
    actions.className = "trim-footer draft-actions";

    const spacer = document.createElement("div");
    spacer.className = "trim-footer-spacer";

    const cancelBtn = document.createElement("button");
    cancelBtn.type = "button";
    cancelBtn.className = "trim-btn";
    cancelBtn.textContent = "Cancel";
    cancelBtn.addEventListener("click", () => c.modal.close());

    const saveBtn = document.createElement("button");
    saveBtn.type = "button";
    saveBtn.className = "trim-btn trim-btn-primary";
    saveBtn.textContent = "Save sound";
    saveBtn.addEventListener("click", doCommit);

    actions.appendChild(spacer);
    actions.appendChild(cancelBtn);
    actions.appendChild(saveBtn);

    footer.appendChild(nameField);
    footer.appendChild(errorLine);
    footer.appendChild(actions);

    function showError(msg: string): void {
      errorLine.hidden = false;
      errorLine.textContent = msg;
    }

    function doCommit(): void {
      if (c.isBusy()) return;
      errorLine.hidden = true;

      const name = input.value.trim();
      if (!name || !sanitizeName(name)) {
        showError("Please enter a name.");
        input.focus();
        return;
      }
      const state = c.getState();
      if (state.end - state.start < MIN_REGION_LENGTH) {
        showToast("Region is too short.", "error");
        return;
      }

      c.stopPlayback();
      c.setBusy(true);
      input.disabled = true;
      saveBtn.disabled = true;
      cancelBtn.disabled = true;
      saveBtn.textContent = "Saving…";

      commitDraft(
        draft.draft_id,
        buildDraftCommitPayload(name, state)
      )
        .then((result) => {
          committed = true;
          c.complete();
          // The grid picks the new sound up via the existing WS events.
          showToast(`Added "${result.name}".`, "success");
          onSaved?.();
        })
        .catch((err) => {
          c.setBusy(false);
          input.disabled = false;
          saveBtn.disabled = false;
          cancelBtn.disabled = false;
          saveBtn.textContent = "Save sound";
          if (err instanceof ApiError && err.status === 409) {
            showError(err.message || "That name is already taken.");
            input.focus();
            input.select();
          } else if (err instanceof ApiError) {
            showError(err.message);
          } else {
            showError("Something went wrong. Try again.");
            console.error("[draft-editor] commit error:", err);
          }
        });
    }

    return footer;
  }
}
