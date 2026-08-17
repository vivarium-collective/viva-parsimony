import { test } from "node:test";
import assert from "node:assert/strict";
import { resolveGrab, makeMotionGate, makeAdaptiveBudget, vignetteIntensity } from "./vr-helpers.js";

test("resolveGrab: trigger pressed grabs", () => {
  assert.equal(resolveGrab({ buttons: [{ pressed: true }, { pressed: false }] }, null), true);
});

test("resolveGrab: grip pressed grabs", () => {
  assert.equal(resolveGrab({ buttons: [{ pressed: false }, { pressed: true }] }, null), true);
});

test("resolveGrab: hand pinch grabs with no gamepad", () => {
  assert.equal(resolveGrab(null, { pinching: true }), true);
});

test("resolveGrab: nothing pressed does not grab", () => {
  assert.equal(resolveGrab({ buttons: [{ pressed: false }, { pressed: false }] }, { pinching: false }), false);
});

test("resolveGrab: null inputs do not grab or throw", () => {
  assert.equal(resolveGrab(null, null), false);
});

test("makeMotionGate: fires once after idle window elapses", () => {
  const g = makeMotionGate(180);
  g.noteMotion(1000);
  assert.equal(g.shouldFire(1100), false); // still within idle window
  assert.equal(g.shouldFire(1180), true);  // window elapsed → fire once
  assert.equal(g.shouldFire(1200), false);  // does not fire again until new motion
});

test("makeMotionGate: new motion re-arms the gate", () => {
  const g = makeMotionGate(180);
  g.noteMotion(0);
  assert.equal(g.shouldFire(200), true);
  g.noteMotion(500);
  assert.equal(g.shouldFire(600), false);
  assert.equal(g.shouldFire(700), true);
});

test("makeMotionGate: does not fire before any motion", () => {
  const g = makeMotionGate(180);
  assert.equal(g.shouldFire(10000), false);
});

test("makeAdaptiveBudget: exact shrink step (1000*0.80=800, then 800*0.80=640)", () => {
  const b = makeAdaptiveBudget(1000);
  assert.equal(b.update(30), true);
  assert.equal(b.value, 800);
  assert.equal(b.update(30), true);
  assert.equal(b.value, 640);
});

test("makeAdaptiveBudget: dead-zone [66,68) yields no change", () => {
  const b = makeAdaptiveBudget(1000);
  // 67 is in [66,68) → neither shrink nor grow
  assert.equal(b.update(67), false);
  assert.equal(b.value, 1000);
  // 66 is not < 66 → no shrink
  assert.equal(b.update(66), false);
  assert.equal(b.value, 1000);
});

test("makeAdaptiveBudget: shrink threshold boundary — 65 shrinks, 66 does not", () => {
  assert.equal(makeAdaptiveBudget(1000).update(65), true);
  assert.equal(makeAdaptiveBudget(1000).update(66), false);
});

test("makeAdaptiveBudget: exact grow step after one shrink (800*1.05=840)", () => {
  const b = makeAdaptiveBudget(1000);
  b.update(30); // shrink to 800
  assert.equal(b.value, 800);
  assert.equal(b.update(80), true);
  assert.equal(b.value, 840); // round(800*1.05)=840
});

test("makeAdaptiveBudget: clamps at custom min and returns false when at floor", () => {
  const b = makeAdaptiveBudget(1000, { min: 500 });
  for (let i = 0; i < 100; i++) b.update(10);
  assert.equal(b.value, 500);
  assert.equal(b.update(10), false);
});

test("makeAdaptiveBudget: clamps at max — no growth past initial when already at ceiling", () => {
  const b = makeAdaptiveBudget(1000);
  // value starts at 1000 = max; high fps cannot grow past max
  assert.equal(b.update(80), false);
  assert.equal(b.value, 1000);
});

test("vignetteIntensity: zero motion → zero", () => {
  assert.equal(vignetteIntensity(0), 0);
});

test("vignetteIntensity: full motion → maxIntensity", () => {
  assert.equal(vignetteIntensity(1), 0.6);
});

test("vignetteIntensity: clamps above maxAt", () => {
  assert.equal(vignetteIntensity(5), 0.6);
});

test("vignetteIntensity: respects custom opts", () => {
  assert.equal(vignetteIntensity(0.5, { maxAt: 1, maxIntensity: 0.4 }), 0.2);
});
