//! What the learning agent sees: the board as compact integer planes plus a vector of whole-game numbers,
//! always from the point of view of the player to move ("me" = 1, "enemy" = 2), so one network plays both sides.
//! Planes are u8 on a fixed S x S canvas (maps are placed at the top-left; tiles off the map have plane 0 = 0);
//! the network turns the categorical planes into one-hot / embeddings itself.

use crate::game::{disp, Game, NONE};
use crate::tables::*;

pub const S: usize = 30; // canvas side; maps up to 30 x 30
pub const NPLANES: usize = 20;
pub const NGLOBAL: usize = 4 + 2 + 2 + 2 + 2 + 2 + 1 + 3 + 2 + 2 + NCO * 2;

// plane indices
pub const P_ON_MAP: usize = 0; // 1 on the map
pub const P_TERRAIN: usize = 1; // terrain kind (TK_*)
pub const P_PROP_OWNER: usize = 2; // 0 none / neutral, 1 mine, 2 enemy's
pub const P_CP: usize = 3; // capture points left (0..20), pipe-seam HP (0..99)
pub const P_UNIT: usize = 4; // unit type + 1 (0 = no unit)
pub const P_UNIT_SIDE: usize = 5; // 1 mine, 2 enemy
pub const P_HP: usize = 6; // internal HP 0..100
pub const P_FUEL: usize = 7; // fuel as % of max
pub const P_AMMO: usize = 8; // ammo as % of max (100 for units without ammo)
pub const P_FLAGS: usize = 9; // bits: 1 acted, 2 moved, 4 hidden, 8 stunned, 16 capturing here
pub const P_CARGO: usize = 10; // first cargo's type + 1, +32 if carrying two
pub const P_SELECT: usize = 11; // 1 the selected unit / factory, 2 the selected destination
pub const P_THREAT: usize = 12; // 12..16: Game::threat_planes (enemy reach count, danger to my unit here, danger to the
                                // selected unit per tile, my reach count, my damage on the enemy unit here)
pub const P_ROUTE: usize = 17; // 17..19: Game::route_planes (path cost from the selected unit, to its nearest firing
                               // spot, to its nearest capturable property; cost + 1, 0 = unreachable / none)

/// AWBW_THREAT=0 leaves the tactical planes at zero (nets without them: saves the reach computation).
fn threat_on() -> bool {
    static ON: std::sync::OnceLock<bool> = std::sync::OnceLock::new();
    *ON.get_or_init(|| std::env::var("AWBW_THREAT").map(|v| v != "0").unwrap_or(true))
}

fn pct(v: i64, m: i64) -> u8 {
    if m <= 0 { 100 } else { ((v.max(0) * 100) / m).min(100) as u8 }
}

impl Game {
    fn rel(&self, owner: i64) -> u8 {
        if owner < 0 { 0 } else if owner as usize == self.cur { 1 } else { 2 }
    }

    /// Board planes, u8[NPLANES * S * S] (plane-major). `sel` / `dest` mark a selected tile (or -1).
    pub fn observe(&self, sel: (i32, i32), dest: (i32, i32)) -> Vec<u8> {
        let mut o = vec![0u8; NPLANES * S * S];
        let at = |p: usize, x: i32, y: i32| p * S * S + (y as usize) * S + x as usize;
        for y in 0..self.h.min(S as i32) {
            for x in 0..self.w.min(S as i32) {
                let i = self.idx(x, y);
                let k = self.kinds[i];
                o[at(P_ON_MAP, x, y)] = 1;
                o[at(P_TERRAIN, x, y)] = k;
                if IS_CAPTURABLE[k as usize] {
                    o[at(P_PROP_OWNER, x, y)] = self.rel(self.owners[i] as i64);
                }
                o[at(P_CP, x, y)] = self.cp[i].clamp(0, 255) as u8;
            }
        }
        for u in &self.units {
            if u.loaded_in != NONE || u.x as usize >= S || u.y as usize >= S {
                continue;
            }
            let (x, y) = (u.x, u.y);
            let t = u.t as usize;
            o[at(P_UNIT, x, y)] = u.t + 1;
            o[at(P_UNIT_SIDE, x, y)] = self.rel(u.owner as i64);
            o[at(P_HP, x, y)] = u.hp.clamp(0, 100) as u8;
            o[at(P_FUEL, x, y)] = pct(u.fuel, UNIT_FUEL[t]);
            o[at(P_AMMO, x, y)] = pct(u.ammo, UNIT_AMMO[t]);
            let i = self.idx(x, y);
            let capturing = IS_FOOT[t] && IS_CAPTURABLE[self.kinds[i] as usize] && self.cp[i] < 20
                && self.owners[i] != u.owner as i8;
            // acted / moved only for the mover's units: the enemy's are left over from its last turn (and always
            // clear in states rebuilt from AWBW turn snapshots, as in the human-game data)
            let mine = u.owner == self.cur;
            o[at(P_FLAGS, x, y)] = ((u.acted && mine) as u8) | ((u.moved && mine) as u8) << 1 | (u.hidden as u8) << 2
                | (u.stunned as u8) << 3 | (capturing as u8) << 4;
            if let Some(&c) = u.cargo.first() {
                if let Some(ci) = self.uidx(c) {
                    o[at(P_CARGO, x, y)] = self.units[ci].t + 1 + if u.cargo.len() > 1 { 32 } else { 0 };
                }
            }
        }
        if sel.0 >= 0 && (sel.0 as usize) < S && (sel.1 as usize) < S {
            o[at(P_SELECT, sel.0, sel.1)] = 1;
        }
        if threat_on() && !self.done {
            let t = self.threat_planes(sel);
            for (k, plane) in t.iter().enumerate() {
                for y in 0..self.h.min(S as i32) {
                    for x in 0..self.w.min(S as i32) {
                        o[at(P_THREAT + k, x, y)] = plane[self.idx(x, y)];
                    }
                }
            }
        }
        if threat_on() && !self.done {
            let r = self.route_planes(sel);
            for (k, plane) in r.iter().enumerate() {
                for y in 0..self.h.min(S as i32) {
                    for x in 0..self.w.min(S as i32) {
                        o[at(P_ROUTE + k, x, y)] = plane[self.idx(x, y)];
                    }
                }
            }
        }
        if dest.0 >= 0 && (dest.0 as usize) < S && (dest.1 as usize) < S {
            o[at(P_SELECT, dest.0, dest.1)] = 2;
        }
        o
    }

    /// Whole-game numbers from the mover's point of view (length NGLOBAL). `phase` 0..3 is one-hot at the start.
    pub fn globals(&self, phase: usize) -> Vec<f32> {
        let me = self.cur;
        let en = 1 - me;
        let mut g = Vec::with_capacity(NGLOBAL);
        for k in 0..4 {
            g.push(if k == phase { 1.0 } else { 0.0 });
        }
        for p in [me, en] {
            g.push(self.players[p].funds as f32 / 20000.0);
        }
        for p in [me, en] {
            let c1 = self.power_cost(p, 1).max(1);
            g.push((self.players[p].charge as f32 / c1 as f32).min(3.0));
        }
        for p in [me, en] {
            let c2 = self.power_cost(p, 2).max(1);
            g.push((self.players[p].charge as f32 / c2 as f32).min(1.0));
        }
        for p in [me, en] {
            g.push(self.players[p].power as f32 / 2.0);
        }
        for p in [me, en] {
            g.push(self.count_income_props(p) as f32 / 20.0);
        }
        g.push(self.day as f32 / 30.0);
        for w in 0..3u8 {
            g.push(if self.weather == w { 1.0 } else { 0.0 });
        }
        for p in [me, en] {
            g.push(self.units.iter().filter(|u| u.owner == p).count() as f32 / 30.0);
        }
        for p in [me, en] {
            let v: i64 = self.units.iter().filter(|u| u.owner == p).map(|u| UNIT_COST[u.t as usize] * disp(u.hp) / 10).sum();
            g.push(v as f32 / 100000.0);
        }
        for p in [me, en] {
            for c in 0..NCO {
                g.push(if self.players[p].co as usize == c { 1.0 } else { 0.0 });
            }
        }
        debug_assert_eq!(g.len(), NGLOBAL);
        g
    }

    /// Phase-0 mask, u8[S * S]: 1 = a unit that can still act stands here, 2 = a factory with an affordable build.
    pub fn select_mask(&self) -> Vec<u8> {
        let mut m = vec![0u8; S * S];
        for id in self.actionable_units() {
            let u = &self.units[self.uidx(id).unwrap()];
            if (u.x as usize) < S && (u.y as usize) < S {
                m[u.y as usize * S + u.x as usize] = 1;
            }
        }
        let mut b = Vec::new();
        if !self.done {
            self.build_actions(&mut b);
        }
        for a in b {
            if (a.dx as usize) < S && (a.dy as usize) < S {
                m[a.dy as usize * S + a.dx as usize] = 2;
            }
        }
        m
    }
}
