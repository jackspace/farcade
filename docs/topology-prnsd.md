# P4.2 — the prnsd topology, settled

Decided and proven 2026-08-09 on the Windows host (Windows 11). This answers the sprint-1 open question
"which prnsd instance, and the 37428 contention question."

## The decision

**prnsd owns the machine's RNS shared instance on port 37428. Every Farcade peer is its own
process whose Python RNS attaches to prnsd as a shared-instance client.** This is exactly the
path Sideband uses (prnsd's README says so in as many words: apps "connect to it exactly as
they connect to `rnsd` today").

```
   farcade peer A (python, rns 1.4.2)  ──┐
                                         ├── localhost TCP 37428 ──  prnsd 0.3.3 (Rust)
   farcade peer B (python, rns 1.4.2)  ──┘                           owns the bus + all interfaces
```

The 37428 contention question dissolves into a start-order rule: **prnsd starts first.**
Python RNS only ever *becomes* the instance owner if the port is free when it starts; if
prnsd is already there, RNS attaches as a client and never touches an interface. The
Sideband/Hopspot Android conflict from the courier notes is the same port fought over by two
would-be owners; on our hosts there is exactly one owner and it is prnsd, by rule.

## Why this cannot silently degrade

Two independent guards, both proven to go red:

1. **`LxmfTransport` raises `NotAttachedToSharedInstance`** at startup when its RNS came up
   as the owner (i.e. prnsd was not there). A game literally cannot start on a stock-RNS
   fallback with the default `require_attached=True`.
2. **`scripts/probe_shared_instance.py`** reports the observed role and exits nonzero on a
   mismatch. Run 2026-08-09: with prnsd up → `PROBE_ROLE=client`, exit 0; against a bus port
   nothing owned → `PROBE_ROLE=owner`, exit 1. The gate fails on known-bad input.

Why "client" is enough to mean "via prnsd": Python RNS brings up configured interfaces only
when it is the shared-instance owner or standalone (`Reticulum.py`, the
`if self.is_shared_instance or self.is_standalone_instance` branch around line 718 in
rns 1.4.2). A client's only pipe is the local socket to the instance owner — there is no
second path the traffic could have taken. To pin the owner to prnsd specifically, check the
port at the OS level (PowerShell):

    Get-NetTCPConnection -State Listen -LocalPort 37428 | Select LocalAddress,LocalPort,OwningProcess
    # OwningProcess must be prnsd's PID

## The evidence (all under .local/, 2026-08-09)

- **P4.1** two processes exchanged ping/pong over LXMF: both artifacts
  `attached_as_client: true`, both messages delivered, `dropped_sends: 0`.
- **P4.3** full chess game, Stockfish 18 (skill 20, white) vs Stockfish 18 (skill 0, black),
  through prnsd: 45 plies to **checkmate**, both peers `finished/checkmate`, and the final
  state hash is **identical on both sides** (`253fc99f093ec8eb`). 23 messages out / 22 in on
  the initiator, mirror image on the responder, zero dropped sends.

## Running prnsd on the Windows host

Release binary, not a local build: `prnsd-0.3.3-x86_64-pc-windows-msvc.zip` from the
upstream v0.3.3 release, SHA256 checked against `SHA256SUMS.txt` and the sums file
minisign-verified against the release `minisign.pub`. Lives under
`.local/prnsd-0.3.3/`, config under `.local/prnsd-config/`.

**The config disables every interface, and that is load-bearing on this bench:**

    [reticulum]
    enable_transport = Yes
    share_instance = Yes
    [interfaces]
      [[Default Interface]]   type = AutoInterface        interface_enabled = No
      [[USB Auto]]            type = PrnsUsbAuto          interface_enabled = No
      [[Bluetooth Auto]]      type = PrnsBluetoothAuto    interface_enabled = No

prnsd's defaults enable USB Auto and Bluetooth Auto. On first start they came up and USB
Auto connected to something within seconds. On a bench with live experiments that is not a
default, it is a hazard: USB Auto opens COM ports (opening an ESP32-S3's port resets the
board) and Bluetooth Auto dials Hopspot boards (a BLE connection changes a board's power
draw — fatal to a battery runtime measurement). **Disable the radios before first `run`,**
or run first in a sandboxed config dir as done here:

    prnsd.exe interfaces disable 'USB Auto' --config <dir>
    prnsd.exe interfaces disable 'Bluetooth Auto' --config <dir>
    prnsd.exe interfaces disable 'Default Interface' --config <dir>
    prnsd.exe run --config <dir>

For the two-host soak (P6.4, the Windows host ↔ Pi) the Pi side uses the
`prnsd-0.3.3-aarch64-unknown-linux-gnu.tar.gz` release asset the same way, and the two
prnsd instances will need one real interface towards each other (TCP or LoRa) — that
interface gets enabled *on the prnsd side*, never on the peers.

## Known warts

- Python RNS logs `Shared instance RPC failed ... digest sent was rejected` when attached to
  prnsd 0.3.3 (rns 1.4.2 tries to report destination stats over the control port and prnsd
  rejects the digest). Cosmetic for us: announces, path resolution and LXMF delivery all
  work, proven by the artifacts above. Worth watching across upstream versions.
- On Windows prnsd logs `shared_instance_unix_fallback fallback="tcp"` — expected; there is
  no unix socket on Windows, TCP 37428 is the intended shape (same as Python RNS).
- `GamePeer` assumes its storage directory exists (test fixtures create it). The runner
  scripts mkdir it; a future tidy could move that into `GamePeer`.
