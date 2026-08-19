# Changelog

Format follows [Keep a Changelog](https://keepachangelog.com/en/1.1.0/).
Versioning is [Semantic Versioning](https://semver.org/): while the wire
format and the Python API are still moving, Farcade stays on `0.y.z` and a
**minor** bump is where a breaking change is allowed to land.

Entries below were reconstructed from the commit history at the point
versioning was adopted, so the earlier releases were never tagged at the
time. Dates are the dates the work landed.

## [Unreleased]

The next release is **0.4.0**, not 0.3.1: `bot_factory` gained a difficulty
argument and its callers moved with it, which is a breaking change to a public
contract, and 0.y.z puts those in the minor.

### Added
- **A hub where each player is a person.** `farcade hub` stands up one
  attachment and one router with a Reticulum identity, a game store and a
  `Node` per player, so two people in one house are two people to everyone they
  play rather than one shared address. Inbound is demultiplexed by the
  destination the message arrived at; anything addressed to a destination this
  hub does not serve is dropped rather than handed to whoever is around, because
  guessing there would be forgery and not routing. Player identities persist and
  re-register on startup, so a restart does not leave real people unreachable at
  addresses they already gave out.
- **A player is a Reticulum identity, not a password.** Proving you are a player
  means signing a hub-issued challenge with the key that player holds - the same
  primitive that authenticates everything else on the network, rather than a
  second credential system beside it. The challenge is bound to the player and to
  Farcade, so a signature harvested from somewhere else is not an answer, and it
  is consumed whether or not the signature was good, so a captured nonce buys one
  attempt rather than unlimited guesses.
- **Hub custody and self custody, on one verification path.** Hub custody is the
  family and club case, where a nine year old should not have to manage a
  keypair: the browser is authorised by a claim code and the hub answers its own
  challenge with the key it holds. Self custody is the player holding their own
  key, which is what a league spanning hubs needs, since a hub-held signature
  cannot be proof against the hub itself. Both walk the identical path, so the
  second is an upgrade rather than a migration. **The claim code is a bearer
  secret**, and exactly as strong as the hub's custody of the key already was.
- **Difficulty levels.** `easy` / `medium` / `hard`, mapped to Stockfish's own
  0-20 skill scale and to minimax depth for the games with no engine. Companion
  mode understands them in passing - "play chess easy" and a few synonyms - and
  only while a game is being started, so it can never swallow a move.
- **`farcade doctor`.** Checks the four things a seat needs at once: something
  listening on the shared-instance port, an instance config it can actually find,
  a derivable RPC key, and a chess engine on PATH. Exit 1 with numbered fixes. It
  deliberately does not name which implementation owns the socket, because from
  outside prnsd and rnsd are indistinguishable and a doctor that guesses is worse
  than one that reports only what it checked.

- **CI.** GitHub Actions runs `scripts/gate.sh`, the same gate as the bench,
  on push and pull request, against Python 3.10 and 3.13 with a real chess
  engine installed.
- **A new game button** in the web UI: a rematch against the same opponent, so
  nobody retypes a 32-character address to play again.
- **"Your move" in the browser title**, because at correspondence pace the tab
  is usually in the background.
- **Companion games reach the instrument.** `events.csv` gains
  `COMPANION_MOVE` rows in both directions, correlated from the host's
  own events, so a companion soak is no longer invisible to the CSV.
- **`scripts/companion_host.py`.** The live entry point P9 never got: a
  companion node attached to prnsd (refuses to run standalone), with
  instrumented CSV, status heartbeat, and periodic announces. Stock
  Sideband on a phone can now actually reach companion mode; the live
  Pixel acceptance is the remaining step.

### Changed
- **`bot_factory` takes a difficulty level explicitly** rather than having one
  sniffed for it, and its callers move with it. **Breaking**, and the reason the
  next release is a minor.
- **The default opponent is medium, not the ceiling.** `default_bot` never passed
  `skill_level`, so the chess bot was Stockfish at its default setting, far above
  any human. Think time drops with skill too, because a weak opponent that stalls
  feels broken rather than easy.
- **The transport finds the running shared instance itself** - `FARCADE_RNS_CONFIG`,
  then Reticulum's default `~/.reticulum` - derives the RPC key and seeds its own
  client config before RNS reads it. `--rpc-key` still works and
  `--instance-config` still points at a daemon living elsewhere, but neither is
  required. A test pins our key derivation against the installed RNS, since
  `full_hash(transport_identity.get_private_key())` was always Reticulum's own
  scheme rather than a prnsd convention - which is why the same code attaches to
  rnsd.
- **Attach logic is shared between the hub and the single seat** rather than
  duplicated. Finding the daemon is the same question for one player or twelve.

### Fixed
- **Every browser on a seat was the same identity.** The API held a single `Node`
  from construction, which is right for a personal seat and is the exact bug a hub
  exists to fix: a result belonged to the machine rather than to whoever played
  it. Routes now look the player up from the session token the browser carries.
- **`farcade doctor` no longer prints ok for an `--instance-config` it never
  found.** The first cut said ok for any path the caller passed - a green that
  examined nothing, which is the bug class this project keeps meeting. It claims
  ok only for a directory seen on disk, and a test holds it there.
- **The error for becoming the instance owner says so.** Attaching to stock RNS
  was never the failure; becoming the OWNER is - a private stack that talks to
  nobody and measures nothing while looking like it works.

- **A restart no longer abandons the game in progress.** `resume_all()` was
  built, tested, and then called by nothing that ships: every entry point
  created a peer, wrote its games faithfully, and started empty. `Node` now
  resumes at construction, and the companion host resumes its conversational
  games too. Found by restarting a live seat mid-game.
- **The companion plays the protocol games it accepts.** Its own docstring
  promised protocol peers worked through the same address, but the `Node` it
  built had no auto player, so `tick()` returned on its first line: a peer
  could invite the host, receive the accept, and wait forever. Only the
  conversational path ever had a bot.
- **A voice comment can no longer kill a node.** A 295-byte comment reached
  the encoder unclamped and the wire's one-byte length prefix raised
  `WireError`, unwinding the process mid-game. Chat is now clamped at the one
  seam every source funnels through, measured in bytes against a ceiling
  derived from `BUDGET` and the codec's own framing, and the voice path
  catches what it can still throw.

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
