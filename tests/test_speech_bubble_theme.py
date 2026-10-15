import unittest

from watched_kettle.pet.bubble_theme import (
    DEFAULT_BUBBLE_THEME,
    bubble_theme_from_manifest,
    resolve_bubble_theme,
)


class SpeechBubbleThemeTests(unittest.TestCase):
    def test_missing_package_theme_uses_common_default(self):
        self.assertIsNone(bubble_theme_from_manifest({"id": "plain"}))
        self.assertEqual(
            resolve_bubble_theme({"id": "plain"}, "character"),
            DEFAULT_BUBBLE_THEME,
        )

    def test_package_theme_is_validated_and_bounded(self):
        theme = bubble_theme_from_manifest(
            {
                "bubbleTheme": {
                    "background": "#ABCDEF",
                    "border": "not-a-color",
                    "text": "#123456",
                    "shadow": "#654321",
                    "shadowAlpha": 999,
                    "radius": 2,
                    "borderWidth": 9,
                }
            }
        )

        self.assertEqual(theme.background, "#abcdef")
        self.assertEqual(theme.border, DEFAULT_BUBBLE_THEME.border)
        self.assertEqual(theme.text, "#123456")
        self.assertEqual(theme.shadow_alpha, 120)
        self.assertEqual(theme.radius, 6)
        self.assertEqual(theme.border_width, 4.0)

    def test_default_mode_ignores_package_theme(self):
        manifest = {"bubbleTheme": {"background": "#112233"}}

        self.assertEqual(
            resolve_bubble_theme(manifest, "default"),
            DEFAULT_BUBBLE_THEME,
        )

    def test_expanded_manifest_schema_is_supported(self):
        theme = bubble_theme_from_manifest(
            {
                "bubbleTheme": {
                    "shape": "cloud",
                    "tail": "curved",
                    "fill": {
                        "type": "vertical",
                        "start": "#ffffff",
                        "end": "#ddeeff",
                    },
                    "border": {
                        "color": "#336699",
                        "width": 2.5,
                        "style": "double",
                    },
                    "header": "tab",
                    "ornaments": ["cat-ear", "small-wing"],
                    "effects": {
                        "pattern": "stars",
                        "glow": True,
                    },
                }
            }
        )

        self.assertEqual(theme.shape, "cloud")
        self.assertEqual(theme.tail, "curved")
        self.assertEqual(theme.gradient, "vertical")
        self.assertEqual(theme.fill_end, "#ddeeff")
        self.assertEqual(theme.border_style, "double")
        self.assertEqual(theme.ornament_left, "cat-ear")
        self.assertEqual(theme.ornament_right, "small-wing")
        self.assertTrue(theme.glow)


if __name__ == "__main__":
    unittest.main()
