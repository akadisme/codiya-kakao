; 코디야 카톡발송 — 설치 파일 (관리자 권한 필요: 카카오톡이 관리자 권한으로 돌아서)
#define AppVer "1.0.0"
[Setup]
AppId={{6B1E2C7A-4D3F-4A8B-9C21-5E7D3F0A9B42}
AppName=코디야 카톡발송
AppVersion={#AppVer}
AppPublisher=코디야
AppPublisherURL=https://codiya.kr
DefaultDirName={autopf}\CodiyaKakao
DisableDirPage=yes
DisableProgramGroupPage=yes
PrivilegesRequired=admin
OutputDir=out
OutputBaseFilename=CodiyaKakaoSetup
SetupIconFile=agent\app.ico
UninstallDisplayIcon={app}\CodiyaKakao.exe
Compression=lzma2
SolidCompression=yes
WizardStyle=modern
CloseApplications=no
LicenseFile=license.txt
DisableReadyPage=yes

[Languages]
Name: "korean"; MessagesFile: "compiler:Languages\Korean.isl"

[Files]
Source: "dist\CodiyaKakao\*"; DestDir: "{app}"; Flags: ignoreversion recursesubdirs createallsubdirs
Source: "agent\setup_task.ps1"; DestDir: "{app}"; Flags: ignoreversion

[Icons]
Name: "{autoprograms}\코디야 카톡발송"; Filename: "{app}\CodiyaKakao.exe"
Name: "{autodesktop}\코디야 카톡발송"; Filename: "{app}\CodiyaKakao.exe"; Check: not WizardSilent

[Run]
; PC 켜면 저절로 (가장 높은 권한) 켜지게 작업 스케줄러에 등록
Filename: "powershell.exe"; Parameters: "-NoProfile -ExecutionPolicy Bypass -File ""{app}\setup_task.ps1"" -AppDir ""{app}"""; Flags: runhidden waituntilterminated
; 설치가 끝나면 바로 켜기 (자동 업데이트 때도)
Filename: "schtasks.exe"; Parameters: "/Run /TN CodiyaKakao"; Flags: runhidden nowait

[UninstallRun]
Filename: "{cmd}"; Parameters: "/C taskkill /IM CodiyaKakao.exe /F"; Flags: runhidden; RunOnceId: "KillApp"
Filename: "schtasks.exe"; Parameters: "/Delete /TN CodiyaKakao /F"; Flags: runhidden; RunOnceId: "DelTask"

[Code]
// 설치 전에 켜져 있는 프로그램을 조용히 끄기 — 설치가 끝나면 다시 켜져요
function PrepareToInstall(var NeedsRestart: Boolean): String;
var R: Integer;
begin
  Exec(ExpandConstant('{sys}\taskkill.exe'), '/F /IM CodiyaKakao.exe', '', SW_HIDE, ewWaitUntilTerminated, R);
  Sleep(800);
  Result := '';
end;
