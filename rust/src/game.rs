//! AWBW rules engine (standard, non-fog, 1v1): a line-by-line port of awbw/game.py + awbw/cos.py.
//!
//! The Python engine is the reference: tests/test_rust_engine.py plays random games through both with the same
//! luck rolls and compares legal actions and the full state after every action. Change the rules there first,
//! then here. Constants come from tables.rs (generated from awbw/data.py and awbw/cos.py).
//! HP is internal 1..100 (display = ceil(hp/10)); coordinates are (x, y) with y growing downward.

use crate::tables::*;
use std::cmp::Reverse;
use std::collections::{BinaryHeap, HashMap};
use std::hash::{BuildHasherDefault, Hasher};

/// Unit ids are already well-spread integers: hash them as themselves.
#[derive(Default, Clone)]
pub struct IdHasher(u64);
impl Hasher for IdHasher {
    fn finish(&self) -> u64 {
        self.0
    }
    fn write(&mut self, _: &[u8]) {
        unreachable!()
    }
    fn write_i64(&mut self, v: i64) {
        self.0 = (v as u64).wrapping_mul(0x9E3779B97F4A7C15);
    }
}
pub type IdMap = HashMap<i64, usize, BuildHasherDefault<IdHasher>>;

pub const CP_MAX: i64 = 20;
pub const SEAM_HP: i64 = 99;
const STAR_BASE: i64 = 9000;
const STAR_STEP: i64 = 1800;
const MAX_STAR_USES: i64 = 10;
const NEIGH: [(i32, i32); 4] = [(1, 0), (-1, 0), (0, 1), (0, -1)];
pub const NONE: i64 = -1;

// action types (same numbers as awbw.game.AT)
pub const AT_WAIT: u8 = 0;
pub const AT_ATTACK: u8 = 1;
pub const AT_CAPTURE: u8 = 2;
pub const AT_LOAD: u8 = 3;
pub const AT_UNLOAD: u8 = 4;
pub const AT_JOIN: u8 = 5;
pub const AT_SUPPLY: u8 = 6;
pub const AT_REPAIR: u8 = 7;
pub const AT_DIVE: u8 = 8;
pub const AT_SURFACE: u8 = 9;
pub const AT_EXPLODE: u8 = 10;
pub const AT_LAUNCH: u8 = 11;
pub const AT_BUILD: u8 = 12;
pub const AT_POWER: u8 = 13;
pub const AT_END_TURN: u8 = 14;
pub const AT_DELETE: u8 = 15;

pub const W_CLEAR: u8 = 0;
pub const W_RAIN: u8 = 1;
pub const W_SNOW: u8 = 2;

pub fn disp(hp: i64) -> i64 {
    (hp + 9).div_euclid(10)
}

fn pick(lvl: u8, v: (i64, i64, i64)) -> i64 {
    match lvl {
        0 => v.0,
        1 => v.1,
        _ => v.2,
    }
}

fn is_direct(t: u8) -> bool {
    UNIT_RMAX[t as usize] == 1
}

fn is_indirect(t: u8) -> bool {
    UNIT_RMAX[t as usize] > 1
}

/// Python's `//` on i64 (floor division, rounding toward minus infinity).
fn fdiv(a: i64, b: i64) -> i64 {
    let q = a / b;
    if a % b != 0 && ((a < 0) != (b < 0)) { q - 1 } else { q }
}

pub fn splitmix(mut z: u64) -> u64 {
    z = z.wrapping_add(0x9E3779B97F4A7C15);
    z = (z ^ (z >> 30)).wrapping_mul(0xBF58476D1CE4E5B9);
    z = (z ^ (z >> 27)).wrapping_mul(0x94D049BB133111EB);
    z ^ (z >> 31)
}

#[derive(Clone, Copy, Debug, PartialEq, Eq, Hash, PartialOrd, Ord)]
pub struct Action {
    pub t: u8,
    pub unit: i64,
    pub dx: i32,
    pub dy: i32,
    pub tx: i32,
    pub ty: i32,
    pub arg: i64,
}

impl Action {
    pub fn simple(t: u8) -> Self {
        Action { t, unit: NONE, dx: -1, dy: -1, tx: -1, ty: -1, arg: 0 }
    }
    fn unit(t: u8, unit: i64, d: (i32, i32)) -> Self {
        Action { t, unit, dx: d.0, dy: d.1, tx: -1, ty: -1, arg: 0 }
    }
    fn target(t: u8, unit: i64, d: (i32, i32), q: (i32, i32), arg: i64) -> Self {
        Action { t, unit, dx: d.0, dy: d.1, tx: q.0, ty: q.1, arg }
    }
}

#[derive(Clone, Debug)]
pub struct Unit {
    pub id: i64,
    pub owner: usize,
    pub t: u8,
    pub x: i32,
    pub y: i32,
    pub hp: i64,
    pub fuel: i64,
    pub ammo: i64,
    pub acted: bool,
    pub moved: bool,
    pub hidden: bool,
    pub stunned: bool,
    pub loaded_in: i64,
    pub cargo: Vec<i64>,
}

/// What combat formulas need of a unit (also stands in for a pipe seam's dummy Neotank).
#[derive(Clone, Copy)]
struct UV {
    owner: usize,
    t: u8,
    x: i32,
    y: i32,
    hp: i64,
}

#[derive(Clone, Debug)]
pub struct Player {
    pub co: u8,
    pub country: i64,
    pub funds: i64,
    pub charge: i64,
    pub power: u8,
    pub uses: i64,
    pub had_units: bool,
}

#[derive(Clone)]
pub struct Game {
    pub w: i32,
    pub h: i32,
    pub kinds: Vec<u8>,
    pub owners: Vec<i8>,
    pub cp: Vec<i64>,
    pub players: [Player; 2],
    pub units: Vec<Unit>, // insertion order, like the Python dict
    pub index: IdMap,     // unit id -> position in `units`
    pub pos: Vec<i64>,    // tile -> unit id (NONE if empty); loaded units are not on the map
    pub next_id: i64,
    pub default_weather: u8,
    pub weather: u8,
    pub weather_expires: i64,
    pub cur: usize,
    pub day: i64,
    pub income_per_prop: i64,
    pub max_days: i64,
    pub capture_limit: i64,
    pub banned: u32, // bit t set: unit type t may not be built
    pub unit_limit: i64,
    pub first_turn_income: bool,
    pub done: bool,
    pub winner: i64,
    pub end_reason: &'static str,
    pub lab_hq: bool,
    pub lab_players: [bool; 2],
    pub last_missiles: Vec<(i32, i32)>,
    pub last_missile_options: Vec<Vec<(i32, i32)>>,
    pub rng_seed: u64,
    pub rng_counter: u64,
    pub avg_luck: bool,   // planning (2026-11-04): every roll is the CO's average luck, no randomness
}

pub struct IllegalAction(pub String);

impl Game {
    // ------------------------------------------------------------ construction
    #[allow(clippy::too_many_arguments)]
    pub fn new(
        kinds: Vec<Vec<u8>>, owners: Vec<Vec<i8>>, cos: [u8; 2], units: &[(usize, u8, i32, i32, i64)],
        starting_funds: i64, weather: u8, seed: u64, income_per_prop: i64, max_days: i64, unit_limit: i64,
        capture_limit: i64, first_turn_income: bool, countries: [i64; 2],
    ) -> Self {
        let h = kinds.len() as i32;
        let w = kinds[0].len() as i32;
        let flat_k: Vec<u8> = kinds.iter().flatten().copied().collect();
        let flat_o: Vec<i8> = owners.iter().flatten().copied().collect();
        let cp = flat_k.iter().map(|&k| if k == TK_SEAM { SEAM_HP } else { CP_MAX }).collect();
        let lab_hq = !flat_k.iter().any(|&k| k == TK_HQ);
        let mut lab_players = [false; 2];
        if lab_hq {
            for (k, o) in flat_k.iter().zip(flat_o.iter()) {
                if *k == TK_LAB && (*o == 0 || *o == 1) {
                    lab_players[*o as usize] = true;
                }
            }
        }
        let pl = |co: u8, c: i64| Player { co, country: c, funds: starting_funds, charge: 0, power: 0, uses: 0, had_units: false };
        let mut g = Game {
            w, h, kinds: flat_k, owners: flat_o, cp,
            players: [pl(cos[0], countries[0]), pl(cos[1], countries[1])],
            units: Vec::new(), index: IdMap::default(), pos: vec![NONE; (w * h) as usize], next_id: 1,
            default_weather: weather, weather, weather_expires: NONE, cur: 0, day: 1, income_per_prop,
            max_days, capture_limit, unit_limit, banned: 0, first_turn_income, done: false, winner: NONE, end_reason: "",
            lab_hq, lab_players, last_missiles: Vec::new(), last_missile_options: Vec::new(),
            rng_seed: seed, rng_counter: 0, avg_luck: false,
        };
        for &(p, t, x, y, hp) in units {
            g.spawn(p, t, x, y, hp, false);
        }
        g.start_turn(0, true);
        g
    }

    #[inline]
    pub fn idx(&self, x: i32, y: i32) -> usize {
        (y * self.w + x) as usize
    }

    fn spawn(&mut self, p: usize, t: u8, x: i32, y: i32, hp: i64, acted: bool) -> i64 {
        let id = self.next_id;
        self.next_id += 1;
        self.index.insert(id, self.units.len());
        self.units.push(Unit {
            id, owner: p, t, x, y, hp, fuel: UNIT_FUEL[t as usize], ammo: UNIT_AMMO[t as usize], acted, moved: false,
            hidden: false, stunned: false, loaded_in: NONE, cargo: Vec::new(),
        });
        let i = self.idx(x, y);
        self.pos[i] = id;
        self.players[p].had_units = true;
        id
    }

    // ------------------------------------------------------------ small queries
    #[inline]
    pub fn uidx(&self, id: i64) -> Option<usize> {
        self.index.get(&id).copied()
    }
    /// Rebuild the id index after units were removed from the middle of `units`.
    pub fn reindex(&mut self) {
        self.index.clear();
        for (i, u) in self.units.iter().enumerate() {
            self.index.insert(u.id, i);
        }
    }
    #[inline]
    fn u(&self, id: i64) -> &Unit {
        &self.units[self.uidx(id).expect("unit")]
    }
    #[inline]
    fn um(&mut self, id: i64) -> &mut Unit {
        let i = self.uidx(id).expect("unit");
        &mut self.units[i]
    }
    fn uv(&self, id: i64) -> UV {
        let u = self.u(id);
        UV { owner: u.owner, t: u.t, x: u.x, y: u.y, hp: u.hp }
    }
    pub fn co(&self, p: usize) -> u8 {
        self.players[p].co
    }
    pub fn lvl(&self, p: usize) -> u8 {
        self.players[p].power
    }
    #[inline]
    pub fn kind_at(&self, x: i32, y: i32) -> u8 {
        self.kinds[self.idx(x, y)]
    }
    #[inline]
    fn in_bounds(&self, x: i32, y: i32) -> bool {
        x >= 0 && x < self.w && y >= 0 && y < self.h
    }
    #[inline]
    pub fn unit_at(&self, x: i32, y: i32) -> Option<i64> {
        let id = self.pos[self.idx(x, y)];
        if id == NONE { None } else { Some(id) }
    }
    fn my_count(&self, p: usize) -> usize {
        self.units.iter().filter(|u| u.owner == p).count()
    }
    fn count_owned(&self, p: usize, pred: impl Fn(u8) -> bool) -> i64 {
        let mut n = 0;
        for i in 0..self.kinds.len() {
            if self.owners[i] == p as i8 && pred(self.kinds[i]) {
                n += 1;
            }
        }
        n
    }
    pub fn count_income_props(&self, p: usize) -> i64 {
        self.count_owned(p, |k| IS_INCOME[k as usize])
    }
    fn towers(&self, p: usize) -> i64 {
        self.count_owned(p, |k| k == TK_COMTOWER)
    }
    fn stars_of(&self, u: &UV) -> i64 {
        if IS_AIR[u.t as usize] {
            return 0;
        }
        STARS[self.kind_at(u.x, u.y) as usize]
    }
    pub fn unit_cost(&self, p: usize, t: u8) -> i64 {
        UNIT_COST[t as usize] * CO_COST_PCT[self.co(p) as usize][self.lvl(p) as usize] / 100
    }
    fn star_value(&self, p: usize) -> i64 {
        STAR_BASE + STAR_STEP * self.players[p].uses.min(MAX_STAR_USES)
    }
    pub fn power_cost(&self, p: usize, lvl: u8) -> i64 {
        let co = self.co(p) as usize;
        let stars = if lvl == 1 { CO_COP_STARS[co] } else { CO_SCOP_STARS[co] };
        stars * self.star_value(p)
    }
    pub fn max_charge(&self, p: usize) -> i64 {
        CO_SCOP_STARS[self.co(p) as usize] * self.star_value(p)
    }

    // ------------------------------------------------------------ CO abilities (awbw/cos.py)
    fn co_atk(&self, p: usize, a: &UV, lvl: u8) -> i64 {
        let t = a.t;
        let tu = t as usize;
        match self.co(p) {
            CO_ANDY => if lvl == 2 { 110 } else { 100 },
            CO_JAKE => 100 + if matches!(self.kind_at(a.x, a.y), TK_PLAIN | TK_RUBBLE) { pick(lvl, (10, 20, 40)) } else { 0 },
            CO_MAX => {
                if IS_FOOT[tu] { 100 } else if is_direct(t) { pick(lvl, (120, 130, 150)) } else if is_indirect(t) { 90 } else { 100 }
            }
            CO_SAMI => if IS_FOOT[tu] { pick(lvl, (130, 150, 170)) } else if is_direct(t) { 90 } else { 100 },
            CO_COLIN => 90 + if lvl == 2 { fdiv(3 * self.players[p].funds, 1000) } else { 0 },
            CO_GRIT => {
                if is_indirect(t) { pick(lvl, (120, 140, 140)) } else if IS_FOOT[tu] { 100 } else if is_direct(t) { 80 } else { 100 }
            }
            CO_DRAKE => if IS_AIR[tu] { 70 } else { 100 },
            CO_EAGLE => if IS_AIR[tu] { pick(lvl, (115, 120, 120)) } else if IS_NAVAL[tu] { 70 } else { 100 },
            CO_JAVIER => 100 + self.towers(p) * pick(lvl, (0, 10, 20)),
            CO_JESS => if IS_VEHICLE[tu] { pick(lvl, (110, 120, 140)) } else { 90 },
            CO_GRIMM => pick(lvl, (130, 150, 180)),
            CO_KANBEI => pick(lvl, (130, 140, 140)),
            CO_SENSEI => {
                if t == UT_BCOPTER { pick(lvl, (150, 165, 165)) } else if IS_FOOT[tu] { 140 } else if IS_AIR[tu] { 100 } else { 90 }
            }
            CO_HAWKE => 110,
            CO_KINDLE => {
                let mut v = 100;
                if IS_URBAN[self.kind_at(a.x, a.y) as usize] {
                    v += pick(lvl, (40, 80, 130));
                }
                if lvl == 2 {
                    v += 3 * self.count_owned(p, |k| IS_URBAN[k as usize]);
                }
                v
            }
            CO_KOAL => 100 + if self.kind_at(a.x, a.y) == TK_ROAD { pick(lvl, (10, 20, 30)) } else { 0 },
            CO_LASH => if IS_AIR[tu] { 100 } else { 100 + 10 * self.stars_of(a) * if lvl == 2 { 2 } else { 1 } },
            CO_STURM => 80,
            CO_VON_BOLT => 110,
            _ => 100,
        }
    }

    fn co_dfn(&self, p: usize, d: &UV, a: &UV, lvl: u8) -> i64 {
        let td = d.t as usize;
        match self.co(p) {
            CO_DRAKE => if IS_NAVAL[td] { 110 } else { 100 },
            CO_EAGLE => if IS_AIR[td] { pick(lvl, (110, 120, 120)) } else { 100 },
            CO_JAVIER => {
                let mut v = 100;
                if is_indirect(a.t) {
                    v += pick(lvl, (20, 40, 80));
                }
                v + self.towers(p) * pick(lvl, (10, 20, 30))
            }
            CO_GRIMM => 80,
            CO_KANBEI => pick(lvl, (130, 130, 150)),
            CO_STURM => 120,
            CO_VON_BOLT => 110,
            _ => 100,
        }
    }

    fn co_counter_boost(&self, p: usize, lvl: u8) -> bool {
        match self.co(p) {
            CO_KANBEI => lvl == 2,
            CO_SONJA => lvl < 2,
            _ => false,
        }
    }

    fn co_star_mult(&self, p: usize, lvl: u8) -> i64 {
        if self.co(p) == CO_LASH && lvl == 2 { 2 } else { 1 }
    }

    fn co_move_bonus(&self, p: usize, t: u8, lvl: u8) -> i64 {
        let tu = t as usize;
        let l = lvl as i64;
        match self.co(p) {
            CO_ANDY => if lvl == 2 { 1 } else { 0 },
            CO_JAKE => if lvl == 2 && IS_VEHICLE[tu] { 2 } else { 0 },
            CO_MAX => if is_direct(t) && !IS_FOOT[tu] { l } else { 0 },
            CO_SAMI => (if IS_FOOT[tu] { l } else { 0 }) + if IS_TRANSPORT[tu] { 1 } else { 0 },
            CO_DRAKE => if IS_NAVAL[tu] { 1 } else { 0 },
            CO_JESS => if IS_VEHICLE[tu] { l } else { 0 },
            CO_SENSEI => if IS_TRANSPORT[tu] { 1 } else { 0 },
            CO_ADDER | CO_KOAL => l,
            _ => 0,
        }
    }

    fn co_range_bonus(&self, p: usize, t: u8, lvl: u8) -> i64 {
        match self.co(p) {
            CO_JAKE => if lvl >= 1 && IS_LAND_INDIRECT[t as usize] { 1 } else { 0 },
            CO_MAX => if is_indirect(t) { -1 } else { 0 },
            CO_GRIT => {
                // AWBW (GL replays): +1 day to day, +2 with COP, +3 with SCOP (the power ranges stack)
                if !is_indirect(t) { 0 } else { 1 + lvl as i64 }
            }
            _ => 0,
        }
    }

    fn co_income_bonus(&self, p: usize) -> i64 {
        if self.co(p) == CO_SASHA { 100 * self.count_income_props(p) } else { 0 }
    }

    fn co_effective_weather(&self, p: usize, w: u8) -> u8 {
        match self.co(p) {
            CO_OLAF => match w {
                W_SNOW => W_CLEAR,
                W_RAIN => W_SNOW,
                _ => W_CLEAR,
            },
            CO_DRAKE => if w == W_RAIN { W_CLEAR } else { w },
            _ => w,
        }
    }

    fn co_capture_pct(&self, p: usize) -> i64 {
        if self.co(p) == CO_SAMI { 150 } else { 100 }
    }

    fn co_instant_capture(&self, p: usize, lvl: u8) -> bool {
        self.co(p) == CO_SAMI && lvl == 2
    }

    fn co_fuel_delta(&self, p: usize, t: u8) -> i64 {
        if self.co(p) == CO_EAGLE && IS_AIR[t as usize] { -2 } else { 0 }
    }

    fn co_sees_hidden(&self, p: usize, lvl: u8) -> bool {
        self.co(p) == CO_SONJA && lvl >= 1
    }

    fn co_luck(&self, p: usize) -> (i64, i64) {
        CO_LUCK[self.co(p) as usize][self.lvl(p) as usize]
    }

    fn on_power(&mut self, p: usize, lvl: u8) {
        let l = lvl as i64;
        match self.co(p) {
            CO_ANDY => self.heal_all(p, if lvl == 1 { 20 } else { 50 }),
            CO_RACHEL => {
                if lvl == 2 {
                    self.rachel_missiles(p)
                }
            }
            CO_COLIN => {
                if lvl == 1 {
                    self.players[p].funds = fdiv(self.players[p].funds * 3, 2)
                }
            }
            CO_OLAF => {
                self.set_weather(W_SNOW, p);
                if lvl == 2 {
                    self.damage_enemies(p, 20, false, false);
                }
            }
            CO_SASHA => {
                if lvl == 1 {
                    self.market_crash(p)
                }
            }
            CO_DRAKE => {
                self.damage_enemies(p, 10 * l, true, false);
                if lvl == 2 {
                    self.set_weather(W_RAIN, p);
                }
            }
            CO_EAGLE => {
                if lvl == 2 {
                    self.refresh_non_foot(p)
                }
            }
            CO_JESS => self.resupply_all(p),
            CO_SENSEI => self.sensei_spawn(p, if lvl == 1 { UT_INF } else { UT_MECH }),
            CO_HAWKE => {
                self.heal_all(p, 10 * l);
                self.damage_enemies(p, 10 * l, false, false);
            }
            CO_KINDLE => {
                if lvl == 1 {
                    self.damage_enemies(p, 30, false, true)
                }
            }
            CO_STURM => self.sturm_missile(p, if lvl == 1 { 40 } else { 80 }),
            CO_VON_BOLT => self.von_bolt_missile(p),
            _ => {}
        }
    }

    // ------------------------------------------------------------ movement
    pub fn move_points(&self, id: i64) -> i64 {
        let u = self.u(id);
        (UNIT_MP[u.t as usize] + self.co_move_bonus(u.owner, u.t, self.lvl(u.owner))).max(0)
    }

    pub fn tile_cost(&self, owner: usize, t: u8, x: i32, y: i32) -> i64 {
        let lv = self.lvl(owner);
        let w = self.co_effective_weather(owner, self.weather);
        let c = MOVE_COST[w as usize][self.kind_at(x, y) as usize][UNIT_MT[t as usize] as usize];
        if c < 0 {
            return -1;
        }
        if CO_FLAT_MOVE[self.co(owner) as usize][lv as usize] && w != W_SNOW {
            return 1;
        }
        c
    }

    fn can_carry(&self, transport: i64, u: i64) -> bool {
        let tr = self.u(transport);
        let un = self.u(u);
        let tt = tr.t as usize;
        CARRY_CAP[tt] > 0 && CARRIES[tt][un.t as usize] && tr.cargo.len() < CARRY_CAP[tt] && tr.owner == un.owner && tr.id != un.id
    }

    /// (tiles in discovery order, cost per tile or -1): tiles the unit may stop on or pass through.
    pub fn reachable(&self, id: i64) -> (Vec<(i32, i32)>, Vec<i64>) {
        let u = self.u(id);
        let (owner, t) = (u.owner, u.t);
        let limit = self.move_points(id).min(u.fuel);
        let n = (self.w * self.h) as usize;
        let mut dist = vec![i64::MAX; n];
        let mut order = Vec::new();
        let s = self.idx(u.x, u.y);
        dist[s] = 0;
        order.push((u.x, u.y));
        let mut heap = BinaryHeap::new();
        heap.push(Reverse((0i64, u.x, u.y)));
        while let Some(Reverse((d0, x, y))) = heap.pop() {
            let i = self.idx(x, y);
            if d0 > dist[i] {
                continue;
            }
            for (dx, dy) in NEIGH {
                let (nx, ny) = (x + dx, y + dy);
                if !self.in_bounds(nx, ny) {
                    continue;
                }
                let ni = self.idx(nx, ny);
                let c = self.tile_cost(owner, t, nx, ny);
                // a friendly transport is boarded only where the cargo could stand (AWBW: Landers load at shoals/ports)
                if let Some(occ) = self.unit_at(nx, ny) {
                    if self.u(occ).owner != owner {
                        continue;
                    }
                }
                if c < 0 {
                    continue;
                }
                let nd = d0 + c;
                if nd > limit || nd >= dist[ni] {
                    continue;
                }
                if dist[ni] == i64::MAX {
                    order.push((nx, ny));
                }
                dist[ni] = nd;
                heap.push(Reverse((nd, nx, ny)));
            }
        }
        let costs = order.iter().map(|&(x, y)| dist[self.idx(x, y)]).collect();
        (order, costs)
    }

    // ------------------------------------------------------------ combat math
    fn atk_pct(&self, a: &UV) -> i64 {
        let p = a.owner;
        let lv = self.lvl(p);
        let mut v = self.co_atk(p, a, lv);
        if lv > 0 {
            v += 10;
        }
        v + 10 * self.towers(p)
    }

    fn def_pct(&self, d: &UV, a: &UV) -> i64 {
        let p = d.owner;
        let lv = self.lvl(p);
        let mut v = self.co_dfn(p, d, a, lv);
        if lv > 0 {
            v += 10;
        }
        v
    }

    fn roll_luck(&mut self, p: usize) -> i64 {
        let (pos, neg) = self.co_luck(p);
        if self.avg_luck {
            return (pos - neg) / 2;
        }
        let x = splitmix(self.rng_seed.wrapping_add(self.rng_counter));
        self.rng_counter += 1;
        let mut r = (x % (pos as u64 + 1)) as i64;
        if neg > 0 {
            r -= ((x >> 32) % (neg as u64 + 1)) as i64;
        }
        r
    }

    /// (base damage, uses ammo) of the weapon `at` fights `dt` with: the main chart's weapon while it has ammo for it
    /// (or needs none), else the machine gun (MG_DMG) if it has one. Mirrors data.weapon.
    fn weapon(at: u8, dt: u8, ammo: i64) -> (i64, bool) {
        let (a, d) = (at as usize, dt as usize);
        if DMG[a][d] > 0 && (ammo > 0 || !USES_AMMO[a][d]) {
            (DMG[a][d], USES_AMMO[a][d])
        } else {
            (MG_DMG[a][d], false)
        }
    }

    fn damage_calc(&self, a: &UV, d: &UV, b: i64, luck: i64, counter: bool) -> i64 {
        if b == 0 {
            return 0;
        }
        let aco = self.atk_pct(a);
        let dco = self.def_pct(d, a);
        let dtr = self.stars_of(d) * self.co_star_mult(d.owner, self.lvl(d.owner));
        let mut num = (b * aco + 100 * luck) * disp(a.hp) * (200 - (dco + dtr * disp(d.hp)));
        let mut den = 100 * 10 * 100;
        if counter && self.co_counter_boost(a.owner, self.lvl(a.owner)) {
            num *= 3;
            den *= 2;
        }
        if num <= 0 {
            return 0;
        }
        fdiv(-fdiv(-20 * num, den), 20)
    }

    fn attack_range(&self, owner: usize, t: u8) -> (i64, i64) {
        let rmax = UNIT_RMAX[t as usize];
        let rmin = UNIT_RMIN[t as usize];
        if rmax == 0 {
            return (0, 0);
        }
        let bonus = if rmax > 1 { self.co_range_bonus(owner, t, self.lvl(owner)) } else { 0 };
        (rmin, rmin.max(rmax + bonus))
    }

    fn can_hit(&self, at: u8, ammo: i64, dt: u8) -> bool {
        Self::weapon(at, dt, ammo).0 > 0
    }

    fn visible_to(&self, p: usize, tid: i64) -> bool {
        let t = self.u(tid);
        if !t.hidden {
            return true;
        }
        if self.co_sees_hidden(p, self.lvl(p)) {
            return true;
        }
        for (dx, dy) in NEIGH {
            let (x, y) = (t.x + dx, t.y + dy);
            if self.in_bounds(x, y) {
                if let Some(o) = self.unit_at(x, y) {
                    if self.u(o).owner == p {
                        return true;
                    }
                }
            }
        }
        false
    }

    fn attack_targets(&self, id: i64, x: i32, y: i32, moved: bool, out: &mut Vec<(i32, i32)>) {
        let u = self.u(id);
        let (rmin, rmax) = self.attack_range(u.owner, u.t);
        if rmax == 0 || (rmin > 1 && moved) {
            return;
        }
        let r = rmax as i32;
        for ty in (y - r).max(0)..(y + r + 1).min(self.h) {
            for tx in (x - r).max(0)..(x + r + 1).min(self.w) {
                let dd = ((tx - x).abs() + (ty - y).abs()) as i64;
                if dd < rmin || dd > rmax {
                    continue;
                }
                match self.unit_at(tx, ty) {
                    None => {
                        if self.kind_at(tx, ty) == TK_SEAM
                            && Self::weapon(u.t, UT_NEO, u.ammo).0 > 0
                        {
                            out.push((tx, ty));
                        }
                    }
                    Some(tid) => {
                        let t = self.u(tid);
                        if t.owner == u.owner || t.loaded_in != NONE {
                            continue;
                        }
                        if self.can_hit(u.t, u.ammo, t.t) && self.visible_to(u.owner, tid) {
                            out.push((tx, ty));
                        }
                    }
                }
            }
        }
    }

    /// Tactical planes for the observation (2026-11-17), each u8[w * h], from the mover's view:
    ///   0 enemy units able to attack the tile on their next turn (count, max 15)
    ///   1 damage % those would deal in total to MY unit standing on the tile (max 250)
    ///   2 damage % they would deal in total to the SELECTED unit if it stood on the tile (max 250; 0 without one)
    ///   3 my units that have not acted and can attack the tile this turn (count, max 15)
    ///   4 damage % those would deal in total to the ENEMY unit standing on the tile (max 250)
    /// Reach = the engine's own movement (terrain, fuel, blocking as the board stands) + weapon range; indirects fire
    /// from where they stand. Damage = base chart, attacker HP, COs, terrain of the tile, no luck.
    pub fn threat_planes(&self, sel: (i32, i32)) -> [Vec<u8>; 5] {
        let n = (self.w * self.h) as usize;
        let mut acc = [vec![0i64; n], vec![0i64; n], vec![0i64; n], vec![0i64; n], vec![0i64; n]];
        let me = self.cur;
        let selected = if self.in_bounds(sel.0, sel.1) {
            self.unit_at(sel.0, sel.1).map(|id| self.uv(id)).filter(|u| u.owner == me)
        } else {
            None
        };
        let mut hit = vec![false; n];
        for u in &self.units {
            if u.loaded_in != NONE || u.stunned || (u.owner == me && u.acted) {
                continue;
            }
            let (rmin, rmax) = self.attack_range(u.owner, u.t);
            if rmax == 0 {
                continue;
            }
            hit.iter_mut().for_each(|h| *h = false);
            if rmin > 1 {
                let r = rmax as i32;
                for ty in (u.y - r).max(0)..(u.y + r + 1).min(self.h) {
                    for tx in (u.x - r).max(0)..(u.x + r + 1).min(self.w) {
                        let dd = ((tx - u.x).abs() + (ty - u.y).abs()) as i64;
                        if dd >= rmin && dd <= rmax {
                            hit[self.idx(tx, ty)] = true;
                        }
                    }
                }
            } else {
                let (tiles, _) = self.reachable(u.id);
                for (x, y) in tiles {
                    if let Some(o) = self.unit_at(x, y) {
                        if o != u.id {
                            continue; // may pass through a friend, not stop there
                        }
                    }
                    for (dx, dy) in NEIGH {
                        if self.in_bounds(x + dx, y + dy) {
                            hit[self.idx(x + dx, y + dy)] = true;
                        }
                    }
                }
            }
            let a = UV { owner: u.owner, t: u.t, x: u.x, y: u.y, hp: u.hp };
            let (cnt, dmg) = if u.owner == me { (3, 4) } else { (0, 1) };
            for i in 0..n {
                if !hit[i] {
                    continue;
                }
                acc[cnt][i] += 1;
                let (x, y) = ((i as i32) % self.w, (i as i32) / self.w);
                if self.pos[i] != NONE {
                    let d = self.uv(self.pos[i]);
                    if d.owner != u.owner {
                        let b = Self::weapon(u.t, d.t, u.ammo).0;
                        acc[dmg][i] += self.damage_calc(&a, &d, b, 0, false);
                    }
                }
                if u.owner != me {
                    if let Some(s) = selected {
                        let b = Self::weapon(u.t, s.t, u.ammo).0;
                        let d = UV { owner: me, t: s.t, x, y, hp: s.hp };
                        acc[2][i] += self.damage_calc(&a, &d, b, 0, false);
                    }
                }
            }
        }
        let cl = |v: &Vec<i64>, m: i64| v.iter().map(|&x| x.clamp(0, m) as u8).collect::<Vec<u8>>();
        [cl(&acc[0], 15), cl(&acc[1], 250), cl(&acc[2], 250), cl(&acc[3], 15), cl(&acc[4], 250)]
    }

    /// Route planes (2026-11-17, user: the net walks infantry toward a com tower across the sea and a tank into a
    /// mountain dead end; a stack of 3x3 convolutions cannot see multi-turn paths, KataGo ladder-style input instead).
    /// For the selected own unit, terrain-only path costs (other units ignored: they move), value = cost + 1 capped at
    /// 254, 0 = never reachable / no unit selected:
    ///   [0] from the unit to every tile;
    ///   [1] from every tile to the nearest tile from which it can fire at an enemy it can damage;
    ///   [2] (foot units only) from every tile to the nearest capturable property not owned by its side.
    pub fn route_planes(&self, sel: (i32, i32)) -> [Vec<u8>; 3] {
        let n = (self.w * self.h) as usize;
        let mut out = [vec![0u8; n], vec![0u8; n], vec![0u8; n]];
        let s = if self.in_bounds(sel.0, sel.1) {
            self.unit_at(sel.0, sel.1).map(|id| self.uv(id)).filter(|u| u.owner == self.cur)
        } else {
            None
        };
        let Some(s) = s else { return out };
        // an intact pipe seam is not a wall forever (user 2026-11-17): it can be broken. A ground unit "passes" it at the
        // cost of a broken seam (plain) plus one turn of its movement per ~35 seam HP it takes to break it
        let mp = (UNIT_MP[s.t as usize]).max(1);
        let cost = |i: usize| {
            let (x, y) = ((i as i32) % self.w, (i as i32) / self.w);
            let c = self.tile_cost(s.owner, s.t, x, y);
            if c < 0 && self.kinds[i] == TK_SEAM {
                let plain = MOVE_COST[self.weather as usize][TK_PLAIN as usize][UNIT_MT[s.t as usize] as usize];
                if plain >= 0 {
                    let hits = (self.cp[i].max(1) + 34) / 35;
                    return plain + hits * mp;
                }
            }
            c
        };
        let costs: Vec<i64> = (0..n).map(cost).collect();
        // forward: entering a tile costs that tile
        let fwd = |src: &[usize]| -> Vec<i64> {
            let mut d = vec![i64::MAX; n];
            let mut heap = BinaryHeap::new();
            for &i in src {
                d[i] = 0;
                heap.push(Reverse((0i64, i)));
            }
            while let Some(Reverse((d0, i))) = heap.pop() {
                if d0 > d[i] {
                    continue;
                }
                let (x, y) = ((i as i32) % self.w, (i as i32) / self.w);
                for (dx, dy) in NEIGH {
                    if !self.in_bounds(x + dx, y + dy) {
                        continue;
                    }
                    let j = self.idx(x + dx, y + dy);
                    if costs[j] < 0 || d0 + costs[j] >= d[j] {
                        continue;
                    }
                    d[j] = d0 + costs[j];
                    heap.push(Reverse((d[j], j)));
                }
            }
            d
        };
        // backward (tile -> goals): stepping from j onto i costs costs[i]; goals must be standable
        let back = |goals: &[usize]| -> Vec<i64> {
            let mut d = vec![i64::MAX; n];
            let mut heap = BinaryHeap::new();
            for &i in goals {
                if costs[i] >= 0 {
                    d[i] = 0;
                    heap.push(Reverse((0i64, i)));
                }
            }
            while let Some(Reverse((d0, i))) = heap.pop() {
                if d0 > d[i] {
                    continue;
                }
                let (x, y) = ((i as i32) % self.w, (i as i32) / self.w);
                for (dx, dy) in NEIGH {
                    if !self.in_bounds(x + dx, y + dy) {
                        continue;
                    }
                    let j = self.idx(x + dx, y + dy);
                    if costs[j] < 0 || d0 + costs[i] >= d[j] {
                        continue;
                    }
                    d[j] = d0 + costs[i];
                    heap.push(Reverse((d[j], j)));
                }
            }
            d
        };
        let enc = |d: &Vec<i64>| d.iter().map(|&v| if v == i64::MAX { 0 } else { (v + 1).min(254) as u8 }).collect::<Vec<u8>>();
        out[0] = enc(&fwd(&[self.idx(s.x, s.y)]));
        let (rmin, rmax) = self.attack_range(s.owner, s.t);
        if rmax > 0 {
            let ammo = self.unit_at(s.x, s.y).map(|id| self.u(id).ammo).unwrap_or(0);
            let mut goal = vec![false; n];
            for e in &self.units {
                if e.owner == s.owner || e.loaded_in != NONE || !self.can_hit(s.t, ammo, e.t) {
                    continue;
                }
                let r = rmax as i32;
                for ty in (e.y - r).max(0)..(e.y + r + 1).min(self.h) {
                    for tx in (e.x - r).max(0)..(e.x + r + 1).min(self.w) {
                        let dd = ((tx - e.x).abs() + (ty - e.y).abs()) as i64;
                        if dd >= rmin && dd <= rmax {
                            goal[self.idx(tx, ty)] = true;
                        }
                    }
                }
            }
            let g: Vec<usize> = (0..n).filter(|&i| goal[i]).collect();
            out[1] = enc(&back(&g));
        }
        if IS_FOOT[s.t as usize] {
            let g: Vec<usize> = (0..n).filter(|&i| IS_CAPTURABLE[self.kinds[i] as usize] && self.owners[i] != s.owner as i8).collect();
            out[2] = enc(&back(&g));
        }
        out
    }

    // ------------------------------------------------------------ power charge
    fn add_charge(&mut self, p: usize, pts: i64) {
        if self.players[p].power == 0 && pts > 0 {
            let m = self.max_charge(p);
            self.players[p].charge = (self.players[p].charge + pts).min(m);
        }
    }

    fn after_damage(&mut self, victim_owner: usize, victim_type: u8, lost: i64, attacker_owner: usize) {
        if lost <= 0 {
            return;
        }
        let value = fdiv(self.unit_cost(victim_owner, victim_type) * lost, 100);
        self.add_charge(victim_owner, value);
        self.add_charge(attacker_owner, fdiv(value, 2));
        if self.co(attacker_owner) == CO_SASHA && self.lvl(attacker_owner) == 2 {
            self.players[attacker_owner].funds += fdiv(value, 2);
        }
    }

    // ------------------------------------------------------------ removing / hitting
    pub fn remove(&mut self, id: i64) {
        let cargo = self.u(id).cargo.clone();
        for cid in cargo {
            if self.uidx(cid).is_some() {
                self.remove(cid);
            }
        }
        let u = self.u(id).clone();
        if u.loaded_in == NONE {
            let i = self.idx(u.x, u.y);
            if self.pos[i] == id {
                self.pos[i] = NONE;
            }
            if self.cp[i] < CP_MAX && IS_FOOT[u.t as usize] {
                self.cp[i] = CP_MAX;
            }
        } else if let Some(ti) = self.uidx(u.loaded_in) {
            self.units[ti].cargo.retain(|&c| c != id);
        }
        let ui = self.uidx(id).unwrap();
        self.units.remove(ui);
        self.reindex();
    }

    fn hit(&mut self, a_owner: usize, vid: i64, dmg: i64) -> bool {
        let (before, owner, t) = {
            let v = self.u(vid);
            (v.hp, v.owner, v.t)
        };
        let after = (before - dmg).max(0);
        self.um(vid).hp = after;
        self.after_damage(owner, t, (disp(before) - disp(after)) * 10, a_owner);
        if after == 0 {
            self.remove(vid);
            return true;
        }
        false
    }

    fn can_counter(&self, did: i64, aid: i64) -> bool {
        let d = self.u(did);
        let (rmin, rmax) = self.attack_range(d.owner, d.t);
        rmax == 1 && rmin == 1 && self.can_hit(d.t, d.ammo, self.u(aid).t)
    }

    fn do_attack(&mut self, aid: i64, did: i64) {
        let at = self.u(aid).t;
        let dt = self.u(did).t;
        let d_owner = self.u(did).owner;
        let a_owner = self.u(aid).owner;
        let direct = UNIT_RMAX[at as usize] == 1;
        let counter_first = self.co(d_owner) == CO_SONJA && self.lvl(d_owner) == 2 && direct && self.can_counter(did, aid);
        if counter_first {
            let luck = self.roll_luck(d_owner);
            let (b, uses) = Self::weapon(dt, at, self.u(did).ammo);
            let cd = self.damage_calc(&self.uv(did), &self.uv(aid), b, luck, true);
            if uses {
                self.um(did).ammo -= 1;
            }
            if self.hit(d_owner, aid, cd) {
                return;
            }
            let luck = self.roll_luck(a_owner);
            let (b, uses) = Self::weapon(at, dt, self.u(aid).ammo);
            let dmg = self.damage_calc(&self.uv(aid), &self.uv(did), b, luck, false);
            if uses {
                self.um(aid).ammo -= 1;
            }
            self.hit(a_owner, did, dmg);
            return;
        }
        let luck = self.roll_luck(a_owner);
        let (b, uses) = Self::weapon(at, dt, self.u(aid).ammo);
        let dmg = self.damage_calc(&self.uv(aid), &self.uv(did), b, luck, false);
        if uses {
            self.um(aid).ammo -= 1;
        }
        if self.hit(a_owner, did, dmg) {
            return;
        }
        if direct && self.can_counter(did, aid) {
            let luck = self.roll_luck(d_owner);
            let (b, uses) = Self::weapon(dt, at, self.u(did).ammo);
            let cd = self.damage_calc(&self.uv(did), &self.uv(aid), b, luck, true);
            if uses {
                self.um(did).ammo -= 1;
            }
            self.hit(d_owner, aid, cd);
        }
    }

    /// Expected funds value of an attack action for the attacker: damage dealt minus the counter taken, both at
    /// mid luck, the attacker standing on its destination (2026-11-04, tactical play-outs). Ignores Sonja's
    /// counter-first and pipe seams (0).
    pub fn attack_gain(&self, a: &Action) -> i64 {
        let did = match self.unit_at(a.tx, a.ty) {
            Some(d) if d != a.unit => d,
            _ => return 0,
        };
        let (au, du) = (self.u(a.unit), self.u(did));
        if au.owner == du.owner {
            return 0;
        }
        let mut av = self.uv(a.unit);
        av.x = a.dx;
        av.y = a.dy;
        let dv = self.uv(did);
        let (b, _) = Self::weapon(au.t, du.t, au.ammo);
        let luck = self.co_luck(au.owner).0 / 2;
        let dmg = self.damage_calc(&av, &dv, b, luck, false).clamp(0, du.hp);
        let dealt = UNIT_COST[du.t as usize] * dmg / 100;
        let mut taken = 0;
        if UNIT_RMAX[au.t as usize] == 1 && dmg < du.hp && self.can_counter(did, a.unit) {
            let mut dv2 = dv;
            dv2.hp -= dmg;
            let (b2, _) = Self::weapon(du.t, au.t, du.ammo);
            let luck2 = self.co_luck(du.owner).0 / 2;
            let cd = self.damage_calc(&dv2, &av, b2, luck2, true).clamp(0, au.hp);
            taken = UNIT_COST[au.t as usize] * cd / 100;
        }
        dealt - taken
    }

    fn attack_seam(&mut self, aid: i64, x: i32, y: i32) {
        let a = self.uv(aid);
        let dummy = UV { owner: a.owner, t: UT_NEO, x, y, hp: 100 };
        let _ = dummy;
        let (b, uses) = Self::weapon(a.t, UT_NEO, self.u(aid).ammo);
        let aco = self.atk_pct(&a);
        let lowest = -self.co_luck(a.owner).1;
        let num = (b * aco + 100 * lowest) * disp(a.hp) * 100;
        let dmg = if num > 0 { fdiv(-fdiv(-20 * num, 100000), 20) } else { 0 };
        if uses {
            self.um(aid).ammo -= 1;
        }
        let i = self.idx(x, y);
        self.cp[i] -= dmg;
        if self.cp[i] <= 0 {
            self.kinds[i] = TK_RUBBLE;
            self.cp[i] = CP_MAX;
        }
    }

    // ------------------------------------------------------------ action generation
    fn adjacent_friends_at(&self, id: i64, x: i32, y: i32) -> Vec<i64> {
        let owner = self.u(id).owner;
        let mut out = Vec::new();
        for (dx, dy) in NEIGH {
            let (nx, ny) = (x + dx, y + dy);
            if !self.in_bounds(nx, ny) {
                continue;
            }
            if let Some(o) = self.unit_at(nx, ny) {
                if o != id && self.u(o).owner == owner {
                    out.push(o);
                }
            }
        }
        out
    }

    fn unload_actions(&self, id: i64, dest: (i32, i32), acts: &mut Vec<Action>) {
        let u = self.u(id);
        for &cid in &u.cargo {
            let c = self.u(cid);
            if c.acted {
                continue; // AWBW refuses to drop cargo that boarded this turn (live game 1764106, 2026-11-15)
            }
            for (dx, dy) in NEIGH {
                let q = (dest.0 + dx, dest.1 + dy);
                if !self.in_bounds(q.0, q.1) {
                    continue;
                }
                let free = self.unit_at(q.0, q.1).is_none() || (q == (u.x, u.y) && dest != q);
                if free && self.tile_cost(c.owner, c.t, q.0, q.1) >= 0 {
                    acts.push(Action::target(AT_UNLOAD, id, dest, q, cid));
                }
            }
        }
    }

    pub fn unit_actions(&self, id: i64, acts: &mut Vec<Action>) {
        let u = self.u(id);
        if self.done || u.owner != self.cur || u.loaded_in != NONE {
            return;
        }
        if u.acted {
            self.unload_actions(id, (u.x, u.y), acts);
            return;
        }
        let (tiles, _) = self.reachable(id);
        let mut targets = Vec::new();
        for dest in tiles {
            if let Some(occ) = self.unit_at(dest.0, dest.1) {
                if occ != id {
                    let o = self.u(occ);
                    if self.can_carry(occ, id) {
                        acts.push(Action::unit(AT_LOAD, id, dest));
                    } else if o.t == u.t && o.hp < 100 && o.cargo.is_empty() && u.cargo.is_empty() {
                        acts.push(Action::unit(AT_JOIN, id, dest));
                    }
                    continue;
                }
            }
            let moved = dest != (u.x, u.y) || u.moved;
            acts.push(Action::unit(AT_WAIT, id, dest));
            targets.clear();
            self.attack_targets(id, dest.0, dest.1, moved, &mut targets);
            for &t in &targets {
                acts.push(Action::target(AT_ATTACK, id, dest, t, 0));
            }
            if IS_FOOT[u.t as usize] {
                let i = self.idx(dest.0, dest.1);
                let k = self.kinds[i];
                if IS_CAPTURABLE[k as usize] && self.owners[i] != u.owner as i8 {
                    acts.push(Action::unit(AT_CAPTURE, id, dest));
                }
                if k == TK_SILO {
                    for ty in 0..self.h {
                        for tx in 0..self.w {
                            acts.push(Action::target(AT_LAUNCH, id, dest, (tx, ty), 0));
                        }
                    }
                }
            }
            if u.t == UT_APC && !self.adjacent_friends_at(id, dest.0, dest.1).is_empty() {
                acts.push(Action::unit(AT_SUPPLY, id, dest));
            }
            if u.t == UT_BLACKBOAT {
                for o in self.adjacent_friends_at(id, dest.0, dest.1) {
                    let ou = self.u(o);
                    acts.push(Action::target(AT_REPAIR, id, dest, (ou.x, ou.y), 0));
                }
            }
            if u.t == UT_SUB || u.t == UT_STEALTH {
                acts.push(Action::unit(if u.hidden { AT_SURFACE } else { AT_DIVE }, id, dest));
            }
            if u.t == UT_BLACKBOMB {
                acts.push(Action::unit(AT_EXPLODE, id, dest));
            }
            self.unload_actions(id, dest, acts);
        }
    }

    pub fn build_actions(&self, acts: &mut Vec<Action>) {
        let p = self.cur;
        let funds = self.players[p].funds;
        if self.unit_limit >= 0 && self.my_count(p) as i64 >= self.unit_limit {
            return;
        }
        let lv = self.lvl(p);
        for y in 0..self.h {
            for x in 0..self.w {
                let i = self.idx(x, y);
                if self.owners[i] != p as i8 || self.pos[i] != NONE {
                    continue;
                }
                let k = self.kinds[i];
                let menu: &[u8] = match k {
                    TK_BASE => &BUILD_FACTORY,
                    TK_AIRPORT => &BUILD_AIRPORT,
                    TK_PORT => &BUILD_PORT,
                    TK_CITY if self.co(p) == CO_HACHI && lv == 2 => &BUILD_FACTORY,
                    _ => continue,
                };
                for &t in menu {
                    if self.unit_cost(p, t) <= funds && self.banned >> t & 1 == 0 {
                        acts.push(Action { t: AT_BUILD, unit: NONE, dx: x, dy: y, tx: -1, ty: -1, arg: t as i64 });
                    }
                }
            }
        }
    }

    fn power_actions(&self, acts: &mut Vec<Action>) {
        let p = self.cur;
        let pl = &self.players[p];
        if pl.power == 0 {
            let c1 = self.power_cost(p, 1);
            if CO_HAS_COP[self.co(p) as usize] && pl.charge >= c1 && c1 > 0 {
                acts.push(Action { arg: 1, ..Action::simple(AT_POWER) });
            }
            if pl.charge >= self.power_cost(p, 2) {
                acts.push(Action { arg: 2, ..Action::simple(AT_POWER) });
            }
        }
    }

    pub fn legal_actions(&self) -> Vec<Action> {
        let mut acts = Vec::new();
        if self.done {
            return acts;
        }
        let ids: Vec<i64> = self.units.iter().filter(|u| u.owner == self.cur).map(|u| u.id).collect();
        for id in ids {
            self.unit_actions(id, &mut acts);
        }
        self.build_actions(&mut acts);
        self.power_actions(&mut acts);
        acts.push(Action::simple(AT_END_TURN));
        acts
    }

    /// Units of the player to move that have something to do: not yet acted (they can always at least wait), or
    /// acted transports that can still drop cargo. Cheap: no movement search.
    pub fn actionable_units(&self) -> Vec<i64> {
        let mut out = Vec::new();
        if self.done {
            return out;
        }
        for u in &self.units {
            if u.owner != self.cur || u.loaded_in != NONE {
                continue;
            }
            if !u.acted {
                out.push(u.id);
            } else if !u.cargo.is_empty() {
                let mut tmp = Vec::new();
                self.unload_actions(u.id, (u.x, u.y), &mut tmp);
                if !tmp.is_empty() {
                    out.push(u.id);
                }
            }
        }
        out
    }

    /// Powers and End Turn (the actions that belong to no unit and no factory).
    pub fn global_actions(&self) -> Vec<Action> {
        let mut acts = Vec::new();
        if self.done {
            return acts;
        }
        self.power_actions(&mut acts);
        acts.push(Action::simple(AT_END_TURN));
        acts
    }

    /// Apply an action taken from legal_actions / unit_actions / build_actions / global_actions without
    /// re-checking it (step() re-generates the unit's moves to validate; this skips that).
    pub fn step_trusted(&mut self, a: Action) {
        if self.done {
            return;
        }
        match a.t {
            AT_END_TURN => self.end_turn(),
            AT_POWER => self.activate_power(a.arg as u8),
            AT_BUILD => {
                let p = self.cur;
                let t = a.arg as u8;
                self.players[p].funds -= self.unit_cost(p, t);
                self.spawn(p, t, a.dx, a.dy, 100, true);
            }
            AT_DELETE => self.remove(a.unit),
            _ => self.do_unit_action(a.unit, a),
        }
        self.check_end();
    }

    // ------------------------------------------------------------ step
    pub fn step(&mut self, a: Action) -> Result<(), IllegalAction> {
        if self.done {
            return Err(IllegalAction("game over".into()));
        }
        match a.t {
            AT_END_TURN => self.end_turn(),
            AT_POWER => {
                let mut ok = Vec::new();
                self.power_actions(&mut ok);
                if !ok.contains(&a) {
                    return Err(IllegalAction(format!("power not available: {:?}", a)));
                }
                self.activate_power(a.arg as u8);
            }
            AT_BUILD => {
                let mut ok = Vec::new();
                self.build_actions(&mut ok);
                if !ok.contains(&a) {
                    return Err(IllegalAction(format!("illegal build: {:?}", a)));
                }
                let p = self.cur;
                let t = a.arg as u8;
                self.players[p].funds -= self.unit_cost(p, t);
                self.spawn(p, t, a.dx, a.dy, 100, true);
            }
            AT_DELETE => {
                match self.uidx(a.unit) {
                    Some(i) if self.units[i].owner == self.cur => self.remove(a.unit),
                    _ => return Err(IllegalAction("bad delete".into())),
                }
            }
            _ => {
                if self.uidx(a.unit).is_none() {
                    return Err(IllegalAction(format!("illegal unit action: {:?}", a)));
                }
                let mut ok = Vec::new();
                self.unit_actions(a.unit, &mut ok);
                if !ok.contains(&a) {
                    return Err(IllegalAction(format!("illegal unit action: {:?}", a)));
                }
                self.do_unit_action(a.unit, a);
            }
        }
        self.check_end();
        Ok(())
    }

    /// Apply a unit action that is known to be legal (used by step after its check).
    pub fn do_unit_action(&mut self, id: i64, a: Action) {
        let dest = (a.dx, a.dy);
        let t = a.t;
        let (ux, uy) = {
            let u = self.u(id);
            (u.x, u.y)
        };
        if dest != (ux, uy) {
            let (tiles, costs) = self.reachable(id);
            let k = tiles.iter().position(|&q| q == dest).expect("reachable");
            self.relocate(id, dest, costs[k], t == AT_LOAD || t == AT_JOIN);
        }
        match t {
            AT_WAIT => self.um(id).acted = true,
            AT_ATTACK => {
                match self.unit_at(a.tx, a.ty) {
                    None => self.attack_seam(id, a.tx, a.ty),
                    Some(did) => self.do_attack(id, did),
                }
                if let Some(i) = self.uidx(id) {
                    self.units[i].acted = true;
                }
            }
            AT_CAPTURE => {
                self.capture(id);
                self.um(id).acted = true;
            }
            AT_LOAD => {
                let tr = self.pos[self.idx(dest.0, dest.1)];
                self.um(tr).cargo.push(id);
                let u = self.um(id);
                u.loaded_in = tr;
                u.acted = true;
            }
            AT_UNLOAD => {
                let cid = a.arg;
                self.um(id).cargo.retain(|&c| c != cid);
                {
                    let c = self.um(cid);
                    c.loaded_in = NONE;
                    c.x = a.tx;
                    c.y = a.ty;
                }
                let i = self.idx(a.tx, a.ty);
                self.pos[i] = cid;
                self.carry_along(cid, (a.tx, a.ty));
                {
                    let c = self.um(cid);
                    c.acted = true;
                    c.moved = true;
                }
                if self.u(id).moved {
                    self.um(id).acted = true;
                }
            }
            AT_JOIN => {
                let other = self.pos[self.idx(dest.0, dest.1)];
                self.join(id, other);
            }
            AT_SUPPLY => {
                let (x, y) = {
                    let u = self.u(id);
                    (u.x, u.y)
                };
                for o in self.adjacent_friends_at(id, x, y) {
                    let ou = self.um(o);
                    ou.fuel = UNIT_FUEL[ou.t as usize];
                    ou.ammo = UNIT_AMMO[ou.t as usize];
                }
                self.um(id).acted = true;
            }
            AT_REPAIR => {
                let p = self.u(id).owner;
                let o = self.unit_at(a.tx, a.ty).expect("repair target");
                let (ohp, ot) = {
                    let ou = self.u(o);
                    (ou.hp, ou.t)
                };
                if ohp < 100 {
                    let new = (ohp + 10).min(100);
                    let cost = fdiv(self.unit_cost(p, ot) * (disp(new) - disp(ohp)), 10);
                    if self.players[p].funds >= cost {
                        self.players[p].funds -= cost;
                        self.um(o).hp = new;
                    }
                }
                let ou = self.um(o);
                ou.fuel = UNIT_FUEL[ot as usize];
                ou.ammo = UNIT_AMMO[ot as usize];
                self.um(id).acted = true;
            }
            AT_DIVE => {
                let u = self.um(id);
                u.hidden = true;
                u.acted = true;
            }
            AT_SURFACE => {
                let u = self.um(id);
                u.hidden = false;
                u.acted = true;
            }
            AT_EXPLODE => self.explode(id),
            AT_LAUNCH => {
                self.launch(id, a.tx, a.ty);
                self.um(id).acted = true;
            }
            _ => {}
        }
    }

    fn carry_along(&mut self, id: i64, xy: (i32, i32)) {
        let cargo = self.u(id).cargo.clone();
        for cid in cargo {
            {
                let c = self.um(cid);
                c.x = xy.0;
                c.y = xy.1;
            }
            self.carry_along(cid, xy);
        }
    }

    fn relocate(&mut self, id: i64, dest: (i32, i32), cost: i64, boarding: bool) {
        let (x, y, t) = {
            let u = self.u(id);
            (u.x, u.y, u.t)
        };
        let i = self.idx(x, y);
        if self.cp[i] < CP_MAX && IS_FOOT[t as usize] {
            self.cp[i] = CP_MAX;
        }
        if self.pos[i] == id {
            self.pos[i] = NONE;
        }
        {
            let u = self.um(id);
            u.x = dest.0;
            u.y = dest.1;
        }
        if !boarding {
            let j = self.idx(dest.0, dest.1);
            self.pos[j] = id;
        }
        self.carry_along(id, dest);
        let u = self.um(id);
        u.fuel -= cost;
        u.moved = true;
    }

    fn capture(&mut self, id: i64) {
        let (x, y, p, hp) = {
            let u = self.u(id);
            (u.x, u.y, u.owner, u.hp)
        };
        let lv = self.lvl(p);
        let mut amount = fdiv(disp(hp) * self.co_capture_pct(p), 100);
        if self.co_instant_capture(p, lv) {
            amount = CP_MAX;
        }
        let i = self.idx(x, y);
        self.cp[i] -= amount;
        if self.cp[i] <= 0 {
            let prev = self.owners[i];
            self.owners[i] = p as i8;
            self.cp[i] = CP_MAX;
            let k = self.kinds[i];
            if k == TK_HQ {
                self.finish(p as i64, "hq");
            } else if k == TK_LAB && (prev == 0 || prev == 1) && self.lab_players[prev as usize]
                && self.count_owned(prev as usize, |k| k == TK_LAB) == 0
            {
                self.finish(p as i64, "labs");
            } else if self.capture_limit >= 0 && self.count_income_props(p) >= self.capture_limit {
                self.finish(p as i64, "capture_limit");
            }
        }
    }

    fn join(&mut self, id: i64, other: i64) {
        let (uhp, ufuel, uammo, uowner, ut) = {
            let u = self.u(id);
            (u.hp, u.fuel, u.ammo, u.owner, u.t)
        };
        let total = disp(uhp) + disp(self.u(other).hp);
        let excess = (total - 10).max(0);
        {
            let o = self.um(other);
            o.hp = total.min(10) * 10;
            o.fuel = UNIT_FUEL[o.t as usize].min(o.fuel + ufuel);
            o.ammo = UNIT_AMMO[o.t as usize].min(o.ammo + uammo);
            o.acted = true; // AWBW: joining ends the merged unit's turn, even if it had not acted yet
        }
        let refund = fdiv(self.unit_cost(uowner, ut) * excess, 10);
        self.players[uowner].funds += refund;
        let ui = self.uidx(id).unwrap();
        self.units.remove(ui);
        self.reindex();
    }

    fn explode(&mut self, id: i64) {
        let (cx, cy) = {
            let u = self.u(id);
            (u.x, u.y)
        };
        self.remove(id);
        for v in self.units.iter_mut() {
            if v.loaded_in == NONE && (v.x - cx).abs() + (v.y - cy).abs() <= 3 {
                v.hp = (v.hp - 50).max(1);
            }
        }
    }

    fn launch(&mut self, id: i64, tx: i32, ty: i32) {
        let (x, y) = {
            let u = self.u(id);
            (u.x, u.y)
        };
        let i = self.idx(x, y);
        self.kinds[i] = TK_SILO_EMPTY;
        for v in self.units.iter_mut() {
            if v.loaded_in == NONE && (v.x - tx).abs() + (v.y - ty).abs() <= 2 {
                v.hp = (v.hp - 30).max(1);
            }
        }
    }

    // ------------------------------------------------------------ CO power helpers
    fn set_weather(&mut self, w: u8, caster: usize) {
        self.weather = w;
        self.weather_expires = caster as i64;
    }

    fn damage_enemies(&mut self, p: usize, amt: i64, halve_fuel: bool, only_urban: bool) {
        for i in 0..self.units.len() {
            let (owner, x, y) = (self.units[i].owner, self.units[i].x, self.units[i].y);
            if owner == p {
                continue;
            }
            if only_urban && !IS_URBAN[self.kind_at(x, y) as usize] {
                continue;
            }
            let v = &mut self.units[i];
            v.hp = (v.hp - amt).max(1);
            if halve_fuel {
                v.fuel = fdiv(v.fuel, 2);
            }
        }
    }

    fn heal_all(&mut self, p: usize, amt: i64) {
        for v in self.units.iter_mut() {
            if v.owner == p {
                v.hp = (v.hp + amt).min(100);
            }
        }
    }

    fn resupply_all(&mut self, p: usize) {
        for v in self.units.iter_mut() {
            if v.owner == p {
                v.fuel = UNIT_FUEL[v.t as usize];
                v.ammo = UNIT_AMMO[v.t as usize];
            }
        }
    }

    fn refresh_non_foot(&mut self, p: usize) {
        for v in self.units.iter_mut() {
            if v.owner == p && v.loaded_in == NONE && !IS_FOOT[v.t as usize] {
                v.acted = false;
                v.moved = false;
            }
        }
    }

    fn sensei_spawn(&mut self, p: usize, ut: u8) {
        for y in 0..self.h {
            for x in 0..self.w {
                let i = self.idx(x, y);
                if self.kinds[i] == TK_CITY && self.owners[i] == p as i8 && self.pos[i] == NONE {
                    self.spawn(p, ut, x, y, 90, false);
                }
            }
        }
    }

    fn market_crash(&mut self, p: usize) {
        let funds = self.players[p].funds;
        let q = 1 - p;
        let drop = fdiv(self.max_charge(q) * funds, 50000);
        self.players[q].charge = (self.players[q].charge - drop).max(0);
    }

    /// score kinds: 0 = value of HP lost, 1 = foot soldiers' HP lost, 2 = HP lost
    fn missile_score(&self, enemy: usize, cx: i32, cy: i32, kind: u8, hp: i64) -> i64 {
        let mut total = 0;
        for v in &self.units {
            if v.owner == enemy && v.loaded_in == NONE && (v.x - cx).abs() + (v.y - cy).abs() <= 2 {
                let lost = hp.min(disp(v.hp) - 1);
                total += match kind {
                    0 => fdiv(UNIT_COST[v.t as usize] * lost, 10),
                    1 => if IS_FOOT[v.t as usize] { lost } else { 0 },
                    _ => lost,
                };
            }
        }
        total
    }

    fn best_center(&mut self, p: usize, kind: u8, hp: i64) -> Option<(i32, i32)> {
        let enemy = 1 - p;
        let mut best = 0;
        let mut bc = None;
        let mut tied = Vec::new();
        for y in 0..self.h {
            for x in 0..self.w {
                let s = self.missile_score(enemy, x, y, kind, hp);
                if s > best {
                    best = s;
                    bc = Some((x, y));
                    tied = vec![(x, y)];
                } else if s == best && s > 0 {
                    tied.push((x, y));
                }
            }
        }
        self.last_missile_options.push(tied);
        bc
    }

    fn blast(&mut self, p: usize, c: (i32, i32), dmg: i64, stun: bool) {
        self.last_missiles.push(c);
        for v in self.units.iter_mut() {
            if v.loaded_in == NONE && (v.x - c.0).abs() + (v.y - c.1).abs() <= 2 {
                v.hp = (v.hp - dmg).max(1);
                if stun && v.owner != p {
                    v.stunned = true; // the enemy skips its next turn
                } else if stun {
                    v.acted = true; // own units: only the rest of this turn (AWBW, 2026-11-17, game.py _blast)
                }
            }
        }
    }

    fn sturm_missile(&mut self, p: usize, dmg: i64) {
        if let Some(c) = self.best_center(p, 0, fdiv(dmg, 10)) {
            self.blast(p, c, dmg, false);
        }
    }

    fn von_bolt_missile(&mut self, p: usize) {
        if let Some(c) = self.best_center(p, 0, 3) {
            self.blast(p, c, 30, true);
        }
    }

    fn rachel_missiles(&mut self, p: usize) {
        for kind in [1u8, 0, 2] {
            if let Some(c) = self.best_center(p, kind, 3) {
                self.blast(p, c, 30, false);
            }
        }
    }

    // ------------------------------------------------------------ turn flow
    fn activate_power(&mut self, lvl: u8) {
        let p = self.cur;
        self.last_missiles.clear();
        self.last_missile_options.clear();
        let cost = self.power_cost(p, lvl);
        let pl = &mut self.players[p];
        pl.charge -= cost;
        pl.uses += 1;
        pl.power = lvl;
        self.on_power(p, lvl);
    }

    fn end_turn(&mut self) {
        self.cur = 1 - self.cur;
        if self.cur == 0 {
            self.day += 1;
            if self.max_days >= 0 && self.day > self.max_days {
                let a = self.count_owned(0, |k| IS_CAPTURABLE[k as usize]);
                let b = self.count_owned(1, |k| IS_CAPTURABLE[k as usize]);
                self.finish(if a > b { 0 } else if b > a { 1 } else { NONE }, "days");
                return;
            }
        }
        let c = self.cur;
        self.start_turn(c, false);
    }

    fn start_turn(&mut self, p: usize, first: bool) {
        self.players[p].power = 0;
        if self.weather_expires == p as i64 {
            self.weather = self.default_weather;
            self.weather_expires = NONE;
        }
        for u in self.units.iter_mut() {
            if u.owner == p {
                u.acted = false;
                u.moved = false;
                if u.stunned {
                    u.acted = true;
                    u.stunned = false;
                }
            }
        }
        if !(first && !self.first_turn_income) {
            let inc = self.income_per_prop * self.count_income_props(p) + self.co_income_bonus(p);
            self.players[p].funds += inc;
        }
        let co = self.co(p) as usize;
        for i in 0..self.units.len() {
            if self.units[i].owner != p || self.units[i].loaded_in != NONE {
                continue;
            }
            let (t, x, y, hidden, hp) = {
                let u = &self.units[i];
                (u.t, u.x, u.y, u.hidden, u.hp)
            };
            let tu = t as usize;
            let mut fpt = if hidden && UNIT_HIDDEN_FUEL[tu] != 0 { UNIT_HIDDEN_FUEL[tu] } else { UNIT_FUEL_PER_TURN[tu] };
            if fpt != 0 {
                fpt = (fpt + self.co_fuel_delta(p, t)).max(0);
            }
            if self.day > 1 {
                self.units[i].fuel -= fpt;
            }
            let ti = self.idx(x, y);
            let k = self.kinds[ti];
            let on_own = self.owners[ti] == p as i8;
            let mt = UNIT_MT[tu];
            let supports = on_own
                && ((matches!(k, TK_CITY | TK_BASE | TK_HQ) && matches!(mt, MT_F | MT_B | MT_T | MT_W | MT_P))
                    || (k == TK_AIRPORT && mt == MT_A)
                    || (k == TK_PORT && (mt == MT_S || mt == MT_L)));
            if supports {
                if hp < 100 {
                    let heal = (20 + CO_REPAIR_BONUS[co]).min(100 - hp);
                    let new = hp + heal;
                    let cost = fdiv(self.unit_cost(p, t) * (disp(new) - disp(hp)), 10);
                    if self.players[p].funds >= cost {
                        self.players[p].funds -= cost;
                        self.units[i].hp = new;
                    }
                }
                self.units[i].fuel = UNIT_FUEL[tu];
                self.units[i].ammo = UNIT_AMMO[tu];
            }
        }
        // APCs resupply adjacent friends at turn start, including the cargo of transports next to them
        let apcs: Vec<i64> = self.units.iter().filter(|u| u.owner == p && u.t == UT_APC && u.loaded_in == NONE).map(|u| u.id).collect();
        for apc in apcs {
            let (x, y) = {
                let u = self.u(apc);
                (u.x, u.y)
            };
            let mut todo = self.adjacent_friends_at(apc, x, y);
            while let Some(o) = todo.pop() {
                let ou = self.um(o);
                ou.fuel = UNIT_FUEL[ou.t as usize];
                ou.ammo = UNIT_AMMO[ou.t as usize];
                let cargo = ou.cargo.clone();
                todo.extend(cargo);
            }
        }
        let crashed: Vec<i64> = self
            .units
            .iter()
            .filter(|u| {
                if u.owner != p || u.loaded_in != NONE {
                    return false;
                }
                let tu = u.t as usize;
                let fpt = if u.hidden && UNIT_HIDDEN_FUEL[tu] != 0 { UNIT_HIDDEN_FUEL[tu] } else { UNIT_FUEL_PER_TURN[tu] };
                fpt != 0 && u.fuel <= 0
            })
            .map(|u| u.id)
            .collect();
        for id in crashed {
            if self.uidx(id).is_some() {
                self.remove(id);
            }
        }
    }

    fn finish(&mut self, winner: i64, reason: &'static str) {
        self.done = true;
        self.winner = winner;
        self.end_reason = reason;
    }

    fn check_end(&mut self) {
        if self.done {
            return;
        }
        for q in 0..2usize {
            if self.players[q].had_units && !self.units.iter().any(|u| u.owner == q) {
                self.finish(1 - q as i64, "rout");
                return;
            }
        }
    }
}
