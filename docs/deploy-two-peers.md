# Deploying two Farcade peers over Reticulum (P7.2)

Everything below was run for real on 2026-08-09 (the Windows host, Windows 11 + the Pi, Pi4 aarch64).
Commands are given for the host they ran on. Paths are examples; use your own.

## 0. What you are building

```
  peer A (python) ──┐                               ┌── peer B (python)
                    ├── shared instance :37428 ── prnsd (owns all interfaces)
  same box, or ─────┘                               └── or another box, via a
                                                        TCP interface on prnsd
```

One prnsd per site owns the RNS shared instance; every Farcade peer is its own process
attached to it as a client. Full rationale and evidence: [topology-prnsd.md](topology-prnsd.md).

## 1. Install Farcade (every host)

```bash
git clone <this repo> farcade && cd farcade
python3 -m venv .venv && . .venv/bin/activate    # .venv\Scripts\activate on Windows
pip install -e .
python -m pytest -q                               # 127 passed expected
```

Optional: install a UCI engine (`stockfish` on PATH) if you want engine players.

## 2. Stand up prnsd (one per site)

Download the release for your platform from the Prns releases page
(`prnsd-<ver>-x86_64-pc-windows-msvc.zip`, `prnsd-<ver>-aarch64-unknown-linux-gnu.tar.gz`, ...),
plus `SHA256SUMS.txt`, `SHA256SUMS.txt.minisig` and `minisign.pub`. Verify before running:

```bash
minisign -V -p minisign.pub -x SHA256SUMS.txt.minisig -m SHA256SUMS.txt
sha256sum -c --ignore-missing SHA256SUMS.txt
```

**Before the first `run`, disable the interfaces you do not want.** The defaults enable USB
Auto and Bluetooth Auto, which will open serial ports (resetting ESP32-S3 boards) and dial
BLE Hopspots. On any bench with live hardware, opt in, never out:

```bash
prnsd interfaces disable 'USB Auto'          --config ./prnsd-config
prnsd interfaces disable 'Bluetooth Auto'    --config ./prnsd-config
prnsd interfaces disable 'Default Interface' --config ./prnsd-config   # LAN autodiscovery
prnsd run --config ./prnsd-config
```

Startup log must show `shared_instance_started bus_port=37428`. **prnsd starts before any
peer, always**: a peer that starts first becomes the instance owner itself, and Farcade's
transport refuses to run that way (`NotAttachedToSharedInstance`).

## 3. Give peers the RPC key (recommended)

Python RNS authenticates shared-instance RPC by a key derived from a shared configdir the
peers do not share with prnsd. Compute prnsd's key and set it explicitly in every peer's
RNS config (details in [topology-prnsd.md](topology-prnsd.md)):

```bash
python3 -c "import hashlib,sys;print(hashlib.sha256(open(sys.argv[1],'rb').read()).hexdigest())" \
    ./prnsd-config/storage/transport_identity
# put the result in each peer's rnsconfig/config:
#   [reticulum]
#     rpc_key = <that hex>
```

Without it everything still works, but the peer logs `digest sent was rejected` on every
stats RPC. With it: zero (verified live, both arms).

## 4. Two peers, one box: the smoke test

Terminal 1 (responder, accepts invites, plays random moves instantly):

```bash
python scripts/soak_responder.py ./run-b
# prints: responder address: <32 hex>   attached=True
```

Terminal 2 (initiator, paced games against that address):

```bash
python scripts/soak_initiator.py ./run-a <responder-address> --hours 0.05 --interval 2
```

Three minutes later the initiator prints a metrics report. Healthy looks like:
`duplicates: 0, gaps: 0, desyncs: 0`, latency of a few seconds. Both sides also write
`events.csv` (one row per message; see `farcade/instrument.py` for columns) and
`status.json` (updated every minute).

## 5. Second box, via prnsd

On the remote host, run the responder on a **standalone** RNS with a TCP server. Its config
(`run-b/rnsconfig/config`, create before first start):

```ini
[reticulum]
  share_instance = No
  enable_transport = No
  panic_on_interface_error = No

[interfaces]
  [[Farcade TCP Server]]
    type = TCPServerInterface
    interface_enabled = True
    listen_ip = 0.0.0.0
    listen_port = 4243
```

(Standalone is the polite shape when the host already has its own Reticulum stack, because nothing
is shared, nothing is fought over. The responder passes `require_attached=False` for exactly
this case.)

Then point the prnsd site at it:

```bash
prnsd interfaces add TCPClientInterface --name 'Farcade Link' \
    --target-host <remote-ip> --target-port 4243 --config ./prnsd-config
# restart prnsd; log shows TcpClient ... connection=Connected
```

Start the responder on the remote host, the initiator locally (same commands as §4, real
hours this time). The initiator actively path-requests, so it finds a responder whose
announce predates the link.

## 6. Judging a run

```bash
python -m farcade.metrics <workdir>/events.csv
```

- `duplicates` / `gaps` are the channel misbehaving, and the protocol absorbs both (that is
  what the harness proves), so nonzero values are *measurements*, not failures.
- `desyncs` nonzero is a real failure. File a bug with both sides' `events.csv`.
- `longest_silence_s` across a multi-hour run is the number that tells you whether the link
  or a peer ever went away.
- A finished run writes `final.json` (runner state + full metrics) next to the CSV.
