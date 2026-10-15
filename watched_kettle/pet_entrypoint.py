"""Packaged pet-only entry point; it has no assistant imports."""

import sys

from watched_kettle.app import main as app_main
from watched_kettle.application.pet_runtime import PetRuntime
from watched_kettle.pet.idle_controller import IdlePetController


def main():
    if "--settings-ui-smoke-test" in sys.argv:
        from watched_kettle.settings_runtime_smoke import run_settings_smoke

        return run_settings_smoke(sys.argv[1:], PetRuntime, IdlePetController)
    if any(
        flag in sys.argv[1:]
        for flag in ("--codex-hook-bridge", "--assistant-notification")
    ):
        return 2
    if "--package-smoke-test" in sys.argv:
        from watched_kettle.app import DEFAULT_PETS_ROOT
        from watched_kettle.package_smoke import run_package_smoke

        return run_package_smoke(DEFAULT_PETS_ROOT)
    if "--runtime-smoke-test" in sys.argv:
        from watched_kettle.pet_runtime_smoke import run_pet_runtime_smoke

        return run_pet_runtime_smoke(sys.argv[1:])
    on_started = None
    if "--performance-probe" in sys.argv:
        from watched_kettle.performance_probe import probe_from_arguments

        on_started = probe_from_arguments(sys.argv[1:])
        # app.main reads argv[1] as an optional pet directory.
        del sys.argv[1:]
    return app_main(
        runtime_factory=PetRuntime,
        agent_controller_factory=IdlePetController,
        on_started=on_started,
    )


if __name__ == "__main__":
    raise SystemExit(main())
