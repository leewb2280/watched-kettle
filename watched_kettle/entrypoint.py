"""Shared source and packaged executable entry point."""

from __future__ import annotations

import sys

from watched_kettle.hook_bridge_entrypoint import (
    HOOK_BRIDGE_FLAGS,
    main as run_hook_bridge_main,
)


def main():
    arguments = sys.argv[1:]
    if "--settings-ui-smoke-test" in arguments:
        from watched_kettle.settings_runtime_smoke import run_settings_smoke
        from watched_kettle.application.runtime import ApplicationRuntime
        from watched_kettle.state.controller import PetAgentController

        return run_settings_smoke(arguments, ApplicationRuntime, PetAgentController)
    if "--remove-managed-hook" in arguments:
        from watched_kettle.integrations.claude_code_install import (
            ClaudeCodeHookInstaller,
        )
        from watched_kettle.integrations.claude_code_status_line_install import (
            ClaudeCodeStatusLineInstaller,
        )
        from watched_kettle.integrations.codex_install import CodexHookInstaller

        # Remove every agent's managed hooks and restore the user's own status
        # line; any blocked one fails the helper.
        exit_code = 0
        for installer in (
            CodexHookInstaller(),
            ClaudeCodeHookInstaller(),
            ClaudeCodeStatusLineInstaller(),
        ):
            plan = installer.preview_remove()
            if plan.can_apply:
                installer.apply(plan)
            else:
                exit_code = 2
        return exit_code
    if "--configure-integrations" in arguments:
        from watched_kettle.application.integration_setup import (
            run_integration_setup,
        )

        return run_integration_setup(arguments)
    if "--migrate-legacy-hook" in arguments:
        from watched_kettle.integrations.codex_install import CodexHookInstaller

        installer = CodexHookInstaller()
        plan = installer.preview_legacy_migration()
        if not plan.can_apply:
            return 2
        installer.apply(plan)
        return 0
    if "--assistant-notification" in arguments:
        from watched_kettle.integrations.assistant_notification import (
            run_assistant_notification,
        )

        raise SystemExit(run_assistant_notification(arguments))

    if "--runtime-smoke-test" in arguments:
        from watched_kettle.runtime_smoke import run_runtime_smoke

        raise SystemExit(run_runtime_smoke(arguments))

    if "--package-smoke-test" in arguments:
        from watched_kettle.app import DEFAULT_PETS_ROOT
        from watched_kettle.package_smoke import run_package_smoke

        raise SystemExit(run_package_smoke(DEFAULT_PETS_ROOT))

    on_started = None
    if "--performance-probe" in arguments:
        from watched_kettle.performance_probe import probe_from_arguments

        on_started = probe_from_arguments(arguments)
        # app.main reads argv[1] as an optional pet directory.
        del sys.argv[1:]
        arguments = []
    if not any(flag in arguments for flag in HOOK_BRIDGE_FLAGS):
        from watched_kettle.app import main as app_main
        from watched_kettle.application.runtime import ApplicationRuntime
        from watched_kettle.state.controller import PetAgentController
        from watched_kettle.integrations.codex_launcher import (
            open_codex_new_conversation,
        )

        return app_main(
            runtime_factory=ApplicationRuntime,
            agent_controller_factory=PetAgentController,
            codex_opener=open_codex_new_conversation,
            on_started=on_started,
        )

    raise SystemExit(run_hook_bridge_main())
