# Changelog

Format follows [Keep a Changelog](https://keepachangelog.com/en/1.1.0/).
Versioning is [Semantic Versioning](https://semver.org/): while the wire
format and the Python API are still moving, Farcade stays on `0.y.z` and a
**minor** bump is where a breaking change is allowed to land.

Entries below were reconstructed from the commit history at the point
versioning was adopted, so the earlier releases were never tagged at the
time. Dates are the dates the work landed.

## [Unreleased]

## [0.3.0] - 2026-08-12

Sprint 3. First version to be tagged; the version had sat at `0.0.1`
through three sprints and no longer said anything true.

### Added
- **Serverless lobby (13.7).** Nodes announce a compact signed card on a
  well-known `farcade.lobby` aspect and aggregate what they hear into a
  local list with freshness ages. No registry and nothing to run. The
  address is derived from the card's public key rather than carried, so
  there is no address field to lie in, and the card is self-signed rather
  than envelope-signed so a relay can re-publish it without being able to
  forge it.
- **Lobby announce plumbing.** `farcade.net.lobby_rns`: the destination,
  the card as announce `app_data`, and a handler that turns heard
  announces into lobby entries. A heard card is accepted only when the
  destination derived from its key is the destination the announce
  arrived from, which is what stops a replayer rebroadcasting somebody
  else's genuine card.
- **Meshtastic transport adapter (13.1a)**, exercised over a full 25-ply
  Connect Four game with no radio and without the `meshtastic` package
  installed.
- **Play by typing on a stock client (13.1b).** A human on an unmodified
  Meshtastic client types `play c4` into a channel and gets a playable
  board back in 186 bytes.

### Changed
- `__version__` is now read from installed package metadata instead of
  being a second literal that could drift from `pyproject.toml`.

## [0.2.0] - 2026-08-10

Sprint 2.

### Added
- **Reversi**, validated across 500 chaos games.
- **Minimax bot**, 99/100 against Connect Four and 94/100 against Reversi.
- Atomic metadata writes, and an `rns-key` helper.

## [0.1.0] - 2026-08-09

Sprint 1.

### Added
- LXMF-on-prnsd transport, instrumentation, metrics and a soak harness.
- Chess, Connect Four, the session/game core and the web and TUI panes.

### Verified
- 24-hour soak, and by accident two concurrent 24-hour sessions: 243
  games, zero duplicates, zero gaps, zero desyncs, ~205 ms median latency.

[Unreleased]: https://github.com/jackspace/farcade/compare/v0.3.0...HEAD
[0.3.0]: https://github.com/jackspace/farcade/releases/tag/v0.3.0
[0.2.0]: https://github.com/jackspace/farcade/releases/tag/v0.2.0
[0.1.0]: https://github.com/jackspace/farcade/releases/tag/v0.1.0
