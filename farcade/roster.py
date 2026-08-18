"""The roster: one Node per player on a hub, and who a request speaks for.

`LocalAPI` used to close over a single `Node`, which made the identity of
the person at the browser a property of the *process*. On a personal seat
that is exactly right. On a hub it is the bug: two people in one house open
the same page and the network cannot tell them apart, so a result belongs
to the machine rather than to whoever actually played it.

So a hub keeps a roster. Each player has their own transport (from
`farcade.net.hub`), their own game storage, and therefore their own `Node`.
A request names nobody; it carries a session token, and the token is what
says which player's `Node` the route runs against. Nothing else in the API
has to know a hub exists.

**Credentials, and why they route through the same door.** A player is a
Reticulum identity (see `farcade.auth`), and the proof of being one is a
signature over a hub-issued challenge. A hub-custody player cannot produce
that signature in a browser, because the hub holds their key - so they are
authorised by a claim code instead, and the hub then answers its own
challenge with the key it holds for them. The token comes out of the same
`Sessions.verify` a self-custody player would walk through, which is what
keeps self custody a later upgrade rather than a second system.

The claim code is a bearer secret, and it is worth naming that plainly: it
is as strong as the hub's custody of the key already was, and no stronger.
A player who needs more than that holds their own key.
"""

from __future__ import annotations

import hmac
import secrets
from pathlib import Path

from farcade.auth import AuthError, Sessions, challenge_message
from farcade.net.hub import normalize_player_name
from farcade.node import Node

#: Long enough that guessing it over a LAN is not a strategy, short enough
#: to read down a table to a nine year old.
CLAIM_CODE_BYTES = 12


class Roster:
    """Every player on one hub, each with a Node, keyed by session token."""

    def __init__(self, hub, node_factory=None) -> None:
        self.hub = hub
        self.nodes: dict[str, Node] = {}
        self._node_factory = node_factory or (lambda transport, storage: Node(transport, storage))
        self.sessions = Sessions(resolve_identity=self._identity_for)

    # -- players -------------------------------------------------------------

    def player_names(self) -> list[str]:
        return sorted(self.hub.players)

    def node_for_player(self, name: str) -> Node:
        """This player's Node, building it - and them - on first ask.

        Idempotent for the same reason `LxmfHub.player` is: asking twice must
        return the same person, not a second one wearing their name.
        """
        name = normalize_player_name(name)
        if name in self.nodes:
            return self.nodes[name]
        transport = self.hub.player(name)
        storage = self._home(name) / "games"
        storage.mkdir(parents=True, exist_ok=True)
        self.nodes[name] = self._node_factory(transport, storage)
        return self.nodes[name]

    def node_for(self, token: str | None) -> Node:
        """The Node of the player this request speaks for.

        Raises rather than falling back to anyone: a request that cannot say
        who it is has no player, and picking one for it is the forgery this
        whole module exists to prevent.
        """
        name = self.player_for(token)
        if name is None:
            raise AuthError("this request does not speak for any player")
        return self.node_for_player(name)

    def player_for(self, token: str | None) -> str | None:
        """The player name behind a token, or None."""
        identity_hash = self.sessions.player_for(token)
        if identity_hash is None:
            return None
        return self._name_for_identity(identity_hash)

    # -- credentials ---------------------------------------------------------

    def claim_code(self, name: str) -> str:
        """This player's claim code, minted once and kept on the hub.

        Handing it out is the operator's job - it is what turns "a browser on
        the LAN" into "this player", and there is no way to re-derive it from
        anything public.
        """
        self.node_for_player(name)  # the player must exist before they can be claimed
        path = self._home(normalize_player_name(name)) / "claim-code"
        if path.exists():
            return path.read_text(encoding="utf-8").strip()
        code = secrets.token_hex(CLAIM_CODE_BYTES)
        path.write_text(code, encoding="utf-8")
        return code

    def authorize(self, name: str, code: str) -> str:
        """Exchange a claim code for a session token. Raises `AuthError`.

        The comparison is constant-time, and a wrong code is never told which
        half of the pair was wrong.
        """
        try:
            name = normalize_player_name(name)
        except ValueError as e:
            raise AuthError("no such player") from e
        if name not in self.hub.players:
            raise AuthError("no such player")
        expected = self.claim_code(name)
        if not hmac.compare_digest(expected, (code or "").strip()):
            raise AuthError("claim code did not match")

        identity = self.hub.players[name].identity
        identity_hash = identity.hexhash
        nonce = self.sessions.challenge(identity_hash)
        signature = identity.sign(challenge_message(identity_hash, nonce))
        return self.sessions.verify(identity_hash, signature)

    def revoke(self, token: str) -> None:
        self.sessions.revoke(token)

    # -- the loop ------------------------------------------------------------

    def pump(self, limit: int = 1000) -> int:
        return self.hub.pump(limit)

    def tick(self) -> int:
        """One automation step per player. Returns how many moved."""
        return sum(1 for node in list(self.nodes.values()) if node.tick())

    # -- internals -----------------------------------------------------------

    def _home(self, name: str) -> Path:
        return Path(self.hub.players_dir) / name

    def _identity_for(self, identity_hash: str):
        for player in self.hub.players.values():
            if player.identity.hexhash == identity_hash:
                return player.identity
        return None

    def _name_for_identity(self, identity_hash: str) -> str | None:
        for name, player in self.hub.players.items():
            if player.identity.hexhash == identity_hash:
                return name
        return None


class SoloRoster:
    """One player, every request: what a personal seat has always meant.

    Exists so `LocalAPI` has exactly one way to find a Node, rather than a
    hub branch and a not-hub branch through every route.
    """

    def __init__(self, node: Node) -> None:
        self.node = node

    def node_for(self, token: str | None) -> Node:
        return self.node

    def player_for(self, token: str | None) -> str | None:
        return None

    def authorize(self, name: str, code: str) -> str:
        raise AuthError("this seat has no players to claim")
