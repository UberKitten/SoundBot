/**
 * Auth state + header UI (login button / avatar chip / logout).
 *
 * Exposes the current auth state and an `onAuthChange` subscription so other
 * modules (admin UI) can appear/disappear without a page reload. Everything here
 * is a no-op for anonymous users beyond a subtle "Log in" button.
 */

import {
  AuthMe,
  claimLoginHandoff,
  createLoginHandoff,
  fetchAuthMe,
  logout,
  startLogin,
} from "admin-api";
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

/* ---- login handoff (iOS PWA cookie-jar-safe flow) ---- */

const HANDOFF_STORAGE_KEY = "soundbot_login_handoff";
const HANDOFF_MAX_AGE_MS = 15 * 60 * 1000;
const HANDOFF_POLL_INTERVAL_MS = 3000;
const HANDOFF_POLL_MAX_MS = 5 * 60 * 1000;

let handoffPollTimer: number | null = null;

function readStoredHandoff(): string | null {
  let raw: string | null = null;
  try {
    raw = localStorage.getItem(HANDOFF_STORAGE_KEY);
  } catch {
    return null;
  }
  if (!raw) return null;
  try {
    const parsed: unknown = JSON.parse(raw);
    if (
      parsed &&
      typeof parsed === "object" &&
      typeof (parsed as { id: unknown }).id === "string" &&
      typeof (parsed as { at: unknown }).at === "number"
    ) {
      const { id, at } = parsed as { id: string; at: number };
      if (Date.now() - at <= HANDOFF_MAX_AGE_MS) return id;
    }
  } catch {
    // corrupt — fall through to clear
  }
  clearStoredHandoff();
  return null;
}

function storeHandoff(id: string): void {
  try {
    localStorage.setItem(
      HANDOFF_STORAGE_KEY,
      JSON.stringify({ id, at: Date.now() })
    );
  } catch {
    // Storage unavailable — claim-on-return just won't work; login in a
    // single-jar browser still completes via the callback's cookie.
  }
}

function clearStoredHandoff(): void {
  try {
    localStorage.removeItem(HANDOFF_STORAGE_KEY);
  } catch {
    /* ignore */
  }
}

function stopHandoffPoll(): void {
  if (handoffPollTimer !== null) {
    window.clearInterval(handoffPollTimer);
    handoffPollTimer = null;
  }
}

/**
 * Try to claim a pending login handoff. Safe to call any time; no-ops when
 * nothing is stored. On success, updates auth state in place (no reload).
 */
async function tryClaimHandoff(): Promise<void> {
  const id = readStoredHandoff();
  if (!id) {
    stopHandoffPoll();
    return;
  }
  // Already logged in (e.g. same-window redirect set the cookie and
  // /api/auth/me picked it up) — the handoff is moot, don't fight it.
  if (current.authenticated) {
    clearStoredHandoff();
    stopHandoffPoll();
    return;
  }

  const result = await claimLoginHandoff(id);
  if (result.status === "claimed") {
    clearStoredHandoff();
    stopHandoffPoll();
    setAuthState(result.me);
    const name = result.me.user?.username;
    showToast(name ? `Logged in as ${name}` : "Logged in", "success");
  } else if (result.status === "gone") {
    clearStoredHandoff();
    stopHandoffPoll();
  }
  // pending: keep the stored id; a later trigger or poll will retry.
}

/** Poll for the handoff result while the page is visible, up to 5 minutes. */
function startHandoffPoll(): void {
  stopHandoffPoll();
  const startedAt = Date.now();
  handoffPollTimer = window.setInterval(() => {
    if (Date.now() - startedAt > HANDOFF_POLL_MAX_MS) {
      stopHandoffPoll();
      return;
    }
    if (document.visibilityState !== "visible") return;
    void tryClaimHandoff();
  }, HANDOFF_POLL_INTERVAL_MS);
}

/**
 * Begin a login via the server-side handoff flow. Falls back to the legacy
 * /api/auth/login navigation if the handoff can't be created.
 */
async function beginLogin(): Promise<void> {
  try {
    const handoff = await createLoginHandoff();
    storeHandoff(handoff.handoff_id);
    startHandoffPoll();
    window.location.href = handoff.authorize_url;
  } catch (e) {
    console.warn("[auth] handoff create failed, using legacy login:", e);
    startLogin();
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
  btn.addEventListener("click", () => void beginLogin());
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

/**
 * Handle ?login_done=1 after a handoff-flow callback. This page may be the
 * iOS in-app Safari sheet — if so, the user can close it and return to the
 * PWA (which claims the session). Shown only once auth state confirms login.
 */
function handleLoginDone(): void {
  const params = new URLSearchParams(window.location.search);
  if (!params.get("login_done")) return;

  const url = new URL(window.location.href);
  url.searchParams.delete("login_done");
  history.replaceState(null, "", url.pathname + url.search);

  let shown = false;
  const unsubscribe = onAuthChange((state) => {
    if (shown || !state.authenticated) return;
    shown = true;
    showToast(
      "Logged in — if you started from the app, you can close this window and return",
      "success",
      8000
    );
    // Defer: unsubscribing mid-notification would splice the listener list
    // while setAuthState iterates it.
    window.setTimeout(unsubscribe, 0);
  });
}

/** Initialise auth: render header, fetch state, wire global handlers. */
export function initAuth(): void {
  handleLoginError();
  handleLoginDone();

  // Close any open avatar menu on outside click / Escape.
  document.addEventListener("click", () => {
    if (!menuOpen) return;
    const chip = document.querySelector<HTMLElement>(".auth-chip");
    if (chip) closeMenu(chip);
  });

  onAuthChange((state) => renderHeader(state));

  // Claim a pending login handoff the moment the user returns to the PWA
  // (closing the iOS in-app Safari sheet fires these).
  document.addEventListener("visibilitychange", () => {
    if (document.visibilityState === "visible") void tryClaimHandoff();
  });
  window.addEventListener("focus", () => void tryClaimHandoff());
  window.addEventListener("pageshow", () => void tryClaimHandoff());

  const claimAfterInit = () => {
    // If a login is still pending from before a reload, resume polling too
    // (tryClaimHandoff stops it again on success/expiry/already-logged-in).
    if (readStoredHandoff()) startHandoffPoll();
    void tryClaimHandoff();
  };

  fetchAuthMe()
    .then((state) => {
      setAuthState(state);
      claimAfterInit();
    })
    .catch((e) => {
      console.warn("[auth] failed to fetch auth state:", e);
      setAuthState(LOGGED_OUT);
      claimAfterInit();
    });
}
