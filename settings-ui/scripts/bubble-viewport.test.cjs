const { test } = require("node:test");
const assert = require("node:assert/strict");
const fs = require("node:fs");
const path = require("node:path");
const vm = require("node:vm");
const ts = require("typescript");
const source = fs.readFileSync(
  path.join(__dirname, "../src/core/bubbleViewport.ts"),
  "utf8",
);
const moduleValue = { exports: {} };
vm.runInNewContext(
  ts.transpileModule(source, {
    compilerOptions: { module: ts.ModuleKind.CommonJS },
  }).outputText,
  { exports: moduleValue.exports },
);
const { fitView, clampView, zoomView, imagePoint, displayPoint, INITIAL_VIEW } =
  moduleValue.exports;
const near = (actual, expected) =>
  assert.ok(Math.abs(actual - expected) < 1e-8, `${actual} != ${expected}`);

test("fit exposes the image and screen-sized editing handles in every window", () => {
  for (const viewport of [
    { width: 280, height: 180 },
    { width: 540, height: 260 },
    { width: 1100, height: 620 },
  ]) {
    for (const image of [
      { width: 308, height: 75 },
      { width: 900, height: 700 },
    ]) {
      const view = fitView(image, viewport);
      assert.ok(view.zoom > 0 && view.zoom <= 4);
      near(view.x * 2 + image.width * view.zoom, viewport.width);
      near(view.y * 2 + image.height * view.zoom, viewport.height);
      assert.ok(view.x >= 28 && view.y >= 28);
    }
  }
});
test("fractional scales and pan round-trip stored logical coordinates", () => {
  for (const zoom of [0.01, 0.375, 1, 1.5, 2, 4]) {
    const view = { x: -134.6, y: 71.3, zoom, fit: false };
    const point = { x: 125.8, y: -10.7 };
    const result = imagePoint(displayPoint(point, view), view);
    near(result.x, point.x);
    near(result.y, point.y);
  }
});
test("zoom anchors a pointer or the center unless an image edge must be clamped", () => {
  const image = { width: 1000, height: 1000 },
    viewport = { width: 600, height: 400 };
  const start = { x: -200, y: -300, zoom: 1, fit: false };
  for (const anchor of [
    { x: 127, y: 153 },
    { x: 300, y: 200 },
  ]) {
    const point = imagePoint(anchor, start);
    const next = zoomView(start, 2, anchor, image, viewport);
    const actual = imagePoint(anchor, next);
    near(actual.x, point.x);
    near(actual.y, point.y);
  }
  assert.equal(zoomView(start, 9, { x: 0, y: 0 }, image, viewport).zoom, 4);
  assert.equal(zoomView(start, -1, { x: 0, y: 0 }, image, viewport).zoom, 0.01);
});
test("pan bounds expose both edges plus handles, and center small axes", () => {
  const image = { width: 1000, height: 100 },
    viewport = { width: 600, height: 400 };
  const left = clampView(
    { ...INITIAL_VIEW, fit: false, x: 10000, y: 10000 },
    image,
    viewport,
  );
  const right = clampView({ ...left, x: -10000, y: -10000 }, image, viewport);
  near(left.x, 28);
  near(right.x + image.width, viewport.width - 28);
  near(left.y, 150);
  near(right.y, 150);
});
