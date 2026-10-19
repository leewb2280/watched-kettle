# User guide

[한국어](user-guide.md) · [English](user-guide.en.md)

[Back to README](../README.en.md) · [Support scope](support-scope.en.md)

Start with installation and the first connection check. Task status and usage features are available in the **Pet + assistant** edition.
If you use the **Pet only** edition, see the basic pet controls and customization sections.

Screen and button names in this guide are the ones shown when the app is set to English.

## Contents

- [Installation and launch](#installation-and-launch) · [Updates](#updates) · [Quitting the app](#quitting-the-app) · [Uninstalling and data](#uninstalling-and-data)
- [Basic pet controls](#basic-pet-controls) · [Locking the pet and widget](#locking-the-pet-and-widget) · [Pet manager and trash](#pet-manager-and-trash)
- [Settings window and first connection check](#settings-window-and-first-connection-check) · [About page](#about-page) · [Turning tools on and off](#turning-tools-on-and-off)
- [Status display](#status-display) · [Project bubbles](#project-bubbles)
- [Usage](#usage)
- [Customization](#customization) · [Importing pets](#importing-pets)
- [Notification history and connections](#notification-history-and-connections)
- [Troubleshooting](#troubleshooting) · [Limitations](#limitations)

## Installation and launch

Download the installer and its `.exe.sha256` file from [Releases](https://github.com/leewb2280/watched-kettle/releases/latest).
Compare them as described in the [README's SHA-256 instructions](../README.en.md#quick-start), then run the installer.
The installer is not yet code-signed, so SmartScreen may show a warning. After checking the source and hash, you can proceed with More info → Run anyway.

Running the installer (`WatchedKettle-<version>-public-unsigned-setup.exe`) installs the app for the current user without administrator privileges.
First, choose the setup language (Korean or English). The app also uses the setup language at first. To change it, open `App settings` → `Language`, choose Korean, English or a custom language pack, and click `Restart app` at the right end of the language card's button row. The app restarts and reopens App settings. See [Language packs](language-packs.md).

1. **Edition**: choose `Pet only` or `Pet + assistant`. When you reinstall, the current edition is preselected.
   Switching from Pet + assistant to Pet only shows a notice that the hooks this app added will be removed.
2. **Tools** (Pet + assistant only): choose `Codex` and `Claude Code` separately. On a new installation, a tool is preselected
   if its settings folder (`~/.codex`, `~/.claude`) exists on this PC. The app installs its hooks and shows usage only for the tools
   you choose, and does not read the files of tools you leave out. When you reinstall, the tools turned on in the app are
   preselected, and only your changes are applied. After installation you can change this at any time in [Turning tools on and off](#turning-tools-on-and-off).
3. **Shortcuts and startup**: choose a desktop shortcut and starting the app when you sign in to Windows. The startup checkbox
   shows the current registration and is applied only if you change it.

The Start menu gets a single `Watched Kettle` shortcut without a folder. The shortcuts and the startup entry point to
`WatchedKettle.exe` in the installation folder (a small launcher that opens the executable for your edition), so pinned
taskbar items and shortcuts keep working when you change editions.

A silent installation (`/SILENT`, `/VERYSILENT`) keeps the current edition, tools and startup setting. A new silent installation
installs Pet only, and even if you choose Pet + assistant, Claude Code stays off unless you pass `/CLAUDECODE=on`. On the command line you can choose
`/EDITION=pet-only|pet-assistant`, `/CODEX=on|off` and `/CLAUDECODE=on|off`. `/LANG=ko|en` skips the language selection.

### Updates

Startup can also be turned on and off in `App settings` in the settings window. Updates are checked in `Version & updates` on the same page.
Click `Check for updates`; if a new version is available, the app shows the download size. Click `Update`. Whenever possible the app downloads only the
changed files and prepares the new program next to the current one (`Preparing the update…`). The pet then says
"Installing the update. The app will restart shortly.", the app quits, and the new version starts within a few seconds.
If only the changed files cannot be used (an old version, a failed preparation and so on), the app downloads the installer for your edition,
installs it without showing a window, and restarts in 20–30 seconds. Your edition, tools, settings and pets are kept. If installation fails, an error window appears.

With `Check for updates automatically` (on by default), an installed copy checks once a day for a new version. When it finds one, the pet
says "A new version is available" once, and `Check for updates` in the tray menu changes to `Get new version (v<version>)`. While bubbles are
off or snoozed, or while the pet is hidden, the app shows this only in the tray and the settings window, without a bubble. Downloading and installing
happen only when you click `Update`. A failed check is not reported; the app tries again later. With automatic checks off, the app checks only when you click `Check for updates`.
`Check for updates` in the tray menu opens the version row in `App settings` and starts a check right away.

The first time you start the app after an update, the pet says "Updated to v<version>" once. See what changed on the `About` page in the settings window.

### Quitting the app

The settings window's X hides only the settings window; the pet keeps running. To quit the pet as well, choose
`Quit` from the pet's right-click menu, `Quit pet app` at the bottom of the settings window's left menu, or `Quit` from the tray menu.

### Uninstalling and data

Uninstall through Windows Installed apps. The uninstaller removes this app's hooks and startup entry, and deletes only the data you choose:
`Keep my data` (default), `Delete history only` or `Delete everything`. `Delete history only` appears only when assistant history exists, and keeps your pets and settings.
If the app left no data, the uninstaller asks only for confirmation, without the data options.

If the pet is running during installation, upgrade or uninstallation, the setup program first closes the pet and the settings window normally. If they do not close within
10 seconds, it asks whether to force them to close; choosing `No` stops without changing anything. A silent run forces them to close without asking.
If another program is using the app data, `Delete everything` deletes nothing and stops the uninstallation; close that
program and uninstall again. Whatever stops an uninstallation, the app stays installed and you can uninstall it again.

## Basic pet controls

- Left-drag: move the pet
- Left double-click: wave and open the settings home (default). In `Customize → Pet → Behavior`, `Double-click action` can be changed to `Open Codex`, `Open Claude Code (VS Code)` or `Wave only`.
- Right-click: settings window, display, movement and quit menu
- Tray left-click: show or hide the pet
- Tray right-click (Pet + assistant): current status and usage, active projects and recent notifications,
  `Snooze notifications` · `Hide pet` · `Lock pet` · `Lock widget`, `Open home` · `View usage` · `Settings` · `Check for updates`, `Quit`
- Tray right-click (Pet only): `Hide pet` · `Lock pet`, `Settings` · `Check for updates`, `Quit`
- Tray icon: the pet's face gets a dot for working (blue), needs attention (ochre) or failed (russet).

### Locking the pet and widget

If the pet or the usage widget covers another app's buttons or text, lock it so that clicks pass through it to the window behind.
A locked pet stays visible, moves and follows the pointer with its gaze, but dragging, double-clicking and the right-click menu do not work.

- Lock the pet: `Lock pet` in the pet's right-click menu, `Lock pet` in the tray menu, or `Lock pet` in `Customize → Pet → Behavior`
- Lock the widget (Pet + assistant): `Usage widget → Lock widget` in the pet's right-click menu, `Lock widget` in the tray menu, or `Lock widget` in the widget settings
- Unlock: clear the check in the tray menu, turn it off in the settings window, or press your shortcut again.
  The widget lock can also be turned off from the pet's right-click menu.
- Shortcuts: in `Pet lock shortcut` or `Widget lock shortcut`, click `Set shortcut` and press the key combination you want.
  It must use Ctrl or Alt with a letter, digit or F1–F24 key, and no shortcut is set at first. Pressing it in any app
  turns the lock on or off. If another app already uses the combination, `Another app already uses this shortcut. Choose a different one.` appears;
  choose another combination. The pet lock and the widget lock cannot share a combination.
- In Pet + assistant, turn on `Let clicks pass through bubbles with buttons too` to make bubbles with buttons click-through while the pet is locked.
  It is off by default, so bubble buttons stay clickable.

The lock state and shortcuts are kept when you switch pets or restart the app. However, if the tray is unavailable and
no pet lock shortcut is set, there would be no way to unlock the pet, so the pet starts unlocked for that run.

## Pet manager and trash

In `Customize → Pet → Manage pets`, add pets, search them by name, or filter them by All, Shown or Hidden.
`Show in list` controls whether a pet appears in the selection list and the tray; it is separate from the pet you are using. The current pet cannot be hidden.
Changes are saved immediately. Reorder pets in the full list by dragging or with the up and down buttons.

- Move a pet you added to the trash from its More menu. If it is in use, choose a replacement pet first. Undo is offered right after the move. Bundled pets and pets from external paths can be hidden instead of deleted.
- The trash is separate from the Windows Recycle Bin and is never emptied automatically. Restoring a pet brings back its own settings, its visibility and, when possible, its previous position, and keeps your current pet. If a pet with the same ID or folder already exists, nothing is overwritten.
- `Delete permanently` and `Empty trash` delete the package and that pet's own settings after confirmation. They do not delete the external image you originally imported, other pets, app settings or history. If a pet with the same ID is back in the list, only the files in the trash are deleted and the listed pet's settings are kept.
- With `Select`, you can move, restore or permanently delete several items in the current search, filter and page. Changing the page or the conditions clears the selection. The trash shows 50 items per page.
- For a batch operation, you can follow its progress, successes and failures, and stop the remaining items. Completed items stay done. If you hide and reopen the settings window, the progress is still there. When the app quits, items that have not started are not resumed automatically.
- A locked file or a restore conflict leaves a failed item; fix the cause and try again. Damaged or unreadable records are reported rather than deleted. Importing the same pet again suggests restoring it from the trash.

## Settings window and first connection check

The settings window's left menu is divided into `Home`, `Assistant` (Usage, Notification history, Connections & diagnostics), `Customize` (Pet, Bubbles, Widget), `About` and `App settings`.
The Pet only edition also has `Home`, plus Pet and Bubbles under `Customize`, `About` and `App settings`. `Assistant` and `Customize` are group headings, not items you select.
Drop-downs, sliders and the tabs at the top of a page do not change with the mouse wheel; use clicks or the keyboard.

In both editions, `Home` shows the current pet, customization shortcuts and the double-click action. In Pet + assistant, it also brings together notifications to review, active conversations, remaining limits (in separate Codex and Claude Code areas) and the connection status of the tools in use,
with links to each page. `Open home` in the tray opens Home.

### About page

`About` shows the version and edition, what's new in this version, links to the GitHub repository, bug reports and licenses, and the licenses of the open-source components included in the app.
Links open in your default browser. `Changelog` opens the list of Releases for every version.
In an installed copy, `Open licenses folder` opens the folder containing the full text of each license.
The first time you start the app after an update, the pet says "Updated to v<version>" once per version and points you to What's new on `About`.
If bubbles are off or snoozed at that time, the message is not shown and is not repeated later.

### First connection check

1. Right-click the pet and open `Settings`. Task status requires the `Pet + assistant` edition.
2. Install and sign in to the Codex or Claude Code tools you want to connect, then open `Connections & diagnostics` in the settings window.
3. Check the `Codex enabled` or `Claude Code enabled` switch for each tool you use. If it is off, turn it on, review the changes and click
   `Apply changes`. If you already chose the tool during installation, there is nothing more to apply.
4. Restart any Claude Code sessions that were already open and run a new task.
   In `Connection checks`, confirm that a recent event was received. For Codex, follow any hook trust guidance in the check results.
5. Turning on `Claude Code enabled` also turns on `Collect Claude Code limits` in the same place. To turn off only the limits, turn off this switch.
   Limits arrive after the first response in a terminal session with a supported claude.ai Pro or Max subscription.
   Using only the VS Code extension panel does not update them.

The Pet only edition has no connection page. The pet keeps running if a connection fails.

### Turning tools on and off

In `Connections & diagnostics`, turn **Codex enabled** and **Claude Code enabled** on and off separately. Before applying, the app shows what will change.

- Turning a tool on adds only this app's hooks to that tool's user settings and shows its task status and usage. It turns on even if the tool's
  settings block hooks; a notice then says that activity display is limited. Codex reports some status from its task logs even without hooks.
- Turning a tool off removes the hooks this app added (for Claude Code, including the status line that collected limits), stops reading that tool's files,
  and hides it from Home, Usage, history, the tray and the widget. Cards that looked active are cleared too. Saved usage history stays and
  reappears when you turn the tool back on. `Open Codex`, when explicitly chosen as the double-click action, is independent of this switch.
- A tool that is off shows only its switch and a short description in Connections & diagnostics.
- If the hooks of a tool that is on are removed or changed, the pet says in a bubble that the tool "was disconnected", and the first line of the tray menu and
  `Connection` on the settings home show it as well. Clicking it opens `Connections & diagnostics`. Until it is fixed, you are told once each time the app starts.
- If you install Codex or Claude Code after installing the app, you are told once that it "was found". Tools that already existed at installation are
  not suggested again.

See [Support scope](support-scope.en.md) for supported environments and verification levels, and
[Notification history and connections](#notification-history-and-connections) for the detailed checks.

## Status display

- `idle`: waiting
- `running`: working or running a tool
- `review`: thinking or summarizing results
- `waiting`: waiting for your confirmation or permission
- `jumping`: task completed
- `failed`: task ended in failure

A single failed tool is not shown as a failed task. A notification for a completed main task stays even while
other tasks are running.

## Project bubbles

Project bubbles show working, needs-attention and completed conversations together.
Up to three project cards are shown; see the rest with the "more projects" row.
One usage or system notice and one reminder are kept separately.

The header reads `Completed N · Needs attention N · Working N`, hiding any count of 0.
Project names and status counts are shown on one line without truncation. If the header needs more room, the bubble widens beyond the theme's maximum width,
and the header's text shrinks only when it would exceed the screen width itself. When the text gets shorter, the width shrinks again.
Counts include conversations below the scroll. Conversations are sorted completed → needs attention and failed → interrupted → working and reviewing,
newest first within a status group. Tool activity or a title update alone does not change the order.
The first two rows are fully visible, and the rest scroll vertically inside the same bubble.
With a single row, the bubble gets shorter; on small screens it shrinks to one row's height and scrolls.
The header stays fixed, and if a new completion arrives while you are scrolled down, the conversation you were looking at stays in place.

A status badge appears to the right of each title. Completed is green, needs attention is yellow,
failed is red and interrupted is gray; working and reviewing are plain text without a background.
The width adjusts to the title, header and buttons, and titles are truncated after two lines.
Hover over a title, or use accessibility features, to read the full title.
While connected normally, titles are refreshed about every 3 seconds. If a lookup fails, the last good title is kept;
`Codex conversation` is shown only when no title has been received yet. Completed conversations on display are refreshed as well.

A new conversation first checks its project and joins the existing bubble. Only the first placement waits, for at most 1 second;
if the project is still unknown, it is gathered into a single `Finding project` bubble. This differs from
`Conversations without a project`, which means the conversation was confirmed to have no project. The pet's reaction to a starting task does not wait.

If no new activity arrives for 60 seconds during normal work or 180 seconds during a tool run, the row is not removed but
shown in gray as `Checking status`. The header counts it separately, and the row returns to its
original state when new activity arrives. A successful title lookup alone is not taken as progress.
Conversations that need attention are waiting for your response, so this time limit does not apply to them.
An asynchronous question raised during a task is also shown as `Needs attention`. Even if the task continues right after the question,
it stays until the next user message in the same conversation. If there are several questions,
each user message clears the oldest one.

When a compaction start signal arrives, the row shows `Compacting context` and is counted as working in the header.
The usual 60- and 180-second limits do not apply during compaction. If no end or clear
resumption of work is detected within 10 minutes of the start, the row switches to `Checking status` but stays.
An end signal or a normal tool run returns it to normal; confirmation requests, completion, failure and interruption take priority.
A title update, a reconnection or an ordinary heartbeat alone is not taken as the end of compaction.
Where the compaction start hook is not delivered, compaction is not assumed, so the usual inactivity display may apply.

A tool result that arrives without a task start is not shown as a new task. A result that arrives late after completion does not
turn the completed display back into working. If you start the pet in the middle of a task, progress can be detected from a tool start
that carries the conversation and call identifiers and arrives after collection begins. A conversation whose end was already confirmed is shown
as working again only after a new task start or another task turn is confirmed.

Rows whose end is not confirmed are not removed by time alone; they stay until an explicit end, an app restart or a confirmed account reset.

Bubbles stack in one column above the pet. At the edge of the screen, they stop moving only in that direction
and follow again when the pet moves back inside. Moving the pet and periodic updates reuse the existing windows and rows.
If the pet would cover the titles at a top corner, the bubble column moves to the free space beside it.
If both sides are too narrow, it uses the space below, and it returns to the usual position above when there is room.

### Completion display and history

When a main task completes normally, its conversation row shows a green `Completed` badge and an X.
The row background and the header's completed count are highlighted for 15 seconds by default; after that only the green badge remains.
The row is cleared at most 5 minutes after completion, and clicking X closes only that completion.
If the next task starts in the same conversation, the row returns to `Working` right away without clicking X.
Conversation rows are never duplicated, and the project bubble closes when no conversations remain.

Clicking a Codex conversation title opens that conversation in the Codex app. For Claude Code, it depends on where the conversation runs.
A conversation in the VS Code extension panel tries to open in the panel (`Open conversation`; the actual click behavior is unverified). A conversation in the VS Code integrated terminal
brings forward the VS Code window for its folder (`Open window`). For a conversation running in another terminal, the app cannot find that window,
so it opens the activity list in the settings window (`View list`). A running terminal conversation is never reopened elsewhere.

If Claude Code finishes its response while leaving background commands or subagents running, the row changes to `Background: N`.
The pet returns to resting, and when the background work ends and Claude Code reads the results and finishes, `Completed` is shown once.

When you use both Codex and Claude Code, source dots (navy for Codex, orange for Claude Code) appear before the card and notification headings.
With only one tool, no dot is added. Hover over a heading to see the source name.

Clicking a title only opens the conversation. Whether the link request succeeds or fails, or opens the Codex home instead,
the completion display stays, and the app does not guess whether you have read it. Failure, interruption, subagent completion and disconnection are
not recorded as normal completions. Failures and interruptions keep their usual display time.

Past completions are listed in `Recent activity` on the `Notification history` page in the settings window, with the completion time, conversation title, completion status and Open conversation.
X, the 5-minute expiry and the next task start only clear the bubble display; they do not delete the history.
Completion history keeps the latest 100 entries in memory only, and completions on display are managed separately from this limit.
The history is cleared when the app restarts or when an account change or sign-out is confirmed. A temporary break in the title lookup connection does not clear active rows or history. Titles and identifiers are not newly written to disk.
There is no separate completion card, recent-completion badge or dedicated list window.

`Completion highlight` under `Display time` defaults to 15 seconds, with a range of 5–60 seconds, and keeps the existing settings key.
It is independent of the shared time, and a changed value applies from the next completion. The 5-minute limit for completed rows is fixed.
Time keeps running while notifications are off or snoozed or the pet is hidden, and expired completions are not shown again when you return.

### Display time for other notifications

Failure and interruption results, usage, system notices and reminders use a shared display time, 8 seconds by default.
Adjust `Shared display time` between 5 and 60 seconds under `Display time` in `Customize → Bubbles`.
Turning on `Use custom time` for a type in the same area starts from the time currently in effect
and lets you set that type alone to 5–60 seconds. Turning the switch off removes the custom value, so failures, general notices and reminders use the current
shared time again and the completion highlight uses its own default of 15 seconds.
`Reset per-type times` removes all four custom values while keeping the shared time.
An earlier display time setting carries over as the shared value, and reminders use the shared value unless set separately.
Working, reviewing and waiting for confirmation are shown while the state lasts. The time for an end result is fixed when the task ends,
and the time for other notifications when they actually start showing; a timer already running is not changed by a settings change.
An automatic expiry does not mark a notification as read.
Opening a notification's details marks it as read. Notifications received while snoozed can be reviewed in the history and are not
replayed all at once after the snooze. The session history of project events (20 status changes, 50 needs-attention items) and 50 general notifications is not restored after a restart.

`Preview on pet` runs from the customization card at the top of the Bubbles page. In the assistant edition, the
`Snooze notifications` card normally offers only 15, 30 and 60 minutes, and while snoozed shows only the time left and
`Resume now`. While snoozed, all bubbles, including project progress and completion cards, are
hidden, and general notices and reminders received in the meantime are not shown later. Tasks still in progress appear when
bubbles return. While bubble notifications are off, a new snooze cannot be chosen.
The Pet only edition offers only bubble customization and Preview on pet.

The 2026-09-05 review build confirmed that clicking a title opened the exact conversation in Codex Windows x64 26.901.5003.0.
In the latest integrated source, the user confirmed manually that the intended conversation opened.
For unverified versions or failed navigation, the app falls back to `Open Codex` or connection guidance.
If only Codex opens, it is not treated as having opened that conversation.
Reminders currently offer only receiving, display preparation and preview; they are not yet connected to your calendar system.

## Usage

On the `Usage` page in the settings window, you can see daily token activity provided by the server, the remaining percentage for each limit,
reset times and the number of available usage resets. Choosing tokens in today's hourly view shows differences observed in this Windows user's Codex JSONL logs, which can include activity from several accounts. Choosing limits shows only the App Server usage differences observed for the currently confirmed account. Neither is an official hourly statistic, and hours without observations are left empty. Local limit samples are not added to account limits.

### Usage widget

The Usage page shows only the tools in use. Tools are turned on and off in `Connections & diagnostics`.
Remaining limits on Overview and Home show the two tools in separate areas, with the reserve limit as the last card in the Codex group.

The usage widget beside the pet shows the remaining limits of Codex and Claude Code together.
A tool that is off or has never received a value takes no space. With both tools off,
the widget is hidden. Its appearance settings are in `Customize → Widget`.
The preview at the top of that page is drawn the same way as the widget beside the pet and reflects changes immediately.
Clicking `Sample values`, or having no limits yet, shows sample values, and for `Compact` you can also see how it looks on hover.

- **Widget layout**: choose `Rings` (default), `Bars` or `Compact`. Compact expands on hover to show reset times and the other limits.
- **Main limit**: choose whichever of the 5-hour and 7-day limits has less left (automatic), 5-hour or 7-day; this applies to both tools. Other limits are shown in small text. Less than 30% left uses the caution color, and less than 10% the low color.
- **Show task status**: shows each tool's working and needs-attention counts, with needs attention first when present. In Compact, both tools have status dots in the same position: gray when there are no tasks to show, the working color while working, and the attention color when something needs attention. Hovering shows the counts or `No tasks to show`, so you can check task status even without limit information. A gray dot does not guarantee a working connection or an actual idle state. Turning this setting off hides both the status dots and the task status text.
- **Show today's activity** (off by default): draws today's hourly tokens as small bars. Codex values are observed in this device's logs, so hours without observations are shown as faint short bars; Claude Code adds up the tokens of finished turns from conversation transcripts. `Today's activity hours` narrows the hours shown.
- **Color**: by default it follows the app theme (light or dark); choose `Custom background color` to set the background color. The text color adapts to the background's brightness. When `Background opacity` is below 100%, secondary text is darkened to the body text color so it stays readable over the desktop, and below 60% the text gets an outline. A light card made semi-transparent over a dark desktop looks gray; in that case, a dark app theme or a higher background opacity looks better.
- **Background material**: choose `Solid` (default) or `Acrylic`. Solid draws a single card color, with transparency set by `Background opacity`. Acrylic is a Windows 11 glass effect that blurs what is behind the widget, so the card does not look muddy over a dark desktop. It follows the app theme (light or dark), so custom color and background opacity are not used with Acrylic. If you turn off Windows transparency effects or use high contrast, it switches to Solid within a minute. The settings preview shows the color over a dark background instead of the actual glass effect.
- **Size**: adjust from 70% to 130% in 10% steps.

If a value has not been updated for more than 15 minutes, the numbers and rings or bars turn gray and show how many minutes old the value is. Lowering the background opacity does not make the text transparent. Connection failures, sign-in required and loading are shown as short text instead of numbers. Claude Code limits update only while you use Claude Code in a terminal; until then, the widget shows `Limits in terminal`. If the reset time has passed with no new value, the widget shows an estimated value marked `(estimated)`, such as `5h 100% (estimated)`. For the large number, the mark is placed beside the limit name.

Clicking the widget opens `Usage` in the settings window. At first the widget moves with the pet, but dragging its background pins it in place, and the position is restored after a restart. From `Usage widget` in the pet's right-click menu, you can show the widget, change its layout, show task status or today's activity, or choose `Move back beside pet`. Widget settings from earlier versions are moved to the new settings once, on the first start.

Tokens in the widget and in small chart tooltips are abbreviated to units such as `950`, `1.2K`, `4.1M`, `1.2B` and `1.2T`.
There is at most one decimal place, and `.0` is omitted. A value that would round to
`1000K` is shown as `1M`. In the settings window's figure cards, task tables and detailed chart tooltips,
you can see the exact full token count with thousands separators. When the remaining percentage or tokens could not be observed,
the app distinguishes this from an actual 0 and shows that it is waiting for observations or collecting a baseline.

Device tokens can include local activity from several accounts and are not added to account limits. Account history and device observation history are deleted with their own buttons. Device history is limited to 8 days or 20,000 rows per table; older records are excluded from totals but can be viewed separately.

On Codex's `Overview`, expand `Limit details and account statistics` to see each limit window's remaining percentage, reset time and available resets, the plan and credits, and account statistics such as total account tokens, peak daily tokens and active-day streaks. When the server provides a window's duration, it is labeled like `5-hour limit`; limits that do not exist are not invented from the plan name alone. Hourly and daily tokens and changes in remaining limits are shown separately in the `Trends` charts below; tokens and limit percentages, which use different units, are never added together or converted.

While the connection is healthy, the shared usage status and last update time appear on one line to the right of the account name. If the account name or status text is truncated in a narrow window, hover over it to read the full text. Connection errors, stale caches, partial updates and history-related notices are shown in a separate banner.

The `Usage` page has **Overview / History / Settings** tabs. Collection for each tool is turned on and off with `Codex enabled` and `Claude Code enabled` in `Connections & diagnostics`; with both off, limits are not checked and `Refresh` is unavailable.

- **Overview**: remaining limit cards in separate Codex and Claude Code areas (`Healthy` at 30% or more left, `Caution` at 10% or more, `Low` below that), today's device activity and the `Trends` charts. Claude Code limit cards show when they were last observed and are marked `Stale value` after more than 15 minutes. Claude Code limits update only while you use Claude Code in a terminal, so usage while you were inactive, or on the web or the desktop app, is not reflected. If the reset time has passed with no new value, the card shows 100% left marked as estimated, and the 5-hour limit says `Starts fresh the next time you use it` (the 5-hour window starts at your next use). The top line shows, for each tool that is on, the Codex account and plan and when Claude Code was last observed.

In `Trends`, choose `Codex | Claude Code` to the right of the heading and the chart type inside the card. Tools that are not in use are left out of the limits on Home and Usage and out of the tool choice in `Trends` and `History`; with only one tool on, that tool is shown without a choice (tools not chosen during installation start off). To see a tool again, turn it on in `Connections & diagnostics`. Summary numbers sit above each chart, and hovering over a bar or line shows the exact value. If there are no observations or the tool is off, a message is shown instead of an empty chart.

| Chart | Bars | Line | Summary |
|---|---|---|---|
| Today's tokens | Tokens per hour (the current hour is darker) | A faint gray area behind the bars = the average for the same hour on days with records in the last 7 days (your usual pattern). Hours without observations are left blank, and it is not drawn with fewer than 3 days of records | Today's total, compared with usual (up to the current hour), busiest hour |
| Today's limits | None | Remaining limit percentage (0–100%). Vertical dotted lines are resets; a faint dotted line runs from the last observation to now. Choose `5-hour / 7-day` on the chart, separately from the widget's `Main limit` | Remaining limit now, limit used today (percentage points; the first value after a reset is used only as a baseline), number of resets |
| Daily tokens | Tokens per day (today is darker) | 7-day moving average (thin line, when at least 4 of the 7 days have records) | Period total, daily average, busiest day. The period is 7, 14 or 30 days |

The data range differs by tool.

- **Codex**: today's tokens are based on this PC's Codex logs, and hours without observations are shown faintly at the bottom. Daily tokens are the server-provided values for the whole account (including other PCs). Limits are the main limits, excluding the reserve limit.
- **Claude Code**: both today's and daily tokens are based on this PC's conversation transcripts, counting the tokens of each finished turn at the time it finished. Limits are observed only while you use Claude Code in a terminal, so there may be gaps.
- **History**: choose `Codex | Claude Code`. Projects are listed on the left and the selected project's conversations on the right. Projects are sorted by newest or name (Codex also supports a custom order), and conversations by most recently completed or by tokens. Sorting applies as soon as you choose it, and a search applies with `Enter` or `Search`. Clicking a conversation opens its task list, and clicking a task row expands details such as tokens, estimated credits and model. Move through the list with `Previous 100` and `Next 100`. Claude Code tasks collect per-turn tokens from the conversation transcript files, including work done while the app was off, within 90 days. Claude Code history can be cleared separately on this tab (Claude Code's own transcript files are not touched).
- **Settings**: usage notifications and `Data management` (clearing device observations or the current account's task history). Clearing asks for confirmation first. Widget settings moved to `Customize → Widget`.

Per-task Codex tokens are calculated from this device's Codex logs by matching the start and completion of the same task and the difference in cumulative values. When a log is split into several files, the boundary with the previous file is verified too. **Partial measurement** means the task's total tokens were confirmed but some items, such as input, output or model, are missing. A confirmed zero is shown as `0` and an unknown value as `—`; unmeasurable records are excluded from usage rankings. Account-wide usage is never divided among tasks.

Existing unmeasurable records are checked again when the app starts, when a new task completes and on refresh. Once checked, the details show the reason, such as no linked log, unconfirmed start or completion, unconfirmed token baseline or a decreasing cumulative value. Per-task credits and USD cannot be confirmed from the logs and are shown as unmeasurable. Switching accounts, signing out or clearing history cancels earlier recovery results so they are not applied late.

Even with the background opacity at 0% and the card invisible, you can drag the widget's empty background area to move it.

## Customization

### Pet and display settings

In `Customize → Pet`, set the pet, its size, gaze range, idle activities, walking, always-on-top and the items below.
The last pet and its screen position are restored on the next start. If the saved monitor is gone, the pet moves to a safe position on the main screen.

- **Pet opacity**: 50–100% (in 5% steps, default 100%). Values below 50% are blocked because the pet becomes hard to find on the desktop.
- **Ground shadow** (off by default): draws a faint shadow under the pet's feet.
- **Fade in and out** (on by default): the pet fades gradually when hidden and shown again. With `Reduce motion` on in `App settings`, it appears and disappears instantly.
- **Show current activity below pet**: the caption below the pet shows the working tools (Codex, Claude Code) with colored dots. It follows the app theme colors.

The pet's original sprite cell is `192×208px`. A display width of `112px` is the default,
`192px` the original size, `224px` the standard maximum and `352px` the extended maximum.
`80–224px` are standard sizes and `256–352px` are extended sizes for large screens.
The preview on the settings card does not reproduce the chosen size 1:1; it shows the pet's basic pose sharply, excluding transparent margins.
Check the actual display size at the bottom of the card and in the size controls.

### Importing pets

`Customize → Pet → Import pet` accepts three kinds of input. It is available in the Pet only edition too.

- **File or folder:** choose a PNG/WebP downloaded from a web pet tool, a pet ZIP, or a pet folder containing `pet.json`.
- **Install command:** paste an install command copied from CodexPetDB or Pets Codex (for example, `npx codexpetdb install <name>`) and
  click **Download**. The command is never run; the app reads only the pet ID and downloads directly from that service, so Node.js or a separate CLI
  is not needed. This is the only time it connects to the internet ([Privacy and storage](privacy-and-storage.en.md#network-and-installer)).
  You can **Cancel** a download and start it again right away.
- **Pets installed in Codex:** choose a pet from `pets` in your Codex user folder (`CODEX_HOME` or `~/.codex`) to copy it. The original is not changed.

In the import window, check the name and previews of the nine actions, then click **Add** to register the pet.
Switch to it with **Use this pet**; adding it alone keeps your current pet. Supported information in the package, such as description, author, size and bubble decorations,
is imported too, and you are told before registration about anything that is not imported. Supported features and limits follow the [pet package format](pet-package-format.en.md).

Still PNG/WebP images up to 20 MiB in the V1 (1536×1872) or V2 (1536×2288) layout are accepted, and the transparent background and
required frames are checked. A file selection expires after 10 minutes; if you see an expiry notice, choose the file again.
The same image reuses the existing pet and keeps its name and settings. A different image with the same name is
registered as a separate pet. Clicking **Use this pet** on a hidden existing pet shows it in the list again.
A web tool's name, description and bubble decorations are not restored from an image file alone; importing a ZIP, folder or install command brings them along.

Registered pets are stored independently in `%LOCALAPPDATA%\WatchedKettle\pets`, so they keep working after you delete the original download,
and they remain in the list after a restart. The app does not connect to web accounts, sync or upload.
As before, you can also copy a complete pet folder to this location and refresh the list to add it.
Folders that are missing required files or are still being copied are skipped.

Settings, custom pets and history from `%LOCALAPPDATA%\CodexDesktopPets`, used under the former name (Codex Desktop Pets),
are moved to the new folder automatically on the first start.

### Bubble design

Change the design in `Edit bubble design` under `Customize → Bubbles`. Start from a preset at the top (the default cream, sage, graphite, sky, paper note and pop, plus
themes provided by pets), then expand the Color / Shape & border / Decorations / Photos & images / Text & spacing groups to adjust items.
Choosing a preset keeps the photos, border images and stickers you added.

- **Background photo**: drawn clipped to the bubble's shape, with adjustable strength, focus and zoom. The photo is drawn over the bubble color at the chosen strength so the text stays readable.
- **Border image**: stretches an image in nine slices instead of the drawn border. You can set the corner size.
- **Stickers**: add up to three, each with a position and size. Clicking the preview on the right moves the selected sticker to that spot.
- Images can be PNG, WebP or JPEG (20 MB or less). On import, the orientation is corrected, the image is reduced to fit within 1024px and saved again, and metadata such as the photo's location is not kept.
- The preview can switch between `Short notification` and `Project card`, and is drawn the same way as real bubbles.

## Notification history and connections

The `Notification history` page in the settings window is where you can review notifications that passed by as bubbles and the task events of the current run.
From the top, it shows `Unread notifications` and `Recent activity` grouped by date.

- `Unread notifications` shows up to 5 items, and the rest expand with `Show N more`. Clicking a notification opens its details and
  marks it as read. `Mark all as read` marks all remaining notifications as read and also dismisses notification bubbles that were waiting.
- `Recent activity` can be filtered by `Notifications` (assistant notices), `Needs attention` (permission requests, needs attention and failures), `Status changes` (working, reviewing and so on)
  and `Completed`; only categories that actually have entries are shown as buttons. Needs-attention entries are kept separately, up to 50, so many status changes do not push them out. Only rows with a destination show `›`.
- Notifications, events and completions are kept only for the current run. Per-task token history is on `Usage`, and active conversations are on `Home`.
- Clearing the assistant notification history is in the `…` menu to the right of `Recent activity`.

### Connections and diagnostics tools

`Connections & diagnostics` in the settings window shows `Codex` and `Claude Code` side by side in the same layout. For each tool,
below a heading with its source-colored dot, come the current connection state, the enable switch and `Connection checks`. A tool that is off shows only its switch.
The connection state is connected (green), disconnected (gray), needs attention (warning) or settings unreadable (error),
and buttons such as `Connect hooks` or `Repair connection` appear on the status card only when something needs fixing. Turning a tool on and off is done with its switch.
For both tools, `Connection checks` starts with `Installation → Managed hooks → Last event received`; it then shows
hook trust and task log monitoring for Codex, and limits received and rejection/interruption detection for Claude Code.
The last error, local history storage and reminders are under `App status` below. Repair review for the tools that are on,
diagnostic ZIP export and the raw status are in `Advanced tools`. Every change shows what will change first and is applied only
when you click `Apply changes`.

The `Codex enabled` switch turns this app's Codex hooks and Codex usage on and off together.
Review the changes in the review window before applying; canceling leaves everything as it was. Other Codex hooks and feature settings, and Claude Code, are not changed.

Turning on `Claude Code enabled` adds only this app's hooks to the Claude Code user settings
(`~/.claude/settings.json`, or that folder under `CLAUDE_CONFIG_DIR` if set). Turning it off
restores only those hooks and this app's status line. Other settings and hooks are left alone, and the file is backed up in the same folder before any change.
Claude Code sessions that are already open must be restarted for the change to apply. The CLI and the VS Code extension both use the same
settings. Permission rejections and interrupted responses clear the working display within a few seconds; for sessions whose signals stop for other reasons,
the display is cleared after `Working status timeout` (default 10 minutes) or `Waiting status timeout` (default 30 minutes) in `Details`.
While a tool is running, the `Waiting status timeout` applies, and while a subagent is working, the parent conversation also stays working.
Claude Code's waiting state is a permission request, so it is shown as `Permission requested`. Claude Code sends no signal when you approve,
so this display stays until the approved tool finishes.

Turning on Claude Code's `Collect Claude Code limits` (turned on together with `Claude Code enabled`) receives the 5-hour and 7-day limits through the status line. If you had no
status line of your own, the app shows a default two-line status line, and in `Status line items` under `Details` you can choose the items to show (pet connection, IDE, model, context, 5-hour, 7-day),
their lines and order, color emphasis and the 5-hour reset time. Limits update only from Claude Code running in a terminal;
for using it from VS Code, see `How to use it in a terminal` in the same place. Support by tool and launch environment is described in
[Claude Code support](support-claude-code.en.md).

Snooze notifications is in `Customize → Bubbles`. Reminders are only ready to be received and displayed and are not yet connected to an external calendar system.

## Troubleshooting

### Task status does not appear

Check that you installed the `Pet + assistant` edition and that the tool's switch is on in `Connections & diagnostics`.
For Claude Code, restart sessions that were open before connecting and run a new task.
Follow the guidance in the Installation, Managed hooks and Last event received results of `Connection checks`.
Even if Codex is not detected, the pet works normally.

### Claude Code limits do not appear

Check that both `Claude Code enabled` and `Collect Claude Code limits` are on in `Connections & diagnostics`.
You must use Claude Code in a terminal with a supported claude.ai Pro or Max subscription, and limits update after the first response.
The VS Code extension panel alone does not update them. See [Claude Code limits](support-claude-code.en.md#limits).

### I can't click the pet

If clicking or dragging the pet clicks the window behind it instead, the pet is locked. Clear `Lock pet` in the tray menu,
press your `Pet lock shortcut`, or turn off `Lock pet` in `Customize → Pet → Behavior` in the settings window.
The usage widget is unlocked the same way (`Lock widget`). See [Locking the pet and widget](#locking-the-pet-and-widget) for details.

### The pet or its status looks wrong

- If a saved pet is damaged, the next working pet takes its place.
- If no pet can be read, you can try again or choose another folder in the recovery window.
- Leftover task status can be reset from the tray.
- Do not use development builds in `dist/` as your everyday installation.

For installation warnings, see [Installation and launch](#installation-and-launch); if the pet stays after you close the settings window, see [Quitting the app](#quitting-the-app);
for how data is handled during updates and uninstallation, see [Updates](#updates) and [Uninstalling and data](#uninstalling-and-data).
When reporting a problem, follow [Security and privacy](../SECURITY.en.md) and include the app and Windows versions and the steps to reproduce.

## Limitations

The conversation discovery, candidate analysis, task queue and automatic execution of earlier versions are neither shown nor started in any edition.
Task data that was already saved is kept as it is.

### Pet double-click action

In both editions, choose `Customize → Pet → Behavior → Double-click action`. The default is the settings home,
and every choice keeps the wave. The setting is kept when you switch characters or restart the app.
If you update from an earlier version, the settings home becomes the default instead of the former fixed Open Codex action.

`Open Codex` keeps the conversation you were viewing and restores and activates the frontmost Codex window; if there is no window,
it starts the registered app. It does not create a new conversation or automatically select the most recently active one.
If it fails, the settings home opens with an error message, and your choice is kept. `Wave only` opens no window.
`Open Claude Code (VS Code)` restores and activates the frontmost VS Code window where you use Claude Code. Open
Claude Code panels and terminals are left as they are, and no new conversation is created. If there is no VS Code window, it starts VS Code,
and VS Code restores your previous workspace. Only the official VS Code release is supported; if it fails, the settings home opens with an error message.
