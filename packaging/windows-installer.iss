; Local pre-release candidate. Stable AppId preserves upgrade identity.
#if Ver < EncodeVer(6, 7, 0)
  #error Inno Setup 6.7 or newer is required (windows11 wizard style, PNG wizard images)
#endif
#ifndef AppVersion
  #error AppVersion must be supplied by build_installer.ps1
#endif
#ifndef PetOnlyBundleRoot
  #error PetOnlyBundleRoot must be supplied by build_installer.ps1
#endif
#ifndef AssistantBundleRoot
  #error AssistantBundleRoot must be supplied by build_installer.ps1
#endif
#ifndef ArtifactDir
  #error ArtifactDir must be supplied by build_installer.ps1
#endif
#ifndef LauncherExe
  #error LauncherExe must be supplied by build_installer.ps1
#endif
#ifndef WizardImagesRoot
  #error WizardImagesRoot must be supplied by build_installer.ps1
#endif
#ifndef RuntimeBytes
  #error RuntimeBytes must be supplied by build_installer.ps1
#endif
; PrivatePetsRoot (optional) makes the invitation installer: the same Public
; bundles plus the original character pets, never published on Releases.
#ifdef PrivatePetsRoot
  #define InstallerKind "private-pets"
#else
  #define InstallerKind "public"
#endif
; UpdateTest marks bundles whose update check reads scripts/serve_update_test.py
; on 127.0.0.1 (build_windows.ps1 -UpdateTestPort); never published either.
#ifdef UpdateTest
  #define InstallerKind InstallerKind + "-update-test"
#endif
; ADR 0005: Private Beta builds used the legacy names below; upgrades migrate them.
#define AppId "WatchedKettle"
#define AppExe "WatchedKettle.exe"
#define LegacyAppId "CodexDesktopPets"
#define LegacyAppExe "CodexDesktopPets.exe"
; Every executable the app runs from {app}, under both names.
#define AppProcesses AppExe + ",WatchedKettleSettings.exe,WatchedKettleHookBridge.exe," + LegacyAppExe + ",CodexPetsSettings.exe,CodexPetsHookBridge.exe"
#define Images WizardImagesRoot

[Setup]
AppId={{74FC68D2-EB57-452A-A11F-7787F5DF8B72}
AppName=Watched Kettle
AppVersion={#AppVersion}
AppPublisher=Watched Kettle contributors
VersionInfoVersion={#AppVersion}
VersionInfoProductName=Watched Kettle
VersionInfoDescription=Watched Kettle Setup
UninstallDisplayName=Watched Kettle
; The launcher keeps one path for every edition, so its icon stays valid.
UninstallDisplayIcon={app}\{#AppExe}
SetupIconFile={#SourcePath}..\assets\app_icon.ico
; The runtime files are conditional, so the space estimate leaves them out.
ExtraDiskSpaceRequired={#RuntimeBytes}
; Existing Private Beta installs keep their folder through UsePreviousAppDir.
DefaultDirName={localappdata}\Programs\{#AppId}
PrivilegesRequired=lowest
ArchitecturesAllowed=x64compatible
ArchitecturesInstallIn64BitMode=x64compatible
MinVersion=10.0
OutputDir={#ArtifactDir}
OutputBaseFilename={#AppId}-{#AppVersion}-{#InstallerKind}-unsigned-setup
Compression=lzma2
SolidCompression=yes
WizardStyle=modern dynamic windows11
; Transparent PNGs per DPI scale (scripts/render_installer_images.py).
WizardImageFile={#Images}\wizard-large-100.png,{#Images}\wizard-large-125.png,{#Images}\wizard-large-150.png,{#Images}\wizard-large-175.png,{#Images}\wizard-large-200.png,{#Images}\wizard-large-250.png
WizardSmallImageFile={#Images}\wizard-small-100.png,{#Images}\wizard-small-125.png,{#Images}\wizard-small-150.png,{#Images}\wizard-small-175.png,{#Images}\wizard-small-200.png,{#Images}\wizard-small-250.png
DisableProgramGroupPage=yes
AlwaysShowDirOnReadyPage=yes
ShowLanguageDialog=yes
LanguageDetectionMethod=uilanguage
CloseApplications=yes
; PrepareToInstall already asked the app to quit; this catches what remains.
CloseApplicationsFilter={#AppProcesses}
RestartApplications=no
SetupLogging=yes
UsePreviousTasks=yes
; Uninstall asks about this app's user data; Codex's own data is never deleted.

[Languages]
; Without a matching Windows display language, the first entry is the default.
Name: "en"; MessagesFile: "compiler:Default.isl"
Name: "ko"; MessagesFile: "compiler:Languages\Korean.isl"

[Messages]
en.WizardSelectTasks=Shortcuts and Startup
en.SelectTasksDesc=Choose how you want to start Watched Kettle.
en.SelectTasksLabel2=Choose the options you want, then click Next.
en.ConfirmUninstall=Remove %1 from this computer?
en.FinishedLabel=Setup has finished installing [name]. You can start it any time from the Start menu.
ko.WizardSelectDir=설치 위치
ko.SelectDirDesc=[name]을(를) 어디에 설치할까요?
ko.WizardSelectTasks=바로 가기와 자동 시작
ko.SelectTasksDesc=Watched Kettle을 어떻게 시작할지 고르세요.
ko.SelectTasksLabel2=원하는 항목을 고르고 다음을 누르세요.
ko.ReadyLabel1=[name]을(를) 설치할 준비가 되었습니다.
ko.ReadyLabel2a=아래 내용을 확인하고 설치를 누르세요. 바꾸려면 뒤로를 누릅니다.
ko.ConfirmUninstall=%1을(를) 이 컴퓨터에서 제거할까요?
ko.UninstalledAll=%1을(를) 제거했습니다.
ko.FinishedHeadingLabel=[name] 설치 완료
ko.FinishedLabelNoIcons=[name] 설치를 마쳤습니다.
ko.FinishedLabel=[name] 설치를 마쳤습니다. 시작 메뉴의 바로 가기로 언제든 실행할 수 있습니다.

[CustomMessages]
en.ShortcutComment=Desktop pet that watches your coding agents
en.EditionPageCaption=Choose What to Install
en.EditionPageDescription=Choose how you want to use Watched Kettle.
en.EditionPetOnly=Pet only
en.EditionPetOnlyNote=Installs the desktop pet and its speech bubbles. Other tools' settings stay untouched.
en.EditionAssistant=Pet + assistant
en.EditionAssistantNote=The pet also reports Codex and Claude Code task status, notifications and usage.%nYou choose the tools on the next page.
en.CurrentPetOnly=Currently installed: pet only.
en.CurrentAssistant=Currently installed: pet + assistant.
en.CurrentBoth=Both editions were found. Choose the one to keep.
en.CurrentLegacy=An earlier Codex Desktop Pets installation with the assistant was found.
en.RemoveAssistantWarning=Switching to pet only removes the Codex and Claude Code hooks this app added. Assistant history is kept.
en.ToolsPageCaption=Connect Your Tools
en.ToolsPageDescription=Choose the coding tools the pet should watch.
en.ToolConnected=Connected now.
en.ToolNotConnected=Not connected now.
en.ToolFound=Its settings folder was found on this PC.
en.ToolNotFound=Its settings folder was not found on this PC.
en.ToolsNewNote=This app adds its hooks only to the tools you choose. You can change this later on the app's connection page.
en.ToolsUpgradeNote=Only your changes are applied. Unchecking a tool removes only the hooks this app added.
en.ReadyEdition=Edition:
en.ReadyTools=Connected tools:
en.ReadyNoTools=None
en.LegacyHookMigrateFailed=Could not move the Codex hook from the previous name to the new program. Repair it on the app's connection page.
en.IntegrationsFailed=Some Codex or Claude Code connection settings could not be applied. Check the app's connection and diagnostics page.
en.HookRemoveFailed=Could not remove the Codex and Claude Code hooks this app added, so the assistant files were kept. Run Setup again, or check each tool's hook settings.
en.UninstallDataCaption=Uninstall Watched Kettle
en.UninstallDataTitle=What should happen to your Watched Kettle data?
en.UninstallKeep=Keep my data (recommended)
en.UninstallKeepNote=Settings, your pets and history stay. Reinstalling picks up where you left off.
en.UninstallRecords=Delete history only
en.UninstallRecordsNote=Deletes assistant task history, usage history and logs. Settings and your pets stay.
en.UninstallAll=Delete everything
en.UninstallAllNote=Deletes settings, your pets and all history. This cannot be undone.
en.UninstallInfoHooks=Whatever you choose, the Codex and Claude Code hooks and the startup entry this app added are removed. Each tool's own conversations and settings are not touched.
en.UninstallInfoStartup=Whatever you choose, the startup entry this app added is removed.
en.UninstallDataFolder=Data folder: %1
en.UninstallButton=Uninstall
en.UninstallAllButton=Delete all and uninstall
en.UnsafeDataRoot=Uninstall stopped because the user data folder could not be verified safely: %1
en.HookFileUnreadable=Could not read the Codex hook file: %1
en.ClaudeSettingsUnreadable=Could not read the Claude Code settings file: %1
en.StartupRemoveFailed=Could not remove the app's startup entry.
en.AppStillRunning=Watched Kettle did not close on its own. Force it to close and continue?
en.AppRunningAbort=Watched Kettle is still running. Quit it from the tray menu, then try again.
en.HookRemoveAbort=Uninstall stopped because the Codex and Claude Code hooks this app manages could not be removed.
en.HookRemainAbort=Uninstall stopped because hooks this app manages are still present in Codex or Claude Code.
en.DataLinkedAbort=Deleting everything stopped because the app data contains a link to another folder: %1
en.DataInUseAbort=Deleting everything stopped because another program is using the app data. Nothing was deleted. Close that program and try again: %1
en.DataLeftover=Some app data could not be deleted. You can delete this folder yourself: %1
en.LogsLinkedAbort=Deleting stopped because the app logs or temporary events contain a link to another folder.
en.RecordsDeleteFailed=Could not delete all assistant history files: %1
en.LogsDeleteFailed=Could not delete the app logs: %1
en.RuntimeDeleteFailed=Could not delete the app's temporary events: %1
en.LegacySettingsDeleteFailed=Could not delete the previous app settings.
ko.ShortcutComment=코딩 에이전트를 지켜보는 데스크톱 펫
ko.EditionPageCaption=설치 구성
ko.EditionPageDescription=Watched Kettle을 어떻게 쓸지 고르세요.
ko.EditionPetOnly=펫만
ko.EditionPetOnlyNote=데스크톱 펫과 말풍선만 설치합니다. 다른 도구의 설정은 건드리지 않습니다.
ko.EditionAssistant=펫 + 비서
ko.EditionAssistantNote=Codex·Claude Code 작업 상태와 알림, 사용량을 펫이 알려 줍니다.%n다음 화면에서 연결할 도구를 고릅니다.
ko.CurrentPetOnly=지금은 펫만 설치되어 있습니다.
ko.CurrentAssistant=지금은 펫 + 비서가 설치되어 있습니다.
ko.CurrentBoth=두 구성이 모두 발견됐습니다. 남길 구성을 고르세요.
ko.CurrentLegacy=이전 이름(Codex Desktop Pets)의 비서 구성이 설치되어 있습니다.
ko.RemoveAssistantWarning=펫만으로 바꾸면 이 앱이 추가한 Codex·Claude Code hook을 제거합니다. 비서 기록은 지우지 않습니다.
ko.ToolsPageCaption=도구 연결
ko.ToolsPageDescription=펫이 지켜볼 코딩 도구를 고르세요.
ko.ToolConnected=지금 연결되어 있습니다.
ko.ToolNotConnected=지금은 연결되어 있지 않습니다.
ko.ToolFound=이 PC에서 설정 폴더를 찾았습니다.
ko.ToolNotFound=이 PC에서 설정 폴더를 찾지 못했습니다.
ko.ToolsNewNote=고른 도구에만 이 앱의 hook을 추가합니다. 나중에 앱의 연결 화면에서 바꿀 수 있습니다.
ko.ToolsUpgradeNote=바꾼 항목만 적용합니다. 체크를 해제하면 이 앱이 추가한 hook만 제거합니다.
ko.ReadyEdition=설치 구성:
ko.ReadyTools=연결할 도구:
ko.ReadyNoTools=없음
ko.LegacyHookMigrateFailed=이전 이름의 Codex hook을 새 실행 파일로 옮기지 못했습니다. 앱의 연결 화면에서 hook을 복구해 주세요.
ko.IntegrationsFailed=Codex·Claude Code 연동 설정 일부를 적용하지 못했습니다. 앱의 연결·진단 화면에서 확인해 주세요.
ko.HookRemoveFailed=이 앱이 추가한 Codex·Claude Code hook을 제거하지 못해 비서 파일을 남겨 두었습니다. 설치 프로그램을 다시 실행하거나 각 도구의 hook 설정을 확인해 주세요.
ko.UninstallDataCaption=Watched Kettle 제거
ko.UninstallDataTitle=Watched Kettle 데이터를 어떻게 할까요?
ko.UninstallKeep=데이터 유지 (권장)
ko.UninstallKeepNote=설정·사용자 펫·기록을 남깁니다. 다시 설치하면 그대로 이어서 씁니다.
ko.UninstallRecords=기록만 삭제
ko.UninstallRecordsNote=비서 작업 기록·사용량 기록·로그를 지웁니다. 설정과 사용자 펫은 남깁니다.
ko.UninstallAll=모두 삭제
ko.UninstallAllNote=설정·사용자 펫·기록을 모두 지웁니다. 되돌릴 수 없습니다.
ko.UninstallInfoHooks=어떤 선택이든 이 앱이 추가한 Codex·Claude Code hook과 자동 시작 등록은 해제합니다. 각 도구의 대화와 설정은 건드리지 않습니다.
ko.UninstallInfoStartup=어떤 선택이든 이 앱의 자동 시작 등록은 해제합니다.
ko.UninstallDataFolder=데이터 위치: %1
ko.UninstallButton=제거
ko.UninstallAllButton=모두 삭제하고 제거
ko.UnsafeDataRoot=사용자 데이터 경로를 안전하게 확인할 수 없어 제거를 중단했습니다: %1
ko.HookFileUnreadable=Codex hook 파일을 확인하지 못했습니다: %1
ko.ClaudeSettingsUnreadable=Claude Code 설정 파일을 확인하지 못했습니다: %1
ko.StartupRemoveFailed=앱 자동 시작 등록을 해제하지 못했습니다.
ko.AppStillRunning=Watched Kettle이 스스로 종료되지 않았습니다. 강제로 종료하고 계속할까요?
ko.AppRunningAbort=Watched Kettle이 아직 실행 중입니다. 트레이 메뉴에서 종료한 뒤 다시 시도해 주세요.
ko.HookRemoveAbort=관리 중인 Codex·Claude Code hook을 해제하지 못해 제거를 중단했습니다.
ko.HookRemainAbort=관리 중인 Codex·Claude Code hook이 남아 있어 제거를 중단했습니다.
ko.DataLinkedAbort=앱 데이터에 연결된 외부 폴더가 있어 전체 삭제를 중단했습니다: %1
ko.DataInUseAbort=다른 프로그램이 앱 데이터를 사용 중이라 전체 삭제를 중단했습니다. 아무것도 지우지 않았습니다. 그 프로그램을 닫고 다시 시도해 주세요: %1
ko.DataLeftover=앱 데이터 일부를 지우지 못했습니다. 이 폴더는 직접 지워도 됩니다: %1
ko.LogsLinkedAbort=앱 로그 또는 임시 이벤트에 연결된 외부 폴더가 있어 삭제를 중단했습니다.
ko.RecordsDeleteFailed=비서 기록 파일을 모두 삭제하지 못했습니다: %1
ko.LogsDeleteFailed=앱 로그를 삭제하지 못했습니다: %1
ko.RuntimeDeleteFailed=앱 임시 이벤트를 삭제하지 못했습니다: %1
ko.LegacySettingsDeleteFailed=이전 앱 설정을 삭제하지 못했습니다.

[Tasks]
Name: "desktopicon"; Description: "{cm:CreateDesktopIcon}"; GroupDescription: "{cm:AdditionalIcons}"; Flags: unchecked
; The wizard checks this from the current Run entry and applies only a change.
Name: "startup"; Description: "{cm:AutoStartProgram,Watched Kettle}"; GroupDescription: "{cm:AutoStartProgramGroupDescription}"; Flags: unchecked

[Files]
Source: "{#LauncherExe}"; DestDir: "{app}"; DestName: "{#AppExe}"; Flags: ignoreversion
Source: "{#PetOnlyBundleRoot}\*"; DestDir: "{app}\runtime\pet-only"; Flags: ignoreversion recursesubdirs createallsubdirs; Check: InstallPetOnly
Source: "{#AssistantBundleRoot}\*"; DestDir: "{app}\runtime\pet-assistant"; Flags: ignoreversion recursesubdirs createallsubdirs; Check: InstallAssistant
; Stage the new helper only when switching an older assistant installation to pet-only.
Source: "{#AssistantBundleRoot}\*"; DestDir: "{app}\hook-cleanup-helper"; Flags: ignoreversion recursesubdirs createallsubdirs; Check: NeedHookCleanup
#ifdef PrivatePetsRoot
; User pet folder, so a later public installer keeps them. Like other custom
; pets, only "delete everything" removes them.
Source: "{#PrivatePetsRoot}\*"; DestDir: "{code:UserPetsRoot}"; Flags: ignoreversion recursesubdirs createallsubdirs uninsneveruninstall
#endif

[InstallDelete]
; Earlier builds put one shortcut in a Start menu folder of its own.
Type: files; Name: "{autoprograms}\Watched Kettle\Watched Kettle.lnk"
Type: dirifempty; Name: "{autoprograms}\Watched Kettle"
Type: files; Name: "{autoprograms}\Codex Desktop Pets\Codex Desktop Pets.lnk"
Type: dirifempty; Name: "{autoprograms}\Codex Desktop Pets"
Type: files; Name: "{autodesktop}\Watched Kettle.lnk"; Tasks: not desktopicon

[Icons]
Name: "{autoprograms}\Watched Kettle"; Filename: "{app}\{#AppExe}"; Comment: "{cm:ShortcutComment}"
Name: "{autodesktop}\Watched Kettle"; Filename: "{app}\{#AppExe}"; Comment: "{cm:ShortcutComment}"; Tasks: desktopicon

[Registry]
; Setup language (en/ko) for the app's future language default. Not read yet.
Root: HKCU; Subkey: "Software\{#AppId}"; ValueType: string; ValueName: "Language"; ValueData: "{language}"; Flags: uninsdeletevalue uninsdeletekeyifempty

[UninstallDelete]
Type: files; Name: "{app}\runtime\edition"

[Run]
Filename: "{app}\{#AppExe}"; Description: "{cm:LaunchProgram,Watched Kettle}"; Flags: nowait postinstall skipifsilent
; The app's own update runs Setup with /VERYSILENT /RELAUNCH=1 and has already quit.
Filename: "{app}\{#AppExe}"; Flags: nowait; Check: RelaunchRequested

[Code]
const
  KeepUserData = 0;
  RemoveRecords = 1;
  RemoveAllUserData = 2;
  ReparsePointAttribute = $400;
  RunKey = 'Software\Microsoft\Windows\CurrentVersion\Run';
  // SingleInstanceCoordinator's endpoint (watched_kettle/integrations/single_instance.py).
  InstancePipe = '\\.\pipe\watched-kettle-instance-v1';
  GenericRead = $80000000;
  GenericWrite = $40000000;
  OpenExisting = 3;
  // Polls every 250 ms: 10 s for a normal quit, 5 s after a forced one.
  QuitWaitPolls = 40;
  ForceWaitPolls = 20;

type
  TProcessIds = array of Integer;

var
  // Install state of the chosen folder, read once before files change.
  DetectedDir: String;
  HadPetRuntime: Boolean;
  HadAssistantRuntime: Boolean;
  // Hook markers for an existing assistant, otherwise whether the tool's
  // config folder exists.
  InitialCodex: Boolean;
  InitialClaudeCode: Boolean;
  InitialStartup: Boolean;
  // Current choices. The pages update them; silent setup keeps the detected
  // state unless /EDITION, /CODEX or /CLAUDECODE says otherwise.
  ChooseAssistant: Boolean;
  ChooseCodex: Boolean;
  ChooseClaudeCode: Boolean;
  StartupTaskShown: Boolean;

  EditionPage: TWizardPage;
  CurrentEditionLabel: TNewStaticText;
  PetOnlyOption: TNewRadioButton;
  PetOnlyNote: TNewStaticText;
  AssistantOption: TNewRadioButton;
  AssistantNote: TNewStaticText;
  RemoveAssistantLabel: TNewStaticText;

  ToolsPage: TWizardPage;
  CodexCheck: TNewCheckBox;
  CodexStateLabel: TNewStaticText;
  ClaudeCodeCheck: TNewCheckBox;
  ClaudeCodeStateLabel: TNewStaticText;
  ToolsNoteLabel: TNewStaticText;

  UninstallDataChoice: Integer;
  UninstallAllOption: TNewRadioButton;
  UninstallConfirmButton: TNewButton;

function GetFileAttributesW(const FileName: String): DWORD;
  external 'GetFileAttributesW@kernel32.dll stdcall';
function CreateFileW(const FileName: String; DesiredAccess, ShareMode: DWORD;
  SecurityAttributes: Longint; CreationDisposition, FlagsAndAttributes: DWORD;
  TemplateFile: THandle): THandle;
  external 'CreateFileW@kernel32.dll stdcall';
function WriteFile(Handle: THandle; const Buffer: AnsiString; BytesToWrite: DWORD;
  var BytesWritten: DWORD; Overlapped: Longint): BOOL;
  external 'WriteFile@kernel32.dll stdcall';
function CloseHandle(Handle: THandle): BOOL;
  external 'CloseHandle@kernel32.dll stdcall';

function IsReparsePoint(const Path: String): Boolean;
var
  Attributes: DWORD;
begin
  Attributes := GetFileAttributesW(Path);
  Result := (Attributes <> $FFFFFFFF) and
    ((Attributes and ReparsePointAttribute) <> 0);
end;

function ContainsReparsePoint(const Directory: String): Boolean;
var
  Entry: TFindRec;
  Child: String;
begin
  Result := IsReparsePoint(Directory);
  if Result or (not DirExists(Directory)) then
    Exit;
  if FindFirst(AddBackslash(Directory) + '*', Entry) then begin
    try
      repeat
        if (Entry.Name <> '.') and (Entry.Name <> '..') then begin
          Child := AddBackslash(Directory) + Entry.Name;
          if IsReparsePoint(Child) then begin
            Result := True;
            Exit;
          end;
          if DirExists(Child) and ContainsReparsePoint(Child) then begin
            Result := True;
            Exit;
          end;
        end;
      until not FindNext(Entry);
    finally
      FindClose(Entry);
    end;
  end;
end;

function UserDataRoot(const Id: String): String;
begin
  Result := ExpandConstant('{localappdata}\') + Id;
end;

function DataRootHasUserData(const Root: String): Boolean;
var
  Entry: TFindRec;
begin
  Result := False;
  if FindFirst(AddBackslash(Root) + '*', Entry) then begin
    try
      repeat
        // Same disposable entries as watched_kettle/application/paths.py.
        if (Entry.Name <> '.') and (Entry.Name <> '..') and
           (CompareText(Entry.Name, 'runtime') <> 0) and
           (CompareText(Entry.Name, 'updates') <> 0) then begin
          Result := True;
          Exit;
        end;
      until not FindNext(Entry);
    finally
      FindClose(Entry);
    end;
  end;
end;

function DataRootHasFile(const Root, Mask: String): Boolean;
var
  Entry: TFindRec;
begin
  Result := FindFirst(AddBackslash(Root) + Mask, Entry);
  if Result then
    FindClose(Entry);
end;

// The files "delete history only" removes beyond logs.
function DataRootHasRecords(const Root: String): Boolean;
begin
  Result := DataRootHasFile(Root, 'assistant-v1.sqlite3*') or
    DataRootHasFile(Root, 'usage-history-v1.json*');
end;

// Mirrors application/paths.py: Private Beta data still waiting for its
// one-time rename receives the pets, so they move with it on first start.
function UserPetsRoot(Param: String): String;
begin
  if (not DataRootHasUserData(UserDataRoot('{#AppId}'))) and
     DataRootHasUserData(UserDataRoot('{#LegacyAppId}')) then
    Result := UserDataRoot('{#LegacyAppId}') + '\pets'
  else
    Result := UserDataRoot('{#AppId}') + '\pets';
end;

procedure AssertSafeUserDataRoot(const DataRoot, Id: String);
begin
  if (CompareText(DataRoot, UserDataRoot(Id)) <> 0) or
     (CompareText(ExtractFileName(DataRoot), Id) <> 0) or
     IsReparsePoint(DataRoot) then
    RaiseException(FmtMessage(CustomMessage('UnsafeDataRoot'), [DataRoot]));
end;

function DeleteRecordFiles(const DataRoot, Mask: String): Boolean;
var
  Entry: TFindRec;
  FileName: String;
begin
  Result := True;
  if FindFirst(AddBackslash(DataRoot) + Mask, Entry) then begin
    try
      repeat
        FileName := AddBackslash(DataRoot) + Entry.Name;
        if DirExists(FileName) or (not DeleteFile(FileName)) then begin
          Result := False;
          Exit;
        end;
      until not FindNext(Entry);
    finally
      FindClose(Entry);
    end;
  end;
end;

// ---- Shared layout helpers -------------------------------------------------

function CreateText(Parent: TWinControl; Left, Top, Width: Integer;
  const Text: String): TNewStaticText;
begin
  Result := TNewStaticText.Create(Parent);
  Result.Parent := Parent;
  Result.AutoSize := False;
  Result.WordWrap := True;
  Result.Left := Left;
  Result.Top := Top;
  Result.Width := Width;
  Result.Caption := Text;
  Result.AdjustHeight;
end;

function CreateOption(Parent: TWinControl; Left, Top, Width: Integer;
  const Text: String): TNewRadioButton;
begin
  Result := TNewRadioButton.Create(Parent);
  Result.Parent := Parent;
  Result.Left := Left;
  Result.Top := Top;
  Result.Width := Width;
  Result.Height := ScaleY(20);
  Result.Font.Style := [fsBold];
  Result.Caption := Text;
end;

function CreateCheck(Parent: TWinControl; Left, Top, Width: Integer;
  const Text: String): TNewCheckBox;
begin
  Result := TNewCheckBox.Create(Parent);
  Result.Parent := Parent;
  Result.Left := Left;
  Result.Top := Top;
  Result.Width := Width;
  Result.Height := ScaleY(20);
  Result.Font.Style := [fsBold];
  Result.Caption := Text;
end;

function Below(Control: TControl; Gap: Integer): Integer;
begin
  Result := Control.Top + Control.Height + Gap;
end;

// ---- Uninstall data dialog -------------------------------------------------

procedure UpdateUninstallConfirmButton(Sender: TObject);
begin
  if UninstallAllOption.Checked then
    UninstallConfirmButton.Caption := CustomMessage('UninstallAllButton')
  else
    UninstallConfirmButton.Caption := CustomMessage('UninstallButton');
end;

// A click on an option's description selects the option above it.
procedure OptionNoteClick(Sender: TObject);
begin
  TNewRadioButton(TNewStaticText(Sender).FocusControl).Checked := True;
  UpdateUninstallConfirmButton(Sender);
end;

function CreateOptionNote(Parent: TWinControl; Option: TNewRadioButton;
  Indent, Width: Integer; const Text: String): TNewStaticText;
begin
  Result := CreateText(Parent, Option.Left + Indent, Below(Option, ScaleY(1)),
    Width - Indent, Text);
  Result.FocusControl := Option;
  Result.OnClick := @OptionNoteClick;
  Option.OnClick := @UpdateUninstallConfirmButton;
end;

function UninstallRemovesHooks(): Boolean; forward;

function SelectUninstallDataChoice(): Boolean;
var
  ChoiceForm: TSetupForm;
  Title, KeepNote, RecordsNote, AllNote, Info, Folder: TNewStaticText;
  KeepOption, RecordsOption: TNewRadioButton;
  CancelButton: TNewButton;
  Margin, Indent, ContentWidth, Top, ButtonWidth, ButtonHeight: Integer;
  InfoText: String;
begin
  Result := True;
  UninstallDataChoice := KeepUserData;
  // Nothing to ask about when the app never stored anything.
  if UninstallSilent or
     ((not DataRootHasUserData(UserDataRoot('{#AppId}'))) and
      (not DataRootHasUserData(UserDataRoot('{#LegacyAppId}')))) then
    Exit;
  ChoiceForm := CreateCustomForm(ScaleX(500), ScaleY(320), False, True);
  try
    ChoiceForm.Caption := CustomMessage('UninstallDataCaption');
    Margin := ScaleX(20);
    Indent := ScaleX(20);
    ContentWidth := ChoiceForm.ClientWidth - 2 * Margin;

    Title := CreateText(ChoiceForm, Margin, ScaleY(18), ContentWidth,
      CustomMessage('UninstallDataTitle'));
    Title.Font.Size := Title.Font.Size + 3;
    Title.Font.Style := [fsBold];
    Title.AdjustHeight;

    KeepOption := CreateOption(ChoiceForm, Margin, Below(Title, ScaleY(16)),
      ContentWidth, CustomMessage('UninstallKeep'));
    KeepOption.Checked := True;
    KeepNote := CreateOptionNote(ChoiceForm, KeepOption, Indent, ContentWidth,
      CustomMessage('UninstallKeepNote'));
    Top := Below(KeepNote, ScaleY(12));

    // A pet-only user has no assistant history, only logs.
    if DataRootHasRecords(UserDataRoot('{#AppId}')) or
       DataRootHasRecords(UserDataRoot('{#LegacyAppId}')) then begin
      RecordsOption := CreateOption(ChoiceForm, Margin, Top, ContentWidth,
        CustomMessage('UninstallRecords'));
      RecordsNote := CreateOptionNote(ChoiceForm, RecordsOption, Indent,
        ContentWidth, CustomMessage('UninstallRecordsNote'));
      Top := Below(RecordsNote, ScaleY(12));
    end else
      RecordsOption := nil;

    UninstallAllOption := CreateOption(ChoiceForm, Margin, Top, ContentWidth,
      CustomMessage('UninstallAll'));
    AllNote := CreateOptionNote(ChoiceForm, UninstallAllOption, Indent,
      ContentWidth, CustomMessage('UninstallAllNote'));

    if UninstallRemovesHooks() then
      InfoText := CustomMessage('UninstallInfoHooks')
    else
      InfoText := CustomMessage('UninstallInfoStartup');
    Info := CreateText(ChoiceForm, Margin, Below(AllNote, ScaleY(20)),
      ContentWidth, InfoText);
    Folder := CreateText(ChoiceForm, Margin, Below(Info, ScaleY(6)), ContentWidth,
      FmtMessage(CustomMessage('UninstallDataFolder'), [UserDataRoot('{#AppId}')]));

    ButtonHeight := ScaleY(25);
    UninstallConfirmButton := TNewButton.Create(ChoiceForm);
    UninstallConfirmButton.Parent := ChoiceForm;
    UninstallConfirmButton.ModalResult := mrOk;
    UninstallConfirmButton.Default := True;
    CancelButton := TNewButton.Create(ChoiceForm);
    CancelButton.Parent := ChoiceForm;
    CancelButton.Caption := SetupMessage(msgButtonCancel);
    CancelButton.ModalResult := mrCancel;
    CancelButton.Cancel := True;
    // Wide enough for both confirm captions, so switching never relayouts.
    ButtonWidth := ChoiceForm.CalculateButtonWidth([CustomMessage('UninstallButton'),
      CustomMessage('UninstallAllButton'), CancelButton.Caption]);
    Top := Below(Folder, ScaleY(22));
    CancelButton.SetBounds(ChoiceForm.ClientWidth - Margin - ButtonWidth, Top,
      ButtonWidth, ButtonHeight);
    UninstallConfirmButton.SetBounds(CancelButton.Left - ScaleX(8) - ButtonWidth,
      Top, ButtonWidth, ButtonHeight);
    UpdateUninstallConfirmButton(nil);
    ChoiceForm.ClientHeight := Below(CancelButton, ScaleY(16));
    ChoiceForm.ActiveControl := KeepOption;

    if ChoiceForm.ShowModal <> mrOk then begin
      Result := False;
      Exit;
    end;
    if UninstallAllOption.Checked then
      UninstallDataChoice := RemoveAllUserData
    else if (RecordsOption <> nil) and RecordsOption.Checked then
      UninstallDataChoice := RemoveRecords
    else
      UninstallDataChoice := KeepUserData;
  finally
    ChoiceForm.Free;
  end;
end;

// A raised exception would reach the user as "Runtime error (at ...)", so the
// uninstall steps raise and these handlers show the message alone.
procedure ShowUninstallFailure(const Message: String);
begin
  Log('Uninstall stopped: ' + Message);
  SuppressibleMsgBox(Message, mbCriticalError, MB_OK, IDOK);
end;

function InitializeUninstall(): Boolean;
begin
  Result := SelectUninstallDataChoice();
  if Result and (UninstallDataChoice <> KeepUserData) then begin
    try
      AssertSafeUserDataRoot(UserDataRoot('{#AppId}'), '{#AppId}');
      AssertSafeUserDataRoot(UserDataRoot('{#LegacyAppId}'), '{#LegacyAppId}');
    except
      ShowUninstallFailure(GetExceptionMessage);
      Result := False;
    end;
  end;
end;

// ---- Runtime layout --------------------------------------------------------

function RuntimeExecutable(const Edition: String): String;
begin
  Result := ExpandConstant('{app}\runtime\') + Edition + '\{#AppExe}';
  if not FileExists(Result) then
    Result := ExpandConstant('{app}\runtime\') + Edition + '\{#LegacyAppExe}';
end;

function RuntimeInstalled(const Edition: String): Boolean;
begin
  Result := FileExists(RuntimeExecutable(Edition));
end;

function InstallAssistant(): Boolean;
begin
  Result := ChooseAssistant;
end;

function InstallPetOnly(): Boolean;
begin
  Result := not InstallAssistant();
end;

function NeedHookCleanup(): Boolean;
begin
  Result := InstallPetOnly() and
    (not RuntimeInstalled('pet-assistant')) and
    FileExists(ExpandConstant('{app}\{#LegacyAppExe}'));
end;

function SelectedEdition(): String;
begin
  if InstallAssistant() then
    Result := 'pet-assistant'
  else
    Result := 'pet-only';
end;

function SelectedExecutable(Param: String): String;
begin
  Result := ExpandConstant('{app}\runtime\') + SelectedEdition() + '\{#AppExe}';
end;

function MatchesExecutable(const Value, Candidate: String): Boolean;
begin
  Result := (CompareText(Value, Candidate) = 0) or
    (CompareText(Value, '"' + Candidate + '"') = 0);
end;

function IsInstalledExecutableValue(const Value: String): Boolean;
var
  Runtime: String;
begin
  Runtime := ExpandConstant('{app}\runtime\');
  Result := MatchesExecutable(Value, ExpandConstant('{app}\{#AppExe}')) or
    MatchesExecutable(Value, ExpandConstant('{app}\{#LegacyAppExe}')) or
    MatchesExecutable(Value, Runtime + 'pet-only\{#AppExe}') or
    MatchesExecutable(Value, Runtime + 'pet-only\{#LegacyAppExe}') or
    MatchesExecutable(Value, Runtime + 'pet-assistant\{#AppExe}') or
    MatchesExecutable(Value, Runtime + 'pet-assistant\{#LegacyAppExe}');
end;

procedure DeleteLegacyExecutables(const Edition: String);
var
  Root: String;
begin
  Root := ExpandConstant('{app}\runtime\') + Edition + '\';
  DeleteFile(Root + '{#LegacyAppExe}');
  DeleteFile(Root + 'CodexPetsHookBridge.exe');
  DeleteFile(Root + 'settings-ui\CodexPetsSettings.exe');
end;

// ---- Running app -----------------------------------------------------------

// Processes started from AppDir: the pet runtime and, unless MainOnly, its
// settings window and hook bridges. The launcher exits once it has started a
// runtime, and the uninstaller runs as unins000.exe and a copy in {tmp}.
function FindRunningProcesses(const AppDir: String; MainOnly: Boolean): TProcessIds;
var
  Locator, Service, Items, Item: Variant;
  Index, Count: Integer;
  Names, Prefix, Path: String;
begin
  SetArrayLength(Result, 0);
  if MainOnly then
    Names := '{#AppExe},{#LegacyAppExe}'
  else
    Names := '{#AppProcesses}';
  StringChangeEx(Names, ',', ''' OR Name = ''', True);
  Prefix := AddBackslash(AppDir);
  try
    Locator := CreateOleObject('WbemScripting.SWbemLocator');
    Service := Locator.ConnectServer('.', 'root\CIMV2');
    Items := Service.ExecQuery('SELECT ProcessId, ExecutablePath FROM Win32_Process ' +
      'WHERE Name = ''' + Names + '''');
    for Index := 0 to Items.Count - 1 do begin
      Item := Items.ItemIndex(Index);
      if VarIsNull(Item.ExecutablePath) then
        Continue;
      Path := Item.ExecutablePath;
      if CompareText(Copy(Path, 1, Length(Prefix)), Prefix) = 0 then begin
        Count := GetArrayLength(Result);
        SetArrayLength(Result, Count + 1);
        Result[Count] := Item.ProcessId;
      end;
    end;
  except
    // Without the process list, setup proceeds as it did before this check.
    Log('Could not list running processes: ' + GetExceptionMessage);
  end;
end;

function WaitForProcessesGone(const AppDir: String; Polls: Integer): Boolean;
var
  Poll: Integer;
begin
  Result := True;
  for Poll := 0 to Polls do begin
    if GetArrayLength(FindRunningProcesses(AppDir, False)) = 0 then
      Exit;
    if Poll < Polls then
      Sleep(250);
  end;
  Result := False;
end;

// Sends "quit" over the single-instance pipe and returns the open pipe, or
// THandle(-1). The caller keeps it open while waiting, so the app has read the
// request before Setup lets go of the connection.
function SendQuitRequest(): THandle;
var
  Written: DWORD;
begin
  Result := CreateFileW(InstancePipe, GenericRead or GenericWrite, 0, 0,
    OpenExisting, 0, 0);
  if Result = THandle(-1) then
    Log('The app pipe is not available: ' + IntToStr(DLLGetLastError))
  else if WriteFile(Result, 'quit' + #10, 5, Written, 0) then
    Log('Asked the running app to quit.')
  else
    Log('Could not send the quit request: ' + IntToStr(DLLGetLastError));
end;

procedure ForceCloseProcesses(const AppDir: String);
var
  Ids: TProcessIds;
  Index, ExitCode: Integer;
begin
  Ids := FindRunningProcesses(AppDir, False);
  for Index := 0 to GetArrayLength(Ids) - 1 do begin
    Exec(ExpandConstant('{sys}\taskkill.exe'), '/F /T /PID ' + IntToStr(Ids[Index]),
      '', SW_HIDE, ewWaitUntilTerminated, ExitCode);
    Log(Format('Force closed process %d (taskkill exit code %d).', [Ids[Index], ExitCode]));
  end;
end;

// Closes this installation's processes before any of its files change. Builds
// without the quit request ignore it; silent runs then force close them and
// interactive runs ask first. False means the app is still running.
function StopRunningApp(const AppDir: String; Silent: Boolean): Boolean;
var
  Pipe: THandle;
begin
  Result := True;
  if GetArrayLength(FindRunningProcesses(AppDir, False)) = 0 then
    Exit;
  // Only this installation's pet owns the pipe; a source run may hold it too.
  Pipe := THandle(-1);
  if GetArrayLength(FindRunningProcesses(AppDir, True)) > 0 then
    Pipe := SendQuitRequest();
  try
    Result := WaitForProcessesGone(AppDir, QuitWaitPolls);
  finally
    if Pipe <> THandle(-1) then
      CloseHandle(Pipe);
  end;
  if Result then begin
    Log('The running app closed.');
    Exit;
  end;
  if (not Silent) and
     (MsgBox(CustomMessage('AppStillRunning'), mbConfirmation, MB_YESNO) <> IDYES) then begin
    Log('The user kept the running app open.');
    Exit;
  end;
  ForceCloseProcesses(AppDir);
  Result := WaitForProcessesGone(AppDir, ForceWaitPolls);
end;

// ---- Startup entry ---------------------------------------------------------

// Same text as WindowsStartupRegistration.expected_command (subprocess.list2cmdline),
// so the app's settings page sees the entry as its own.
function StartupCommand(): String;
begin
  Result := ExpandConstant('{app}\{#AppExe}');
  if (Pos(' ', Result) > 0) or (Pos(#9, Result) > 0) then
    Result := '"' + Result + '"';
end;

function OwnStartupValue(const Name: String): Boolean;
var
  Current: String;
begin
  Result := RegQueryStringValue(HKCU, RunKey, Name, Current) and
    IsInstalledExecutableValue(Current);
end;

// Points an existing entry at the launcher, or applies the user's change on
// the tasks page. Silent setup never turns startup on or off.
procedure UpdateStartupEntry();
var
  Enable: Boolean;
begin
  Enable := InitialStartup;
  if StartupTaskShown then
    Enable := WizardIsTaskSelected('startup');
  if Enable then begin
    RegWriteStringValue(HKCU, RunKey, '{#AppId}', StartupCommand());
    if OwnStartupValue('{#LegacyAppId}') then
      RegDeleteValue(HKCU, RunKey, '{#LegacyAppId}');
  end else if InitialStartup then begin
    if OwnStartupValue('{#AppId}') then
      RegDeleteValue(HKCU, RunKey, '{#AppId}');
    if OwnStartupValue('{#LegacyAppId}') then
      RegDeleteValue(HKCU, RunKey, '{#LegacyAppId}');
  end;
end;

// ---- Tool integrations -----------------------------------------------------

function CodexHome(): String;
begin
  Result := GetEnv('CODEX_HOME');
  if Result = '' then
    Result := AddBackslash(GetEnv('USERPROFILE')) + '.codex';
end;

function ClaudeCodeHome(): String;
begin
  Result := GetEnv('CLAUDE_CONFIG_DIR');
  if Result = '' then
    Result := AddBackslash(GetEnv('USERPROFILE')) + '.claude';
end;

function ManagedHookMarkerPresent(const Marker: String): Boolean;
var
  HookPath: String;
  HookText: AnsiString;
begin
  HookPath := AddBackslash(CodexHome()) + 'hooks.json';
  Result := False;
  if FileExists(HookPath) then begin
    if not LoadStringFromFile(HookPath, HookText) then
      RaiseException(FmtMessage(CustomMessage('HookFileUnreadable'), [HookPath]));
    Result := Pos(Marker, HookText) > 0;
  end;
end;

function ClaudeCodeManagedHookPresent(): Boolean;
var
  SettingsPath: String;
  SettingsText: AnsiString;
begin
  SettingsPath := AddBackslash(ClaudeCodeHome()) + 'settings.json';
  Result := False;
  if FileExists(SettingsPath) then begin
    if not LoadStringFromFile(SettingsPath, SettingsText) then
      RaiseException(FmtMessage(CustomMessage('ClaudeSettingsUnreadable'), [SettingsPath]));
    Result := Pos('watched-kettle-managed-v1', SettingsText) > 0;
  end;
end;

function CodexManagedHookPresent(): Boolean;
begin
  Result := ManagedHookMarkerPresent('watched-kettle-managed-v1') or
    ManagedHookMarkerPresent('codex-desktop-pets-managed-v1');
end;

function AnyManagedHookPresent(): Boolean;
begin
  Result := CodexManagedHookPresent() or ClaudeCodeManagedHookPresent();
end;

// For wording only: an unreadable file still blocks the uninstall later.
function AnyManagedHookPresentSafe(): Boolean;
begin
  try
    Result := AnyManagedHookPresent();
  except
    Result := True;
  end;
end;

function SwitchParam(const Name: String; Default: Boolean): Boolean;
var
  Value: String;
begin
  Value := Lowercase(ExpandConstant('{param:' + Name + '|}'));
  if Value = 'on' then
    Result := True
  else if Value = 'off' then
    Result := False
  else
    Result := Default;
end;

// Reads what is installed in {app} and resets the choices to match. Runs again
// only when the user picked another folder.
procedure DetectInstalledState();
var
  Edition: String;
begin
  if CompareText(DetectedDir, ExpandConstant('{app}')) = 0 then
    Exit;
  DetectedDir := ExpandConstant('{app}');
  HadPetRuntime := RuntimeInstalled('pet-only');
  HadAssistantRuntime := RuntimeInstalled('pet-assistant') or
    FileExists(ExpandConstant('{app}\{#LegacyAppExe}'));
  if HadAssistantRuntime then begin
    // An unreadable file counts as "not connected"; setup leaves it alone.
    try
      InitialCodex := CodexManagedHookPresent();
    except
      InitialCodex := False;
    end;
    try
      InitialClaudeCode := ClaudeCodeManagedHookPresent();
    except
      InitialClaudeCode := False;
    end;
  end else begin
    InitialCodex := DirExists(CodexHome());
    InitialClaudeCode := DirExists(ClaudeCodeHome());
  end;
  InitialStartup := OwnStartupValue('{#AppId}') or OwnStartupValue('{#LegacyAppId}');
  StartupTaskShown := False;

  Edition := Lowercase(ExpandConstant('{param:EDITION|}'));
  if Edition = 'pet-assistant' then
    ChooseAssistant := True
  else if Edition = 'pet-only' then
    ChooseAssistant := False
  else
    ChooseAssistant := HadAssistantRuntime;
  ChooseCodex := SwitchParam('CODEX', InitialCodex);
  ChooseClaudeCode := SwitchParam('CLAUDECODE', InitialClaudeCode);
end;

// A new assistant applies every tool choice. An upgrade applies the tools that
// changed, so a plain silent upgrade keeps the in-app settings. An interactive
// upgrade also turns off a tool left unchecked: an unconnected tool starts
// unchecked, and its usage switch would otherwise stay on (shown in the app).
// A checked tool that was already connected keeps the switch the user set.
function ToolArgument(const Flag: String; Selected, Initial: Boolean): String;
begin
  Result := '';
  if (not HadAssistantRuntime) or (Selected <> Initial) or
     ((not Selected) and (not WizardSilent())) then begin
    if Selected then
      Result := ' ' + Flag + '=on'
    else
      Result := ' ' + Flag + '=off';
  end;
end;

function IntegrationArguments(): String;
begin
  Result := ToolArgument('--codex', ChooseCodex, InitialCodex) +
    ToolArgument('--claude-code', ChooseClaudeCode, InitialClaudeCode);
end;

// ---- Wizard pages ----------------------------------------------------------

procedure UpdateRemoveAssistantWarning(Sender: TObject);
begin
  RemoveAssistantLabel.Visible := HadAssistantRuntime and PetOnlyOption.Checked;
end;

procedure EditionNoteClick(Sender: TObject);
begin
  TNewRadioButton(TNewStaticText(Sender).FocusControl).Checked := True;
  UpdateRemoveAssistantWarning(Sender);
end;

procedure ToolStateClick(Sender: TObject);
var
  Check: TNewCheckBox;
begin
  Check := TNewCheckBox(TNewStaticText(Sender).FocusControl);
  Check.Checked := not Check.Checked;
end;

procedure CreateEditionPage();
var
  Width, Indent: Integer;
begin
  EditionPage := CreateCustomPage(wpSelectDir, CustomMessage('EditionPageCaption'),
    CustomMessage('EditionPageDescription'));
  Width := EditionPage.SurfaceWidth;
  Indent := ScaleX(20);
  CurrentEditionLabel := CreateText(EditionPage.Surface, 0, 0, Width, '');
  PetOnlyOption := CreateOption(EditionPage.Surface, 0, 0, Width,
    CustomMessage('EditionPetOnly'));
  PetOnlyNote := CreateText(EditionPage.Surface, Indent, 0, Width - Indent,
    CustomMessage('EditionPetOnlyNote'));
  AssistantOption := CreateOption(EditionPage.Surface, 0, 0, Width,
    CustomMessage('EditionAssistant'));
  AssistantNote := CreateText(EditionPage.Surface, Indent, 0, Width - Indent,
    CustomMessage('EditionAssistantNote'));
  RemoveAssistantLabel := CreateText(EditionPage.Surface, 0, 0, Width,
    CustomMessage('RemoveAssistantWarning'));
  PetOnlyNote.FocusControl := PetOnlyOption;
  AssistantNote.FocusControl := AssistantOption;
  PetOnlyOption.OnClick := @UpdateRemoveAssistantWarning;
  AssistantOption.OnClick := @UpdateRemoveAssistantWarning;
  PetOnlyNote.OnClick := @EditionNoteClick;
  AssistantNote.OnClick := @EditionNoteClick;
end;

procedure CreateToolsPage();
var
  Width, Indent: Integer;
begin
  ToolsPage := CreateCustomPage(EditionPage.ID, CustomMessage('ToolsPageCaption'),
    CustomMessage('ToolsPageDescription'));
  Width := ToolsPage.SurfaceWidth;
  Indent := ScaleX(20);
  CodexCheck := CreateCheck(ToolsPage.Surface, 0, 0, Width, 'Codex');
  CodexStateLabel := CreateText(ToolsPage.Surface, Indent, Below(CodexCheck, ScaleY(1)),
    Width - Indent, '');
  ClaudeCodeCheck := CreateCheck(ToolsPage.Surface, 0, Below(CodexStateLabel, ScaleY(14)),
    Width, 'Claude Code');
  ClaudeCodeStateLabel := CreateText(ToolsPage.Surface, Indent,
    Below(ClaudeCodeCheck, ScaleY(1)), Width - Indent, '');
  ToolsNoteLabel := CreateText(ToolsPage.Surface, 0, 0, Width, '');
  CodexStateLabel.FocusControl := CodexCheck;
  ClaudeCodeStateLabel.FocusControl := ClaudeCodeCheck;
  CodexStateLabel.OnClick := @ToolStateClick;
  ClaudeCodeStateLabel.OnClick := @ToolStateClick;
end;

procedure InitializeWizard();
begin
  CreateEditionPage();
  CreateToolsPage();
end;

function CurrentEditionText(): String;
begin
  if HadPetRuntime and RuntimeInstalled('pet-assistant') then
    Result := CustomMessage('CurrentBoth')
  else if RuntimeInstalled('pet-assistant') then
    Result := CustomMessage('CurrentAssistant')
  else if HadAssistantRuntime then
    Result := CustomMessage('CurrentLegacy')
  else if HadPetRuntime then
    Result := CustomMessage('CurrentPetOnly')
  else
    Result := '';
end;

procedure ShowEditionPage();
var
  Top: Integer;
begin
  CurrentEditionLabel.Caption := CurrentEditionText();
  CurrentEditionLabel.AdjustHeight;
  CurrentEditionLabel.Visible := CurrentEditionLabel.Caption <> '';
  Top := 0;
  if CurrentEditionLabel.Visible then
    Top := Below(CurrentEditionLabel, ScaleY(16));
  PetOnlyOption.Top := Top;
  PetOnlyNote.Top := Below(PetOnlyOption, ScaleY(1));
  AssistantOption.Top := Below(PetOnlyNote, ScaleY(16));
  AssistantNote.Top := Below(AssistantOption, ScaleY(1));
  RemoveAssistantLabel.Top := Below(AssistantNote, ScaleY(22));
  PetOnlyOption.Checked := not ChooseAssistant;
  AssistantOption.Checked := ChooseAssistant;
  UpdateRemoveAssistantWarning(nil);
end;

function ToolStateText(Initial: Boolean): String;
begin
  if HadAssistantRuntime then begin
    if Initial then
      Result := CustomMessage('ToolConnected')
    else
      Result := CustomMessage('ToolNotConnected');
  end else if Initial then
    Result := CustomMessage('ToolFound')
  else
    Result := CustomMessage('ToolNotFound');
end;

procedure ShowToolsPage();
begin
  CodexCheck.Checked := ChooseCodex;
  ClaudeCodeCheck.Checked := ChooseClaudeCode;
  CodexStateLabel.Caption := ToolStateText(InitialCodex);
  ClaudeCodeStateLabel.Caption := ToolStateText(InitialClaudeCode);
  if HadAssistantRuntime then
    ToolsNoteLabel.Caption := CustomMessage('ToolsUpgradeNote')
  else
    ToolsNoteLabel.Caption := CustomMessage('ToolsNewNote');
  ToolsNoteLabel.AdjustHeight;
  ToolsNoteLabel.Top := Below(ClaudeCodeStateLabel, ScaleY(22));
end;

procedure ReadToolChoices();
begin
  ChooseCodex := CodexCheck.Checked;
  ChooseClaudeCode := ClaudeCodeCheck.Checked;
end;

procedure CurPageChanged(CurPageID: Integer);
begin
  // Runs before each page is painted, so the defaults never flash.
  if CurPageID = EditionPage.ID then begin
    DetectInstalledState();
    ShowEditionPage();
  end else if CurPageID = ToolsPage.ID then
    ShowToolsPage()
  else if (CurPageID = wpSelectTasks) and (not StartupTaskShown) then begin
    // The app can change startup after setup, so show the current entry
    // rather than the previous setup's choice.
    if InitialStartup then
      WizardSelectTasks('startup')
    else
      WizardSelectTasks('!startup');
    StartupTaskShown := True;
  end;
end;

function NextButtonClick(CurPageID: Integer): Boolean;
begin
  Result := True;
  // Silent setup simulates Next on pages it never showed; keep its choices.
  if WizardSilent then
    Exit;
  if CurPageID = EditionPage.ID then
    ChooseAssistant := AssistantOption.Checked
  else if CurPageID = ToolsPage.ID then
    ReadToolChoices();
end;

function BackButtonClick(CurPageID: Integer): Boolean;
begin
  Result := True;
  if (CurPageID = ToolsPage.ID) and (not WizardSilent) then
    ReadToolChoices();
end;

function ShouldSkipPage(PageID: Integer): Boolean;
begin
  Result := (PageID = ToolsPage.ID) and (not ChooseAssistant);
end;

function EditionName(): String;
begin
  if ChooseAssistant then
    Result := CustomMessage('EditionAssistant')
  else
    Result := CustomMessage('EditionPetOnly');
end;

function ChosenTools(): String;
begin
  Result := '';
  if ChooseCodex then
    Result := 'Codex';
  if ChooseClaudeCode then begin
    if Result <> '' then
      Result := Result + ', ';
    Result := Result + 'Claude Code';
  end;
  if Result = '' then
    Result := CustomMessage('ReadyNoTools');
end;

function UpdateReadyMemo(Space, NewLine, MemoUserInfoInfo, MemoDirInfo, MemoTypeInfo,
  MemoComponentsInfo, MemoGroupInfo, MemoTasksInfo: String): String;
begin
  Result := CustomMessage('ReadyEdition') + NewLine + Space + EditionName() + NewLine;
  if ChooseAssistant then
    Result := Result + NewLine + CustomMessage('ReadyTools') + NewLine + Space +
      ChosenTools() + NewLine;
  if MemoDirInfo <> '' then
    Result := Result + NewLine + MemoDirInfo + NewLine;
  if MemoTasksInfo <> '' then
    Result := Result + NewLine + MemoTasksInfo + NewLine;
end;

// ---- Install steps ---------------------------------------------------------

// The app's update button starts Setup this way after it quits itself.
function RelaunchRequested(): Boolean;
begin
  Result := WizardSilent and (ExpandConstant('{param:RELAUNCH|0}') = '1');
end;

// Runs before Restart Manager looks at [Files], and also closes the edition
// that ssPostInstall removes, which Restart Manager never checks.
function PrepareToInstall(var NeedsRestart: Boolean): String;
begin
  Result := '';
  if not StopRunningApp(WizardDirValue, WizardSilent) then
    Result := CustomMessage('AppRunningAbort');
end;

// An unreadable hook file is reported like the other integration failures
// instead of as a script error.
function LegacyHookPresent(): Boolean;
begin
  try
    Result := ManagedHookMarkerPresent('codex-desktop-pets-managed-v1');
  except
    Result := False;
    SuppressibleMsgBox(GetExceptionMessage, mbError, MB_OK, IDOK);
  end;
end;

procedure CurStepChanged(CurStep: TSetupStep);
var
  ExitCode: Integer;
  Helper, Arguments: String;
  HookRemoved: Boolean;
begin
  // Silent setup skips the pages; read the old state before files change.
  if CurStep = ssInstall then
    DetectInstalledState();
  if CurStep <> ssPostInstall then
    Exit;
  HookRemoved := True;
  if InstallAssistant() then begin
    DelTree(ExpandConstant('{app}\runtime\pet-only'), True, True, True);
    // Point Private Beta hooks at the renamed bridge before its old file goes.
    if LegacyHookPresent() then begin
      if (not Exec(SelectedExecutable(''), '--migrate-legacy-hook', '', SW_HIDE,
                   ewWaitUntilTerminated, ExitCode)) or (ExitCode <> 0) then
        SuppressibleMsgBox(CustomMessage('LegacyHookMigrateFailed'), mbError, MB_OK, IDOK);
    end;
    DeleteLegacyExecutables('pet-assistant');
    Arguments := IntegrationArguments();
    if Arguments <> '' then begin
      if (not Exec(SelectedExecutable(''), '--configure-integrations' + Arguments, '',
                   SW_HIDE, ewWaitUntilTerminated, ExitCode)) or (ExitCode <> 0) then
        SuppressibleMsgBox(CustomMessage('IntegrationsFailed'), mbError, MB_OK, IDOK);
    end;
  end else begin
    DeleteLegacyExecutables('pet-only');
    Helper := RuntimeExecutable('pet-assistant');
    if not FileExists(Helper) then
      Helper := ExpandConstant('{app}\hook-cleanup-helper\{#AppExe}');
    if FileExists(Helper) then begin
      if (not Exec(Helper, '--remove-managed-hook', '', SW_HIDE,
                   ewWaitUntilTerminated, ExitCode)) or (ExitCode <> 0) then begin
        HookRemoved := False;
        SuppressibleMsgBox(CustomMessage('HookRemoveFailed'), mbError, MB_OK, IDOK);
      end;
    end;
    DelTree(ExpandConstant('{app}\hook-cleanup-helper'), True, True, True);
    if HookRemoved then
      DelTree(ExpandConstant('{app}\runtime\pet-assistant'), True, True, True);
  end;
  // The launcher starts this edition even if the other one had to stay.
  SaveStringToFile(ExpandConstant('{app}\runtime\edition'), SelectedEdition(), False);
  UpdateStartupEntry();
  // Remove the old single-bundle layout after the selected runtime was copied.
  if HookRemoved then begin
    DeleteFile(ExpandConstant('{app}\{#LegacyAppExe}'));
    DelTree(ExpandConstant('{app}\_internal'), True, True, True);
  end;
end;

// ---- Uninstall steps -------------------------------------------------------

procedure RemoveManagedStartupForUninstall();
begin
  if OwnStartupValue('{#AppId}') and
     (not RegDeleteValue(HKCU, RunKey, '{#AppId}')) then
    RaiseException(CustomMessage('StartupRemoveFailed'));
  if OwnStartupValue('{#LegacyAppId}') and
     (not RegDeleteValue(HKCU, RunKey, '{#LegacyAppId}')) then
    RaiseException(CustomMessage('StartupRemoveFailed'));
end;

// The assistant runtime that can remove the managed hooks, or '' for none.
function HookCleanupHelper(): String;
begin
  Result := RuntimeExecutable('pet-assistant');
  if not FileExists(Result) then
    Result := ExpandConstant('{app}\{#LegacyAppExe}');
  if not FileExists(Result) then
    Result := '';
end;

function UninstallRemovesHooks(): Boolean;
begin
  Result := (HookCleanupHelper() <> '') and AnyManagedHookPresentSafe();
end;

procedure RemoveManagedHookForUninstall();
var
  Helper: String;
  ExitCode: Integer;
begin
  if not AnyManagedHookPresent() then
    Exit;
  Helper := HookCleanupHelper();
  // Switching to pet only keeps the assistant runtime while its hooks remain,
  // so hooks with no helper here belong to another copy, such as a source run.
  if Helper = '' then begin
    Log('Leaving managed hooks that another copy of the app added.');
    Exit;
  end;
  if (not Exec(Helper, '--remove-managed-hook', '', SW_HIDE,
               ewWaitUntilTerminated, ExitCode)) or (ExitCode <> 0) then
    RaiseException(CustomMessage('HookRemoveAbort'));
  if AnyManagedHookPresent() then
    RaiseException(CustomMessage('HookRemainAbort'));
end;

procedure DeleteAllUserDataIn(const DataRoot: String);
var
  Staging: String;
begin
  if not DirExists(DataRoot) then
    Exit;
  Staging := DataRoot + '.removing';
  if ContainsReparsePoint(DataRoot) or ContainsReparsePoint(Staging) then
    RaiseException(FmtMessage(CustomMessage('DataLinkedAbort'), [DataRoot]));
  // Left behind by an earlier uninstall that could not finish deleting.
  if DirExists(Staging) then
    DelTree(Staging, True, True, True);
  // Renaming fails while any file inside is open, so either all of the data
  // goes or none of it does.
  if DirExists(Staging) or (not RenameFile(DataRoot, Staging)) then
    RaiseException(FmtMessage(CustomMessage('DataInUseAbort'), [DataRoot]));
  if not DelTree(Staging, True, True, True) then
    SuppressibleMsgBox(FmtMessage(CustomMessage('DataLeftover'), [Staging]),
      mbInformation, MB_OK, IDOK);
end;

procedure DeleteChosenUserDataIn(const Id: String);
var
  DataRoot, LogRoot, RuntimeRoot: String;
begin
  DataRoot := UserDataRoot(Id);
  AssertSafeUserDataRoot(DataRoot, Id);
  if UninstallDataChoice = RemoveAllUserData then begin
    DeleteAllUserDataIn(DataRoot);
    Exit;
  end;
  if not DirExists(DataRoot) then
    Exit;
  LogRoot := AddBackslash(DataRoot) + 'logs';
  RuntimeRoot := AddBackslash(DataRoot) + 'runtime';
  if ContainsReparsePoint(LogRoot) or ContainsReparsePoint(RuntimeRoot) then
    RaiseException(CustomMessage('LogsLinkedAbort'));
  if (not DeleteRecordFiles(DataRoot, 'assistant-v1.sqlite3*')) or
     (not DeleteRecordFiles(DataRoot, 'usage-history-v1.json*')) then
    RaiseException(FmtMessage(CustomMessage('RecordsDeleteFailed'), [DataRoot]));
  if DirExists(LogRoot) and (not DelTree(LogRoot, True, True, True)) then
    RaiseException(FmtMessage(CustomMessage('LogsDeleteFailed'), [LogRoot]));
  if DirExists(RuntimeRoot) and (not DelTree(RuntimeRoot, True, True, True)) then
    RaiseException(FmtMessage(CustomMessage('RuntimeDeleteFailed'), [RuntimeRoot]));
end;

procedure DeleteChosenUserData();
begin
  if UninstallDataChoice = KeepUserData then
    Exit;
  DeleteChosenUserDataIn('{#AppId}');
  // A Private Beta folder remains when a running old build blocked migration.
  DeleteChosenUserDataIn('{#LegacyAppId}');
  if UninstallDataChoice = RemoveAllUserData then begin
    if RegKeyExists(HKCU, 'Software\{#LegacyAppId}\DesktopPet') and
       (not RegDeleteKeyIncludingSubkeys(HKCU, 'Software\{#LegacyAppId}\DesktopPet')) then
      RaiseException(CustomMessage('LegacySettingsDeleteFailed'));
    RegDeleteKeyIfEmpty(HKCU, 'Software\{#LegacyAppId}');
  end;
end;

// Installers the app downloaded for its own updates. They are a cache, so
// they go even when the user keeps their data, and a failure does not stop
// the uninstall.
procedure DeleteDownloadedUpdates();
var
  Updates: String;
begin
  Updates := AddBackslash(UserDataRoot('{#AppId}')) + 'updates';
  if not DirExists(Updates) then
    Exit;
  if ContainsReparsePoint(Updates) then
    Log('Kept the downloaded updates folder because it contains a link: ' + Updates)
  else if not DelTree(Updates, True, True, True) then
    Log('Could not delete the downloaded updates folder: ' + Updates);
end;

procedure UninstallSteps();
begin
  if not StopRunningApp(ExpandConstant('{app}'), UninstallSilent) then
    RaiseException(CustomMessage('AppRunningAbort'));
  // Hook removal restores the user's Claude Code status line from the data
  // folder's runtime directory, so it runs before the data is deleted.
  RemoveManagedHookForUninstall();
  RemoveManagedStartupForUninstall();
  DeleteChosenUserData();
  DeleteDownloadedUpdates();
end;

procedure CurUninstallStepChanged(CurUninstallStep: TUninstallStep);
var
  Failure: String;
begin
  if CurUninstallStep <> usUninstall then
    Exit;
  // Everything runs before any program file is removed. An exception here
  // stops the uninstaller with the app still installed, so it can run again;
  // after usUninstall it would only be logged and the uninstall would finish.
  Failure := '';
  try
    UninstallSteps();
  except
    Failure := GetExceptionMessage;
  end;
  if Failure <> '' then begin
    ShowUninstallFailure(Failure);
    Abort;
  end;
end;
