$path = 'C:\ProgramData\MySQL\MySQL Server 9.6\my.ini'
$out_log = 'C:\Users\akodoreign\Desktop\mysql_fix.txt'
$lines = Get-Content $path
$out = [System.Collections.Generic.List[string]]::new()
$added = $false
foreach ($line in $lines) {
    $out.Add($line)
    if ($line.Trim() -eq '[mysqld]' -and -not $added) {
        $out.Add('bind-address = 127.0.0.1')
        $added = $true
    }
}
if ($added) {
    $utf8NoBom = New-Object System.Text.UTF8Encoding $false
    [System.IO.File]::WriteAllLines($path, $out, $utf8NoBom)
    "bind-address written (UTF-8 no BOM)" | Set-Content $out_log
} else {
    "ERROR: [mysqld] not found" | Set-Content $out_log
}

$validate = & 'C:\Program Files\MySQL\MySQL Server 9.6\bin\mysqld.exe' --defaults-file=$path --validate-config 2>&1
"=== validate-config ===" | Add-Content $out_log
$validate | Out-String | Add-Content $out_log

Start-Service MySQL96 -ErrorAction SilentlyContinue
Start-Sleep 4
$svc = Get-Service MySQL96
"=== Service status: $($svc.Status) ===" | Add-Content $out_log
