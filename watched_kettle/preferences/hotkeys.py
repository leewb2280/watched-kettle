"""The saved spelling of a global shortcut, independent of Qt and Windows.

Shortcuts are written ``Ctrl+Alt+Shift+K``: at least Ctrl or Alt, then one of
A-Z, 0-9 or F1-F24. The Win key is not offered since Windows reserves most of
its combinations. Values are the Win32 ``RegisterHotKey`` modifier flags and
virtual-key codes.
"""

from __future__ import annotations

MOD_ALT = 0x0001
MOD_CONTROL = 0x0002
MOD_SHIFT = 0x0004
MODIFIERS = (("Ctrl", MOD_CONTROL), ("Alt", MOD_ALT), ("Shift", MOD_SHIFT))
KEYS = {
    **{chr(code): code for code in range(ord("A"), ord("Z") + 1)},
    **{chr(code): code for code in range(ord("0"), ord("9") + 1)},
    **{f"F{number}": 0x6F + number for number in range(1, 25)},
}


def parse_hotkey(text):
    """``(modifiers, virtual key)`` for a valid shortcut, otherwise None."""
    if not isinstance(text, str) or len(text) > 32:
        return None
    *names, key = text.split("+")
    key = key.strip().upper()
    if key not in KEYS:
        return None
    modifiers = 0
    known = {name.casefold(): flag for name, flag in MODIFIERS}
    for name in names:
        flag = known.get(name.strip().casefold())
        if flag is None or modifiers & flag:
            return None
        modifiers |= flag
    if not modifiers & (MOD_CONTROL | MOD_ALT):
        return None
    return modifiers, KEYS[key]


def format_hotkey(text):
    """The canonical spelling of a valid shortcut, or "" for anything else."""
    parsed = parse_hotkey(text)
    if parsed is None:
        return ""
    modifiers, virtual_key = parsed
    key = next(name for name, code in KEYS.items() if code == virtual_key)
    return "+".join([name for name, flag in MODIFIERS if modifiers & flag] + [key])
