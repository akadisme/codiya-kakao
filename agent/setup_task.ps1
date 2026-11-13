# 설치할 때 실행: PC 켜고 로그인하면 "가장 높은 권한"으로 코디야 카톡발송을 켜는 작업 등록
# (카카오톡이 관리자 권한으로 돌아서 이 프로그램도 관리자 권한이어야 해요 · 매번 "예"를 누르지 않게)
param([string]$AppDir)
$exe = Join-Path $AppDir "CodiyaKakao.exe"
$a = New-ScheduledTaskAction -Execute $exe -Argument "/tray" -WorkingDirectory $AppDir
$t = New-ScheduledTaskTrigger -AtLogOn -User "$env:USERDOMAIN\$env:USERNAME"
$s = New-ScheduledTaskSettingsSet -AllowStartIfOnBatteries -DontStopIfGoingOnBatteries -DontStopOnIdleEnd -ExecutionTimeLimit ([TimeSpan]::Zero) -MultipleInstances IgnoreNew
$p = New-ScheduledTaskPrincipal -UserId "$env:USERDOMAIN\$env:USERNAME" -LogonType Interactive -RunLevel Highest
Register-ScheduledTask -TaskName "CodiyaKakao" -Action $a -Trigger $t -Settings $s -Principal $p -Force | Out-Null
