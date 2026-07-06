/**
 * Minimal transient toast notifications, bottom-center, auto-dismissing.
 * Used by the admin flows for success/error feedback.
 */

export type ToastKind = "info" | "success" | "error";

let container: HTMLElement | null = null;

function getContainer(): HTMLElement {
  if (container && document.body.contains(container)) return container;
  container = document.createElement("div");
  container.className = "toast-container";
  container.setAttribute("aria-live", "polite");
  container.setAttribute("role", "status");
  document.body.appendChild(container);
  return container;
}

export function showToast(
  message: string,
  kind: ToastKind = "info",
  durationMs = 4000
): void {
  const host = getContainer();

  const toast = document.createElement("div");
  toast.className = `toast toast-${kind}`;
  toast.textContent = message;

  const dismiss = () => {
    toast.classList.add("toast-leaving");
    window.setTimeout(() => toast.remove(), 200);
  };

  toast.addEventListener("click", dismiss);
  host.appendChild(toast);

  window.setTimeout(dismiss, durationMs);
}
