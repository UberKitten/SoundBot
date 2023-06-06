import { SOUNDS_PATH } from "./config.js";

const mainAudio = document.createElement("audio");
const buttonAudio: Array<HTMLAudioElement> = [];

export interface Sound {
  name: string;
  filename: string;
  modified: number;
  count: number;
  tags: Array<string>;
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
  return sound && `${SOUNDS_PATH}/${sound.filename}`;
}

export function attachChangeListeners(
  audioElement: HTMLAudioElement,
  cb: (e: Event) => unknown
) {
  ["pause", "play", "ended"].forEach((eventType) => {
    audioElement.addEventListener(eventType, (e) => cb(e));
  });
}

export function playButtonAudio(sound: Sound, updateCb: (e: Event) => unknown) {
  const audioElement = document.createElement("audio");
  audioElement.src = getSoundPath(sound);

  buttonAudio.push(audioElement);

  audioElement.addEventListener("ended", (e) => {
    buttonAudio.splice(
      buttonAudio.indexOf(e.currentTarget as HTMLAudioElement),
      1
    );
  });

  audioElement.play();
  attachChangeListeners(audioElement, updateCb);
  return audioElement;
}

export function playMainAudio(sound: Sound) {
  mainAudio.src = getSoundPath(sound);
  mainAudio.play();
}

export function getActiveAudioElements(sound?: Sound) {
  const activeSounds = [mainAudio, ...buttonAudio].filter(
    (audioElement) => !audioElement.paused
  );

  if (!sound) return activeSounds;

  return activeSounds.filter((audioElement) =>
    audioElement.src.endsWith(getSoundPath(sound))
  );
}

export function isMainAudioActive(sound?: Sound) {
  return !!getActiveAudioElements(sound).find(
    (audioEl) => audioEl === mainAudio
  );
}

export function addMainAudioChangeListener(cb: (e: Event) => unknown) {
  return attachChangeListeners(mainAudio, cb);
}

export function stopMainAudio() {
  mainAudio.pause();
}

export function stopAllButtonAudio() {
  buttonAudio.forEach((audio) => {
    audio.pause();
  });

  buttonAudio.splice(0, buttonAudio.length);
}
