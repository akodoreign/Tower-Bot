# remove_peak_saver.ps1 -- fully undo setup_peak_saver.ps1.
# Deletes the two scheduled tasks, restores High performance as the active scheme,
# and deletes the "Tower Peak Saver" scheme. Safe to run anytime.
#   powershell -ExecutionPolicy Bypass -File scripts\remove_peak_saver.ps1

$SchemeName = "Tower Peak Saver"

function Get-SchemeGuidByName($name) {
  foreach ($l in (powercfg /list)) {
    if ($l -like "*$name*" -and $l -match '([0-9a-fA-F-]{36})') { return $Matches[1] }
  }
  return $null
}

# 1) delete tasks (ignore if absent)
foreach ($t in @("Tower Peak Saver - On", "Tower Peak Saver - Off")) {
  try { schtasks /delete /tn "$t" /f 2>$null | Out-Null; "deleted task: $t" } catch {}
}

# 2) restore a normal scheme as active before deleting the peak saver
$hp = Get-SchemeGuidByName "High performance"
if ($hp) { powercfg /setactive $hp; "active scheme restored to High performance" }

# 3) delete the peak-saver scheme
$g = Get-SchemeGuidByName $SchemeName
if ($g) { powercfg /delete $g; "deleted scheme: $SchemeName ($g)" } else { "no $SchemeName scheme found" }

"active scheme now:"; powercfg /getactivescheme
"Removal complete."
