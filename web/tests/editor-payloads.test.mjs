import assert from "node:assert/strict";
import test from "node:test";

import {
  buildDraftCommitPayload,
  buildTrimPayload,
} from "../scripts/editor-payloads.ts";

const baseState = {
  duration: 12.5,
  start: 1.25,
  end: 8.75,
};

for (const [label, build] of [
  ["draft commit", (state) => buildDraftCommitPayload("airhorn", state)],
  ["trim", buildTrimPayload],
]) {
  test(`${label} payload ignores preview volume`, () => {
    const quiet = build({ ...baseState, previewVolume: 25 });
    const loud = build({ ...baseState, previewVolume: 175 });

    assert.deepEqual(quiet, loud);
    assert.equal("volume_adjust" in quiet, false);
  });
}

test("draft full-span selection maps timestamps to null exactly", () => {
  assert.deepEqual(
    buildDraftCommitPayload("airhorn", {
      duration: 12.5,
      start: 0,
      end: 12.5,
      previewVolume: 175,
    }),
    { name: "airhorn", start: null, end: null }
  );
});

for (const start of [1.0408340855860843e-16, -1.0408340855860843e-16]) {
  test(`draft full-span selection canonicalizes near-zero start ${start}`, () => {
    assert.deepEqual(
      buildDraftCommitPayload("airhorn", {
        duration: 28,
        start,
        end: 28,
      }),
      { name: "airhorn", start: null, end: null }
    );
  });

  test(`trim payload canonicalizes near-zero start ${start}`, () => {
    assert.deepEqual(
      buildTrimPayload({ duration: 28, start, end: 3.875 }),
      { start: 0, end: 3.875 }
    );
  });
}

for (const end of [1.0408340855860843e-16, -1.0408340855860843e-16]) {
  test(`trim payload canonicalizes near-zero end ${end}`, () => {
    assert.deepEqual(
      buildTrimPayload({ duration: 28, start: 0, end }),
      { start: 0, end: 0 }
    );
  });
}

test("draft partial selection preserves subsecond boundaries", () => {
  assert.deepEqual(buildDraftCommitPayload("airhorn", baseState), {
    name: "airhorn",
    start: 1.25,
    end: 8.75,
  });
});
