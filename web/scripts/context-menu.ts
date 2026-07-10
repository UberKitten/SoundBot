import { getAdminMenuItems } from "admin-ui";
import { Sound, SoundGroup, getSoundPath } from "audio";
import { copyToClipboard } from "clipboard";
import { getRandomPrefix } from "config";

interface MenuItem {
  label: string;
  action: () => void;
  danger?: boolean;
  separator?: boolean;
}

let activeMenu: HTMLElement | null = null;
let activeModal: HTMLElement | null = null;

function closeMenu() {
  if (activeMenu) {
    activeMenu.remove();
    activeMenu = null;
  }
}

function closeModal() {
  if (activeModal) {
    activeModal.remove();
    activeModal = null;
  }
}

document.addEventListener("click", closeMenu);
document.addEventListener("contextmenu", (e) => {
  // Close menu if right-clicking outside a sound button or group button
  const target = e.target as HTMLElement;
  if (!target.closest("soundboard-button") && !target.closest(".group-button")) {
    closeMenu();
  }
});

document.addEventListener("keydown", (e) => {
  if (e.key === "Escape") {
    closeMenu();
    closeModal();
  }
});

export function showContextMenu(e: MouseEvent, sound: Sound) {
  e.preventDefault();
  showContextMenuAt(e.clientX, e.clientY, sound);
}

/** Open the sound menu at viewport coordinates (mouse or touch long-press). */
export function showContextMenuAt(x: number, y: number, sound: Sound) {
  closeMenu();

  const menu = document.createElement("div");
  menu.className = "context-menu";

  const items: MenuItem[] = [
    { label: "Copy Command", action: () => copyCommand(sound) },
    { label: "Copy Link", action: () => copyLink(sound) },
    { label: "Download", action: () => downloadSound(sound) },
    { label: "Properties", action: () => showProperties(sound) },
  ];

  // Append admin-only actions (empty for non-admins).
  const adminItems = getAdminMenuItems(sound, { x, y });
  if (adminItems.length > 0) {
    items.push({ label: "", action: () => {}, separator: true });
    for (const adminItem of adminItems) items.push(adminItem);
  }

  renderMenuItems(menu, items);

  document.body.appendChild(menu);
  activeMenu = menu;

  positionMenu(menu, x, y);
}

function renderMenuItems(menu: HTMLElement, items: MenuItem[]) {
  for (const item of items) {
    if (item.separator) {
      const sep = document.createElement("div");
      sep.className = "context-menu-separator";
      menu.appendChild(sep);
      continue;
    }
    const el = document.createElement("div");
    el.className = "context-menu-item";
    if (item.danger) el.classList.add("context-menu-item-danger");
    el.textContent = item.label;
    el.addEventListener("click", (clickEvent) => {
      clickEvent.stopPropagation();
      closeMenu();
      item.action();
    });
    menu.appendChild(el);
  }
}

function positionMenu(menu: HTMLElement, atX: number, atY: number) {
  // Position menu, keeping it within viewport (clamped both ways so it stays
  // on-screen even at touch points near edges of small screens).
  const rect = menu.getBoundingClientRect();
  let x = atX;
  let y = atY;

  if (x + rect.width > window.innerWidth) {
    x = window.innerWidth - rect.width - 4;
  }
  if (y + rect.height > window.innerHeight) {
    y = window.innerHeight - rect.height - 4;
  }
  x = Math.max(4, x);
  y = Math.max(4, y);

  menu.style.left = `${x}px`;
  menu.style.top = `${y}px`;
}

export function showGroupContextMenu(e: MouseEvent, group: SoundGroup) {
  e.preventDefault();
  showGroupContextMenuAt(e.clientX, e.clientY, group);
}

/** Open the group menu at viewport coordinates (mouse or touch long-press). */
export function showGroupContextMenuAt(x: number, y: number, group: SoundGroup) {
  closeMenu();

  const menu = document.createElement("div");
  menu.className = "context-menu";

  const items: MenuItem[] = [
    { label: "Copy Command", action: () => copyGroupCommand(group) },
    { label: "Copy Link", action: () => copyGroupLink(group) },
    { label: "Properties", action: () => showGroupProperties(group) },
  ];

  renderMenuItems(menu, items);

  document.body.appendChild(menu);
  activeMenu = menu;

  positionMenu(menu, x, y);
}

function copyGroupCommand(group: SoundGroup) {
  const command = `${getRandomPrefix()}${group.name}`;
  copyToClipboard(command);
}

function copyGroupLink(group: SoundGroup) {
  const url = new URL(window.location.origin);
  url.searchParams.set("sound", group.name);
  copyToClipboard(url.href);
}

function copyCommand(sound: Sound) {
  const command = `${getRandomPrefix()}${sound.name}`;
  copyToClipboard(command);
}

function copyLink(sound: Sound) {
  const url = new URL(window.location.origin);
  url.searchParams.set("sound", sound.name);
  copyToClipboard(url.href);
}

function downloadSound(sound: Sound) {
  const path = getSoundPath(sound);
  if (!path) return;

  const a = document.createElement("a");
  a.href = path;
  a.download = sound.name;
  document.body.appendChild(a);
  a.click();
  a.remove();
}

function showProperties(sound: Sound) {
  closeModal();

  const overlay = document.createElement("div");
  overlay.className = "modal-overlay";
  overlay.addEventListener("click", (e) => {
    if (e.target === overlay) closeModal();
  });

  const modal = document.createElement("div");
  modal.className = "modal";

  const header = document.createElement("div");
  header.className = "modal-header";

  const title = document.createElement("h2");
  title.textContent = sound.name;

  const closeBtn = document.createElement("button");
  closeBtn.className = "modal-close";
  closeBtn.textContent = "\u00d7";
  closeBtn.addEventListener("click", closeModal);

  header.appendChild(title);
  header.appendChild(closeBtn);
  modal.appendChild(header);

  const body = document.createElement("div");
  body.className = "modal-body";

  const props: [string, string | HTMLElement | null][] = [
    ["Aliases", sound.aliases?.length ? sound.aliases.join(", ") : null],
    ["Source Title", sound.source_title],
    ["Source URL", sound.source_url ? createLink(sound.source_url) : null],
    ["Volume", sound.volume != null && sound.volume !== 1 ? `${sound.volume}` : null],
    ["Trim Start", sound.trim_start !== null ? `${sound.trim_start}s` : null],
    ["Trim End", sound.trim_end !== null ? `${sound.trim_end}s` : null],
    ["Source Duration", sound.source_duration !== null ? `${sound.source_duration}s` : null],
    ["Discord Plays", `${sound.discord_plays}`],
    ["Web Plays", `${sound.web_plays}`],
    ["Created", sound.created ? formatDate(sound.created) : null],
    ["Modified", sound.modified ? formatDate(sound.modified) : null],
  ];

  for (const [label, value] of props) {
    if (value === null) continue;

    const row = document.createElement("div");
    row.className = "modal-row";

    const labelEl = document.createElement("span");
    labelEl.className = "modal-label";
    labelEl.textContent = label;

    const valueEl = document.createElement("span");
    valueEl.className = "modal-value";
    if (typeof value === "string") {
      valueEl.textContent = value;
    } else {
      valueEl.appendChild(value);
    }

    row.appendChild(labelEl);
    row.appendChild(valueEl);
    body.appendChild(row);
  }

  modal.appendChild(body);
  overlay.appendChild(modal);
  document.body.appendChild(overlay);
  activeModal = overlay;
}

function showGroupProperties(group: SoundGroup) {
  closeModal();

  const overlay = document.createElement("div");
  overlay.className = "modal-overlay";
  overlay.addEventListener("click", (e) => {
    if (e.target === overlay) closeModal();
  });

  const modal = document.createElement("div");
  modal.className = "modal";

  const header = document.createElement("div");
  header.className = "modal-header";

  const title = document.createElement("h2");
  title.textContent = `🎲 ${group.name}`;

  const closeBtn = document.createElement("button");
  closeBtn.className = "modal-close";
  closeBtn.textContent = "\u00d7";
  closeBtn.addEventListener("click", closeModal);

  header.appendChild(title);
  header.appendChild(closeBtn);
  modal.appendChild(header);

  const body = document.createElement("div");
  body.className = "modal-body";

  const props: [string, string | null][] = [
    ["Members", group.members.length > 0 ? group.members.join(", ") : "Empty"],
    ["Member Count", `${group.members.length}`],
    ["Discord Plays", `${group.discord_plays}`],
    ["Web Plays", `${group.web_plays}`],
    ["Created", group.created ? formatDate(group.created) : null],
  ];

  for (const [label, value] of props) {
    if (value === null) continue;

    const row = document.createElement("div");
    row.className = "modal-row";

    const labelEl = document.createElement("span");
    labelEl.className = "modal-label";
    labelEl.textContent = label;

    const valueEl = document.createElement("span");
    valueEl.className = "modal-value";
    valueEl.textContent = value;

    row.appendChild(labelEl);
    row.appendChild(valueEl);
    body.appendChild(row);
  }

  modal.appendChild(body);
  overlay.appendChild(modal);
  document.body.appendChild(overlay);
  activeModal = overlay;
}

function createLink(url: string): HTMLAnchorElement {
  const a = document.createElement("a");
  a.href = url;
  a.textContent = url;
  a.target = "_blank";
  a.rel = "noopener noreferrer";
  return a;
}

function formatDate(dateStr: string): string {
  return new Date(dateStr).toLocaleString(undefined, {
    year: "numeric",
    month: "long",
    day: "numeric",
    hour: "numeric",
    minute: "2-digit",
  });
}
