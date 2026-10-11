; Inno Setup script — builds PRIVEX-<ver>-setup.exe from dist\PRIVEX (run via build.py).
#ifndef AppVersion
  #define AppVersion "0.0.0"
#endif

[Setup]
AppId=PRIVEX.LocalPrivacyFirewall
AppName=PRIVEX
AppVersion={#AppVersion}
AppPublisher=PRIVEX
DefaultDirName={localappdata}\Programs\PRIVEX
DefaultGroupName=PRIVEX
PrivilegesRequired=lowest
OutputBaseFilename=PRIVEX-{#AppVersion}-setup
SetupIconFile=privex.ico
Compression=lzma2/max
SolidCompression=yes
ArchitecturesInstallIn64BitMode=x64compatible
WizardStyle=modern

[Files]
Source: "..\dist\PRIVEX\*"; DestDir: "{app}"; Flags: recursesubdirs ignoreversion

[Icons]
Name: "{group}\PRIVEX"; Filename: "{app}\PRIVEX.exe"
Name: "{userdesktop}\PRIVEX"; Filename: "{app}\PRIVEX.exe"; Tasks: desktopicon
Name: "{userstartup}\PRIVEX"; Filename: "{app}\PRIVEX.exe"; Parameters: "--no-browser"; Tasks: autostart

[Tasks]
Name: "desktopicon"; Description: "Create a desktop shortcut"
Name: "autostart"; Description: "Start PRIVEX in the background when I sign in (needed for the browser extension)"; Flags: unchecked

[Run]
Filename: "{app}\PRIVEX.exe"; Description: "Launch PRIVEX"; Flags: nowait postinstall skipifsilent
