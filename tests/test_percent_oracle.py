"""Cross-check CO attack/defense modifiers against awbw.amarriner.com/percent.php.

The expectations below were transcribed from that page by reading its rows (alphabetical CO order)
and are written WITHOUT importing cos.py's rules. Values are the page's totals converted to
"before the universal +10% on powers": page COP/SCOP columns show (D2D + delta), and every delta
contains that universal +10 (except Von Bolt, who has no COP).
Dynamic bonuses (terrain, funds, towers, ...) are excluded: the harness stands units on river tiles
(0 stars, not plain/road/urban) with zero funds and no towers, so those terms are 0.
"""
import pytest

from awbw.cos import COS
from awbw.data import UT
from awbw.game import Game, Unit
from awbw.maps import make_game

ALL = set(UT)
NON_ATTACKERS = {UT.APC, UT.BLACKBOAT, UT.BLACKBOMB, UT.LANDER, UT.TCOPTER}
AIR = {UT.BCOPTER, UT.BLACKBOMB, UT.BOMBER, UT.FIGHTER, UT.STEALTH, UT.TCOPTER}
NAVAL = {UT.BATTLESHIP, UT.BLACKBOAT, UT.CARRIER, UT.CRUISER, UT.LANDER, UT.SUB}
FOOT = {UT.INF, UT.MECH}
INDIRECT = {UT.ARTY, UT.BATTLESHIP, UT.CARRIER, UT.MISSILE, UT.PIPE, UT.ROCKET}
# page columns where the "vehicle" CO bonuses (Jess) appear
JESS_VEH = {UT.AA, UT.ARTY, UT.MDTANK, UT.MEGATANK, UT.MISSILE, UT.NEO, UT.PIPE, UT.RECON,
            UT.ROCKET, UT.TANK}
DIRECT_NONFOOT = ALL - FOOT - INDIRECT - NON_ATTACKERS


def rule(default, *overrides):
    """overrides: (set_of_units, (d2d, cop, scop))"""
    def f(t):
        for s, v in overrides:
            if t in s:
                return v
        return default
    return f


FLAT = (100, 100, 100)
ATK = {
    "Adder": rule(FLAT),
    "Andy": rule((100, 100, 110)),
    "Colin": rule((90, 90, 90)),
    "Drake": rule(FLAT, (AIR, (70, 70, 70))),
    "Eagle": rule(FLAT, (AIR, (115, 120, 120)), (NAVAL, (70, 70, 70))),
    "Flak": rule(FLAT),
    "Grimm": rule((130, 150, 180)),
    "Grit": rule(FLAT, (INDIRECT, (120, 140, 140)), (DIRECT_NONFOOT, (80, 80, 80))),
    "Hachi": rule(FLAT),
    "Hawke": rule((110, 110, 110)),
    "Jake": rule(FLAT),
    "Javier": rule(FLAT),
    "Jess": rule((90, 90, 90), (JESS_VEH, (110, 120, 140))),
    "Jugger": rule(FLAT),
    "Kanbei": rule((130, 140, 140)),
    "Kindle": rule(FLAT),
    "Koal": rule(FLAT),
    "Lash": rule(FLAT),
    "Max": rule(FLAT, (INDIRECT, (90, 90, 90)), (DIRECT_NONFOOT, (120, 130, 150))),
    "Nell": rule(FLAT),
    "Olaf": rule(FLAT),
    "Rachel": rule(FLAT),
    "Sami": rule((90, 90, 90), (FOOT, (130, 150, 170)), (INDIRECT, (100, 100, 100))),
    "Sasha": rule(FLAT),
    "Sensei": rule((90, 90, 90), (FOOT, (140, 140, 140)), ({UT.BCOPTER}, (150, 165, 165)),
                   ({UT.BOMBER, UT.FIGHTER, UT.STEALTH}, (100, 100, 100))),
    "Sonja": rule(FLAT),
    "Sturm": rule((80, 80, 80)),
    "Von Bolt": rule((110, 110, 110)),
}
DEF = {c: rule(FLAT) for c in ATK}
DEF["Drake"] = rule(FLAT, (NAVAL, (110, 110, 110)))
DEF["Eagle"] = rule(FLAT, (AIR, (110, 120, 120)))
DEF["Grimm"] = rule((80, 80, 80))
DEF["Kanbei"] = rule((130, 130, 150))
DEF["Sturm"] = rule((120, 120, 120))
DEF["Von Bolt"] = rule((110, 110, 110))


@pytest.fixture(scope="module")
def harness():
    rows = ["rrr", "rrr", "rrr"]
    return make_game(rows, [(0, UT.INF, 0, 0), (1, UT.INF, 1, 0)])


def test_all_28_cos_present():
    assert len(COS) == 28 and set(COS) == set(ATK)


@pytest.mark.parametrize("co", sorted(ATK))
def test_attack_matches_percent_php(co, harness):
    g = harness
    g.players[0].co = co
    g.players[0].power = 0
    defender = Unit(99, 1, UT.INF, 1, 0)
    for t in UT:
        if t in NON_ATTACKERS:
            continue
        u = Unit(98, 0, t, 0, 0)
        exp = ATK[co](t)
        for lvl in (0, 1, 2):
            if lvl == 1 and not COS[co].has_cop:
                continue
            got = COS[co].atk(g, 0, u, defender, lvl)
            assert got == exp[lvl], f"{co} {t.name} lvl{lvl}: got {got} expected {exp[lvl]}"


@pytest.mark.parametrize("co", sorted(DEF))
def test_defense_matches_percent_php(co, harness):
    g = harness
    g.players[1].co = co
    attacker = Unit(98, 0, UT.INF, 0, 0)          # a direct attacker: Javier's indirect bonus is off
    for t in UT:
        d = Unit(99, 1, t, 1, 0)
        exp = DEF[co](t)
        for lvl in (0, 1, 2):
            if lvl == 1 and not COS[co].has_cop:
                continue
            got = COS[co].dfn(g, 1, d, attacker, lvl)
            assert got == exp[lvl], f"{co} {t.name} lvl{lvl}: got {got} expected {exp[lvl]}"
