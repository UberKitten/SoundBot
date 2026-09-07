/**
 * Admin UI wiring: shows the "+ Add sound" header button only when the user can
 * admin, and exposes the admin context-menu items consumed by context-menu.ts.
 *
 * Everything here is inert for anonymous users — the button is hidden and the
 * context-menu extras return an empty list.
 */

import { openAddSoundModal } from "add-sound-modal";
import {
  ApiError,
  fetchClipEmbedUrl,
  soundVideoDownloadUrl,
} from "admin-api";
import { Sound } from "audio";
import { copyToClipboard } from "clipboard";
import { isAdmin, onAuthChange } from "auth";
import { openDeleteModal, openRenameModal } from "sound-actions";
import { openTrimEditor } from "trim-editor";
import { initVideoControl } from "video-popover";
import { showToast } from "toast";

export interface AdminMenuItem {
  label: string;
  action: () => void;
  danger?: boolean;
}

const ICON_ADD =
  '<svg class="icon" aria-hidden="true" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><path d="M5 12h14"/><path d="M12 5v14"/></svg>';

let addButton: HTMLButtonElement | null = null;

function ensureAddButton(): HTMLButtonElement {
  if (addButton && document.body.contains(addButton)) return addButton;

  const btn = document.createElement("button");
  btn.type = "button";
  btn.id = "admin-add-sound";
  btn.className = "admin-add-btn";
  btn.title = "Add a new sound";
  btn.innerHTML = `${ICON_ADD}<span>Add sound</span>`;
  btn.addEventListener("click", () => openAddSoundModal());

  // Insert before the auth controls if present, else append to header.
  const header = document.querySelector("header");
  const authControls = document.querySelector("#auth-controls");
  if (header) {
    if (authControls) header.insertBefore(btn, authControls);
    else header.appendChild(btn);
  } else {
    document.body.appendChild(btn);
  }
  addButton = btn;
  return btn;
}

function downloadClip(name: string): void {
  const link = document.createElement("a");
  link.href = soundVideoDownloadUrl(name);
  link.download = "";
  document.body.appendChild(link);
  link.click();
  link.remove();
}

async function copyClipEmbedUrl(name: string): Promise<void> {
  try {
    const url = await fetchClipEmbedUrl(name);
    await copyToClipboard(url);
    showToast("Clip embed URL copied.", "success");
  } catch (err) {
    if (err instanceof ApiError) {
      showToast(err.message, "error", 6000);
    } else {
      showToast("Could not copy clip embed URL.", "error");
      console.error("[admin-ui]", err);
    }
  }
}

/**
 * Build the admin-only context-menu items for a given sound. Returns [] when the
 * current user is not an admin so the base menu is unchanged for everyone else.
 */
export function getAdminMenuItems(sound: Sound): AdminMenuItem[] {
  if (!isAdmin()) return [];
  const items: AdminMenuItem[] = [
    { label: "Edit / Trim…", action: () => openTrimEditor(sound.name) },
  ];
  if (sound.has_video) {
    items.push(
      {
        label: "Download clip",
        action: () => downloadClip(sound.name),
      },
      {
        label: "Copy clip embed URL",
        action: () => void copyClipEmbedUrl(sound.name),
      }
    );
  }
  items.push(
    { label: "Rename…", action: () => openRenameModal(sound.name) },
    { label: "Delete…", action: () => openDeleteModal(sound.name), danger: true }
  );
  return items;
}

/** Initialise authenticated header controls and context-menu affordances. */
export function initAdminUi(): void {
  initVideoControl();
  onAuthChange((state) => {
    const btn = ensureAddButton();
    btn.hidden = !(state.authenticated && state.can_admin);
  });
}
