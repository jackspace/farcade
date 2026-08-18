"""Who is this player? Answered with Reticulum, not with a password.

A player IS a Reticulum identity. Proving you are that player means signing
something the hub just made up, with the key only that player holds - the
same primitive that authenticates every other thing on the network, rather
than a second credential system living beside it.

That choice is what keeps the door open. Custody of the key is an attribute
of a player, not a different product:

- ``hub`` custody - the hub holds the key. This is the family and club case,
  the one where a nine year old should not have to manage a keypair. The hub
  can sign on their behalf once a browser session is authorised.
- ``self`` custody - the player holds their own key, in their own client, and
  the hub never sees it. This is what a league spanning hubs eventually needs,
  because a hub-held signature cannot be proof against the hub itself.

Both walk the same verification path, so moving from the first to the second
is an upgrade rather than a migration.

Nothing here logs a nonce, a signature or a token.
"""

from __future__ import annotations

import secrets
import time
from collections.abc import Callable
from dataclasses import dataclass

import RNS

#: A challenge is short-lived on purpose: it is a single answer to a single
#: question, and a stale one is only useful to someone who kept it.
CHALLENGE_TTL_SECONDS = 120.0
SESSION_TTL_SECONDS = 30 * 24 * 3600.0

#: Signed alongside the nonce so a signature captured for one player cannot be
#: presented as another's, and so a Farcade challenge cannot be answered with a
#: signature harvested from some other protocol that used the same key.
CHALLENGE_CONTEXT = b"farcade-hub-auth-v1:"


class AuthError(Exception):
    """Authentication failed. Deliberately says little."""


@dataclass(frozen=True)
class PlayerRecord:
    """A player, keyed by identity rather than by name.

    The display name is presentation and may change or collide; the identity
    hash is the player. Storing it the other way round is how a rename or a
    duplicate name silently becomes a different person.
    """

    identity_hash: str
    display_name: str
    custody: str = "hub"

    def __post_init__(self) -> None:
        if self.custody not in ("hub", "self"):
            raise ValueError(f"custody must be 'hub' or 'self', not {self.custody!r}")


def challenge_message(identity_hash: str, nonce: str) -> bytes:
    """Exactly the bytes a player signs. Binds the nonce to the player."""
    return CHALLENGE_CONTEXT + identity_hash.encode() + b":" + nonce.encode()


class Sessions:
    """Challenge, verify, and remember - with everything single-use."""

    def __init__(
        self,
        resolve_identity: Callable[[str], RNS.Identity | None],
        challenge_ttl: float = CHALLENGE_TTL_SECONDS,
        session_ttl: float = SESSION_TTL_SECONDS,
        now: Callable[[], float] = time.monotonic,
    ) -> None:
        self.resolve_identity = resolve_identity
        self.challenge_ttl = challenge_ttl
        self.session_ttl = session_ttl
        self.now = now
        self._challenges: dict[str, tuple[str, float]] = {}
        self._sessions: dict[str, tuple[str, float]] = {}

    # -- the flow -----------------------------------------------------------

    def challenge(self, identity_hash: str) -> str:
        """Issue a nonce for this player to sign. Replaces any outstanding one."""
        nonce = secrets.token_hex(32)
        self._challenges[identity_hash] = (nonce, self.now() + self.challenge_ttl)
        return nonce

    def verify(self, identity_hash: str, signature: bytes) -> str:
        """Check a signature over the outstanding challenge; return a token.

        The challenge is consumed whether or not the signature is good, so a
        captured nonce is worth one attempt rather than unlimited guesses.
        """
        issued = self._challenges.pop(identity_hash, None)
        if issued is None:
            raise AuthError("no challenge outstanding for this player")
        nonce, expires_at = issued
        if self.now() > expires_at:
            raise AuthError("challenge expired")

        identity = self.resolve_identity(identity_hash)
        if identity is None:
            raise AuthError("unknown player")
        try:
            valid = identity.validate(signature, challenge_message(identity_hash, nonce))
        except KeyError as e:  # no public key on the identity
            raise AuthError("player has no usable public key") from e
        if not valid:
            raise AuthError("signature did not match")

        token = secrets.token_urlsafe(32)
        self._sessions[token] = (identity_hash, self.now() + self.session_ttl)
        return token

    def player_for(self, token: str | None) -> str | None:
        """The player this token speaks for, or None. Expired tokens are None."""
        if not token:
            return None
        found = self._sessions.get(token)
        if found is None:
            return None
        identity_hash, expires_at = found
        if self.now() > expires_at:
            del self._sessions[token]
            return None
        return identity_hash

    def revoke(self, token: str) -> None:
        self._sessions.pop(token, None)

    # -- housekeeping -------------------------------------------------------

    def purge_expired(self) -> int:
        """Drop what has timed out. Returns how many entries went."""
        now = self.now()
        stale_challenges = [k for k, (_, exp) in self._challenges.items() if now > exp]
        stale_sessions = [k for k, (_, exp) in self._sessions.items() if now > exp]
        for key in stale_challenges:
            del self._challenges[key]
        for key in stale_sessions:
            del self._sessions[key]
        return len(stale_challenges) + len(stale_sessions)
