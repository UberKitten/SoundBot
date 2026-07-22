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

test("draft partial selection preserves subsecond boundaries", () => {
  assert.deepEqual(buildDraftCommitPayload("airhorn", baseState), {
    name: "airhorn",
    start: 1.25,
    end: 8.75,
  });
});
