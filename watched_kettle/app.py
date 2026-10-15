"""Application startup and default pet selection."""

import signal
import sys

from pathlib import Path

from PySide6.QtCore import QTimer
from PySide6.QtGui import QIcon
from PySide6.QtWidgets import QApplication

from watched_kettle.app_preferences import ApplicationPreferences
from watched_kettle.branding import APP_ICON_PATH, APPLICATION_ID, APPLICATION_NAME
from watched_kettle.config import DEFAULT_PET_ID
from watched_kettle.integrations.single_instance import (
    SingleInstanceCoordinator,
    configured_instance_server_name,
)
from watched_kettle.pet.catalog import (
    discover_pets_in_roots,
    personalize_pet_catalog,
)
from watched_kettle.pet.window import DesktopPet
from watched_kettle.startup_recovery import (
    StartupPetLoadError,
    create_startup_pet,
)
from watched_kettle.integrations.windows_startup import WindowsStartupRegistration
from watched_kettle.ui.startup_recovery import StartupRecoveryDialog
from watched_kettle.ui.fonts import configure_application_font
from watched_kettle.application.paths import AppPaths, migrate_legacy_data_root
from watched_kettle.application.logging import configure_logging, log_event


DEFAULT_PETS_ROOT = Path(__file__).resolve().parent.parent / "pets"
DEFAULT_PRIVATE_PETS_ROOT = Path(__file__).resolve().parent.parent / "private-pets"


def migrate_legacy_startup_entry():
    try:
        if WindowsStartupRegistration().migrate_legacy_entry():
            log_event("application.startup", "legacy_entry_migrated")
    except OSError:
        log_event("application.startup", "legacy_entry_failed", level="warning")


def prepare_codex_detection_notice(preferences, codex_detected):
    """Return a one-time notice when no local Codex environment is detected."""
    if codex_detected:
        preferences.save_codex_not_detected_notice_shown(False)
        return None
    if preferences.load_codex_not_detected_notice_shown():
        return None
    preferences.save_codex_not_detected_notice_shown(True)
    return {
        "source": "system",
        "event": "notification",
        "session_id": "codex-not-detected",
        "message": ("Codex를 감지하지 못했어요 · 펫 기능은 그대로 사용할 수 있어요"),
    }


def resolve_startup_pet(
    pet_directory=None,
    preferences=None,
    pets_root=None,
    additional_pets_roots=(),
):
    preferences = preferences or ApplicationPreferences()

    if pet_directory is not None:
        pet_directory = Path(pet_directory)
        if not pet_directory.is_dir():
            raise FileNotFoundError(pet_directory)
        return pet_directory

    pets_root = Path(pets_root or DEFAULT_PETS_ROOT)
    all_pets = discover_pets_in_roots(
        (pets_root, *(Path(root) for root in additional_pets_roots))
    )
    available_pets = personalize_pet_catalog(
        all_pets,
        preferences.load_pet_catalog_sort_mode(),
        preferences.load_pet_custom_order(),
        preferences.load_hidden_pet_ids(),
        fallback_pet_id=DEFAULT_PET_ID,
    )
    selected_pet_id = preferences.load_selected_pet_id()
    installed_selected_pet = next(
        (entry for entry in all_pets if entry.id == selected_pet_id),
        None,
    )
    selected_pet = next(
        (entry for entry in available_pets if entry.id == selected_pet_id),
        None,
    )
    if selected_pet is not None:
        return selected_pet.directory

    if installed_selected_pet is not None and available_pets:
        return available_pets[0].directory

    default_pet = next(
        (entry for entry in available_pets if entry.id == DEFAULT_PET_ID),
        None,
    )
    if default_pet is not None:
        return default_pet.directory

    if available_pets:
        return available_pets[0].directory

    raise FileNotFoundError(pets_root)


def create_pet_with_recovery(
    requested_pet_directory=None,
    preferences=None,
    pets_root=None,
    pet_factory=DesktopPet,
    recovery_request=StartupRecoveryDialog.request,
    settings=None,
    additional_pets_roots=(),
    pet_factory_kwargs=None,
):
    """Load a pet, allowing retry, folder selection, or a clean exit."""
    preferences = preferences or ApplicationPreferences(settings)
    pets_root = Path(pets_root or DEFAULT_PETS_ROOT)
    current_directory = (
        Path(requested_pet_directory) if requested_pet_directory is not None else None
    )
    while True:
        try:
            result = create_startup_pet(
                pet_factory,
                current_directory,
                preferences,
                pets_root,
                settings=settings,
                additional_pets_roots=additional_pets_roots,
                pet_factory_kwargs=pet_factory_kwargs,
            )
            return result, current_directory
        except StartupPetLoadError as error:
            initial_directory = current_directory or pets_root
            choice = recovery_request(error, initial_directory)
            if choice.action == "quit":
                return None, current_directory
            if choice.action == "choose":
                current_directory = choice.pet_directory


def main(
    *,
    runtime_factory=None,
    agent_controller_factory=None,
    codex_opener=None,
    on_started=None,
):
    if runtime_factory is None:
        from importlib import import_module

        runtime_factory = import_module(
            "watched_kettle.application.runtime"
        ).ApplicationRuntime
    app = QApplication(sys.argv)
    app.setApplicationName(APPLICATION_NAME)
    app.setOrganizationName(APPLICATION_ID)
    app.setQuitOnLastWindowClosed(False)
    configure_application_font(app)
    # Before anything opens files under the data root (ADR 0005).
    data_migration = migrate_legacy_data_root()
    paths = AppPaths.default()
    configure_logging(paths.logs)
    log_event("application.app", "started")
    if data_migration != "none":
        log_event("application.paths", "legacy_data_root", result=data_migration)
    migrate_legacy_startup_entry()
    if APP_ICON_PATH.is_file():
        app.setWindowIcon(QIcon(str(APP_ICON_PATH)))

    instance_coordinator = SingleInstanceCoordinator(
        server_name=configured_instance_server_name(), parent=app
    )
    if not instance_coordinator.start():
        return 0

    requested_pet_directory = Path(sys.argv[1]) if len(sys.argv) >= 2 else None
    preferences = ApplicationPreferences()
    startup_result, requested_pet_directory = create_pet_with_recovery(
        requested_pet_directory,
        preferences,
        pets_root=paths.user_pets,
        additional_pets_roots=(
            DEFAULT_PETS_ROOT,
            DEFAULT_PRIVATE_PETS_ROOT,
        ),
        pet_factory_kwargs={
            "pets_roots": (
                paths.user_pets,
                DEFAULT_PETS_ROOT,
                DEFAULT_PRIVATE_PETS_ROOT,
            ),
            "user_pets_root": paths.user_pets,
            "agent_controller_factory": agent_controller_factory,
            "codex_opener": codex_opener,
        },
    )
    if startup_result is None:
        instance_coordinator.close()
        return 0

    signal.signal(
        signal.SIGINT,
        lambda sig, frame: app.quit(),
    )

    signal_timer = QTimer()
    signal_timer.timeout.connect(lambda: None)
    signal_timer.start(100)

    pet = startup_result.pet
    if requested_pet_directory is None:
        preferences.save_selected_pet_id(pet.pet_id)
    instance_coordinator.activation_requested.connect(pet.reveal)

    def quit_for_installer():
        # Same path as the tray's quit, so every runtime closes in order.
        log_event("application.app", "quit_requested")
        app.quit()

    instance_coordinator.quit_requested.connect(quit_for_installer)
    runtime = runtime_factory(app, pet, preferences, paths=paths)
    runtime.start()
    codex_notice = None
    if getattr(runtime, "codex_server", None) is not None:
        codex_notice = prepare_codex_detection_notice(
            preferences,
            runtime.codex_server.diagnostics()["codex_environment"]["detected"],
        )
    if startup_result.failures:
        if getattr(runtime, "coordinator", None) is not None:
            runtime.coordinator.show_notice(
                {
                    "source": "system",
                    "event": "notification",
                    "session_id": "startup-pet-recovery",
                    "message": f"손상된 펫 대신 {pet.pet_display_name} 비서로 시작했어요",
                }
            )
    app.aboutToQuit.connect(instance_coordinator.close)
    pet.show()
    if codex_notice is not None:
        QTimer.singleShot(
            750,
            lambda payload=codex_notice: runtime.coordinator.show_notice(payload),
        )
    if on_started is not None:
        # Measurement probes attach here so they observe the real startup path.
        on_started(app, pet, runtime)

    sys.exit(app.exec())
