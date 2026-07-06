/**
 * Auth state + header UI (login button / avatar chip / logout).
 *
 * Exposes the current auth state and an `onAuthChange` subscription so other
 * modules (admin UI) can appear/disappear without a page reload. Everything here
 * is a no-op for anonymous users beyond a subtle "Log in" button.
 */

import { AuthMe, fetchAuthMe, logout, startLogin } from "admin-api";
import { showToast } from "toast";

type AuthListener = (state: AuthMe) => void;

const LOGGED_OUT: AuthMe = {
  authenticated: false,
  can_admin: false,
  user: null,
};

let current: AuthMe = LOGGED_OUT;
const listeners: AuthListener[] = [];

export function getAuthState(): AuthMe {
  return current;
}

export function isAdmin(): boolean {
  return current.authenticated && current.can_admin;
}

/**
 * Subscribe to auth state changes. Fires immediately with the current state.
 * Returns an unsubscribe function.
 */
export function onAuthChange(listener: AuthListener): () => void {
  listeners.push(listener);
  listener(current);
  return () => {
    const i = listeners.indexOf(listener);
    if (i !== -1) listeners.splice(i, 1);
  };
}

function setAuthState(state: AuthMe): void {
  current = state;
  for (const listener of listeners) {
    try {
      listener(state);
    } catch (e) {
      console.error("[auth] listener error:", e);
    }
  }
}

/* ---- header UI ---- */

const ICON_LOGIN =
  '<svg class="icon" aria-hidden="true" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><path d="M15 3h4a2 2 0 0 1 2 2v14a2 2 0 0 1-2 2h-4"/><polyline points="10 17 15 12 10 7"/><line x1="15" x2="3" y1="12" y2="12"/></svg>';

let menuOpen = false;

function closeMenu(chip: HTMLElement): void {
  const menu = chip.querySelector<HTMLElement>(".auth-menu");
  if (menu) menu.hidden = true;
  chip.setAttribute("aria-expanded", "false");
  menuOpen = false;
}

function buildContainer(): HTMLElement {
  let container = document.querySelector<HTMLElement>("#auth-controls");
  if (container) return container;

  container = document.createElement("div");
  container.id = "auth-controls";
  container.className = "auth-controls";

  const header = document.querySelector("header");
  if (header) {
    header.appendChild(container);
  } else {
    document.body.appendChild(container);
  }
  return container;
}

function renderLoggedOut(container: HTMLElement): void {
  container.innerHTML = "";
  const btn = document.createElement("button");
  btn.type = "button";
  btn.className = "auth-login-btn";
  btn.title = "Log in with Discord";
  btn.innerHTML = `${ICON_LOGIN}<span>Log in</span>`;
  btn.addEventListener("click", () => startLogin());
  container.appendChild(btn);
}

function renderLoggedIn(container: HTMLElement, state: AuthMe): void {
  container.innerHTML = "";
  const user = state.user;
  const username = user?.username ?? "Account";

  const chip = document.createElement("div");
  chip.className = "auth-chip";
  chip.tabIndex = 0;
  chip.setAttribute("role", "button");
  chip.setAttribute("aria-haspopup", "true");
  chip.setAttribute("aria-expanded", "false");
  chip.title = username;

  const avatar = document.createElement("span");
  avatar.className = "auth-avatar";
  if (user?.avatar_url) {
    const img = document.createElement("img");
    img.src = user.avatar_url;
    img.alt = "";
    img.width = 24;
    img.height = 24;
    img.referrerPolicy = "no-referrer";
    avatar.appendChild(img);
  } else {
    avatar.textContent = username.slice(0, 1).toUpperCase();
    avatar.classList.add("auth-avatar-fallback");
  }

  const nameEl = document.createElement("span");
  nameEl.className = "auth-username";
  nameEl.textContent = username;

  const menu = document.createElement("div");
  menu.className = "auth-menu";
  menu.hidden = true;

  const logoutItem = document.createElement("button");
  logoutItem.type = "button";
  logoutItem.className = "auth-menu-item";
  logoutItem.textContent = "Log out";
  logoutItem.addEventListener("click", (e) => {
    e.stopPropagation();
    logout()
      .then(() => {
        setAuthState(LOGGED_OUT);
        showToast("Logged out", "info");
      })
      .catch(() => showToast("Could not log out", "error"));
  });
  menu.appendChild(logoutItem);

  const toggle = (e: Event) => {
    e.stopPropagation();
    menuOpen = menu.hidden;
    menu.hidden = !menu.hidden;
    chip.setAttribute("aria-expanded", menuOpen ? "true" : "false");
  };
  chip.addEventListener("click", toggle);
  chip.addEventListener("keydown", (e) => {
    if (e.key === "Enter" || e.key === " ") {
      e.preventDefault();
      toggle(e);
    } else if (e.key === "Escape") {
      closeMenu(chip);
    }
  });

  chip.appendChild(avatar);
  chip.appendChild(nameEl);
  chip.appendChild(menu);
  container.appendChild(chip);
}

function renderHeader(state: AuthMe): void {
  const container = buildContainer();
  if (state.authenticated && state.can_admin) {
    renderLoggedIn(container, state);
  } else {
    // Not authenticated (or authenticated but not an admin): offer login.
    renderLoggedOut(container);
  }
}

/** Handle ?login_error=... from a failed OAuth round-trip, then clean the URL. */
function handleLoginError(): void {
  const params = new URLSearchParams(window.location.search);
  const err = params.get("login_error");
  if (!err) return;

  const messages: Record<string, string> = {
    not_a_member: "Login failed: you're not a member of the required server.",
    oauth_failed: "Login failed: Discord sign-in didn't complete. Try again.",
  };
  showToast(messages[err] ?? "Login failed. Try again.", "error", 8000);

  const url = new URL(window.location.href);
  url.searchParams.delete("login_error");
  history.replaceState(null, "", url.pathname + url.search);
}

/** Initialise auth: render header, fetch state, wire global handlers. */
export function initAuth(): void {
  handleLoginError();

  // Close any open avatar menu on outside click / Escape.
  document.addEventListener("click", () => {
    if (!menuOpen) return;
    const chip = document.querySelector<HTMLElement>(".auth-chip");
    if (chip) closeMenu(chip);
  });

  onAuthChange((state) => renderHeader(state));

  fetchAuthMe()
    .then((state) => setAuthState(state))
    .catch((e) => {
      console.warn("[auth] failed to fetch auth state:", e);
      setAuthState(LOGGED_OUT);
    });
}
