# Farcade — a turn-based game arcade over low-bandwidth links

**Name: Farcade** (far + arcade — an arcade at a distance). Jack's pick 2026-08-08 from a
PyPI-checked shortlist; `farcade` verified free on PyPI. Known residue: a defunct
Farcaster crypto-gaming platform once used the name — accepted knowingly. P0.1 still runs the
full GitHub/Gitea collision sweep (including case-variants) before anything is created.
Repo: `farcade`. Package: `farcade`.

## Context

Nobody has built a game for Reticulum. The curated `awesome-reticulum` index lists roughly sixty
projects across fourteen categories and has **no games category at all** (checked 2026-08-08).

But novelty is not the reason to build it. On 2026-08-08 the a233 battery run proved we have **no
trustworthy long-running liveness instrument** on this mesh: BLE presence lied for hours in both
directions, three manual scans "confirmed" a death that had not happened, and the only thing that
told the truth was Jack firing announces by hand. A turn-based game is an **ordered, verifiable,
self-generating message log**. Every move carries a ply number, so loss, duplication and reordering
become detectable for free, as a by-product of playing.

So this is two things at once: a genuinely fun peer-to-peer correspondence game platform with chat,
and the unattended application-level soak harness we currently lack.

**It is not a Prns contribution.** Prns is the road; this is a car. Nothing here goes to Ken.

## What changed from the first draft

Three of Jack's calls reshaped it, all in the same direction — **the interesting thing is the
platform, not the chess**:

1. **It is a game hub, not a chess app.** Chess is the first game plugin, not the product.
2. **It is transport-portable.** Reticulum/LXMF first, then Meshtastic, MeshCore, and potentially
   ham packet.
3. **The excluded list became a roadmap.** Everything previously listed as "not in sprint 1" now
   has a tier, so they are scheduled rather than merely deferred.

## Decisions locked

| decision | choice | why |
|---|---|---|
| Language | **Python** | `python-chess` is excellent; `RNS` and `LXMF` are markqvist's own; every other game library we'd want exists here too |
| First transport | **LXMF riding a `prnsd` instance** | Same path Sideband already uses. Fast build *and* the "real app on the Rust stack" demo |
| First game | **Chess** | Best-supported library, and Jack wants to play it |
| Topology | **Pure peer-to-peer** | Two bound peers. No server, no matchmaking, no discovery |
| Interfaces | **TUI *and* local web UI** | Both. See §Interfaces |
| Voice | **Seam in sprint 1, wired in sprint 2** | P40 has tenants (Ollama, other tenants) and needs the operator's sign-off; must not block the harness |
| Hosts | **the Windows host + one Raspberry Pi** | |
| Repo | **A new private repo** | Not Prns work |

## Architecture — four ports and a shell

The insight that makes the hub cheap: **almost nothing in the design was ever chess-specific.**

```
        Game plugin                    Player plug              Voice plug
   (chess, checkers, go)          (human UI / engine)      (null → Ollama, S2)
             │                             │                       │
             └──────────────┬──────────────┴───────────┬───────────┘
                            ▼                          ▼
                 ┌──────────────────────────────────────────┐
                 │                Session core              │
                 │  move log · ply sequence · state hash    │   ← knows no game,
                 │  dup/gap/resync · peer binding           │     no transport, no UI
                 └──────────────────┬───────────────────────┘
                                    ▼
                 ┌──────────────────────────────────────────┐
                 │          Protocol + codecs               │   binary | text
                 └──────────────────┬───────────────────────┘
                                    ▼
                 ┌──────────────────────────────────────────┐
                 │             Transport port               │
                 │   LXMF (S1) · Meshtastic · AX.25 · ...   │
                 └──────────────────────────────────────────┘
```

### The Game port

```python
Game:
    initial_state() -> State
    legal_moves(state) -> [Move]
    apply(state, move) -> State
    outcome(state) -> Outcome | None        # None while in progress
    hash(state) -> bytes                    # divergence detection
    encode_move(move) -> bytes              # compact, transport-budgeted
    decode_move(bytes) -> Move
    render_ascii(state) -> str              # TUI
    render_model(state) -> dict             # web UI
```

Game-agnostic (built once, in the core): the move log, ply sequencing, duplicate and gap handling,
resync, state hashing, peer binding and trust level, chat, instrumentation, both UIs' shells, the
player and voice plugs, and every transport adapter.

Game-specific (per plugin, small): rules, move encoding, rendering.

Move encodings stay tiny across the board — chess fits in 16 bits (6 from, 6 to, 3 promotion), go on
19×19 in 9 bits, checkers around 12, connect four in 3. **A whole game therefore fits in one
Meshtastic packet in most cases**, which keeps the "just send the entire log" resync strategy alive
on constrained links instead of forcing diffing.

### Three load-bearing invariants

1. **State is a pure function of the move log.** The board is derived by replaying an append-only
   log. This collapses persistence, crash recovery, peer resync and idempotency into one mechanism.
2. **Ply number is the sequence number.** `ply < expected` → already applied, ignore silently (the
   duplicate case is *normal*, not an error). `ply == expected` → validate and apply.
   `ply > expected` → gap, request sync.
3. **State hash on every move.** Divergence is caught on the very next ply instead of twenty moves
   later when the game has become nonsense.

### Deliberately out of the tier-1 model

**Randomness** (backgammon, dice) needs a deterministic shared RNG or commit-reveal, and **hidden
information** (card games) needs commitment schemes. Both are real designs, not small ones. They are
on the roadmap at tier 4 and the `Game` port above does **not** pretend to support them.

## Transport portability

```python
Transport:
    address -> str
    send(peer: str, payload: bytes)
    on_receive(cb)
```

| transport | payload ceiling | addressing | encryption | delivery |
|---|---|---|---|---|
| Reticulum / LXMF | effectively unbounded | cryptographic identity | E2E, free | store-and-forward, delay tolerant |
| Meshtastic | **~230 bytes** | node id + channel | channel PSK (shared, not per-peer) | best effort |
| MeshCore | small | node id | varies | best effort. **Least mature — spike before promising** |
| Ham / AX.25 / APRS | ~256 byte frames | callsign | **must be plaintext** | best effort |
| SMS | **160 chars** (GSM-7) | phone number | none | carrier store-and-forward |
| Telegram | generous | bot API chat id | transport-level | reliable, ordered |
| WhatsApp | generous | Business API only | E2E | reliable. **Highest friction — see roadmap** |

The messaging trio slots straight into the same port, and each earns a different tier:

- **Telegram** is the easy one: a first-class bot API, no gatekeeping, and it doubles as the
  "play against your friend who has installed nothing" on-ramp.
- **SMS** is the philosophically perfect one — a move in our text codec fits a single 160-char
  message with room for chat, which is the whole low-bandwidth thesis restated in carrier form.
  Needs a gateway (an Android phone as bridge, or Twilio-style service).
- **WhatsApp** is the hard one, and honesty first: there is no personal-account bot API. The
  lawful path is the Business API (cost, approval), and the unofficial libraries violate ToS and
  get numbers banned. It stays on the roadmap as "Business API or not at all."

**Two codecs, one protocol.** A binary codec for efficiency, and a **text codec** that makes a move
a plain readable line. The text codec buys two things nearly free: a human on a **stock Meshtastic
client** can play a bot by typing in a channel, and it is the lawful shape on amateur bands where
obscuring meaning is prohibited.

**Trust degrades explicitly, never accidentally.** Peer authentication is a property of the
transport — cryptographic on Reticulum, a shared channel key on Meshtastic, a callsign and nothing
else on ham. That level must be stated in config and logs. "Trusted by convention" is fine for a
game; *pretending* it is authenticated when it is not is not fine.

**The ham caveat, honestly**: the blocker is regulatory, not bandwidth. Amateur rules generally
prohibit transmissions intended to obscure meaning, which is in direct tension with LXMF's always-on
encryption; the text codec over plain KISS/AX.25 is the lawful shape. **Ham use answers to the local regulator,
not FCC Part 97** — any ham track gets a regulatory gate answered by a
licensed operator before code. RNS appears to ship KISS/AX.25-style interfaces, which would make
this mostly a legal question; **that needs verifying, not assuming.**

## Interfaces

Both, because they serve different jobs. The critical point: **the UI is entirely local. Only moves
cross the link.** Low bandwidth puts no constraint whatsoever on how rich the interface is.

- **TUI** — unicode board, keyboard driven, works over SSH. This is how you play on the Pi without
  exposing a port, and it doubles as the debugging view.
- **Local web UI** — small HTTP server on the peer serving a click-driven board plus a chat pane.
  Open from the S24 or any laptop, no install. This is the one that is actually pleasant.
- **CLI** — built regardless; headless soak on the Pi needs it.

All three sit on **one local API** (HTTP + websocket) exposed by the peer process. That is the seam
that keeps three front-ends from becoming three implementations, and it is what a native app or a
NomadNet page would later hang off too.

## Sprint 1 — work breakdown

Model = which Claude model does the work. Cheap tier by default; opus reserved for judgment.
Size: S ≈ under an hour, M ≈ a few hours, L ≈ most of a day.

### P0 — Repo and scaffolding

| ID | task | acceptance / QA | model | size |
|---|---|---|---|---|
| 0.1 | Name check (PyPI, GitHub, Gitea) then create the repo; check for **case-variants** | No collision; clone succeeds | haiku | S |
| 0.2 | Move the spec in, reconciled to the final name and the hub framing | Consistent throughout | haiku | S |
| 0.3 | Package skeleton, `pyproject.toml`, `.gitignore`, README | `pip install -e .` succeeds | haiku | S |
| 0.4 | Pin deps: `rns`, `lxmf`, `chess`, `httpx`, TUI lib | Clean venv on the Windows host **and** the Pi (arm64) | haiku | S |
| 0.5 | Gate script: format, lint, tests | Green on empty suite **and proven red** on a planted failing test | sonnet | M |

### P1 — Session core (no game, no network)

| ID | task | acceptance / QA | model | size |
|---|---|---|---|---|
| 1.1 | **`Game` port definition** | Core imports no game module; enforced by an import test | **opus** | S |
| 1.2 | Append-only move log, replay-to-state | `replay(log)` equals live state across 100 random games | sonnet | M |
| 1.3 | **Ply sequencing and the apply rule** (dup / gap / ok) | Same move twice is a no-op; table-driven tests over all three branches | **opus** | M |
| 1.4 | State hashing and divergence detection | Hash differs for states differing only in side-to-move and castling rights | sonnet | M |
| 1.5 | Crash recovery by replay | Kill mid-game, restart, identical state | sonnet | S |
| 1.6 | Property tests for the core | Idempotency and replay-equivalence under randomised orders | sonnet | M |

### P2 — Chess plugin

| ID | task | acceptance / QA | model | size |
|---|---|---|---|---|
| 2.1 | Chess `Game` implementation over `python-chess` | Full rules incl. threefold, 50-move, promotion, en passant | sonnet | M |
| 2.2 | 16-bit move codec | Round-trips every legal move in 10k random games | sonnet | S |
| 2.3 | **A second trivial game (connect four or tic-tac-toe)** | **Proves the port is real.** One game is not an abstraction; two is | sonnet | M |

P2.3 is not filler. An interface with a single implementation is a guess.

### P3 — Protocol, codecs, transport port

| ID | task | acceptance / QA | model | size |
|---|---|---|---|---|
| 3.1 | **Transport port interface** | Core and protocol import nothing transport-specific | **opus** | S |
| 3.2 | Envelope + binary codec | Round-trips every type; 80-ply chess log under **200 bytes** | sonnet | M |
| 3.3 | Text codec | Human-readable; parses sloppy human input (case, spacing) | sonnet | M |
| 3.4 | **Size budget test** | Every message fits 200 bytes or documents its chunking; **fails loudly** on regression | sonnet | S |
| 3.5 | **Session state machine**: INVITE/ACCEPT, MOVE, SYNC, REJECT, RESIGN | Full game drives cleanly; every failure mode has a test | **opus** | L |
| 3.6 | **Peer binding + explicit trust level** | Third-party message with a valid game id dropped with **no reply**; trust level in config and logs | **opus** | M |
| 3.7 | **Adversarial channel harness** — duplication, reordering, loss, desync, truncation | 1000 games over a channel dropping/duplicating/reordering 10% each, zero desyncs; **harness proven to break a naive implementation** | **opus** | L |

P3.7 is the most valuable artifact in the sprint. It turns "it worked once" into evidence.

### P4 — LXMF transport

| ID | task | acceptance / QA | model | size |
|---|---|---|---|---|
| 4.1 | LXMF adapter implementing the port | Two peers on one box exchange a message | sonnet | M |
| 4.2 | Attach to `prnsd`; document topology | Confirmed via prnsd, **not** a stock RNS fallback. Watch **port 37428** contention | sonnet | M |
| 4.3 | Loopback full game | Engine vs engine reaches checkmate locally | sonnet | S |

### P5 — Players and local API

| ID | task | acceptance / QA | model | size |
|---|---|---|---|---|
| 5.1 | `Player` + `Voice` protocols (voice seam only) | Null voice returns `None`; game unaffected | sonnet | S |
| 5.2 | UCI engine adapter (Stockfish) | Strength configurable; engine crash is a clean error, never a corrupt move | sonnet | M |
| 5.3 | **Local API** (HTTP + websocket) that all front-ends use | One API drives CLI, TUI and web | **opus** | M |
| 5.4 | CLI player | Illegal input re-prompts, never desyncs the log | sonnet | S |
| 5.5 | **TUI** board + chat | Playable over SSH end to end | sonnet | L |
| 5.6 | **Web UI**, click-driven board + chat | Playable from the S24 with no install; legal squares highlight | sonnet | L |
| 5.7 | Voice adapter shell, OpenAI-compatible, **not wired** | Timeout and failure degrade to silence; **prove a game completes with the endpoint pointed at a black hole** | sonnet | M |

### P6 — Instrumentation and soak

| ID | task | acceptance / QA | model | size |
|---|---|---|---|---|
| 6.1 | Event CSV: `ts, gid, dir, type, ply, latency_s, dup, gap, hash_ok, peer` | One row per message, both directions | haiku | S |
| 6.2 | Metrics report: latency, dup/reorder/loss, desyncs, longest silence survived | Reproduces known values from a **synthetic log with injected faults** | sonnet | M |
| 6.3 | Soak runner: min interval, ply cap, game cap | Rate limit provably honoured; caps stop the run | sonnet | M |
| 6.4 | **24h soak, the Windows host ↔ Pi** | Completes or is explained; every anomaly attributable | sonnet | L |

### P7 — Review and write-up

| ID | task | acceptance / QA | model | size |
|---|---|---|---|---|
| 7.1 | Adversarial review | Each finding verified before acting — audit findings are hypotheses | **opus** | M |
| 7.2 | README, deploy guide, soak evidence | A stranger can stand up two peers from the docs alone | sonnet | M |
| 7.3 | Whether any of it goes public | **Nothing public without Jack's explicit yes** | — | — |

## Roadmap

Everything previously listed as "not in sprint 1" now has a home.

**Tier 1 — next sprint**
- Voice / inference wired to Ollama on the P40 (ask the operator first). Engine moves, model talks. One P40
  serves both peers because turn-based play is strictly alternating.
- Checkers or draughts as the third game plugin.
- Meshtastic transport adapter, including the "human on a stock client plays a bot" path.
- Web UI polish: move history, resign/draw, board flip.

**Tier 2 — once the platform is proven**
- **Multiple concurrent games** (the session core is already keyed by game id; this is mostly UI).
- **Time controls**, including correspondence-style multi-day clocks.
- **Go** — bigger state, harder scoring, excellent stress test for the `Game` port.
- **Spectators** — read-only followers of a game log.
- **Telegram transport** — first-class bot API, no gatekeeping; the zero-install on-ramp for
  playing against someone with nothing but a phone.

**Tier 3 — ecosystem**
- **N-player sessions** — the Risk unlock. Everything up to here binds exactly two identities;
  Risk, Diplomacy and most classic strategy board games want three to six. What changes is the
  session layer, not the games: turn order becomes part of logged state, commit-reveal randomness
  generalises cleanly (everyone commits, XOR all reveals — no player can bias it), and the hard
  part is **dropout policy**: what happens when one of five players goes silent for a week. Postal
  gaming solved this socially (Diplomacy's NMR rules); we adopt a policy, we do not invent
  distributed consensus. Two-player ships first precisely so this lands on a proven core.
- **Risk-class strategy games** — once N-player exists, Risk itself is just a `Game` plugin: dice
  are primitive 1, territory state is ~100 bytes, and a multi-action turn (reinforce, attacks,
  fortify) is simply a batch of log entries under one ply.
- **Matchmaking and discovery** — a lobby, which is the first thing here that needs more than two
  peers *before* a game even starts.
- **Ratings and tournaments.**
- **NomadNet page** front-end, served over Reticulum in micron.
- **Sideband integration.**
- **Opening books** and engine analysis.
- **Ham / AX.25** — gated on the regulatory question above.
- **SMS transport** — one move per 160-char message via a gateway (Android bridge or Twilio-style);
  the low-bandwidth thesis in carrier form.

**Tier 4 — the mechanics that unlock whole genres**

Card games, dice, casino and simultaneous-move games all reduce to three primitives, and all three
are cheap on the wire (a hash or two per turn — inside our 200-byte budget). None require a server
or a trusted third party except where noted.

1. **Shared randomness — commit-reveal.** Each peer commits `hash(nonce)`, then reveals; XOR of the
   nonces is the dice roll. Neither side can bias it, and it costs two small messages.
   *Unlocks: backgammon, Yahtzee, Can't Stop, any dice game.*
2. **Simultaneous moves — the same commit-reveal.** Both commit their move's hash, then both
   reveal. Nobody moves second.
   *Unlocks: rock-paper-scissors, Diplomacy-style orders, simultaneous auctions.*
3. **Hidden information — commitments, in two very different weight classes:**
   - **Easy class**: the secret is fixed at game start and checkable at game end. Commit the
     hash up front, reveal when it matters, replay verifies nobody cheated.
     *Unlocks: Battleship (the textbook case), Wordle-style word duels, hangman, Stratego-lite.*
   - **Hard class**: **peer-to-peer poker**, where cards must be dealt from a shared deck that
     nobody sees. This is "mental poker" (SRA and successors) — genuinely solved in the
     literature, genuinely heavyweight in practice. Research tier, honestly labelled.

**Casino games are the surprise easy case** — because a casino has a *house*. Blackjack, roulette
or slots against a house bot use the provably-fair pattern: house commits `hash(seed)` before your
bet, player supplies a client seed, outcome derives from both, reveal proves it after. One
commitment per round, trivially inside budget. (Real stakes would raise legal questions we are not
touching; this is for chips that mean nothing.)

Also tier 4:
- **MeshCore**, pending a maturity spike.
- **WhatsApp transport** — Business API or not at all; unofficial libraries violate ToS and get
  numbers banned.

**What genuinely does NOT fit slow links**, recorded so nobody wastes a weekend: anything real-time
(twitch/arcade action, RTS), anything needing voice/video, and games whose state per turn is
inherently large. The dividing line is simple — **if a turn fits in a text message and nobody needs
an answer in under a minute, it works here.** That covers a startling fraction of all games humans
have ever played by mail: chess, go, Diplomacy, and the entire postal-gaming tradition are the
existence proof.

## QA principles — every phase, not a phase

- **Every gate must be proven to fail on known-bad input.** A check that returns green having
  examined nothing is the worst bug class we have hit. No gate is accepted until someone has watched
  it go red on purpose.
- **Every negative result needs a positive control near the margin.** On 2026-08-08 three BLE scans
  "confirmed" a dead board while their control sat 45 dB stronger than the target. Proving the
  instrument is powered is not proving it can see.
- **Repeating a blind measurement does not make it sighted.**
- **Report what ran, on what host, and what was skipped.**

## Verification

1. Gate green, and demonstrated red on a planted failure.
2. **Two game plugins** (P2.3) — the `Game` port is exercised, not asserted.
3. **Adversarial channel** (P3.7): 1000 games, lossy/duplicating/reordering, zero desyncs.
4. **Size budget** (P3.4): every message inside 200 bytes or explicitly chunked.
5. **Loopback game** (P4.3): engine vs engine to checkmate.
6. **Real two-host game**: the Windows host ↔ Pi over prnsd; log replay on both sides yields identical final
   states **and identical hashes**.
7. **Failure injection**: pull the Pi's network mid-game; the game resumes and reconciles, with the
   gap visible in the event CSV.
8. **Black-hole voice test** (P5.7).
9. **24h soak** (P6.4) with every anomaly attributable.

## Risks

| risk | severity | mitigation |
|---|---|---|
| Silent state divergence | **High** — destroys the premise | Hash every move; P3.7 harness |
| P3.7 harness weaker than it looks | **High** | Must break a naive implementation or it is theatre |
| Hub abstraction is a guess | **High** | P2.3 second game in sprint 1, not later |
| Three front-ends diverge | Medium | P5.3 single local API before any UI is written |
| prnsd port contention (37428) | Medium | Settle topology in P4.2 |
| Ham track on wrong assumptions | Medium | Regulatory gate first, Mexican rules, licensed operator |
| Scope creep — the roadmap is long | Medium | Sprint 1 ships a playable two-host chess game with evidence. Everything else is tiered |

## Name research trail (settled)

- **Chessticulum** — dropped when the scope grew past chess and past Reticulum.
- **Ply** — researched deeply and out: PyPI `ply` is David Beazley's 25-year-old Python Lex-Yacc,
  a transitive dependency of half the ecosystem via `pycparser`, and PLY is also the Stanford 3D
  file format. Uninstallable and unsearchable under that name.
- **Parley** — PyPI name taken, and linebender/parley is a prominent active Rust library.
- **Farcade** — chosen from a ten-name, PyPI-verified arcade-themed batch (all free except
  `turnpike`). Runners-up: Slowcade, Telecade, Longplay.
