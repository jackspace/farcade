# Farcade: the design

**Status**: the durable design, first written 2026-08-08. Work breakdowns, roadmap tiers and the
risk register are tracked outside the repo; this document is the part meant to last.

**One line**: peers play turn-based games and talk to each other over links where a message may
take minutes or days, where either seat may be a human or a machine, and where the whole exchange
doubles as an unattended soak test of the link.

## 1. Why

1. **It is the soak instrument we lack.** On 2026-08-08 a battery-runtime measurement on the
   bench showed there was no trustworthy long-running liveness instrument on the mesh: passive
   BLE presence lied in both directions for hours, and the only ground truth was a hand-fired
   announce. A turn-based game is an **ordered, verifiable, self-generating message log**: every
   move is ply-numbered and hash-checked, so delivery latency, duplication, reordering and loss
   are measured continuously as a by-product of play.
2. **It exercises the application layer.** Cross-implementation conformance work on this bench
   proved PHY/packet/announce-level interop between Reticulum implementations. Farcade rides LXMF
   above all of that and answers a question nothing else here answers: *does a real, stateful,
   long-lived conversation survive this network for a week?*
3. **Nobody has built one.** The curated awesome-reticulum index has no games category at all
   (checked 2026-08-08).

Farcade is an LXMF application, a car on the road rather than part of the road. It is not a
contribution to any Reticulum implementation.

## 2. Principles

1. **State is a pure function of the move log.** The authoritative state of a session is an
   append-only log of moves; the board is derived by replay. Persistence is appending a line,
   crash recovery is replaying the file, peer resync is sending the log, and idempotency falls
   out because re-applying a logged ply is a no-op. Logs are small (an 80-ply chess game is under
   200 bytes in the binary codec), so *send the whole log* is always affordable. No diffing.
2. **The ply number is the sequence number.** `ply < expected` → duplicate, ignore silently;
   duplicates are **normal operation** on a store-and-forward network, not errors.
   `ply == expected` → validate, apply, append. `ply > expected` → gap; request sync.
3. **Every move carries a hash of the resulting state.** Divergence is caught on the very next
   ply, not twenty moves later when the game has become nonsense.
4. **Verify, never trust.** Every incoming move is validated against local rules. The peer's
   claim of legality is worth nothing. Illegal → reject, log, do not apply.
5. **Delay, duplication and reordering are the normal case.** The protocol is designed for them,
   not defended against them.
6. **Games, players, voices and transports are plugins.** The session core knows none of them.
7. **An engine moves; a language model talks.** LLMs are never asked to choose moves. They
   hallucinate illegal ones and play badly. Move selection belongs to game engines (UCI for
   chess); the LLM is a *correspondent* with a persona, and its chat is flavour, never state.
8. **The voice never blocks the game.** Commentary is generated with a timeout on a side path;
   failure degrades to silence.
9. **Trust level is a property of the transport and is stated, never assumed.** Cryptographic
   identity on Reticulum; a shared channel key on Meshtastic; a bare callsign on ham. All are
   acceptable for games. Pretending one is another is not.

## 3. Architecture

```
        Game plugin                    Player plug              Voice plug
   (chess, connect4, …)           (human UI / engine)        (null → LLM later)
             │                             │                       │
             └──────────────┬──────────────┴───────────┬───────────┘
                            ▼                          ▼
                 ┌──────────────────────────────────────────┐
                 │                Session core              │
                 │  move log · ply sequence · state hash    │
                 │  dup/gap/resync · peer binding · chat    │
                 └──────────────────┬───────────────────────┘
                                    ▼
                 ┌──────────────────────────────────────────┐
                 │          Protocol + codecs               │   binary | text
                 └──────────────────┬───────────────────────┘
                                    ▼
                 ┌──────────────────────────────────────────┐
                 │             Transport port               │
                 │      LXMF first · others by adapter      │
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
    encode_move(move) -> bytes              # compact, budgeted
    decode_move(data) -> Move
    render_ascii(state) -> str              # TUI
    render_model(state) -> dict             # web UI
```

The port covers two-player, perfect-information, alternating games. Shared randomness, hidden
information and simultaneous moves are deliberate later extensions (commit-reveal and commitment
schemes, which are on the roadmap rather than here); this port does not pretend to support them.

### The Transport port

```python
Transport:
    address -> str                          # opaque, transport-defined
    send(peer: str, payload: bytes)
    on_receive(cb)
```

First adapter: LXMF, attached to a running `prnsd` (Prns's daemon) the same way Sideband
attaches. The **200-byte message budget** is a first-class test: every protocol message fits, or
documents its chunking, so constrained transports (Meshtastic ~230 B, AX.25 ~256 B, SMS 160
chars) remain reachable by adapter rather than redesign.

**Two codecs, one protocol.** Binary for efficiency; text for humans and for links where
encryption is not lawful (amateur radio). The text codec is what lets a person on a stock
Meshtastic client play a bot by typing into a channel.

### The local API

One local HTTP + websocket API on the peer process drives every front-end: CLI, TUI (SSH-able),
and a click-driven local web UI. The UI is entirely local; **only moves cross the link**, so link
bandwidth places no constraint on interface richness.

## 4. Protocol

Envelope keys on every message: `v` (protocol version), `gid` (16-hex game id, minted by the
initiator), `t` (type), `ply`.

| type | payload | notes |
|---|---|---|
| `INVITE` | `game`, `color` (initiator's own, **stated not negotiated**), `note` | |
| `ACCEPT` / `DECLINE` | - / `reason` | responder takes the other colour |
| `MOVE` | `move`, `hash` (state hash **after** applying) | |
| `CHAT` | `text` | `ply` gives conversational context |
| `RESIGN`, `DRAW_OFFER`, `DRAW_ACCEPT` | - | |
| `SYNC_REQUEST` | `have_ply` | "I am at N; I believe you are ahead" |
| `SYNC_STATE` | `moves` (full log), `hash`, chunked `i/n` if needed | |
| `REJECT` | `reason`, `hash` | illegal move, bad ply, or hash mismatch |

### Failure modes and designed responses

| failure | detected by | response |
|---|---|---|
| duplicate delivery | `ply < expected` | ignore; normal |
| reordering / loss | `ply > expected` gap | `SYNC_REQUEST` |
| board divergence | hash mismatch | `SYNC_REQUEST`, full replay-validate |
| unrecoverable divergence | replay fails validation | mark broken, log loudly, never paper over |
| illegal move | local validation | `REJECT`, do not apply |
| message from a third identity | sender ≠ either bound identity | drop with **no reply** |
| peer silent for days | nothing | wait; this is correspondence |
| voice backend down | timeout | play on in silence |
| local crash | - | replay the log on start |

### Identity

A session is bound to exactly two transport identities at INVITE/ACCEPT. On Reticulum that
binding is cryptographic for free. The transport adapter declares its trust level
(`cryptographic` / `channel-key` / `nominal`) and the session logs it.

## 5. Instrumentation

Every message in and out appends a CSV row:

```
ts_local, gid, dir, type, ply, latency_s, dup, gap, hash_ok, peer
```

The report derives: delivery latency distribution, duplicate rate, reorder rate, loss (gaps that
required sync), desync events, longest silence survived. That is the soak harness. The chat
channel doubles as human-readable telemetry: "your move took four minutes to reach me" is the
report writing itself in prose.

## 6. QA discipline

Carried from the bench practices that motivated this project:

- Every gate is **proven to fail** on known-bad input before it counts as a gate.
- Every negative result needs a **positive control near the margin** (a control 45 dB inside the
  margin proved nothing about a target at the floor, and that mistake is why this rule exists).
- Repeating a blind measurement does not make it sighted.
- Report what ran, on what host, and what was skipped. Never imply an unrun platform passed.

## 7. Sprint-1 scope

In: two peers, one game at a time, chess plus one trivial second game (to prove the port),
engine and human players, voice **seam** (OpenAI-compatible shape, unwired), CLI + TUI + web UI
on one local API, LXMF-on-prnsd transport, full instrumentation, a 24-hour two-host soak.

Out, tiered on the roadmap rather than forgotten: every other transport, multiple concurrent games,
N-player, time controls, spectators, ratings/lobbies, NomadNet/Sideband fronts, randomness and
hidden-information mechanics, real-stakes anything.
