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

const TRIM_TIME_ZERO_EPSILON = 0.000001;

function canonicalizeTrimTimestamp(value: number): number {
  return Math.abs(value) <= TRIM_TIME_ZERO_EPSILON ? 0 : value;
}

/** Build a draft commit body without leaking ephemeral preview state. */
export function buildDraftCommitPayload(
  name: string,
  state: EditorTrimState
): DraftCommitPayload {
  const start = canonicalizeTrimTimestamp(state.start);
  const end = canonicalizeTrimTimestamp(state.end);
  const fullSpan =
    start === 0 && Math.abs(state.duration - end) < 0.001;
  return {
    name,
    start: fullSpan ? null : start,
    end: fullSpan ? null : end,
  };
}

/** Build an existing-sound trim body without leaking ephemeral preview state. */
export function buildTrimPayload(state: EditorTrimState): TrimPayload {
  return {
    start: canonicalizeTrimTimestamp(state.start),
    end: canonicalizeTrimTimestamp(state.end),
  };
}
