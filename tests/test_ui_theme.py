from unittest import TestCase

from trade_helper.ui.theme import COLORS, status_color


class UiThemeTests(TestCase):
    def test_all_button_palette_entries_are_available(self) -> None:
        self.assertIn("cyan_soft", COLORS)

    def test_semantic_status_colors_are_distinct(self) -> None:
        self.assertEqual(COLORS["green"], status_color("READY"))
        self.assertEqual(COLORS["yellow"], status_color("REVIEW"))
        self.assertEqual(COLORS["red"], status_color("BLOCKED"))
        self.assertNotEqual(status_color("READY"), status_color("BLOCKED"))
