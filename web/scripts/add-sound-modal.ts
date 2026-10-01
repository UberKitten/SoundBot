/**
 * Add-sound modal, draft-first: collects ONLY a URL, POSTs to the drafts API
 * (a slow call — the server downloads via yt-dlp), and on success opens the
 * draft editor where the sound is trimmed and named BEFORE anything is saved.
 */

import { ApiError, createDraft, discardDraft } from "admin-api";
import { openDraftEditor } from "draft-editor";
import { openModal } from "modal";
function normalizeSourceUrl(value: string): string | null {
  try {
    const parsed = new URL(value);
    if (
      (parsed.protocol !== "http:" && parsed.protocol !== "https:") ||
      !parsed.hostname
    ) {
      return null;
    }
    return parsed.href;
  } catch {
    return null;
  }
}

export function openAddSoundModal(onAdded?: () => void): void {
  let submitting = false;
  let dismissed = false;

  const modal = openModal({
    title: "Add sound",
    className: "add-sound",
    beforeClose: () => {
      if (submitting) {
        return window.confirm(
          "Still downloading — abandon adding this sound?"
        );
      }
      return true;
    },
    onClosed: () => {
      dismissed = true;
    },
  });

  const form = document.createElement("form");
  form.className = "admin-form";
  form.noValidate = true;

  // -- explainer --
  const explainer = document.createElement("p");
  explainer.className = "admin-explainer";
  explainer.textContent =
    "Paste a video/audio URL — you'll trim and name it before anything is saved.";

  // -- url field --
  const urlField = document.createElement("div");
  urlField.className = "admin-field";
  const urlLabel = document.createElement("label");
  urlLabel.className = "admin-label";
  urlLabel.textContent = "URL";
  urlLabel.htmlFor = "add-sound-url";
  const urlInput = document.createElement("input");
  urlInput.id = "add-sound-url";
  urlInput.type = "url";
  urlInput.className = "admin-input";
  urlInput.autocomplete = "off";
  urlInput.required = true;
  urlInput.placeholder = "https://example.com/video";
  urlInput.setAttribute("aria-describedby", "add-sound-url-hint");
  const urlHint = document.createElement("div");
  urlHint.id = "add-sound-url-hint";
  urlHint.className = "admin-hint";
  urlHint.textContent = "Use a complete http:// or https:// link.";
  urlField.appendChild(urlLabel);
  urlField.appendChild(urlInput);
  urlField.appendChild(urlHint);

  // -- error line --
  const errorLine = document.createElement("div");
  errorLine.className = "admin-error";
  errorLine.hidden = true;
  errorLine.setAttribute("role", "alert");

  // -- actions --
  const actions = document.createElement("div");
  actions.className = "admin-actions";

  const status = document.createElement("div");
  status.className = "admin-status";
  status.hidden = true;
  status.setAttribute("role", "status");
  status.setAttribute("aria-live", "polite");

  const cancelBtn = document.createElement("button");
  cancelBtn.type = "button";
  cancelBtn.className = "trim-btn";
  cancelBtn.textContent = "Cancel";
  cancelBtn.addEventListener("click", () => modal.close());

  const submitBtn = document.createElement("button");
  submitBtn.type = "submit";
  submitBtn.className = "trim-btn trim-btn-primary";
  submitBtn.textContent = "Fetch & edit";

  actions.appendChild(status);
  actions.appendChild(cancelBtn);
  actions.appendChild(submitBtn);

  form.appendChild(explainer);
  form.appendChild(urlField);
  form.appendChild(errorLine);
  form.appendChild(actions);
  modal.body.appendChild(form);

  const setBusy = (busy: boolean) => {
    submitting = busy;
    urlInput.disabled = busy;
    submitBtn.disabled = busy;
    cancelBtn.disabled = busy;
    submitBtn.textContent = busy ? "Preparing…" : "Fetch & edit";
    status.hidden = !busy;
    if (busy) {
      status.innerHTML =
        '<span class="admin-spinner" aria-hidden="true"></span><span>Fetching the source and preparing audio… This may take a minute.</span>';
      modal.modal.classList.add("busy");
    } else {
      modal.modal.classList.remove("busy");
    }
  };

  const showError = (msg: string, invalidUrl = false) => {
    errorLine.hidden = false;
    errorLine.textContent = msg;
    if (invalidUrl) urlInput.setAttribute("aria-invalid", "true");
  };

  const validateUrl = (showMessage: boolean): string | null => {
    const value = urlInput.value.trim();
    if (!value) {
      if (showMessage) showError("Please enter a URL.", true);
      return null;
    }
    const normalized = normalizeSourceUrl(value);
    if (!normalized) {
      if (showMessage) {
        showError("Enter a complete http:// or https:// URL.", true);
      }
      return null;
    }
    urlInput.removeAttribute("aria-invalid");
    if (!submitting) errorLine.hidden = true;
    return normalized;
  };

  urlInput.addEventListener("input", () => {
    if (!urlInput.value.trim()) {
      urlInput.removeAttribute("aria-invalid");
      errorLine.hidden = true;
      return;
    }
    validateUrl(true);
  });

  form.addEventListener("submit", (e) => {
    e.preventDefault();
    if (submitting) return;
    errorLine.hidden = true;

    const url = validateUrl(true);
    if (!url) {
      urlInput.focus();
      return;
    }

    setBusy(true);
    createDraft(url)
      .then((draft) => {
        if (dismissed) {
          // User abandoned the modal mid-download — clean up the draft.
          discardDraft(draft.draft_id);
          return;
        }
        // Success — close this modal and jump into the draft editor.
        submitting = false;
        modal.forceClose();
        openDraftEditor(draft, onAdded, url);
      })
      .catch((err) => {
        if (dismissed) return;
        setBusy(false);
        if (err instanceof ApiError) {
          showError(err.message);
        } else {
          showError("Something went wrong. Try again.");
          console.error("[add-sound] error:", err);
        }
      });
  });
}
