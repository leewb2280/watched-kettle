"""Isolated real settings bridge for Electron integration tests, never product input."""

import argparse
from datetime import datetime, timedelta, timezone
import json
import os
from pathlib import Path
import shutil
import sys
import tempfile
import threading
from zipfile import ZipFile

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PySide6.QtCore import QObject, QProcess, QSettings, QTimer, Signal
from PySide6.QtWidgets import QApplication
from PIL import Image

from scripts import serve_update_test

from watched_kettle.app_preferences import ApplicationPreferences
from watched_kettle.application.paths import AppPaths
from watched_kettle.application.pet_runtime import PetRuntime
from watched_kettle.application.runtime import ApplicationRuntime
from watched_kettle.features.integrations.activation import (
    ACTIVATION_MIGRATION_KEY,
)
from watched_kettle.features.notifications.actions import ActionTarget
from watched_kettle.features.notifications.models import NoticeRequest
from watched_kettle.integrations.claude_code_hooks import normalize_claude_code_hook
from watched_kettle.integrations.claude_code_install import ClaudeCodeHookInstaller
from watched_kettle.integrations.claude_code_status_line import normalize_status_line
from watched_kettle.integrations.claude_code_status_line_install import (
    ClaudeCodeStatusLineInstaller,
)
from watched_kettle.integrations.codex_install import CodexHookInstaller
from watched_kettle.integrations.codex_ipc import CodexHookServer
from watched_kettle.integrations.windows_startup import StartupRegistrationStatus
from watched_kettle.pet.window import DesktopPet
from watched_kettle.ui.fonts import configure_application_font
from watched_kettle.usage.models import (
    DailyUsageBucket,
    RateLimitBucket,
    UsageAvailability,
    UsageWindow,
)
from watched_kettle.usage.trends import hourly_profile, remaining_series


class OfflineCodexClient(QObject):
    """Stands in for the Codex app-server so QA never reads the developer's
    account. Limits come only from the ``codex_limits`` control action; a real
    client let live rate-limit updates replace them while Codex was in use."""

    ready_changed = Signal(bool)
    response_received = Signal(int, str, object, object, object)
    notification_received = Signal(str, object)
    error_changed = Signal(str)

    def __init__(self, parent=None):
        super().__init__(parent)
        self.ready = False

    def start(self):
        pass

    def close(self):
        pass

    def request(self, method, params=None, timeout_ms=10000):
        return None


class IsolatedStartup:
    def __init__(self):
        self.enabled = False

    def inspect(self):
        return StartupRegistrationStatus(True, self.enabled, self.enabled, "", "")

    def set_enabled(self, enabled):
        self.enabled = enabled
        return self.inspect()


QA_CLAUDE_CODE_SESSION = "5c0de000-0000-4000-8000-000000000013"
# A user-chosen title is user data in any UI language. English QA uses an
# English title because history summaries mix titles with app fallbacks.
QA_CONVERSATION_TITLES = {"ko": "QA 대화 제목", "en": "QA conversation title"}
QA_PENDING_NOTICES = {"ko": "확인 대기 알림", "en": "Pending QA notice"}


def write_claude_code_transcript(config_dir, title):
    """A transcript shaped like Claude Code 2.1.286 output, with no real data."""
    folder = config_dir / "projects" / "C--qa-folder"
    folder.mkdir(parents=True)
    now = datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")
    entries = (
        dict(
            type="user",
            promptId="qa-prompt",
            sessionId=QA_CLAUDE_CODE_SESSION,
            cwd=str(config_dir.parent / "qa-folder"),
            timestamp=now,
            message=dict(role="user", content=[dict(type="text", text="qa")]),
        ),
        dict(
            type="assistant",
            sessionId=QA_CLAUDE_CODE_SESSION,
            requestId="qa-request",
            timestamp=now,
            message=dict(
                id="qa-message",
                model="claude-qa",
                stop_reason="end_turn",
                content=[dict(type="text", text="qa")],
                usage=dict(input_tokens=12, output_tokens=34),
            ),
        ),
        dict(type="custom-title", customTitle=title),
    )
    (folder / f"{QA_CLAUDE_CODE_SESSION}.jsonl").write_text(
        "".join(json.dumps(entry, ensure_ascii=False) + "\n" for entry in entries),
        encoding="utf-8",
    )


def synthetic_codex_trends(now):
    """Overview trend values with a reset and an average, no real data."""
    local = now.astimezone()
    midnight = local.replace(hour=0, minute=0, second=0, microsecond=0)

    def day(scale):
        # Uneven hours, and early hours never observed (the PC was off), as
        # in real use: the usual-day shape must break there, not drop to 0.
        return [
            None
            if 2 <= hour <= 6
            else int((900 + 140 * ((hour * 7) % 11)) * scale)
            if 8 <= hour <= 22
            else 0
            for hour in range(24)
        ]

    today = [
        value if hour <= local.hour else None for hour, value in enumerate(day(1.3))
    ]
    today[3] = None  # one unobserved hour
    hours = hourly_profile(
        today, [day(0.8 + 0.1 * offset) for offset in range(7)], local.hour
    )
    five, seven = [], []
    for step in range(local.hour * 2 + 1):
        moment = midnight + timedelta(minutes=30 * step)
        cycle = step // 10
        reset = midnight + timedelta(hours=5 * (cycle + 1))
        five.append((moment, 6.0 * (step % 10), reset))
        seven.append((moment, 30 + step * 0.8, midnight + timedelta(days=3)))
    quota = {
        "five_hour": remaining_series(five, midnight.date(), local.tzinfo, local),
        "seven_day": remaining_series(seven, midnight.date(), local.tzinfo, local),
    }
    daily = tuple(
        DailyUsageBucket(
            midnight.date() - timedelta(days=offset),
            None
            if offset == 9
            else 90000 + 6000 * (36 - offset) + 45000 * ((offset * 5) % 7),
        )
        for offset in range(36, -1, -1)
    )
    return hours, quota, daily


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument(
        "--edition", choices=("pet-only", "pet-assistant"), required=True
    )
    parser.add_argument("--language", choices=("ko", "en"), default="ko")
    parser.add_argument("--language-pack", type=Path)
    args = parser.parse_args()
    app = QApplication([])
    configure_application_font(app)
    app.setQuitOnLastWindowClosed(False)
    with tempfile.TemporaryDirectory(prefix="watched-kettle-settings-qa-") as folder:
        root = Path(folder)
        os.environ["CODEX_HOME"] = str(root / "codex")
        # Never read the developer's ~/.claude; one isolated finished turn.
        os.environ["CLAUDE_CONFIG_DIR"] = str(root / "claude")
        write_claude_code_transcript(
            root / "claude", QA_CONVERSATION_TITLES[args.language]
        )
        # The update row checks a local release server that announces v9.9.9.
        update_server = serve_update_test.serve(0, version="9.9.9")
        update_source = root / "update-source.json"
        update_source.write_text(
            json.dumps(
                serve_update_test.update_source(update_server.server_address[1])
            ),
            encoding="utf-8",
        )
        os.environ["WATCHED_KETTLE_UPDATE_SOURCE"] = str(update_source)
        settings = QSettings(str(root / "settings.ini"), QSettings.Format.IniFormat)
        preferences = ApplicationPreferences(settings)
        settings.setValue("app/languagePack", "official." + args.language)
        from watched_kettle.application.localization import initialize_language

        if args.language_pack is not None:
            from watched_kettle.localization.packs import load_pack

            pack = load_pack(args.language_pack)
            destination = AppPaths(root).language_packs / "qa-community"
            destination.mkdir(parents=True)
            for name in ("manifest.json", "messages.json"):
                shutil.copyfile(args.language_pack / name, destination / name)
            settings.setValue("app/languagePack", pack.id)
            # The runner copies the pack as an editable pack; opening the new
            # folder must not show the isolated temp folder in Explorer.
            from watched_kettle.application.settings_ui import core as settings_core

            settings_core.QDesktopServices = type(
                "QaDesktopServices", (), {"openUrl": staticmethod(lambda url: True)}
            )
        initialize_language(preferences, AppPaths(root))
        # The QA user already uses both tools (one switch per tool).
        preferences.save_claude_code_usage_enabled(True)
        settings.setValue(ACTIVATION_MIGRATION_KEY, 1)
        qa_pets_root = root / "pets"
        alternate_pet = qa_pets_root / "mori-bot-qa-alt"
        shutil.copytree(Path("pets/mori-bot"), alternate_pet)
        manifest_path = alternate_pet / "pet.json"
        manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
        manifest.update(id="mori-bot-qa-alt", displayName="Mori Bot QA Alt")
        manifest_path.write_text(
            json.dumps(manifest, ensure_ascii=False, indent=2), encoding="utf-8"
        )
        spritesheet_path = alternate_pet / manifest["spritesheetPath"]
        installed_pet = root / "codex" / "pets" / "qa-installed"
        shutil.copytree(alternate_pet, installed_pet)
        # Unused fields and another installation's decoration reference make
        # the import dialog show both omitted-information notices.
        installed_manifest = dict(
            manifest,
            tags=["qa"],
            bubbleTheme=dict(manifest.get("bubbleTheme", {}), pattern="user:qa"),
        )
        (installed_pet / "pet.json").write_text(
            json.dumps(installed_manifest, ensure_ascii=False, indent=2),
            encoding="utf-8",
        )
        import_archive = root / "qa-pet.zip"
        with ZipFile(import_archive, "w") as archive:
            for item in installed_pet.rglob("*"):
                if item.is_file():
                    archive.write(item, item.relative_to(installed_pet).as_posix())
        import_source = root / "웹 펫.png"
        with Image.open(Path("pets/mori-bot") / manifest["spritesheetPath"]) as atlas:
            atlas.save(import_source, format="PNG")
        import_invalid = root / "invalid-pet.png"
        Image.new("RGBA", (12, 12)).save(import_invalid)
        with Image.open(spritesheet_path) as spritesheet:
            # Keep the first idle cell populated; flipping the entire atlas
            # moves empty trailing cells into the thumbnail position.
            changed = spritesheet.copy()
            changed.paste(
                spritesheet.crop((0, 0, 192, 208)).transpose(
                    Image.Transpose.FLIP_LEFT_RIGHT
                ),
                (0, 0),
            )
            changed.save(spritesheet_path)
        pet = DesktopPet(
            Path("pets/mori-bot"),
            settings=settings,
            pets_roots=(Path("pets"), qa_pets_root),
            user_pets_root=qa_pets_root,
        )
        if args.edition == "pet-only":
            runtime = PetRuntime(app, pet, preferences, AppPaths(root))
            host = runtime.settings
        else:
            server = CodexHookServer(
                server_name="settings-qa-" + root.name,
                spool_directory=root / "spool",
                hook_health_path=root / "health.json",
                hook_config_path=root / "hooks.json",
                global_hook_config_path=root / "global-hooks.json",
                codex_config_path=root / "config.toml",
                managed_spool_directory=None,
                managed_hook_health_path=None,
            )
            runtime = ApplicationRuntime(
                app,
                pet,
                preferences,
                AppPaths(root),
                codex_server=server,
                usage_client_factory=OfflineCodexClient,
                codex_sessions_root=root / "sessions",
            )
            runtime.codex_hook_installer = CodexHookInstaller(
                hooks_path=root / "codex" / "hooks.json",
                config_path=root / "codex" / "config.toml",
            )
            runtime.integrations_vm.hook_installer = runtime.codex_hook_installer
            runtime.claude_code_hook_installer = ClaudeCodeHookInstaller(
                settings_path=root / "claude" / "settings.json",
                policy_paths=(),
            )
            runtime.integrations_vm.claude_code_installer = (
                runtime.claude_code_hook_installer
            )
            runtime.claude_code_status_line_installer = ClaudeCodeStatusLineInstaller(
                settings_path=root / "claude" / "settings.json",
                sidecar_path=root / "runtime" / "claude-code-status-line.json",
            )
            runtime.integrations_vm.status_line_installer = (
                runtime.claude_code_status_line_installer
            )
            # Both tools are on without their isolated hooks, so the connection
            # watch would post reconnect notices into the empty-history checks.
            runtime.connection_watch.announce_ready.disconnect(
                runtime._announce_connection
            )
            host = runtime.center
        runtime.settings_vm.startup_registration = IsolatedStartup()
        restart_requests = 0

        def record_restart():
            nonlocal restart_requests
            restart_requests += 1

        # UI command coverage only; detached relaunch has separate process tests.
        host.restart = record_restart
        host._start_server()
        # The runner consumes this line privately and never logs the token.
        print(
            json.dumps(
                dict(
                    pipe=host.server.fullServerName(),
                    token=host.token,
                    profile=str(root / "electron"),
                    control=str(root / "control.json"),
                    petImportSource=str(import_source),
                    petImportInvalid=str(import_invalid),
                    petImportFolder=str(installed_pet),
                    petImportZip=str(import_archive),
                )
            ),
            flush=True,
        )
        control_path = root / "control.json"
        # The runner never writes to stdin, so EOF means it is gone; quit
        # instead of polling forever when it dies before sending "quit".
        orphaned = threading.Event()

        def watch_runner():
            sys.stdin.buffer.read()
            orphaned.set()

        if sys.stdin is not None:
            threading.Thread(target=watch_runner, daemon=True).start()

        def tick():
            if orphaned.is_set():
                app.quit()
                return
            if not control_path.exists():
                return
            try:
                data = json.loads(control_path.read_text(encoding="utf-8"))
                control_path.unlink()
            except (OSError, json.JSONDecodeError):
                # The runner may still be writing; consume a complete command
                # on the next tick instead of logging a transient callback error.
                return
            if data["action"] == "double_click":
                from unittest.mock import patch
                from PySide6.QtCore import Qt
                from watched_kettle.integrations.windows_apps import AppOpenResult

                class DoubleClickEvent:
                    def button(self):
                        return Qt.MouseButton.LeftButton

                    def accept(self):
                        pass

                with (
                    patch.object(
                        host.process,
                        "state",
                        return_value=QProcess.ProcessState.Running,
                    ),
                    patch.dict(
                        runtime.pet_actions.openers,
                        {
                            action: lambda: AppOpenResult(True)
                            for action in ("codex", "claude")
                        },
                    ),
                ):
                    pet.mouseDoubleClickEvent(DoubleClickEvent())
            elif data["action"] == "batch_fixture":
                count = min(60, max(1, int(data.get("count", 55))))
                base = Path("pets/mori-bot")
                manifest = json.loads((base / "pet.json").read_text(encoding="utf-8"))
                for index in range(count):
                    pet_id = f"batch-qa-{index:02d}"
                    folder = qa_pets_root / pet_id
                    folder.mkdir(exist_ok=True)
                    (folder / "pet.json").write_text(
                        json.dumps(
                            {
                                **manifest,
                                "id": pet_id,
                                "displayName": "일괄 QA 중복"
                                if index < 2
                                else f"일괄 QA {index:02d}",
                            }
                        ),
                        encoding="utf-8",
                    )
                    atlas = folder / "spritesheet.webp"
                    if not atlas.exists():
                        shutil.copyfile(base / "spritesheet.webp", atlas)
                host.adapter.revision += 1
                host.adapter.changed.emit("settings")
            elif data["action"] == "batch_config":
                host.adapter.pet_batch.delay_ms = min(
                    2000, max(0, int(data.get("delay", 0)))
                )
                service = host.adapter.pet_vm.packages
                if not hasattr(service, "qa_original_move"):
                    service.qa_original_move = service.move
                failed_ids = set(data.get("failed", []))

                def controlled_move(pet_id):
                    if pet_id in failed_ids:
                        raise PermissionError("isolated QA failure")
                    return service.qa_original_move(pet_id)

                service.move = controlled_move
            elif data["action"] == "quit":
                app.quit()
            elif data["action"] == "show":
                host._send(
                    dict(event="navigate", data=dict(page=data.get("page", "pet")))
                )
            elif data["action"] == "account":
                host.adapter.assistant._account_changed(True)
            elif data["action"] == "notice":
                runtime.notification_service.submit(
                    NoticeRequest(
                        source="qa", message="연결 검증 알림", category="system"
                    )
                )
                record = runtime.notification_service.snapshot.recent[-1]
                # Avoid launching a second Electron; the runner owns the tested process.
                from unittest.mock import patch

                with patch.object(host, "_launch"):
                    host.open_target(ActionTarget("notice", record.record_id))
            elif data["action"] == "pending_notices":
                # Unopened notices for the notice center's confirm-all button;
                # more than five also fold behind "show more".
                for number in range(1, int(data.get("count", 2)) + 1):
                    message = f"{QA_PENDING_NOTICES[args.language]} {number}"
                    runtime.notification_service.submit(
                        NoticeRequest(source="qa", message=message, category="system")
                    )
            elif data["action"] == "claude_code":
                # One running Claude Code turn in an isolated folder, through
                # the same coordinator path a real hook event takes.
                session = QA_CLAUDE_CODE_SESSION
                runtime.projects.set_claude_code_title(
                    session, QA_CONVERSATION_TITLES[args.language]
                )
                runtime.coordinator.observe_agent_payload(
                    normalize_claude_code_hook(
                        dict(
                            session_id=session,
                            cwd=str(root / "qa-folder"),
                            prompt_id="qa-prompt",
                            hook_event_name="UserPromptSubmit",
                        )
                    )
                )
            elif data["action"] in {"claude_code_limits", "claude_code_limits_expired"}:
                # The expired sample's windows have reset since it was taken,
                # so the cards show the estimate (claude_code_limits.bucket).
                reset = int(datetime.now(timezone.utc).timestamp()) + (
                    -60 if data["action"].endswith("_expired") else 3 * 3600
                )
                runtime.coordinator.observe_agent_payload(
                    normalize_status_line(
                        dict(
                            session_id=QA_CLAUDE_CODE_SESSION,
                            rate_limits=dict(
                                five_hour=dict(used_percentage=25, resets_at=reset),
                                seven_day=dict(
                                    used_percentage=40, resets_at=reset + 86400
                                ),
                            ),
                        )
                    )
                )
            elif data["action"] == "codex_limits":
                # Put reserve first in the input to verify display grouping.
                now = datetime.now(timezone.utc)
                trend_hours, trend_quota, daily = synthetic_codex_trends(now)
                runtime.usage_service._publish(
                    availability=UsageAvailability(
                        "available", "Codex 한도를 받았습니다."
                    ),
                    trend_hours=trend_hours,
                    trend_quota=trend_quota,
                    daily_buckets=daily,
                    buckets=(
                        RateLimitBucket(
                            "base_model_inference",
                            limit_name="gpt-reserve",
                            primary=UsageWindow(24, 76, 10080, now + timedelta(days=3)),
                        ),
                        RateLimitBucket(
                            "codex",
                            primary=UsageWindow(68, 32, 300, now + timedelta(hours=2)),
                            secondary=UsageWindow(
                                90, 10, 10080, now + timedelta(days=2)
                            ),
                            plan_type="plus",
                        ),
                    ),
                    last_sample_at=now,
                    last_updated_at=now,
                    account_hash="synthetic-account",
                    account_checking=False,
                )
            elif data["action"] == "report":
                Path(data["path"]).write_text(
                    json.dumps(
                        dict(
                            visible=host.visible,
                            route=host.route,
                            doubleClickAction=preferences.load_double_click_action(),
                            petState=pet.current_state,
                            subscriptions=sorted(host.subscriptions),
                            revision=host.adapter.revision,
                            restartRequests=restart_requests,
                            notices=[
                                dict(id=n.record_id, confirmed=n.confirmed)
                                for n in runtime.notification_service.snapshot.recent
                            ]
                            if args.edition == "pet-assistant"
                            else [],
                        )
                    ),
                    encoding="utf-8",
                )

        timer = QTimer()
        timer.timeout.connect(tick)
        timer.start(30)
        try:
            app.exec()
        finally:
            runtime.close()
            pet.close()


if __name__ == "__main__":
    main()
