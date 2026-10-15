def __getattr__(name):
    if name == "SettingsViewModel":
        from importlib import import_module

        return import_module(
            "watched_kettle.features.settings.viewmodel"
        ).SettingsViewModel
    raise AttributeError(name)


__all__ = ["SettingsViewModel"]
