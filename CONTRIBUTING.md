# Contributing to Farcade

Farcade is an arcade at a distance: turn-based games that stay playable over links
too slow and too lossy for anything real-time. A move is a handful of bytes, a game
can take a week, and the network underneath it might be a LoRa mesh in a valley with
no internet at all.

That constraint is the whole design, and it's the thing to keep in mind when you
change anything here.

Contributions are welcome. Bug reports, a game, a client, a transport, a fix for
something that reads wrong in the docs. What follows is how to make one land quickly.

## Getting set up

```
python -m pip install -e ".[dev]"
```

Python 3.10 or newer. CI runs 3.10 and 3.13, so those are the two that matter.

If you're touching chess, install Stockfish too. Without a real engine the bot falls
back to random moves and the engine tests stop meaning anything, which is worse than
skipping them.

## The gate

One command, and it's the same one CI runs:

```
bash scripts/gate.sh
```

Green is the literal string `GATE_OK` on the last line. `ruff format --check`, `ruff
check`, then `pytest`. If you send a pull request, that's what decides it.

**A gate that has never been seen red is not a gate.** There's a canary in the tree
for exactly this, so you can prove the thing still fails:

```
mv tests/test_gate_canary.py.disabled tests/test_gate_canary.py
bash scripts/gate.sh    # must print GATE_FAILED
```

Move it back when you're done.

The same rule goes for the test you're adding. Before you trust it green, break the
code it guards and watch it fail with a message that actually names the problem. A
test that passes whether or not the bug is present is worse than no test, because it
reads like coverage.

## What a good change looks like

**Test the real thing, not a stand-in for it.** The auth code is verified with real
Reticulum identities rather than mocks, because mocking a signature check tests the
mock. Same instinct everywhere: if the interesting behaviour lives in the dependency,
don't replace the dependency.

**Respect the byte budget.** `BUDGET` in `farcade/proto/messages.py` is 200 bytes and
every wire message fits inside it. If your change makes a message bigger, the size
test will say so, and the answer is usually a smaller encoding rather than a bigger
budget.

**Say why in the commit message.** Not what the diff already shows. What was wrong,
what you found out, and what you decided. The history here is the best documentation
the project has, and it's worth keeping that way.

**Small and complete beats big and partial.** A change with its test and its
changelog line is easy to merge. A large one that needs a conversation first should
start as an issue.

## Changelog and versions

Every user-visible change gets a line under `## [Unreleased]` in `CHANGELOG.md`, in
the section it belongs to: Added, Changed, Fixed, Removed.

Farcade is on `0.y.z` while the wire format and the Python API are still moving. A
**minor** bump is where a breaking change is allowed to land, so if you change a
public contract, say so in the entry. The version lives in `pyproject.toml` and
nowhere else; `farcade.__version__` reads it from the installed metadata.

## Style

`ruff format` and `ruff check` decide formatting and lint, so there's nothing to
argue about there. For prose, in docs and comments and commit messages alike:

- Write like a person talking to another person. Contractions are fine.
- Be specific. Name the file, the function, the number you measured.
- No em dashes. A comma, a colon, or two sentences will do.
- No hedging filler. "It's worth noting that" is never worth noting.
- Comments explain why, not what. If the code needs a comment to say what it does,
  the code is the thing to fix.

## On AI tools

Use them if they help you. Nobody here is going to audit your process.

What isn't welcome is text that reads like it was generated and shipped without
anyone reading it back. Uniform paragraph rhythm, em dashes everywhere, confident
claims that nothing was measured to support, a comment restating the line beneath it.
If you wouldn't say it out loud, don't commit it.

Two hard rules:

- **No AI attribution trailers.** No `Co-Authored-By` for a tool, no "generated with"
  footer. The commit is yours; you're the one who read it.
- **Don't paste in a claim you haven't checked.** If you say a message fits in 200
  bytes, or that a restart resumes the game, run it first. This project has been
  bitten more than once by a check that returned green having examined nothing.

## Reporting a bug

Tell me what you ran, on what, and what happened instead. Version from
`farcade --version`, the transport you were on, and the smallest sequence that
reproduces it. `farcade doctor` output helps too, since most setup problems are one
of the four things it checks.

If it's a security issue, or anything involving somebody's identity or claim code,
mail me rather than opening an issue.
