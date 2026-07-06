/**
 * Add-sound modal. Collects name + URL, POSTs to the admin API (a slow call —
 * the server downloads via yt-dlp), and on success immediately opens the trim
 * editor for the returned canonical name.
 */

import { ApiError, addSound } from "admin-api";
import { openModal } from "modal";
import { showToast } from "toast";
import { openTrimEditor } from "trim-editor";

const NAME_MAXLEN = 50;

export function openAddSoundModal(onAdded?: () => void): void {
  const modal = openModal({ title: "Add sound", className: "add-sound" });

  const form = document.createElement("form");
  form.className = "admin-form";
  form.noValidate = true;

  // -- name field --
  const nameField = document.createElement("div");
  nameField.className = "admin-field";
  const nameLabel = document.createElement("label");
  nameLabel.className = "admin-label";
  nameLabel.textContent = "Name";
  nameLabel.htmlFor = "add-sound-name";
  const nameInput = document.createElement("input");
  nameInput.id = "add-sound-name";
  nameInput.type = "text";
  nameInput.className = "admin-input";
  nameInput.maxLength = NAME_MAXLEN;
  nameInput.autocomplete = "off";
  nameInput.required = true;
  nameInput.placeholder = "e.g. airhorn";
  const nameHint = document.createElement("div");
  nameHint.className = "admin-hint";
  nameHint.textContent = `Up to ${NAME_MAXLEN} chars; sanitized & lowercased by the server.`;
  nameField.appendChild(nameLabel);
  nameField.appendChild(nameInput);
  nameField.appendChild(nameHint);

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
  urlInput.placeholder = "https://…";
  urlField.appendChild(urlLabel);
  urlField.appendChild(urlInput);

  // -- error line --
  const errorLine = document.createElement("div");
  errorLine.className = "admin-error";
  errorLine.hidden = true;

  // -- actions --
  const actions = document.createElement("div");
  actions.className = "admin-actions";

  const status = document.createElement("div");
  status.className = "admin-status";
  status.hidden = true;

  const cancelBtn = document.createElement("button");
  cancelBtn.type = "button";
  cancelBtn.className = "trim-btn";
  cancelBtn.textContent = "Cancel";
  cancelBtn.addEventListener("click", () => modal.close());

  const submitBtn = document.createElement("button");
  submitBtn.type = "submit";
  submitBtn.className = "trim-btn trim-btn-primary";
  submitBtn.textContent = "Add";

  actions.appendChild(status);
  actions.appendChild(cancelBtn);
  actions.appendChild(submitBtn);

  form.appendChild(nameField);
  form.appendChild(urlField);
  form.appendChild(errorLine);
  form.appendChild(actions);
  modal.body.appendChild(form);

  let submitting = false;

  const setBusy = (busy: boolean) => {
    submitting = busy;
    nameInput.disabled = busy;
    urlInput.disabled = busy;
    submitBtn.disabled = busy;
    cancelBtn.disabled = busy;
    submitBtn.textContent = busy ? "Adding…" : "Add";
    status.hidden = !busy;
    if (busy) {
      status.innerHTML =
        '<span class="admin-spinner" aria-hidden="true"></span>downloading & processing — can take a minute…';
      modal.modal.classList.add("busy");
    } else {
      modal.modal.classList.remove("busy");
    }
  };

  const showError = (msg: string) => {
    errorLine.hidden = false;
    errorLine.textContent = msg;
  };

  form.addEventListener("submit", (e) => {
    e.preventDefault();
    if (submitting) return;
    errorLine.hidden = true;

    const name = nameInput.value.trim();
    const url = urlInput.value.trim();
    if (!name) {
      showError("Please enter a name.");
      nameInput.focus();
      return;
    }
    if (!url) {
      showError("Please enter a URL.");
      urlInput.focus();
      return;
    }

    setBusy(true);
    addSound({ name, url })
      .then((result) => {
        // Success — close this modal and jump straight into trimming.
        modal.forceClose();
        showToast(`Added "${result.name}".`, "success");
        onAdded?.();
        openTrimEditor(result.name, onAdded);
      })
      .catch((err) => {
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
