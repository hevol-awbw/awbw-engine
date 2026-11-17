"""Random-playout fuzzing: legal actions must always be steppable and never break invariants."""
import random

import pytest

from awbw.cos import COS
from awbw.data import UNITS, UT, CARRY
from awbw.game import Action, AT, Game, IllegalAction
from awbw.maps import make_game

ROWS = [
    "HBCc..^^..cDbh",
    "A.=.@@..@@.=.a",
    "P~~s=.^^..=s~p",
    "~~~s.@@.@@.s~~",
    "~~~s..=S==.s~~",
    "~~~s..====.s~~",
    "~~~s.@@.@@.s~~",
    "P~~s=.^^..=s~p",
    "A.=.@@..@@.=.a",
    "CBCc..^^..cDbD",
]
assert len({len(r) for r in ROWS}) == 1

START = [
    (0, UT.INF, 3, 3), (0, UT.TANK, 4, 3), (0, UT.APC, 3, 4), (0, UT.ARTY, 2, 4), (0, UT.MECH, 4, 6),
    (0, UT.BCOPTER, 1, 1), (0, UT.LANDER, 1, 2), (0, UT.BATTLESHIP, 0, 4), (0, UT.SUB, 0, 5),
    (1, UT.INF, 10, 3), (1, UT.TANK, 9, 3), (1, UT.APC, 10, 4), (1, UT.RECON, 11, 4), (1, UT.INF, 9, 6),
    (1, UT.FIGHTER, 12, 1), (1, UT.CRUISER, 13, 4), (1, UT.BLACKBOAT, 13, 5), (1, UT.MDTANK, 8, 5),
]


def check_invariants(g: Game):
    on_map = [u for u in g.units.values() if u.loaded_in is None]
    assert len(on_map) == len(g.pos), "pos map size mismatch"
    for (x, y), uid in g.pos.items():
        u = g.units[uid]
        assert (u.x, u.y) == (x, y) and u.loaded_in is None
        assert 0 <= x < g.w and 0 <= y < g.h
    for u in g.units.values():
        assert 1 <= u.hp <= 100, u
        assert u.ammo >= 0 and u.ammo <= UNITS[u.type].ammo, u
        assert u.fuel >= 0 or UNITS[u.type].fuel_per_turn == 0 or u.fuel > -1, u
        if u.loaded_in is not None:
            t = g.units[u.loaded_in]
            assert u.id in t.cargo and (u.x, u.y) == (t.x, t.y)
            assert u.type in CARRY[t.type][1]
        for cid in u.cargo:
            assert g.units[cid].loaded_in == u.id
        assert len(u.cargo) <= (CARRY[u.type][0] if u.type in CARRY else 0)
    for p in (0, 1):
        pl = g.players[p]
        assert pl.funds >= 0, pl
        assert 0 <= pl.charge <= g.max_charge(p)
    for row in g.cp:
        assert all(1 <= c <= 20 for c in row)


def random_game(co0, co1, seed):
    return make_game(ROWS, START, cos=(co0, co1), starting_funds=15000, seed=seed, max_days=40, unit_limit=40)


def play(g: Game, seed: int, max_steps: int = 400):
    rnd = random.Random(seed)
    sig = []
    for step in range(max_steps):
        if g.done:
            break
        p = g.cur
        if rnd.random() < 0.03:
            g.players[p].charge = g.max_charge(p)       # force power availability
        acts = g.legal_actions()
        non_end = [a for a in acts if a.type != AT.END_TURN]
        if not non_end or rnd.random() < 0.04:
            a = Action(AT.END_TURN)
        else:
            powers = [a for a in non_end if a.type == AT.POWER]
            a = rnd.choice(powers) if powers and rnd.random() < 0.5 else rnd.choice(non_end)
        if step % 25 == 0:               # legal action list must be consistent with the validator
            for probe in rnd.sample(acts, min(5, len(acts))):
                g.copy().step(probe)
        g.step(a)
        check_invariants(g)
        sig.append((a.type, a.unit, a.dest, a.target, a.arg))
    return sig


ALL_COS = sorted(COS)


@pytest.mark.parametrize("co", ALL_COS)
def test_fuzz_each_co_as_player_zero(co):
    for seed in (1, 2):
        g = random_game(co, "Andy", seed)
        play(g, seed)


@pytest.mark.parametrize("co", ALL_COS)
def test_fuzz_each_co_as_player_one(co):
    g = random_game("Andy", co, 7)
    play(g, 7)


def test_fuzz_random_pairings():
    rnd = random.Random(99)
    for i in range(40):
        a, b = rnd.choice(ALL_COS), rnd.choice(ALL_COS)
        g = random_game(a, b, i)
        play(g, i, max_steps=300)


def test_determinism():
    sigs, states = [], []
    for _ in range(2):
        g = random_game("Nell", "Flak", 5)
        sigs.append(play(g, 5))
        states.append(sorted((u.id, u.owner, int(u.type), u.x, u.y, u.hp) for u in g.units.values()))
    assert sigs[0] == sigs[1] and states[0] == states[1]


def test_some_games_end():
    ended = 0
    for i in range(10):
        g = random_game("Andy", "Max", i)
        play(g, i, max_steps=1500)
        ended += g.done
    assert ended >= 1
