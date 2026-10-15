import json
import unittest
from datetime import datetime, timezone
from pathlib import Path
from tempfile import TemporaryDirectory

from watched_kettle.storage.legacy_usage import (
    LegacyUsageImportError,
    read_legacy_usage,
)
from watched_kettle.usage.identifiers import hash_identifier
from watched_kettle.usage.models import TaskUsageRecord
from watched_kettle.usage.serialization import decode_usage_record, encode_usage_record


class UsageRepositoryTests(unittest.TestCase):
    def make_record(self):
        return TaskUsageRecord(
            datetime(2026, 9, 4, tzinfo=timezone.utc),
            "account",
            "thread",
            "done",
            total_tokens=20,
        )

    def test_codec_contains_only_declared_numeric_usage_fields(self):
        payload = encode_usage_record(self.make_record())
        self.assertEqual(payload["account_hash"], "account")
        self.assertNotIn("email", payload)
        self.assertEqual(decode_usage_record(payload), self.make_record())

    def test_legacy_import_validates_every_record_before_returning(self):
        with TemporaryDirectory() as directory:
            path = Path(directory) / "usage.json"
            path.write_text(
                json.dumps(
                    {
                        "schemaVersion": 1,
                        "records": [encode_usage_record(self.make_record())],
                    }
                ),
                encoding="utf-8",
            )
            self.assertEqual(read_legacy_usage(path), (self.make_record(),))
            payload = encode_usage_record(self.make_record())
            path.write_text(
                json.dumps(
                    {
                        "schemaVersion": 1,
                        "records": [{**payload, "email": "private@example.com"}],
                    }
                ),
                encoding="utf-8",
            )
            with self.assertRaises(LegacyUsageImportError):
                read_legacy_usage(path)

    def test_identifier_hash_is_stable_and_does_not_expose_input(self):
        value = hash_identifier("account@example.com")
        self.assertEqual(value, hash_identifier("account@example.com"))
        self.assertNotIn("account", value)
        self.assertEqual(len(value), 24)


if __name__ == "__main__":
    unittest.main()
