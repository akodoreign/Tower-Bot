$out = 'C:\Users\akodoreign\Desktop\mysql_diag.txt'

# Service status
"=== Service ===" | Set-Content $out
Get-Service MySQL96 | Select-Object Name, Status, StartType | Out-String | Add-Content $out

# Recent events
"=== Event Log (last 10) ===" | Add-Content $out
Get-EventLog -LogName Application -Source "MySQL*" -Newest 10 -ErrorAction SilentlyContinue |
    Select-Object TimeGenerated, EntryType, Message | Out-String | Add-Content $out

# my.ini around mysqld section
"=== my.ini [mysqld] section (first 20 lines) ===" | Add-Content $out
$lines = Get-Content 'C:\ProgramData\MySQL\MySQL Server 9.6\my.ini'
$start = ($lines | Select-String '\[mysqld\]').LineNumber - 1
$lines[$start..($start+20)] | Out-String | Add-Content $out
