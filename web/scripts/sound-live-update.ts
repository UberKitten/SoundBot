export interface SoundsSnapshot<TSound> {
  sounds: TSound[];
  groups: unknown[];
}

export interface SoundUpdateLike {
  action: string;
  sound_name: string;
  modified: string;
}

interface LiveSound {
  name: string;
  modified: string | null;
}

export interface SoundLiveUpdateBindings<TSound extends LiveSound> {
  sounds: TSound[];
  generations: Map<string, number>;
  fetchSound: (name: string) => Promise<TSound | null>;
  addRenderedSound: (sound: TSound) => void;
  updateRenderedSound: (sound: TSound) => void;
  removeRenderedSound: (name: string) => void;
  reapplyFilter: () => void;
}

export type SoundLiveUpdateResult =
  | "added"
  | "deleted"
  | "edited"
  | "missing"
  | "stale"
  | "timestamp-updated";

/** Find a sound in the snapshot envelope returned by /api/sounds. */
export function findSoundInSnapshot<TSound extends { name: string }>(
  snapshot: SoundsSnapshot<TSound>,
  name: string
): TSound | null {
  return snapshot.sounds.find((sound) => sound.name === name) ?? null;
}

/** Merge a fresh same-name representation without breaking playback identity. */
export function mergeSoundRepresentation<TSound extends { name: string }>(
  sound: TSound,
  freshSound: TSound
): TSound {
  const mutableSound = sound as Record<string, unknown>;
  for (const key of Object.keys(mutableSound)) {
    if (!(key in freshSound)) delete mutableSound[key];
  }
  Object.assign(sound, freshSound);
  return sound;
}

/** Update both cached and rendered representations of an existing sound. */
export function replaceSoundRepresentation<TSound extends { name: string }>(
  sounds: TSound[],
  name: string,
  freshSound: TSound,
  updateRenderedSound: (sound: TSound) => void
): boolean {
  const sound = sounds.find((candidate) => candidate.name === name);
  if (!sound) return false;

  mergeSoundRepresentation(sound, freshSound);
  updateRenderedSound(sound);
  return true;
}

/** Match the canonical sound name or any canonical alias. */
export function soundMatchesFilter<TSound extends { name: string; aliases?: string[] }>(
  sound: TSound,
  filter: string,
  canonicalize: (value: string) => string | null
): boolean {
  if (!filter) return true;
  if (canonicalize(sound.name)?.includes(filter)) return true;
  return sound.aliases?.some((alias) => canonicalize(alias)?.includes(filter)) ?? false;
}

/**
 * Apply one WebSocket sound action. The generation is advanced synchronously
 * before any fetch, so every later action invalidates older pending work.
 */
export async function applySoundLiveUpdate<TSound extends LiveSound>(
  event: SoundUpdateLike,
  bindings: SoundLiveUpdateBindings<TSound>
): Promise<SoundLiveUpdateResult> {
  const name = event.sound_name;
  const generation = (bindings.generations.get(name) ?? 0) + 1;
  bindings.generations.set(name, generation);

  if (event.action === "delete") {
    const index = bindings.sounds.findIndex((sound) => sound.name === name);
    if (index !== -1) bindings.sounds.splice(index, 1);
    bindings.removeRenderedSound(name);
    return "deleted";
  }

  if (event.action === "add") {
    const sound = await bindings.fetchSound(name);
    if (bindings.generations.get(name) !== generation) return "stale";
    if (!sound) return "missing";
    bindings.sounds.push(sound);
    bindings.addRenderedSound(sound);
    return "added";
  }

  if (event.action === "edit") {
    const sound = await bindings.fetchSound(name);
    if (bindings.generations.get(name) !== generation) return "stale";
    if (!sound) return "missing";
    if (
      !replaceSoundRepresentation(
        bindings.sounds,
        name,
        sound,
        bindings.updateRenderedSound
      )
    ) {
      return "missing";
    }
    bindings.reapplyFilter();
    return "edited";
  }

  const sound = bindings.sounds.find((candidate) => candidate.name === name);
  if (!sound) return "missing";
  sound.modified = event.modified;
  bindings.updateRenderedSound(sound);
  return "timestamp-updated";
}
