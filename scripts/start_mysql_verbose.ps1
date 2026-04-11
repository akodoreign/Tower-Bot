$out = 'C:\Users\akodoreign\Desktop\mysql_diag.txt'

# Try net start for verbose error
"=== net start output ===" | Add-Content $out
& net start MySQL96 2>&1 | Out-String | Add-Content $out

# Try running mysqld directly to catch config errors
"=== mysqld --validate-config ===" | Add-Content $out
& 'C:\Program Files\MySQL\MySQL Server 9.6\bin\mysqld.exe' `
    --defaults-file='C:\ProgramData\MySQL\MySQL Server 9.6\my.ini' `
    --validate-config 2>&1 | Out-String | Add-Content $out
