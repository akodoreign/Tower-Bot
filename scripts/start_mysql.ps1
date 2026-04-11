Start-Service MySQL96 -ErrorAction SilentlyContinue
Start-Sleep 5
$svc = Get-Service MySQL96
Write-Host "Status: $($svc.Status)"
$out = 'C:\Users\akodoreign\Desktop\mysql_log.txt'
Get-Content 'C:\ProgramData\MySQL\MySQL Server 9.6\Data\DH0424-C8823422.err' -Tail 20 | Set-Content $out
