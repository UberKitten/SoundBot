export const WAVEFORM_ZOOM_MIN = 0;
export const WAVEFORM_ZOOM_MAX = 300;
export const WAVEFORM_ZOOM_STEP = 20;

const DECIMAL_COMPONENT = /^(?:\d+(?:\.\d+)?|\.\d+)$/;
const INTEGER_COMPONENT = /^\d+$/;

/**
 * Parse plain seconds, MM:SS, or HH:MM:SS. Fractions belong on the seconds
 * component. Clock minute/second components are base-60 and therefore < 60.
 */
export function parseTimestamp(input: string): number | null {
  const text = input.trim();
  if (!text) return null;

  const parts = text.split(":");
  if (parts.length < 1 || parts.length > 3) return null;

  if (parts.length === 1) {
    if (!DECIMAL_COMPONENT.test(parts[0])) return null;
    const seconds = Number(parts[0]);
    return Number.isFinite(seconds) && seconds >= 0 ? seconds : null;
  }

  if (!DECIMAL_COMPONENT.test(parts[parts.length - 1])) return null;
  if (!parts.slice(0, -1).every((part) => INTEGER_COMPONENT.test(part))) {
    return null;
  }

  const secondsComponent = Number(parts[parts.length - 1]);
  if (!Number.isFinite(secondsComponent) || secondsComponent >= 60) return null;

  let total: number;
  if (parts.length === 2) {
    const minutes = Number(parts[0]);
    if (!Number.isFinite(minutes) || minutes >= 60) return null;
    total = minutes * 60 + secondsComponent;
  } else {
    const hours = Number(parts[0]);
    const minutes = Number(parts[1]);
    if (
      !Number.isFinite(hours) ||
      !Number.isFinite(minutes) ||
      minutes >= 60
    ) {
      return null;
    }
    total = hours * 3600 + minutes * 60 + secondsComponent;
  }

  return Number.isFinite(total) && total >= 0 ? total : null;
}

function clockText(hours: number, minutes: number, seconds: string): string {
  const fractionalDigits = seconds.includes(".")
    ? seconds.length - seconds.indexOf(".") - 1
    : 0;
  const secondWidth = fractionalDigits > 0 ? 3 + fractionalDigits : 2;
  return `${String(hours).padStart(2, "0")}:${String(minutes).padStart(2, "0")}:${seconds.padStart(secondWidth, "0")}`;
}

/**
 * Format a nonnegative finite time as readable HH:MM:SS[.fraction].
 *
 * The editor keeps its numeric trim state separately, so bounding display
 * precision here does not quantize an untouched or waveform-adjusted trim.
 */
export function formatTimestamp(seconds: number): string {
  if (!Number.isFinite(seconds) || seconds < 0) {
    throw new RangeError("Timestamp must be a nonnegative finite number");
  }

  let hours = Math.floor(seconds / 3600);
  let withinHour =
    Math.round((seconds - hours * 3600) * 1000) / 1000;
  if (withinHour >= 3600) {
    hours += 1;
    withinHour = 0;
  }

  const minutes = Math.floor(withinHour / 60);
  const secondsComponent = withinHour - minutes * 60;
  const component = secondsComponent
    .toFixed(3)
    .replace(/0+$/, "")
    .replace(/\.$/, "");
  return clockText(hours, minutes, component);
}

export interface WheelZoomDecisionInput {
  currentZoom: number;
  deltaX: number;
  deltaY: number;
  ctrlKey?: boolean;
  metaKey?: boolean;
  minZoom?: number;
  maxZoom?: number;
  step?: number;
}

export interface WheelZoomDecision {
  handled: boolean;
  nextZoom: number;
}

/** Decide whether a wheel event is an intentional, available waveform step. */
export function decideWheelZoom({
  currentZoom,
  deltaX,
  deltaY,
  ctrlKey = false,
  metaKey = false,
  minZoom = WAVEFORM_ZOOM_MIN,
  maxZoom = WAVEFORM_ZOOM_MAX,
  step = WAVEFORM_ZOOM_STEP,
}: WheelZoomDecisionInput): WheelZoomDecision {
  const boundedCurrent = Math.max(minZoom, Math.min(maxZoom, currentZoom));
  if (
    ctrlKey ||
    metaKey ||
    !Number.isFinite(deltaX) ||
    !Number.isFinite(deltaY) ||
    deltaY === 0 ||
    Math.abs(deltaX) > Math.abs(deltaY) ||
    !Number.isFinite(step) ||
    step <= 0 ||
    maxZoom < minZoom
  ) {
    return { handled: false, nextZoom: boundedCurrent };
  }

  const direction = deltaY < 0 ? 1 : -1;
  const nextZoom = Math.max(
    minZoom,
    Math.min(maxZoom, boundedCurrent + direction * step)
  );
  return { handled: nextZoom !== boundedCurrent, nextZoom };
}

export interface ZoomFocus {
  focalTime: number;
  focalViewportX: number;
}

/**
 * Keep the original focal point until its deferred scroll correction lands.
 * Rapid wheel events otherwise measure against an already-resized, not-yet-
 * scrolled waveform and make the pointer jump to a different time.
 */
export function retainPendingZoomFocus(
  pending: ZoomFocus | null,
  candidate: ZoomFocus
): ZoomFocus {
  return pending ?? candidate;
}

export interface ZoomScrollInput {
  focalTime: number;
  duration: number;
  nextZoom: number;
  viewportWidth: number;
  focalViewportX: number;
}

/** Scroll offset that keeps focalTime under the same viewport x after zoom. */
export function computeZoomScroll({
  focalTime,
  duration,
  nextZoom,
  viewportWidth,
  focalViewportX,
}: ZoomScrollInput): number {
  if (
    !Number.isFinite(duration) ||
    duration <= 0 ||
    !Number.isFinite(nextZoom) ||
    !Number.isFinite(viewportWidth) ||
    viewportWidth <= 0
  ) {
    return 0;
  }

  const contentWidth = Math.max(viewportWidth, duration * Math.max(0, nextZoom));
  const boundedTime = Math.max(0, Math.min(duration, focalTime));
  const boundedX = Math.max(0, Math.min(viewportWidth, focalViewportX));
  const wanted = (boundedTime / duration) * contentWidth - boundedX;
  return Math.max(0, Math.min(contentWidth - viewportWidth, wanted));
}
