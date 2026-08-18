"""20.4: proving who a player is, with Reticulum rather than a password.

Every failing arm is asserted here, because for authentication the arm that
must not pass is the whole point. Real RNS identities throughout - they are
cheap to make, and mocking the signature check would test the mock."""

import pytest
import RNS

from farcade.auth import AuthError, PlayerRecord, Sessions, challenge_message


@pytest.fixture
def alice():
    return RNS.Identity()


@pytest.fixture
def sessions(alice):
    known = {alice.hash.hex(): alice}
    return Sessions(resolve_identity=known.get), alice.hash.hex()


def sign_challenge(identity, identity_hash, nonce):
    return identity.sign(challenge_message(identity_hash, nonce))


def test_a_signed_challenge_authenticates(sessions, alice):
    auth, alice_hash = sessions
    nonce = auth.challenge(alice_hash)
    token = auth.verify(alice_hash, sign_challenge(alice, alice_hash, nonce))
    assert auth.player_for(token) == alice_hash


def test_a_wrong_signature_is_refused(sessions, alice):
    auth, alice_hash = sessions
    auth.challenge(alice_hash)
    with pytest.raises(AuthError):
        auth.verify(alice_hash, b"\x00" * 64)


def test_another_players_key_cannot_answer_your_challenge(sessions):
    """The nonce is bound to the player, so a signature made by someone else
    over the same nonce is not an answer."""
    auth, alice_hash = sessions
    intruder = RNS.Identity()
    nonce = auth.challenge(alice_hash)
    with pytest.raises(AuthError):
        auth.verify(alice_hash, sign_challenge(intruder, alice_hash, nonce))


def test_a_challenge_is_single_use_even_when_it_fails(sessions, alice):
    """A captured nonce buys one attempt, not unlimited guesses."""
    auth, alice_hash = sessions
    nonce = auth.challenge(alice_hash)
    with pytest.raises(AuthError):
        auth.verify(alice_hash, b"\x00" * 64)
    with pytest.raises(AuthError, match="no challenge"):
        auth.verify(alice_hash, sign_challenge(alice, alice_hash, nonce))


def test_a_replayed_signature_does_not_work_twice(sessions, alice):
    auth, alice_hash = sessions
    nonce = auth.challenge(alice_hash)
    signature = sign_challenge(alice, alice_hash, nonce)
    auth.verify(alice_hash, signature)
    with pytest.raises(AuthError, match="no challenge"):
        auth.verify(alice_hash, signature)


def test_an_expired_challenge_is_refused(alice):
    clock = {"t": 1000.0}
    auth = Sessions(
        resolve_identity={alice.hash.hex(): alice}.get,
        challenge_ttl=60.0,
        now=lambda: clock["t"],
    )
    alice_hash = alice.hash.hex()
    nonce = auth.challenge(alice_hash)
    clock["t"] += 61.0
    with pytest.raises(AuthError, match="expired"):
        auth.verify(alice_hash, sign_challenge(alice, alice_hash, nonce))


def test_an_unknown_player_cannot_authenticate(alice):
    auth = Sessions(resolve_identity=lambda _h: None)
    auth.challenge("deadbeef")
    with pytest.raises(AuthError, match="unknown player"):
        auth.verify("deadbeef", b"\x00" * 64)


def test_verifying_without_a_challenge_is_refused(sessions, alice):
    auth, alice_hash = sessions
    with pytest.raises(AuthError, match="no challenge"):
        auth.verify(alice_hash, sign_challenge(alice, alice_hash, "made-up"))


def test_tokens_expire_and_revoke(alice):
    clock = {"t": 0.0}
    auth = Sessions(
        resolve_identity={alice.hash.hex(): alice}.get,
        session_ttl=100.0,
        now=lambda: clock["t"],
    )
    alice_hash = alice.hash.hex()
    nonce = auth.challenge(alice_hash)
    token = auth.verify(alice_hash, sign_challenge(alice, alice_hash, nonce))

    assert auth.player_for(token) == alice_hash
    clock["t"] += 101.0
    assert auth.player_for(token) is None, "an expired token still spoke for a player"

    clock["t"] = 0.0
    nonce = auth.challenge(alice_hash)
    token = auth.verify(alice_hash, sign_challenge(alice, alice_hash, nonce))
    auth.revoke(token)
    assert auth.player_for(token) is None


def test_no_token_and_junk_tokens_speak_for_nobody(sessions):
    auth, _ = sessions
    for junk in (None, "", "not-a-token"):
        assert auth.player_for(junk) is None


def test_custody_is_constrained():
    PlayerRecord("abcd", "Ana", "hub")
    PlayerRecord("abcd", "Ana", "self")
    with pytest.raises(ValueError):
        PlayerRecord("abcd", "Ana", "sort-of")
