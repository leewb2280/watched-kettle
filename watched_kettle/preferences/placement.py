"""placement preferences; existing QSettings keys are preserved."""

from watched_kettle.pet.placement import SavedWindowPlacement


class PlacementPreferences:
    def __init__(self, settings, placement=None):
        self.settings = settings
        self.placement = placement

    def load_auto_movement_screen(self):
        mode = str(
            self.settings.value(
                "autoMovementScreenMode",
                "current",
            )
            or "current"
        )
        if mode not in {"current", "primary", "specific"}:
            mode = "current"

        name = str(
            self.settings.value(
                "autoMovementScreenName",
                "",
            )
            or ""
        )
        if mode != "specific" or not name:
            name = ""
            if mode == "specific":
                mode = "current"
        return mode, name

    def save_auto_movement_screen(self, mode, name=""):
        mode = str(mode)
        name = str(name or "")
        if mode not in {"current", "primary", "specific"}:
            mode = "current"
        if mode != "specific" or not name:
            name = ""
            if mode == "specific":
                mode = "current"

        self.settings.setValue("autoMovementScreenMode", mode)
        self.settings.setValue("autoMovementScreenName", name)

    def load_window_placement(self):
        return self._load_saved_window_placement("windowPlacement")

    def _load_saved_window_placement(self, prefix):
        values = {
            "screen_name": self.settings.value(f"{prefix}/screenName", ""),
            "x": self.settings.value(f"{prefix}/x"),
            "y": self.settings.value(f"{prefix}/y"),
            "work_x": self.settings.value(f"{prefix}/workX"),
            "work_y": self.settings.value(f"{prefix}/workY"),
            "work_width": self.settings.value(f"{prefix}/workWidth"),
            "work_height": self.settings.value(f"{prefix}/workHeight"),
            "relative_x": self.settings.value(f"{prefix}/relativeX"),
            "relative_y": self.settings.value(f"{prefix}/relativeY"),
        }
        if any(value is None for key, value in values.items() if key != "screen_name"):
            return None
        try:
            placement = SavedWindowPlacement(
                screen_name=str(values["screen_name"] or ""),
                x=int(values["x"]),
                y=int(values["y"]),
                work_x=int(values["work_x"]),
                work_y=int(values["work_y"]),
                work_width=int(values["work_width"]),
                work_height=int(values["work_height"]),
                relative_x=float(values["relative_x"]),
                relative_y=float(values["relative_y"]),
            )
        except (TypeError, ValueError):
            return None
        if placement.work_width <= 0 or placement.work_height <= 0:
            return None
        if not 0.0 <= placement.relative_x <= 1.0:
            return None
        if not 0.0 <= placement.relative_y <= 1.0:
            return None
        return placement

    def save_window_placement(self, placement):
        self._save_saved_window_placement("windowPlacement", placement)

    def _save_saved_window_placement(self, prefix, placement):
        values = {
            "screenName": placement.screen_name,
            "x": placement.x,
            "y": placement.y,
            "workX": placement.work_x,
            "workY": placement.work_y,
            "workWidth": placement.work_width,
            "workHeight": placement.work_height,
            "relativeX": placement.relative_x,
            "relativeY": placement.relative_y,
        }
        for key, value in values.items():
            self.settings.setValue(f"{prefix}/{key}", value)
