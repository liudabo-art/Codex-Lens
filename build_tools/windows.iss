#ifndef AppVersion
  #error AppVersion required
#endif
#ifndef AppSource
  #error AppSource required
#endif

[Setup]
AppId={{88AB59D1-2F0D-4C8E-B3FC-66A1DF94772D}
AppName=Codex Lens
AppVersion={#AppVersion}
AppPublisher=Codex Lens contributors
DefaultDirName={localappdata}\Programs\Relay-Auditor
DefaultGroupName=Codex Lens
PrivilegesRequired=lowest
ArchitecturesAllowed=x64compatible
ArchitecturesInstallIn64BitMode=x64compatible
MinVersion=10.0
LicenseFile=..\LICENSE
SetupIconFile=..\assets\codex-lens.ico
OutputBaseFilename=Relay-Auditor-{#AppVersion}-windows-x64-Setup
Compression=lzma2
SolidCompression=yes
WizardStyle=modern
UninstallDisplayIcon={app}\Relay-Auditor.exe
CloseApplications=yes
RestartApplications=no
SignedUninstaller=no

[Files]
Source: "{#AppSource}\*"; DestDir: "{app}"; Flags: ignoreversion recursesubdirs createallsubdirs

[Tasks]
Name: "desktopicon"; Description: "Create a desktop shortcut"; Flags: unchecked

[Icons]
Name: "{group}\Codex Lens"; Filename: "{app}\Relay-Auditor.exe"
Name: "{autodesktop}\Codex Lens"; Filename: "{app}\Relay-Auditor.exe"; Tasks: desktopicon

[Run]
Filename: "{app}\Relay-Auditor.exe"; Description: "Launch Codex Lens"; Flags: nowait postinstall skipifsilent
