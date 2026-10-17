"""Enforce combined and pure branch coverage, with critical-module floors."""

import argparse
import json
from pathlib import Path

CRITICAL = (
    "watched_kettle/usage/account_session.py",
    "watched_kettle/usage/activity.py",
    "watched_kettle/usage/device.py",
    "watched_kettle/usage/turn_measurement.py",
    "watched_kettle/integrations/log_tail.py",
    "watched_kettle/integrations/log_lifecycle.py",
    "watched_kettle/integrations/usage_log_parser.py",
    "watched_kettle/process_metrics.py",
)


def evaluate(report):
    totals = report["totals"]
    branch = 100 * totals["covered_branches"] / max(1, totals["num_branches"])
    issues = []
    if totals["percent_covered"] < 80:
        issues.append("combined_coverage_below_80")
    if branch < 69.1:
        issues.append("pure_branch_coverage_below_69.1")
    files = {k.replace(chr(92), "/"): v for k, v in report["files"].items()}
    boundaries = {}
    for path in CRITICAL:
        if path not in files:
            issues.append("missing_module:" + path)
            continue
        summary = files[path]["summary"]
        count = summary["num_branches"]
        percent = (
            100 * summary["covered_branches"] / count
            if count
            else summary["percent_covered"]
        )
        boundaries[path] = percent
        if percent < 80:
            issues.append("critical_coverage_below_80:" + path)
    return {
        "ok": not issues,
        "combined_percent": totals["percent_covered"],
        "pure_branch_percent": branch,
        "critical_percent": boundaries,
        "issues": issues,
    }


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("report", type=Path)
    args = parser.parse_args()
    result = evaluate(json.loads(args.report.read_text(encoding="utf-8")))
    print(json.dumps(result, indent=2))
    return 0 if result["ok"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
