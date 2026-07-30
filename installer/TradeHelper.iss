#ifndef MyAppVersion
  #define MyAppVersion "0.1.0"
#endif

#define MyAppName "Trade Helper"
#define MyAppPublisher "Trade Helper contributors"
#define MyAppExeName "TradeHelper.exe"
#define MyReleaseRoot "..\dist\TradeHelper-" + MyAppVersion + "-windows-x64"

[Setup]
AppId=TradeHelper.PersonalV1
AppName={#MyAppName}
AppVersion={#MyAppVersion}
AppPublisher={#MyAppPublisher}
DefaultDirName={localappdata}\Programs\TradeHelper
DefaultGroupName={#MyAppName}
DisableProgramGroupPage=yes
PrivilegesRequired=lowest
PrivilegesRequiredOverridesAllowed=dialog
OutputDir=..\dist
OutputBaseFilename=TradeHelper-{#MyAppVersion}-windows-x64-setup
Compression=lzma2
SolidCompression=yes
WizardStyle=modern
ArchitecturesAllowed=x64compatible
ArchitecturesInstallIn64BitMode=x64compatible
UninstallDisplayIcon={app}\{#MyAppExeName}
VersionInfoVersion={#MyAppVersion}
VersionInfoProductName={#MyAppName}
VersionInfoProductVersion={#MyAppVersion}
VersionInfoDescription=Local ETF position management assistant
CloseApplications=yes
RestartApplications=no
InfoBeforeFile=..\RELEASE_NOTES.md

[Languages]
Name: "chinesesimp"; MessagesFile: "compiler:Languages\ChineseSimplified.isl"

[Tasks]
Name: "desktopicon"; Description: "创建桌面快捷方式"; GroupDescription: "附加图标："; Flags: unchecked

[Files]
Source: "{#MyReleaseRoot}\TradeHelper.exe"; DestDir: "{app}"; Flags: ignoreversion
Source: "{#MyReleaseRoot}\TradeHelperCLI.exe"; DestDir: "{app}"; Flags: ignoreversion
Source: "{#MyReleaseRoot}\release-manifest.json"; DestDir: "{app}"; Flags: ignoreversion
Source: "{#MyReleaseRoot}\RELEASE_NOTES.md"; DestDir: "{app}"; Flags: ignoreversion
Source: "{#MyReleaseRoot}\docs\*"; DestDir: "{app}\docs"; Flags: ignoreversion recursesubdirs createallsubdirs
Source: "{#MyReleaseRoot}\config\*"; DestDir: "{app}\config"; Flags: ignoreversion recursesubdirs createallsubdirs
Source: "{#MyReleaseRoot}\templates\*"; DestDir: "{app}\templates"; Flags: ignoreversion recursesubdirs createallsubdirs
Source: "{#MyReleaseRoot}\scripts\*"; DestDir: "{app}\scripts"; Flags: ignoreversion recursesubdirs createallsubdirs

[Icons]
Name: "{group}\{#MyAppName}"; Filename: "{app}\{#MyAppExeName}"
Name: "{autodesktop}\{#MyAppName}"; Filename: "{app}\{#MyAppExeName}"; Tasks: desktopicon

[Run]
Filename: "{app}\{#MyAppExeName}"; Description: "启动 {#MyAppName}"; Flags: nowait postinstall skipifsilent unchecked

[UninstallDelete]
; Intentionally do not remove {localappdata}\TradeHelper.
; The account database and pre-restore backups remain user-controlled.
