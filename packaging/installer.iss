#ifndef AppVersion
  #error AppVersion required
#endif
#ifndef BundleDir
  #error BundleDir required
#endif
#ifndef OutputDir
  #error OutputDir required
#endif
#ifndef AppIcon
  #error AppIcon required
#endif

[Setup]
AppId={{462CFA5D-1847-4CE8-BBD8-50DDFD79D582}
AppName=Windows Macro Studio
AppVersion={#AppVersion}
AppPublisher=Windows Macro Studio
DefaultDirName={localappdata}\Programs\Windows Macro Studio
DefaultGroupName=Windows Macro Studio
DisableProgramGroupPage=yes
AllowNoIcons=yes
PrivilegesRequired=lowest
ArchitecturesAllowed=x64compatible
ArchitecturesInstallIn64BitMode=x64compatible
MinVersion=10.0.17763
OutputDir={#OutputDir}
OutputBaseFilename=WindowsMacroStudio-Setup-{#AppVersion}-x64
SetupIconFile={#AppIcon}
UninstallDisplayIcon={app}\WindowsMacroStudio.exe
UninstallDisplayName=Windows Macro Studio
WizardStyle=modern
Compression=lzma2
SolidCompression=yes
CloseApplications=yes
RestartApplications=no
AppMutex=WindowsMacroStudio.Desktop
SetupLogging=yes
VersionInfoVersion={#AppVersion}.0

[Languages]
Name: "french"; MessagesFile: "compiler:Languages\French.isl"
Name: "english"; MessagesFile: "compiler:Default.isl"

[Tasks]
Name: "desktopicon"; Description: "Créer un raccourci sur le Bureau"; GroupDescription: "Raccourcis :"; Flags: unchecked

[Files]
Source: "{#BundleDir}\*"; DestDir: "{app}"; Flags: ignoreversion recursesubdirs createallsubdirs

[Icons]
Name: "{group}\Windows Macro Studio"; Filename: "{app}\WindowsMacroStudio.exe"; WorkingDir: "{userdocs}"; AppUserModelID: "WindowsMacroStudio.Desktop"
Name: "{autodesktop}\Windows Macro Studio"; Filename: "{app}\WindowsMacroStudio.exe"; WorkingDir: "{userdocs}"; Tasks: desktopicon; AppUserModelID: "WindowsMacroStudio.Desktop"

[Run]
Filename: "{app}\WindowsMacroStudio.exe"; Description: "Lancer Windows Macro Studio"; Flags: nowait postinstall skipifsilent

; No deletion of workflows, local counters or user settings on uninstall.
