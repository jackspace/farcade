# Farcade

**An arcade at a distance.** Turn-based games — chess first — played peer-to-peer over
low-bandwidth, high-latency links: Reticulum/LXMF today, Meshtastic, SMS, packet radio and
others on the roadmap. With chat, because the conversation is half the point.

Every game doubles as evidence: moves are an ordered, ply-numbered, hash-verified message log,
so a running game continuously measures delivery latency, duplication, reordering and loss on
whatever link carries it. Farcade is a correspondence game platform and an unattended
network soak harness wearing each other's clothes.

## What it looks like

Chess in the browser — a real stalemate found at ply 83, chat and all:

![Chess to stalemate in the Farcade web UI](docs/screenshots/chess-stalemate-ply83-jack-2026-08-10.png)

Reversi mid-game — legal squares highlighted, forced-pass aware, live disc count:

![Reversi in the Farcade web UI](docs/screenshots/reversi-demo-2026-08-10.png)

## Design in one breath

State is a pure function of an append-only move log. The ply number is the sequence number.
Every move carries a hash of the resulting state, so divergence is caught on the next ply.
Games, players, voices and transports are all plugins behind narrow ports; the session core
knows none of them.

- **Spec**: [docs/spec.md](docs/spec.md)
- **Sprint 1 plan and work breakdown**: [docs/sprint-1.md](docs/sprint-1.md)
- **Deploying two peers over Reticulum/prnsd**: [docs/deploy-two-peers.md](docs/deploy-two-peers.md)
- **Why prnsd owns port 37428, with evidence**: [docs/topology-prnsd.md](docs/topology-prnsd.md)

## Status

Sprint 1 nearly complete (2026-08-09): P0–P6 landed — two game plugins, adversarial channel
harness (1000 lossy games, zero desyncs), LXMF transport over prnsd proven cross-host
(the Windows host ↔ Pi, engine chess to checkmate with identical hashes both sides), instrumentation
CSV + metrics + paced soak runner. A 24 h Windows ↔ Pi soak (P6.4) is running. Interfaces are
not stable yet.

## Quick start (will firm up as sprint 1 lands)

```bash
python -m venv .venv && . .venv/bin/activate   # or .venv\Scripts\activate on Windows
pip install -e ".[dev]"
bash scripts/gate.sh                            # format, lint, tests
```
