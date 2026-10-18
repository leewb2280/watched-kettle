"""Device observations: no account key in the schema or public methods."""

from __future__ import annotations

from watched_kettle.localization import t

from datetime import datetime, timedelta, timezone
from watched_kettle.usage.device import DeviceTokenEvent, DeviceQuotaSample


def migrate_device_storage(connection):
    for statement in (
        "CREATE TABLE device_token_events(event_hash TEXT PRIMARY KEY, session_hash TEXT NOT NULL, occurred_at_utc TEXT NOT NULL, delta_tokens INTEGER NOT NULL CHECK(delta_tokens>0))",
        "CREATE TABLE device_quota_samples(event_hash TEXT PRIMARY KEY, limit_id TEXT NOT NULL, window_slot TEXT NOT NULL, observed_at_utc TEXT NOT NULL, used_percent REAL NOT NULL, window_duration_mins INTEGER, resets_at_utc TEXT)",
        "CREATE INDEX idx_device_token_time ON device_token_events(occurred_at_utc)",
        "CREATE INDEX idx_device_quota_time ON device_quota_samples(observed_at_utc)",
        "CREATE TABLE device_import_state(id INTEGER PRIMARY KEY CHECK(id=1), cleared_before_utc TEXT)",
        "INSERT INTO device_import_state SELECT 1, MAX(cleared_before_utc) FROM usage_import_state",
        "ALTER TABLE usage_quota_samples ADD COLUMN source TEXT NOT NULL DEFAULT 'legacy_unverified'",
    ):
        connection.execute(statement)


class DeviceRepository:
    def __init__(self, database, now=None):
        self.database = database
        self._now = now or (lambda: datetime.now(timezone.utc))

    @property
    def connection(self):
        return self.database.require_connection()

    def append(self, tokens=(), quotas=()):
        watermark = self.watermark()
        with self.connection:
            self.connection.executemany(
                "INSERT OR IGNORE INTO device_token_events VALUES (?,?,?,?)",
                [
                    (
                        x.event_hash,
                        x.session_hash,
                        x.occurred_at.isoformat(),
                        x.delta_tokens,
                    )
                    for x in tokens
                    if isinstance(x, DeviceTokenEvent)
                    and x.delta_tokens > 0
                    and (watermark is None or x.occurred_at > watermark)
                ],
            )
            self.connection.executemany(
                "INSERT OR IGNORE INTO device_quota_samples VALUES (?,?,?,?,?,?,?)",
                [
                    (
                        x.event_hash,
                        x.limit_id,
                        x.window_slot,
                        x.observed_at.isoformat(),
                        x.used_percent,
                        x.window_duration_mins,
                        x.resets_at.isoformat() if x.resets_at else None,
                    )
                    for x in quotas
                    if isinstance(x, DeviceQuotaSample)
                    and (watermark is None or x.observed_at > watermark)
                ],
            )
        self.maintenance()

    def tokens(self):
        cutoff = (self._now() - timedelta(days=8)).isoformat()
        return tuple(
            DeviceTokenEvent(r[0], r[1], datetime.fromisoformat(r[2]), r[3])
            for r in self.connection.execute(
                "SELECT * FROM device_token_events WHERE occurred_at_utc>=? ORDER BY occurred_at_utc",
                (cutoff,),
            )
        )

    def quotas(self):
        cutoff = (self._now() - timedelta(days=8)).isoformat()
        return tuple(
            DeviceQuotaSample(
                r[0],
                r[1],
                r[2],
                datetime.fromisoformat(r[3]),
                r[4],
                r[5],
                datetime.fromisoformat(r[6]) if r[6] else None,
            )
            for r in self.connection.execute(
                "SELECT * FROM device_quota_samples WHERE observed_at_utc>=? ORDER BY observed_at_utc",
                (cutoff,),
            )
        )

    def legacy(self):
        # v4 events cannot prove account ownership or measurement quality.
        return tuple(
            (r[0], r[1], t("message.0355"))
            for r in self.connection.execute(
                "SELECT occurred_at_utc, CAST(delta_tokens AS TEXT) || ' tokens' FROM usage_local_token_events UNION ALL SELECT observed_at_utc, CAST(used_percent AS TEXT) || '%' FROM usage_quota_samples WHERE source='legacy_unverified' ORDER BY 1 DESC LIMIT 500"
            )
        )

    def watermark(self):
        row = self.connection.execute(
            "SELECT cleared_before_utc FROM device_import_state WHERE id=1"
        ).fetchone()
        return datetime.fromisoformat(row[0]) if row and row[0] else None

    def clear(self, when=None):
        when = max(
            when or self._now(),
            self.watermark() or datetime.min.replace(tzinfo=timezone.utc),
        )
        with self.connection:
            self.connection.execute("DELETE FROM device_token_events")
            self.connection.execute("DELETE FROM device_quota_samples")
            self.connection.execute("DELETE FROM usage_local_token_events")
            self.connection.execute(
                "DELETE FROM usage_quota_samples WHERE source='legacy_unverified'"
            )
            self.connection.execute(
                "UPDATE device_import_state SET cleared_before_utc=? WHERE id=1",
                (when.isoformat(),),
            )
        return True

    def maintenance(self):
        cutoff = (self._now() - timedelta(days=8)).isoformat()
        with self.connection:
            for table, column in (
                ("device_token_events", "occurred_at_utc"),
                ("device_quota_samples", "observed_at_utc"),
            ):
                self.connection.execute(
                    f"DELETE FROM {table} WHERE {column}<?", (cutoff,)
                )
                self.connection.execute(
                    f"DELETE FROM {table} WHERE event_hash NOT IN (SELECT event_hash FROM {table} ORDER BY {column} DESC LIMIT 20000)"
                )


class VolatileDeviceRepository:
    def __init__(self, now=None):
        self._now = now or (lambda: datetime.now(timezone.utc))
        self._tokens = {}
        self._quotas = {}
        self._watermark = None

    def append(self, tokens=(), quotas=()):
        for collection, items, field in (
            (self._tokens, tokens, "occurred_at"),
            (self._quotas, quotas, "observed_at"),
        ):
            for item in items:
                if self._watermark is None or getattr(item, field) > self._watermark:
                    collection.setdefault(item.event_hash, item)
            retained = sorted(
                (
                    x
                    for x in collection.values()
                    if getattr(x, field) >= self._now() - timedelta(days=8)
                ),
                key=lambda x: getattr(x, field),
            )[-20000:]
            collection.clear()
            collection.update((x.event_hash, x) for x in retained)

    def tokens(self):
        return tuple(
            sorted(
                (
                    x
                    for x in self._tokens.values()
                    if x.occurred_at >= self._now() - timedelta(days=8)
                ),
                key=lambda x: x.occurred_at,
            )
        )

    def quotas(self):
        return tuple(
            sorted(
                (
                    x
                    for x in self._quotas.values()
                    if x.observed_at >= self._now() - timedelta(days=8)
                ),
                key=lambda x: x.observed_at,
            )
        )

    def legacy(self):
        return ()

    def watermark(self):
        return self._watermark

    def clear(self, when=None):
        self._tokens.clear()
        self._quotas.clear()
        self._watermark = max(
            when or self._now(),
            self._watermark or datetime.min.replace(tzinfo=timezone.utc),
        )
        return True
