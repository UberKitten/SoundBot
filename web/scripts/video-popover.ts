/**
 * "Watch clip" video popover (admin-only — the endpoint is auth-gated).
 *
 * Desktop: a lightweight popover anchored near the point the context menu was
 * opened at. Small screens: a centered modal-style card. Both sit on a
 * full-viewport scrim (transparent on desktop, dimmed on small screens) so a
 * click outside closes the popover WITHOUT also activating the sound button
 * underneath. The video streams from GET /api/admin/sounds/{name}/video
 * (same-origin cookies); the FIRST request may take a few seconds while the
 * server transcodes, so a spinner is shown until `canplay`. Closing pauses AND
 * unloads the video (src removed, load()) so audio never lingers.
 */

import { soundVideoUrl } from "admin-api";
import { stopAllButtonAudio, stopMainAudio } from "audio";
import { showToast } from "toast";
import { MenuAnchor } from "admin-ui";

const SMALL_SCREEN_MAX_PX = 600;

let activeClose: (() => void) | null = null;

export function openVideoPopover(name: string, anchor?: MenuAnchor): void {
  // Only one at a time.
  activeClose?.();

  // Pause main soundboard audio so the clip isn't fighting other playback.
  stopMainAudio();
  stopAllButtonAudio();

  const small =
    window.innerWidth <= SMALL_SCREEN_MAX_PX || window.innerHeight <= 500;

  const scrim = document.createElement("div");
  scrim.className = small
    ? "video-popover-scrim video-popover-scrim-dim"
    : "video-popover-scrim";

  const wrap = document.createElement("div");
  wrap.className = small
    ? "video-popover video-popover-centered"
    : "video-popover";
  wrap.setAttribute("role", "dialog");
  wrap.setAttribute("aria-label", `Video clip: ${name}`);

  const header = document.createElement("div");
  header.className = "video-popover-header";

  const title = document.createElement("span");
  title.className = "video-popover-title";
  title.textContent = name;

  const closeBtn = document.createElement("button");
  closeBtn.type = "button";
  closeBtn.className = "video-popover-close";
  closeBtn.setAttribute("aria-label", "Close");
  closeBtn.textContent = "×";

  header.appendChild(title);
  header.appendChild(closeBtn);

  const stage = document.createElement("div");
  stage.className = "video-popover-stage";

  const spinner = document.createElement("div");
  spinner.className = "video-popover-loading";
  spinner.innerHTML =
    '<span class="admin-spinner" aria-hidden="true"></span>preparing clip…';

  const video = document.createElement("video");
  video.className = "video-popover-video";
  video.controls = true;
  video.autoplay = true;
  video.playsInline = true;
  video.preload = "auto";

  stage.appendChild(spinner);
  stage.appendChild(video);
  wrap.appendChild(header);
  wrap.appendChild(stage);
  scrim.appendChild(wrap);

  let closed = false;
  const close = () => {
    if (closed) return;
    closed = true;
    if (activeClose === close) activeClose = null;
    document.removeEventListener("keydown", onKeydown, true);
    // Pause + unload so audio doesn't keep playing after close.
    try {
      video.pause();
      video.removeAttribute("src");
      video.load();
    } catch {
      /* ignore */
    }
    scrim.remove();
  };
  activeClose = close;

  const onKeydown = (e: KeyboardEvent) => {
    if (e.key === "Escape") {
      e.stopPropagation();
      close();
    }
  };

  closeBtn.addEventListener("click", close);
  scrim.addEventListener("click", (e) => {
    // The scrim swallows the outside click; only close on true outside taps.
    if (e.target === scrim) close();
  });
  document.addEventListener("keydown", onKeydown, true);

  video.addEventListener("canplay", () => {
    spinner.remove();
    wrap.classList.add("video-ready");
  });
  video.addEventListener("error", () => {
    if (closed || !video.getAttribute("src")) return;
    close();
    showToast(`Couldn't load the video for "${name}".`, "error", 6000);
  });

  document.body.appendChild(scrim);

  if (!small && anchor) {
    positionNear(wrap, anchor);
  }

  video.src = soundVideoUrl(name);
  video.play().catch(() => {
    /* autoplay guards — user can hit play via controls */
  });
}

function positionNear(el: HTMLElement, anchor: MenuAnchor): void {
  // Anchor near the opening point, clamped to the viewport.
  const margin = 8;
  const rect = el.getBoundingClientRect();
  let x = anchor.x;
  let y = anchor.y + 8;

  if (x + rect.width > window.innerWidth - margin) {
    x = window.innerWidth - rect.width - margin;
  }
  if (y + rect.height > window.innerHeight - margin) {
    y = Math.max(margin, window.innerHeight - rect.height - margin);
  }
  x = Math.max(margin, x);
  y = Math.max(margin, y);

  el.style.left = `${x}px`;
  el.style.top = `${y}px`;
}
