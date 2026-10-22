# Privacy and storage

[한국어](privacy-and-storage.md) · [English](privacy-and-storage.en.md)

Last updated: 2026-10-19 · 0.15.7 / schema v9

## Location, contents and retention

Account switch checks use read-only responses from a new App Server. The pet never reads or copies the contents of
authentication files or tokens directly. Only a masked email in the form `a***@example.com` and the plan are passed to the screen;
neither the original email, the masked email nor the plan is newly stored in settings, the usage database,
logs or diagnostic files. An in-memory fingerprint of the email is used only to detect changes,
and the permanent history key remains a hash of the server's account identifier.

Project bubbles look up project and conversation metadata from a read-only App Server on a separate worker
thread. Conversation contents are not requested, and project names, conversation and parent IDs, working paths and
action targets are kept only in memory. These fields are not added to the existing hook events, SQLite or diagnostic
storage. Project events (20 status changes, 50 needs-attention items), the latest 100 completions, 50 general notifications and their read state are also managed only in memory,
and are cleared when the connection or account generation changes or when the app quits. Your calendar system is not connected yet.
The `Notification history` page in the settings window shows only these temporary rows and states that they disappear when the app quits. Database-backed per-task token history is shown on the `Usage` page. When uninstalling the whole app, you choose one of Keep my data (the interactive default), Delete history only or Delete everything. A silent uninstallation keeps the data. Removing only the assistant edition keeps the database history.

The user data root is `%LOCALAPPDATA%\WatchedKettle`. If `%LOCALAPPDATA%\CodexDesktopPets` from the former name (Codex Desktop Pets) exists, the whole folder is moved on the first start; if another process holds it, that run keeps using the old folder and the move is retried on the next start ([ADR 0005 (Korean)](decisions/0005-product-name-watched-kettle.md)). The database file names below are kept for compatibility, and the internal schema is v3.

All settings and history, including the positions and sizes of the pet, widget and settings window, are stored only in this data root and never written to the installation folder or the distributed bundle.
On the same PC, running from source and the installed app share this folder, so the installed app also starts where you last moved it. Bundle builds
are checked with `scripts.release_artifacts inspect` for settings, databases, logs, runtime files and build-PC paths (including the Python code inside the executables), and no ZIP is created if any are found.

| Location | Contents | Retention and deletion |
|---|---|---|
| `assistant-v1.sqlite3` and `-wal`, `-shm` | Account, conversation and turn hashes, UTC times, figures, models, status, quality, notification de-duplication state | New task history kept for 90 days per account, viewed 100 rows at a time; new activity samples 8 days / 2,500 rows |
| Earlier-version records in the database | Unverified past account data and figures | Excluded from normal totals and kept. Only records matching the current account ID can be viewed as earlier records |
| Database `.bak`, `.corrupt` and preserved companion files | Pre-migration backups and damaged originals | Never deleted automatically. Separate from clearing the current account's history; included in `Delete history only` when uninstalling the whole app |
| `usage-history-v1.json` / `.imported.bak` | Earlier JSON usage history | Imported after verification; the original is kept under a backup name |
| `pets/` | Names, manifests and sprites of pets you installed. File imports are saved again as lossless WebP that preserves the original size, transparency and pixels, with EXIF, ICC and text metadata removed. Web accounts, download URLs and original file paths are not kept in the new package, and nothing is uploaded or synced | Kept until you remove them |
| `bubble-elements/` | Bubble patterns, decorations, background photos, border images and stickers, with their names and metadata. Imported images are reoriented, reduced to 1024px or less and saved again as PNG/WebP, so metadata such as where and with which device a photo was taken (EXIF) is not kept | Kept until you remove them |
| `logs/app.log*` | Sanitized JSONL status and error diagnostics | 2 MiB per file, up to 3 rotated backups. Text from before the format change is kept as `.legacy` |
| `runtime/` and the project `.watched-kettle-runtime/` | Hook state files and the temporary notification queue | The queue's 60 seconds are checked when consumed. Entries can remain longer while the app is off |
| Windows QSettings | General and per-pet settings from earlier versions | Copied to the new settings file, and the original is kept. If migration fails, the original settings are used. Included in `Delete everything` when uninstalling the whole app. |
| `settings.ini` | Shared, pet and assistant settings since stage 10. 0.15.7 added the double-click action (`pet/doubleClickAction`), pet and widget locks and lock shortcuts (`pet/clickThrough`, `pet/clickThroughBubbles`, `pet/clickThroughHotkey`, `usage/widgetClickThrough`, `usage/widgetClickThroughHotkey`) and the last launched version (`updates/lastLaunchedVersion`). Shortcuts are stored only as combination strings such as `Ctrl+Alt+P` | Existing registry QSettings values are copied once on the first start. The registry original is not deleted, and the file is kept when switching editions or with the default uninstall option. |
| Claude Code task and limit records in the database (schema v8) | Session, turn and working folder hashes, times, results, model names, token counts; limits as 5-hour and 7-day usage percentages and reset times per Claude account hash. Conversation titles, folder names, prompts and paths are not stored; titles and folder names are kept only in memory while running | Task history 90 days, limit samples 8 days (the same value is stored at most once every 10 minutes). Only Claude Code history can be cleared from Usage → History, and Claude Code's transcript files are not touched |
| Codex project classification in the database (schema v9) | Account, conversation and project hashes, an explicit no-project marker, the fixed classification basis and the last check time. Names, titles, original IDs and working paths are not stored | Kept while the usage records that refer to it are kept. Included when clearing an account's usage history, and cleaned up periodically when no longer referenced. Signing out, switching accounts and reconnecting reset only memory |
| `runtime/claude-code-status-line.json` | Your status line setting from before the Claude Code limit connection | Deleted when the limit connection is turned off or the app's removal tool restores the original setting |
| Hooks and config in Codex home, hooks and status line in Claude Code's `settings.json`, Windows startup | Connection settings you installed or registered | Only the managed entries are changed by the app's install and uninstall actions. Backed up as `<file name>.backup-<time>` in the same folder before changes |
| `Language` in the registry key `HKCU\Software\WatchedKettle` | The language chosen in the installer (`ko`/`en`). The app does not read it yet; it will be used as the first-start default when the app supports multiple languages | Written by the installer and always deleted on uninstall |

Retention cleanup runs after saving and during periodic maintenance while the app runs. Queries do not show expired new records, but physical deletion does not run while the app is off. Earlier records are excluded from the retention cleanup of new normal records.

Task history is not automatically trimmed above 500 rows. Retention and the amount shown on screen are separate; search and sort apply to all retained records of the current account, and at most 100 rows are passed to the screen. Database rows already deleted under an earlier policy are not recreated from the original logs alone. Recovery of unmeasured records reads 200 rows at a time from the database regardless of the screen's page, moving to the next batch once a batch has been checked. Switching accounts or clearing history cancels page queries and recovery passes.

Images prepared for a pet import and their temporary identifiers are kept in memory only, for at most one item and 10 minutes, and are discarded on cancel, a new selection,
hiding the settings window or closing the connection. On Add, the package is completed in a temporary folder in the data root, then
published to `pets/`, and the temporary folder is cleaned up after success or failure. `pet-import-*`
temporary folders left by a forced exit are excluded from the pet list. The original downloaded file is never changed.

## Pet manager and trash

The app data folder's `pet-trash/<temporary ID>/` holds the user pet package and `record.json`.
The record stores the pet ID, name, original folder name, deletion time, visibility, previous order and operation state.
Instead of a full original path it uses the folder name inside the user pets folder, and this record is kept apart from the activity and usage databases.
A pet's own customization settings are kept so it can be restored, and are deleted when you confirm permanent deletion.
The trash never expires automatically. When uninstalling, Keep my data and Delete history only keep your pets and the trash, and Delete everything deletes them too.

The intent to move, restore or delete is recorded first, and unfinished file operations are recovered at startup. Unreadable or conflicting data is kept.
The progress and last result of a batch operation are kept only in the current run's memory, and unprocessed items are not run automatically after a restart.
File operations are limited to the user pets folder and the app's own trash, and externally linked folders and bundled pets are protected.
The names, paths and contents in these management records are not added to general logs or diagnostics.

## Usage accounts and measurement

The per-project usage view first restores the database classification of the confirmed account, then updates it with the read-only `project/list`, `thread/list` and `thread/read(includeTurns=false)` and the desktop app's project link information. Only the hash relationships between accounts, conversations and projects, the check time and the classification basis are stored. Actual project names and conversation titles are kept only in memory for the current account and connection generation, and prompt previews are never used as titles. Right after a restart the classification is restored, but names and titles are looked up again. Resetting an account or quitting clears the name cache and keeps the per-account classification; clearing usage history also deletes that classification. Project and conversation summaries aggregate all retained history, but only 100 projects, 100 conversations of the selected project and 100 tasks of the selected conversation are passed to the screen. The project sort mode and custom order store only project keys in QSettings per account hash. Names and titles are not included in this setting, and Codex's own project order is not changed.

- The permanent account key is a hash of the `accountId` provided by the App Server. The email is used only to detect an account change in the current connection and is never used as a storage key.
- Without an account ID, limits can still be shown, but permanent history queries, saving and deletion are held back. Signing out, switching accounts and reconnecting separate earlier observations and late responses.
- Hashes are pseudonymous identifiers that reduce exposure of the original identifiers; they do not guarantee full anonymization.
- Per-task tokens are calculated from this device's Codex logs by confirming the task start and completion and the cumulative token values. Records with reversed cumulative values, missing logs or unclear ownership are left as unmeasurable. Conversation titles, prompts and raw logs are not stored. Per-task credits and USD are not provided in the logs and are never made up.
- Split logs are linked by verifying the header owner and the byte and sequence boundaries of the previous file. Recovery updates only unmeasurable rows that match the current account's existing conversation and task hashes, and does not fill in data when the account attribution is ambiguous. Progress is kept only in memory, and the last check reason and the original collection reason are stored together in the existing quality reason field. The original logs and the database schema are not changed. Switching accounts, signing out and clearing history cancel recovery and caches, and past activity events are not delivered again.
- Recovery changes are saved in batches at most every 200 ms after the account and run generation are confirmed. The same verdict is not written again, and the in-memory cache of verified log boundaries, cumulative values and task identifiers is limited to 1,024 boundaries. New-file discovery is separate from content checks, so unrelated conversation logs are not parsed repeatedly. Only changes held during account verification are reapplied to that generation, and switching accounts or clearing history also empties the pending batch.
- Original account, conversation and turn IDs, prompts, Codex conversation titles, commands, transcripts and tool output are not stored in the usage database, logs or diagnostics. The diagnostic ZIP does not include the database contents.
- `app.log` is schema 1 JSONL. Each line contains the UTC time, level, run_id, component and event,
  with only limited diagnostic fields such as status, error codes and durations added. Authentication files, tokens, emails, account IDs,
  full paths, App Server response bodies and stderr are not stored.
- The titles of your calendar reminders can be included in the display and the temporary delivery queue. User pet and decoration metadata and path settings in QSettings are distinct from the usage database's policy of not storing original contents.

## Failures and deletion

A database from an unsupported future version is not changed. For a damaged database, a new one is created only if the original was preserved successfully; a partially created database that cannot be recovered safely is kept, and the app runs in memory mode. In this mode, history is not kept after a restart.

Clearing history on the Usage page applies only to the confirmed current account, and completion is shown after the storage operation succeeds. Other accounts' data, separate backups and user pets are not deleted with it.

Uninstalling the whole app removes the managed hooks and this app's startup entry. `Keep my data`, the default for an interactive uninstall, and a silent uninstall keep your data. `Delete history only` (shown only when assistant history files exist) deletes the assistant database, its companion files and backups, earlier usage files, app logs and temporary events, and keeps `settings.ini` and your pets and decorations. `Delete everything` also deletes the user data folder and the earlier QSettings. The uninstaller closes the running app before deleting anything, and if another program has a data file open, it deletes nothing and stops. If there is no user data, the data options are not shown. Codex's own conversations and settings and other hooks are not deleted. Separate project runtime folders are outside the app data folder, so they are not searched or deleted automatically.

## Read scope and feature control

JSONL status observation and the usage assistant connect to the local Codex, and the status and usage features can be checked and turned off on `Connections & diagnostics` and `Usage` in the settings window. Codex home is `CODEX_HOME` if set, otherwise `~/.codex`. Existing external hook settings are not migrated automatically just because the path changed.

The Claude Code integration (stage 13) receives only the identifiers and types needed to determine status from hook events. Claude Code sends no hook on permission rejection or interrupted responses, so, only for working sessions, the app checks just the types (entry type, content item type, meta and compaction markers) of lines newly added to the transcript (`projects/*/<session ID>.jsonl` under `CLAUDE_CONFIG_DIR` or `~/.claude`). Lines over 64 KiB are not parsed. The original prompts, responses and tool results are not kept in memory or written to logs, the database or diagnostics, and monitoring stops when the turn ends.
Hook events also send the session's launch environment (one of `vscode-panel`, `vscode-terminal` or `terminal`), which the app keeps only in memory while running. Only when you click `Open window` for a conversation running in a VS Code terminal does the app read the folder the session started in from the start of that session's transcript (64 KiB; if it is not there, the newest folder from the last 64 KiB) to build the address passed to VS Code; the path is not kept or logged.

Conversation reading starts only after you explicitly turn it on. For each project, explicit plans are read from the latest 10 conversations, and past conversations are read when you select them. Original text is never sent to an external analysis model. In supported storage, the text is processed page by page, and only candidates and hashes are kept. Unregistered candidates are removed from memory when they leave the recent range and the current past page. Tasks you saved are kept separately.

Schema v7 adds candidate link keys and encrypted completion summaries to the task ledger of schema v6. Instructions, sources, titles and paths are encrypted with per-user DPAPI, and access is separated per account. Candidate link and exclusion keys use an HMAC with a secret key. Completion summaries keep only the title, target conversation, project, completion time, verdict and condition description, and the full instruction is deleted. Completion records are trimmed to 30 days / 500 items and exclusion records to 30 days. Items in progress or awaiting recovery are not deleted by this cleanup.

Before migrating to v7, a consistent database backup is made. Pending tasks that never ran are moved to drafts for review because of a change in how source versions are calculated, and the original instruction is kept. Completion contents already deleted in earlier versions are not restored. Old exclusion records may lack project information, so they are released with `Restore excluded candidates for all projects`.

Automatic execution uses a separate shared Desktop connection. Nothing runs until the account, execution observation, ownership and approval delivery reviews are complete. A list or log estimate from a separate read server is not treated as the execution state of the whole Desktop app.

## Network and installer

This app has no server of its own and never sends usage data out. Codex usage and account checks are requested from the local Codex App Server process
over standard input and output. How far that process communicates externally with your Codex sign-in is up to Codex.

The app itself connects to the internet in two cases only: update checks and install commands in Import pet. Updates are checked when you click
`Check for updates` in `App settings → Version & updates` in the settings window,
and, in an installed copy with `Check for updates automatically` (on by default), once a day (starting 1 minute after the app starts, when 24 hours have passed
since the last answer; 3 hours later after a failure). Running from source or a ZIP never checks on its own. Each check sends a single
`User-Agent: WatchedKettle-update-check` request to the GitHub Releases address built into the build (`api.github.com`); no account, device or usage
history is sent. Automatic checks keep only the time of the last answer and the version announced in the settings (`[updates]`) (the last launched version is kept in the same place so the post-update bubble appears only once), and when a new version is found,
the app only announces it and does not download it. Since 0.15.10, when `Install updates automatically` (on by default, `updates/autoInstall`) is also on,
the app downloads the update index and the zip of changed files for the version an automatic check finds, in the same way as the partial update path below,
without a click, prepares it, and applies it at the next start. When the installer is needed, it is not downloaded; the app only announces the version
([ADR 0009 (Korean)](decisions/0009-automatic-updates.md)). As with any HTTPS request, GitHub receives your IP address. From the response, only the latest version tag and the Release page address
are checked, and they are not stored. If there is no Release yet, GitHub returns 404 and the app only reports that. Clicking `View release notes`
opens the Release page in your browser. Since 0.15.5, checks go to the Releases of `leewb2280/watched-kettle-updates`, a public repository
that holds only update files, and `View release notes` opens the same version's Release in the main repository `leewb2280/watched-kettle`
([ADR 0008 (Korean)](decisions/0008-update-repository.md)). Installed copies up to 0.15.4 check the main repository's Releases. Both repositories use the same
GitHub addresses, so the information sent and the servers contacted are the same.

When a new version exists and you click `Update`, only then are the installer and its `.sha256` checksum file from the same Release downloaded from `github.com` and GitHub's attachment
servers (`objects.githubusercontent.com`, `release-assets.githubusercontent.com`) with the same `User-Agent`. No other
information is sent. The installer is downloaded to `%LOCALAPPDATA%\WatchedKettle\updates`. If the checksum does not match, or the download is canceled or fails, it is
deleted immediately. An installer that was started is deleted on the next start, and on uninstall this folder is deleted even if you choose `Keep my data`.
When checking, an installed copy also downloads the same Release's update index (`WatchedKettle-<version>-update.json` and `.sha256`) the same way,
and when possible downloads a zip containing only the changed files instead of the installer ([ADR 0007 (Korean)](decisions/0007-partial-updates.md)). The zip goes to the same `updates`
folder, and the new program files are prepared in `runtime\<edition>.next` in the installation folder (unchanged files are hard links, so they take almost no extra
disk space). When the app quits, the launcher swaps the folders, and the previous program folder (`runtime\<edition>.old`) and the downloaded zip are deleted on the next start.
The information sent in this process is the same as when downloading the installer. Only development test
builds (`build_windows.ps1 -UpdateTestPort`) send the same requests to a test server at `127.0.0.1` on the same PC instead of GitHub, and this address is not included in public
release builds.

Only when you click `Download` for an `Install command` in Import pet does the app download a pet from a public pet service, using the pet ID in the pasted command.
CodexPetDB uses `codexpetdb.com` (catalog) and `cdn.codexpetdb.com` (ZIP), and Pets Codex uses `api.github.com` (the latest commit of its public repository) and
`raw.githubusercontent.com` (manifest and images). Only these four HTTPS addresses are allowed, redirects are not followed, and nothing but the address containing the pet ID
and `User-Agent: WatchedKettle-PetImport` is sent; no account, device or usage history. As with any HTTPS request, each service receives your IP
address. The command is never run. A downloaded ZIP stays in the system temporary folder only while it is being verified and is then deleted, and only the verified assets are saved as a
new package in the user pets folder. There are no automatic checks or retries. The `File or folder` and `Pets installed in Codex` inputs do not use the network.
The repository and release notes links on `About` in the settings window are opened by your default browser, not by the app.

The Windows installer installs and removes this app's managed hooks only for the tools you chose, using the `--configure-integrations` mode that shows no app window,
and saves each tool's enable switch in `settings.ini`. Tools you did not choose and other hooks and tool settings are not changed.

## Tools not in use

Codex and Claude Code each have an enable switch ([ADR 0006 (Korean)](decisions/0006-tool-activation-single-bundle.md)). The files of a tool that is off
are not read. Turning Codex off stops tailing its logs (`sessions`, `archived_sessions`), checking `auth.json`, running `codex app-server`,
reading `.codex-global-state.json`, and reading hooks and `config.toml` for diagnostics. Turning Claude Code off stops reading transcripts and
checking the status of `settings.json`. The Connections & diagnostics page only checks whether the tool's folder exists. The moment a tool is turned off, its active
cards and pet state are cleared, and events are discarded even if the hooks this app added remain. History already saved is not deleted.

## Separating device observations

Only numbers and status from the JSONL `sessions` and `archived_sessions` are read. Local logs carry no proof of account ownership, so token and limit observations are **this device's** records. They can include activity from several Codex accounts. Account limit charts and notifications use only App Server responses and never add device figures.

In schema v5, `device_token_events` stores only event and session hashes, UTC times and positive token differences, and `device_quota_samples` only event hashes, limit windows, UTC times, usage percentages and reset times. Neither table has an account column. Each table is limited to 8 days / 20,000 rows, trimmed after saving and during maintenance, and expired rows are excluded when reading as well. The original logs are never modified or deleted.

Local tokens and limit samples from v4 are kept as earlier records whose ownership and measurement reliability cannot be confirmed. They are not promoted automatically to account views or current totals, and up to 500 can be viewed among the device's earlier records. Earlier records are excluded from automatic retention cleanup. New account limit samples are marked `source=app_server`, and v4 limits `source=legacy_unverified`.

`Clear current account history` (choose Codex on the usage `History` tab, then `Clear history`) deletes only the confirmed account's server observations and task history. `Clear device observations` deletes the new device records together with the v4 earlier records above, and keeps the account history. The device clear watermark is the time used to prevent re-import, migrated as the maximum of the earlier per-account watermarks. Separate databases, WAL files and backups, the original JSONL, QSettings and hooks are not removed by this deletion. Turning the feature off stops saving new observations and keeps the existing records.

A consistent backup is made before migration, and the DDL and version record are handled in a single transaction. A database from a future version is opened in a restricted mode that does not change the original. Backups are never deleted automatically.
