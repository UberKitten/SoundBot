export interface AudioPlatformNavigator {
  userAgent: string;
  platform: string;
  maxTouchPoints: number;
}

/**
 * iOS/iPadOS needs HTML media playback bridged through Web Audio for reliable
 * user-activated audio while retaining GainNode volume above 100%.
 */
export function shouldUseMediaElementEngine(
  nav: AudioPlatformNavigator | undefined =
    typeof navigator === "undefined" ? undefined : navigator
): boolean {
  if (!nav) return false;
  return (
    /iP(?:hone|ad|od)/.test(nav.userAgent) ||
    (nav.platform === "MacIntel" && nav.maxTouchPoints > 1)
  );
}
