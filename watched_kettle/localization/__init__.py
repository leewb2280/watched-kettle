"""Display-only localization. No Qt, application, feature or storage dependencies."""

from .catalog import Translator, get_translator, set_translator, t

__all__ = ["Translator", "get_translator", "set_translator", "t"]
