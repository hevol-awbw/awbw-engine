//! The agent's decision phases in Rust - a line-by-line port of awbw/rl/env.py's Env (same masks, same candidate
//! order, same observation, same shaping), so search and training can step many games without Python per decision.
//!
//! Phases: 0 SELECT (tile / COP / SCOP / END), 1 DEST (tile), 2 ACTION (candidate), 3 BUILD (unit type).
//! A phase with one legal option is played automatically. Tiles are indexed y * C + x on a C x C canvas.

use crate::encode::{NGLOBAL, NPLANES, S};
use crate::game::{Action, Game, NONE};
use crate::tables::*;

pub const K: usize = 64; // max ACTION candidates
pub const SELECT: u8 = 0;
pub const DEST: u8 = 1;
pub const ACTION: u8 = 2;
pub const BUILD: u8 = 3;
const AT_POWER: u8 = 13;
const AT_END: u8 = 14;

#[derive(Clone)]
pub struct Decider {
    pub g: Game,
    pub c: usize,
    pub shaping: f64,
    pub phase: u8,
    pub sel: (i32, i32),
    pub dest: (i32, i32),
    unit_acts: Vec<Action>,
    mask: Vec<u8>,                    // select_mask (S * S)
    powers: [Option<Action>; 3],      // by power level 1, 2
    by_dest: Vec<((i32, i32), Vec<Action>)>, // insertion-ordered like the Python dict
    cands: Vec<Action>,
    builds: Vec<Action>,
    phi: [f64; 2],
    pub pending: [f64; 2],
    pub decisions: i64,
    pub log: Vec<Action>,             // actions applied since the last drain (for mirroring into a Python game)
    pub keep_log: bool,
    plan: Option<Action>,             // tactical(): the attack being carried out over SELECT / DEST / ACTION
}

impl Decider {
    pub fn new(g: Game, c: usize, shaping: f64) -> Self {
        let mut d = Decider {
            g, c, shaping, phase: SELECT, sel: (-1, -1), dest: (-1, -1), unit_acts: Vec::new(), mask: Vec::new(),
            powers: [None; 3], by_dest: Vec::new(), cands: Vec::new(), builds: Vec::new(), phi: [0.0; 2],
            pending: [0.0; 2], decisions: 0, log: Vec::new(), keep_log: false, plan: None,
        };
        d.phi = [d.potential(0), d.potential(1)];
        d.advance();
        d
    }

    fn score(&self, p: usize) -> (i64, i64) {
        let v = self.g.units.iter().filter(|u| u.owner == p).map(|u| UNIT_COST[u.t as usize] * crate::game::disp(u.hp) / 10).sum();
        (v, self.g.count_income_props(p))
    }

    pub fn potential(&self, p: usize) -> f64 {
        let (av, pp) = self.score(p);
        let (bv, bp) = self.score(1 - p);
        0.5 * (pp - bp) as f64 / ((pp + bp).max(1)) as f64 + 0.5 * (av - bv) as f64 / ((av + bv).max(10000)) as f64
    }

    fn update_shaping(&mut self) {
        for p in 0..2 {
            let phi = if self.g.done { 0.0 } else { self.potential(p) };
            self.pending[p] += self.shaping * (phi - self.phi[p]);
            self.phi[p] = phi;
        }
    }

    pub fn take_reward(&mut self, p: usize) -> f64 {
        let mut r = self.pending[p];
        self.pending[p] = 0.0;
        if self.g.done && self.g.winner != NONE {
            r += if self.g.winner as usize == p { 1.0 } else { -1.0 };
        }
        r
    }

    fn apply(&mut self, a: Action) {
        if self.keep_log {
            self.log.push(a);
        }
        self.g.step_trusted(a);
        self.phase = SELECT;
        self.sel = (-1, -1);
        self.dest = (-1, -1);
        self.unit_acts.clear();
        self.update_shaping();
    }

    /// Play forced choices until there is a real decision (or the game is over).
    pub fn advance(&mut self) {
        while !self.g.done {
            match self.phase {
                SELECT => {
                    self.mask = self.g.select_mask();
                    self.powers = [None; 3];
                    for a in self.g.global_actions() {
                        if a.t == AT_POWER {
                            self.powers[a.arg as usize] = Some(a);
                        }
                    }
                    if !self.mask.iter().any(|&m| m != 0) && self.powers.iter().all(|p| p.is_none()) {
                        self.apply(Action::simple(AT_END));
                        continue;
                    }
                    return;
                }
                DEST => {
                    let mut groups: Vec<((i32, i32), Vec<Action>)> = Vec::new();
                    for a in &self.unit_acts {
                        let key = (a.dx, a.dy);
                        match groups.iter_mut().find(|(k, _)| *k == key) {
                            Some((_, v)) => v.push(*a),
                            None => groups.push((key, vec![*a])),
                        }
                    }
                    self.by_dest = groups;
                    if self.by_dest.len() == 1 {
                        self.dest = self.by_dest[0].0;
                        self.phase = ACTION;
                        continue;
                    }
                    return;
                }
                ACTION => {
                    let dest = self.dest;
                    let list = self.by_dest.iter().find(|(k, _)| *k == dest).map(|(_, v)| v.clone()).unwrap_or_default();
                    self.cands = list.into_iter().take(K).collect();
                    if self.cands.len() == 1 {
                        let a = self.cands[0];
                        self.apply(a);
                        continue;
                    }
                    return;
                }
                _ => {
                    let mut b = Vec::new();
                    self.g.build_actions(&mut b);
                    let sel = self.sel;
                    self.builds = b.into_iter().filter(|a| (a.dx, a.dy) == sel).collect();
                    if self.builds.len() == 1 {
                        let a = self.builds[0];
                        self.apply(a);
                        continue;
                    }
                    return;
                }
            }
        }
    }

    pub fn nsel(&self) -> usize {
        self.c * self.c + 3
    }

    /// (mask over this phase's options [nsel], candidates [K][2] as (type, target tile or -1), n candidates).
    pub fn legal(&self, mask: &mut [u8], cand: &mut [i16]) -> i32 {
        let c = self.c;
        let c2 = c * c;
        mask.iter_mut().for_each(|m| *m = 0);
        cand.iter_mut().for_each(|v| *v = -1);
        let mut n = 0;
        match self.phase {
            SELECT => {
                for y in 0..c.min(S) {
                    for x in 0..c.min(S) {
                        if self.mask[y * S + x] > 0 {
                            mask[y * c + x] = 1;
                        }
                    }
                }
                mask[c2] = self.powers[1].is_some() as u8;
                mask[c2 + 1] = self.powers[2].is_some() as u8;
                mask[c2 + 2] = 1;
            }
            DEST => {
                for ((x, y), _) in &self.by_dest {
                    mask[*y as usize * c + *x as usize] = 1;
                }
            }
            ACTION => {
                for (i, a) in self.cands.iter().enumerate() {
                    cand[2 * i] = a.t as i16;
                    cand[2 * i + 1] = if a.tx >= 0 { (a.ty as usize * c + a.tx as usize) as i16 } else { -1 };
                }
                n = self.cands.len();
                for m in mask.iter_mut().take(n) {
                    *m = 1;
                }
            }
            _ => {
                for a in &self.builds {
                    mask[a.arg as usize] = 1;
                }
            }
        }
        n as i32
    }

    /// Planes cropped to C x C (u8[NPLANES * C * C]) and globals (f32[NGLOBAL]).
    pub fn observation(&self, planes: &mut [u8], glob: &mut [f32]) {
        let full = self.g.observe(self.sel, self.dest);
        let c = self.c;
        for p in 0..NPLANES {
            for y in 0..c {
                let src = p * S * S + y * S;
                let dst = p * c * c + y * c;
                planes[dst..dst + c].copy_from_slice(&full[src..src + c]);
            }
        }
        glob.copy_from_slice(&self.g.globals(self.phase as usize));
    }

    /// Tactical play-out rule (2026-11-04): the choice that carries out the mover's most valuable attack
    /// (Game::attack_gain >= min_gain) through SELECT -> DEST -> ACTION, or -1 to let the network decide.
    /// Exists because net-top-choice play-outs missed simple first strikes (unit order blocking the attacker,
    /// low-rated attack squares), so search believed exposed units were safe.
    pub fn tactical(&mut self, min_gain: i64) -> i64 {
        let c = self.c;
        match self.phase {
            SELECT => {
                self.plan = None;
                let mut best: Option<(i64, Action)> = None;
                for uid in self.g.actionable_units() {
                    let mut acts = Vec::new();
                    self.g.unit_actions(uid, &mut acts);
                    for a in acts.iter().filter(|a| a.t == crate::game::AT_ATTACK) {
                        let gn = self.g.attack_gain(a);
                        if gn >= min_gain && best.map_or(true, |(b, _)| gn > b) {
                            best = Some((gn, *a));
                        }
                    }
                }
                if let Some((_, a)) = best {
                    let u = self.g.units.iter().find(|u| u.id == a.unit).map(|u| (u.x, u.y));
                    if let Some((x, y)) = u {
                        if (x as usize) < c && (y as usize) < c && self.mask[y as usize * S + x as usize] == 1 {
                            self.plan = Some(a);
                            return (y as usize * c + x as usize) as i64;
                        }
                    }
                }
                -1
            }
            DEST => match self.plan {
                Some(a) if self.by_dest.iter().any(|((x, y), _)| (*x, *y) == (a.dx, a.dy)) => (a.dy as usize * c + a.dx as usize) as i64,
                _ => { self.plan = None; -1 }
            },
            ACTION => {
                let r = match self.plan {
                    Some(a) => self.cands.iter().position(|b| b.t == a.t && b.tx == a.tx && b.ty == a.ty).map_or(-1, |i| i as i64),
                    None => -1,
                };
                self.plan = None;
                r
            }
            _ => -1,
        }
    }

    /// Apply the agent's choice for the current phase; returns the player who made it.
    pub fn act(&mut self, choice: usize) -> usize {
        let p = self.g.cur;
        let c = self.c;
        let c2 = c * c;
        self.decisions += 1;
        match self.phase {
            SELECT => {
                if choice == c2 + 2 {
                    self.apply(Action::simple(AT_END));
                } else if choice == c2 || choice == c2 + 1 {
                    let a = self.powers[if choice == c2 { 1 } else { 2 }].expect("power not available");
                    self.apply(a);
                } else {
                    let (x, y) = ((choice % c) as i32, (choice / c) as i32);
                    self.sel = (x, y);
                    if self.mask[y as usize * S + x as usize] == 2 {
                        self.phase = BUILD;
                    } else {
                        let uid = self.g.unit_at(x, y).expect("no unit on the selected tile");
                        self.unit_acts.clear();
                        let mut acts = Vec::new();
                        self.g.unit_actions(uid, &mut acts);
                        self.unit_acts = acts;
                        self.phase = DEST;
                    }
                }
            }
            DEST => {
                self.dest = ((choice % c) as i32, (choice / c) as i32);
                self.phase = ACTION;
            }
            ACTION => {
                let a = self.cands[choice];
                self.apply(a);
            }
            _ => {
                let a = *self.builds.iter().find(|a| a.arg as usize == choice).expect("build not available");
                self.apply(a);
            }
        }
        self.advance();
        p
    }
}

pub fn sizes(c: usize) -> (usize, usize, usize) {
    (NPLANES * c * c, NGLOBAL, c * c + 3)
}
