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
AppName=Macro Studio
AppVersion={#AppVersion}
AppPublisher=Macro Studio
DefaultDirName={localappdata}\Programs\Macro Studio
DefaultGroupName=Macro Studio
DisableProgramGroupPage=yes
AllowNoIcons=yes
PrivilegesRequired=lowest
ArchitecturesAllowed=x64compatible
ArchitecturesInstallIn64BitMode=x64compatible
MinVersion=10.0.17763
OutputDir={#OutputDir}
OutputBaseFilename=MacroStudio-Setup-{#AppVersion}-x64
SetupIconFile={#AppIcon}
UninstallDisplayIcon={app}\MacroStudio.exe
UninstallDisplayName=Macro Studio
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
Name: "{group}\Macro Studio"; Filename: "{app}\MacroStudio.exe"; WorkingDir: "{userdocs}"; AppUserModelID: "WindowsMacroStudio.Desktop"
Name: "{autodesktop}\Macro Studio"; Filename: "{app}\MacroStudio.exe"; WorkingDir: "{userdocs}"; Tasks: desktopicon; AppUserModelID: "WindowsMacroStudio.Desktop"

[Run]
Filename: "{app}\MacroStudio.exe"; Description: "Lancer Macro Studio"; Flags: nowait postinstall skipifsilent

; No deletion of workflows, local counters or user settings on uninstall.
