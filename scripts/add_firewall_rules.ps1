$rules = @(
    @{Name='Block MySQL External (3306)';              Port=3306},
    @{Name='Block MySQL X Protocol External (33060)';  Port=33060},
    @{Name='Block SMB External (445)';                 Port=445},
    @{Name='Block RPC External (135)';                 Port=135},
    @{Name='Block RDP External (3389)';                Port=3389},
    @{Name='Block HyperV External (2179)';             Port=2179}
)

foreach ($r in $rules) {
    # Remove old rule with same name if it exists (idempotent)
    Remove-NetFirewallRule -DisplayName $r.Name -ErrorAction SilentlyContinue
    New-NetFirewallRule `
        -DisplayName  $r.Name `
        -Direction    Inbound `
        -Protocol     TCP `
        -LocalPort    $r.Port `
        -RemoteAddress Internet `
        -Action       Block `
        -Profile      Any `
        -ErrorAction  Stop
    Write-Host "OK: $($r.Name)"
}

Write-Host "`nAll rules added. Verifying..."
Get-NetFirewallRule -DisplayName "Block MySQL External (3306)",
                                 "Block MySQL X Protocol External (33060)",
                                 "Block SMB External (445)",
                                 "Block RPC External (135)",
                                 "Block RDP External (3389)",
                                 "Block HyperV External (2179)",
                                 "Block Ollama External (11434)",
                                 "Block A1111 External (7860)" |
    Select-Object DisplayName, Enabled, Action |
    Format-Table -AutoSize
