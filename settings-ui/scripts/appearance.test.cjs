const { test } = require("node:test");
const assert = require("node:assert/strict");
const { effectiveAppearance } = require("../electron/appearance.cjs");
const settings = {
  theme: "system",
  material: "acrylic",
  lightOpacity: 60,
  darkOpacity: 36,
  reduceMotion: false,
};
test("materials fall back on unsupported Windows and platforms", () => {
  for (const [platform, version] of [
    ["win32", "10.0.19045"],
    ["win32", "10.0.22000"],
    ["linux", "6.8.0"],
  ])
    assert.equal(
      effectiveAppearance(settings, {}, platform, version).effectiveMaterial,
      "none",
    );
  assert.equal(
    effectiveAppearance(settings, {}, "win32", "10.0.22621").effectiveMaterial,
    "acrylic",
  );
});
test("accessibility preferences override transparency without altering saved values", () => {
  for (const flag of [
    "shouldUseHighContrastColors",
    "inForcedColorsMode",
    "prefersReducedTransparency",
  ]) {
    const value = effectiveAppearance(
      settings,
      { [flag]: true, shouldUseDarkColors: true },
      "win32",
      "10.0.26200",
    );
    assert.equal(value.effectiveMaterial, "none");
    assert.equal(value.effectiveTheme, "dark");
    assert.equal(value.material, "acrylic");
  }
});
