; Inno Setup script: per-user install (no admin), Start menu shortcut, optional desktop
; shortcut and optional "Open with" entry for PDFs.
; Build: iscc /DAppVersion=0.1.0 packaging\installer.iss

#ifndef AppVersion
  #define AppVersion "0.0.0"
#endif
#define AppName "PDF Touch-up"
#define AppExe "PDFTouchup.exe"

[Setup]
AppId={{268502DF-8DD4-434C-A338-9827B259D616}
AppName={#AppName}
AppVersion={#AppVersion}
AppPublisher=PDF Touch-up contributors
DefaultDirName={localappdata}\Programs\{#AppName}
DefaultGroupName={#AppName}
DisableProgramGroupPage=yes
PrivilegesRequired=lowest
OutputDir=..\dist
OutputBaseFilename=PDF-Touchup-Setup-{#AppVersion}
Compression=lzma2/max
SolidCompression=yes
WizardStyle=modern
UninstallDisplayIcon={app}\{#AppExe}
LicenseFile=..\LICENSE
ChangesAssociations=yes

[Tasks]
Name: "desktopicon"; Description: "Create a desktop shortcut"; Flags: unchecked
Name: "openwith"; Description: "Add PDF Touch-up to the ""Open with"" menu for PDF files"; Flags: unchecked

[Files]
Source: "..\dist\PDFTouchup\*"; DestDir: "{app}"; Flags: ignoreversion recursesubdirs createallsubdirs

[Icons]
Name: "{group}\{#AppName}"; Filename: "{app}\{#AppExe}"
Name: "{group}\Uninstall {#AppName}"; Filename: "{uninstallexe}"
Name: "{userdesktop}\{#AppName}"; Filename: "{app}\{#AppExe}"; Tasks: desktopicon

[Registry]
Root: HKCU; Subkey: "Software\Classes\Applications\{#AppExe}\shell\open\command"; ValueType: string; ValueData: """{app}\{#AppExe}"" ""%1"""; Flags: uninsdeletekey; Tasks: openwith
Root: HKCU; Subkey: "Software\Classes\Applications\{#AppExe}"; ValueType: string; ValueName: "FriendlyAppName"; ValueData: "{#AppName}"; Tasks: openwith
Root: HKCU; Subkey: "Software\Classes\.pdf\OpenWithList\{#AppExe}"; Flags: uninsdeletekey; Tasks: openwith

[Run]
Filename: "{app}\{#AppExe}"; Description: "Open {#AppName} now"; Flags: nowait postinstall skipifsilent
