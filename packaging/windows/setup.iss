; Inno Setup script for the Windows setup program. build.sh runs it with /DAppVersion=X.Y.Z after
; PyInstaller has built dist\TalkpodManager. Installs for the current user only (no administrator
; rights), so the in-app updater can run the next one silently: it passes /UPDATE=1, and the app is
; started again when the update is done.

#ifndef AppVersion
  #error Pass /DAppVersion=X.Y.Z
#endif

[Setup]
AppId={{6F1C3A52-9C1E-4F5B-A0D4-2B7E8C4D9A61}
AppName=Talkpod Manager
AppVersion={#AppVersion}
AppVerName=Talkpod Manager {#AppVersion}
AppPublisher=ssjrocks
AppPublisherURL=https://github.com/ssjrocks/talkpod-manager
AppSupportURL=https://github.com/ssjrocks/talkpod-manager/issues
AppUpdatesURL=https://github.com/ssjrocks/talkpod-manager/releases
DefaultDirName={autopf}\Talkpod Manager
DisableProgramGroupPage=yes
DisableDirPage=auto
PrivilegesRequired=lowest
ArchitecturesAllowed=x64compatible
ArchitecturesInstallIn64BitMode=x64compatible
OutputDir=..\..\dist
OutputBaseFilename=TalkpodManager-{#AppVersion}-setup
SetupIconFile=talkpod-manager.ico
UninstallDisplayIcon={app}\TalkpodManager.exe
UninstallDisplayName=Talkpod Manager
LicenseFile=..\..\LICENSE
Compression=lzma2/max
SolidCompression=yes
WizardStyle=modern

[Tasks]
Name: "desktopicon"; Description: "{cm:CreateDesktopIcon}"; GroupDescription: "{cm:AdditionalIcons}"; Flags: unchecked

[InstallDelete]
; the previous version's libraries, so nothing stale is left beside the new ones
Type: filesandordirs; Name: "{app}\_internal"

[Files]
Source: "..\..\dist\TalkpodManager\*"; DestDir: "{app}"; Flags: ignoreversion recursesubdirs createallsubdirs

[Icons]
Name: "{autoprograms}\Talkpod Manager"; Filename: "{app}\TalkpodManager.exe"
Name: "{autodesktop}\Talkpod Manager"; Filename: "{app}\TalkpodManager.exe"; Tasks: desktopicon

[Run]
Filename: "{app}\TalkpodManager.exe"; Description: "{cm:LaunchProgram,Talkpod Manager}"; Flags: nowait postinstall skipifsilent
Filename: "{app}\TalkpodManager.exe"; Flags: nowait; Check: IsUpdate

[Code]
function IsUpdate: Boolean;
begin
  Result := ExpandConstant('{param:UPDATE|0}') = '1';
end;
