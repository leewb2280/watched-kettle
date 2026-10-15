"""Bounded JSON values and explicit validation at the settings process boundary."""

from __future__ import annotations

from dataclasses import fields, is_dataclass
from datetime import date, datetime
from enum import Enum
import math

PROTOCOL_VERSION = 1
MAX_FRAME_BYTES = 4 * 1024 * 1024


class CommandError(Exception):
    def __init__(self, code, message):
        super().__init__(message)
        self.code = code


def require(condition, message="설정 값이 올바르지 않습니다.", code="invalid_argument"):
    if not condition:
        raise CommandError(code, message)


def text(value, maximum=300):
    require(isinstance(value, str) and len(value) <= maximum)
    return value


def integer(value, low, high):
    require(type(value) is int and low <= value <= high)
    return value


def boolean(value):
    require(type(value) is bool)
    return value


def choice(value, options):
    require(value in options)
    return value


def wire(value, depth=0):
    """Serialize value models only, never QObject, arbitrary objects or paths."""
    require(depth < 16, "응답 구조가 너무 깊습니다.", "response_limit")
    if value is None or isinstance(value, (str, bool, int)):
        return value
    if isinstance(value, float):
        return value if math.isfinite(value) else None
    if isinstance(value, Enum):
        return wire(value.value, depth + 1)
    if isinstance(value, (datetime, date)):
        return value.isoformat()
    if is_dataclass(value) and not isinstance(value, type):
        return {
            field.name: wire(getattr(value, field.name), depth + 1)
            for field in fields(value)
            if field.name != "unknown"
        }
    if isinstance(value, dict):
        require(len(value) <= 4096, code="response_limit")
        return {str(key): wire(item, depth + 1) for key, item in value.items()}
    if isinstance(value, (list, tuple, set, frozenset)):
        require(len(value) <= 4096, code="response_limit")
        return [wire(item, depth + 1) for item in value]
    raise CommandError("invalid_response", "표시할 수 없는 응답 형식입니다.")
