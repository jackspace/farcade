# Farcade Sprint 4 — the Hub MVP

Target release: **0.4.0**. Repo: `C:\agents\farcade` (public at github.com/jackspace/farcade).
Format follows `docs/sprints-2-4.md`; approved WBS becomes `docs/sprint-4.md` in the repo.

## Context

Farcade's protocol is finished work: three games, a serverless lobby, an adversarial harness, two
24-hour soaks with zero desyncs. The *product* is not, and playing it tonight showed exactly
where. The bot won every game because `default_bot` never passes `skill_level`, so every human
meets full-strength Stockfish. The board offers no way to pick a side though the API accepts one.
Restarting the seat silently abandoned a live game. Starting a game means pasting 32 hex
characters. Two crashes surfaced and were fixed on the spot.

**The reframe that reshapes this sprint:** Farcade is not one person's client, it is a *hub* — a
web app with a real chess board that a family, a league, or a community stands up, on top of Prns
out of the box but working with any RNS stack. Text-over-Sideband is a real reach story and stays,
but it is the fallback, not the product.

That reframe exposes an architectural gap that no amount of wiring fixes. `LocalAPI` wraps exactly
one `Node`, has no sessions or accounts, and its own docstring states the design out loud:
*"The server binds 127.0.0.1 only. The UI is local; only moves cross the real network."* Every
person who opens that page today **is the same player on the same identity**. Binding it to the
LAN (done tonight to reach the tablet) is already outside what it was built for. A hub needs
multiple players on one server, and that is this sprint's real work.

The good news from the inventory: most of the rest is **built and unwired, not missing**.
`resume_all()` exists and is tested but no entry point calls it. The lobby's crypto and announce
layer is complete but nothing consumes it. `skill_level` works but only an engine-vs-engine test
harness sets it. `POST /invite` already accepts a `seat`. That is cheap work, and much of it runs
fine on small models.

**"Any RNS stack" is nearly true today.** The transport uses plain `RNS.Reticulum` and
`is_connected_to_shared_instance` — nothing Prns-specific in the mechanism. Only the RPC-key
helper is prnsd-shaped (it reads prnsd's `storage/transport_identity`) and the error text says
"start prnsd first". Generalizing that is small.

## What the MVP is

A web app, served by a hub on the LAN, where:

- you pick **play the computer** (at a difficulty you can beat) or **play a person**,
- you see **a real chess board**, on a phone, tablet or laptop,
- you are **yourself** — a named player with your own identity, not whoever opened the page,
- others can **watch a live game and talk in it**,
- the hub **runs on Prns out of the box**, and is tested against stock `rnsd` too,
- and restarting the hub does not lose the game.

## The sprint demo (acceptance for the whole sprint)

1. On a machine where Reticulum was never configured, open Farcade and beat the computer at a
   difficulty you chose, on a side you chose.
2. Two people on two devices join the hub as **themselves**, find each other, play, razz each
   other in chat, and the hub is restarted mid-game without losing it.
3. A third person opens the same game and **watches it live and talks in it** without being able
   to move.
4. Leg 1 repeated with stock `rnsd` instead of prnsd, and the difference reported honestly.

## Decisions taken (2026-08-17)

| decision | choice |
|---|---|
| Scope | Experience **and** distribution in one sprint |
| Hub identity | **Identity per player from the start** |
| Spectating | **Full spectating with chat** |
| Reach | **LAN hub this sprint**, public hub next sprint |
| RNS stacks | **Prns by default, stock `rnsd` tested and supported** |
| Packaging | **CI and install docs, no PyPI publish** |
| Reticulum BBS / NomadNet page | **Stretch this sprint** (see P22) — the web app is the MVP |

### Architecture note, and the caveat that must be written down

Identity per player means the hub stores a Reticulum identity per player and registers each as its
own LXMF delivery identity on one `LXMRouter`. That is the right shape: it is what lets a result
be attributed to a *person* later, which is what P15's leagues and ratings need.

It also means **the hub holds every player's private key, so a hub operator can act as any of its
players.** That is acceptable and normal for a family or club hub — it is the same trust you give
a mail server — but it must be stated in the docs, not discovered. Two consequences: a league
spanning hubs cannot treat hub-held signatures as proof against the hub itself, and a future
"bring your own identity" path (player holds the key, hub holds nothing) should be designed for
now and built when leagues land.

Because players are separate, the browser must prove *which* player it is. LAN-only keeps the
stakes low this sprint, but "no auth at all" means anyone on the LAN can play, chat and resign as
anyone. Minimal per-player auth is in scope (P20.4); it is not optional.

---

## Executor legend

| tier | means | use for |
|---|---|---|
| `script` | deterministic, no model | CI yaml, changelog, version bump, gate runs, evidence capture |
| `haiku` | cheapest model | one-line wiring, parameter passthrough, doc formatting |
| `sonnet` | default | feature work with tests |
| **`opus`** | session model | identity, auth, the attach seam — anything where being wrong is expensive |
| `Jack` | human | device verification, the demo, taste calls |
| operator | whoever owns the bench | hardware clears, and sign-off before a shared instance restarts |

Size: **S** under an hour · **M** a few hours · **L** most of a day.
**MUST** ships this sprint · **STRETCH** only if the must-list is done.

---

## P20 — The hub: a player is a person (NEW, the headline)

| ID | task | acceptance / QA | executor | size | ship |
|---|---|---|---|---|---|
| 20.1 | Player registry: a hub holds N players, each with its own Reticulum identity and LXMF delivery identity on one router. Reuse `LxmfTransport`'s identity handling in `farcade/net/lxmf.py`; one router, many `register_delivery_identity` calls | Three players on one hub each announce their own address; a message to player B never reaches player A; identities survive restart | **opus** | L | MUST |
| 20.2 | `LocalAPI` becomes multi-player: routes act as the *requesting* player, not a single captured `Node`. This is the change the current one-`Node` closure blocks | Two browsers act as two different players against the same hub; each sees only its own games as playable | **opus** | L | MUST |
| 20.3 | Join and pick your name: a new person reaches the hub, creates a player, and is remembered | Names persist across restart; duplicate names refused or disambiguated; default name is the identity hash prefix, never blank | sonnet | M | MUST |
| 20.4 | Minimal per-player auth so a browser cannot act as someone else on the LAN | Acting as another player without their credential is rejected; the failing arm proven, not just the passing one | **opus** | M | MUST |
| 20.5 | Document the key-custody caveat above in the hub docs | A hub operator reads what they are trusted with before standing one up | `haiku` | S | MUST |

## P16 — Prns out of the box, any RNS stack

| ID | task | acceptance / QA | executor | size | ship |
|---|---|---|---|---|---|
| 16.1 | Auto-attach: find the running instance's config, read the RPC key, attach. `--rpc-key` stays an override. Generalize `rns_rpc_key` beyond prnsd's `transport_identity` layout and fix the prnsd-only error text | Hub starts with no flags against prnsd **and** against stock `rnsd`; with neither running it fails in one actionable sentence and **never** becomes the shared-instance owner (`NotAttachedToSharedInstance` must still fire — both arms tested) | **opus** | M | MUST |
| 16.2 | `farcade doctor`: which stack is running, who owns 37428, interfaces, key readable, and the exact fix per failure | Green on a healthy host; with the instance stopped it names the fix rather than raising. Two-arm test | sonnet | M | MUST |
| 16.3 | Stock `rnsd` as a tested configuration, run and reported alongside prnsd | Demo leg 4: same game on both stacks, differences stated plainly | sonnet + `Jack` | M | MUST |
| 16.4 | House-default config (AutoInterface on the LAN) so two machines find each other with no hand-editing | Two LAN hosts, no manual config, announce heard both directions | sonnet + `Jack` | M | MUST |
| 16.5 | Install docs for someone who has never heard of Reticulum; Prns is the default path, `rnsd` documented as supported | A stranger reaches "playing the computer" in five minutes and "playing a person" without help | sonnet | S | MUST |

## P17 — Choose your opponent

| ID | task | acceptance / QA | executor | size | ship |
|---|---|---|---|---|---|
| 17.1 | New-game flow: **play the computer** / **play a person**, replacing the address box. The computer path uses the loopback shape `cmd_demo` already proves, so it works with **no Reticulum at all** | Both routes in two clicks from cold start; computer route works with no instance running | sonnet | M | MUST |
| 17.2 | Difficulty: easy/medium/hard onto `UCIEnginePlayer(skill_level=…)` and minimax depth, in the web flow and as `play chess easy` in companion mode. **The human-facing default must be beatable** | Measurable strength separation across levels; easy loses to a weak reference player sometimes | sonnet | M | MUST |
| 17.3 | Side selection: white / black / **random default**, sending the `seat` field the API already accepts | Choosing black yields black; random is genuinely mixed over 100 invites | `haiku` | S | MUST |

## P21 — Watching (NEW)

| ID | task | acceptance / QA | executor | size | ship |
|---|---|---|---|---|---|
| 21.1 | Spectator view: any hub player can open a running game read-only, board and chat updating live | A spectator sees moves as they land and **cannot** move, resign or offer a draw — the rejection tested, not assumed | sonnet | M | MUST |
| 21.2 | Spectator chat, kept distinct from the players' own chat | Spectator messages are attributed and visibly not from a player; a spectator cannot forge a player line | sonnet | M | MUST |
| 21.3 | Hub game list: running and finished games with players, status and result | Visible to everyone on the hub; finished games readable afterwards | sonnet | S | MUST |
| 21.4 | Spectators over the network (a non-hub identity following a game) — the original 14.5 | A remote identity watches and cannot inject; intruder test extended | sonnet | M | STRETCH |

## P13.8 — Lobby: finding people (protocol already done, nothing consumes it)

| ID | task | acceptance / QA | executor | size | ship |
|---|---|---|---|---|---|
| 13.8a | Actually run the lobby: construct, announce and listen in the hub. `farcade/proto/lobby.py` and `farcade/net/lobby_rns.py` are complete and unused | Two bench hubs discover each other with **no prior exchange of addresses** — the acceptance the protocol was built for and never got | sonnet | M | MUST |
| 13.8b | `/lobby` route exposing heard cards with freshness ages | Stale entries age out; empty state handled | sonnet | S | MUST |
| 13.8c | Lobby pane with one-tap invite | Invite from the lobby starts an ordinary game; nobody types an address | sonnet | M | MUST |

## P13.5 — A board worth looking at

Mobile-first, because the real screens are a tablet and two phones.

| ID | task | acceptance / QA | executor | size | ship |
|---|---|---|---|---|---|
| 13.5a | Responsive layout: board and chat usable on Zenpad, S24 and Pixel without pinch-zoom | Verified on all three, screenshots in the repo | sonnet + `Jack` | M | MUST |
| 13.5b | Visual pass: typography, piece rendering, dark mode, real empty state | Jack's taste call — he is the acceptance | sonnet + `Jack` | M | MUST |
| 13.5c | Move history pane and board flip (both named in the original 13.5, neither built) | History matches the session log exactly; flip is display-only and never touches the log | sonnet | M | STRETCH |
| 9c.4 | "Your move" in the browser title bar | Title flips to `● your move — Farcade`, clears when it does not | `haiku` | S | MUST |

## P19 — Correctness found on the bench

| ID | task | acceptance / QA | executor | size | ship |
|---|---|---|---|---|---|
| 19.1 | Call `resume_all()` from the real entry points. It is built and tested; `Node.__init__`, `web_game_peer.py`, `lxmf_game_peer.py` and `companion_host.py` all skip it, so a restart abandons live games (hit live tonight) | Restart mid-game: play continues, no duplicate invite, ply and hashes intact both sides | sonnet | S | MUST |
| 19.2 | Changelog the two fixes already landed (`92d8ac1` companion `ProtocolBot`, `dbf9ce7` voice clamp and guard) | `CHANGELOG.md` Unreleased reflects both | `script` | S | MUST |

## P18 — CI and install docs (no publish)

No CI exists today: no `.github/workflows`, so `scripts/gate.sh` has only ever run on this bench.

| ID | task | acceptance / QA | executor | size | ship |
|---|---|---|---|---|---|
| 18.1 | GitHub Actions running `scripts/gate.sh` on push and PR | A deliberately broken commit fails the workflow — proven red, house rule | `script` | S | MUST |
| 18.2 | 0.4.0 release notes and tag | Changelog complete; no PyPI publish this sprint | `script` | S | MUST |
| 18.3a | **README triage now**: the Status section still says "Sprint 1 nearly complete (2026-08-09)" three releases later, and the only install line is a dev editable install. Correct what is simply false | Nothing in the README contradicts the shipped 0.3.0 | `haiku` | S | MUST |
| 18.3b | **README rewrite, the front door.** Warm and welcoming, professional throughout — what Farcade is (a hub for families, clubs and leagues), who it is for, what a first evening looks like, and how to start. Written *after* the hub lands so it describes what exists rather than what is hoped for | A stranger knows what it is and how to begin inside a minute; a non-technical reader is not scared off; **no crew names, hosts, or private addresses** (public repo hygiene) | **opus** + `Jack` | M | MUST |

## P22 — The mesh-native view (STRETCH, answers "does it need to be a BBS?")

A web app needs an IP path, so someone out on LoRa with only Sideband cannot see the hub at all.
A NomadNet page is how a hub becomes visible on the mesh itself, and it is a fourth renderer over
a core that already has three. `docs/sprints-2-4.md` already assumes this shape for league
standings (15.3).

| ID | task | acceptance / QA | executor | size | ship |
|---|---|---|---|---|---|
| 22.1 | NomadNet page: hub game list and a live board rendered in micron, served over Reticulum | Readable from Sideband's browser with no IP path to the hub | sonnet | M | STRETCH |

## Deferred out of this sprint

Rules text and es-419 catalogs (9b) · checkers (13.3) · Telegram (13.9) · Docker compose node
(13.6 — note there is **no** Docker anything in this repo today) · commit-reveal and
hidden-information games (14.x) · certificates, leagues, scorekeepers (15.x) · machine text codec
wiring (10.1) · golden vectors (9c.5) · PyPI publish · public hub. The previously planned
"Sprint 4 — the primitives" moves to Sprint 5; P-numbers stay stable so the existing plan document
keeps its meaning.

---

## Shared-bench coordination

The machine that runs these tests also carries other long-running measurements, so two rules apply.

1. **The live phone acceptance** carried over from the previous sprint is still open and needs the
   bench owner's clear before it runs. It closes as a demo device here.
2. **Restarting a shared Reticulum instance drops everything else attached to it.** P16 touches
   instance config, and one restart during planning cost another running measurement about ninety
   minutes. Announce a config change before making it, and record the down and up times after.

Nothing here needs new infrastructure or a public address.

## Sequencing

1. **19.1, 19.2, 9c.4, 18.1** — hours total, cheap tiers, and 19.1 removes a bug that would
   otherwise contaminate every later test.
2. **16.1 → 16.2**, then **20.1 → 20.2 → 20.3 → 20.4** — the two structural pieces. Everything
   else depends on them, so they go early and get the expensive tier.
3. **17.x** and **13.8a → 13.8b → 13.8c** in parallel (17.1's computer path needs no network, so
   it can land before the hub work settles).
4. **21.1 → 21.2 → 21.3**, then **13.5a/13.5b**.
5. **16.3, 16.4, 16.5, 18.2** last, documenting what actually shipped.
6. Stretch only if the MUST list is closed: 13.5c, 21.4, 22.1.

## Verification

- `bash scripts/gate.sh` green (`GATE_OK`) before every commit, and **every new gate proven red on
  planted bad input** — the standing house rule, applied to both of tonight's fixes.
- Every wiring task names the entry point it wired and shows before/after behaviour. A module
  existing is not evidence that it runs — that mistake is why `resume_all`, the lobby and
  `skill_level` all looked done.
- Anything that denies an action (spectators moving, players acting as other players) is tested on
  the **failing** arm, not just the passing one.
- Live bench evidence in the repo for all four demo legs, sprint-1 pattern: artifact files plus a
  doc attributing every anomaly. Screenshots from Zenpad, S24 and Pixel.
- Report the platform each result came from and say what was not run. Never imply an untested
  device or stack passed.
