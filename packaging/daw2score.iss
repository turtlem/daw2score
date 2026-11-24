; Inno Setup script for daw2score. Built by packaging/build.py, which passes AppVersion, SourceDir
; (the PyInstaller folder dist/daw2score) and OutputDir.

#ifndef AppVersion
  #error AppVersion not defined: run packaging/build.py
#endif

[Setup]
; never change AppId: upgrades and uninstall find the installed copy by it
AppId={{46FE6A2F-48D0-4FE1-8C09-D7FAAD4F0A59}
AppName=daw2score
AppVersion={#AppVersion}
AppVerName=daw2score {#AppVersion}
AppPublisher=turtlem
AppPublisherURL=https://github.com/turtlem/daw2score
AppSupportURL=https://github.com/turtlem/daw2score/issues
AppUpdatesURL=https://github.com/turtlem/daw2score/releases
VersionInfoVersion={#AppVersion}
VersionInfoProductName=daw2score
DefaultDirName={autopf}\daw2score
DefaultGroupName=daw2score
DisableProgramGroupPage=yes
; per-user install by default (no administrator rights needed), all users on request
PrivilegesRequired=lowest
PrivilegesRequiredOverridesAllowed=dialog
ArchitecturesAllowed=x64compatible
ArchitecturesInstallIn64BitMode=x64compatible
MinVersion=10.0
LicenseFile=..\LICENSE
SetupIconFile=..\gp_export\assets\daw2score.ico
UninstallDisplayIcon={app}\daw2score.exe
UninstallDisplayName=daw2score {#AppVersion}
OutputDir={#OutputDir}
OutputBaseFilename=daw2score-{#AppVersion}-setup
Compression=lzma2/ultra64
SolidCompression=yes
LZMAUseSeparateProcess=yes
WizardStyle=modern
CloseApplications=yes
RestartApplications=no

[Languages]
Name: "en"; MessagesFile: "compiler:Default.isl"
Name: "fr"; MessagesFile: "compiler:Languages\French.isl"

[Tasks]
Name: "desktopicon"; Description: "{cm:CreateDesktopIcon}"; GroupDescription: "{cm:AdditionalIcons}"; Flags: unchecked

[InstallDelete]
; an upgrade replaces the whole bundled runtime (no stale modules from the previous version)
Type: filesandordirs; Name: "{app}\_internal"
Type: filesandordirs; Name: "{app}\licenses"

[Files]
Source: "{#SourceDir}\*"; DestDir: "{app}"; Flags: ignoreversion recursesubdirs createallsubdirs

[Icons]
Name: "{autoprograms}\daw2score"; Filename: "{app}\daw2score.exe"
Name: "{autodesktop}\daw2score"; Filename: "{app}\daw2score.exe"; Tasks: desktopicon

[Run]
Filename: "{app}\daw2score.exe"; Description: "{cm:LaunchProgram,daw2score}"; Flags: nowait postinstall skipifsilent

[UninstallDelete]
Type: filesandordirs; Name: "{app}\_internal"
; settings (registry), the log and the numba cache in %LOCALAPPDATA%\daw2score are user data: kept
