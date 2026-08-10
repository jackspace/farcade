# Farcade — sprints 2, 3, and 4

## Context

Sprint 1 is complete through P6 (two game plugins, adversarial harness, LXMF over prnsd
proven cross-host, instrumentation, and a double 24h soak with zero desyncs). Jack picked
the "one new game, one new audience" bundle as the ASAP target: Reversi, plus playing
Farcade from stock Sideband with nothing installed. These three sprints package that first,
then the reach items (Meshtastic, voice, Docker), then the tier-4 primitives that unlock
dice, simultaneous-move, and hidden-information games.

Format matches `C:\agents\farcade\docs\sprint-1.md` (the WBS becomes `docs/sprint-2.md`
etc. in the repo when approved). Model = which Claude tier does the work; size S under an
hour, M a few hours, L most of a day.

**Serverless matchmaking (Jack's ask, 2026-08-10): the lobby is an announce, not a place.**
A Farcade node seeking games periodically announces a well-known `farcade.lobby` aspect
with a compact signed card (games offered, display name) — the same announce-driven
discovery NomadNet nodes and LXMF propagation nodes use today. Every node aggregates the
announces it hears into a LOCAL lobby list with freshness ages; inviting someone is the
ordinary INVITE to the announced address. No server, no registry: cards are signed by
Reticulum identities so they cannot be forged, blocking is local, and sparse meshes get an
optional peer-run "amplifier" that re-publishes heard cards without gaining any authority.
Core lands in sprint 3 (13.7/13.8), amplifier in sprint 4 (14.6). Per-transport honesty:
on Meshtastic the shared channel itself is the lobby; Telegram is inherently centralized.

**A design distinction that shapes P9 (found reading `proto/messages.py`):** the existing
text codec (`FARCADE1 <gid> MOVE <ply> <hex> <hash>`) is machine-grade — a human cannot
compute state hashes. So "play from stock Sideband" is a *conversational companion mode*:
the Farcade node holds the one authoritative log, renders the board as ASCII
(`render_ascii` exists), and parses sloppy human input (`parse_move` exists). Ordering and
hashing concerns vanish because the phone holds no state. The machine text codec gets wired
separately (it is the lawful shape for ham links later, and it already round-trips in
tests).

---

## Sprint 2 — "New game, new audience" (the ASAP sprint)

### P8 — Reversi plugin

| ID | task | acceptance / QA | model | size |
|---|---|---|---|---|
| 8.1 | Reversi `Game` over an internal board impl (no good PyPI lib; rules are one page) | Full rules: flips, **forced pass as an explicit legal move**, double-pass ends, disc-count outcome | sonnet | M |
| 8.2 | 1-byte move codec (6 bits square + pass sentinel) | Round-trips every legal move in 10k random games | sonnet | S |
| 8.3 | Wire into games registry + generic port tests (`test_port_generic.py` runs a third game) | Adversarial harness: 500 reversi games at 10% chaos, zero desyncs | sonnet | S |
| 8.4 | Renders: ASCII + web model (reuse c4 disc rendering idioms) | Playable in `farcade demo --game reversi` | sonnet | M |

Pass-move note: the `Game` port stays unchanged — pass is just a move Reversi returns from
`legal_moves` when no placement exists. No core edits.

### P9 — Sideband companion mode (play with nothing installed)

| ID | task | acceptance / QA | model | size |
|---|---|---|---|---|
| 9.1 | Companion session model: peer address ↔ conversational game, held by the Farcade node | A `CompanionHost` object on top of `Node`; core/proto untouched (isolation test extended) | **opus** | M |
| 9.2 | Inbound: parse plain LXMF text — "play chess", "play reversi", moves ("e4", "d3"), "board", "resign", "help"; everything else is chat | Sloppy input table-driven tests (case, spacing, punctuation); unknown input never crashes, replies with help | sonnet | M |
| 9.3 | Outbound: ASCII board + status + prompt per reply, sized for Sideband's message view | Reply fits one LXMF message; board legible on a phone (Jack eyeballs the Pixel) | sonnet | S |
| 9.4 | **Live acceptance: full game from stock Sideband 2.0.1 on the Pixel XL** vs bot on the Windows host, via prnsd | Zero installs on the phone; game to a decided outcome; screenshots for the doc | sonnet | M |
| 9.5 | Companion soak hooks: events CSV rows for companion games too | Instrument sees companion moves (dir/type rows present) | haiku | S |

### P10 — machine text codec over LXMF

| ID | task | acceptance / QA | model | size |
|---|---|---|---|---|
| 10.1 | Text-mode peers: `GamePeer` encodes/decodes via `encode_text`/`decode_text` for peers flagged text | Full game peer-to-peer in text mode through prnsd; budget test covers text sizes | sonnet | M |

### P11 — hardening from the soak's lessons

| ID | task | acceptance / QA | model | size |
|---|---|---|---|---|
| 11.1 | rpc_key helper: `farcade rns-key <prnsd-config-dir>` prints the key; soak scripts take `--rpc-key` | Two-arm test: with key zero digest errors (live) | haiku | S |
| 11.2 | Soak monitor checks completion artifact BEFORE process liveness | The "SOAK DEAD at the finish line" race cannot recur | haiku | S |
| 11.3 | Multi-session soak made deliberate: `--sessions N` on the initiator | N=2 for 1h, both clean — the accidental result reproduced on purpose | sonnet | M |

### P9b — rules and help, in the player's language (Jack, 2026-08-10)

| ID | task | acceptance / QA | model | size |
|---|---|---|---|---|
| 9b.1 | Per-game rules text in clear language: a `rules()` string on each Game plugin, structured for translation (message catalog, not hardcoded prose) | Every registered game has rules; test enforces it so a new game cannot ship ruleless | sonnet | M |
| 9b.2 | English + Spanish (es-419) catalogs first; language picked per peer/UI setting | Both languages complete for all games; missing-translation falls back to English visibly, never crashes | sonnet | M |
| 9b.3 | Surfaces: "rules"/"reglas" command in companion mode; help link/pane in the web UI and TUI | Companion replies with the rules in the asker's language; web help renders without leaving the game | sonnet | M |

### P12 — review and the public gate (carried P7.1/P7.3)

| ID | task | acceptance / QA | model | size |
|---|---|---|---|---|
| 12.1 | Adversarial review of sprint 1+2 code | Findings verified before acting (audit findings are hypotheses) | **opus** | M |
| 12.2 | README/docs refresh incl. companion mode guide | A stranger stands up companion play from docs alone | sonnet | S |
| 12.3 | **Jack's P7.3 decision: public or not** (gates PyPI, exe, any announcement) | Decision recorded; nothing public without explicit yes | — | — |

---

## Sprint 3 — "Reach": Meshtastic, voice, polish, deploy

| ID | task | acceptance / QA | model | size |
|---|---|---|---|---|
| 13.1 | Meshtastic transport adapter (host-side via Meshtastic python API to a radio node) | Binary codec ≤230B enforced; trust=CHANNEL_KEY stated in logs; loopback-bench game first | **opus** | L |
| 13.2 | Meshtastic live game via **the operator's mesh** (Jack's call 2026-08-10): a Farcade host drives one of the operator's fleet nodes, meshing-around-BBS pattern; an ask to the mesh operator at sprint-3 start | Full game over LoRa; events CSV becomes the first real LoRa link-quality dataset | sonnet | L |
| 13.3 | Checkers plugin (game #4) | Same bar as Reversi: port tests + 500 chaos games | sonnet | M |
| 13.4 | Voice wired: Ollama on the P40, engine moves + model banter (**gated on the operator's sign-off**) | Black-hole test still passes; latency budget: voice never delays a move | sonnet | M |
| 13.5 | Web UI polish: move history, resign/draw buttons, board flip, multi-game switcher | Playable multi-game session from the S24 | sonnet | L |
| 13.6 | Docker compose soak node: prnsd (Ken's image) + responder + volumes | `docker compose up` on a clean Linux box = joinable peer; identity survives restart | sonnet | M |
| 13.7 | **Serverless lobby, core** (Jack 2026-08-10): nodes announce a well-known `farcade.lobby` aspect with a compact signed card (games offered, display name); every node aggregates heard announces into a local lobby list with freshness ages | Card fits the 200-byte budget; two bench nodes discover each other with NO prior exchange of addresses; forged-card test rejected by identity check | **opus** | L |
| 13.8 | Lobby UI: pane in web/TUI listing heard players, one-tap invite | Invite from the lobby starts a normal game; stale entries age out visibly | sonnet | M |
| 13.9 | Stretch: Telegram transport (first-class bot API) | Full game vs a phone with only Telegram | sonnet | L |

## Sprint 4 — "The primitives": randomness, secrets, simultaneity

| ID | task | acceptance / QA | model | size |
|---|---|---|---|---|
| 14.1 | Commit-reveal shared randomness in the protocol (commit msgs, reveal msgs, XOR) | Cheat test: a peer that lies about its nonce is **provably caught**; budget test covers new msgs | **opus** | L |
| 14.2 | Simultaneous moves via the same machinery; rock-paper-scissors as the proof game | Neither side can move second (test forges a late reveal, gets caught) | sonnet | M |
| 14.3 | **Yahtzee** (Jack's call 2026-08-10; backgammon follows once dice are proven) | Full game over LXMF with commit-reveal dice; harness chaos run clean | sonnet | L |
| 14.4 | Hidden-info easy class: Battleship (commit board hash at start, reveal at end) | Replay verifies honesty; a cheating board is provably caught at reveal | **opus** | L |
| 14.5 | Spectators: read-only followers of a game log | A third identity watches a live game; cannot inject (intruder test extended) | sonnet | M |
| 14.6 | Lobby amplifier: a peer-run bulletin that re-publishes heard lobby cards (propagation-node pattern) for sparse meshes | Cards stay signed by their authors — amplifier cannot forge (test); purely optional infrastructure, holds no authority | sonnet | M |
| 14.7 | Stretch: correspondence time controls (multi-day clocks in logged state) | Clock state survives crash-replay identically both sides | sonnet | M |

---

## The ASAP path (can start immediately on approval)

1. P8 Reversi — no dependencies, pure code.
2. P9 companion mode — needs the Pixel XL with stock Sideband for 9.4 (already on the
   bench, live session) and prnsd on the Windows host (already running).
3. P11.1/11.2 are minutes each; fold in early.
4. Sprint 3's 13.2 and 13.4 need the operator coordination — flag ahead when sprint 3 nears.

## Reuse (found in exploration, nothing new invented)

- `parse_move` (sloppy input) and `render_ascii` on every Game — companion mode is mostly
  glue around them.
- `encode_text`/`decode_text` are complete and tested — P10 is wiring, not codec work.
- `InstrumentedTransport`/`metrics.report` extend to companion + Meshtastic rows unchanged.
- The adversarial channel (`tests/channel.py`) runs any new game via `test_port_generic.py`.
- Ken ships a prnsd container image (release assets) — 13.6 stacks on it.

## Verification (each sprint)

- Gate green (`scripts/gate.sh`), and every new gate proven red on planted bad input —
  the standing house rule.
- Each new game: port-generic tests + ≥500 adversarial-channel games, zero desyncs.
- Each new transport/mode: one full live game on real hardware, evidence in the repo
  (the sprint-1 pattern: artifact JSON + a doc that attributes every anomaly).
- Sprint 2 exit: the Pixel-XL-stock-Sideband game is the demo that decides P7.3.
