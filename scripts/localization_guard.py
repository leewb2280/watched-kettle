"""Keep Korean source text in the catalog and translations in step with it.

``check`` fails when code gains a hard-coded Korean literal outside the
allowlist, names a message key the catalog lacks, or when a catalog message
changes without a revision bump. ``lock`` records the reviewed source
fingerprints after such a change.
"""

from __future__ import annotations

import argparse
import ast
import hashlib
import json
from pathlib import Path
import re
import sys

ROOT = Path(__file__).resolve().parents[1]
SOURCE_ROOT = ROOT / "watched_kettle"
LOCK_PATH = ROOT / "scripts/localization_source.lock.json"
ALLOWLIST_PATH = ROOT / "scripts/localization_literals.json"
RESOURCE_PACKS = (
    SOURCE_ROOT / "localization/resources/catalog.json",
    SOURCE_ROOT / "localization/resources/en/messages.json",
)
# Same Hangul syllable range as the official English completeness test.
HANGUL = re.compile("[가-힣]")
_QML_COMMENT = re.compile(r"//[^\n]*|/\*.*?\*/", re.S)
_QML_STRING = re.compile(
    r"\"(?:\\.|[^\"\\\n])*\"|'(?:\\.|[^'\\\n])*'|`(?:\\.|[^`\\])*`"
)
# Fields that change what a translator must say; context/domain are notes.
_FINGERPRINT_FIELDS = ("value", "variables", "plural")
# Literal message references. A missing key renders as its own ID on screen.
_KEY = r"[a-z_]+(?:\.[a-z0-9_]+)+"
_KEY_REFERENCE = re.compile(
    rf"\b(?:t|MessageId|parts)\(\s*[\"']({_KEY})[\"']"
    rf"|<LocalizedText\s+id=\{{?\"({_KEY})\""
)
_KEY_SOURCES = (
    "watched_kettle/**/*.py",
    "watched_kettle/**/*.qml",
    "watched_kettle/**/*.js",
    "settings-ui/src/**/*.ts",
    "settings-ui/src/**/*.tsx",
    "settings-ui/electron/*.cjs",
)


def _docstrings(tree):
    nodes = (ast.Module, ast.ClassDef, ast.FunctionDef, ast.AsyncFunctionDef)
    found = set()
    for node in ast.walk(tree):
        if isinstance(node, nodes) and node.body:
            first = node.body[0]
            if (
                isinstance(first, ast.Expr)
                and isinstance(first.value, ast.Constant)
                and isinstance(first.value.value, str)
            ):
                found.add(id(first.value))
    return found


def python_literals(text):
    """Line numbers of non-docstring string constants containing Hangul."""
    tree = ast.parse(text)
    docstrings = _docstrings(tree)
    return sorted(
        node.lineno
        for node in ast.walk(tree)
        if isinstance(node, ast.Constant)
        and isinstance(node.value, str)
        and id(node) not in docstrings
        and HANGUL.search(node.value)
    )


def qml_literals(text):
    """Line numbers of quoted QML/JS strings containing Hangul, comments excluded."""

    def blank(match):
        # Keep newlines so reported line numbers still match the file.
        return re.sub(r"[^\n]", " ", match.group())

    code = _QML_COMMENT.sub(blank, text)
    return [
        code.count("\n", 0, match.start()) + 1
        for match in _QML_STRING.finditer(code)
        if HANGUL.search(match.group())
    ]


def scan_literals(root=SOURCE_ROOT):
    """Map each repository-relative source path to its Hangul literal lines."""
    found = {}
    resources = root / "localization" / "resources"
    for path in sorted(root.rglob("*")):
        if resources in path.parents or path.suffix not in {".py", ".qml", ".js"}:
            continue
        text = path.read_text(encoding="utf-8-sig")
        lines = python_literals(text) if path.suffix == ".py" else qml_literals(text)
        if lines:
            found[path.relative_to(root.parent).as_posix()] = lines
    return found


def literal_problems(found, allowlist):
    problems = []
    for path in sorted(set(found) | set(allowlist)):
        lines = found.get(path, [])
        allowed = allowlist.get(path, {})
        expected = allowed.get("count", 0)
        if allowed and not str(allowed.get("reason", "")).strip():
            problems.append(f"{path}: allowlist entry needs a reason")
        if len(lines) > expected:
            where = ", ".join(map(str, lines))
            problems.append(
                f"{path}: {len(lines)} Korean literal(s) at line {where}, "
                f"{expected} allowed. Move user-visible text to catalog.json and "
                "t(), or record a reason in scripts/localization_literals.json"
            )
        elif len(lines) < expected:
            problems.append(
                f"{path}: {len(lines)} Korean literal(s), allowlist still says "
                f"{expected}. Lower the count in scripts/localization_literals.json"
            )
    return problems


def scan_keys(root=ROOT):
    """Map each literal message key in UI code to the places that name it."""
    found = {}
    for pattern in _KEY_SOURCES:
        for path in sorted(root.glob(pattern)):
            text = path.read_text(encoding="utf-8-sig")
            for match in _KEY_REFERENCE.finditer(text):
                line = text.count("\n", 0, match.start()) + 1
                found.setdefault(match.group(1) or match.group(2), []).append(
                    f"{path.relative_to(root).as_posix()}:{line}"
                )
    return found


def key_problems(found, messages):
    return [
        f"{key}: not in catalog.json (used at {', '.join(places)}). Add the "
        "message and its English translation, or fix the key"
        for key, places in sorted(found.items())
        if key not in messages
    ]


def control_problems(name, payload):
    """Flag control characters other than newline in any string of a pack.

    A Windows path typed through a shell lost its backslashes this way twice:
    ``\\a`` in ``application`` became BEL inside translator notes.
    """
    problems = []

    def walk(value, where):
        if isinstance(value, str):
            bad = sorted(
                {f"U+{ord(c):04X}" for c in value if ord(c) < 32 and c != "\n"}
            )
            if bad:
                problems.append(
                    f"{name}: {where} has control characters {', '.join(bad)}"
                )
        elif isinstance(value, dict):
            for key, item in value.items():
                walk(item, f"{where}.{key}" if where else str(key))
        elif isinstance(value, list):
            for index, item in enumerate(value):
                walk(item, f"{where}[{index}]")

    walk(payload, "")
    return problems


def fingerprint(entry):
    payload = {field: entry.get(field) for field in _FINGERPRINT_FIELDS}
    raw = json.dumps(payload, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
    return hashlib.sha256(raw.encode("utf-8")).hexdigest()


def lock_changes(messages, lock):
    """Classify catalog differences against the recorded source lock."""
    changes = {"added": [], "removed": [], "bumped": [], "reworded": [], "lowered": []}
    for key in sorted(set(messages) | set(lock)):
        entry, locked = messages.get(key), lock.get(key)
        if locked is None:
            changes["added"].append(key)
        elif entry is None:
            changes["removed"].append(key)
        elif entry["revision"] < locked["revision"]:
            changes["lowered"].append(key)
        elif entry["revision"] > locked["revision"]:
            changes["bumped"].append(key)
        elif fingerprint(entry) != locked["sha256"]:
            changes["reworded"].append(key)
    return changes


def lock_problems(messages, lock):
    changes = lock_changes(messages, lock)
    problems = [
        f"{key}: source text changed without a revision bump. If the meaning "
        "changed, raise its revision and update en/messages.json; if only the "
        f"wording changed, run: python -m scripts.localization_guard lock "
        f"--wording-only {key}"
        for key in changes["reworded"]
    ]
    problems += [f"{key}: revision went backwards" for key in changes["lowered"]]
    pending = changes["added"] + changes["removed"] + changes["bumped"]
    if pending:
        problems.append(
            "catalog keys or revisions changed since the source lock: "
            + ", ".join(pending)
            + ". Run: python -m scripts.localization_guard lock"
        )
    return problems


def updated_lock(messages, lock, wording_only=()):
    """Return the new lock, or raise ValueError for unreviewed rewording."""
    changes = lock_changes(messages, lock)
    unknown = sorted(set(wording_only) - set(changes["reworded"]))
    if unknown:
        raise ValueError("not a same-revision wording change: " + ", ".join(unknown))
    blocked = sorted(set(changes["reworded"]) - set(wording_only))
    if blocked or changes["lowered"]:
        raise ValueError(
            "refusing to lock unreviewed source changes: "
            + ", ".join(blocked + changes["lowered"])
            + ". Raise the revision, or pass --wording-only KEY for wording fixes"
        )
    return {
        key: {"revision": entry["revision"], "sha256": fingerprint(entry)}
        for key, entry in sorted(messages.items())
    }


def _read(path):
    return json.loads(path.read_text(encoding="utf-8")) if path.exists() else {}


def _messages():
    from watched_kettle.localization.catalog import source_catalog

    return source_catalog()["messages"]


def check():
    # settings-ui entries belong to settings-ui/scripts/localization-literals.test.cjs.
    allowlist = {
        path: entry
        for path, entry in _read(ALLOWLIST_PATH).get("korean", {}).items()
        if path.startswith(f"{SOURCE_ROOT.name}/")
    }
    messages = _messages()
    return (
        literal_problems(scan_literals(), allowlist)
        + key_problems(scan_keys(), messages)
        + lock_problems(messages, _read(LOCK_PATH))
        + [
            problem
            for path in RESOURCE_PACKS
            for problem in control_problems(
                path.relative_to(ROOT).as_posix(), _read(path)
            )
        ]
    )


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    sub = parser.add_subparsers(dest="command", required=True)
    sub.add_parser("check")
    lock = sub.add_parser("lock")
    lock.add_argument("--wording-only", nargs="+", default=[], metavar="KEY")
    args = parser.parse_args(argv)
    if args.command == "lock":
        try:
            value = updated_lock(_messages(), _read(LOCK_PATH), args.wording_only)
        except ValueError as error:
            print(f"ERROR: {error}", file=sys.stderr)
            return 1
        # One key per line keeps lock diffs reviewable next to catalog.json.
        lines = [
            f"  {json.dumps(key, ensure_ascii=False)}: "
            f"{json.dumps(entry, separators=(', ', ': '))}"
            for key, entry in value.items()
        ]
        LOCK_PATH.write_text(
            "{\n" + ",\n".join(lines) + "\n}\n", encoding="utf-8", newline="\n"
        )
        print(f"Locked {len(value)} source messages.")
        return 0
    problems = check()
    for problem in problems:
        print(f"ERROR: {problem}", file=sys.stderr)
    if problems:
        return 1
    print("Localization guards passed.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
