"""Record locale tags with compatible Babel and pinned Electron plural behavior."""

import argparse
import json
import os
from pathlib import Path
import subprocess

import babel
from babel import Locale, localedata

ROOT = Path(__file__).resolve().parents[1]
TARGET = ROOT / "watched_kettle/localization/resources/locales.json"
# Exercise small integers, CLDR modulo/million boundaries, fractions and negatives.
# These are a compatibility regression corpus, not a proof over all real numbers.
PLURAL_PROBES = tuple(range(201)) + (
    999,
    1000,
    1001,
    10000,
    10001,
    100000,
    100001,
    999999,
    1000000,
    1000001,
    2000000,
    10**12,
    10**12 + 1,
    0.000001,
    0.0001,
    0.001,
    0.01,
    0.1,
    0.5,
    1.0001,
    1.1,
    1.2,
    1.5,
    2.1,
    2.5,
    3.5,
    10.1,
    11.1,
    100.1,
    1000000.1,
    -1,
    -2,
    -5,
    -21,
    -1.0001,
    -0.000001,
)


def payload():
    candidates = []
    for name in sorted(localedata.locale_identifiers()):
        locale = Locale.parse(name)
        if locale.character_order == "left-to-right" and locale.language != "root":
            candidates.append(
                {
                    "tag": str(locale).replace("_", "-"),
                    "forms": [
                        str(locale.plural_form(count)) for count in PLURAL_PROBES
                    ],
                }
            )
    candidates.sort(key=lambda item: item["tag"])
    electron = ROOT / "settings-ui/node_modules/electron/dist/electron.exe"
    script = """
const fs = require("node:fs");
const {counts, candidates} = JSON.parse(fs.readFileSync(0, "utf8"));
const apis = [Intl.PluralRules, Intl.NumberFormat, Intl.DateTimeFormat];
const locales = [], excludedPluralLocales = [];
for (const {tag, forms} of candidates) {
  let supported;
  try { supported = apis.every(api => api.supportedLocalesOf(tag).length === 1); }
  catch { supported = false; }
  if (!supported) continue;
  const rules = new Intl.PluralRules(tag, {maximumFractionDigits: 20});
  if (counts.every((count, index) => rules.select(count) === forms[index]))
    locales.push(tag);
  else excludedPluralLocales.push(tag);
}
console.log(JSON.stringify({
  electron: process.versions.electron, locales, excludedPluralLocales
}));
"""
    result = subprocess.run(
        [str(electron), "-e", script],
        input=json.dumps({"counts": PLURAL_PROBES, "candidates": candidates}),
        text=True,
        encoding="utf-8",
        capture_output=True,
        check=True,
        env={**os.environ, "ELECTRON_RUN_AS_NODE": "1"},
        creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0),
    )
    actual = json.loads(result.stdout)
    return {
        "babel": babel.__version__,
        "pluralProbeCounts": list(PLURAL_PROBES),
        **actual,
    }


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--check", action="store_true")
    args = parser.parse_args()
    encoded = json.dumps(payload(), ensure_ascii=False, indent=2) + "\n"
    if args.check:
        if TARGET.read_text(encoding="utf-8") != encoded:
            raise SystemExit(
                "Locale compatibility list is stale. Run python -m scripts.generate_language_locales."
            )
        print("Babel / Electron locale and plural compatibility list is current.")
    else:
        TARGET.write_text(encoded, encoding="utf-8")
        print(TARGET)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
