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

## On Linux the bus is not a TCP port, and that gap could have cost us a soak

Added 2026-08-14. Everything above was proven on Windows, where the shared instance really is
TCP 37428. **On Linux, RNS uses an abstract unix socket, `@rns/default`.** The PowerShell recipe
has no equivalent there, so a Linux peer had no documented way to prove its instance owner.

That is not cosmetic. Measured on a third Linux box, 2026-08-14:

    rnsd  pid 906094  unix @rns/default (LISTEN)     <- rnsd owns the bus
    meshchat                                          <- attached to it as a client

Start a Farcade peer on that box and this happens:

    peer's RNS finds @rns/default and attaches as a CLIENT
    LxmfTransport's require_attached guard sees "client"           -> green
    probe_shared_instance.py prints PROBE_ROLE=client, exits 0      -> green
    the game plays, the soak accumulates numbers                    -> green

...against **stock RNS**, which is the one thing this transport exists to refuse. Every guard
passes because none of them ever looked at who was on the other end of the socket.

**Use `scripts/probe_instance_owner.py`.** It names the owning process on both platforms:

    python scripts/probe_instance_owner.py              # exit 0 only if prnsd owns the bus
    sudo python scripts/probe_instance_owner.py         # Linux: needs to read the owner's /proc/<pid>/fd

Exit codes are deliberate: `0` match, `1` mismatch, **`2` could-not-determine — never 0.** A check
that cannot see must not report success.

Proven to go red on real hosts rather than fixtures, 2026-08-14:

    the Windows host     TCP 37428 held by reticulum-meshchat    -> OWNER_NAME=python.exe, MISMATCH, exit 1
    a third Linux box  @rns/default held by rnsd, unprivileged -> UNDETERMINED, exit 2
    a third Linux box  @rns/default held by rnsd, under sudo   -> OWNER_NAME=rnsd, MISMATCH, exit 1
    both hosts, told the truth via --expect           -> MATCH, exit 0

The last line matters as much as the others: a gate that only ever returns red is not a gate.

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

- **`digest sent was rejected` — root-caused and fixed 2026-08-09.** Python RNS
  authenticates shared-instance RPC with `full_hash(transport identity private key)`
  (`Reticulum.py` ~line 356), which assumes every process shares one configdir. prnsd's key
  is the same construction over ITS identity: `sha256` of the raw bytes of
  `<prnsd-config>/storage/transport_identity` (see
  `prns-interfaces/.../rns_rpc/tests/persistence.rs`). A client with its own configdir can
  never match by derivation — but both sides honour an explicit key, so compute
  `sha256(transport_identity bytes)` and set it in each peer's RNS config:

      [reticulum]
        rpc_key = <64 hex chars>

  Verified live: a paced exchange without the key logged dozens of digest errors; the same
  exchange with it logged **zero**, and link-stats/first-hop-timeout RPCs work. Latency was
  unchanged (median 4.01 s both arms), so the errors were cosmetic — but 24 h of clean logs
  and working stats beat 24 h of noise. Note this is interesting for *any* RNS app with its
  own configdir attaching to prnsd (Sideband on a desktop, say): same mismatch, same fix.
- On Windows prnsd logs `shared_instance_unix_fallback fallback="tcp"` — expected; there is
  no unix socket on Windows, TCP 37428 is the intended shape (same as Python RNS).
- `GamePeer` assumes its storage directory exists (test fixtures create it). The runner
  scripts mkdir it; a future tidy could move that into `GamePeer`.
