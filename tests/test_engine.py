import pytest

from awbw.data import UT, TK, UNITS
from awbw.game import Action, AT, Game, IllegalAction, disp
from awbw.maps import make_game

PLAIN5 = ["Hh...", ".....", ".....", ".....", "....."]


def luck(n):
    return lambda p: n


def new(rows, units, cos=("Andy", "Andy"), **kw):
    kw.setdefault("luck_fn", luck(0))
    return make_game(rows, units, cos=cos, **kw)


def A(t, unit=-1, dest=None, target=None, arg=0):
    return Action(t, unit, dest, target, arg)


def uid_at(g, x, y):
    return g.pos[(x, y)]


# ------------------------------------------------------------------ damage formula
def test_tank_vs_infantry_plain():
    g = new(PLAIN5, [(0, UT.TANK, 1, 1), (1, UT.INF, 2, 1)])
    a, d = g.units[1], g.units[2]
    # (75*100/100 + 0) * 10/10 * (200-(100+1*10))/100 = 67.5 -> 67 (floor; rounding is an assumption)
    assert g.damage_calc(a, d, 0) == 67
    assert g.damage_calc(a, d, 9) == 75


def test_infantry_vs_infantry_and_terrain():
    g = new(["..^..", ".....", ".....", ".....", "....."], [(0, UT.INF, 1, 0), (1, UT.INF, 2, 0)])
    a, d = g.units[1], g.units[2]
    assert g.damage_calc(a, d, 0) == 33        # mountain: 55 * (200-(100+4*10))/100 = 33


def test_attacker_hp_scales_damage():
    g = new(PLAIN5, [(0, UT.TANK, 1, 1, 50), (1, UT.INF, 2, 1)])
    assert g.damage_calc(g.units[1], g.units[2], 0) == 33     # 75 * 0.5 * 0.9 = 33.75


def test_defender_hp_scales_terrain_defense():
    g = new(PLAIN5, [(0, UT.TANK, 1, 1), (1, UT.INF, 2, 1, 30)])
    # terrain star term uses defender display HP: (200-(100+1*3))/100 = .97 -> 75*.97 = 72
    assert g.damage_calc(g.units[1], g.units[2], 0) == 72


def test_air_units_ignore_terrain():
    g = new(["^^^..", ".....", ".....", ".....", "....."], [(0, UT.BOMBER, 3, 0), (1, UT.BCOPTER, 1, 0)])
    # no 'bomber vs b-copter' entry
    assert g.damage_calc(g.units[1], g.units[2], 0) == 0
    g = new(["^^^..", ".....", ".....", ".....", "....."], [(0, UT.FIGHTER, 3, 0), (1, UT.BCOPTER, 1, 0)])
    assert g.damage_calc(g.units[1], g.units[2], 0) == 100 * 100 // 100  # 100 base, 0 stars for air


def test_counterattack_and_ammo():
    g = new(PLAIN5, [(0, UT.TANK, 1, 1), (1, UT.TANK, 2, 1)])
    t0, t1 = g.units[1], g.units[2]
    g.step(A(AT.ATTACK, 1, (1, 1), (2, 1)))
    assert t1.hp == 100 - 49          # 55*0.9 = 49.5 -> 49
    assert t0.hp < 100                # counter happened
    assert t0.ammo == 8 and t1.ammo == 8
    assert g.units[1].acted


def test_no_counter_from_indirect_and_none_vs_ranged():
    g = new(PLAIN5, [(0, UT.ARTY, 0, 1), (1, UT.TANK, 2, 1)])
    g.step(A(AT.ATTACK, 1, (0, 1), (2, 1)))
    assert g.units[1].hp == 100 and g.units[2].hp < 100


def test_indirect_cannot_move_and_fire():
    g = new(PLAIN5, [(0, UT.ARTY, 0, 1), (1, UT.TANK, 3, 1)])
    acts = g.unit_actions(g.units[1])
    assert any(a.type == AT.ATTACK and a.dest == (0, 1) for a in acts)
    assert not any(a.type == AT.ATTACK and a.dest != (0, 1) for a in acts)


def test_min_range_respected():
    g = new(PLAIN5, [(0, UT.ARTY, 1, 1), (1, UT.TANK, 2, 1)])
    assert not any(a.type == AT.ATTACK for a in g.unit_actions(g.units[1]) if a.dest == (1, 1))


def test_unit_dies_no_counter():
    g = new(PLAIN5, [(0, UT.TANK, 1, 1), (1, UT.INF, 2, 1, 10)])
    g.step(A(AT.ATTACK, 1, (1, 1), (2, 1)))
    assert 2 not in g.units and g.units[1].hp == 100


# ------------------------------------------------------------------ CO effects on damage
def test_grimm_vs_andy():
    g = new(PLAIN5, [(0, UT.TANK, 1, 1), (1, UT.TANK, 2, 1)], cos=("Grimm", "Andy"))
    # 55*1.3 = 71.5; * (200-110)/100 = .9 -> 64.35 -> 64
    assert g.damage_calc(g.units[1], g.units[2], 0) == 64
    # Grimm defending has 80% defense: (200 - (80 + 10))/100 = 1.1
    assert g.damage_calc(g.units[2], g.units[1], 0) == 60


def test_luck_added_before_scaling():
    g = new(PLAIN5, [(0, UT.TANK, 1, 1), (1, UT.TANK, 2, 1)])
    assert g.damage_calc(g.units[1], g.units[2], 9) == (55 + 9) * 90 // 100   # 57.6 -> 57
    assert g.damage_calc(g.units[1], g.units[2], -9) == (55 - 9) * 90 // 100   # 41.4 -> 41


def test_kanbei_scop_counter_boost():
    g = new(PLAIN5, [(0, UT.TANK, 1, 1), (1, UT.TANK, 2, 1)], cos=("Andy", "Kanbei"))
    g.players[1].power = 2
    base = g.damage_calc(g.units[2], g.units[1], 0, counter=False)
    boosted = g.damage_calc(g.units[2], g.units[1], 0, counter=True)
    assert boosted > base and abs(boosted - base * 1.5) <= 1.5


def test_sonja_counter_break_strikes_first():
    g = new(PLAIN5, [(0, UT.INF, 1, 1, 30), (1, UT.INF, 2, 1)], cos=("Andy", "Sonja"))
    g.players[1].power = 2
    g.step(A(AT.ATTACK, 1, (1, 1), (2, 1)))
    # defender fired first at full HP and (with 30hp attacker) destroyed it; attacker never fired
    assert 1 not in g.units and g.units[2].hp == 100


def test_nell_luck_range():
    g = new(PLAIN5, [(0, UT.TANK, 1, 1), (1, UT.TANK, 2, 1)], cos=("Nell", "Andy"), luck_fn=None, seed=3)
    rolls = {g.roll_luck(0) for _ in range(500)}
    assert min(rolls) >= 0 and max(rolls) <= 19 and max(rolls) > 9


def test_flak_two_roll_luck():
    g = new(PLAIN5, [(0, UT.TANK, 1, 1), (1, UT.TANK, 2, 1)], cos=("Flak", "Andy"), luck_fn=None, seed=3)
    rolls = [g.roll_luck(0) for _ in range(2000)]
    assert min(rolls) >= -9 and max(rolls) <= 24 and min(rolls) < 0


# ------------------------------------------------------------------ movement
def test_movement_costs_and_blocking():
    g = new(["..^..", ".....", ".....", ".....", "....."], [(0, UT.TANK, 0, 0), (1, UT.INF, 1, 1)])
    r = g.reachable(g.units[1])
    assert (2, 0) not in r                    # mountain impassable for treads
    assert r.get((1, 1)) is None               # enemy unit blocks its own tile


def test_foot_mountain_cost():
    g = new(["..^..", ".....", ".....", ".....", "....."], [(0, UT.INF, 1, 0), (1, UT.INF, 4, 4)])
    assert g.reachable(g.units[1])[(2, 0)] == 2


def test_rain_and_snow_costs():
    g = new(PLAIN5, [(0, UT.TANK, 0, 1), (1, UT.INF, 4, 4)], weather="R")
    assert g.reachable(g.units[1])[(1, 1)] == 2
    g = new(PLAIN5, [(0, UT.TANK, 0, 1), (1, UT.INF, 4, 4)], weather="S")
    assert g.reachable(g.units[1])[(1, 1)] == 2
    # Olaf: snow is clear for him, rain acts like snow
    g = new(PLAIN5, [(0, UT.TANK, 0, 1), (1, UT.INF, 4, 4)], cos=("Olaf", "Andy"), weather="S")
    assert g.reachable(g.units[1])[(1, 1)] == 1
    g = new(PLAIN5, [(0, UT.TANK, 0, 1), (1, UT.INF, 4, 4)], cos=("Olaf", "Andy"), weather="R")
    assert g.reachable(g.units[1])[(1, 1)] == 2
    # Drake: rain is clear
    g = new(PLAIN5, [(0, UT.TANK, 0, 1), (1, UT.INF, 4, 4)], cos=("Drake", "Andy"), weather="R")
    assert g.reachable(g.units[1])[(1, 1)] == 1


def test_move_bonus_and_fuel():
    g = new(PLAIN5, [(0, UT.INF, 0, 1), (1, UT.INF, 4, 4)], cos=("Adder", "Andy"))
    g.players[0].power = 2
    assert g.move_points(g.units[1]) == 5
    g = new(PLAIN5, [(0, UT.INF, 0, 1), (1, UT.INF, 4, 4)])
    f0 = g.units[1].fuel
    g.step(A(AT.WAIT, 1, (3, 1)))
    assert g.units[1].fuel == f0 - 3


def test_sturm_flat_movement_cost():
    g = new(["..^..", ".@@@.", ".....", ".....", "....."], [(0, UT.INF, 0, 1), (1, UT.INF, 4, 4)], cos=("Sturm", "Andy"))
    assert g.reachable(g.units[1])[(3, 1)] == 3        # woods cost 1 for Sturm


def test_cannot_pass_enemy_but_can_pass_friend():
    g = new(["...", "...", "..."], [(0, UT.INF, 0, 0), (0, UT.INF, 1, 0), (1, UT.INF, 0, 1)])
    r = g.reachable(g.units[1])
    assert r[(2, 0)] == 2                      # through the friend
    assert (0, 1) not in r                      # enemy tile


# ------------------------------------------------------------------ capture / win
def test_capture_takes_two_turns_and_resets():
    g = new(["Hhc..", ".....", ".....", ".....", "....."], [(0, UT.INF, 0, 1), (1, UT.INF, 4, 4)])
    g.step(A(AT.CAPTURE, 1, (2, 0)))
    assert g.cp[0][2] == 10 and g.owners[0][2] == -1
    g.step(A(AT.END_TURN)); g.step(A(AT.END_TURN))
    g.step(A(AT.CAPTURE, 1, (2, 0)))
    assert g.owners[0][2] == 0 and g.cp[0][2] == 20


def test_capture_progress_reset_when_unit_leaves():
    g = new(["Hhc..", ".....", ".....", ".....", "....."], [(0, UT.INF, 1, 1), (1, UT.INF, 4, 4)])
    g.step(A(AT.CAPTURE, 1, (2, 0)))
    g.step(A(AT.END_TURN)); g.step(A(AT.END_TURN))
    g.step(A(AT.WAIT, 1, (2, 1)))
    assert g.cp[0][2] == 20


def test_hq_capture_wins():
    g = new(["Hh...", ".....", ".....", ".....", "....."], [(0, UT.INF, 1, 0), (1, UT.INF, 4, 4), (0, UT.TANK, 3, 3)])
    g.cp[0][1] = 5
    g.step(A(AT.CAPTURE, 1, (1, 0)))
    assert g.done and g.winner == 0


def test_damaged_capture_strength_and_sami():
    g = new(["Hhc..", ".....", ".....", ".....", "....."], [(0, UT.INF, 2, 0, 55), (1, UT.INF, 4, 4)])
    g.step(A(AT.CAPTURE, 1, (2, 0)))
    assert g.cp[0][2] == 20 - 6          # display HP 6
    g = new(["Hhc..", ".....", ".....", ".....", "....."], [(0, UT.INF, 2, 0, 100), (1, UT.INF, 4, 4)], cos=("Sami", "Andy"))
    g.step(A(AT.CAPTURE, 1, (2, 0)))
    assert g.cp[0][2] == 20 - 15         # 10 * 1.5
    g = new(["Hhc..", ".....", ".....", ".....", "....."], [(0, UT.INF, 2, 0, 10), (1, UT.INF, 4, 4)], cos=("Sami", "Andy"))
    g.players[0].power = 2
    g.step(A(AT.CAPTURE, 1, (2, 0)))
    assert g.owners[0][2] == 0           # Victory March: instant


def test_destroying_all_units_and_no_buildings_wins():
    g = new(["....h", ".....", ".....", ".....", "....."], [(0, UT.TANK, 3, 0), (1, UT.INF, 4, 1, 10)])
    # player 1 owns a HQ only (no base/airport/port) -> eliminated once last unit dies
    g.step(A(AT.ATTACK, 1, (4, 0), (4, 1)))
    assert g.done and g.winner == 0


def test_rout_even_with_a_base_left():
    # AWBW: losing your last unit loses, bases or not
    g = new(["H...h", "B...b", ".....", ".....", "....."], [(0, UT.TANK, 3, 0), (1, UT.INF, 4, 1, 10)])
    g.step(A(AT.ATTACK, 1, (3, 1), (4, 1)))
    assert g.done and g.winner == 0 and g.end_reason == "rout"


def test_no_units_at_start_is_not_a_rout():
    g = new(["HB.bh", ".....", "....."], [])
    g.step(A(AT.END_TURN))
    assert not g.done


def test_days_limit_most_properties_wins_or_draws():
    g = new(["HC.ch", ".....", "....."], [(0, UT.INF, 1, 1), (1, UT.INF, 3, 1)], max_days=1)
    g.step(A(AT.END_TURN)); g.step(A(AT.END_TURN))
    assert g.done and g.winner == 0 and g.end_reason == "days"     # HQ + city vs HQ
    g = new(["H...h", ".....", "....."], [(0, UT.INF, 1, 1), (1, UT.INF, 3, 1)], max_days=1)
    g.step(A(AT.END_TURN)); g.step(A(AT.END_TURN))
    assert g.done and g.winner is None and g.end_reason == "days"


def test_labs_act_as_hq_on_maps_without_hq():
    from awbw.maps import from_ascii
    kinds, owners = from_ascii([".L..L", ".....", "....."])
    owners[0][1], owners[0][4] = 0, 1                              # each army pre-owns one lab
    g = Game(kinds, owners, units=[(0, UT.INF, 4, 1), (1, UT.INF, 0, 2)], luck_fn=luck(0))
    g.cp[0][4] = 5
    g.step(A(AT.CAPTURE, 1, (4, 0)))
    assert g.done and g.winner == 0 and g.end_reason == "labs"


def test_capture_limit():
    g = new(["Hc..h", ".....", "....."], [(0, UT.INF, 1, 1), (1, UT.INF, 4, 2)], capture_limit=2)
    g.cp[0][1] = 5
    g.step(A(AT.CAPTURE, 1, (1, 0)))
    assert g.done and g.winner == 0 and g.end_reason == "capture_limit"


# ------------------------------------------------------------------ economy
def test_income_build_and_repair():
    g = new(["HBc.h", "Cb...", ".....", ".....", "....."], [(0, UT.TANK, 3, 3, 40), (1, UT.INF, 4, 4)])
    # player 0 owns HQ, base, city => 3 properties; income on day 1
    assert g.players[0].funds == 3000
    g.step(A(AT.BUILD, dest=(1, 0), arg=int(UT.INF)))
    assert g.players[0].funds == 2000 and g.unit_at(1, 0).acted
    with pytest.raises(IllegalAction):
        g.step(A(AT.BUILD, dest=(1, 0), arg=int(UT.TANK)))     # occupied
    g.step(A(AT.END_TURN))
    assert g.players[1].funds == 2000                          # base + HQ for p1 (b,h)
    g.step(A(AT.END_TURN))
    assert not g.unit_at(1, 0).acted                           # unit refreshed


def test_repair_on_property_costs_funds():
    g = new(["HBc.h", "Cb...", ".....", ".....", "....."], [(0, UT.TANK, 0, 1, 50), (1, UT.INF, 4, 4)])
    # turn 1 start already repaired 50 -> 70 (+2 display HP), costing 7000*2/10 = 1400
    assert g.units[1].hp == 70 and g.players[0].funds == 3000 - 1400
    f_before = g.players[0].funds
    g.step(A(AT.END_TURN)); g.step(A(AT.END_TURN))
    assert g.units[1].hp == 90
    assert g.players[0].funds == f_before + 3000 - 1400


def test_cost_modifiers():
    g = new(PLAIN5, [(0, UT.INF, 3, 3), (1, UT.INF, 4, 4)], cos=("Kanbei", "Colin"))
    assert g.unit_cost(0, UT.TANK) == 8400
    assert g.unit_cost(1, UT.TANK) == 5600
    g.players[0].co = "Hachi"
    assert g.unit_cost(0, UT.TANK) == 6300
    g.players[0].power = 1
    assert g.unit_cost(0, UT.TANK) == 3500


def test_sasha_income_bonus():
    g = new(["HBc.h", "Cb...", ".....", ".....", "....."], [(0, UT.INF, 3, 3), (1, UT.INF, 4, 4)], cos=("Sasha", "Andy"))
    assert g.players[0].funds == 3000 + 300


def test_hachi_builds_from_city_with_scop():
    g = new(["HBc.h", "Cb...", ".....", ".....", "....."], [(0, UT.INF, 3, 3), (1, UT.INF, 4, 4)], cos=("Hachi", "Andy"),
            starting_funds=50000)
    assert not any(a.type == AT.BUILD and a.dest == (0, 1) for a in g.legal_actions())
    g.players[0].power = 2
    assert any(a.type == AT.BUILD and a.dest == (0, 1) and a.arg == int(UT.TANK) for a in g.legal_actions())
    assert not any(a.type == AT.BUILD and a.dest == (0, 1) and a.arg == int(UT.FIGHTER) for a in g.legal_actions())


# ------------------------------------------------------------------ transports / join
def test_load_and_unload():
    g = new(PLAIN5, [(0, UT.APC, 1, 1), (0, UT.INF, 0, 1), (1, UT.INF, 4, 4)])
    apc, inf = g.units[1], g.units[2]
    g.step(A(AT.LOAD, inf.id, (1, 1)))
    assert inf.loaded_in == apc.id and (0, 1) not in g.pos and apc.cargo == [inf.id]
    g.step(A(AT.END_TURN)); g.step(A(AT.END_TURN))
    g.step(A(AT.UNLOAD, apc.id, (2, 1), (2, 2), inf.id))
    assert g.unit_at(2, 2).id == inf.id and inf.acted and apc.acted and not apc.cargo


def test_cargo_dies_with_transport():
    g = new(PLAIN5, [(0, UT.TANK, 1, 1), (1, UT.APC, 2, 1, 10), (1, UT.INF, 3, 3)])
    apc = g.units[2]
    inf = g.units[3]
    inf.x, inf.y = 2, 1
    g.pos.pop((3, 3)); inf.loaded_in = apc.id; apc.cargo.append(inf.id)
    g.step(A(AT.ATTACK, 1, (1, 1), (2, 1)))
    assert apc.id not in g.units and inf.id not in g.units


def test_no_boarding_a_lander_over_sea():
    # AWBW: cargo boards only where it could stand itself (shoal / port / beach), never onto a transport at sea
    g = new(["..~~.", "..~~.", ".....", ".....", "....."], [(0, UT.LANDER, 2, 0), (0, UT.TANK, 1, 0), (1, UT.INF, 4, 4)])
    tank = g.units[2]
    assert not any(a.type == AT.LOAD and a.dest == (2, 0) for a in g.unit_actions(tank))


def test_join_merges_hp_and_refunds():
    g = new(PLAIN5, [(0, UT.TANK, 1, 1, 70), (0, UT.TANK, 2, 1, 60), (1, UT.INF, 4, 4)])
    f = g.players[0].funds
    g.step(A(AT.JOIN, 1, (2, 1)))
    assert 1 not in g.units and g.units[2].hp == 100
    assert g.players[0].funds == f + 7000 * 30 // 100


def test_join_ends_the_merged_units_turn():
    # the unit joined into had not acted yet; after the join it must not act again (it used to be able to capture)
    g = new(PLAIN5, [(0, UT.INF, 1, 1, 50), (0, UT.INF, 2, 1, 40), (1, UT.INF, 4, 4)])
    g.step(A(AT.JOIN, 1, (2, 1)))
    assert g.units[2].acted
    assert not [a for a in g.legal_actions() if a.unit == 2]



def test_cargo_that_boarded_this_turn_cannot_be_dropped():
    # live game 1764106 (2026-11-15): AWBW refused an unload of infantry that had boarded the Black Boat the same turn
    g = new(PLAIN5, [(0, UT.INF, 1, 1), (0, UT.APC, 2, 1), (1, UT.INF, 4, 4)])
    g.step(A(AT.LOAD, 1, (2, 1)))
    assert not [a for a in g.legal_actions() if a.type == AT.UNLOAD]
    g.step(A(AT.END_TURN))
    g.step(A(AT.END_TURN))
    assert [a for a in g.legal_actions() if a.type == AT.UNLOAD]        # next turn it can be dropped again


def test_out_of_ammo_units_fire_their_machine_gun():
    # AWBW replays (e.g. 1591834): a B-Copter with 0 missiles still attacks vehicles, with the machine gun (AW2 values)
    g = new(PLAIN5, [(0, UT.BCOPTER, 1, 1), (1, UT.TANK, 2, 1), (1, UT.INF, 4, 4)])
    g.units[1].ammo = 0
    assert g.can_hit(g.units[1], g.units[2])
    g.luck_fn = lambda p: 0
    g.step(A(AT.ATTACK, 1, (1, 1), (2, 1)))
    assert g.units[2].hp == 95 and g.units[1].ammo == 0          # base 6 x 0.9 (plain: 1 star), no luck
    # a Mech without bazooka shells still hits a Tank; an Artillery (no machine gun) without shells cannot
    g = new(PLAIN5, [(0, UT.MECH, 1, 1), (0, UT.ARTY, 3, 3), (1, UT.TANK, 2, 1), (1, UT.INF, 4, 4)])
    g.units[1].ammo = g.units[2].ammo = 0
    assert g.can_hit(g.units[1], g.units[3])
    assert not g.can_hit(g.units[2], g.units[3])

def test_supply_and_black_boat_repair():
    g = new(PLAIN5, [(0, UT.APC, 1, 1), (0, UT.TANK, 2, 1), (1, UT.INF, 4, 4)])
    g.units[2].fuel, g.units[2].ammo = 5, 1
    g.step(A(AT.SUPPLY, 1, (1, 1)))
    assert g.units[2].fuel == 70 and g.units[2].ammo == 9


# ------------------------------------------------------------------ fuel / weather / hidden
def test_air_fuel_burn_and_crash():
    g = new(PLAIN5, [(0, UT.FIGHTER, 2, 2), (1, UT.INF, 4, 4)])
    g.units[1].fuel = 5
    g.step(A(AT.END_TURN)); g.step(A(AT.END_TURN))
    assert 1 not in g.units                                   # ran dry at turn start


def test_eagle_burns_less_fuel():
    g = new(PLAIN5, [(0, UT.FIGHTER, 2, 2), (1, UT.INF, 4, 4)], cos=("Eagle", "Andy"))
    assert g.units[1].fuel == 99                              # AWBW: no daily burn on day 1
    g.step(A(AT.END_TURN)); g.step(A(AT.END_TURN))            # day 2 start burns 5 - 2
    assert g.units[1].fuel == 99 - 3


def test_dive_hides_sub():
    g = new(["~~~..", "~~~..", ".....", ".....", "....."], [(0, UT.SUB, 0, 0), (1, UT.CRUISER, 2, 0)], cos=("Andy", "Andy"))
    g.step(A(AT.DIVE, 1, (0, 0)))
    assert g.units[1].hidden
    g.step(A(AT.END_TURN))
    # cruiser two tiles away has no neighbour of the sub -> cannot be targeted until adjacent
    assert not g.attack_targets(g.units[2], 1, 0, False)
    assert g.attack_targets(g.units[2], 1, 0, False) == []


# ------------------------------------------------------------------ silo / bomb
def test_missile_silo():
    g = new(["HhS..", ".....", ".....", ".....", "....."],
            [(0, UT.INF, 1, 0), (1, UT.TANK, 4, 4), (1, UT.INF, 3, 4)])
    g.step(A(AT.LAUNCH, 1, (2, 0), (4, 4)))
    assert g.kinds[0][2] == TK.SILO_EMPTY
    assert g.units[2].hp == 70 and g.units[3].hp == 70


def test_black_bomb():
    g = new(PLAIN5, [(0, UT.BLACKBOMB, 2, 2), (1, UT.TANK, 3, 2), (1, UT.INF, 4, 4)])
    g.step(A(AT.EXPLODE, 1, (2, 2)))
    assert 1 not in g.units and g.units[2].hp == 50     # adjacent tank hit for 5 HP
    assert g.units[3].hp == 100                         # infantry at distance 4: outside radius 3


# ------------------------------------------------------------------ powers
def charge_to(g, p, lvl):
    g.players[p].charge = g.power_cost(p, lvl)


def test_power_charge_from_combat():
    g = new(PLAIN5, [(0, UT.TANK, 1, 1), (1, UT.TANK, 2, 1)])
    g.step(A(AT.ATTACK, 1, (1, 1), (2, 1)))
    # meters use DISPLAYED HP lost (AWBW replays): defender 10 -> 6 shown = 4 HP of a 7000 tank -> 2800 to its owner,
    # plus half of what the counter took from the attacker (10 -> ceil(hp/10) shown)
    lost_att = 10 - (g.units[1].hp + 9) // 10
    assert g.players[1].charge == 7000 * 4 // 10 + (7000 * lost_att // 10) // 2
    assert g.players[0].charge == (7000 * 4 // 10) // 2 + 7000 * lost_att // 10


def test_power_activation_requires_charge_and_resets_next_turn():
    g = new(PLAIN5, [(0, UT.TANK, 1, 1, 50), (1, UT.INF, 4, 4)])
    assert not any(a.type == AT.POWER for a in g.legal_actions())
    charge_to(g, 0, 1)
    assert any(a.type == AT.POWER and a.arg == 1 for a in g.legal_actions())
    g.step(A(AT.POWER, arg=1))
    assert g.units[1].hp == 70 and g.players[0].power == 1 and g.players[0].charge == 0
    assert g.players[0].uses == 1
    assert g.power_cost(0, 1) == 3 * (9000 + 1800)
    g.step(A(AT.END_TURN)); g.step(A(AT.END_TURN))
    assert g.players[0].power == 0


def test_no_charge_while_power_active():
    g = new(PLAIN5, [(0, UT.TANK, 1, 1), (1, UT.TANK, 2, 1)])
    charge_to(g, 0, 1); g.step(A(AT.POWER, arg=1))
    c = g.players[0].charge
    g.step(A(AT.ATTACK, 1, (1, 1), (2, 1)))
    assert g.players[0].charge == c


def test_hawke_black_wave_never_kills():
    g = new(PLAIN5, [(0, UT.TANK, 1, 1), (1, UT.INF, 4, 4, 5), (1, UT.TANK, 4, 3)], cos=("Hawke", "Andy"))
    charge_to(g, 0, 2); g.step(A(AT.POWER, arg=2))
    assert g.units[2].hp == 1 and g.units[3].hp == 80 and g.units[1].hp == 100


def test_drake_tsunami_halves_fuel():
    g = new(PLAIN5, [(0, UT.TANK, 1, 1), (1, UT.TANK, 4, 4)], cos=("Drake", "Andy"))
    charge_to(g, 0, 1); g.step(A(AT.POWER, arg=1))
    assert g.units[2].hp == 90 and g.units[2].fuel == 35


def test_olaf_blizzard_weather_reverts():
    g = new(PLAIN5, [(0, UT.TANK, 1, 1), (1, UT.TANK, 4, 4)], cos=("Olaf", "Andy"))
    charge_to(g, 0, 1); g.step(A(AT.POWER, arg=1))
    assert g.weather == "S"
    g.step(A(AT.END_TURN))
    assert g.weather == "S"
    g.step(A(AT.END_TURN))
    assert g.weather == "C"


def test_colin_gold_rush_and_power_of_money():
    g = new(PLAIN5, [(0, UT.TANK, 1, 1), (1, UT.TANK, 4, 4)], cos=("Colin", "Andy"), starting_funds=10000)
    f = g.players[0].funds
    charge_to(g, 0, 1); g.step(A(AT.POWER, arg=1))
    assert g.players[0].funds == f * 3 // 2
    g.players[0].power = 2
    # 90% + 10% power + 3*funds/1000 %
    assert g.atk_pct(g.units[1], g.units[2]) == 90 + 10 + 3 * g.players[0].funds // 1000


def test_sensei_spawns_units_on_empty_owned_cities():
    g = new(["HCCCh", ".....", ".....", ".....", "....."], [(0, UT.TANK, 2, 0), (1, UT.INF, 4, 4)], cos=("Sensei", "Andy"))
    charge_to(g, 0, 1); g.step(A(AT.POWER, arg=1))
    spawned = [u for u in g.units.values() if u.owner == 0 and u.type == UT.INF]
    assert {(u.x, u.y) for u in spawned} == {(1, 0), (3, 0)} and all(u.hp == 90 and not u.acted for u in spawned)


def test_von_bolt_stun_blocks_next_turn():
    g = new(PLAIN5, [(0, UT.INF, 0, 2), (1, UT.TANK, 3, 3), (1, UT.TANK, 4, 3)], cos=("Von Bolt", "Andy"))
    assert not any(a.type == AT.POWER and a.arg == 1 for a in g.legal_actions())
    charge_to(g, 0, 2); g.step(A(AT.POWER, arg=2))
    assert g.units[2].hp == 70 and g.units[3].hp == 70 and g.units[2].stunned
    g.step(A(AT.END_TURN))
    assert g.units[2].acted and g.units[3].acted and not g.unit_actions(g.units[2])
    g.step(A(AT.END_TURN)); g.step(A(AT.END_TURN))
    assert not g.units[2].acted


def test_von_bolt_stuns_own_units_for_the_rest_of_the_turn():
    # AWBW (user, live game 1765038; 470 expert Von Bolt games, tools/vb_stun*.py): Ex Machina also stuns the caster's own
    # units in the blast (units_moved -1) - they cannot act this turn but are free again on the caster's next turn
    g = new(PLAIN5, [(0, UT.TANK, 2, 3), (1, UT.TANK, 3, 3), (1, UT.TANK, 4, 3), (0, UT.INF, 0, 0)], cos=("Von Bolt", "Andy"))
    charge_to(g, 0, 2); g.step(A(AT.POWER, arg=2))
    own = g.units[1]
    assert own.hp < 100 and own.acted and not own.stunned and not g.unit_actions(own)
    assert g.units[2].stunned
    g.step(A(AT.END_TURN)); g.step(A(AT.END_TURN))
    assert g.cur == 0 and not g.units[1].acted and g.unit_actions(g.units[1])


def test_sturm_missile_picks_densest_value():
    g = new(["..........", ".........."], [(0, UT.INF, 0, 0), (1, UT.INF, 9, 1), (1, UT.TANK, 4, 0), (1, UT.TANK, 5, 1), (1, UT.TANK, 6, 0)],
            cos=("Sturm", "Andy"))
    charge_to(g, 0, 1); g.step(A(AT.POWER, arg=1))
    hp = {u.type: u.hp for u in g.units.values() if u.owner == 1}
    tanks = [u.hp for u in g.units.values() if u.type == UT.TANK]
    assert tanks == [60, 60, 60] and g.units[2].hp == 100


def test_rachel_missiles_three_strikes():
    g = new(PLAIN5, [(0, UT.INF, 0, 2), (1, UT.INF, 3, 3), (1, UT.INF, 4, 4)], cos=("Rachel", "Andy"))
    charge_to(g, 0, 2); g.step(A(AT.POWER, arg=2))
    assert g.units[2].hp == 10 and g.units[3].hp == 10      # three hits of 30 each, within blast


def test_eagle_lightning_strike_refreshes_nonfoot():
    g = new(PLAIN5, [(0, UT.TANK, 1, 1), (0, UT.INF, 0, 1), (1, UT.INF, 4, 4)], cos=("Eagle", "Andy"))
    g.step(A(AT.WAIT, 1, (2, 1))); g.step(A(AT.WAIT, 2, (0, 2)))
    charge_to(g, 0, 2); g.step(A(AT.POWER, arg=2))
    assert not g.units[1].acted and g.units[2].acted


def test_sasha_market_crash_and_war_bonds():
    g = new(PLAIN5, [(0, UT.TANK, 1, 1), (1, UT.TANK, 2, 1)], cos=("Sasha", "Andy"), starting_funds=0)
    g.players[0].funds = 25000
    g.players[1].charge = 3 * 9000 * 2
    charge_to(g, 0, 1); g.step(A(AT.POWER, arg=1))
    # reduces enemy bar by (10*25000/5000)% = 50% of its max (Andy SCOP 6 stars)
    assert g.players[1].charge == max(0, 3 * 9000 * 2 - g.max_charge(1) * 50 // 100)


def test_jess_and_koal_and_jake_dynamic_bonuses():
    g = new(["..=..", ".....", ".....", ".....", "....."], [(0, UT.TANK, 2, 0), (1, UT.TANK, 4, 4)], cos=("Koal", "Andy"))
    assert g.atk_pct(g.units[1], g.units[2]) == 110          # road +10
    g = new(PLAIN5, [(0, UT.TANK, 2, 2), (1, UT.TANK, 4, 4)], cos=("Jake", "Andy"))
    assert g.atk_pct(g.units[1], g.units[2]) == 110          # plains +10
    g = new(["..H..", ".....", ".....", ".....", "....."], [(0, UT.TANK, 2, 0), (1, UT.TANK, 4, 4)], cos=("Kindle", "Andy"))
    assert g.atk_pct(g.units[1], g.units[2]) == 140          # urban +40
    g = new(["^....", ".....", ".....", ".....", "....."], [(0, UT.TANK, 0, 0), (1, UT.TANK, 4, 4)], cos=("Lash", "Andy"))
    assert g.atk_pct(g.units[1], g.units[2]) == 140          # 4 stars * 10%


def test_javier_defense_with_towers_and_indirect():
    g = new(["tt...", ".....", ".....", ".....", "....."], [(0, UT.ARTY, 3, 3), (1, UT.TANK, 4, 4)], cos=("Andy", "Javier"))
    g.owners[0][0] = 1; g.owners[0][1] = 1
    assert g.def_pct(g.units[2], g.units[1]) == 100 + 20 + 2 * 10     # indirect +20, two towers +10 each
    inf = g.units[1]
    inf.type = UT.TANK
    assert g.def_pct(g.units[2], inf) == 100 + 2 * 10                   # direct attacker: towers only


def test_grit_and_max_range():
    g = new(PLAIN5, [(0, UT.ARTY, 1, 1), (1, UT.TANK, 4, 4)], cos=("Grit", "Andy"))
    assert g.attack_range(g.units[1]) == (2, 4)
    g.players[0].power = 1                     # AWBW GL replay 1737327: artillery fires at range 5 under Snipe Attack
    assert g.attack_range(g.units[1]) == (2, 5)
    g.players[0].power = 2
    assert g.attack_range(g.units[1]) == (2, 6)
    g = new(PLAIN5, [(0, UT.ARTY, 1, 1), (1, UT.TANK, 4, 4)], cos=("Max", "Andy"))
    assert g.attack_range(g.units[1]) == (2, 2)
    g = new(PLAIN5, [(0, UT.ARTY, 1, 1), (1, UT.TANK, 4, 4)], cos=("Jake", "Andy"))
    g.players[0].power = 1
    assert g.attack_range(g.units[1]) == (2, 4)


# ------------------------------------------------------------------ misc
def test_copy_is_independent_and_deterministic():
    g = new(PLAIN5, [(0, UT.TANK, 1, 1), (1, UT.TANK, 2, 1)], luck_fn=None, seed=5)
    h = g.copy()
    g.step(A(AT.ATTACK, 1, (1, 1), (2, 1)))
    assert h.units[2].hp == 100
    h.step(A(AT.ATTACK, 1, (1, 1), (2, 1)))
    assert h.units[2].hp == g.units[2].hp            # same rng state -> same luck


def test_illegal_actions_rejected():
    g = new(PLAIN5, [(0, UT.TANK, 1, 1), (1, UT.TANK, 4, 4)])
    with pytest.raises(IllegalAction):
        g.step(A(AT.WAIT, 1, (4, 4)))                # tile occupied by an enemy
    with pytest.raises(IllegalAction):
        g.step(A(AT.WAIT, 2, (4, 4)))                # not your unit
    with pytest.raises(IllegalAction):
        g.step(A(AT.POWER, arg=1))                    # no charge


def test_acted_unit_cannot_act_again():
    g = new(PLAIN5, [(0, UT.TANK, 1, 1), (1, UT.TANK, 4, 4)])
    g.step(A(AT.WAIT, 1, (1, 2)))
    with pytest.raises(IllegalAction):
        g.step(A(AT.WAIT, 1, (1, 3)))


def test_disp():
    assert [disp(h) for h in (1, 10, 11, 55, 100)] == [1, 1, 2, 6, 10]
