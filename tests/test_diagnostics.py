import json
import logging
import unittest
import zipfile
from pathlib import Path
from tempfile import TemporaryDirectory
from unittest.mock import patch

from watched_kettle.application.diagnostics import DiagnosticsExporter
from watched_kettle.application.logging import (
    LOGGER_NAME,
    LOG_SCHEMA_VERSION,
    close_logging,
    configure_logging,
    log_event,
    redact_diagnostic_text,
)
from watched_kettle.application.paths import AppPaths


class DiagnosticLoggingTests(unittest.TestCase):
    def tearDown(self):
        close_logging()

    def test_redaction_removes_email_paths_and_sensitive_fields(self):
        raw = (
            "email=person@example.com "
            "prompt=private request; file_path=C:\\Users\\example\\secret.txt"
        )
        safe = redact_diagnostic_text(raw)
        self.assertNotIn("person@example.com", safe)
        self.assertNotIn("private request", safe)
        self.assertNotIn("C:\\Users", safe)

    def test_structured_events_are_jsonl_with_safe_fields(self):
        with TemporaryDirectory() as directory:
            log_path = configure_logging(Path(directory))
            log_event(
                "usage.service",
                "request_failed",
                "WARNING",
                operation="account/read",
                request_id=4,
                error_code="timeout",
                secret="must_be_ignored",
            )
            logging.getLogger(LOGGER_NAME).info(
                "email=person@example.com prompt=private request"
            )
            close_logging()
            rows = [
                json.loads(line)
                for line in log_path.read_text(encoding="utf-8").splitlines()
            ]
            self.assertGreaterEqual(len(rows), 3)
            event = next(row for row in rows if row["event"] == "request_failed")
            self.assertEqual(event["schema"], LOG_SCHEMA_VERSION)
            self.assertEqual(event["component"], "usage.service")
            self.assertEqual(event["operation"], "account/read")
            self.assertEqual(event["error_code"], "timeout")
            self.assertNotIn("secret", event)
            message = next(row for row in rows if row["event"] == "message")
            self.assertNotIn("person@example.com", message["message"])
            self.assertNotIn("private request", message["message"])

    def test_existing_text_log_is_preserved_as_legacy(self):
        with TemporaryDirectory() as directory:
            root = Path(directory)
            path = root / "app.log"
            path.write_text("old text log\n", encoding="utf-8")
            configure_logging(root)
            log_event("test", "after_migration")
            close_logging()
            self.assertEqual(
                (root / "app.log.legacy").read_text(encoding="utf-8"),
                "old text log\n",
            )
            row = json.loads(path.read_text(encoding="utf-8").splitlines()[-1])
            self.assertEqual(row["event"], "after_migration")

    def test_rotating_log_is_utf8_bounded_and_redacted(self):
        with TemporaryDirectory() as directory:
            with patch("watched_kettle.application.logging.MAX_LOG_BYTES", 180):
                log_path = configure_logging(Path(directory))
                logger = logging.getLogger(LOGGER_NAME)
                for index in range(20):
                    logger.info("테스트 %s email=person@example.com", index)
            close_logging()
            self.assertTrue(log_path.is_file())
            self.assertTrue(log_path.with_name("app.log.1").is_file())
            combined = "".join(
                path.read_text(encoding="utf-8")
                for path in Path(directory).glob("app.log*")
            )
            self.assertNotIn("person@example.com", combined)

    def test_export_contains_metadata_and_redacted_logs_but_not_database(self):
        with TemporaryDirectory() as directory:
            root = Path(directory)
            paths = AppPaths(root / "data")
            paths.logs.mkdir(parents=True)
            paths.database.write_text("private database rows", encoding="utf-8")
            (paths.logs / "app.log").write_text(
                "email=person@example.com path=C:\\Users\\example\\project",
                encoding="utf-8",
            )
            target = DiagnosticsExporter(paths, 1).export(
                root / "diagnostics",
                {
                    "detected": True,
                    "config_path": "C:\\Users\\example\\.codex",
                    "event_count": 4,
                },
            )
            with zipfile.ZipFile(target) as bundle:
                self.assertEqual(
                    set(bundle.namelist()),
                    {"diagnostics.json", "logs/app.log"},
                )
                metadata = json.loads(bundle.read("diagnostics.json"))
                self.assertEqual(metadata["database_schema_version"], 1)
                self.assertNotIn("config_path", metadata["integration"])
                log = bundle.read("logs/app.log").decode("utf-8")
                self.assertNotIn("person@example.com", log)
                self.assertNotIn("C:\\Users", log)

    def test_utf8_and_multiline_records_rotate_before_byte_limit(self):
        with TemporaryDirectory() as directory:
            with patch("watched_kettle.application.logging.MAX_LOG_BYTES", 500):
                configure_logging(Path(directory))
                logger = logging.getLogger(LOGGER_NAME)
                for index in range(30):
                    logger.info("%s %s\n%s", index, "가나다라" * 12, "마바사아" * 4)
            close_logging()
            files = list(Path(directory).glob("app.log*"))
            self.assertEqual(len(files), 4)
            for path in files:
                self.assertLessEqual(path.stat().st_size, 500)
                self.assertIn("가나다라", path.read_text(encoding="utf-8"))

    def test_paths_keep_logs_beside_other_user_data(self):
        paths = AppPaths(Path("data-root"))
        self.assertEqual(paths.logs, Path("data-root") / "logs")


if __name__ == "__main__":
    unittest.main()
