# Claude Code support

[한국어](support-claude-code.md) · [English](support-claude-code.en.md)

This page describes what the Pet + assistant edition reads from Claude Code, how it shows it, and how far each launch environment has been verified.
The current source version is **0.15.7 (beta)**, and the measurements date from **2026-10-04, with app version 0.14.0 at the time**.
Past measurements do not mean the current public installer has been re-verified.
The verification levels (measured, automated, unverified) and common points follow [Support scope](support-scope.en.md).

## Summary

- Read-only. The app only shows task status, conversation titles, task history and limits; it never sends work to Claude Code or answers permission requests.
- Task status comes from Claude Code hooks; interruption detection, conversation titles and task history from conversation transcript files; limits from the status line.
- The terminal CLI (standalone and in the VS Code integrated terminal) and the VS Code extension panel were tested for real. Limits update only from a terminal, and opening a conversation depends on the launch environment.
- The Claude desktop app, `claude -p` and other IDEs have not been observed.

## Tested environment

| Item | Details |
|---|---|
| Operating system | Windows 11 |
| Claude Code | 2.1.286 (hook and transcript investigation), 2.1.287 (status line measurement), 2.1.288 (VS Code extension link handling), 2.1.301 (Windows hook command format, 2026-10-17) |
| Launch environments | Standalone terminal CLI, VS Code integrated terminal CLI, VS Code extension panel (auto and default modes) |
| Earlier versions | Not verified. The hook registration format requires Claude Code 2.1.139 or later |

## Connecting

1. Install and sign in to Claude Code separately, and run the `Pet + assistant` edition of Watched Kettle.
2. Right-click the pet → `Settings → Connections & diagnostics`, and turn on `Claude Code enabled`.
   If you already chose it during installation, just check its status. The changes are shown in advance and applied only when you click `Apply changes`.
3. Restart any Claude Code sessions that were already open, run a new task, and confirm in `Connection checks` that events are received.
4. Turning on `Claude Code enabled` also turns on `Collect Claude Code limits` in the same place. To turn off only the limits, turn off this switch.
   Limits update after the first response in a terminal session with a supported claude.ai Pro or Max subscription. The VS Code extension panel alone does not update them.

See [First connection check](user-guide.en.md#first-connection-check) for the full steps. The hook connection and usage collection are turned on and off together with the single `Claude Code enabled` switch ([ADR 0006 (Korean)](decisions/0006-tool-activation-single-bundle.md)).

| Feature | What the app changes | When turned on or off |
|---|---|---|
| Claude Code enabled (off by default, [ADR 0006 (Korean)](decisions/0006-tool-activation-single-bundle.md)) | Adds this app's 14 hooks to `hooks` in your user settings (`~/.claude/settings.json`, `CLAUDE_CONFIG_DIR`) and turns on task history and limit collection | Turning it off restores this app's hooks and status line, stops reading Claude Code files and hides it from every screen. Other settings and hooks are left alone, and the file is backed up in the same folder before any change. Saved history stays |
| Collect Claude Code limits (only while enabled; turned on together with `Claude Code enabled`) | Replaces `statusLine` in your user settings with this app's command and keeps your previous status line in the app data | Turning it off restores the kept setting. If you changed the status line in the meantime, it is not overwritten |
| Status line items (in `Details`) | The items, lines and order, color emphasis and 5-hour reset time shown in the default status line | Not applied if you had your own status line, since only its output is shown as is |

- Claude Code sessions that are already open must be restarted for the hooks to apply. The CLI and the VS Code extension use the same user settings.
- If your user settings are broken (`invalid`), they are not overwritten. If `disableAllHooks` or the managed policy `allowManagedHooksOnly` is on, the hooks are not installed and only the status is shown. The enable switch still turns on, with a notice that activity display is limited.
- While the tool is off, events sent by leftover hooks are discarded. While off, the app only checks whether the `~/.claude` folder exists.
- The app's removal tool (`--remove-managed-hook`) restores the managed hooks and status line of both Codex and Claude Code.
- On Windows, Claude Code runs command strings with Git Bash, or with PowerShell if Git Bash is not available. The 14 hooks are therefore registered in exec form, which bypasses the shell (the executable in `command`, the arguments in `args`).
  The status line has no such form. If the executable path consists only of plain characters (letters, digits, Hangul, `/ : . _ -`), an unquoted path is used; otherwise a `powershell.exe -EncodedCommand` call. Both shells run the same command.
  Earlier Git Bash–only string entries appear as `drifted` and change to the new form when repaired.

## Support by launch environment

| Feature | Standalone terminal CLI | VS Code integrated terminal CLI | VS Code extension panel | `claude -p` | Desktop app, other IDEs |
|---|---|---|---|---|---|
| Working, waiting for confirmation, completed | Measured | Measured | Measured | Unverified (only hook execution observed) | Unverified |
| Interruption and permission rejection detection | Measured | Measured | Measured | Unverified | Unverified |
| Background waits and the completion after them | Automated | Automated | Automated | Unverified | Unverified |
| Conversation titles | Measured | Measured | Measured | Unverified | Unverified |
| Clicking a bubble title | Activity list | The VS Code window for that folder (measured) | That conversation in the panel (unverified) | Activity list | Activity list |
| 5-hour and 7-day limits | Measured | Measured | Not updated (measured) | Unverified | Unverified |
| Task history (per-turn tokens) | Measured | Measured | Measured | Unverified | Unverified |

The VS Code extension's terminal mode (`claudeCode.useTerminal`) runs the CLI, so it behaves like the VS Code integrated terminal CLI (limits measured).

## What is shown

### Task status

| Claude Code hook | Pet and bubbles |
|---|---|
| `UserPromptSubmit`, `PreToolUse`, `PostToolUse` | Working |
| `PermissionRequest`, `Notification` (`permission_prompt` only) | Waiting for confirmation (shown as `Permission requested` in bubbles, the settings window and the tray). Cleared when the next tool event arrives in the same session. No hook arrives when you approve, so it stays until the approved tool finishes |
| `Stop` | Completed. If background commands or subagents are running, it changes to `Background: N` (the pet rests, no notification); a tool use in the next turn that reads the results shows working, and that turn's `Stop` completes it. If only monitoring tasks (`monitor`, MCP tasks) remain, it completes right away |
| `PostToolUseFailure` | Stays working. Interrupted if `is_interrupt=true` |
| `StopFailure` | Failed (not observed) |
| `PreCompact`, `PostCompact` | Compacting, only during a working turn. A manual `/compact` between turns sends no `Stop`, so the pet's state does not change |
| `SubagentStart`, `SubagentStop` | Counted separately as subagents. Unnamed internal agents are discarded |
| `SessionEnd` | Session cleanup |

### Bubble cards

- A card is named after the main repository folder if the working folder is inside a git repository (including sessions opened in a worktree or subfolder), or after the working folder otherwise. The hook bridge decides this from `.git` and the worktree's `commondir`; a repository at the home folder or a drive root does not group the folders below it. The project is fixed from the session's first event. Usage history uses the same rule, grouping all turns of a conversation under the project of its earliest turn. Moving to another folder mid-conversation does not split it, and worktree records saved separately before this rule are merged into the project where the conversation started. A conversation started in a worktree and recorded before this rule stays separate. The row title is the conversation title (a name you gave it first, otherwise the automatic title, or `Claude Code conversation` if neither exists).
- Even when Codex uses the same folder, cards are kept separate per source. The source dot (orange for Claude Code) is added to headings only when you use both Codex and Claude Code.
- The activity caption below the pet and the tray status show the name of the working source.
- Since 0.15.7, project grouping in Usage → History follows the project of the working folder where the conversation started. Moving to a worktree or another folder mid-conversation does not split the same conversation across projects, and already saved history is shown merged by the same rule.

### Opening a conversation

| Launch environment | Behavior | Button |
|---|---|---|
| VS Code extension panel | Tries to open that conversation with `vscode://anthropic.claude-code/open?session=<ID>`. The actual click behavior is unverified | Open conversation |
| VS Code integrated terminal CLI | Reads the working folder from the transcript and brings forward the VS Code window for that folder | Open window |
| Elsewhere | Opens the activity list in the settings window | View list |

- The launch environment is determined from `CLAUDE_CODE_ENTRYPOINT` (`cli`, `claude-vscode`) and `TERM_PROGRAM=vscode` in the hook environment.
- A running CLI session is never reopened in the panel, because two processes would then use the same session.
- If the session link fails, the app falls back to the folder window, and if that also fails, to the list, explaining why next to the pointer.

### Limits

- Only the 5-hour and 7-day usage percentages and reset times are taken from `rate_limits` in the status line input. They arrive only with a claude.ai Pro or Max subscription, after the session's first response.
- They are shown on Usage Overview, Home, the widget and the tray, with a notification the first time 70%, 90% and 100% are crossed in the same reset window. The first value after the app restarts does not trigger a notification.
- Values whose reset time has passed are removed so they do not look current. Limit samples are kept for 8 days per Claude Code account.
- If you had no status line of your own, the app shows a default two-line status line (connection and model / context, 5-hour, 7-day). This text is only printed to the screen; only the limit numbers are sent to the app.

### Task history

- Per-turn tokens are collected from the conversation transcript files, including work done while the app was off, within 90 days.
- It is per device, not per account (the transcripts have no account). Only the limit samples are per account.
- Results are divided into completed, interrupted and in progress. Failures are not distinguished from the transcripts alone. Cost is not shown because there is no official value.
- `Trends` on Usage Overview (with Claude Code selected) draws today's hourly and daily tokens from the same turn records (per device, by finish time). The limit line is drawn from status line samples, so hours when you did not use a terminal are empty.
- Clearing history deletes only the app's history; Claude Code's transcript files are not touched.

## When hooks do not arrive

| Case | Handling |
|---|---|
| Interrupted response, permission rejection | If a user line without a hook appears in the transcript of a working session, it is treated as interrupted after 2 seconds (checked every second) |
| A turn that reads background command results (no `UserPromptSubmit`) | That turn's tool events and `Stop` are treated as belonging to the open turn. The result notification line is not taken as an interruption |
| A monitoring background task (for example, a live subscription) runs for the whole session | Not treated as work that delays completion. Only the task type and status in `Stop` are read |
| A background command that never ends (for example, a development server) | Stays as `Background: N` and is cleared by the 30-minute inactivity timeout (the same as waiting for confirmation) |
| Closing the VS Code panel (no `SessionEnd`) | Inactivity timeout: 10 minutes while working, 30 minutes while waiting for confirmation or running a tool (changeable in `Connections & diagnostics`) |
| A subagent works for a long time (the parent session is quiet) | Subagent events also update the parent's last activity time, and the parent's `Stop` completes it afterwards |
| A single tool runs for a long time (long builds, MCP tools) | While a tool has not finished, the same 30-minute limit as waiting for confirmation applies |
| The app starts mid-task | The session is not shown until the next hook arrives |
| While the app is off | Events are queued per user (up to 512), and events older than 60 seconds are discarded when the app starts again. Claude Code's work is never blocked |

## What is and is not read

- From hooks: the event type, session, prompt and tool IDs, the working folder name and a hash of its path, and the launch environment. Prompts, responses, commands, tool output and full paths are not sent to the app.
- From transcripts: line types, the conversation title, per-turn tokens and model names. Lines over 64 KiB are not parsed. Only when you click `Open window` for a VS Code terminal conversation is the working folder path read and passed to VS Code; it is not kept.
- From the status line: the 5-hour and 7-day usage percentages and reset times.
- Conversation titles and folder names are kept only in memory while running and never written to logs or the database. See [Privacy and storage](privacy-and-storage.en.md) for the detailed retention scope.

## What the app does not do

- It does not send work to Claude Code or approve or reject permission requests on your behalf.
- It does not read the graphical panel's limits through the undocumented OAuth usage API (that would require using your sign-in token directly).
- It does not show cost (USD) or git branches.
- It does not jump directly to a specific VS Code terminal tab. VS Code does not allow external links to run a command that selects a terminal, so without a dedicated VS Code extension the app brings forward only the folder window (decided 2026-10-04).

## If the format changes

Even if a Claude Code update changes the format, Claude Code's work is never blocked. The hook bridge always exits normally and prints nothing.

- Unknown hook names and notification types are discarded. Without `prompt_id`, events are handled without turn boundaries.
- If the payload cannot be parsed, a minimal event is built from the event name in the command arguments and `CLAUDE_CODE_SESSION_ID`.
- If the transcript format changes, immediate interruption detection stops and the inactivity timeout clears the display instead.
- The VS Code extension's conversation link and the transcript line format are paths that Claude Code does not document. If they change, opening a conversation falls back to the folder window or the list.

## Remaining checks

- `Open conversation` for VS Code extension panel conversations: the actual click, several VS Code windows, VS Code's confirmation dialog
- Background waits and the completion after them (real environment)
- The actual conditions for `StopFailure`, and the event order when the auto-mode classifier hands over to user confirmation
- The Claude desktop app, `claude -p` and other IDEs
- Hook processing time in the installer (target p95 100 ms) and actual simultaneous use of Codex and Claude Code
- Supported version range of the current public installer and re-verification for each launch environment
