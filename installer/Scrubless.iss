; Scrubless installer (Inno Setup 6). Build with installer\build-installer.ps1.
; Installs for the current user (no admin): program files in %LOCALAPPDATA%\Programs\Scrubless,
; the Python environment, AI models and search data in a data folder the user picks (D: by default).

#define AppVersion "0.4.0"
#define Root ".."

[Setup]
AppId={{6E3C1D52-5B9A-4C1F-9A8E-6F0D2B7C4A11}
AppName=Scrubless
AppVersion={#AppVersion}
AppPublisher=Goodo Studios
AppComments=Search footage by what is said and what is shown, on this PC.
DefaultDirName={localappdata}\Programs\Scrubless
; Up to 0.3.1 the app was called Footage Finder (same AppId): install into the new folder, not the old one.
UsePreviousAppDir=no
DisableProgramGroupPage=yes
PrivilegesRequired=lowest
OutputDir=build
OutputBaseFilename=Scrubless Setup {#AppVersion}
SetupIconFile={#Root}\footage_finder\icon.ico
UninstallDisplayIcon={app}\Scrubless.exe
UninstallDisplayName=Scrubless
WizardStyle=modern
Compression=lzma2/max
SolidCompression=yes
CloseApplications=yes

[Tasks]
Name: "desktopicon"; Description: "Create a Desktop shortcut"; GroupDescription: "Shortcuts:"

[Files]
Source: "build\Scrubless.exe"; DestDir: "{app}"; Flags: ignoreversion
Source: "build\uv.exe"; DestDir: "{app}\tools"; Flags: ignoreversion
Source: "setup-env.ps1"; DestDir: "{app}\tools"; Flags: ignoreversion
Source: "setup.cmd"; DestDir: "{app}\tools"; Flags: ignoreversion
Source: "{#Root}\pyproject.toml"; DestDir: "{app}\app"; Flags: ignoreversion
Source: "{#Root}\uv.lock"; DestDir: "{app}\app"; Flags: ignoreversion
Source: "{#Root}\README.md"; DestDir: "{app}"; Flags: ignoreversion
Source: "{#Root}\footage_finder\*"; DestDir: "{app}\app\footage_finder"; Excludes: "__pycache__\*,*.pyc"; Flags: ignoreversion recursesubdirs createallsubdirs

[InstallDelete]
; Leftovers from when the app was called Footage Finder (0.3.x)
Type: filesandordirs; Name: "{localappdata}\Programs\Footage Finder"
Type: files; Name: "{autodesktop}\Footage Finder.lnk"
Type: files; Name: "{autoprograms}\Footage Finder.lnk"
Type: files; Name: "{autoprograms}\Footage Finder setup (repair).lnk"

[Icons]
Name: "{autoprograms}\Scrubless"; Filename: "{app}\Scrubless.exe"; Comment: "Search footage by what is said and shown"
Name: "{autodesktop}\Scrubless"; Filename: "{app}\Scrubless.exe"; Tasks: desktopicon
Name: "{autoprograms}\Scrubless setup (repair)"; Filename: "{app}\tools\setup.cmd"; IconFilename: "{app}\Scrubless.exe"; Comment: "Check or repair the Python environment"

[Run]
; The Python/AI setup is not run here: Windows restricts processes the installer starts, which breaks
; uv's Python folder junction. Scrubless.exe offers the setup on first launch instead.
Filename: "{app}\Scrubless.exe"; Description: "Open Scrubless"; Flags: postinstall nowait skipifsilent

[UninstallDelete]
Type: filesandordirs; Name: "{app}\app"

[Code]
var
  DataPage: TInputDirWizardPage;

function DefaultData(): String;
begin
  if DirExists('D:\footage-finder-data') or DirExists('D:\') then
    Result := 'D:\footage-finder-data'
  else
    Result := ExpandConstant('{localappdata}\FootageFinder');
end;

procedure InitializeWizard;
begin
  DataPage := CreateInputDirPage(wpSelectDir,
    'Data folder', 'Where should Scrubless keep its AI models and search data?',
    'Needs about 15 GB (Python, AI libraries and models), plus a little per indexed folder.' + #13#10 +
    'Pick an internal drive with space. An external drive works, but the app won''t open without it.',
    False, '');
  DataPage.Add('');
  DataPage.Values[0] := GetPreviousData('DataDir', DefaultData());
end;

procedure RegisterPreviousData(PreviousDataKey: Integer);
begin
  SetPreviousData(PreviousDataKey, 'DataDir', DataPage.Values[0]);
end;

function DataDir(Param: String): String;
begin
  Result := DataPage.Values[0];
end;

procedure CurStepChanged(CurStep: TSetupStep);
begin
  if CurStep = ssPostInstall then
    SaveStringToFile(ExpandConstant('{app}\launcher.ini'),
      '; Scrubless launcher settings' + #13#10 +
      'data=' + DataPage.Values[0] + #13#10, False);
end;

procedure CurUninstallStepChanged(CurUninstallStep: TUninstallStep);
begin
  if CurUninstallStep = usPostUninstall then
    MsgBox('Scrubless was removed. Its data folder (AI models and search data) was kept, so a reinstall ' +
           'is quick. Delete it by hand to free the space.', mbInformation, MB_OK);
end;
