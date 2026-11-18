"""AWBW rules engine: standard (non-fog) 1v1.

Coordinates are (x, y) with y growing downward. HP is internal 1..100 (display = ceil(hp/10)).
`Game.legal_actions()` / `Game.step(action)` is the whole interface; `Game.copy()` clones state.
Randomness (luck) comes from `Game.rng`; pass `luck_fn` to override for tests.
"""
from __future__ import annotations

import heapq
import random
from dataclasses import dataclass, field
from enum import IntEnum
from typing import Callable, Optional

from .cos import CO, COS
from .data import (
    BUILDS, CAPTURABLE, CARRY, DMG, FACTORY_UNITS, FOOT, GROUND_UNITS, INCOME_PROPS, MT, STARS,
    TK, TRANSPORTS, UNITS, URBAN, UT, AIR_UNITS, NAVAL_UNITS, move_cost, uses_ammo, weapon,
)

STAR_BASE = 9000          # funds-points per power star   (AW2 value; AWBW value UNVERIFIED)
STAR_STEP = 1800          # +20% per power used            (AW2 value; AWBW value UNVERIFIED)
MAX_STAR_USES = 10
CP_MAX = 20
SEAM_HP = 99


class AT(IntEnum):
    WAIT = 0
    ATTACK = 1
    CAPTURE = 2
    LOAD = 3
    UNLOAD = 4
    JOIN = 5
    SUPPLY = 6
    REPAIR = 7
    DIVE = 8        # Sub dive / Stealth hide
    SURFACE = 9     # Sub surface / Stealth appear
    EXPLODE = 10
    LAUNCH = 11
    BUILD = 12
    POWER = 13
    END_TURN = 14
    DELETE = 15


@dataclass(frozen=True)
class Action:
    type: AT
    unit: int = -1
    dest: Optional[tuple] = None     # final tile of a unit action / BUILD tile
    target: Optional[tuple] = None   # attack tile / unload tile / launch tile
    arg: int = 0                     # BUILD: UT; POWER: 1=COP 2=SCOP; UNLOAD: cargo unit id


class IllegalAction(Exception):
    pass


@dataclass
class Unit:
    id: int
    owner: int
    type: UT
    x: int
    y: int
    hp: int = 100
    fuel: int = 0
    ammo: int = 0
    acted: bool = False
    moved: bool = False
    hidden: bool = False
    stunned: bool = False
    unload_lock: bool = False
    loaded_in: Optional[int] = None
    cargo: list = field(default_factory=list)

    def clone(self) -> "Unit":
        return Unit(self.id, self.owner, self.type, self.x, self.y, self.hp, self.fuel, self.ammo,
                    self.acted, self.moved, self.hidden, self.stunned, self.unload_lock,
                    self.loaded_in, list(self.cargo))


@dataclass
class Player:
    co: str
    country: int = 0
    funds: int = 0
    charge: int = 0       # power meter in funds-points
    power: int = 0        # 0 none, 1 COP active, 2 SCOP active
    uses: int = 0
    had_units: bool = False   # rout only applies once a player has fielded a unit

    def clone(self) -> "Player":
        return Player(self.co, self.country, self.funds, self.charge, self.power, self.uses, self.had_units)


def disp(hp: int) -> int:
    return (hp + 9) // 10


NEIGH = ((1, 0), (-1, 0), (0, 1), (0, -1))


class Game:
    def __init__(self, kinds, owners, cos=("Andy", "Andy"), units=(), starting_funds=0,
                 weather="C", seed=0, income_per_prop=1000, max_days=None, unit_limit=None, capture_limit=None,
                 first_turn_income=True, countries=(1, 2), luck_fn: Optional[Callable] = None, banned_units=()):
        self.h = len(kinds)
        self.w = len(kinds[0])
        self.kinds = [list(r) for r in kinds]
        self.owners = [list(r) for r in owners]
        self.cp = [[CP_MAX] * self.w for _ in range(self.h)]
        for y in range(self.h):          # pipe seams keep their HP (99 when intact) in the capture-points grid
            for x in range(self.w):
                if self.kinds[y][x] == TK.SEAM:
                    self.cp[y][x] = SEAM_HP
        self.players = [Player(cos[0], countries[0], starting_funds), Player(cos[1], countries[1], starting_funds)]
        self.units: dict[int, Unit] = {}
        self.pos: dict[tuple, int] = {}
        self.next_id = 1
        self.default_weather = weather
        self.weather = weather
        self.weather_expires: Optional[int] = None
        self.cur = 0
        self.day = 1
        self.income_per_prop = income_per_prop
        self.max_days = max_days              # Days Limit: after this day, most properties wins (tie = draw)
        self.capture_limit = capture_limit    # Capture Limit: first to own this many HQ/base/airport/port/city wins
        self.unit_limit = unit_limit
        self.banned_units = {int(t) for t in banned_units}   # unit types that may not be built
        self.first_turn_income = first_turn_income
        self.done = False
        self.winner: Optional[int] = None
        self.end_reason: Optional[str] = None   # rout / hq / labs / days / capture_limit
        self.last_missiles: list = []            # missile centres of the last CO power (for replays / checks)
        self.last_missile_options: list = []     # per missile: every equally good centre
        # AWBW: on a map without HQs, labs pre-owned by an army act as its HQ (lose them all -> out)
        self.lab_hq = not any(k == TK.HQ for r in self.kinds for k in r)
        self.lab_players = {o for r_k, r_o in zip(self.kinds, self.owners) for k, o in zip(r_k, r_o)
                            if k == TK.LAB and o in (0, 1)} if self.lab_hq else set()
        self.rng = random.Random(seed)
        self.luck_fn = luck_fn
        for (p, t, x, y, *rest) in units:
            u = self._spawn(p, UT(t), x, y, hp=rest[0] if rest else 100)
        self._start_turn(0, first=True)

    # ------------------------------------------------------------ construction helpers
    def _spawn(self, p, t, x, y, hp=100, acted=False) -> Unit:
        info = UNITS[t]
        u = Unit(self.next_id, p, t, x, y, hp, info.fuel, info.ammo, acted=acted)
        self.next_id += 1
        self.units[u.id] = u
        self.pos[(x, y)] = u.id
        self.players[p].had_units = True
        return u

    def copy(self) -> "Game":
        g = Game.__new__(Game)
        g.__dict__.update(self.__dict__)
        g.kinds = [list(r) for r in self.kinds]
        g.owners = [list(r) for r in self.owners]
        g.cp = [list(r) for r in self.cp]
        g.players = [p.clone() for p in self.players]
        g.units = {i: u.clone() for i, u in self.units.items()}
        g.pos = dict(self.pos)
        g.rng = random.Random()
        g.rng.setstate(self.rng.getstate())
        return g

    # ------------------------------------------------------------ small queries
    def co(self, p) -> CO:
        return COS[self.players[p].co]

    def lvl(self, p) -> int:
        return self.players[p].power

    def kind_at(self, x, y) -> TK:
        return self.kinds[y][x]

    def in_bounds(self, x, y) -> bool:
        return 0 <= x < self.w and 0 <= y < self.h

    def unit_at(self, x, y) -> Optional[Unit]:
        i = self.pos.get((x, y))
        return self.units[i] if i is not None else None

    def my_units(self, p):
        return [u for u in self.units.values() if u.owner == p]

    def count_owned(self, p, kinds) -> int:
        ks = set(kinds)
        return sum(1 for y in range(self.h) for x in range(self.w)
                   if self.owners[y][x] == p and self.kinds[y][x] in ks)

    def count_income_props(self, p) -> int:
        return self.count_owned(p, INCOME_PROPS)

    def stars_of(self, u) -> int:
        """Terrain stars under a unit (air units get none)."""
        if u.type in AIR_UNITS:
            return 0
        return STARS[self.kinds[u.y][u.x]]

    def unit_cost(self, p, t) -> int:
        return UNITS[t].cost * self.co(p).cost_pct(self.lvl(p)) // 100

    def star_value(self, p) -> int:
        return STAR_BASE + STAR_STEP * min(self.players[p].uses, MAX_STAR_USES)

    def power_cost(self, p, lvl) -> int:
        co = self.co(p)
        stars = co.cop_stars if lvl == 1 else co.scop_stars
        return stars * self.star_value(p)

    def max_charge(self, p) -> int:
        return self.co(p).scop_stars * self.star_value(p)

    # ------------------------------------------------------------ movement
    def move_points(self, u) -> int:
        co = self.co(u.owner)
        return max(0, UNITS[u.type].mp + co.move_bonus(self, u.owner, u, self.lvl(u.owner)))

    def tile_cost(self, u, x, y) -> Optional[int]:
        co = self.co(u.owner)
        lv = self.lvl(u.owner)
        w = co.effective_weather(self.weather)
        c = move_cost(w, self.kinds[y][x], UNITS[u.type].mt)
        if c is None:
            return None
        if co.flat_move_cost_levels[lv] and w != "S":
            return 1
        return c

    def can_carry(self, transport, u) -> bool:
        spec = CARRY.get(transport.type)
        return bool(spec and u.type in spec[1] and len(transport.cargo) < spec[0]
                    and transport.owner == u.owner and transport.id != u.id)   # AWBW: a loaded APC may board a Lander

    def reachable(self, u) -> dict:
        """tile -> cheapest movement cost, for tiles the unit may stop on or pass through."""
        limit = min(self.move_points(u), u.fuel)
        start = (u.x, u.y)
        dist = {start: 0}
        heap = [(0, start)]
        while heap:
            d0, (x, y) = heapq.heappop(heap)
            if d0 > dist.get((x, y), 1 << 30):
                continue
            for dx, dy in NEIGH:
                nx, ny = x + dx, y + dy
                if not self.in_bounds(nx, ny):
                    continue
                occ = self.unit_at(nx, ny)
                c = self.tile_cost(u, nx, ny)
                # a friendly transport is boarded only where the cargo could stand (AWBW: Landers load at shoals/ports)
                if occ is not None and occ.owner != u.owner:
                    continue
                if c is None:
                    continue
                nd = d0 + c
                if nd > limit or nd >= dist.get((nx, ny), 1 << 30):
                    continue
                dist[(nx, ny)] = nd
                heapq.heappush(heap, (nd, (nx, ny)))
        return dist

    # ------------------------------------------------------------ combat math
    def atk_pct(self, a, d) -> int:
        p = a.owner
        lv = self.lvl(p)
        v = self.co(p).atk(self, p, a, d, lv)
        if lv > 0:
            v += 10          # universal +10% on COP/SCOP
        v += 10 * self.count_owned(p, (TK.COMTOWER,))   # each owned com tower: +10% attack (checked against replays)
        return v

    def def_pct(self, d, a) -> int:
        p = d.owner
        lv = self.lvl(p)
        v = self.co(p).dfn(self, p, d, a, lv)
        if lv > 0:
            v += 10
        return v

    def roll_luck(self, p) -> int:
        if self.luck_fn is not None:
            return self.luck_fn(p)
        pos, neg = self.co(p).luck(self.lvl(p))
        r = self.rng.randint(0, pos)
        if neg:
            r -= self.rng.randint(0, neg)
        return r

    def damage_calc(self, a, d, luck, counter=False) -> int:
        """AWBW damage in internal HP percent: rounded UP to the next 0.05, then down to an integer
        (fits 646/661 exact counter-damage observations from real replays; plain floor fits 644 and never one more)."""
        b = weapon(a.type, d.type, a.ammo)[0]
        if b == 0:
            return 0
        aco = self.atk_pct(a, d)
        dco = self.def_pct(d, a)
        dtr = self.stars_of(d) * self.co(d.owner).star_mult(self.lvl(d.owner))
        num = (b * aco + 100 * luck) * disp(a.hp) * (200 - (dco + dtr * disp(d.hp)))
        den = 100 * 10 * 100
        if counter and self.co(a.owner).counter_boost(self.lvl(a.owner)):
            num, den = num * 3, den * 2
        if num <= 0:
            return 0
        return -(-20 * num // den) // 20      # ceil to 0.05, then floor

    def attack_range(self, u):
        info = UNITS[u.type]
        if info.rmax == 0:
            return 0, 0
        bonus = self.co(u.owner).range_bonus(self, u.owner, u, self.lvl(u.owner)) if info.rmax > 1 else 0
        return info.rmin, max(info.rmin, info.rmax + bonus)

    def can_hit(self, a, d) -> bool:
        return weapon(a.type, d.type, a.ammo)[0] > 0

    def _visible_to(self, p, t) -> bool:
        if not t.hidden:
            return True
        if self.co(p).sees_hidden(self.lvl(p)):
            return True
        for dx, dy in NEIGH:
            o = self.unit_at(t.x + dx, t.y + dy)
            if o is not None and o.owner == p:
                return True
        return False

    def attack_targets(self, u, x, y, moved) -> list:
        """Enemy unit tiles u could hit standing at (x,y)."""
        rmin, rmax = self.attack_range(u)
        if rmax == 0:
            return []
        if rmin > 1 and moved:
            return []
        out = []
        for ty in range(max(0, y - rmax), min(self.h, y + rmax + 1)):
            for tx in range(max(0, x - rmax), min(self.w, x + rmax + 1)):
                dd = abs(tx - x) + abs(ty - y)
                if dd < rmin or dd > rmax:
                    continue
                t = self.unit_at(tx, ty)
                if t is None and self.kinds[ty][tx] == TK.SEAM:
                    if weapon(u.type, UT.NEO, u.ammo)[0] > 0:
                        out.append((tx, ty))
                    continue
                if t is None or t.owner == u.owner or t.loaded_in is not None:
                    continue
                if self.can_hit(u, t) and self._visible_to(u.owner, t):
                    out.append((tx, ty))
        return out

    # ------------------------------------------------------------ power charge
    def add_charge(self, p, pts):
        pl = self.players[p]
        if pl.power == 0 and pts > 0:
            pl.charge = min(pl.charge + pts, self.max_charge(p))

    def _after_damage(self, victim_owner, victim_type, lost, attacker_owner):
        if lost <= 0:
            return
        value = self.unit_cost(victim_owner, victim_type) * lost // 100
        self.add_charge(victim_owner, value)
        self.add_charge(attacker_owner, value // 2)
        # Sasha SCOP: War Bonds
        if self.players[attacker_owner].co == "Sasha" and self.lvl(attacker_owner) == 2:
            self.players[attacker_owner].funds += value // 2

    # ------------------------------------------------------------ killing / removing
    def _remove(self, u):
        for cid in list(u.cargo):
            self._remove(self.units[cid])
        if u.loaded_in is None:
            self.pos.pop((u.x, u.y), None)
            if self.cp[u.y][u.x] < CP_MAX and u.type in FOOT:
                self.cp[u.y][u.x] = CP_MAX
        else:
            t = self.units.get(u.loaded_in)
            if t and u.id in t.cargo:
                t.cargo.remove(u.id)
        self.units.pop(u.id, None)

    def _hit(self, a_owner, v, dmg, ammo_user=None):
        """Apply dmg to unit v; returns True if destroyed."""
        before = v.hp
        v.hp = max(0, v.hp - dmg)
        # power meters grow by the value of DISPLAYED HP lost (matches 1445/1449 fights in real replays)
        self._after_damage(v.owner, v.type, (disp(before) - disp(v.hp)) * 10, a_owner)
        if v.hp == 0:
            self._remove(v)
            return True
        return False

    def can_counter(self, d, a) -> bool:
        rmin, rmax = self.attack_range(d)
        return rmax == 1 and rmin == 1 and self.can_hit(d, a)

    def do_attack(self, a, d):
        direct = UNITS[a.type].rmax == 1
        co_d = self.co(d.owner)
        counter_first = (co_d.name == "Sonja" and self.lvl(d.owner) == 2 and direct and self.can_counter(d, a))
        if counter_first:
            uses = weapon(d.type, a.type, d.ammo)[1]
            cd = self.damage_calc(d, a, self.roll_luck(d.owner), counter=True)
            if uses:
                d.ammo -= 1
            if self._hit(d.owner, a, cd):
                return
            uses = weapon(a.type, d.type, a.ammo)[1]
            dmg = self.damage_calc(a, d, self.roll_luck(a.owner))
            if uses:
                a.ammo -= 1
            self._hit(a.owner, d, dmg)
            return
        uses = weapon(a.type, d.type, a.ammo)[1]
        dmg = self.damage_calc(a, d, self.roll_luck(a.owner))
        if uses:
            a.ammo -= 1
        if self._hit(a.owner, d, dmg):
            return
        if direct and self.can_counter(d, a):
            uses = weapon(d.type, a.type, d.ammo)[1]
            cd = self.damage_calc(d, a, self.roll_luck(d.owner), counter=True)
            if uses:
                d.ammo -= 1
            self._hit(d.owner, a, cd)

    def _attack_seam(self, a, xy):
        """Pipe seam: damaged as a Neotank on a road with the lowest possible luck roll (no terrain, no defending CO,
        no counter, no power charge). At 0 HP it becomes rubble."""
        x, y = xy
        dummy = Unit(0, a.owner, UT.NEO, x, y)
        b, uses = weapon(a.type, UT.NEO, a.ammo)
        aco = self.atk_pct(a, dummy)
        lowest = -self.co(a.owner).luck(self.lvl(a.owner))[1]      # no luck roll: always the lowest possible roll
        num = (b * aco + 100 * lowest) * disp(a.hp) * 100
        dmg = -(-20 * num // 100000) // 20 if num > 0 else 0     # same scale as damage_calc
        if uses:
            a.ammo -= 1
        self.cp[y][x] -= dmg
        if self.cp[y][x] <= 0:
            self.kinds[y][x] = TK.RUBBLE
            self.cp[y][x] = CP_MAX

    # ------------------------------------------------------------ action generation
    def _adjacent_friends(self, u, x, y):
        out = []
        for dx, dy in NEIGH:
            o = self.unit_at(x + dx, y + dy)
            if o is not None and o.owner == u.owner and o.id != u.id:
                out.append(o)
        return out

    def unit_actions(self, u) -> list:
        if self.done or u.owner != self.cur or u.loaded_in is not None:
            return []
        if u.acted:   # AWBW (replays): cargo can still be dropped next to a transport that has already acted
            return self._unload_actions(u, (u.x, u.y))
        acts: list[Action] = []
        if u.unload_lock:
            dist = {(u.x, u.y): 0}
        else:
            dist = self.reachable(u)
        info = UNITS[u.type]
        for dest in dist:
            occ = self.unit_at(*dest)
            if occ is not None and occ.id != u.id:
                if self.can_carry(occ, u):
                    acts.append(Action(AT.LOAD, u.id, dest))
                elif (occ.type == u.type and occ.hp < 100 and not occ.cargo and not u.cargo):
                    acts.append(Action(AT.JOIN, u.id, dest))
                continue
            moved = dest != (u.x, u.y) or u.moved
            if not u.unload_lock:
                acts.append(Action(AT.WAIT, u.id, dest))
                for t in self.attack_targets(u, dest[0], dest[1], moved):
                    acts.append(Action(AT.ATTACK, u.id, dest, t))
                if u.type in FOOT:
                    k = self.kinds[dest[1]][dest[0]]
                    if k in CAPTURABLE and self.owners[dest[1]][dest[0]] != u.owner:
                        acts.append(Action(AT.CAPTURE, u.id, dest))
                    if k == TK.SILO:
                        for ty in range(self.h):
                            for tx in range(self.w):
                                acts.append(Action(AT.LAUNCH, u.id, dest, (tx, ty)))
                if u.type == UT.APC and self._adjacent_friends_at(u, dest):     # AWBW: allowed even if nobody is low
                    acts.append(Action(AT.SUPPLY, u.id, dest))
                if u.type == UT.BLACKBOAT:      # AWBW (replays): repairs ONE chosen adjacent unit
                    for o in self._adjacent_friends_at(u, dest):
                        acts.append(Action(AT.REPAIR, u.id, dest, (o.x, o.y)))
                if u.type in (UT.SUB, UT.STEALTH):
                    acts.append(Action(AT.SURFACE if u.hidden else AT.DIVE, u.id, dest))
                if u.type == UT.BLACKBOMB:
                    acts.append(Action(AT.EXPLODE, u.id, dest))
            else:
                acts.append(Action(AT.WAIT, u.id, dest))
            acts.extend(self._unload_actions(u, dest))
        return acts

    def _unload_actions(self, u, dest) -> list:
        acts = []
        # AWBW (libaw rule findings A10; 0 of ~3,900 recorded unloads): APC / T-Copter / Lander / Black Boat cannot
        # unload while standing on Sea or Reef (Cruiser and Carrier can)
        if u.type in TRANSPORTS and self.kinds[dest[1]][dest[0]] in (TK.SEA, TK.REEF):
            return acts
        for cid in u.cargo:
            c = self.units[cid]
            if c.acted:   # AWBW refuses to drop cargo that boarded this turn (live game 1764106, 2026-11-15)
                continue
            for dx, dy in NEIGH:
                q = (dest[0] + dx, dest[1] + dy)
                if (self.in_bounds(*q) and (self.unit_at(*q) is None or q == (u.x, u.y) and dest != q)
                        and self.tile_cost(c, *q) is not None):
                    acts.append(Action(AT.UNLOAD, u.id, dest, q, cid))
        return acts

    def _adjacent_friends_at(self, u, dest):
        out = []
        for dx, dy in NEIGH:
            o = self.unit_at(dest[0] + dx, dest[1] + dy)
            if o is not None and o.owner == u.owner and o.id != u.id:
                out.append(o)
        return out

    @staticmethod
    def _needs_supply(o) -> bool:
        info = UNITS[o.type]
        return o.fuel < info.fuel or o.ammo < info.ammo

    def build_actions(self) -> list:
        acts = []
        p = self.cur
        pl = self.players[p]
        count = len(self.my_units(p))
        if self.unit_limit is not None and count >= self.unit_limit:
            return acts
        lv = self.lvl(p)
        for y in range(self.h):
            for x in range(self.w):
                if self.owners[y][x] != p or (x, y) in self.pos:
                    continue
                k = self.kinds[y][x]
                menu = BUILDS.get(k)
                if menu is None and k == TK.CITY and self.co(p).name == "Hachi" and lv == 2:
                    menu = FACTORY_UNITS
                if menu is None:
                    continue
                for t in menu:
                    if self.unit_cost(p, t) <= pl.funds and int(t) not in self.banned_units:
                        acts.append(Action(AT.BUILD, -1, (x, y), None, int(t)))
        return acts

    def legal_actions(self) -> list:
        if self.done:
            return []
        acts: list[Action] = []
        for u in list(self.units.values()):
            if u.owner == self.cur:
                acts.extend(self.unit_actions(u))
        acts.extend(self.build_actions())
        p = self.cur
        pl = self.players[p]
        co = self.co(p)
        if pl.power == 0:
            if co.has_cop and pl.charge >= self.power_cost(p, 1) > 0:
                acts.append(Action(AT.POWER, arg=1))
            if pl.charge >= self.power_cost(p, 2):
                acts.append(Action(AT.POWER, arg=2))
        acts.append(Action(AT.END_TURN))
        return acts

    # ------------------------------------------------------------ step
    def step(self, a: Action):
        if self.done:
            raise IllegalAction("game over")
        t = a.type
        if t == AT.END_TURN:
            self._end_turn()
        elif t == AT.POWER:
            if a not in [x for x in self.legal_actions() if x.type == AT.POWER]:
                raise IllegalAction(f"power not available: {a}")
            self._activate_power(a.arg)
        elif t == AT.BUILD:
            if a not in self.build_actions():
                raise IllegalAction(f"illegal build: {a}")
            p = self.cur
            self.players[p].funds -= self.unit_cost(p, UT(a.arg))
            self._spawn(p, UT(a.arg), a.dest[0], a.dest[1], acted=True)
        elif t == AT.DELETE:
            u = self.units.get(a.unit)
            if u is None or u.owner != self.cur:
                raise IllegalAction("bad delete")
            self._remove(u)
        else:
            u = self.units.get(a.unit)
            if u is None or a not in self.unit_actions(u):
                raise IllegalAction(f"illegal unit action: {a}")
            self._do_unit_action(u, a)
        self._check_end()

    def _do_unit_action(self, u, a):
        dest = a.dest
        t = a.type
        if dest != (u.x, u.y):
            cost = self.reachable(u)[dest]
            self._relocate(u, dest, cost, boarding=(t in (AT.LOAD, AT.JOIN)))
        if t == AT.WAIT:
            u.acted = True
            u.unload_lock = False
        elif t == AT.ATTACK:
            d = self.unit_at(*a.target)
            if d is None:
                self._attack_seam(u, a.target)
            else:
                self.do_attack(u, d)
            if u.id in self.units:
                u.acted = True
        elif t == AT.CAPTURE:
            self._capture(u)
            u.acted = True
        elif t == AT.LOAD:
            tr = self.units[self.pos[dest]]
            tr.cargo.append(u.id)
            u.loaded_in = tr.id
            u.acted = True
        elif t == AT.UNLOAD:
            c = self.units[a.arg]
            u.cargo.remove(c.id)
            c.loaded_in = None
            c.x, c.y = a.target
            self.pos[a.target] = c.id
            self._carry_along(c, a.target)
            c.acted = True
            c.moved = True
            # AWBW (replays): unloading in place leaves the transport free to move and act; a transport that moved
            # first is done moving but may keep dropping cargo
            if u.moved:
                u.acted = True
        elif t == AT.JOIN:
            other = self.units[self.pos[dest]]
            self._join(u, other)
        elif t == AT.SUPPLY:
            for o in self._adjacent_friends(u, u.x, u.y):
                o.fuel, o.ammo = UNITS[o.type].fuel, UNITS[o.type].ammo
            u.acted = True
        elif t == AT.REPAIR:
            p = u.owner
            o = self.unit_at(*a.target)
            # AWBW (libaw B4): +1.0 HP keeping the fraction; a 9.x unit is topped up to 10 only if it also needs supplies
            if o.hp < 100 and (disp(o.hp) < 10 or self._needs_supply(o)):
                new = min(100, o.hp + 10)
                cost = self.unit_cost(p, o.type) * (disp(new) - disp(o.hp)) // 10
                if self.players[p].funds >= cost:
                    self.players[p].funds -= cost
                    o.hp = new
            o.fuel, o.ammo = UNITS[o.type].fuel, UNITS[o.type].ammo
            u.acted = True
        elif t == AT.DIVE:
            u.hidden = True
            u.acted = True
        elif t == AT.SURFACE:
            u.hidden = False
            u.acted = True
        elif t == AT.EXPLODE:
            self._explode(u)
        elif t == AT.LAUNCH:
            self._launch(u, a.target)
            u.acted = True

    def _carry_along(self, u, xy):
        """Cargo (and cargo's cargo) sits on its transport's tile."""
        for cid in u.cargo:
            c = self.units[cid]
            c.x, c.y = xy
            self._carry_along(c, xy)

    def _relocate(self, u, dest, cost, boarding=False):
        if self.cp[u.y][u.x] < CP_MAX and u.type in FOOT:
            self.cp[u.y][u.x] = CP_MAX
        self.pos.pop((u.x, u.y), None)
        u.x, u.y = dest
        if not boarding:
            self.pos[dest] = u.id
        self._carry_along(u, dest)
        u.fuel -= cost
        u.moved = True

    def _capture(self, u):
        x, y = u.x, u.y
        p = u.owner
        co = self.co(p)
        lv = self.lvl(p)
        amount = disp(u.hp) * co.capture_bonus_pct(lv) // 100
        if co.instant_capture(lv):
            amount = CP_MAX
        self.cp[y][x] -= amount
        if self.cp[y][x] <= 0:
            prev = self.owners[y][x]
            self.owners[y][x] = p
            self.cp[y][x] = CP_MAX
            k = self.kinds[y][x]
            if k == TK.HQ:
                self._finish(p, "hq")
            elif k == TK.LAB and prev in self.lab_players and self.count_owned(prev, (TK.LAB,)) == 0:
                self._finish(p, "labs")
            elif self.capture_limit is not None and self.count_income_props(p) >= self.capture_limit:
                self._finish(p, "capture_limit")

    def _join(self, u, other):
        # AWBW (checked against replays): displayed HP add up, the result is a whole HP value, excess displayed HP
        # is refunded at the unit's price; fuel and ammo add up to the maximum
        total = disp(u.hp) + disp(other.hp)
        excess = max(0, total - 10)
        other.hp = min(10, total) * 10
        info = UNITS[other.type]
        other.fuel = min(info.fuel, other.fuel + u.fuel)
        other.ammo = min(info.ammo, other.ammo + u.ammo)
        self.players[u.owner].funds += self.unit_cost(u.owner, u.type) * excess // 10
        self.units.pop(u.id, None)       # u already left self.pos when it moved onto `other`
        other.acted = True               # AWBW: joining ends the merged unit's turn, even if it had not acted yet

    def _explode(self, u):
        # ASSUMPTION: radius 3 (Manhattan), 5 HP, hits friend and foe, min 0.1 HP.
        cx, cy = u.x, u.y
        self._remove(u)
        for v in list(self.units.values()):
            if v.loaded_in is None and abs(v.x - cx) + abs(v.y - cy) <= 3:
                v.hp = max(1, v.hp - 50)

    def _launch(self, u, target):
        tx, ty = target
        self.kinds[u.y][u.x] = TK.SILO_EMPTY
        for v in list(self.units.values()):
            if v.loaded_in is None and abs(v.x - tx) + abs(v.y - ty) <= 2:
                v.hp = max(1, v.hp - 30)

    # ------------------------------------------------------------ CO power helpers
    def set_weather(self, w, caster):
        self.weather = w
        self.weather_expires = caster

    def damage_enemies(self, p, amt, halve_fuel=False, only_urban=False):
        for v in self.units.values():
            if v.owner == p:
                continue
            if only_urban:
                if self.kinds[v.y][v.x] not in URBAN:
                    continue
            v.hp = max(1, v.hp - amt)
            if halve_fuel:
                v.fuel //= 2

    def heal_all(self, p, amt, carried=True):
        for v in self.units.values():
            if v.owner == p and (carried or v.loaded_in is None):
                v.hp = min(100, v.hp + amt)

    def resupply_all(self, p):
        for v in self.units.values():
            if v.owner == p:
                v.fuel, v.ammo = UNITS[v.type].fuel, UNITS[v.type].ammo

    def refresh_units(self, p, pred):
        for v in self.units.values():
            if v.owner == p and v.loaded_in is None and pred(v):
                v.acted = False
                v.moved = False
                v.unload_lock = False

    def sensei_spawn(self, p, ut):
        for y in range(self.h):
            for x in range(self.w):
                if self.kinds[y][x] == TK.CITY and self.owners[y][x] == p and (x, y) not in self.pos:
                    self._spawn(p, ut, x, y, hp=90)

    def market_crash(self, p):
        # opponent loses 10% of their meter's maximum per 5000 funds, not rounded to whole percents
        # (exact on every Market Crash in the replays)
        funds = self.players[p].funds
        for q in (0, 1):
            if q != p:
                pl = self.players[q]
                pl.charge = max(0, pl.charge - self.max_charge(q) * funds // 50000)

    # Missiles (checked against AWBW replays: 7/7 Von Bolt centres, 5/6 Rachel missiles): the centre can be any tile;
    # it is the one where the enemy loses the most, counting only damage the missile can really do (at most `hp`
    # displayed HP, never below 1); among tied tiles AWBW's pick looks random, the engine takes the first. The blast (radius 2) then hits
    # EVERY unit in range, the caster's own included, leaving at least 0.1 HP.
    def _missile_score(self, enemy, cx, cy, score, hp):
        total = 0
        for v in self.units.values():
            if v.owner == enemy and v.loaded_in is None and abs(v.x - cx) + abs(v.y - cy) <= 2:
                total += score(v, min(hp, disp(v.hp) - 1))
        return total

    def _best_center(self, p, score, hp=3):
        enemy = 1 - p
        best, bc = 0, None
        tied = []
        for y in range(self.h):
            for x in range(self.w):
                s = self._missile_score(enemy, x, y, score, hp)
                if s > best:
                    best, bc, tied = s, (x, y), [(x, y)]
                elif s == best and s > 0:
                    tied.append((x, y))
        self.last_missile_options.append(tied)     # AWBW seems to pick randomly among tied tiles
        return bc

    def _blast(self, p, center, dmg, stun=False):
        self.last_missiles.append(center)
        for v in list(self.units.values()):
            if v.loaded_in is None and abs(v.x - center[0]) + abs(v.y - center[1]) <= 2:
                v.hp = max(1, v.hp - dmg)
                if stun and v.owner != p:
                    v.stunned = True              # the enemy skips its next turn
                elif stun:
                    # 2026-11-17 (user, live game 1765038; tools/vb_stun*.py on 470 expert Von Bolt games): Ex Machina stuns
                    # the caster's own units too (AWBW units_moved -1), but only for the rest of this turn - 50% act on the
                    # caster's next turn (enemy units hit: 0.9% on their next turn)
                    v.acted = True

    @staticmethod
    def _value(v, lost):
        return UNITS[v.type].cost * lost // 10

    def sturm_missile(self, p, dmg):
        c = self._best_center(p, self._value, dmg // 10)
        if c:
            self._blast(p, c, dmg)

    def von_bolt_missile(self, p):
        c = self._best_center(p, self._value)
        if c:
            self._blast(p, c, 30, stun=True)

    def rachel_missiles(self, p):
        for score in (lambda v, lost: lost if v.type in FOOT else 0, self._value, lambda v, lost: lost):
            c = self._best_center(p, score)
            if c:
                self._blast(p, c, 30)

    # ------------------------------------------------------------ turn flow
    def _activate_power(self, lvl):
        p = self.cur
        self.last_missiles, self.last_missile_options = [], []
        pl = self.players[p]
        pl.charge -= self.power_cost(p, lvl)
        pl.uses += 1
        pl.power = lvl
        self.co(p).on_power(self, p, lvl)

    def _end_turn(self):
        for u in self.units.values():
            u.unload_lock = False
        self.cur = 1 - self.cur
        if self.cur == 0:
            self.day += 1
            if self.max_days is not None and self.day > self.max_days:
                a, b = (self.count_owned(q, CAPTURABLE) for q in (0, 1))
                self._finish(0 if a > b else 1 if b > a else None, "days")
                return
        self._start_turn(self.cur)

    def _start_turn(self, p, first=False):
        pl = self.players[p]
        co = self.co(p)
        pl.power = 0
        if self.weather_expires == p:
            self.weather = self.default_weather
            self.weather_expires = None
        for u in self.my_units(p):
            u.acted = False
            u.moved = False
            u.unload_lock = False
            if u.stunned:
                u.acted = True
                u.stunned = False
        if first and not self.first_turn_income:
            pass
        else:
            pl.funds += self.income_per_prop * self.count_income_props(p) + co.income_bonus(self, p)
        crashed = []
        for u in self.my_units(p):
            if u.loaded_in is not None:
                continue
            info = UNITS[u.type]
            fpt = info.hidden_fuel if (u.hidden and info.hidden_fuel) else info.fuel_per_turn
            if fpt:
                fpt = max(0, fpt + co.fuel_per_turn_delta(u.type))
            if self.day > 1:                 # AWBW (replays): no daily fuel burn on day 1
                u.fuel -= fpt
            k = self.kinds[u.y][u.x]
            on_own = self.owners[u.y][u.x] == p
            mt = info.mt
            supports = on_own and (
                (k in (TK.CITY, TK.BASE, TK.HQ) and mt in (MT.F, MT.B, MT.T, MT.W, MT.P)) or
                (k == TK.AIRPORT and mt == MT.A) or (k == TK.PORT and mt in (MT.S, MT.L)))
            if supports:
                if u.hp < 100:
                    heal = min(20 + co.repair_bonus, 100 - u.hp)
                    new = u.hp + heal
                    cost = self.unit_cost(p, u.type) * (disp(new) - disp(u.hp)) // 10
                    if pl.funds >= cost:
                        pl.funds -= cost
                        u.hp = new
                u.fuel, u.ammo = info.fuel, info.ammo
        # APCs (not Black Boats) resupply adjacent friendly units at turn start (AWBW replays)
        for apc in self.my_units(p):
            if apc.type == UT.APC and apc.loaded_in is None:
                todo = list(self._adjacent_friends(apc, apc.x, apc.y))
                while todo:                                    # ... including the cargo of transports next to it
                    o = todo.pop()
                    o.fuel, o.ammo = UNITS[o.type].fuel, UNITS[o.type].ammo
                    todo.extend(self.units[c] for c in o.cargo)
        for u in self.my_units(p):
            if u.loaded_in is not None:
                continue
            info = UNITS[u.type]
            fpt = info.hidden_fuel if (u.hidden and info.hidden_fuel) else info.fuel_per_turn
            if fpt and u.fuel <= 0:
                crashed.append(u)
        for u in crashed:
            if u.id in self.units:
                self._remove(u)

    def _finish(self, winner, reason):
        self.done, self.winner, self.end_reason = True, winner, reason

    def _check_end(self):
        if self.done:
            return
        for q in (0, 1):   # Rout: a player who has fielded units and now has none is out
            if self.players[q].had_units and not self.my_units(q):
                self._finish(1 - q, "rout")
                return
