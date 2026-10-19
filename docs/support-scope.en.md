# Support scope

[한국어](support-scope.md) · [English](support-scope.en.md)

This page describes what the Pet + assistant edition shows for each tool and launch environment.
The current source version is **0.15.7 (beta)**. The verification history below describes the scope of past measurements and automated checks;
it does not mean that every combination has been verified in the current public installer.
The Claude Code measurements date from 2026-10-04, with app version 0.14.0 at the time.

| Tool | Page |
|---|---|
| Codex | [Codex on this page](#codex) |
| Claude Code | [Claude Code support](support-claude-code.en.md) |

## Verification levels

- **Measured**: observed by running the actual tool, with investigation records or user confirmation.
- **Automated**: confirmed only with synthetic events and regression tests, not yet with the actual screen or tool.
- **Unverified**: only the behavior expected from the code; never observed.

## Common

- Installation supports Windows 10 or later, 64-bit. Running from source supports only standard CPython 3.14.x; the development and CI baseline is 3.14.8.
- Each tool must be installed and signed in separately. The installer, uninstaller and app support Korean and English. The app also supports [custom language packs](language-packs.md), and a change applies after a restart.
- The **Pet only** edition does not connect to Codex or Claude Code. All per-tool pages apply to the **Pet + assistant** edition.
- If a connection fails, only that feature turns off, and the pet and the other tool's display keep working (fail-open, [ADR 0003 (Korean)](decisions/0003-fail-open-integrations.md)).
- Prompts, responses, commands, paths and tool output are not stored or logged ([Privacy and storage](privacy-and-storage.en.md)).
- Conversation discovery, the task queue and automatic execution exist in the source but are neither shown nor started in any edition.

## Codex

Shows the task status, conversation titles, project relationships and usage of the Codex Windows app.
Task status comes primarily from lifecycle hooks and, when needed, from read-only observation of status metadata events in the local session logs.
Usage is requested from the local Codex App Server. This app never approves permission requests on your behalf or runs tasks automatically.

| Feature | Behavior and verification scope |
| --- | --- |
| Task status and project bubbles | Shows working, needs attention, completed and failed. See [Project bubbles](user-guide.en.md#project-bubbles) for the detailed rules |
| Title click | Opens that conversation in the Codex app. Measured with Codex Windows x64 26.901.5003.0 in the 2026-09-05 review build. Not a guarantee for the current public installer or every other version |
| Navigation failure, unverified versions | Falls back to `Open Codex` or connection guidance. If only the Codex home opens, it is not treated as opening the exact conversation |
| Remaining limits and reset times | Shows the current account's limits returned by the local App Server. May be limited by the tool's installation, sign-in and response state |
| Token and task history | Distinguishes server account statistics from this device's log observations. Per-task figures that cannot be confirmed are shown as unmeasurable and never estimated |

To connect for the first time, right-click the pet → `Settings → Connections & diagnostics`, check `Codex enabled` and click `Connection checks`.
Review the changes before applying them, and follow any hook trust guidance.
The steps are in [First connection check](user-guide.en.md#first-connection-check), the measurement scope in [Usage](user-guide.en.md#usage),
and implementation notes in [Codex integration (Korean)](codex-integration.md). The conversation lookup and automatic execution described in the implementation notes are not part of the public feature list.

The supported tool versions and per-environment behavior of the current public installer need further real-environment review.
Past title navigation measurements and automated check results alone do not stand in for verification of the latest tool versions or installers.

## Using both tools

- Source dots (navy for Codex, orange for Claude Code) are added to bubbles, notifications and the tray only when you use both Codex and Claude Code. This is based on the Claude Code connection and a confirmed Codex account. The settings home and notifications always show the source name.
- Even in the same folder, bubble cards are kept separate per source.
- Usage collection is turned on and off per tool. With both off, the usage widget is hidden.
- Actual simultaneous use of both tools has been confirmed only by automated checks (a real-environment installer review is planned).
