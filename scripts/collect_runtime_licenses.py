"""Copy installed distribution notices into the local Windows bundle."""

from __future__ import annotations

import argparse
import importlib.metadata
import json
from pathlib import Path
import sys


DISTRIBUTIONS = (
    "Pillow",
    "Babel",
    "PySide6",
    "PySide6_Essentials",
    "PySide6_Addons",
    "shiboken6",
    "PyInstaller",
)


def collect(destination: Path) -> dict:
    destination.mkdir(parents=True, exist_ok=True)
    inventory = []
    for name in DISTRIBUTIONS:
        distribution = importlib.metadata.distribution(name)
        files = []
        for relative in distribution.files or ():
            if not any(
                part.casefold().startswith(
                    ("license", "copying", "copyright", "notice")
                )
                for part in relative.parts
            ):
                continue
            source = Path(distribution.locate_file(relative))
            if not source.is_file():
                continue
            target = destination / name / Path(*relative.parts)
            if not target.resolve().is_relative_to(destination.resolve()):
                raise ValueError("Unexpected distribution license path")
            target.parent.mkdir(parents=True, exist_ok=True)
            target.write_bytes(source.read_bytes())
            files.append(target.relative_to(destination).as_posix())
        if not files:
            raise ValueError(f"No installed license text found for {name}")
        inventory.append(
            {"name": name, "version": distribution.version, "files": files}
        )
    python_license = Path(sys.base_prefix) / "LICENSE.txt"
    if not python_license.is_file():
        raise ValueError("Python runtime license missing")
    (destination / "PYTHON_LICENSE.txt").write_bytes(python_license.read_bytes())
    report = {"python": sys.version.split()[0], "distributions": inventory}
    (destination / "DEPENDENCIES.json").write_text(
        json.dumps(report, indent=2) + "\n", encoding="utf-8"
    )
    return report


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("destination", type=Path)
    collect(parser.parse_args().destination)
