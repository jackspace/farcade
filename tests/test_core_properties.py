"""Property tests: the invariants hold under randomised play, not just
in the hand-picked cases."""

from hypothesis import given, settings
from hypothesis import strategies as st

from farcade.core.session import Apply, Session
from tests.conftest import NimGame

GID = "00112233aabbccdd"


def random_playout(seed_moves):
    """Clamp an arbitrary int list into a legal nim playout prefix."""
    nim = NimGame()
    state = nim.initial_state()
    legal_played = []
    for raw in seed_moves:
        take = (abs(raw) % 3) + 1
        if take > state.remaining:
            take = state.remaining
        if take == 0:
            break
        state = nim.apply(state, take)
        legal_played.append(take)
        if state.remaining == 0:
            break
    return legal_played


@given(st.lists(st.integers(), max_size=30))
@settings(max_examples=200, deadline=None)
def test_replay_equals_live(seed_moves):
    """Invariant 1: replaying the log always reproduces the live state."""
    nim = NimGame()
    s = Session.new(nim, GID)
    for m in random_playout(seed_moves):
        s.apply_local_move(m)
    replayed = s._replay(s.log.moves)
    assert replayed == s.state
    assert nim.hash(replayed) == s.our_hash()


@given(st.lists(st.integers(), max_size=30), st.data())
@settings(max_examples=200, deadline=None)
def test_redelivery_storm_changes_nothing(seed_moves, data):
    """Invariant 2: any storm of duplicate deliveries is absorbed silently."""
    nim = NimGame()
    s = Session.new(nim, GID)
    for m in random_playout(seed_moves):
        s.apply_local_move(m)
    if s.log.plies == 0:
        return

    snapshot = (s.log.plies, s.state)
    n_dups = data.draw(st.integers(min_value=1, max_value=20))
    for _ in range(n_dups):
        ply = data.draw(st.integers(min_value=0, max_value=s.log.plies - 1))
        r = s.apply_wire_move(ply, s.log.moves[ply], None)
        assert r.verdict in (Apply.DUPLICATE, Apply.FINISHED)
    assert (s.log.plies, s.state) == snapshot


@given(st.lists(st.integers(), max_size=30))
@settings(max_examples=100, deadline=None)
def test_hash_tracks_state_exactly(seed_moves):
    """Invariant 3: equal states hash equal; every ply changes the hash."""
    nim = NimGame()
    s = Session.new(nim, GID)
    seen = {s.our_hash()}
    for m in random_playout(seed_moves):
        s.apply_local_move(m)
        h = s.our_hash()
        assert h not in seen, "two different plies produced the same hash"
        seen.add(h)
