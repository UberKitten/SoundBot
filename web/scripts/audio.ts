import { shouldUseMediaElementEngine } from "audio-platform";
import { SOUNDS_API_PATH, SOUNDS_PATH } from "config";
import { parseInteger, scheduleBackgroundTask } from "utils";

type ChangeListener = (e: Event) => unknown;

const changeListeners: Map<EventTarget, ChangeListener[]> = new Map();
const mainAudioEvents = new EventTarget();

let audioCtx: AudioContext | null = null;
let mainSound: Sound | null = null;
let mainPending: MainRequest | null = null;
let mainVoice: Voice | null = null;
let mainGeneration = 0;

const buttonAudio: Map<Sound, Voice[]> = new Map();
const pendingButtonAudio: Set<ButtonRequest> = new Set();

const DECODED_CACHE_LIMIT_BYTES = 64 * 1024 * 1024;
const decodedAudio: Map<string, DecodedAudio> = new Map();
const activeDecodedAudio: Map<string, DecodedAudio> = new Map();
const inFlightAudio: Map<string, Promise<AudioBuffer>> = new Map();

const volumeSlider = document.querySelector(
  "input#volume"
) as HTMLInputElement | null;

let volume = 1;
setVolume(localStorage.getItem("volume"));

export interface Sound {
  name: string;
  audio_path: string | null;
  source_url: string | null;
  source_title: string | null;
  source_duration: number | null;
  duration: number;
  trim_start: number | null;
  trim_end: number | null;
  volume: number;
  created: string | null;
  modified: string | null;
  aliases: string[];
  discord_plays: number;
  twitch_plays: number;
  web_plays: number;
  discord_clips: number;
  is_legacy: boolean;
  has_video: boolean;
}

export interface SoundGroup {
  name: string;
  members: string[];
  created: string | null;
  discord_plays: number;
  twitch_plays: number;
  web_plays: number;
}

export interface AudioGroup {
  element: EventTarget;
  source: AudioNode;
  gain: GainNode;
}

interface BaseVoice extends AudioGroup {
  sound: Sound;
  stopped: boolean;
}

interface BufferVoice extends BaseVoice {
  engine: "decoded-buffer";
  source: AudioBufferSourceNode;
  cacheKey: string;
  buffer: AudioBuffer;
  startedAt: number;
  duration: number;
}

interface MediaVoice extends BaseVoice {
  engine: "media-element";
  source: MediaElementAudioSourceNode;
  media: HTMLAudioElement;
}

type Voice = BufferVoice | MediaVoice;

interface MainRequest {
  generation: number;
  sound: Sound;
  cacheKey: string;
  contextReady: Promise<void>;
  mediaStarted: boolean;
}

interface ButtonRequest {
  sound: Sound;
  cacheKey: string;
  element: EventTarget;
  contextReady: Promise<void>;
  mediaStarted: boolean;
  cancelled: boolean;
}

interface DecodedAudio {
  buffer: AudioBuffer;
  bytes: number;
  pins: number;
}


const preferredPlaybackEngine = shouldUseMediaElementEngine()
  ? "media-element"
  : "decoded-buffer";

/**
 * Sets the soundboard volume.
 *
 * @param vol A percentage between 0 and 400, inclusive. Values outside this range are clamped.
 */
export function setVolume(vol: string | number | null) {
  const intVol = parseInteger(vol);
  if (typeof intVol === "undefined") return;

  const volumePercent = Math.max(0, Math.min(intVol, 400));
  volume = volumePercent / 100;
  getActiveAudioGroups().forEach((groups) =>
    groups.forEach(({ gain }) => (gain.gain.value = volume))
  );

  if (volumeSlider) volumeSlider.value = volumePercent.toString();
  localStorage.setItem("volume", volumePercent.toString());
}

export function getVolume() {
  return volume * 100;
}

export function isSoundObject(maybeSound: unknown) {
  if (!maybeSound) return false;
  if (typeof maybeSound !== "object") return false;

  const maybeSoundObj = maybeSound as {
    name: unknown;
    audio_path: unknown;
    discord_plays: unknown;
  };

  if (typeof maybeSoundObj.name !== "string") return false;
  // audio_path can be null or string
  if (
    maybeSoundObj.audio_path !== null &&
    typeof maybeSoundObj.audio_path !== "string"
  )
    return false;
  if (typeof maybeSoundObj.discord_plays !== "number") return false;

  return true;
}

export function getSoundPath(sound: undefined): undefined;
export function getSoundPath(sound: Sound): string | undefined;
export function getSoundPath(sound?: Sound): string | undefined;
export function getSoundPath(sound?: Sound): string | undefined {
  if (!sound || !sound.audio_path) return;

  const soundUrl = new URL(`${SOUNDS_PATH}/${sound.audio_path}`, location.origin);
  // Use modified date as cache buster if available
  if (sound.modified) {
    soundUrl.searchParams.append(
      "v",
      new Date(sound.modified).getTime().toString()
    );
  }
  return soundUrl.href;
}

function attachPlaybackChangeListener(
  target: EventTarget,
  cb: ChangeListener
): void {
  const existingListeners = changeListeners.get(target);

  if (existingListeners) {
    existingListeners.push(cb);
    return;
  }

  ["pause", "play", "ended"].forEach((eventType) => {
    target.addEventListener(eventType, (e) => {
      changeListeners.get(target)?.forEach((listener) => {
        scheduleBackgroundTask(() => listener(e));
      });
    });
  });

  changeListeners.set(target, [cb]);
}

export function attachChangeListeners(
  audioElement: HTMLAudioElement,
  cb: ChangeListener
) {
  attachPlaybackChangeListener(audioElement, cb);
}

export function detachChangeListeners(
  audioElement: HTMLAudioElement,
  cb: ChangeListener
) {
  detachPlaybackChangeListener(audioElement, cb);
}

function detachPlaybackChangeListener(
  target: EventTarget,
  cb: ChangeListener
): void {
  const existingListeners = changeListeners.get(target);
  if (!existingListeners) return;

  const iCB = existingListeners.indexOf(cb);
  if (iCB === -1) return;

  scheduleBackgroundTask(() => {
    const listenerIndex = existingListeners.indexOf(cb);
    if (listenerIndex !== -1) existingListeners.splice(listenerIndex, 1);
  });
}

function dispatchPlaybackEvent(target: EventTarget, type: string): void {
  target.dispatchEvent(new Event(type));
}

function dispatchTerminalButtonEvent(target: EventTarget, type: string): void {
  dispatchPlaybackEvent(target, type);
  changeListeners.delete(target);
}

function recordWebPlay(sound: Sound) {
  fetch(`${SOUNDS_API_PATH}/${encodeURIComponent(sound.name)}/play`, {
    method: "POST",
  }).catch(() => {});
}

function getAudioContext(): AudioContext {
  if (!audioCtx) audioCtx = new AudioContext();
  return audioCtx;
}

function unlockAudioContext(): Promise<void> {
  const ctx = getAudioContext();
  if (ctx.state === "running") return Promise.resolve();
  return ctx.resume().then(() => {
    if (ctx.state !== "running") {
      throw new Error("AudioContext did not enter the running state");
    }
  });
}

function beginAudioContextUnlock(): Promise<void> {
  const contextReady = unlockAudioContext();
  void contextReady.catch(() => {});
  return contextReady;
}

function decodedAudioBytes(buffer: AudioBuffer): number {
  return buffer.length * buffer.numberOfChannels * Float32Array.BYTES_PER_ELEMENT;
}

function touchDecodedAudio(cacheKey: string, decoded: DecodedAudio): void {
  decodedAudio.delete(cacheKey);
  decodedAudio.set(cacheKey, decoded);
}

function decodedCacheBytes(): number {
  let bytes = 0;
  decodedAudio.forEach((decoded) => (bytes += decoded.bytes));
  return bytes;
}

function cacheDecodedAudio(cacheKey: string, buffer: AudioBuffer): void {
  const bytes = decodedAudioBytes(buffer);
  if (bytes > DECODED_CACHE_LIMIT_BYTES) return;

  const existing = decodedAudio.get(cacheKey);
  if (existing) decodedAudio.delete(cacheKey);

  let cacheBytes = decodedCacheBytes();
  while (cacheBytes + bytes > DECODED_CACHE_LIMIT_BYTES) {
    let evictableKey: string | null = null;
    let evictableBytes = 0;
    for (const [candidateKey, decoded] of decodedAudio) {
      if (decoded.pins !== 0) continue;
      evictableKey = candidateKey;
      evictableBytes = decoded.bytes;
      break;
    }
    if (evictableKey === null) {
      if (existing) decodedAudio.set(cacheKey, existing);
      return;
    }
    decodedAudio.delete(evictableKey);
    cacheBytes -= evictableBytes;
  }

  decodedAudio.set(cacheKey, { buffer, bytes, pins: 0 });
}

function getDecodedAudio(cacheKey: string): Promise<AudioBuffer> {
  const cached = decodedAudio.get(cacheKey);
  if (cached) {
    touchDecodedAudio(cacheKey, cached);
    return Promise.resolve(cached.buffer);
  }
  const active = activeDecodedAudio.get(cacheKey);
  if (active) return Promise.resolve(active.buffer);

  const inFlight = inFlightAudio.get(cacheKey);
  if (inFlight) return inFlight;

  const ctx = getAudioContext();
  const decode = fetch(cacheKey)
    .then((response) => {
      if (!response.ok) {
        throw new Error(`Unable to fetch audio (${response.status})`);
      }
      return response.arrayBuffer();
    })
    .then((encodedAudio) => ctx.decodeAudioData(encodedAudio))
    .then((buffer) => {
      cacheDecodedAudio(cacheKey, buffer);
      return buffer;
    })
    .finally(() => {
      if (inFlightAudio.get(cacheKey) === decode) {
        inFlightAudio.delete(cacheKey);
      }
    });

  inFlightAudio.set(cacheKey, decode);
  return decode;
}

function pinDecodedAudio(cacheKey: string, buffer: AudioBuffer): void {
  const cached = decodedAudio.get(cacheKey);
  if (cached?.buffer === buffer) {
    cached.pins += 1;
    touchDecodedAudio(cacheKey, cached);
    return;
  }

  const active = activeDecodedAudio.get(cacheKey);
  if (active?.buffer === buffer) {
    active.pins += 1;
    return;
  }
  activeDecodedAudio.set(cacheKey, {
    buffer,
    bytes: decodedAudioBytes(buffer),
    pins: 1,
  });
}

function releaseDecodedAudio(cacheKey: string, buffer: AudioBuffer): void {
  const cached = decodedAudio.get(cacheKey);
  if (cached?.buffer === buffer) {
    cached.pins = Math.max(0, cached.pins - 1);
    return;
  }

  const active = activeDecodedAudio.get(cacheKey);
  if (!active || active.buffer !== buffer) return;
  active.pins = Math.max(0, active.pins - 1);
  if (active.pins === 0) activeDecodedAudio.delete(cacheKey);
}

function createBufferVoice(
  sound: Sound,
  cacheKey: string,
  buffer: AudioBuffer,
  element: EventTarget
): BufferVoice {
  const ctx = getAudioContext();
  const source = ctx.createBufferSource();
  const gain = ctx.createGain();
  source.buffer = buffer;
  gain.gain.value = volume;
  source.connect(gain);
  gain.connect(ctx.destination);
  pinDecodedAudio(cacheKey, buffer);

  return {
    engine: "decoded-buffer",
    element,
    source,
    gain,
    sound,
    cacheKey,
    buffer,
    startedAt: ctx.currentTime,
    duration: buffer.duration,
    stopped: false,
  };
}

function createMediaVoice(
  sound: Sound,
  cacheKey: string,
  element: EventTarget
): MediaVoice {
  const ctx = getAudioContext();
  const media = document.createElement("audio");
  const source = ctx.createMediaElementSource(media);
  const gain = ctx.createGain();
  media.preload = "auto";
  media.src = cacheKey;
  gain.gain.value = volume;
  source.connect(gain);
  gain.connect(ctx.destination);

  return {
    engine: "media-element",
    element,
    source,
    gain,
    sound,
    media,
    stopped: false,
  };
}

function disconnectVoice(voice: Voice): void {
  if (voice.stopped) return;
  voice.stopped = true;

  if (voice.engine === "decoded-buffer") {
    voice.source.onended = null;
    try {
      voice.source.stop();
    } catch {
      // A naturally ended one-shot source cannot be stopped again.
    }
    releaseDecodedAudio(voice.cacheKey, voice.buffer);
  } else {
    voice.media.onended = null;
    voice.media.onerror = null;
    voice.media.pause();
    voice.media.removeAttribute("src");
    voice.media.load();
  }

  voice.source.disconnect();
  voice.gain.disconnect();
}

function addButtonVoice(voice: Voice): void {
  const voices = buttonAudio.get(voice.sound);
  if (voices) voices.push(voice);
  else buttonAudio.set(voice.sound, [voice]);
}

function removeButtonVoice(voice: Voice): void {
  const voices = buttonAudio.get(voice.sound);
  if (!voices) return;
  const index = voices.indexOf(voice);
  if (index !== -1) voices.splice(index, 1);
  if (voices.length === 0) buttonAudio.delete(voice.sound);
}

function finishButtonVoice(voice: Voice, eventType: "pause" | "ended"): void {
  if (voice.stopped) return;
  removeButtonVoice(voice);
  disconnectVoice(voice);
  dispatchTerminalButtonEvent(voice.element, eventType);
}

async function startMediaButtonAudio(request: ButtonRequest): Promise<void> {
  if (request.cancelled || request.mediaStarted) return;
  request.mediaStarted = true;

  let voice: MediaVoice;
  try {
    voice = createMediaVoice(request.sound, request.cacheKey, request.element);
    pendingButtonAudio.delete(request);
    addButtonVoice(voice);
    voice.media.onended = () => finishButtonVoice(voice, "ended");
    voice.media.onerror = () => finishButtonVoice(voice, "pause");
    const mediaStarted = voice.media.play();
    await Promise.all([request.contextReady, mediaStarted]);
  } catch {
    pendingButtonAudio.delete(request);
    if (typeof voice! !== "undefined") {
      removeButtonVoice(voice);
      disconnectVoice(voice);
    }
    if (!request.cancelled) {
      dispatchTerminalButtonEvent(request.element, "pause");
    }
    return;
  }

  if (!request.cancelled && !voice.stopped) {
    dispatchPlaybackEvent(voice.element, "play");
  }
}

async function startButtonAudio(request: ButtonRequest): Promise<void> {
  let buffer: AudioBuffer;
  try {
    buffer = await getDecodedAudio(request.cacheKey);
  } catch {
    if (!request.cancelled) void startMediaButtonAudio(request);
    return;
  }

  if (request.cancelled) return;
  try {
    await request.contextReady;
  } catch {
    pendingButtonAudio.delete(request);
    dispatchTerminalButtonEvent(request.element, "pause");
    return;
  }
  if (request.cancelled) return;
  pendingButtonAudio.delete(request);

  let voice: BufferVoice;
  try {
    voice = createBufferVoice(
      request.sound,
      request.cacheKey,
      buffer,
      request.element
    );
    addButtonVoice(voice);
    voice.source.onended = () => finishButtonVoice(voice, "ended");
    voice.source.start();
  } catch {
    if (typeof voice! !== "undefined") {
      removeButtonVoice(voice);
      disconnectVoice(voice);
    }
    void startMediaButtonAudio(request);
    return;
  }

  dispatchPlaybackEvent(voice.element, "play");
}

export function playButtonAudio(sound: Sound, updateCb: ChangeListener) {
  const soundPath = getSoundPath(sound);
  if (!soundPath) return;

  const request: ButtonRequest = {
    sound,
    cacheKey: soundPath,
    element: new EventTarget(),
    contextReady: beginAudioContextUnlock(),
    mediaStarted: false,
    cancelled: false,
  };
  attachPlaybackChangeListener(request.element, updateCb);
  pendingButtonAudio.add(request);
  recordWebPlay(sound);
  if (preferredPlaybackEngine === "media-element") {
    void startMediaButtonAudio(request);
  } else {
    void startButtonAudio(request);
  }
}

function stopMainVoice(voice: Voice, eventType: "pause" | "ended"): void {
  if (mainVoice !== voice || voice.stopped) return;
  mainVoice = null;
  mainSound = null;
  disconnectVoice(voice);
  dispatchPlaybackEvent(mainAudioEvents, eventType);
}

function cancelCurrentMainAudio(): boolean {
  const hadPending = mainPending !== null;
  mainPending = null;
  if (mainVoice) {
    stopMainVoice(mainVoice, "pause");
    return true;
  }
  if (hadPending) {
    mainSound = null;
    dispatchPlaybackEvent(mainAudioEvents, "pause");
  }
  return hadPending;
}

function failMainRequest(request: MainRequest): void {
  if (mainGeneration !== request.generation) return;
  if (mainPending === request) mainPending = null;
  mainSound = null;
  dispatchPlaybackEvent(mainAudioEvents, "pause");
}

async function startMediaMainAudio(request: MainRequest): Promise<void> {
  if (
    request.mediaStarted ||
    mainGeneration !== request.generation ||
    mainPending !== request
  )
    return;
  request.mediaStarted = true;

  let voice: MediaVoice;
  try {
    voice = createMediaVoice(request.sound, request.cacheKey, mainAudioEvents);
    mainVoice = voice;
    mainPending = null;
    mainSound = request.sound;
    voice.media.onended = () => stopMainVoice(voice, "ended");
    voice.media.onerror = () => stopMainVoice(voice, "pause");
    const mediaStarted = voice.media.play();
    await Promise.all([request.contextReady, mediaStarted]);
  } catch {
    if (typeof voice! !== "undefined" && mainVoice === voice) {
      stopMainVoice(voice, "pause");
    } else {
      failMainRequest(request);
    }
    return;
  }

  if (
    mainGeneration === request.generation &&
    mainVoice === voice &&
    !voice.stopped
  ) {
    dispatchPlaybackEvent(mainAudioEvents, "play");
  }
}

async function startMainAudio(request: MainRequest): Promise<void> {
  let buffer: AudioBuffer;
  try {
    buffer = await getDecodedAudio(request.cacheKey);
  } catch {
    void startMediaMainAudio(request);
    return;
  }

  if (mainGeneration !== request.generation || mainPending !== request) return;
  try {
    await request.contextReady;
  } catch {
    failMainRequest(request);
    return;
  }
  if (mainGeneration !== request.generation || mainPending !== request) return;

  let voice: BufferVoice;
  try {
    voice = createBufferVoice(
      request.sound,
      request.cacheKey,
      buffer,
      mainAudioEvents
    );
    mainVoice = voice;
    mainPending = null;
    mainSound = request.sound;
    voice.source.onended = () => stopMainVoice(voice, "ended");
    voice.source.start();
  } catch {
    if (typeof voice! !== "undefined") {
      if (mainVoice === voice) mainVoice = null;
      disconnectVoice(voice);
    }
    if (mainGeneration === request.generation) {
      mainPending = request;
      mainSound = request.sound;
      void startMediaMainAudio(request);
    }
    return;
  }

  dispatchPlaybackEvent(mainAudioEvents, "play");
}

export function playMainAudio(sound: Sound) {
  const soundPath = getSoundPath(sound);
  if (!soundPath) return;

  mainGeneration += 1;
  cancelCurrentMainAudio();
  const request: MainRequest = {
    generation: mainGeneration,
    sound,
    cacheKey: soundPath,
    contextReady: beginAudioContextUnlock(),
    mediaStarted: false,
  };
  mainPending = request;
  mainSound = sound;
  recordWebPlay(sound);
  if (preferredPlaybackEngine === "media-element") {
    void startMediaMainAudio(request);
  } else {
    void startMainAudio(request);
  }
}

export function getActiveButtonAudioGroups(
  sound?: Sound
): Map<Sound, AudioGroup[]> {
  const audioGroups = new Map<Sound, AudioGroup[]>();
  buttonAudio.forEach((voices, buttonSound) => {
    if (!sound || buttonSound === sound)
      audioGroups.set(buttonSound, voices.slice());
  });
  pendingButtonAudio.forEach((request) => {
    if ((!sound || request.sound === sound) && !audioGroups.has(request.sound)) {
      audioGroups.set(request.sound, []);
    }
  });
  return audioGroups;
}

export function getActiveAudioGroups(sound?: Sound): Map<Sound, AudioGroup[]> {
  const audioGroups = getActiveButtonAudioGroups(sound);
  if (mainSound && (mainPending || mainVoice) && (!sound || sound === mainSound)) {
    const groups = audioGroups.get(mainSound) ?? [];
    if (mainVoice) groups.push(mainVoice);
    audioGroups.set(mainSound, groups);
  }
  return audioGroups;
}

export function isMainAudioActive(sound?: Sound) {
  return (
    (!sound || sound === mainSound) &&
    mainSound !== null &&
    (mainPending !== null || mainVoice !== null)
  );
}

export function getMainAudioProgress(): number {
  if (!mainVoice) return 0;
  if (mainVoice.engine === "media-element") {
    if (!mainVoice.media.duration) return 0;
    return Math.max(
      0,
      Math.min(1, mainVoice.media.currentTime / mainVoice.media.duration)
    );
  }
  if (!audioCtx || mainVoice.duration <= 0) return 0;
  return Math.max(
    0,
    Math.min(
      1,
      (audioCtx.currentTime - mainVoice.startedAt) / mainVoice.duration
    )
  );
}

export function addMainAudioChangeListener(cb: ChangeListener) {
  attachPlaybackChangeListener(mainAudioEvents, cb);
}

export function removeMainAudioChangeListener(cb: ChangeListener) {
  detachPlaybackChangeListener(mainAudioEvents, cb);
}

export function stopMainAudio() {
  mainGeneration += 1;
  cancelCurrentMainAudio();
}

export function stopAllButtonAudio() {
  pendingButtonAudio.forEach((request) => {
    request.cancelled = true;
    dispatchTerminalButtonEvent(request.element, "pause");
  });
  pendingButtonAudio.clear();

  buttonAudio.forEach((voices) => {
    voices.slice().forEach((voice) => finishButtonVoice(voice, "pause"));
  });
  buttonAudio.clear();
}
