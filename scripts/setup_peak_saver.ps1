# setup_peak_saver.ps1 -- "Tower Peak Saver": cut power draw during summer peak-rate hours.
#
# During the window (default weekdays 17:00-21:00) Windows switches to a low-power
# scheme -- CPU capped + monitors off fast -- but NEVER suspends (bot/MySQL/Ollama keep
# running). At the end of the window it switches back to High performance. Weekends are
# left on High performance (the tasks only fire Mon-Fri).
#
# Re-runnable / idempotent. No admin required (creates interactive tasks that run while
# you are logged on). Run AS ADMIN to instead create SYSTEM tasks that run even when
# logged off.
#   powershell -ExecutionPolicy Bypass -File scripts\setup_peak_saver.ps1

$ErrorActionPreference = "Stop"

# ---------------- tweakables ----------------
$CpuMaxPct     = 50                       # max processor state during peak hours (%)
$MonitorOffSec = 60                       # blank monitors after N seconds idle during peak
$StartTime     = "17:00"                  # window start (24h)
$EndTime       = "21:00"                  # window end   (24h)
$Days          = "MON,TUE,WED,THU,FRI"    # which days the throttle applies
$SchemeName    = "Tower Peak Saver"
$TaskOn        = "Tower Peak Saver - On"
$TaskOff       = "Tower Peak Saver - Off"
# --------------------------------------------

function Get-SchemeGuidByName($name) {
  foreach ($l in (powercfg /list)) {
    if ($l -like "*$name*" -and $l -match '([0-9a-fA-F-]{36})') { return $Matches[1] }
  }
  return $null
}

# Restore target = the normal "High performance" scheme (fallback: current active).
$restore = Get-SchemeGuidByName "High performance"
if (-not $restore) {
  $restore = ((powercfg /getactivescheme) -match '([0-9a-fA-F-]{36})') | Out-Null; $restore = $Matches[1]
}
"Restore scheme (off-peak / weekends): $restore"

# Remove any prior Tower Peak Saver scheme so we start clean.
$old = Get-SchemeGuidByName $SchemeName
if ($old) { powercfg /delete $old; "removed prior $SchemeName scheme" }

# Build the peak-saver scheme as a duplicate of the restore scheme.
$dup = powercfg /duplicatescheme $restore
$g = ($dup | Select-String -Pattern '([0-9a-fA-F-]{36})').Matches.Value
powercfg /changename $g "$SchemeName" "Reduced CPU + fast monitor-off for $StartTime-$EndTime peak rates. Never suspends."
powercfg /setacvalueindex $g SUB_PROCESSOR PROCTHROTTLEMAX $CpuMaxPct
powercfg /setdcvalueindex $g SUB_PROCESSOR PROCTHROTTLEMAX $CpuMaxPct
powercfg /setacvalueindex $g SUB_VIDEO VIDEOIDLE $MonitorOffSec
powercfg /setdcvalueindex $g SUB_VIDEO VIDEOIDLE $MonitorOffSec
powercfg /setacvalueindex $g SUB_SLEEP STANDBYIDLE 0
powercfg /setdcvalueindex $g SUB_SLEEP STANDBYIDLE 0
powercfg /setacvalueindex $g SUB_SLEEP HIBERNATEIDLE 0
powercfg /setdcvalueindex $g SUB_SLEEP HIBERNATEIDLE 0
"Created scheme $SchemeName = $g (CPU max $CpuMaxPct%, monitor off ${MonitorOffSec}s, never sleep)"

# Scheduled tasks. If elevated, run as SYSTEM (fires even when logged off); else interactive.
$isAdmin = ([Security.Principal.WindowsPrincipal][Security.Principal.WindowsIdentity]::GetCurrent()).IsInRole([Security.Principal.WindowsBuiltinRole]::Administrator)
$onCmd  = "C:\Windows\System32\powercfg.exe /setactive $g"
$offCmd = "C:\Windows\System32\powercfg.exe /setactive $restore"
$ru = if ($isAdmin) { @("/ru","SYSTEM","/rl","HIGHEST") } else { @() }
"Task run context: " + ($(if ($isAdmin) {"SYSTEM (whether logged on or not)"} else {"interactive (while logged on)"}))

schtasks /create /tn "$TaskOn"  /tr "$onCmd"  /sc weekly /d "$Days" /st $StartTime @ru /f | Out-Null
schtasks /create /tn "$TaskOff" /tr "$offCmd" /sc weekly /d "$Days" /st $EndTime   @ru /f | Out-Null
"Tasks created: '$TaskOn' @ $StartTime and '$TaskOff' @ $EndTime on $Days"

"--- verify ---"
schtasks /query /tn "$TaskOn"  /fo LIST | Select-String "TaskName|Next Run"
schtasks /query /tn "$TaskOff" /fo LIST | Select-String "TaskName|Next Run"
"Done. To remove: scripts\remove_peak_saver.ps1"
