/**
 * Rename + Delete admin flows for a sound. The grid updates itself via the
 * existing WebSocket sound-update events, so these just call the API and toast.
 */

import { ApiError, deleteSound, patchSound } from "admin-api";
import { openModal } from "modal";
import { showToast } from "toast";

function reportError(err: unknown, fallback: string): void {
  if (err instanceof ApiError) {
    showToast(err.message, "error", 6000);
  } else {
    showToast(fallback, "error");
    console.error("[sound-actions]", err);
  }
}

export function openRenameModal(name: string, onDone?: () => void): void {
  const modal = openModal({ title: `Rename "${name}"`, className: "rename-sound" });

  const form = document.createElement("form");
  form.className = "admin-form";
  form.noValidate = true;

  const field = document.createElement("div");
  field.className = "admin-field";
  const label = document.createElement("label");
  label.className = "admin-label";
  label.htmlFor = "rename-input";
  label.textContent = "New name";
  const input = document.createElement("input");
  input.id = "rename-input";
  input.type = "text";
  input.className = "admin-input";
  input.maxLength = 50;
  input.autocomplete = "off";
  input.required = true;
  input.value = name;
  const hint = document.createElement("div");
  hint.className = "admin-hint";
  hint.textContent = "Sanitized & lowercased by the server.";
  field.appendChild(label);
  field.appendChild(input);
  field.appendChild(hint);

  const errorLine = document.createElement("div");
  errorLine.className = "admin-error";
  errorLine.hidden = true;

  const actions = document.createElement("div");
  actions.className = "admin-actions";
  const cancelBtn = document.createElement("button");
  cancelBtn.type = "button";
  cancelBtn.className = "trim-btn";
  cancelBtn.textContent = "Cancel";
  cancelBtn.addEventListener("click", () => modal.close());
  const saveBtn = document.createElement("button");
  saveBtn.type = "submit";
  saveBtn.className = "trim-btn trim-btn-primary";
  saveBtn.textContent = "Rename";
  actions.appendChild(cancelBtn);
  actions.appendChild(saveBtn);

  form.appendChild(field);
  form.appendChild(errorLine);
  form.appendChild(actions);
  modal.body.appendChild(form);

  let busy = false;
  form.addEventListener("submit", (e) => {
    e.preventDefault();
    if (busy) return;
    errorLine.hidden = true;
    const newName = input.value.trim();
    if (!newName) {
      errorLine.hidden = false;
      errorLine.textContent = "Please enter a name.";
      return;
    }
    if (newName === name) {
      modal.close();
      return;
    }
    busy = true;
    input.disabled = true;
    saveBtn.disabled = true;
    cancelBtn.disabled = true;
    saveBtn.textContent = "Renaming…";

    patchSound(name, { new_name: newName })
      .then((result) => {
        modal.forceClose();
        showToast(`Renamed to "${result.name}".`, "success");
        onDone?.();
      })
      .catch((err) => {
        busy = false;
        input.disabled = false;
        saveBtn.disabled = false;
        cancelBtn.disabled = false;
        saveBtn.textContent = "Rename";
        errorLine.hidden = false;
        errorLine.textContent =
          err instanceof ApiError ? err.message : "Rename failed.";
        if (!(err instanceof ApiError)) console.error("[rename]", err);
      });
  });
}

export function openDeleteModal(name: string, onDone?: () => void): void {
  const modal = openModal({ title: `Delete "${name}"?`, className: "delete-sound" });

  const body = document.createElement("div");
  body.className = "admin-form";

  const warning = document.createElement("p");
  warning.className = "admin-warning";
  warning.textContent = `This permanently deletes the files for "${name}". This cannot be undone.`;

  const errorLine = document.createElement("div");
  errorLine.className = "admin-error";
  errorLine.hidden = true;

  const actions = document.createElement("div");
  actions.className = "admin-actions";
  const cancelBtn = document.createElement("button");
  cancelBtn.type = "button";
  cancelBtn.className = "trim-btn";
  cancelBtn.textContent = "Cancel";
  cancelBtn.addEventListener("click", () => modal.close());
  const deleteBtn = document.createElement("button");
  deleteBtn.type = "button";
  deleteBtn.className = "trim-btn trim-btn-danger";
  deleteBtn.textContent = "Delete";
  actions.appendChild(cancelBtn);
  actions.appendChild(deleteBtn);

  body.appendChild(warning);
  body.appendChild(errorLine);
  body.appendChild(actions);
  modal.body.appendChild(body);

  let busy = false;
  deleteBtn.addEventListener("click", () => {
    if (busy) return;
    busy = true;
    errorLine.hidden = true;
    deleteBtn.disabled = true;
    cancelBtn.disabled = true;
    deleteBtn.textContent = "Deleting…";

    deleteSound(name)
      .then(() => {
        modal.forceClose();
        showToast(`Deleted "${name}".`, "success");
        onDone?.();
      })
      .catch((err) => {
        busy = false;
        deleteBtn.disabled = false;
        cancelBtn.disabled = false;
        deleteBtn.textContent = "Delete";
        errorLine.hidden = false;
        errorLine.textContent =
          err instanceof ApiError ? err.message : "Delete failed.";
        if (!(err instanceof ApiError)) console.error("[delete]", err);
      });
  });
}
