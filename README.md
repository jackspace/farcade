# Farcade

**An arcade at a distance.** Turn-based games — chess first — played peer-to-peer over
low-bandwidth, high-latency links: Reticulum/LXMF today, Meshtastic, SMS, packet radio and
others on the roadmap. With chat, because the conversation is half the point.

Every game doubles as evidence: moves are an ordered, ply-numbered, hash-verified message log,
so a running game continuously measures delivery latency, duplication, reordering and loss on
whatever link carries it. Farcade is a correspondence game platform and an unattended
network soak harness wearing each other's clothes.

## Design in one breath

State is a pure function of an append-only move log. The ply number is the sequence number.
Every move carries a hash of the resulting state, so divergence is caught on the next ply.
Games, players, voices and transports are all plugins behind narrow ports; the session core
knows none of them.

- **Spec**: [docs/spec.md](docs/spec.md)
- **Sprint 1 plan and work breakdown**: [docs/sprint-1.md](docs/sprint-1.md)

## Status

Sprint 1 in progress (2026-08-08). Nothing here is stable yet.

## Quick start (will firm up as sprint 1 lands)

```bash
python -m venv .venv && . .venv/bin/activate   # or .venv\Scripts\activate on Windows
pip install -e ".[dev]"
bash scripts/gate.sh                            # format, lint, tests
```
