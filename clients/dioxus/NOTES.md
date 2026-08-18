# Dioxus spike

A spike, kept honest about being one. Ken suggested Dioxus for Farcade: a Rust app
framework that runs natively on desktop and mobile through a light webview, with the app
code running native rather than in the browser, and the same source also building for web.
This directory exists to find out whether that earns a place here, at the smallest cost
that answers the question.

## The finding that shaped it

**Farcade does not need rewriting in Rust to try this.** `LocalAPI` is already the seam:

| route | purpose |
|---|---|
| `GET /whoami` | which player this request speaks for, or null |
| `GET /games` | that player's games and no one else's |
| `GET /games/{gid}` | the view, including `model` |
| `GET /events?since=N` | short-poll cursor |
| `POST /games/{gid}/{action}` | move, chat, resign, draw-offer, draw-accept, nudge |
| `POST /auth/claim` | exchange a claim code for a session token |

Every one carries `X-Farcade-Token` or the `farcade_token` cookie. So a Dioxus client is a
**front end over routes that already exist and are already tested** — a swap, not an
architecture change. That matters for judging Ken's suggestion fairly: if Dioxus is worth
it, the cost is one client, not one rewrite.

## The constraint this spike surfaced immediately

`LocalAPI` sends no `Access-Control-*` headers — it sets `Content-Type` and
`Content-Length` and nothing else.

- **Desktop** builds talk to the node directly with a native HTTP client. No browser, no
  origin, no problem.
- **Web** builds served from any other origin are blocked by the browser before the
  request is even useful.

The wrong fix is to bolt CORS onto `LocalAPI` and start reasoning about which origins a
hub should trust. The right one is to **serve the built bundle from `LocalAPI` itself**, on
the same origin, which is what "a hub is a web app with a real board that a family stands
up" already means. `sprint-4.md` describes the hub serving the page; this just means the
page can be a WASM bundle instead of `PAGE_HTML`.

So the spike's own constraint points at the deployment story rather than away from it.

## Scope

Connect Four only, and deliberately: its model is a grid — seven columns of `"0"`/`"1"`
read bottom-up, plus `to_move` and the legal columns — so there is no notation parsing and
what is under test is the framework. Ken lost a game of it, which makes it the right one.

Fetch, render, drop a piece, refetch. **No poll loop yet.** `/events?since=N` is the next
thing to prove, not this one, and a hand-rolled cross-platform sleep is exactly the kind of
platform abstraction a spike has not earned.

Not in scope: styling ambition (that is `13.5`), the lobby (`13.8`), chess, chat,
spectating, or mobile targets. Those are the questions *after* this one.

## What would make this worth adopting

1. One source tree renders a real board and plays a legal move on **desktop** and **web**.
2. The web bundle can be served by `LocalAPI` so a hub hands out one URL.
3. The result is small enough that a mobile target is a build flag rather than a project.

If 1 and 2 hold, the sleek mobile board and the lobby stop being two separate front ends.
If they do not, this stays a spike and the HTML page keeps its job — which is a perfectly
good outcome for a few hours.

## Running it

```
cd clients/dioxus
cargo run --no-default-features --features desktop     # FARCADE_API, FARCADE_TOKEN
dx serve --features web                                # web, subject to the CORS note above
```

`FARCADE_API` defaults to `http://127.0.0.1:8765`. `FARCADE_TOKEN` is only needed against a
hub; a personal seat has no players to claim and `LocalAPI` never looks for a token there.

The crate carries an empty `[workspace]` so it stays out of the Python package's world and
cannot slow `scripts/gate.sh` down.
