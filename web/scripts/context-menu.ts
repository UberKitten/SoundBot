import { Sound, getSoundPath } from "audio";
import { copyToClipboard } from "clipboard";
import { getRandomPrefix } from "config";

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
  // Close menu if right-clicking outside a sound button
  if (!(e.target as HTMLElement).closest("soundboard-button")) {
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
  closeMenu();

  const menu = document.createElement("div");
  menu.className = "context-menu";

  const items = [
    { label: "Copy Command", action: () => copyCommand(sound) },
    { label: "Download", action: () => downloadSound(sound) },
    { label: "Properties", action: () => showProperties(sound) },
  ];

  for (const item of items) {
    const el = document.createElement("div");
    el.className = "context-menu-item";
    el.textContent = item.label;
    el.addEventListener("click", (clickEvent) => {
      clickEvent.stopPropagation();
      closeMenu();
      item.action();
    });
    menu.appendChild(el);
  }

  document.body.appendChild(menu);
  activeMenu = menu;

  // Position menu, keeping it within viewport
  const rect = menu.getBoundingClientRect();
  let x = e.clientX;
  let y = e.clientY;

  if (x + rect.width > window.innerWidth) {
    x = window.innerWidth - rect.width - 4;
  }
  if (y + rect.height > window.innerHeight) {
    y = window.innerHeight - rect.height - 4;
  }

  menu.style.left = `${x}px`;
  menu.style.top = `${y}px`;
}

function copyCommand(sound: Sound) {
  const command = `${getRandomPrefix()}${sound.name}`;
  copyToClipboard(command);
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
    ["Source Title", sound.source_title],
    ["Source URL", sound.source_url ? createLink(sound.source_url) : null],
    ["Volume", sound.volume != null && sound.volume !== 1 ? `${sound.volume}` : null],
    ["Trim Start", sound.trim_start !== null ? `${sound.trim_start}s` : null],
    ["Trim End", sound.trim_end !== null ? `${sound.trim_end}s` : null],
    ["Source Duration", sound.source_duration !== null ? `${sound.source_duration}s` : null],
    ["Discord Plays", `${sound.discord_plays}`],
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
