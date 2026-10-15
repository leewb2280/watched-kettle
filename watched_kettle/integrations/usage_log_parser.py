"""Pure local rollout usage extraction, independent of Qt and SQLite."""

import hashlib
import json
from datetime import datetime, timezone
from watched_kettle.usage.device import nonnegative


class UsageLogParser:
    def __init__(self, now, session_id, recorded_at):
        self._now = now
        self.session_id = session_id
        self.recorded_at = recorded_at
        self._usage_metadata = {}
        self._usage_totals = {}
        self.usage_regression_count = 0

    def extract(self, path, record, line_offset):
        if not isinstance(record, dict):
            return ()
        payload = record.get("payload")
        if record.get("type") == "session_meta" and isinstance(payload, dict):
            owner_id = str(payload.get("id") or self.session_id(path))[:160]
            session_id = str(payload.get("session_id") or owner_id)[:160]
            self._usage_metadata[path] = {
                "owner_id": owner_id,
                "file_id": self.session_id(path),
                "inherited": bool(payload.get("history_base"))
                or owner_id != session_id,
            }
            return ()
        if (
            record.get("type") != "event_msg"
            or not isinstance(payload, dict)
            or payload.get("type") != "token_count"
        ):
            return ()
        recorded_at = self.recorded_at(record)
        if recorded_at is None:
            return ()
        info = payload.get("info")
        total_usage = info.get("total_token_usage") if isinstance(info, dict) else None
        last_usage = info.get("last_token_usage") if isinstance(info, dict) else None
        total = nonnegative(
            total_usage.get("total_tokens") if isinstance(total_usage, dict) else None
        )
        if total is None:
            return ()
        metadata = self._usage_metadata.get(path) or {
            "owner_id": self.session_id(path),
            "file_id": self.session_id(path),
            "inherited": True,
        }
        owner_id = metadata["owner_id"]
        previous = self._usage_totals.get(owner_id)
        if previous is None:
            last = nonnegative(
                last_usage.get("total_tokens") if isinstance(last_usage, dict) else None
            )
            delta = last if metadata["inherited"] else total
        elif total >= previous:
            delta = total - previous
        else:
            delta = 0
            if total != 0:
                self.usage_regression_count += 1
        self._usage_totals[owner_id] = (
            max(previous, total) if previous is not None else total
        )

        current = self._now()
        if current.tzinfo is None:
            current = current.replace(tzinfo=timezone.utc)
        if recorded_at.astimezone(current.tzinfo).date() != current.date():
            return ()
        record_key = hashlib.sha256(
            json.dumps(
                [owner_id, recorded_at.isoformat(), payload],
                sort_keys=True,
                separators=(",", ":"),
            ).encode()
        ).hexdigest()
        extracted = []
        if delta and delta > 0:
            extracted.append(
                {
                    "kind": "token",
                    "event_key": f"{record_key}|token",
                    "session_id": owner_id,
                    "occurred_at": recorded_at.isoformat(),
                    "delta_tokens": int(delta),
                }
            )
        rate_limits = payload.get("rate_limits")
        if isinstance(rate_limits, dict):
            limit_id = str(rate_limits.get("limit_id") or "codex")[:160]
            for slot in ("primary", "secondary"):
                window = rate_limits.get(slot)
                if not isinstance(window, dict):
                    continue
                used = nonnegative(window.get("used_percent"), float)
                if used is None:
                    continue
                duration = nonnegative(window.get("window_minutes"))
                resets_epoch = nonnegative(window.get("resets_at"))
                try:
                    resets_at = (
                        datetime.fromtimestamp(resets_epoch, timezone.utc).isoformat()
                        if resets_epoch is not None
                        else None
                    )
                except (ValueError, OverflowError, OSError):
                    resets_at = None
                extracted.append(
                    {
                        "kind": "quota",
                        "event_key": f"{record_key}|quota|{limit_id}|{slot}",
                        "limit_id": limit_id,
                        "slot": slot,
                        "occurred_at": recorded_at.isoformat(),
                        "used_percent": float(used),
                        "window_duration_mins": duration,
                        "resets_at": resets_at,
                    }
                )
        return tuple(extracted)
