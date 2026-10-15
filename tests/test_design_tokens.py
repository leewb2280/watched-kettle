"""Design tokens stay generated and keep text readable in both themes."""

import unittest

from scripts import generate_design_tokens as generator
from watched_kettle.ui import design_tokens


def _channels(value):
    value = value.lstrip("#")
    alpha = int(value[6:8], 16) / 255 if len(value) == 8 else 1.0
    return [int(value[index : index + 2], 16) / 255 for index in (0, 2, 4)], alpha


def _over(foreground, background):
    """Composite a possibly translucent color over an opaque background."""
    (front, alpha), (back, _) = _channels(foreground), _channels(background)
    mixed = [alpha * f + (1 - alpha) * b for f, b in zip(front, back)]
    return "#" + "".join(f"{round(channel * 255):02x}" for channel in mixed)


def _luminance(value):
    channels, _ = _channels(value)
    linear = [
        c / 12.92 if c <= 0.03928 else ((c + 0.055) / 1.055) ** 2.4 for c in channels
    ]
    return 0.2126 * linear[0] + 0.7152 * linear[1] + 0.0722 * linear[2]


def contrast(foreground, background):
    lighter, darker = sorted(
        (_luminance(foreground), _luminance(background)), reverse=True
    )
    return (lighter + 0.05) / (darker + 0.05)


class DesignTokenTests(unittest.TestCase):
    def test_generated_outputs_match_the_token_source(self):
        tokens = generator.load_tokens()
        for path, content in generator.outputs(tokens).items():
            with self.subTest(path=path.name):
                self.assertEqual(path.read_text(encoding="utf-8"), content)

    def test_text_pairs_meet_the_minimum_contrast_in_both_themes(self):
        tokens = generator.load_tokens()
        minimum = tokens["contrast"]["text"]
        for name, theme in tokens["themes"].items():
            # Cards sit on the translucent surface over the solid page.
            card = _over(theme["surface"], theme["solid"])
            for foreground, background in tokens["contrast"]["pairs"]:
                backgrounds = [theme[background]]
                if background == "solid":
                    backgrounds.append(card)
                for back in backgrounds:
                    with self.subTest(theme=name, pair=(foreground, background)):
                        self.assertGreaterEqual(
                            contrast(theme[foreground], back), minimum
                        )

    def test_python_tokens_expose_aliases_and_fall_back_to_light(self):
        self.assertEqual(
            design_tokens.DARK_THEME["alert"],
            design_tokens.DARK_THEME["status-failed"],
        )
        self.assertIs(design_tokens.theme_tokens("unknown"), design_tokens.LIGHT_THEME)
        self.assertEqual(design_tokens.FONT_FAMILIES[0], "Pretendard")


if __name__ == "__main__":
    unittest.main()
