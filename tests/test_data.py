from awbw.data import (DMG, UT, UNITS, TK, MT, STARS, TERRAIN_IDS, move_cost, uses_ammo, BUILDS,
                       COUNTRIES, CARRY)


def test_damage_chart_spot_checks():
    # values read straight off damage.php
    assert DMG[UT.TANK][UT.INF] == 75
    assert DMG[UT.TANK][UT.TANK] == 55
    assert DMG[UT.INF][UT.INF] == 55
    assert DMG[UT.MEGATANK][UT.INF] == 135
    assert DMG[UT.BOMBER][UT.TANK] == 105
    assert DMG[UT.FIGHTER][UT.BOMBER] == 100
    assert DMG[UT.ARTY][UT.TANK] == 70
    assert DMG[UT.SUB][UT.BATTLESHIP] == 55
    assert DMG[UT.CRUISER][UT.SUB] == 90
    assert DMG[UT.STEALTH][UT.SUB] == 55
    assert DMG[UT.PIPE][UT.BLACKBOMB] == 120


def test_non_attackers_have_empty_rows():
    for t in (UT.APC, UT.BLACKBOAT, UT.BLACKBOMB, UT.LANDER, UT.TCOPTER):
        assert all(v == 0 for v in DMG[t]), t


def test_who_can_hit_what():
    # air-only attackers cannot hit ground; AA can hit infantry; infantry cannot hit B-Copter? (it can: 7)
    assert DMG[UT.FIGHTER][UT.TANK] == 0
    assert DMG[UT.INF][UT.BCOPTER] == 7
    assert DMG[UT.INF][UT.BOMBER] == 0
    assert DMG[UT.ARTY][UT.BCOPTER] == 0
    assert DMG[UT.TANK][UT.BCOPTER] == 10


def test_unit_table():
    assert UNITS[UT.INF].cost == 1000 and UNITS[UT.INF].mp == 3 and UNITS[UT.INF].mt == MT.F
    assert UNITS[UT.AA].cost == 8000
    assert UNITS[UT.ARTY].rmin == 2 and UNITS[UT.ARTY].rmax == 3
    assert UNITS[UT.CARRIER].rmin == 3 and UNITS[UT.CARRIER].rmax == 8
    assert UNITS[UT.STEALTH].hidden_fuel == 8 and UNITS[UT.SUB].hidden_fuel == 5
    assert len(UNITS) == 25


def test_ammo_rules():
    assert not uses_ammo(UT.INF, UT.TANK)
    assert not uses_ammo(UT.TANK, UT.INF)
    assert uses_ammo(UT.TANK, UT.TANK)
    assert not uses_ammo(UT.BCOPTER, UT.INF)
    assert uses_ammo(UT.BCOPTER, UT.TANK)
    assert uses_ammo(UT.ARTY, UT.INF)


def test_terrain_costs():
    assert move_cost("C", TK.PLAIN, MT.T) == 1 and move_cost("C", TK.PLAIN, MT.W) == 2
    assert move_cost("R", TK.PLAIN, MT.T) == 2 and move_cost("R", TK.WOOD, MT.W) == 4
    assert move_cost("S", TK.MOUNTAIN, MT.F) == 4 and move_cost("S", TK.MOUNTAIN, MT.B) == 2
    assert move_cost("C", TK.MOUNTAIN, MT.T) is None
    assert move_cost("C", TK.SEA, MT.S) == 1 and move_cost("C", TK.SEA, MT.F) is None
    assert move_cost("C", TK.REEF, MT.S) == 2
    assert move_cost("C", TK.SHOAL, MT.L) == 1 and move_cost("C", TK.SHOAL, MT.S) is None
    assert move_cost("C", TK.PIPE, MT.P) == 1 and move_cost("C", TK.PIPE, MT.T) is None
    assert move_cost("C", TK.SEAM, MT.P) is None
    assert move_cost("S", TK.SEA, MT.A) == 2 and move_cost("S", TK.AIRPORT, MT.A) == 2
    assert move_cost("S", TK.SEA, MT.S) == 2


def test_stars():
    assert STARS[TK.MOUNTAIN] == 4 and STARS[TK.HQ] == 4 and STARS[TK.CITY] == 3
    assert STARS[TK.WOOD] == 2 and STARS[TK.PLAIN] == 1 and STARS[TK.ROAD] == 0 and STARS[TK.REEF] == 1


def test_terrain_id_table():
    assert TERRAIN_IDS[1] == (TK.PLAIN, None)
    assert TERRAIN_IDS[38] == (TK.CITY, 1) and TERRAIN_IDS[42] == (TK.HQ, 1)
    assert TERRAIN_IDS[43] == (TK.CITY, 2) and TERRAIN_IDS[47] == (TK.HQ, 2)
    assert TERRAIN_IDS[96] == (TK.CITY, 8)
    assert TERRAIN_IDS[117] == (TK.AIRPORT, 9) and TERRAIN_IDS[121] == (TK.PORT, 9)
    assert TERRAIN_IDS[134] == (TK.COMTOWER, 1) and TERRAIN_IDS[133] == (TK.COMTOWER, None)
    assert TERRAIN_IDS[146] == (TK.LAB, 1) and TERRAIN_IDS[145] == (TK.LAB, None)
    assert TERRAIN_IDS[153] == (TK.HQ, 11) and TERRAIN_IDS[223] == (TK.PORT, 20)
    assert TERRAIN_IDS[111] == (TK.SILO, None)
    # every country has an HQ id
    hq_countries = {c for (k, c) in TERRAIN_IDS.values() if k == TK.HQ}
    assert hq_countries == set(COUNTRIES)


def test_production_menus():
    assert UT.TANK in BUILDS[TK.BASE] and UT.PIPE in BUILDS[TK.BASE]
    assert UT.FIGHTER in BUILDS[TK.AIRPORT] and UT.BLACKBOMB in BUILDS[TK.AIRPORT]
    assert UT.LANDER in BUILDS[TK.PORT] and UT.CARRIER in BUILDS[TK.PORT]
    assert sum(len(v) for v in BUILDS.values()) == 25
    assert CARRY[UT.LANDER][0] == 2
