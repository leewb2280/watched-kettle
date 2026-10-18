"""Late-bound display labels in module-level lookup tables; no import-time I/O."""

from collections.abc import Mapping, Sequence

from .catalog import t


class MessageId:
    def __init__(self, key):
        self.key = key


def resolve(value):
    if isinstance(value, MessageId):
        return t(value.key)
    if isinstance(value, dict):
        return {key: resolve(item) for key, item in value.items()}
    if isinstance(value, tuple):
        return tuple(resolve(item) for item in value)
    if isinstance(value, list):
        return [resolve(item) for item in value]
    return value


class MessageMapping(Mapping):
    def __init__(self, values):
        self._values = values

    def __getitem__(self, key):
        return resolve(self._values[key])

    def __iter__(self):
        return iter(self._values)

    def __len__(self):
        return len(self._values)


class MessageSequence(Sequence):
    def __init__(self, values):
        self._values = values

    def __getitem__(self, key):
        return resolve(self._values[key])

    def __len__(self):
        return len(self._values)
