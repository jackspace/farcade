//! A spike, and labelled as one: does a single Rust codebase render a real
//! Farcade board and play a move, on both desktop and web?
//!
//! What it deliberately does *not* do is rewrite Farcade. `LocalAPI` is already
//! an HTTP seam - `GET /whoami`, `GET /games`, `GET /games/{gid}`,
//! `GET /events?since=N`, and POSTs for the actions, all carrying
//! `X-Farcade-Token`. So this is a front end over routes that already exist and
//! are already tested, which is the cheapest honest way to find out whether
//! Dioxus earns a place here.
//!
//! Connect Four on purpose: its model is a grid - seven columns of "0"/"1" read
//! bottom-up, plus `to_move` and the legal columns. No notation parsing, so what
//! is under test is the framework rather than my patience.
//!
//! Scope held down on purpose: fetch, render, drop a piece, refetch. No polling
//! loop yet - `/events?since=N` is the next thing to prove, not this one.
//!
//! **The constraint this spike exists to surface:** `LocalAPI` sends no
//! `Access-Control-*` headers. A desktop build talks to it directly and does not
//! care. A web build served from any other origin is blocked by the browser. The
//! answer is not to bolt CORS on - it is to serve this bundle *from* `LocalAPI`,
//! same origin, which is what "a hub serves the web app" already means. See
//! NOTES.md.

use dioxus::prelude::*;
use serde::Deserialize;

const COLS: usize = 7;
const ROWS: usize = 6;

/// Where the node is. On web this is empty, so requests go to the origin that
/// served the page - which is the point. Desktop has no origin, so it needs a
/// real base.
fn api_base() -> String {
    if cfg!(feature = "desktop") {
        std::env::var("FARCADE_API").unwrap_or_else(|_| "http://127.0.0.1:8765".to_string())
    } else {
        String::new()
    }
}

/// A hub issues one of these per player. A personal seat has none, and
/// `LocalAPI` never looks for one there, so empty is correct.
fn api_token() -> String {
    std::env::var("FARCADE_TOKEN").unwrap_or_default()
}

#[derive(Deserialize, Clone, Debug, PartialEq)]
struct GameSummary {
    gid: String,
    game: String,
}

#[derive(Deserialize, Clone, Debug, PartialEq)]
struct C4Model {
    /// Seven strings, one per column, each character the player who dropped
    /// there, read bottom-up.
    grid: Vec<String>,
    to_move: u8,
    legal: Vec<usize>,
}

#[derive(Deserialize, Clone, Debug, PartialEq)]
struct GameView {
    gid: String,
    game: String,
    our_turn: bool,
    ply: Option<u32>,
    model: Option<C4Model>,
    #[serde(default)]
    peer: String,
}

async fn get_json<T>(path: String) -> Result<T, String>
where
    T: for<'de> Deserialize<'de>,
{
    let url = format!("{}{}", api_base(), path);
    let mut request = reqwest::Client::new().get(&url);
    let token = api_token();
    if !token.is_empty() {
        request = request.header("X-Farcade-Token", token);
    }
    let response = request.send().await.map_err(|e| e.to_string())?;
    if !response.status().is_success() {
        return Err(format!("{} on {}", response.status(), path));
    }
    response.json::<T>().await.map_err(|e| e.to_string())
}

async fn post_move(gid: String, column: usize) -> Result<(), String> {
    let url = format!("{}/games/{}/move", api_base(), gid);
    let mut request = reqwest::Client::new()
        .post(&url)
        .json(&serde_json::json!({ "move": column }));
    let token = api_token();
    if !token.is_empty() {
        request = request.header("X-Farcade-Token", token);
    }
    let response = request.send().await.map_err(|e| e.to_string())?;
    if response.status().is_success() {
        Ok(())
    } else {
        // 400 is Farcade telling the UI to ask again; the session log is untouched.
        Err(format!("{} rejected that column", response.status()))
    }
}

/// The first Connect Four game this player can see, and its view.
async fn load() -> Result<GameView, String> {
    let games: Vec<GameSummary> = get_json("/games".to_string()).await?;
    let chosen = games
        .into_iter()
        .find(|g| g.game == "c4")
        .ok_or_else(|| "no connect four game visible to this player".to_string())?;
    get_json(format!("/games/{}", chosen.gid)).await
}

fn main() {
    dioxus::launch(App);
}

#[component]
fn App() -> Element {
    let mut game = use_resource(load);
    let mut banner = use_signal(String::new);

    rsx! {
        style { {STYLE} }
        h1 {
            "Farcade "
            small { "dioxus spike" }
        }
        if !banner.read().is_empty() {
            div { class: "banner", "{banner}" }
        }
        match &*game.read_unchecked() {
            Some(Ok(view)) => {
                let view = view.clone();
                let gid = view.gid.clone();
                rsx! {
                    Board {
                        view: view,
                        on_drop: move |col: usize| {
                            let gid = gid.clone();
                            spawn(async move {
                                if let Err(e) = post_move(gid, col).await {
                                    banner.set(e);
                                }
                                game.restart();
                            });
                        },
                    }
                }
            }
            Some(Err(e)) => rsx! { p { class: "banner", "{e}" } },
            None => rsx! { p { "asking the node..." } },
        }
        p {
            button { onclick: move |_| game.restart(), "refresh" }
        }
    }
}

#[component]
fn Board(view: GameView, on_drop: EventHandler<usize>) -> Element {
    let Some(model) = view.model.clone() else {
        return rsx! { p { "game has no board yet" } };
    };

    rsx! {
        p {
            "{view.game} · ply {view.ply.unwrap_or(0)} · "
            if view.our_turn {
                b { "your turn" }
            } else {
                span { "waiting on {view.peer}" }
            }
        }
        div { class: "board",
            // Rows are drawn top down while the model stacks bottom up, so the
            // top visual row is the highest index.
            for row in (0..ROWS).rev() {
                div { class: "row",
                    for col in 0..COLS {
                        {
                            let playable = view.our_turn && model.legal.contains(&col);
                            let mark = model
                                .grid
                                .get(col)
                                .and_then(|column| column.chars().nth(row));
                            let (class, label) = match mark {
                                Some('0') => ("cell x", "X"),
                                Some('1') => ("cell o", "O"),
                                _ => ("cell", ""),
                            };
                            rsx! {
                                button {
                                    class: "{class}",
                                    disabled: !playable,
                                    onclick: move |_| on_drop.call(col),
                                    "{label}"
                                }
                            }
                        }
                    }
                }
            }
        }
        p { class: "count", "player {model.to_move} to move · legal {model.legal:?}" }
    }
}

/// Deliberately tiny. The spike is about whether the framework can drive a real
/// game, not about how it looks; 13.5 is where looks get decided.
const STYLE: &str = r#"
body { font-family: system-ui, sans-serif; margin: 2rem; }
.banner { background: #fee; border: 1px solid #c66; padding: .5rem; margin: .5rem 0; }
.board { display: inline-block; background: #2b4c7e; padding: 6px; border-radius: 6px; }
.row { display: flex; }
.cell { width: 44px; height: 44px; margin: 3px; border-radius: 50%;
        border: none; background: #eef; font-size: 20px; font-weight: 700; }
.cell.x { background: #d33; color: #fff; }
.cell.o { background: #fc3; color: #333; }
.cell:disabled { cursor: default; }
.count { color: #666; font-size: .85rem; }
"#;
