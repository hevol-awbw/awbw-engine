"""The Rust engine (awbw_rs) must behave exactly like the Python reference engine.

Random games are played through both engines from the same state with the same luck rolls; after every action the
full state (units, HP, fuel, ammo, funds, meters, buildings, weather, missiles ...) and the complete set of legal
actions must be identical. Skipped when awbw_rs is not built (see rust/README.md).
"""
import random

import pytest

from awbw.cos import COS
from awbw.data import TK, UT
from awbw.fast import act_to_tuple, det_luck, py_state, to_rust
from awbw.game import AT, Action, Game, IllegalAction
from awbw.maps import from_ascii

awbw_rs = pytest.importorskip("awbw_rs")
pytestmark = pytest.mark.rust

from tests.test_fuzz import ROWS, START  # noqa: E402

CO_NAMES = list(COS)

# a second map with pipes, pipe seams and a lab, for Piperunners and seam attacks
SEAM_ROWS = [
    "HB..c....cbh",
    "..=..@@..=..",
    "..=..^^..=..",
    "....c..c....",
    "............",
    "CB..c....cbD",
]
SEAM_START = [(0, UT.INF, 2, 4), (0, UT.TANK, 3, 4), (0, UT.ARTY, 1, 3), (0, UT.PIPE, 5, 4),
              (1, UT.INF, 9, 4), (1, UT.TANK, 8, 4), (1, UT.ROCKET, 10, 3), (1, UT.PIPE, 6, 4)]


def seam_game(co0, co1, seed):
    kinds, owners = from_ascii(SEAM_ROWS)
    for x in range(3, 9):
        kinds[4][x] = TK.PIPE
    kinds[4][4], kinds[4][7] = TK.SEAM, TK.SEAM
    kinds[3][6] = TK.LAB
    return Game(kinds, owners, cos=(co0, co1), units=SEAM_START, starting_funds=12000, seed=seed, max_days=25,
                unit_limit=30)


def fuzz_game(co0, co1, seed):
    kinds, owners = from_ascii(ROWS)
    return Game(kinds, owners, cos=(co0, co1), units=START, starting_funds=15000, seed=seed, max_days=40,
                unit_limit=40, banned_units=(UT.TANK, UT.STEALTH) if seed % 2 else ())


def compare(g, r, step, last, fast=None):
    a, b = py_state(g), r.state()
    if fast is not None:                               # the trusted fast path must stay identical too
        c = fast.state()
        diff = {k: (b[k], c[k]) for k in b if b[k] != c.get(k)}
        assert not diff, f"step {step} after {last}: step_trusted state differs in {sorted(diff)}"
        per_unit = [x for u in r.actionable_units() for x in r.unit_actions(u)] + r.build_actions() + r.global_actions()
        assert sorted(per_unit) == sorted(r.legal_actions()), f"step {step}: per-unit action lists != legal_actions"
    diff = {k: (a[k], b[k]) for k in a if a[k] != b.get(k)}
    assert not diff, f"step {step} after {last}: state differs in {sorted(diff)}: {str(diff)[:1500]}"
    pa = sorted(act_to_tuple(x) for x in g.legal_actions())
    ra = sorted(r.legal_actions())
    if pa != ra:
        only_py, only_rs = sorted(set(pa) - set(ra))[:8], sorted(set(ra) - set(pa))[:8]
        raise AssertionError(f"step {step} after {last}: legal actions differ; python only {only_py}, rust only {only_rs}")


def run(make, co0, co1, seed, steps):
    g = make(co0, co1, seed)
    g.luck_fn = det_luck(g, seed)
    r = to_rust(g, seed, 0)
    fast = to_rust(g, seed, 0)
    rnd = random.Random(seed)
    last = "start"
    for step in range(steps):
        compare(g, r, step, last, fast)
        if g.done:
            break
        p = g.cur
        if rnd.random() < 0.04:                        # force a power now and then, in both engines
            g.players[p].charge = g.max_charge(p)
            r = to_rust(g, seed, g.luck_fn.state["k"])
            fast = to_rust(g, seed, g.luck_fn.state["k"])
            compare(g, r, step, "forced charge", fast)
        acts = g.legal_actions()
        non_end = [a for a in acts if a.type != AT.END_TURN]
        if not non_end or rnd.random() < 0.05:
            a = Action(AT.END_TURN)
        else:
            powers = [a for a in non_end if a.type == AT.POWER]
            a = rnd.choice(powers) if powers and rnd.random() < 0.6 else rnd.choice(non_end)
        g.step(a)
        r.step(act_to_tuple(a))
        fast.step_trusted(act_to_tuple(a))
        last = a
    compare(g, r, steps, last, fast)
    return g


@pytest.mark.parametrize("i", range(len(CO_NAMES)))
def test_rust_matches_python_fuzz_map(i):
    co0, co1 = CO_NAMES[i], CO_NAMES[(i * 7 + 3) % len(CO_NAMES)]
    run(fuzz_game, co0, co1, seed=1000 + i, steps=350)


@pytest.mark.parametrize("i", range(0, len(CO_NAMES), 2))
def test_rust_matches_python_seam_map(i):
    co0, co1 = CO_NAMES[i], CO_NAMES[(i + 5) % len(CO_NAMES)]
    run(seam_game, co0, co1, seed=2000 + i, steps=250)


def test_rust_copy_is_independent():
    g = fuzz_game("Andy", "Max", 1)
    r = to_rust(g)
    c = r.copy()
    r.step((int(AT.END_TURN), -1, -1, -1, -1, -1, 0))
    assert c.cur == 0 and r.cur == 1


def test_rust_rejects_illegal_actions():
    r = to_rust(fuzz_game("Andy", "Max", 1))
    with pytest.raises(ValueError):
        r.step((int(AT.WAIT), 99999, 0, 0, -1, -1, 0))
    g = fuzz_game("Andy", "Max", 1)
    with pytest.raises(IllegalAction):
        g.step(Action(AT.WAIT, 99999, (0, 0)))
