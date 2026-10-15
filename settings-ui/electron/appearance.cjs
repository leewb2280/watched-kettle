function effectiveAppearance(appearance, nativeTheme, platform, release) {
  // Electron's system materials require Windows 11 22H2 (build 22621).
  const supported =
    platform === "win32" && Number(release.split(".")[2]) >= 22621;
  const solid =
    !supported ||
    nativeTheme.shouldUseHighContrastColors ||
    nativeTheme.inForcedColorsMode ||
    nativeTheme.prefersReducedTransparency;
  return {
    ...appearance,
    effectiveTheme: nativeTheme.shouldUseDarkColors ? "dark" : "light",
    effectiveMaterial: solid ? "none" : appearance.material,
    highContrast: nativeTheme.shouldUseHighContrastColors,
  };
}
module.exports = { effectiveAppearance };
