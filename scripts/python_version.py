"""Check the interpreter used for development checks and Windows builds."""

from __future__ import annotations

import platform
import struct
import sys
import sysconfig


def runtime_errors(version, implementation, bits, free_threaded) -> list[str]:
    errors = []
    if tuple(version[:2]) != (3, 14):
        errors.append("Python 3.14.x is required")
    if implementation != "CPython" or bits != 64 or free_threaded:
        errors.append("Use standard CPython x64 (not a free-threaded build)")
    return errors


def main() -> int:
    errors = runtime_errors(
        sys.version_info,
        platform.python_implementation(),
        struct.calcsize("P") * 8,
        bool(sysconfig.get_config_var("Py_GIL_DISABLED")),
    )
    if errors:
        print(
            f"Unsupported interpreter: {sys.version.split()[0]} ({sys.executable})",
            file=sys.stderr,
        )
        for error in errors:
            print(error, file=sys.stderr)
        print(
            "Create the project environment with: py -3.14 -m venv .venv",
            file=sys.stderr,
        )
        return 1
    print(f"Python runtime: {sys.version.split()[0]} (CPython x64)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
