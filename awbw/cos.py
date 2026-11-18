"""Commanding officers: day-to-day (D2D) abilities and the COP / SCOP.

Source: awbw.amarriner.com co.php (text) and percent.php (static attack/defense table).
`lvl` is 0 = no power active, 1 = CO Power (COP), 2 = Super CO Power (SCOP).
The universal +10% attack/defense on COP/SCOP is added by the Game, not here.

Power-star costs are NOT on any fetched AWBW page; the values below come from
Advance Wars 2 / Dual Strike references and are PROVISIONAL (see UNVERIFIED_COSTS).
"""
from __future__ import annotations

from .data import (UNITS, UT, TK, FOOT, AIR_UNITS, NAVAL_UNITS, LAND_INDIRECT, VEHICLES,
                   TRANSPORTS, URBAN, MT)


def _direct(t):      # attacks at range 1
    return UNITS[t].rmax == 1


def _indirect(t):
    return UNITS[t].rmax > 1


class CO:
    name = "?"
    cop_name = ""
    scop_name = ""
    cop_stars = 0           # in stars (x 9000 funds-points each, +20% per use)
    scop_stars = 0
    has_cop = True
    luck_levels = ((9, 0), (9, 0), (9, 0))      # (max positive roll, max negative roll) by lvl
    cost_levels = (100, 100, 100)               # unit cost percent by lvl
    counter_num, counter_den = 3, 2
    counter_mult_levels = (1, 1, 1)              # 1 = normal; 1.5 handled via counter_boost
    repair_bonus = 0                             # extra internal HP repaired on properties
    flat_move_cost_levels = (False, False, False)
    plain_vision_only = False

    # --- combat ---------------------------------------------------------
    def atk(self, g, p, a, d, lvl):
        return 100

    def dfn(self, g, p, d, a, lvl):
        return 100

    def luck(self, lvl):
        return self.luck_levels[lvl]

    def counter_boost(self, lvl):
        """True if this CO's counterattacks get the x1.5 counter bonus (on its own attack value only)."""
        return False

    def atk_milli(self, g, p, lvl):
        """Extra attack in thousandths of a percent point, unrounded (Colin's Power of Money)."""
        return 0

    def star_mult(self, lvl):
        return 1

    # --- movement / economy --------------------------------------------
    def move_bonus(self, g, p, u, lvl):
        return 0

    def range_bonus(self, g, p, u, lvl):
        """Delta applied to a unit's MAX attack range (indirect units only)."""
        return 0

    def cost_pct(self, lvl):
        return self.cost_levels[lvl]

    def income_bonus(self, g, p):
        return 0

    def effective_weather(self, w):
        return w

    def capture_bonus_pct(self, lvl):
        return 100

    def instant_capture(self, lvl):
        return False

    def fuel_per_turn_delta(self, t):
        return 0

    def sees_hidden(self, lvl):
        return False

    # --- powers ---------------------------------------------------------
    def on_power(self, g, p, lvl):
        pass


COS: dict[str, CO] = {}


def _reg(cls):
    inst = cls()
    COS[inst.name] = inst
    return cls


def _pick(lvl, vals):
    return vals[lvl]


@_reg
class Andy(CO):
    name = "Andy"; cop_name = "Hyper Repair"; scop_name = "Hyper Upgrade"
    cop_stars, scop_stars = 3, 6

    def atk(self, g, p, a, d, lvl):
        return 110 if lvl == 2 else 100

    def move_bonus(self, g, p, u, lvl):
        return 1 if lvl == 2 else 0

    def on_power(self, g, p, lvl):
        g.heal_all(p, 20 if lvl == 1 else 50)


@_reg
class Hachi(CO):
    name = "Hachi"; cop_name = "Barter"; scop_name = "Merchant Union"
    cop_stars, scop_stars = 3, 5
    cost_levels = (90, 50, 50)


@_reg
class Jake(CO):
    name = "Jake"; cop_name = "Beat Down"; scop_name = "Block Rock"
    cop_stars, scop_stars = 3, 6

    def atk(self, g, p, a, d, lvl):
        # pipe rubble counts as plains (replays: 0 impossible fights in 681 vs 4 without)
        return 100 + (_pick(lvl, (10, 20, 40)) if g.kind_at(a.x, a.y) in (TK.PLAIN, TK.RUBBLE) else 0)

    def range_bonus(self, g, p, u, lvl):
        return 1 if lvl >= 1 and u.type in LAND_INDIRECT else 0

    def move_bonus(self, g, p, u, lvl):
        return 2 if lvl == 2 and u.type in VEHICLES else 0


@_reg
class Max(CO):
    name = "Max"; cop_name = "Max Force"; scop_name = "Max Blast"
    cop_stars, scop_stars = 3, 6

    def atk(self, g, p, a, d, lvl):
        t = a.type
        if t in FOOT:
            return 100
        if _direct(t):
            return _pick(lvl, (120, 130, 150))
        if _indirect(t):
            return 90
        return 100

    def move_bonus(self, g, p, u, lvl):
        # libaw B21: every unit that is not an indirect, a foot soldier or a transport (the Black Bomb too)
        return lvl if not (_indirect(u.type) or u.type in FOOT or u.type in TRANSPORTS) else 0

    def range_bonus(self, g, p, u, lvl):
        return -1 if _indirect(u.type) else 0


@_reg
class Nell(CO):
    name = "Nell"; cop_name = "Lucky Star"; scop_name = "Lady Luck"
    cop_stars, scop_stars = 3, 6
    luck_levels = ((19, 0), (59, 0), (99, 0))


@_reg
class Rachel(CO):
    name = "Rachel"; cop_name = "Lucky Lass"; scop_name = "Covering Fire"
    cop_stars, scop_stars = 3, 6
    luck_levels = ((9, 0), (39, 0), (9, 0))
    repair_bonus = 10

    def on_power(self, g, p, lvl):
        if lvl == 2:
            g.rachel_missiles(p)


@_reg
class Sami(CO):
    name = "Sami"; cop_name = "Double Time"; scop_name = "Victory March"
    cop_stars, scop_stars = 3, 8

    def atk(self, g, p, a, d, lvl):
        t = a.type
        if t in FOOT:
            return _pick(lvl, (130, 150, 170))
        if _direct(t):
            return 90
        return 100

    def move_bonus(self, g, p, u, lvl):
        b = 0
        if u.type in FOOT:
            b += lvl
        if u.type in TRANSPORTS:
            b += 1
        return b

    def capture_bonus_pct(self, lvl):
        return 150

    def instant_capture(self, lvl):
        return lvl == 2


@_reg
class Colin(CO):
    name = "Colin"; cop_name = "Gold Rush"; scop_name = "Power of Money"
    cop_stars, scop_stars = 2, 6
    cost_levels = (80, 80, 80)

    def atk(self, g, p, a, d, lvl):
        return 90

    def atk_milli(self, g, p, lvl):
        # libaw #6: +3% per 1000 funds held at each attack, unrounded
        return 3 * max(0, g.players[p].funds) if lvl == 2 else 0

    def on_power(self, g, p, lvl):
        if lvl == 1:
            g.players[p].funds = (g.players[p].funds * 3) // 2


@_reg
class Grit(CO):
    name = "Grit"; cop_name = "Snipe Attack"; scop_name = "Super Snipe"
    cop_stars, scop_stars = 3, 6

    def atk(self, g, p, a, d, lvl):
        t = a.type
        if _indirect(t):
            return _pick(lvl, (120, 140, 140))
        if t in FOOT:
            return 100
        if _direct(t):
            return 80
        return 100

    def range_bonus(self, g, p, u, lvl):
        if not _indirect(u.type):
            return 0
        return 1 + lvl          # AWBW (GL replays): +1 day to day, +2 with COP, +3 with SCOP (the power ranges stack)


@_reg
class Olaf(CO):
    name = "Olaf"; cop_name = "Blizzard"; scop_name = "Winter Fury"
    cop_stars, scop_stars = 3, 7

    def effective_weather(self, w):
        return {"S": "C", "R": "S", "C": "C"}[w]

    def on_power(self, g, p, lvl):
        g.set_weather("S", p)
        if lvl == 2:
            g.damage_enemies(p, 20)


@_reg
class Sasha(CO):
    name = "Sasha"; cop_name = "Market Crash"; scop_name = "War Bonds"
    cop_stars, scop_stars = 2, 6   # UNVERIFIED for AWBW

    def income_bonus(self, g, p):
        return 100 * g.count_income_props(p)

    def on_power(self, g, p, lvl):
        if lvl == 1:
            g.market_crash(p)


@_reg
class Drake(CO):
    name = "Drake"; cop_name = "Tsunami"; scop_name = "Typhoon"
    cop_stars, scop_stars = 4, 7

    def atk(self, g, p, a, d, lvl):
        return 70 if a.type in AIR_UNITS else 100

    def dfn(self, g, p, d, a, lvl):
        return 110 if d.type in NAVAL_UNITS else 100

    def move_bonus(self, g, p, u, lvl):
        return 1 if u.type in NAVAL_UNITS else 0

    def effective_weather(self, w):
        return "C" if w == "R" else w

    def on_power(self, g, p, lvl):
        g.damage_enemies(p, 10 * lvl, halve_fuel=True)
        if lvl == 2:
            g.set_weather("R", p)


@_reg
class Eagle(CO):
    name = "Eagle"; cop_name = "Lightning Drive"; scop_name = "Lightning Strike"
    cop_stars, scop_stars = 3, 9

    def atk(self, g, p, a, d, lvl):
        if a.type in AIR_UNITS:
            return _pick(lvl, (115, 120, 120))
        if a.type in NAVAL_UNITS:
            return 70
        return 100

    def dfn(self, g, p, d, a, lvl):
        if d.type in AIR_UNITS:
            return _pick(lvl, (110, 120, 120))
        return 100

    def fuel_per_turn_delta(self, t):
        return -2 if t in AIR_UNITS else 0

    def on_power(self, g, p, lvl):
        if lvl == 2:
            g.refresh_units(p, lambda u: u.type not in FOOT)


@_reg
class Javier(CO):
    name = "Javier"; cop_name = "Tower Shield"; scop_name = "Tower of Power"
    cop_stars, scop_stars = 3, 6

    def atk(self, g, p, a, d, lvl):
        # powers raise the com-tower attack bonus too: +20 / +30 per tower in total with the generic +10
        # (replays: 0 impossible fights in 330 vs 3 without)
        return 100 + g.count_owned(p, (TK.COMTOWER,)) * _pick(lvl, (0, 10, 20))

    def dfn(self, g, p, d, a, lvl):
        v = 100
        if _indirect(a.type):
            v += _pick(lvl, (20, 40, 80))
        v += g.count_owned(p, (TK.COMTOWER,)) * _pick(lvl, (10, 20, 30))
        return v


@_reg
class Jess(CO):
    name = "Jess"; cop_name = "Turbo Charge"; scop_name = "Overdrive"
    cop_stars, scop_stars = 3, 6

    def atk(self, g, p, a, d, lvl):
        return _pick(lvl, (110, 120, 140)) if a.type in VEHICLES else 90

    def move_bonus(self, g, p, u, lvl):
        return lvl if u.type in VEHICLES else 0

    def on_power(self, g, p, lvl):
        g.resupply_all(p)


@_reg
class Grimm(CO):
    name = "Grimm"; cop_name = "Knuckleduster"; scop_name = "Haymaker"
    cop_stars, scop_stars = 3, 6

    def atk(self, g, p, a, d, lvl):
        return _pick(lvl, (130, 150, 180))

    def dfn(self, g, p, d, a, lvl):
        return 80


@_reg
class Kanbei(CO):
    name = "Kanbei"; cop_name = "Morale Boost"; scop_name = "Samurai Spirit"
    cop_stars, scop_stars = 4, 7
    cost_levels = (120, 120, 120)

    def atk(self, g, p, a, d, lvl):
        return _pick(lvl, (130, 140, 140))

    def dfn(self, g, p, d, a, lvl):
        return _pick(lvl, (130, 130, 150))

    def counter_boost(self, lvl):
        return lvl == 2


@_reg
class Sensei(CO):
    name = "Sensei"; cop_name = "Copter Command"; scop_name = "Airborne Assault"
    cop_stars, scop_stars = 2, 6

    def atk(self, g, p, a, d, lvl):
        t = a.type
        if t == UT.BCOPTER:
            return _pick(lvl, (150, 165, 165))
        if t in FOOT:
            return 140
        if t in AIR_UNITS:
            return 100
        return 90

    def move_bonus(self, g, p, u, lvl):
        return 1 if u.type in TRANSPORTS else 0

    def on_power(self, g, p, lvl):
        g.sensei_spawn(p, UT.INF if lvl == 1 else UT.MECH)


@_reg
class Sonja(CO):
    name = "Sonja"; cop_name = "Enhanced Vision"; scop_name = "Counter Break"
    cop_stars, scop_stars = 3, 5
    luck_levels = ((9, 9), (9, 9), (9, 9))

    def counter_boost(self, lvl):
        # x1.5 on her counters at every level; under Counter Break her first strike is not a counter (game.do_attack)
        return True

    def sees_hidden(self, lvl):
        return lvl >= 1


@_reg
class Adder(CO):
    name = "Adder"; cop_name = "Sideslip"; scop_name = "Sidewinder"
    cop_stars, scop_stars = 2, 5

    def move_bonus(self, g, p, u, lvl):
        return lvl


@_reg
class Flak(CO):
    name = "Flak"; cop_name = "Brute Force"; scop_name = "Barbaric Blow"
    cop_stars, scop_stars = 3, 6
    luck_levels = ((24, 9), (49, 19), (89, 39))


@_reg
class Hawke(CO):
    name = "Hawke"; cop_name = "Black Wave"; scop_name = "Black Storm"
    cop_stars, scop_stars = 5, 9

    def atk(self, g, p, a, d, lvl):
        return 110

    def on_power(self, g, p, lvl):
        g.heal_all(p, 10 * lvl, carried=False)   # AWBW (libaw B6, hot-seat game 1762036): Hawke skips carried units
        g.damage_enemies(p, 10 * lvl)


@_reg
class Jugger(CO):
    name = "Jugger"; cop_name = "Overclock"; scop_name = "System Crash"
    cop_stars, scop_stars = 3, 7
    luck_levels = ((29, 14), (54, 24), (94, 44))


@_reg
class Kindle(CO):
    name = "Kindle"; cop_name = "Urban Blight"; scop_name = "High Society"
    cop_stars, scop_stars = 3, 6   # UNVERIFIED for AWBW

    def atk(self, g, p, a, d, lvl):
        v = 100
        if g.kind_at(a.x, a.y) in URBAN:
            v += _pick(lvl, (40, 80, 130))
        if lvl == 2:
            v += 3 * g.count_owned(p, tuple(URBAN))
        return v

    def on_power(self, g, p, lvl):
        if lvl == 1:
            g.damage_enemies(p, 30, only_urban=True)


@_reg
class Koal(CO):
    name = "Koal"; cop_name = "Forced March"; scop_name = "Trail of Woe"
    cop_stars, scop_stars = 3, 5

    def atk(self, g, p, a, d, lvl):
        # roads only, NOT bridges (replays: 0 impossible fights in 418 vs 3 with bridges)
        on_road = g.kind_at(a.x, a.y) == TK.ROAD
        return 100 + (_pick(lvl, (10, 20, 30)) if on_road else 0)

    def move_bonus(self, g, p, u, lvl):
        return lvl


@_reg
class Lash(CO):
    name = "Lash"; cop_name = "Terrain Tactics"; scop_name = "Prime Tactics"
    cop_stars, scop_stars = 4, 7
    flat_move_cost_levels = (False, True, True)

    def atk(self, g, p, a, d, lvl):
        if a.type in AIR_UNITS:
            return 100
        return 100 + 10 * g.stars_of(a) * (2 if lvl == 2 else 1)

    def star_mult(self, lvl):
        return 2 if lvl == 2 else 1


@_reg
class Sturm(CO):
    name = "Sturm"; cop_name = "Meteor Strike"; scop_name = "Meteor Strike II"
    cop_stars, scop_stars = 6, 10    # AWBW snapshot prices: 540000 / 900000
    flat_move_cost_levels = (True, True, True)

    def atk(self, g, p, a, d, lvl):
        return 80

    def dfn(self, g, p, d, a, lvl):
        return 120

    def on_power(self, g, p, lvl):
        g.sturm_missile(p, 40 if lvl == 1 else 80)


@_reg
class VonBolt(CO):
    name = "Von Bolt"; cop_name = ""; scop_name = "Ex Machina"
    cop_stars, scop_stars = 0, 10
    has_cop = False

    def atk(self, g, p, a, d, lvl):
        return 110

    def dfn(self, g, p, d, a, lvl):
        return 110

    def on_power(self, g, p, lvl):
        g.von_bolt_missile(p)


# power-star costs that are guesses rather than sourced
UNVERIFIED_COSTS = ("Sasha", "Kindle", "Sturm", "and every CO's AWBW-specific value: all costs come from AW2/DS, not AWBW")
