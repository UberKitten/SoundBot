/**
 * Admin UI wiring: shows the "+ Add sound" header button only when the user can
 * admin, and exposes the admin context-menu items consumed by context-menu.ts.
 *
 * Everything here is inert for anonymous users — the button is hidden and the
 * context-menu extras return an empty list.
 */

import { openAddSoundModal } from "add-sound-modal";
import { Sound } from "audio";
import { isAdmin, onAuthChange } from "auth";
import { openDeleteModal, openRenameModal } from "sound-actions";
import { openTrimEditor } from "trim-editor";
import { openVideoPopover } from "video-popover";

export interface AdminMenuItem {
  label: string;
  action: () => void;
  danger?: boolean;
}

/** Viewport point the menu was opened at (anchors e.g. the video popover). */
export interface MenuAnchor {
  x: number;
  y: number;
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

/**
 * Build the admin-only context-menu items for a given sound. Returns [] when the
 * current user is not an admin so the base menu is unchanged for everyone else.
 */
export function getAdminMenuItems(
  sound: Sound,
  anchor?: MenuAnchor
): AdminMenuItem[] {
  if (!isAdmin()) return [];
  const items: AdminMenuItem[] = [
    { label: "Edit / Trim…", action: () => openTrimEditor(sound.name) },
  ];
  if (sound.has_video) {
    items.push({
      label: "Watch clip",
      action: () => openVideoPopover(sound.name, anchor),
    });
  }
  items.push(
    { label: "Rename…", action: () => openRenameModal(sound.name) },
    { label: "Delete…", action: () => openDeleteModal(sound.name), danger: true }
  );
  return items;
}

/** Initialise admin UI: toggle the add button with auth state. */
export function initAdminUi(): void {
  onAuthChange((state) => {
    const btn = ensureAddButton();
    btn.hidden = !(state.authenticated && state.can_admin);
  });
}
