/**
 * Reusable modal scaffolding shared by the admin flows. Provides a dim overlay,
 * a header with title + close button, Escape / backdrop dismissal (guarded by an
 * optional dirty-check), and focus restoration. Only one admin modal is open at
 * a time.
 */

export interface ModalController {
  overlay: HTMLElement;
  modal: HTMLElement;
  body: HTMLElement;
  header: HTMLElement;
  setTitle(node: string | HTMLElement): void;
  /** Close, running the beforeClose guard. Returns true if it actually closed. */
  close(): boolean;
  /** Force close without the guard (e.g. after a successful save). */
  forceClose(): void;
}

export interface ModalOptions {
  title: string | HTMLElement;
  className?: string;
  /**
   * Called before a user-initiated close (Esc / backdrop / × button). Return
   * false to veto (e.g. unsaved changes and the user cancelled the confirm).
   */
  beforeClose?: () => boolean;
  onClosed?: () => void;
}

let activeModal: ModalController | null = null;

export function getActiveModal(): ModalController | null {
  return activeModal;
}

export function closeActiveModal(): boolean {
  if (activeModal) return activeModal.close();
  return false;
}

export function openModal(options: ModalOptions): ModalController {
  // Only one admin modal at a time — force-close any existing one.
  if (activeModal) activeModal.forceClose();

  const previouslyFocused = document.activeElement as HTMLElement | null;

  const overlay = document.createElement("div");
  overlay.className = "modal-overlay admin-modal-overlay";

  const modal = document.createElement("div");
  modal.className = "modal admin-modal";
  // className may be multiple space-separated classes (e.g. the draft editor's
  // "trim-editor draft-editor") — classList.add throws on tokens containing
  // spaces, which nuked the whole add-sound flow after download. Split first.
  if (options.className) {
    modal.classList.add(...options.className.split(/\s+/).filter(Boolean));
  }
  modal.setAttribute("role", "dialog");
  modal.setAttribute("aria-modal", "true");

  const header = document.createElement("div");
  header.className = "modal-header";

  const titleEl = document.createElement("h2");
  if (typeof options.title === "string") {
    titleEl.textContent = options.title;
  } else {
    titleEl.appendChild(options.title);
  }

  const closeBtn = document.createElement("button");
  closeBtn.type = "button";
  closeBtn.className = "modal-close";
  closeBtn.setAttribute("aria-label", "Close");
  closeBtn.textContent = "×";

  header.appendChild(titleEl);
  header.appendChild(closeBtn);

  const body = document.createElement("div");
  body.className = "modal-body";

  modal.appendChild(header);
  modal.appendChild(body);
  overlay.appendChild(modal);
  document.body.appendChild(overlay);

  let closed = false;

  const finalize = () => {
    if (closed) return;
    closed = true;
    overlay.remove();
    document.removeEventListener("keydown", onKeydown, true);
    if (activeModal === controller) activeModal = null;
    if (previouslyFocused && document.contains(previouslyFocused)) {
      previouslyFocused.focus();
    }
    options.onClosed?.();
  };

  const guardedClose = (): boolean => {
    if (options.beforeClose && !options.beforeClose()) return false;
    finalize();
    return true;
  };

  const onKeydown = (e: KeyboardEvent) => {
    if (e.key === "Escape" && activeModal === controller) {
      e.stopPropagation();
      guardedClose();
    }
  };

  closeBtn.addEventListener("click", guardedClose);
  overlay.addEventListener("click", (e) => {
    if (e.target === overlay) guardedClose();
  });
  document.addEventListener("keydown", onKeydown, true);

  const controller: ModalController = {
    overlay,
    modal,
    body,
    header,
    setTitle(node) {
      titleEl.innerHTML = "";
      if (typeof node === "string") titleEl.textContent = node;
      else titleEl.appendChild(node);
    },
    close: guardedClose,
    forceClose: finalize,
  };

  activeModal = controller;

  // Move focus into the modal for keyboard users.
  window.setTimeout(() => {
    const focusTarget = modal.querySelector<HTMLElement>(
      "input, textarea, select, button:not(.modal-close)"
    );
    (focusTarget ?? closeBtn).focus();
  }, 0);

  return controller;
}
