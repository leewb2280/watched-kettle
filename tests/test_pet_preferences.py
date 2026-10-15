import unittest

from PySide6.QtCore import QObject, Signal

from watched_kettle.app_preferences import (
    ApplicationPreferences,
    PET_CATALOG_SORT_CUSTOM,
    PET_CATALOG_SORT_NAME,
)
from watched_kettle.features.usage.viewmodel import UsageViewModel
from watched_kettle.pet.preferences import PetPreferences
from watched_kettle.pet.placement import SavedWindowPlacement


class FakeSettings:
    def __init__(self, values=None):
        self.values = dict(values or {})

    def value(self, key, default=None, type=None):
        value = self.values.get(key, default)
        return type(value) if type is not None else value

    def setValue(self, key, value):
        self.values[key] = value

    def remove(self, key):
        self.values.pop(key, None)


class FakeUsageService(QObject):
    snapshot_changed = Signal(object)

    def __init__(self):
        super().__init__()
        from watched_kettle.usage.models import UsageSnapshot

        self.snapshot = UsageSnapshot()
        self.enabled = True
        self.quiet_summary_enabled = True


class PetPreferencesTests(unittest.TestCase):
    def test_selected_pet_is_persisted_application_wide(self):
        settings = FakeSettings()
        preferences = ApplicationPreferences(settings)

        preferences.save_selected_pet_id("sample-pet")

        self.assertEqual(preferences.load_selected_pet_id(), "sample-pet")
        self.assertEqual(settings.values["selectedPetId"], "sample-pet")

    def test_pet_catalog_preferences_default_to_name_order_and_visible(self):
        preferences = ApplicationPreferences(FakeSettings())

        self.assertEqual(
            preferences.load_pet_catalog_sort_mode(),
            PET_CATALOG_SORT_NAME,
        )
        self.assertEqual(preferences.load_pet_custom_order(), ())
        self.assertEqual(preferences.load_hidden_pet_ids(), frozenset())

    def test_pet_catalog_preferences_normalize_and_round_trip(self):
        settings = FakeSettings()
        preferences = ApplicationPreferences(settings)

        self.assertEqual(
            preferences.save_pet_catalog_sort_mode("CUSTOM"),
            PET_CATALOG_SORT_CUSTOM,
        )
        self.assertEqual(
            preferences.save_pet_custom_order(["two", "one", "two", ""]),
            ("two", "one"),
        )
        self.assertEqual(
            preferences.save_hidden_pet_ids(["hidden", "hidden", ""]),
            frozenset({"hidden"}),
        )
        self.assertEqual(
            preferences.load_pet_custom_order(),
            ("two", "one"),
        )
        self.assertEqual(
            preferences.load_hidden_pet_ids(),
            frozenset({"hidden"}),
        )

    def test_invalid_pet_catalog_preferences_fail_safe(self):
        preferences = ApplicationPreferences(
            FakeSettings(
                {
                    "petCatalog/sortMode": "unexpected",
                    "petCatalog/customOrder": "not-json",
                    "petCatalog/hiddenIds": '{"not": "a list"}',
                }
            )
        )

        self.assertEqual(
            preferences.load_pet_catalog_sort_mode(),
            PET_CATALOG_SORT_NAME,
        )
        self.assertEqual(preferences.load_pet_custom_order(), ())
        self.assertEqual(preferences.load_hidden_pet_ids(), frozenset())

    def test_bubbles_default_on_and_are_persisted_application_wide(self):
        settings = FakeSettings()
        preferences = ApplicationPreferences(settings)

        self.assertTrue(preferences.load_bubbles_enabled())
        preferences.save_bubbles_enabled(False)

        self.assertFalse(preferences.load_bubbles_enabled())
        self.assertFalse(settings.values["bubblesEnabled"])

    def test_usage_assistant_defaults_are_private_and_quiet(self):
        settings = FakeSettings()
        preferences = ApplicationPreferences(settings)

        self.assertTrue(preferences.load_usage_enabled())
        self.assertTrue(preferences.load_usage_quiet_summary_enabled())
        self.assertTrue(preferences.load_usage_widget_visible())
        self.assertEqual(preferences.load_usage_widget_shape(), "rings")
        self.assertEqual(preferences.load_usage_widget_emphasis(), "auto")
        self.assertTrue(preferences.load_usage_widget_tasks_visible())
        self.assertFalse(preferences.load_usage_widget_today_visible())
        self.assertEqual(preferences.load_usage_widget_theme_mode(), "app")
        self.assertEqual(preferences.load_usage_widget_limit_key(), "")
        self.assertEqual(preferences.load_usage_widget_background_color(), "#263246")
        self.assertEqual(preferences.load_usage_widget_background_opacity(), 93)
        self.assertEqual(preferences.load_usage_widget_scale(), 100)
        self.assertEqual(preferences.load_usage_widget_hour_range(), (0, 24))
        self.assertEqual(preferences.load_usage_widget_offset(), (0, 0))
        self.assertIsNone(preferences.load_usage_widget_legacy_offset())
        self.assertFalse(preferences.load_usage_widget_detached())
        self.assertIsNone(preferences.load_usage_widget_placement())
        self.assertEqual(preferences.load_usage_chart_days(), 7)
        self.assertEqual(preferences.load_usage_threshold_markers(), frozenset())

        preferences.save_usage_enabled(False)
        preferences.save_usage_quiet_summary_enabled(False)
        preferences.save_usage_widget_visible(False)
        preferences.save_usage_widget_shape("bars")
        preferences.save_usage_widget_emphasis("seven_day")
        preferences.save_usage_widget_tasks_visible(False)
        preferences.save_usage_widget_today_visible(True)
        preferences.save_usage_widget_theme_mode("custom")
        preferences.save_usage_widget_background_color("#f7ead8")
        preferences.save_usage_widget_background_opacity(0)
        preferences.save_usage_widget_scale(127)
        preferences.save_usage_widget_hour_range(7, 22)
        preferences.save_usage_widget_offset(35, -18)
        preferences.save_usage_chart_days(30)
        preferences.save_usage_threshold_markers({"b", "a"})
        preferences.save_usage_last_summary_date("2026-09-04")

        self.assertFalse(preferences.load_usage_enabled())
        self.assertFalse(preferences.load_usage_quiet_summary_enabled())
        self.assertFalse(preferences.load_usage_widget_visible())
        self.assertEqual(preferences.load_usage_widget_shape(), "bars")
        self.assertFalse(preferences.load_usage_widget_tasks_visible())
        self.assertTrue(preferences.load_usage_widget_today_visible())
        self.assertEqual(preferences.load_usage_widget_theme_mode(), "custom")
        # The usage service charts the emphasized Codex limit.
        self.assertEqual(preferences.load_usage_widget_limit_key(), "codex|secondary")
        self.assertEqual(preferences.save_usage_widget_shape("unknown"), "rings")
        self.assertEqual(preferences.load_usage_widget_background_color(), "#F7EAD8")
        self.assertEqual(preferences.load_usage_widget_background_opacity(), 0)
        self.assertEqual(preferences.load_usage_widget_scale(), 130)
        self.assertEqual(preferences.load_usage_widget_hour_range(), (7, 22))
        self.assertEqual(preferences.load_usage_widget_offset(), (35, -18))
        self.assertEqual(preferences.load_usage_widget_legacy_offset(), (35, -18))
        self.assertEqual(preferences.load_usage_chart_days(), 30)
        # The overview offers 14 days too; unknown ranges fall back to 7.
        self.assertEqual(preferences.save_usage_chart_days(14), 14)
        self.assertEqual(preferences.load_usage_chart_days(), 14)
        self.assertEqual(preferences.save_usage_chart_days(10), 7)
        self.assertEqual(
            preferences.load_usage_threshold_markers(), frozenset({"a", "b"})
        )
        self.assertEqual(preferences.load_usage_last_summary_date(), "2026-09-04")

        preferences.reset_usage_widget_offset()
        self.assertEqual(preferences.load_usage_widget_offset(), (0, 0))
        preferences.reset_usage_widget_style()
        self.assertEqual(preferences.load_usage_widget_background_color(), "#263246")
        self.assertEqual(preferences.load_usage_widget_background_opacity(), 93)
        preferences.reset_usage_widget_scale()
        self.assertEqual(preferences.load_usage_widget_scale(), 100)
        preferences.reset_usage_widget_hour_range()
        self.assertEqual(preferences.load_usage_widget_hour_range(), (0, 24))

    def test_usage_widget_detached_placement_round_trips_and_resets(self):
        settings = FakeSettings()
        preferences = ApplicationPreferences(settings)
        placement = SavedWindowPlacement(
            screen_name="DISPLAY2",
            x=-1400,
            y=300,
            work_x=-1920,
            work_y=0,
            work_width=1920,
            work_height=1080,
            relative_x=0.25,
            relative_y=0.4,
        )

        preferences.save_usage_widget_placement(placement)
        preferences.save_usage_widget_detached(True)

        self.assertTrue(preferences.load_usage_widget_detached())
        self.assertEqual(preferences.load_usage_widget_placement(), placement)

        service = FakeUsageService()
        viewmodel = UsageViewModel(service, preferences)
        viewmodel.reset_widget_position()

        self.assertFalse(viewmodel.widget_detached)
        self.assertIsNone(viewmodel.widget_placement)

    def test_usage_widget_style_values_are_validated_and_clamped(self):
        preferences = ApplicationPreferences(
            FakeSettings(
                {
                    "usage/widgetBackgroundColor": "not-a-color",
                    "usage/widgetBackgroundOpacity": -5,
                    "usage/widgetScalePercent": 40,
                    "usage/widgetScaleBasisVersion": 2,
                }
            )
        )
        self.assertEqual(preferences.load_usage_widget_background_color(), "#263246")
        self.assertEqual(preferences.load_usage_widget_background_opacity(), 0)
        self.assertEqual(preferences.load_usage_widget_scale(), 70)
        self.assertEqual(preferences.save_usage_widget_background_opacity(5), 5)
        self.assertEqual(preferences.save_usage_widget_background_opacity(120), 100)
        self.assertEqual(preferences.save_usage_widget_scale(124), 120)
        self.assertEqual(preferences.save_usage_widget_scale(170), 130)
        self.assertEqual(preferences.save_usage_widget_hour_range(22, 7), (0, 24))

    def test_legacy_usage_widget_scale_is_rebased_once_without_visual_change(self):
        settings = FakeSettings({"usage/widgetScalePercent": 130})
        preferences = ApplicationPreferences(settings)

        self.assertEqual(preferences.load_usage_widget_scale(), 100)
        self.assertEqual(settings.values["usage/widgetScalePercent"], 100)
        self.assertEqual(settings.values["usage/widgetScaleBasisVersion"], 2)
        self.assertEqual(preferences.load_usage_widget_scale(), 100)

    def test_usage_widget_version_one_settings_migrate_once(self):
        cases = (
            ({}, ("auto", False, "app")),
            (
                {
                    "usage/widgetConfigVersion": 1,
                    "usage/widgetLayoutPreset": "detailed",
                    "usage/widgetLimitKey": "codex|primary",
                },
                ("five_hour", True, "app"),
            ),
            (
                {
                    "usage/widgetConfigVersion": 1,
                    "usage/widgetGraphMetric": "local_tokens",
                    "usage/widgetLimitKey": "claude_code|secondary",
                    "usage/widgetBackgroundColor": "#F7EAD8",
                },
                ("seven_day", True, "custom"),
            ),
            (
                {
                    "usage/widgetConfigVersion": 1,
                    "usage/widgetLayoutPreset": "simple",
                    "usage/widgetBackgroundColor": "#263246",
                },
                ("auto", False, "app"),
            ),
        )
        for values, (emphasis, today, theme) in cases:
            with self.subTest(values=values):
                settings = FakeSettings(dict(values))
                preferences = ApplicationPreferences(settings)
                self.assertEqual(preferences.load_usage_widget_shape(), "rings")
                self.assertEqual(preferences.load_usage_widget_emphasis(), emphasis)
                self.assertEqual(preferences.load_usage_widget_today_visible(), today)
                self.assertTrue(preferences.load_usage_widget_tasks_visible())
                self.assertEqual(preferences.load_usage_widget_theme_mode(), theme)
                self.assertEqual(settings.values["usage/widgetConfigVersion"], 2)
                # Old keys stay for older builds; migration runs only once.
                for key, value in values.items():
                    if key != "usage/widgetConfigVersion":
                        self.assertEqual(settings.values[key], value)
                settings.values["usage/widgetLayoutPreset"] = "detailed"
                preferences.save_usage_widget_today_visible(False)
                self.assertFalse(preferences.load_usage_widget_today_visible())

    def test_usage_widget_view_model_changes_and_reset(self):
        service = FakeUsageService()
        selected = []
        service.set_selected_limit_key = selected.append
        viewmodel = UsageViewModel(service, ApplicationPreferences(FakeSettings()))

        self.assertEqual(viewmodel.set_widget_shape("chips"), "chips")
        self.assertEqual(viewmodel.set_widget_emphasis("five_hour"), "five_hour")
        self.assertEqual(selected, ["codex|primary"])
        self.assertFalse(viewmodel.set_widget_tasks_visible(False))
        self.assertTrue(viewmodel.set_widget_today_visible(True))
        self.assertEqual(viewmodel.set_widget_theme_mode("custom"), "custom")
        self.assertEqual(viewmodel.set_widget_hour_range(7, 22), (7, 22))

        viewmodel.reset_widget_settings()
        self.assertEqual(viewmodel.widget_shape, "rings")
        self.assertEqual(viewmodel.widget_emphasis, "auto")
        self.assertTrue(viewmodel.widget_tasks_visible)
        self.assertFalse(viewmodel.widget_today_visible)
        self.assertEqual(selected[-1], "")
        # Style and placement are separate resets.
        self.assertEqual(viewmodel.widget_theme_mode, "custom")
        self.assertEqual(viewmodel.widget_hour_range, (7, 22))

    def test_bubble_scale_defaults_normalizes_and_persists(self):
        settings = FakeSettings()
        preferences = ApplicationPreferences(settings)

        self.assertEqual(preferences.load_bubble_scale(), 100)
        self.assertEqual(preferences.save_bubble_scale(137), 140)
        self.assertEqual(settings.values["bubbleScalePercent"], 140)
        self.assertEqual(preferences.load_bubble_scale(), 140)

        settings.values["bubbleScalePercent"] = 30
        self.assertEqual(preferences.load_bubble_scale(), 80)
        settings.values["bubbleScalePercent"] = "invalid"
        self.assertEqual(preferences.load_bubble_scale(), 100)

    def test_bubble_duration_defaults_normalizes_and_persists(self):
        settings = FakeSettings()
        preferences = ApplicationPreferences(settings)

        self.assertEqual(preferences.load_bubble_duration_seconds(), 8)
        self.assertEqual(preferences.save_bubble_duration_seconds(12), 12)
        self.assertEqual(settings.values["bubbleDurationSeconds"], 12)

        settings.values["bubbleDurationSeconds"] = 2
        self.assertEqual(preferences.load_bubble_duration_seconds(), 5)
        settings.values["bubbleDurationSeconds"] = 99
        self.assertEqual(preferences.load_bubble_duration_seconds(), 60)
        settings.values["bubbleDurationSeconds"] = "invalid"
        self.assertEqual(preferences.load_bubble_duration_seconds(), 8)

    def test_bubble_theme_mode_defaults_validates_and_persists(self):
        settings = FakeSettings()
        preferences = ApplicationPreferences(settings)

        self.assertEqual(preferences.load_bubble_theme_mode(), "character")
        self.assertEqual(preferences.save_bubble_theme_mode("default"), "default")
        self.assertEqual(settings.values["bubbleThemeMode"], "default")

        settings.values["bubbleThemeMode"] = "unknown"
        self.assertEqual(preferences.load_bubble_theme_mode(), "character")

    def test_activity_labels_default_off_and_are_persisted(self):
        settings = FakeSettings()
        preferences = ApplicationPreferences(settings)

        self.assertFalse(preferences.load_activity_labels_enabled())
        preferences.save_activity_labels_enabled(True)

        self.assertTrue(preferences.load_activity_labels_enabled())
        self.assertTrue(settings.values["activityLabelsEnabled"])

    def test_codex_not_detected_notice_defaults_off_and_is_persisted(self):
        settings = FakeSettings()
        preferences = ApplicationPreferences(settings)

        self.assertFalse(preferences.load_codex_not_detected_notice_shown())
        preferences.save_codex_not_detected_notice_shown(True)

        self.assertTrue(preferences.load_codex_not_detected_notice_shown())

    def test_auto_movement_screen_defaults_to_current_display(self):
        preferences = ApplicationPreferences(FakeSettings())

        self.assertEqual(
            preferences.load_auto_movement_screen(),
            ("current", ""),
        )

    def test_specific_auto_movement_screen_is_persisted(self):
        settings = FakeSettings()
        preferences = ApplicationPreferences(settings)

        preferences.save_auto_movement_screen("specific", "DISPLAY2")

        self.assertEqual(
            preferences.load_auto_movement_screen(),
            ("specific", "DISPLAY2"),
        )

    def test_window_placement_round_trips_application_wide(self):
        settings = FakeSettings()
        preferences = ApplicationPreferences(settings)
        placement = SavedWindowPlacement(
            screen_name="DISPLAY2",
            x=-1400,
            y=300,
            work_x=-1920,
            work_y=0,
            work_width=1920,
            work_height=1080,
            relative_x=0.25,
            relative_y=0.4,
        )

        preferences.save_window_placement(placement)

        self.assertEqual(preferences.load_window_placement(), placement)

    def test_invalid_window_placement_is_ignored(self):
        settings = FakeSettings(
            {
                "windowPlacement/screenName": "DISPLAY2",
                "windowPlacement/x": "invalid",
                "windowPlacement/y": 10,
                "windowPlacement/workX": 0,
                "windowPlacement/workY": 0,
                "windowPlacement/workWidth": 1920,
                "windowPlacement/workHeight": 1080,
                "windowPlacement/relativeX": 0.5,
                "windowPlacement/relativeY": 0.5,
            }
        )

        self.assertIsNone(ApplicationPreferences(settings).load_window_placement())

    def test_legacy_scale_is_migrated_to_nearest_width(self):
        settings = FakeSettings({"pets/test-pet/scale": 1.5})
        preferences = PetPreferences("test-pet", settings)

        self.assertEqual(preferences.load_width(), 288)
        self.assertEqual(
            settings.values["pets/test-pet/width"],
            288,
        )
        self.assertNotIn("pets/test-pet/scale", settings.values)

    def test_saved_width_is_snapped_to_supported_option(self):
        settings = FakeSettings({"pets/test-pet/width": 250})
        preferences = PetPreferences("test-pet", settings)

        self.assertEqual(preferences.load_width(), 256)

    def test_always_on_top_defaults_to_enabled(self):
        preferences = PetPreferences("test-pet", FakeSettings())

        self.assertTrue(preferences.load_always_on_top())

    def test_auto_movement_defaults_to_disabled(self):
        preferences = PetPreferences("test-pet", FakeSettings())

        self.assertFalse(preferences.load_auto_movement_enabled())

    def test_auto_movement_is_persisted_per_pet(self):
        settings = FakeSettings()
        preferences = PetPreferences("test-pet", settings)

        preferences.save_auto_movement_enabled(True)

        self.assertTrue(settings.values["pets/test-pet/autoMovementEnabled"])

    def test_always_on_top_is_persisted(self):
        settings = FakeSettings()
        preferences = PetPreferences("test-pet", settings)

        preferences.save_always_on_top(False)

        self.assertFalse(settings.values["pets/test-pet/alwaysOnTop"])

    def test_look_range_defaults_to_smaller_240_pixels(self):
        preferences = PetPreferences("test-pet", FakeSettings())

        self.assertEqual(preferences.load_look_range(), 240)

    def test_saved_look_range_is_clamped_and_snapped(self):
        preferences = PetPreferences(
            "test-pet",
            FakeSettings({"pets/test-pet/lookRange": 251}),
        )

        self.assertEqual(preferences.load_look_range(), 260)

        settings = FakeSettings()
        preferences = PetPreferences("test-pet", settings)
        preferences.save_look_range(180)
        self.assertEqual(settings.values["pets/test-pet/lookRange"], 180)


if __name__ == "__main__":
    unittest.main()
