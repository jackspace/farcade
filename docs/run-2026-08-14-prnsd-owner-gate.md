# 2026-08-14 — first run where "attached as client" is backed by "client of prnsd"

Three paced runs on the Windows host, two peers on one box, through prnsd 0.3.3. Everything below was
measured this session. The interesting parts are a fixed hypothesis, a killed hypothesis, and a
control I broke myself.

## Why this run happened at all

Farcade's transport refuses stock RNS. It had two guards for that:

    LxmfTransport require_attached=True     -> "am I a client?"
    scripts/probe_shared_instance.py        -> "am I a client?"

**Both ask the same question, and it is the wrong one.** Neither asks *a client of what*. On
Windows the gap never showed, because prnsd was the only thing that would ever hold TCP 37428. On
Linux it is wide open — measured on a third Linux box the same day:

    rnsd  pid 906094  unix @rns/default (LISTEN)      <- rnsd owns the bus
    meshchat                                           <- attached as its client

A Farcade peer there attaches as a client, every guard goes green, and the run measures stock RNS.

`scripts/probe_instance_owner.py` closes it. Exit `0` match, `1` mismatch, **`2` could-not-determine,
never 0.**

## Setup

    MeshChat stopped on the Windows host (it held 37428 for 22 h; nothing restarts it automatically)
    prnsd 0.3.3 started from .local/prnsd-0.3.3/, config .local/prnsd-config/

        shared_instance_started bus_port=37428 control_port=37429 instance_name=default
        daemon_ready transport=true online=0 listening=1

**`Farcade Link` (TCPClient -> the Pi's port 4243) deliberately DISABLED.** That interface dials the same
prnsd carrying the operator's long-run measurement, and with `enable_transport = Yes` our announces would
reach the radio link under characterisation. Original config backed up as
`config.backup-20260814`; the only edit is one `interface_enabled` line. Asked the
operator before touching it, not after.

`USB Auto`, `Bluetooth Auto` and the `AutoInterface` were already `No` in that config, which matters
more than usual: a dev board sits on COM13 and opening that port resets the board, and another bench board had
been reflashed an hour earlier.

## Both gates green together, for the first time

    OWNER_WHERE=TCP 37428   OWNER_NAME=prnsd.exe   OWNER_PID=38080   MATCH   exit 0
    PROBE_ROLE=client                                                MATCH   exit 0

## The three runs

Identical command each time: `--hours 0.05 --interval 2`.

| run | rpc_key | games | dup | gaps | **desyncs** | median latency |
|---|---|---|---|---|---|---|
| 1 | neither peer | 5 | 0 | 0 | **0** | 4.011 s |
| 2 | responder only | 5 | 0 | 0 | **0** | 4.011 s |
| 3 | **both peers** | 4 | 0 | 0 | **0** | 4.011 s |

14 games, 282 messages, zero duplicates, zero gaps, **zero desyncs**.

## What the rpc_key does, and what it does not

`docs/deploy-two-peers.md` §3 says peers without prnsd's rpc_key log `digest sent was rejected` on
every stats RPC. Confirmed: runs 1 and 2 are full of them, run 3 has **none**.

**And it changed latency not at all.** I had guessed those rejected RPCs were costing a timeout per
message. Median 4.011 s in all three runs, min 3.808-3.810. That is not a transport cost, it is a
fixed cadence — and 4.0 s is exactly 2x the `--interval 2`. **Latency here is pacing, not the link.**

### A retraction that belongs in the record

Mid-session I flagged 4.0 s as *"20x worse than the 205 ms of the 24 h soak"*. **Withdrawn.** Those
two numbers do not count the same thing and I compared them before checking that they did. Same
failure as the four retracted numbers of 2026-08-13. Any future comparison against the 205 ms figure
needs the soak's interval and its definition of latency established first.

## The control I broke

Run 2 was meant to be the treated arm. I created `.local/run-a2` as a fresh workdir to keep metrics
clean, and that **generated a new default RNS config, discarding the rpc_key I had just patched into
`run-a`**. So run 2 treated only the responder while I believed both were treated. Caught it in the
output rather than by design; run 3 is the real one, built by copying the patched config into
`.local/run-a3/rnsconfig/`.

**The treatment lived in the config, and the hygiene step for the measurement silently reverted it.**
Worth remembering the next time a "clean workdir" is used to isolate a run.

## State left behind

    prnsd 38080         running, owns 37428, transport on, no interfaces online
    responder           redacted-responder-identity, attached=True
    MeshChat            STOPPED on the Windows host, no auto-restart
    Farcade Link        disabled, pending the operator's answer
    artifacts           .local/run-a, run-a2, run-a3, run-b  (gitignored)

## Next

1. Get the operator's answer on when the Pi's port 4243 is safe, or stand a second peer somewhere else.
2. Establish what the 24 h soak's 205 ms actually measured before anyone compares to it again.
3. Vary `--interval` to confirm latency tracks pacing rather than transport.
