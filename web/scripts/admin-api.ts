/**
 * Typed client for the authenticated admin + auth API.
 *
 * All admin mutations are same-origin, cookie-authenticated (the browser sends
 * the session cookie automatically). Errors come back as `{ detail: string }`
 * with a 4xx status; this module normalises them into `ApiError`.
 */

const AUTH_BASE = "/api/auth";
const ADMIN_BASE = "/api/admin";

export interface AuthUser {
  id: string;
  username: string;
  avatar_url: string | null;
}

export interface AuthMe {
  authenticated: boolean;
  can_admin: boolean;
  user: AuthUser | null;
}

export interface WaveformInfo {
  audio_url: string;
  duration: number;
  start: number | null;
  end: number | null;
  volume_adjust: number;
  source_title: string | null;
  source_url: string | null;
}

export interface AddSoundRequest {
  name: string;
  url: string;
  start?: number | null;
  end?: number | null;
}

export interface TrimRequest {
  start: number | null;
  end: number | null;
}

export interface PatchSoundRequest {
  new_name?: string;
  volume_adjust?: number;
}

export interface DraftInfo {
  draft_id: string;
  duration: number;
  source_title: string | null;
  source_url: string | null;
  has_video: boolean;
  audio_url: string;
}

export interface CommitDraftRequest {
  name: string;
  start: number | null;
  end: number | null;
}

/** An error carrying the server's HTTP status and a human-readable message. */
export class ApiError extends Error {
  status: number;

  constructor(status: number, message: string) {
    super(message);
    this.name = "ApiError";
    this.status = status;
  }

  /** True when the session is missing/expired and the user should re-auth. */
  get isUnauthenticated(): boolean {
    return this.status === 401;
  }

  /** True when authenticated but not permitted (not a guild member). */
  get isForbidden(): boolean {
    return this.status === 403;
  }
}

async function extractDetail(response: Response): Promise<string> {
  try {
    const body: unknown = await response.json();
    if (
      body &&
      typeof body === "object" &&
      "detail" in body &&
      typeof (body as { detail: unknown }).detail === "string"
    ) {
      return (body as { detail: string }).detail;
    }
  } catch {
    // fall through to a status-based message
  }
  return `Request failed (HTTP ${response.status})`;
}

async function request<T>(
  input: string,
  init: RequestInit,
  parse: (r: Response) => Promise<T>
): Promise<T> {
  let response: Response;
  try {
    response = await fetch(input, init);
  } catch (e) {
    throw new ApiError(0, "Could not reach the server. Check your connection.");
  }

  if (!response.ok) {
    if (response.status === 401) {
      throw new ApiError(401, "Your session expired — log in again.");
    }
    if (response.status === 403) {
      throw new ApiError(
        403,
        "You don't have permission to do that (not a member)."
      );
    }
    throw new ApiError(response.status, await extractDetail(response));
  }

  return parse(response);
}

function jsonInit(method: string, body?: unknown): RequestInit {
  const init: RequestInit = {
    method,
    headers: { "Content-Type": "application/json" },
    credentials: "same-origin",
  };
  if (body !== undefined) init.body = JSON.stringify(body);
  return init;
}

async function asJson<T>(r: Response): Promise<T> {
  return (await r.json()) as T;
}

async function asVoid(): Promise<void> {
  /* 204 / no body */
}

/* ---- Auth ---- */

export async function fetchAuthMe(): Promise<AuthMe> {
  return request<AuthMe>(
    `${AUTH_BASE}/me`,
    { method: "GET", credentials: "same-origin" },
    asJson
  );
}

/** Navigate the browser to the Discord OAuth login flow (legacy cookie-state). */
export function startLogin(): void {
  window.location.href = `${AUTH_BASE}/login`;
}

export interface LoginHandoff {
  handoff_id: string;
  authorize_url: string;
}

/**
 * Create a server-side login handoff (iOS PWA cookie-jar-safe flow).
 * Throws on failure (e.g. 503 when auth isn't configured).
 */
export async function createLoginHandoff(): Promise<LoginHandoff> {
  return request<LoginHandoff>(`${AUTH_BASE}/handoff`, jsonInit("POST"), asJson);
}

/** Result of a handoff claim attempt. */
export type ClaimResult =
  | { status: "claimed"; me: AuthMe }
  | { status: "pending" }
  | { status: "gone" };

/**
 * Try to claim a completed login handoff. On success the response sets the
 * session cookie in THIS context's cookie jar.
 */
export async function claimLoginHandoff(
  handoffId: string
): Promise<ClaimResult> {
  let response: Response;
  try {
    response = await fetch(
      `${AUTH_BASE}/handoff/${encodeURIComponent(handoffId)}/claim`,
      jsonInit("POST")
    );
  } catch {
    // Network error — treat as still pending; the caller will retry.
    return { status: "pending" };
  }
  if (response.status === 202) return { status: "pending" };
  if (response.ok) {
    return { status: "claimed", me: (await response.json()) as AuthMe };
  }
  // 404 (unknown/expired/claimed), 503, anything else: stop trying.
  return { status: "gone" };
}

export async function logout(): Promise<void> {
  return request<void>(`${AUTH_BASE}/logout`, jsonInit("POST"), asVoid);
}

/* ---- Admin: sounds ---- */

export async function addSound(req: AddSoundRequest): Promise<{ name: string }> {
  return request<{ name: string }>(
    `${ADMIN_BASE}/sounds`,
    jsonInit("POST", req),
    asJson
  );
}

export async function fetchWaveform(name: string): Promise<WaveformInfo> {
  return request<WaveformInfo>(
    `${ADMIN_BASE}/sounds/${encodeURIComponent(name)}/waveform`,
    { method: "GET", credentials: "same-origin" },
    asJson
  );
}

export async function saveTrim(name: string, req: TrimRequest): Promise<void> {
  return request<void>(
    `${ADMIN_BASE}/sounds/${encodeURIComponent(name)}/trim`,
    jsonInit("PUT", req),
    asVoid
  );
}

export async function patchSound(
  name: string,
  req: PatchSoundRequest
): Promise<{ name: string }> {
  return request<{ name: string }>(
    `${ADMIN_BASE}/sounds/${encodeURIComponent(name)}`,
    jsonInit("PATCH", req),
    asJson
  );
}

export async function deleteSound(name: string): Promise<void> {
  return request<void>(
    `${ADMIN_BASE}/sounds/${encodeURIComponent(name)}`,
    { method: "DELETE", credentials: "same-origin" },
    asVoid
  );
}

export async function redownloadSound(name: string): Promise<void> {
  return request<void>(
    `${ADMIN_BASE}/sounds/${encodeURIComponent(name)}/redownload`,
    jsonInit("POST"),
    asVoid
  );
}

/* ---- Admin: drafts (download first, name + commit later) ---- */

export async function createDraft(url: string): Promise<DraftInfo> {
  return request<DraftInfo>(
    `${ADMIN_BASE}/drafts`,
    jsonInit("POST", { url }),
    asJson
  );
}

export async function commitDraft(
  draftId: string,
  req: CommitDraftRequest
): Promise<{ name: string }> {
  return request<{ name: string }>(
    `${ADMIN_BASE}/drafts/${encodeURIComponent(draftId)}/commit`,
    jsonInit("POST", req),
    asJson
  );
}

/** Best-effort draft cleanup — fire-and-forget on cancel. */
export function discardDraft(draftId: string): void {
  fetch(`${ADMIN_BASE}/drafts/${encodeURIComponent(draftId)}`, {
    method: "DELETE",
    credentials: "same-origin",
    keepalive: true,
  }).catch(() => {
    /* fire-and-forget */
  });
}

/** URL for the admin-only trimmed-clip video (auth via same-origin cookie). */
export function soundVideoUrl(name: string): string {
  return `${ADMIN_BASE}/sounds/${encodeURIComponent(name)}/video`;
}

/** URL for downloading the authenticated clip with its canonical filename. */
export function soundVideoDownloadUrl(name: string): string {
  return `${soundVideoUrl(name)}?download=true`;
}

/** Fetch the canonical absolute signed URL used to embed a clip. */
export async function fetchClipEmbedUrl(name: string): Promise<string> {
  const result = await request<{ url: string }>(
    `${ADMIN_BASE}/sounds/${encodeURIComponent(name)}/clip-url`,
    { method: "GET", credentials: "same-origin" },
    asJson
  );
  return result.url;
}
