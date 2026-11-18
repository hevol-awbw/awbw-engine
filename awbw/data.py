"""Static AWBW data: units, terrain, movement costs, base damage chart, terrain IDs.

Sources: awbw.amarriner.com units.php, damage.php, terrain.php, terrain_map.php,
countries.php (fetched by hand and transcribed). Anything NOT on those pages is
marked ASSUMPTION in a comment and listed in README.md.
"""
from __future__ import annotations

from dataclasses import dataclass
from enum import IntEnum


class UT(IntEnum):
    """Unit types, in damage.php row/column order."""
    AA = 0
    APC = 1
    ARTY = 2
    BCOPTER = 3
    BATTLESHIP = 4
    BLACKBOAT = 5
    BLACKBOMB = 6
    BOMBER = 7
    CARRIER = 8
    CRUISER = 9
    FIGHTER = 10
    INF = 11
    LANDER = 12
    MDTANK = 13
    MECH = 14
    MEGATANK = 15
    MISSILE = 16
    NEO = 17
    PIPE = 18
    RECON = 19
    ROCKET = 20
    STEALTH = 21
    SUB = 22
    TCOPTER = 23
    TANK = 24


class MT(IntEnum):
    """Movement types (units.php): F foot, B boots(mech), T treads, W tires, A air, S sea, L lander, P pipe."""
    F = 0
    B = 1
    T = 2
    W = 3
    A = 4
    S = 5
    L = 6
    P = 7


@dataclass(frozen=True)
class UnitInfo:
    name: str
    mp: int
    ammo: int
    fuel: int
    fuel_per_turn: int
    vision: int
    rmin: int          # attack range (units.php shows 0-0 for direct units; we store 1-1 if it can attack)
    rmax: int
    mt: MT
    cost: int
    hidden_fuel: int = 0   # fuel/turn while hidden (stealth) / submerged (sub); 0 = n/a


_U = UnitInfo
UNITS: dict[UT, UnitInfo] = {
    UT.AA:         _U("Anti-Air",   6, 9, 60, 0, 2, 1, 1, MT.T, 8000),
    UT.APC:        _U("APC",        6, 0, 70, 0, 1, 0, 0, MT.T, 5000),
    UT.ARTY:       _U("Artillery",  5, 9, 50, 0, 1, 2, 3, MT.T, 6000),
    UT.BCOPTER:    _U("B-Copter",   6, 6, 99, 2, 3, 1, 1, MT.A, 9000),
    UT.BATTLESHIP: _U("Battleship", 5, 9, 99, 1, 2, 2, 6, MT.S, 28000),
    UT.BLACKBOAT:  _U("Black Boat", 7, 0, 60, 1, 1, 0, 0, MT.L, 7500),
    UT.BLACKBOMB:  _U("Black Bomb", 9, 0, 45, 5, 1, 0, 0, MT.A, 25000),
    UT.BOMBER:     _U("Bomber",     7, 9, 99, 5, 2, 1, 1, MT.A, 22000),
    UT.CARRIER:    _U("Carrier",    5, 9, 99, 1, 4, 3, 8, MT.S, 30000),
    UT.CRUISER:    _U("Cruiser",    6, 9, 99, 1, 3, 1, 1, MT.S, 18000),
    UT.FIGHTER:    _U("Fighter",    9, 9, 99, 5, 2, 1, 1, MT.A, 20000),
    UT.INF:        _U("Infantry",   3, 0, 99, 0, 2, 1, 1, MT.F, 1000),
    UT.LANDER:     _U("Lander",     6, 0, 99, 1, 1, 0, 0, MT.L, 12000),
    UT.MDTANK:     _U("Md.Tank",    5, 8, 50, 0, 1, 1, 1, MT.T, 16000),
    UT.MECH:       _U("Mech",       2, 3, 70, 0, 2, 1, 1, MT.B, 3000),
    UT.MEGATANK:   _U("Mega Tank",  4, 3, 50, 0, 1, 1, 1, MT.T, 28000),
    UT.MISSILE:    _U("Missile",    4, 6, 50, 0, 5, 3, 5, MT.W, 12000),
    UT.NEO:        _U("Neotank",    6, 9, 99, 0, 1, 1, 1, MT.T, 22000),
    UT.PIPE:       _U("Piperunner", 9, 9, 99, 0, 4, 2, 5, MT.P, 20000),
    UT.RECON:      _U("Recon",      8, 0, 80, 0, 5, 1, 1, MT.W, 4000),
    UT.ROCKET:     _U("Rocket",     5, 6, 50, 0, 1, 3, 5, MT.W, 15000),
    UT.STEALTH:    _U("Stealth",    6, 6, 60, 5, 4, 1, 1, MT.A, 24000, hidden_fuel=8),
    UT.SUB:        _U("Sub",        5, 6, 60, 1, 5, 1, 1, MT.S, 20000, hidden_fuel=5),
    UT.TCOPTER:    _U("T-Copter",   6, 0, 99, 2, 2, 0, 0, MT.A, 5000),
    UT.TANK:       _U("Tank",       6, 9, 70, 0, 3, 1, 1, MT.T, 7000),
}

FOOT = frozenset({UT.INF, UT.MECH})
AIR_UNITS = frozenset(u for u, i in UNITS.items() if i.mt == MT.A)
NAVAL_UNITS = frozenset(u for u, i in UNITS.items() if i.mt in (MT.S, MT.L))
INDIRECT = frozenset(u for u, i in UNITS.items() if i.rmax > 1)
LAND_INDIRECT = frozenset({UT.ARTY, UT.ROCKET, UT.MISSILE, UT.PIPE})
VEHICLES = frozenset(u for u, i in UNITS.items() if i.mt in (MT.T, MT.W, MT.P))
GROUND_UNITS = frozenset(u for u, i in UNITS.items() if i.mt in (MT.F, MT.B, MT.T, MT.W, MT.P))
TRANSPORTS = frozenset({UT.APC, UT.LANDER, UT.TCOPTER, UT.BLACKBOAT})

# ---------------------------------------------------------------- damage chart
# damage.php, rows = attacker, columns = defender, both in UT order. '-' = cannot attack.
_DMG_TEXT = """
45 50 50 120 - - 120 75 - - 65 105 - 10 105 1 55 5 25 60 55 75 - 120 25
- - - - - - - - - - - - - - - - - - - - - - - - -
75 70 75 - 40 55 - - 45 65 - 90 55 45 85 15 80 40 70 80 80 - 60 - 70
25 60 65 65 25 25 - - 25 55 - 75 25 25 75 10 65 20 55 55 65 - 25 95 55
85 80 80 - 50 95 - - 60 95 - 95 95 55 90 25 90 50 80 90 85 - 95 - 80
- - - - - - - - - - - - - - - - - - - - - - - - -
- - - - - - - - - - - - - - - - - - - - - - - - -
95 105 105 - 75 95 - - 75 85 - 110 95 95 110 35 105 90 105 105 105 - 95 - 105
- - - 115 - - 120 100 - - 100 - - - - - - - - - - 100 - 115 -
- - - 115 - 25 120 65 5 - 55 - - - - - - - - - - 100 90 115 -
- - - 100 - - 120 100 - - 55 - - - - - - - - - - 85 - 100 -
5 14 15 7 - - - - - - - 55 - 1 45 1 25 1 5 12 25 - - 30 5
- - - - - - - - - - - - - - - - - - - - - - - - -
105 105 105 12 10 35 - - 10 45 - 105 35 55 95 25 105 45 85 105 105 - 10 45 85
65 75 70 9 - - - - - - - 65 - 15 55 5 85 15 55 85 85 - - 35 55
195 195 195 22 45 105 - - 45 65 - 135 75 125 125 65 195 115 180 195 195 - 45 55 180
- - - 120 - - 120 100 - - 100 - - - - - - - - - - 100 - 120 -
115 125 115 22 15 40 - - 15 50 - 125 40 75 115 35 125 55 105 125 125 - 15 55 105
85 80 80 105 55 60 120 75 60 60 65 95 60 55 90 25 90 50 80 90 85 75 85 105 80
4 45 45 10 - - - - - - - 70 - 1 65 1 28 1 6 35 55 - - 35 6
85 80 80 - 55 60 - - 60 85 - 95 60 55 90 25 90 50 80 90 85 - 85 - 80
50 85 75 85 45 65 120 70 45 35 45 90 65 70 90 15 85 60 80 85 85 55 55 95 75
- - - - 55 95 - - 75 25 - - 95 - - - - - - - - - 55 - -
- - - - - - - - - - - - - - - - - - - - - - - - -
65 75 70 10 1 10 - - 1 5 - 75 10 15 70 10 85 15 55 85 85 - 1 40 55
"""


def _parse_damage() -> list[list[int]]:
    rows = [r.split() for r in _DMG_TEXT.strip().splitlines()]
    assert len(rows) == 25 and all(len(r) == 25 for r in rows)
    return [[0 if c == "-" else int(c) for c in r] for r in rows]


DMG: list[list[int]] = _parse_damage()   # 0 means "cannot attack"


def base_damage(att: UT, dfn: UT) -> int:
    return DMG[att][dfn]


# ASSUMPTION (not on any chart page): which weapon a unit uses decides whether ammo is consumed.
# Machine guns have unlimited ammo. Based on Advance Wars weapon loadouts.
_MG_ALWAYS = {UT.INF, UT.RECON}
_MG_VS_SOFT = {UT.TANK, UT.MDTANK, UT.NEO, UT.MEGATANK, UT.MECH}   # MG vs foot + copters
_SOFT_TARGETS = {UT.INF, UT.MECH, UT.BCOPTER, UT.TCOPTER}
_BCOPTER_MG = {UT.INF, UT.MECH, UT.BCOPTER, UT.TCOPTER}   # machine gun (AWBW replays: no ammo used vs copters)
_AIR = {UT.FIGHTER, UT.BOMBER, UT.STEALTH, UT.BCOPTER, UT.TCOPTER, UT.BLACKBOMB}


def uses_ammo(att: UT, dfn: UT) -> bool:
    if att in _MG_ALWAYS:
        return False
    if att in _MG_VS_SOFT and dfn in _SOFT_TARGETS:
        return False
    if att == UT.BCOPTER and dfn in _BCOPTER_MG:
        return False
    if att == UT.CRUISER and dfn in _AIR:          # anti-air gun, unlimited (AWBW replays)
        return False
    return True


# Machine-gun (secondary weapon) damage against targets the primary weapon hits, used once the primary is out of
# ammo (AWBW replays: B-Copters / Mechs / Tanks with 0 ammo still attack vehicles). Values = Advance Wars 2 secondary
# weapon chart, which AWBW follows; the soft targets above already use the machine gun in the main chart.
# Defender order: Recon, Tank, Md.Tank, Neotank, Megatank, APC, Artillery, Rocket, Anti-Air, Missile, Pipe Runner.
_MG_COLS = (UT.RECON, UT.TANK, UT.MDTANK, UT.NEO, UT.MEGATANK, UT.APC, UT.ARTY, UT.ROCKET, UT.AA, UT.MISSILE, UT.PIPE)
_MG_ROWS = {
    UT.MECH:     (18, 6, 1, 1, 1, 20, 32, 35, 6, 35, 6),
    UT.TANK:     (40, 6, 1, 1, 1, 45, 45, 55, 5, 30, 6),
    UT.MDTANK:   (45, 8, 1, 1, 1, 45, 45, 55, 7, 35, 8),
    UT.NEO:      (65, 10, 1, 1, 1, 65, 65, 75, 17, 55, 10),
    UT.MEGATANK: (65, 10, 1, 1, 1, 65, 65, 75, 17, 55, 10),
    UT.BCOPTER:  (30, 6, 1, 1, 1, 20, 25, 35, 6, 35, 6),
}
MG_DMG: list[list[int]] = [[0] * len(UT) for _ in UT]
for _a, _row in _MG_ROWS.items():
    for _d, _v in zip(_MG_COLS, _row):
        MG_DMG[_a][_d] = _v


def weapon(att: UT, dfn: UT, ammo: int) -> tuple[int, bool]:
    """(base damage, uses ammo) of the weapon `att` fights `dfn` with: the main chart's weapon while it has ammo for
    it (or it needs none), else the machine gun if it has one (0 = cannot attack)."""
    b = DMG[att][dfn]
    if att == UT.CRUISER and ammo <= 0:          # libaw B23: out of ammo a Cruiser cannot fire at all
        return 0, False
    if b and (ammo > 0 or not uses_ammo(att, dfn)):
        return b, uses_ammo(att, dfn)
    return MG_DMG[att][dfn], False


# ---------------------------------------------------------------- terrain
class TK(IntEnum):
    PLAIN = 0
    MOUNTAIN = 1
    WOOD = 2
    RIVER = 3
    ROAD = 4
    BRIDGE = 5
    SEA = 6
    SHOAL = 7
    REEF = 8
    CITY = 9
    BASE = 10
    AIRPORT = 11
    PORT = 12
    HQ = 13
    PIPE = 14
    COMTOWER = 15
    LAB = 16
    SILO = 17
    SILO_EMPTY = 18
    SEAM = 19
    RUBBLE = 20


# terrain.php defense stars. ASSUMPTION: SILO_EMPTY keeps 3 stars, RUBBLE behaves like plain.
STARS = {
    TK.PLAIN: 1, TK.MOUNTAIN: 4, TK.WOOD: 2, TK.RIVER: 0, TK.ROAD: 0, TK.BRIDGE: 0,
    TK.SEA: 0, TK.SHOAL: 0, TK.REEF: 1, TK.CITY: 3, TK.BASE: 3, TK.AIRPORT: 3,
    TK.PORT: 3, TK.HQ: 4, TK.PIPE: 0, TK.COMTOWER: 3, TK.LAB: 3, TK.SILO: 3,
    TK.SILO_EMPTY: 3, TK.SEAM: 0, TK.RUBBLE: 1,
}

CAPTURABLE = frozenset({TK.CITY, TK.BASE, TK.AIRPORT, TK.PORT, TK.HQ, TK.COMTOWER, TK.LAB})
INCOME_PROPS = frozenset({TK.CITY, TK.BASE, TK.AIRPORT, TK.PORT, TK.HQ})
URBAN = frozenset({TK.HQ, TK.BASE, TK.AIRPORT, TK.PORT, TK.CITY, TK.LAB, TK.COMTOWER})  # Kindle


def _row(f, b, t, w, a, s=None, l=None, p=None):
    return {MT.F: f, MT.B: b, MT.T: t, MT.W: w, MT.A: a, MT.S: s, MT.L: l, MT.P: p}


# terrain.php: per weather (C=clear, R=rain, S=snow), per terrain: F B T W A S L P
_CL = {
    TK.PLAIN: _row(1, 1, 1, 2, 1), TK.MOUNTAIN: _row(2, 1, None, None, 1),
    TK.WOOD: _row(1, 1, 2, 3, 1), TK.RIVER: _row(2, 1, None, None, 1),
    TK.ROAD: _row(1, 1, 1, 1, 1), TK.BRIDGE: _row(1, 1, 1, 1, 1),
    TK.SEA: _row(None, None, None, None, 1, 1, 1), TK.SHOAL: _row(1, 1, 1, 1, 1, None, 1),
    TK.REEF: _row(None, None, None, None, 1, 2, 2),
    TK.CITY: _row(1, 1, 1, 1, 1), TK.BASE: _row(1, 1, 1, 1, 1, None, None, 1),
    TK.AIRPORT: _row(1, 1, 1, 1, 1), TK.PORT: _row(1, 1, 1, 1, 1, 1, 1),
    TK.HQ: _row(1, 1, 1, 1, 1), TK.PIPE: _row(None, None, None, None, None, None, None, 1),
    TK.COMTOWER: _row(1, 1, 1, 1, 1), TK.LAB: _row(1, 1, 1, 1, 1), TK.SILO: _row(1, 1, 1, 1, 1),
    TK.SILO_EMPTY: _row(1, 1, 1, 1, 1), TK.SEAM: _row(*[None] * 8),
    TK.RUBBLE: _row(1, 1, 1, 2, 1),
}


def _variant(base, edits):
    out = {k: dict(v) for k, v in base.items()}
    for k, e in edits.items():
        out[k].update(e)
    return out


_RAIN = _variant(_CL, {
    TK.PLAIN: {MT.T: 2, MT.W: 3}, TK.WOOD: {MT.T: 3, MT.W: 4}, TK.RUBBLE: {MT.T: 2, MT.W: 3},
})
# snow: air costs 2 everywhere it can go; some ground costs change
_SNOW = _variant(_CL, {
    TK.PLAIN: {MT.F: 2, MT.T: 2, MT.W: 3}, TK.MOUNTAIN: {MT.F: 4, MT.B: 2},
    TK.WOOD: {MT.F: 2, MT.B: 1, MT.T: 2, MT.W: 3}, TK.RUBBLE: {MT.F: 2, MT.T: 2, MT.W: 3},
})
for _k, _r in _SNOW.items():
    for _m in (MT.A, MT.S, MT.L):
        if _r[_m] is not None and (_m == MT.A or _k in (TK.SEA, TK.REEF, TK.PORT)):
            _r[_m] = 2
# shoal/lander stays 1 in snow, port sea=2 handled above; shoal L stays 1.
_SNOW[TK.SHOAL][MT.L] = 1

MOVE_COST = {"C": _CL, "R": _RAIN, "S": _SNOW}


def move_cost(weather: str, tk: TK, mt: MT):
    """Movement cost or None if impassable."""
    return MOVE_COST[weather][tk][mt]


# ---------------------------------------------------------------- production
FACTORY_UNITS = (UT.INF, UT.MECH, UT.TANK, UT.MDTANK, UT.NEO, UT.MEGATANK, UT.AA, UT.ARTY,
                 UT.ROCKET, UT.MISSILE, UT.RECON, UT.APC, UT.PIPE)
AIRPORT_UNITS = (UT.BCOPTER, UT.TCOPTER, UT.BOMBER, UT.FIGHTER, UT.STEALTH, UT.BLACKBOMB)
PORT_UNITS = (UT.LANDER, UT.BLACKBOAT, UT.CRUISER, UT.SUB, UT.BATTLESHIP, UT.CARRIER)
BUILDS = {TK.BASE: FACTORY_UNITS, TK.AIRPORT: AIRPORT_UNITS, TK.PORT: PORT_UNITS}

# transport capacity / what can be carried
CARRY = {
    UT.APC: (1, FOOT),
    UT.TCOPTER: (1, FOOT),
    UT.BLACKBOAT: (2, FOOT),
    UT.LANDER: (2, GROUND_UNITS),
    UT.CRUISER: (2, frozenset({UT.BCOPTER, UT.TCOPTER})),
    UT.CARRIER: (2, AIR_UNITS),
}

# ---------------------------------------------------------------- countries / terrain ids
COUNTRIES = {
    1: "Orange Star", 2: "Blue Moon", 3: "Green Earth", 4: "Yellow Comet", 5: "Black Hole",
    6: "Red Fire", 7: "Grey Sky", 8: "Brown Desert", 9: "Amber Blossom", 10: "Jade Sun",
    11: "Cobalt Ice", 12: "Pink Cosmos", 13: "Teal Galaxy", 14: "Purple Lightning",
    15: "Acid Rain", 16: "White Nova", 17: "Azure Asteroid", 18: "Noir Eclipse",
    19: "Silver Claw", 20: "Umber Wilds",
}


def _build_terrain_ids() -> dict[int, tuple[TK, int | None]]:
    t: dict[int, tuple[TK, int | None]] = {1: (TK.PLAIN, None), 2: (TK.MOUNTAIN, None), 3: (TK.WOOD, None)}
    for i in range(4, 15):
        t[i] = (TK.RIVER, None)
    for i in range(15, 26):
        t[i] = (TK.ROAD, None)
    t[26] = (TK.BRIDGE, None)
    t[27] = (TK.BRIDGE, None)
    t[28] = (TK.SEA, None)
    for i in range(29, 33):
        t[i] = (TK.SHOAL, None)
    t[33] = (TK.REEF, None)
    t[34], t[35], t[36], t[37] = (TK.CITY, None), (TK.BASE, None), (TK.AIRPORT, None), (TK.PORT, None)
    five = [(1, 38), (2, 43), (3, 48), (4, 53), (6, 81), (7, 86), (5, 91), (8, 96)]
    for cid, start in five:   # city, base, airport, port, hq
        for off, tk in enumerate((TK.CITY, TK.BASE, TK.AIRPORT, TK.PORT, TK.HQ)):
            t[start + off] = (tk, cid)
    for i in range(101, 111):
        t[i] = (TK.PIPE, None)
    t[111], t[112] = (TK.SILO, None), (TK.SILO_EMPTY, None)
    t[113], t[114] = (TK.SEAM, None), (TK.SEAM, None)
    t[115], t[116] = (TK.RUBBLE, None), (TK.RUBBLE, None)
    for cid, start in ((9, 117), (10, 122)):   # airport, base, city, hq, port
        for off, tk in enumerate((TK.AIRPORT, TK.BASE, TK.CITY, TK.HQ, TK.PORT)):
            t[start + off] = (tk, cid)
    for cid, tid in zip((9, 5, 2, 8, 3, 10, None, 1, 6, 4, 7), range(127, 138)):
        t[tid] = (TK.COMTOWER, cid)
    for cid, tid in zip((9, 5, 2, 8, 3, 7, 10, None, 1, 6, 4), range(138, 149)):
        t[tid] = (TK.LAB, cid)
    t[133] = (TK.COMTOWER, None)
    t[145] = (TK.LAB, None)
    seven = [(11, 149), (12, 156), (13, 163), (14, 170), (15, 181), (16, 188),
             (17, 196), (18, 203), (19, 210), (20, 217)]
    for cid, start in seven:   # airport, base, city, comtower, hq, lab, port
        for off, tk in enumerate((TK.AIRPORT, TK.BASE, TK.CITY, TK.COMTOWER, TK.HQ, TK.LAB, TK.PORT)):
            t[start + off] = (tk, cid)
    return t


TERRAIN_IDS = _build_terrain_ids()
