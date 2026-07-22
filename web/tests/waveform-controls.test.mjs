import assert from "node:assert/strict";
import test from "node:test";

import {
  computeZoomScroll,
  decideWheelZoom,
  retainPendingZoomFocus,
  formatTimestamp,
  parseTimestamp,
  WAVEFORM_ZOOM_MAX,
  WAVEFORM_ZOOM_MIN,
} from "../scripts/waveform-controls.ts";

test("parses seconds and validated MM:SS / HH:MM:SS timestamps", () => {
  assert.equal(parseTimestamp(" 75.125 "), 75.125);
  assert.equal(parseTimestamp(".5"), 0.5);
  assert.equal(parseTimestamp("02:03.5"), 123.5);
  assert.equal(parseTimestamp("1:02:03.125"), 3723.125);
  assert.equal(parseTimestamp("25:00:00.001"), 90000.001);

  for (const invalid of [
    "",
    "-1",
    "NaN",
    "Infinity",
    "1e3",
    "1:60",
    "60:00",
    "1:60:00",
    "1:00:60",
    "1.5:00",
    "1:2:3:4",
    "1::02",
  ]) {
    assert.equal(parseTimestamp(invalid), null, invalid);
  }
});

test("formats canonical timestamps across hour and subsecond boundaries", () => {
  assert.equal(formatTimestamp(0), "00:00:00");
  assert.equal(formatTimestamp(59.999), "00:00:59.999");
  assert.equal(formatTimestamp(60), "00:01:00");
  assert.equal(formatTimestamp(3599.999), "00:59:59.999");
  assert.equal(formatTimestamp(3600), "01:00:00");
  assert.equal(formatTimestamp(90061.125), "25:01:01.125");
  assert.throws(() => formatTimestamp(-0.01), RangeError);
  assert.throws(() => formatTimestamp(Number.POSITIVE_INFINITY), RangeError);
});

test("timestamp text round-trips millisecond and arbitrary subsecond trim floats", () => {
  for (const seconds of [
    1e-18,
    0.001,
    0.05,
    0.30000000000000004,
    61.23456789,
    3661.000001,
    90061.123456789,
  ]) {
    const text = formatTimestamp(seconds);
    assert.equal(parseTimestamp(text), seconds, `${seconds} via ${text}`);
  }
});

test("wheel zoom decisions clamp and only consume an available vertical step", () => {
  assert.deepEqual(
    decideWheelZoom({ currentZoom: 100, deltaX: 0, deltaY: -1 }),
    { handled: true, nextZoom: 120 }
  );
  assert.deepEqual(
    decideWheelZoom({ currentZoom: WAVEFORM_ZOOM_MAX, deltaX: 0, deltaY: -1 }),
    { handled: false, nextZoom: WAVEFORM_ZOOM_MAX }
  );
  assert.deepEqual(
    decideWheelZoom({ currentZoom: WAVEFORM_ZOOM_MIN, deltaX: 0, deltaY: 1 }),
    { handled: false, nextZoom: WAVEFORM_ZOOM_MIN }
  );

  for (const ignored of [
    { currentZoom: 100, deltaX: 0, deltaY: -1, ctrlKey: true },
    { currentZoom: 100, deltaX: 0, deltaY: -1, metaKey: true },
    { currentZoom: 100, deltaX: 10, deltaY: 2 },
    { currentZoom: 100, deltaX: 0, deltaY: 0 },
  ]) {
    assert.equal(decideWheelZoom(ignored).handled, false);
  }
});

test("zoom scroll math preserves the focal point and clamps at both edges", () => {
  assert.equal(
    computeZoomScroll({
      focalTime: 50,
      duration: 100,
      nextZoom: 10,
      viewportWidth: 200,
      focalViewportX: 100,
    }),
    400
  );
  assert.equal(
    computeZoomScroll({
      focalTime: 0,
      duration: 100,
      nextZoom: 10,
      viewportWidth: 200,
      focalViewportX: 100,
    }),
    0
  );
  assert.equal(
    computeZoomScroll({
      focalTime: 100,
      duration: 100,
      nextZoom: 10,
      viewportWidth: 200,
      focalViewportX: 100,
    }),
    800
  );
  assert.equal(
    computeZoomScroll({
      focalTime: 50,
      duration: 100,
      nextZoom: 0,
      viewportWidth: 200,
      focalViewportX: 100,
    }),
    0
  );
});
test("rapid wheel bursts retain one focal time until scroll correction", () => {
  const firstFocus = retainPendingZoomFocus(null, {
    focalTime: 50,
    focalViewportX: 350,
  });
  const secondFocus = retainPendingZoomFocus(firstFocus, {
    // What a second event would misread from a resized, not-yet-scrolled wave.
    focalTime: 17.5,
    focalViewportX: 350,
  });

  assert.deepEqual(secondFocus, firstFocus);
  assert.equal(
    computeZoomScroll({
      ...secondFocus,
      duration: 100,
      nextZoom: 40,
      viewportWidth: 700,
    }),
    1650
  );
});
