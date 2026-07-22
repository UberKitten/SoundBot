export interface EditorTrimState {
  duration: number;
  start: number;
  end: number;
}

export interface DraftCommitPayload {
  name: string;
  start: number | null;
  end: number | null;
}

export interface TrimPayload {
  start: number;
  end: number;
}

/** Build a draft commit body without leaking ephemeral preview state. */
export function buildDraftCommitPayload(
  name: string,
  state: EditorTrimState
): DraftCommitPayload {
  const fullSpan = state.start <= 0 && state.duration - state.end < 0.001;
  return {
    name,
    start: fullSpan ? null : state.start,
    end: fullSpan ? null : state.end,
  };
}

/** Build an existing-sound trim body without leaking ephemeral preview state. */
export function buildTrimPayload(state: EditorTrimState): TrimPayload {
  return {
    start: state.start,
    end: state.end,
  };
}
