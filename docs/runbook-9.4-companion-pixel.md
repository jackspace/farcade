# Runbook: the 9.4 live acceptance — chess from a stock phone

Written 2026-08-16. A full game from stock Sideband on the Pixel XL against the bot on
the Windows host, over prnsd. Written so someone who has never touched this stack can run it.
Everything here happens on the Windows host (the Windows machine) and the Pixel; nothing touches
the Pi.

**The one dangerous fact:** step 2 restarts the Windows host's prnsd, which drops the Farcade TCP
link to the Pi. If a measurement window is running, that ends it. That is why step 1
exists and is not optional.

---

## 1. Get the operator's clear (do not skip)

On the ops log, as a **reply to the operator's latest comment** (top-level comments
don't notify), post:

> About to add a TCP listener to the Windows host's farcade prnsd and restart it for the 9.4
> companion test. The restart drops the Farcade TCP link to the Pi. Clear, or hold?

Wait for an explicit "clear". Config changes void measurement windows, and the operator is the
measurer.

## 2. Add a listening interface and restart prnsd (PowerShell, on the Windows host)

```powershell
cd C:\agents\farcade

# 2a. Back up the config (the house convention: config.pre-<change>)
Copy-Item .local\prnsd-config\config .local\prnsd-config\config.pre-couch-tcp

# 2b. Confirm port 4242 is free (no output = free)
Get-NetTCPConnection -LocalPort 4242 -State Listen -ErrorAction SilentlyContinue
```

Open `.local\prnsd-config\config` in a text editor and add this block at the end,
indented exactly like the `[[Farcade Link]]` block above it:

```
  [[Couch TCP]]
    type = TCPServerInterface
    interface_enabled = Yes
    listen_ip = 0.0.0.0
    listen_port = 4242
```

Save. Then restart the stack:

```powershell
# 2c. Stop the running responder (identify it by its command line, not by name)
Get-CimInstance Win32_Process |
  Where-Object { $_.CommandLine -match 'soak_responder' } |
  ForEach-Object { Stop-Process -Id $_.ProcessId -Force }

# 2d. Stop prnsd itself
Get-Process prnsd -ErrorAction SilentlyContinue | Stop-Process -Force

# 2e. Start everything back up through the owner-gated wrapper
Start-ScheduledTask -TaskName Farcade-Responder
```

The wrapper probes the shared-instance owner, starts prnsd with the new config, waits
for a MATCH, and re-attaches the responder. Give it a minute, then verify all three:

```powershell
# The new listener is up:
Get-NetTCPConnection -LocalPort 4242 -State Listen
# The the Pi link came back (note the NEW pid — the old one died with the restart):
Get-NetTCPConnection -RemotePort 4243 -State Established
# The wrapper's own log ends in "owner MATCH - starting responder":
Get-Content .local\responder-service.log -Tail 3
```

**Stamp the flap on the ops log** (reply to the operator): the time prnsd went down and the time the
4243 session re-established. If 4243 does not come back within ~2 minutes, restore the
backup config (`Copy-Item .local\prnsd-config\config.pre-couch-tcp .local\prnsd-config\config -Force`),
repeat 2c–2e, and stop here — tell the operator what happened.

## 3. Start the companion host (a second PowerShell window)

```powershell
cd C:\agents\farcade
$env:PYTHONPATH = 'C:\agents\farcade'

# 3a. The shared instance's RPC key (a hex string; copy it)
.venv\Scripts\python.exe -m farcade.cli rns-key .local\prnsd-config

# 3b. Run the host (paste the key in place of <KEY>)
.venv\Scripts\python.exe scripts\companion_host.py .local\companion --rpc-key <KEY>
```

The first line it prints is the whole health check:

```
companion address: <32 hex characters>  attached=True
```

`attached=True` is required. `attached=False` or a refusal means it could not join
prnsd — stop and investigate; do not work around it. Copy the 32-character address
(it is also saved in `.local\companion\address.txt`). Leave this window running for
the entire game.

## 4. Set up the Pixel

1. Put the Pixel on the local Wi-Fi (the local network).
2. Open **Sideband** → menu (≡) → **Preferences / Connectivity**.
3. Enable the **TCP client interface** ("Connect via TCP"). Two fields:
   - Host: `your-host-lan-ip`  (that is the Windows host)
   - Port: `4242`
   (Menu wording shifts slightly between Sideband versions; you are looking for the
   TCP client with a host field and a port field.)
4. Apply/save. Sideband connects within a few seconds.

## 5. Play

1. In Sideband: start a **new conversation** and paste the 32-character companion
   address as the recipient. (If you wait for announces instead, the peer shows up as
   `farcade-companion` — but pasting is immediate.)
2. Send `help` — a help message comes back. That round-trip is the moment the whole
   path works.
3. Send `play chess`. The board arrives as text.
4. Make moves by typing them: `e4`, `Nf3`, sloppy input is fine. `board` reprints the
   position, `resign` gives up, `play reversi` starts a different game.
5. Play to a decided outcome (win, loss, or draw — a resign counts).

## 6. Capture the evidence

- On the Pixel: screenshots at the start, mid-game, and the final position.
- On the Windows host, save these three files from `.local\companion\`:
  `events.csv` (must contain `COMPANION_MOVE` rows, both `in` and `out`),
  `status.json`, `address.txt`.
- Note the UTC start and end times of the game.
- Stamp completion on the ops log (reply to the operator, as always).

## 7. Put everything back

```powershell
# Stop the companion host: Ctrl+C in its window.

# If the operator wants the pre-test interface shape restored:
cd C:\agents\farcade
Copy-Item .local\prnsd-config\config.pre-couch-tcp .local\prnsd-config\config -Force
Get-CimInstance Win32_Process |
  Where-Object { $_.CommandLine -match 'soak_responder' } |
  ForEach-Object { Stop-Process -Id $_.ProcessId -Force }
Get-Process prnsd -ErrorAction SilentlyContinue | Stop-Process -Force
Start-ScheduledTask -TaskName Farcade-Responder
# Verify 4243 is ESTABLISHED again, then stamp the operator with the restore time.
```

Evidence files and screenshots then go into the repo as
`docs/run-<date>-companion-pixel.md` plus the CSV, following the sprint-1 pattern:
every anomaly attributed, no exceptions.
