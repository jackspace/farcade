# Farcade responder service wrapper. Registered as scheduled task "Farcade-Responder" (at logon).
#
# The gate, in priority order, re-checked before anything starts:
#   MATCH (0)        prnsd owns the bus       -> attach the responder
#   UNDETERMINED (2) nothing visibly owns it  -> start OUR prnsd, wait, re-probe
#   MISMATCH (1)     something else owns it   -> REFUSE, loudly. A foreign owner means the
#                    responder would measure the wrong transport (the guard that asked the
#                    wrong question, 2026-08-14). Never fall back to standalone.
#
# The responder itself runs with require_attached=False in its transport, which is exactly why
# this wrapper must never launch it without a verified MATCH first.

$ErrorActionPreference = 'Stop'
Set-Location C:\agents\farcade
$env:PYTHONPATH = 'C:\agents\farcade'
$log = 'C:\agents\farcade\.local\responder-service.log'

function Log($msg) {
    # UTC with an explicit Z: the task-scheduler session has shown a drifted local TZ, and an
    # ambiguous stamp in a service log is worse than none.
    "$((Get-Date).ToUniversalTime().ToString('yyyy-MM-dd HH:mm:ss'))Z $msg" | Out-File -Append -FilePath $log -Encoding utf8
}

function Probe {
    & python scripts\probe_instance_owner.py *> $null
    return $LASTEXITCODE
}

Log 'wrapper start'

$verdict = Probe
if ($verdict -eq 2) {
    Log 'owner UNDETERMINED - starting the Farcade prnsd'
    Start-Process -FilePath 'C:\agents\farcade\.local\prnsd-0.3.3\bin\prnsd-0.3.3-x86_64-pc-windows-msvc\prnsd.exe' `
        -ArgumentList 'run', '--config', '.local/prnsd-config' `
        -WorkingDirectory 'C:\agents\farcade' -WindowStyle Hidden
    $deadline = (Get-Date).AddMinutes(3)
    do {
        Start-Sleep -Seconds 5
        $verdict = Probe
    } until ($verdict -eq 0 -or (Get-Date) -gt $deadline)
}

if ($verdict -eq 1) {
    Log 'owner MISMATCH - a foreign process owns the bus. REFUSING to start the responder.'
    exit 1
}
if ($verdict -ne 0) {
    Log "owner still not MATCH after prnsd start (verdict=$verdict). Giving up."
    exit 2
}

Log 'owner MATCH - starting responder (workdir .local\run-b, identity redacted-responder-identity)'
& python scripts\soak_responder.py .local\run-b *>> $log
Log "responder exited with $LASTEXITCODE"
exit $LASTEXITCODE
