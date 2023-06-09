import { SOUNDS_PATH } from "config";
import { parseInteger, scheduleBackgroundTask } from "utils";

const changeListeners: Map<
  HTMLAudioElement,
  Array<(e: Event) => unknown>
> = new Map();

const mainAudio = document.createElement("audio");
let mainAudioCtx: AudioContext | null = null;
let mainSound: Sound | null = null;
let mainAudioSource: MediaElementAudioSourceNode | null = null;
let mainAudioGain: GainNode | null = null;

const buttonAudio: Map<Sound, AudioGroup[]> = new Map();

const volumeSlider = document.querySelector(
  "input#volume"
) as HTMLInputElement | null;

let volume = 1;
setVolume(localStorage.getItem("volume"));

export interface Sound {
  name: string;
  filename: string;
  modified: number;
  count: number;
  tags: Array<string>;
}

export interface AudioGroup {
  element: HTMLAudioElement;
  source: MediaElementAudioSourceNode;
  gain: GainNode;
}

/**
 * Sets the soundboard volume
 *
 * @param vol A value between 0 and 100, inclusive. Values outside this range will be clamped
 */
export function setVolume(vol: string | number | null) {
  const intVol = parseInteger(vol);
  if (typeof intVol === "undefined") return;

  volume = Math.max(0, Math.min(intVol / 100, 1));
  getActiveAudioGroups().forEach((groups) =>
    groups.forEach(({ gain }) => (gain.gain.value = volume))
  );

  if (volumeSlider) volumeSlider.value = intVol.toString();
  localStorage.setItem("volume", intVol.toString());
}

export function getVolume() {
  return volume * 100;
}

export function isSoundObject(maybeSound: unknown) {
  if (!maybeSound) return false;
  if (typeof maybeSound !== "object") return false;

  const maybeSoundObj = maybeSound as {
    name: unknown;
    filename: unknown;
    modified: unknown;
    count: unknown;
    tags: unknown;
  };

  if (typeof maybeSoundObj.name !== "string") return false;
  if (typeof maybeSoundObj.filename !== "string") return false;
  if (typeof maybeSoundObj.modified !== "number") return false;
  if (typeof maybeSoundObj.count !== "number") return false;
  if (!Array.isArray(maybeSoundObj.tags)) return false;
  if (maybeSoundObj.tags.find((tag) => typeof tag !== "string")) return false;

  return true;
}

export function getSoundPath(sound: undefined): undefined;
export function getSoundPath(sound: Sound): string;
export function getSoundPath(sound?: Sound): string | undefined;
export function getSoundPath(sound?: Sound): string | undefined {
  if (!sound) return;

  const soundUrl = new URL(`${SOUNDS_PATH}/${sound.filename}`, location.origin);
  soundUrl.searchParams.append("v", sound.modified.toString());
  return soundUrl.href;
}

export function attachChangeListeners(
  audioElement: HTMLAudioElement,
  cb: (e: Event) => unknown
) {
  const existingListeners = changeListeners.get(audioElement);

  if (existingListeners) {
    existingListeners.push(cb);
    return;
  }

  ["pause", "play", "ended"].forEach((eventType) => {
    audioElement.addEventListener(eventType, (e) => {
      changeListeners.get(audioElement)?.forEach((listener) => {
        scheduleBackgroundTask(() => listener(e));
      });
    });
  });

  changeListeners.set(audioElement, [cb]);
}

export function detachChangeListeners(
  audioElement: HTMLAudioElement,
  cb: (e: Event) => unknown
) {
  const existingListeners = changeListeners.get(audioElement);
  if (!existingListeners) return;

  const iCB = existingListeners.indexOf(cb);
  if (iCB === -1) return;

  const cleanup = () =>
    existingListeners.splice(existingListeners.indexOf(cb), 1);
  scheduleBackgroundTask(cleanup);
}

export function playButtonAudio(sound: Sound, updateCb: (e: Event) => unknown) {
  const audioGroups = buttonAudio.get(sound);
  const element = document.createElement("audio");
  element.src = getSoundPath(sound);
  const audioCtx = new AudioContext();
  const source = audioCtx.createMediaElementSource(element);
  const gain = audioCtx.createGain();
  source.connect(gain);
  gain.connect(audioCtx.destination);

  if (audioGroups) {
    audioGroups.push({ element, gain, source });
  } else {
    buttonAudio.set(sound, [{ element, gain, source }]);
  }

  gain.gain.value = volume;
  element.play();
  attachChangeListeners(element, updateCb);

  scheduleBackgroundTask(() => {
    for (const [, audioGroups] of buttonAudio) {
      const activeGroups = audioGroups.filter((group) => !group.element.paused);
      audioGroups.splice(0, audioGroups.length, ...activeGroups);
    }
  });
}

export function playMainAudio(sound: Sound) {
  if (!mainAudioCtx) mainAudioCtx = new AudioContext();
  if (!mainAudioSource) {
    mainAudioSource = mainAudioCtx.createMediaElementSource(mainAudio);
  }
  if (!mainAudioGain) {
    mainAudioGain = mainAudioCtx.createGain();
    mainAudioSource.connect(mainAudioGain);
    mainAudioGain.connect(mainAudioCtx.destination);
  }

  mainAudioGain.gain.value = volume;
  mainSound = sound;
  mainAudio.src = getSoundPath(sound);
  mainAudio.play();
}

export function getActiveButtonAudioGroups(
  sound?: Sound
): Map<Sound, AudioGroup[]> {
  return new Map(
    [...buttonAudio.entries()].filter(([buttonSound, audioGroups]) =>
      audioGroups.find(
        (group) => !group.element.paused && (!sound || buttonSound === sound)
      )
    )
  );
}

export function getActiveAudioGroups(sound?: Sound): Map<Sound, AudioGroup[]> {
  const audioGroups = getActiveButtonAudioGroups(sound);
  if (!mainAudio.paused && mainSound && mainAudioGain && mainAudioSource) {
    if (!sound || sound === mainSound)
      audioGroups.set(mainSound, [
        {
          element: mainAudio,
          gain: mainAudioGain,
          source: mainAudioSource,
        },
      ]);
  }

  return audioGroups;
}

export function isMainAudioActive(sound?: Sound) {
  return (!sound || sound === mainSound) && !mainAudio.paused;
}

export function addMainAudioChangeListener(cb: (e: Event) => unknown) {
  return attachChangeListeners(mainAudio, cb);
}

export function removeMainAudioChangeListener(cb: (e: Event) => unknown) {
  return detachChangeListeners(mainAudio, cb);
}

export function stopMainAudio() {
  mainAudio.pause();
}

export function stopAllButtonAudio() {
  buttonAudio.forEach((groups) => {
    groups.forEach((group) => group.element.pause());
  });
}
