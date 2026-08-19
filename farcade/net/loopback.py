"""In-process loopback transport: two endpoints, one queue, no chaos.

For demo mode and UI development. The adversarial variant lives in the
test suite on purpose. Chaos is an instrument, not a feature.
"""

from __future__ import annotations

from collections import deque
from collections.abc import Callable

from farcade.net import TrustLevel


class LoopbackHub:
    def __init__(self):
        self.queue: deque[tuple[str, str, bytes]] = deque()
        self.endpoints: dict[str, LoopbackEndpoint] = {}

    def endpoint(self, address: str) -> LoopbackEndpoint:
        ep = LoopbackEndpoint(self, address)
        self.endpoints[address] = ep
        return ep

    def pump(self, limit: int = 1000) -> int:
        n = 0
        while self.queue and n < limit:
            src, dst, payload = self.queue.popleft()
            ep = self.endpoints.get(dst)
            if ep is not None and ep.receive_cb is not None:
                ep.receive_cb(src, payload)
            n += 1
        return n


class LoopbackEndpoint:
    trust_level = TrustLevel.CRYPTOGRAPHIC  # same process; trivially true

    def __init__(self, hub: LoopbackHub, address: str):
        self.hub = hub
        self._address = address
        self.receive_cb: Callable[[str, bytes], None] | None = None

    @property
    def address(self) -> str:
        return self._address

    def send(self, peer: str, payload: bytes) -> None:
        self.hub.queue.append((self._address, peer, payload))

    def set_receive_callback(self, cb: Callable[[str, bytes], None]) -> None:
        self.receive_cb = cb
