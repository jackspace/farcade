"""The adversarial in-memory channel.

Implements the Transport port twice over a shared chaos engine that
drops, duplicates, reorders and truncates messages with seeded
probabilities. This is the instrument that turns "it worked once" into
"it survives the conditions the real network is documented to produce".

Determinism: everything runs off one random.Random(seed), so a failing
case replays exactly.
"""

from __future__ import annotations

import random
from collections.abc import Callable

from farcade.net import TrustLevel


class ChaosEndpoint:
    """One side's Transport. send() feeds the shared channel."""

    def __init__(self, channel: AdversarialChannel, address: str):
        self.channel = channel
        self._address = address
        self.trust_level = TrustLevel.CRYPTOGRAPHIC
        self.receive_cb: Callable[[str, bytes], None] | None = None

    @property
    def address(self) -> str:
        return self._address

    def send(self, peer: str, payload: bytes) -> None:
        self.channel.submit(self._address, peer, payload)

    def set_receive_callback(self, cb: Callable[[str, bytes], None]) -> None:
        self.receive_cb = cb


class AdversarialChannel:
    def __init__(
        self,
        seed: int,
        p_drop: float = 0.0,
        p_dup: float = 0.0,
        p_reorder: float = 0.0,
        p_truncate: float = 0.0,
    ):
        self.rng = random.Random(seed)
        self.p_drop = p_drop
        self.p_dup = p_dup
        self.p_reorder = p_reorder
        self.p_truncate = p_truncate
        self.queue: list[tuple[str, str, bytes]] = []  # (src, dst, payload)
        self.endpoints: dict[str, ChaosEndpoint] = {}
        self.stats = {"sent": 0, "dropped": 0, "duplicated": 0, "reordered": 0, "truncated": 0}

    def endpoint(self, address: str) -> ChaosEndpoint:
        ep = ChaosEndpoint(self, address)
        self.endpoints[address] = ep
        return ep

    def submit(self, src: str, dst: str, payload: bytes) -> None:
        self.stats["sent"] += 1
        if self.rng.random() < self.p_drop:
            self.stats["dropped"] += 1
            return
        if self.rng.random() < self.p_truncate and len(payload) > 2:
            cut = self.rng.randrange(1, len(payload))
            payload = payload[:cut]
            self.stats["truncated"] += 1
        copies = 1
        if self.rng.random() < self.p_dup:
            copies = 2
            self.stats["duplicated"] += 1
        for _ in range(copies):
            item = (src, dst, payload)
            if self.queue and self.rng.random() < self.p_reorder:
                # insert somewhere strictly before the tail: true reordering
                idx = self.rng.randrange(0, len(self.queue))
                self.queue.insert(idx, item)
                self.stats["reordered"] += 1
            else:
                self.queue.append(item)

    def pump_one(self) -> bool:
        if not self.queue:
            return False
        src, dst, payload = self.queue.pop(0)
        ep = self.endpoints.get(dst)
        if ep is not None and ep.receive_cb is not None:
            ep.receive_cb(src, payload)
        return True

    def pump(self, limit: int = 10_000) -> int:
        n = 0
        while n < limit and self.pump_one():
            n += 1
        return n
