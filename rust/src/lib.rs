//! Python bindings for the Rust AWBW engine: `import awbw_rs`.
//!
//! awbw_rs.Game mirrors awbw.game.Game. Actions are tuples (type, unit, dest_x, dest_y, target_x, target_y, arg)
//! with -1 for "none" (awbw/fast.py converts to and from awbw.game.Action). state() / Game.from_state() turn a
//! game into a plain dict and back; awbw/fast.py builds the same dict from a Python Game.

mod decide;
mod encode;
mod game;
mod tables;

use game::{Action, Game, Unit, NONE};
use pyo3::exceptions::{PyKeyError, PyValueError};
use pyo3::prelude::*;
use pyo3::types::{PyBytes, PyDict, PyList, PyTuple};
use tables::*;

type ActTuple = (u8, i64, i32, i32, i32, i32, i64);

fn to_tuple(a: &Action) -> ActTuple {
    (a.t, a.unit, a.dx, a.dy, a.tx, a.ty, a.arg)
}

fn from_tuple(t: ActTuple) -> Action {
    Action { t: t.0, unit: t.1, dx: t.2, dy: t.3, tx: t.4, ty: t.5, arg: t.6 }
}

fn co_index(name: &str) -> PyResult<u8> {
    CO_NAME
        .iter()
        .position(|n| *n == name)
        .map(|i| i as u8)
        .ok_or_else(|| PyValueError::new_err(format!("unknown CO {name}")))
}

fn weather_code(w: &str) -> PyResult<u8> {
    match w {
        "C" => Ok(0),
        "R" => Ok(1),
        "S" => Ok(2),
        _ => Err(PyValueError::new_err(format!("unknown weather {w}"))),
    }
}

fn weather_name(w: u8) -> &'static str {
    ["C", "R", "S"][w as usize]
}

fn opt(v: i64) -> Option<i64> {
    if v == NONE { None } else { Some(v) }
}

fn get<'py, T: FromPyObject<'py>>(d: &Bound<'py, PyDict>, k: &str) -> PyResult<T> {
    d.get_item(k)?.ok_or_else(|| PyKeyError::new_err(k.to_string()))?.extract()
}

#[pyclass(name = "Game", module = "awbw_rs")]
#[derive(Clone)]
struct PyGame {
    g: Game,
}

#[pymethods]
impl PyGame {
    #[new]
    #[pyo3(signature = (kinds, owners, cos=("Andy".to_string(), "Andy".to_string()), units=Vec::new(), starting_funds=0,
        weather="C", seed=0, income_per_prop=1000, max_days=None, unit_limit=None, capture_limit=None,
        first_turn_income=true, countries=(1, 2)))]
    #[allow(clippy::too_many_arguments)]
    fn new(
        kinds: Vec<Vec<u8>>, owners: Vec<Vec<i8>>, cos: (String, String), units: Vec<Bound<'_, PyTuple>>,
        starting_funds: i64, weather: &str, seed: u64, income_per_prop: i64, max_days: Option<i64>,
        unit_limit: Option<i64>, capture_limit: Option<i64>, first_turn_income: bool, countries: (i64, i64),
    ) -> PyResult<Self> {
        let mut us = Vec::new();
        for t in units {
            let p: usize = t.get_item(0)?.extract()?;
            let ut: u8 = t.get_item(1)?.extract()?;
            let x: i32 = t.get_item(2)?.extract()?;
            let y: i32 = t.get_item(3)?.extract()?;
            let hp: i64 = if t.len() > 4 { t.get_item(4)?.extract()? } else { 100 };
            us.push((p, ut, x, y, hp));
        }
        Ok(PyGame {
            g: Game::new(
                kinds, owners, [co_index(&cos.0)?, co_index(&cos.1)?], &us, starting_funds, weather_code(weather)?, seed,
                income_per_prop, max_days.unwrap_or(NONE), unit_limit.unwrap_or(NONE), capture_limit.unwrap_or(NONE),
                first_turn_income, [countries.0, countries.1],
            ),
        })
    }

    /// Forbid building these unit types (AWBW unit bans, e.g. Black Bomb and Stealth in GL Std).
    fn set_banned_units(&mut self, types: Vec<u32>) {
        self.g.banned = types.iter().fold(0, |m, t| m | 1 << t);
    }

    /// Every legal action as (type, unit, dest_x, dest_y, target_x, target_y, arg).
    fn legal_actions(&self) -> Vec<ActTuple> {
        self.g.legal_actions().iter().map(to_tuple).collect()
    }

    fn step(&mut self, action: ActTuple) -> PyResult<()> {
        self.g.step(from_tuple(action)).map_err(|e| PyValueError::new_err(e.0))
    }

    /// Apply an action taken from one of the action lists without re-validating it (fast path for training).
    fn step_trusted(&mut self, action: ActTuple) {
        self.g.step_trusted(from_tuple(action))
    }

    /// Ids of units that can still do something this turn (no movement search; cheap).
    fn actionable_units(&self) -> Vec<i64> {
        self.g.actionable_units()
    }

    /// Every legal action of one unit (its own movement search only).
    fn unit_actions(&self, unit: i64) -> PyResult<Vec<ActTuple>> {
        if self.g.uidx(unit).is_none() {
            return Err(PyValueError::new_err(format!("no unit {unit}")));
        }
        let mut acts = Vec::new();
        self.g.unit_actions(unit, &mut acts);
        Ok(acts.iter().map(to_tuple).collect())
    }

    /// Every legal BUILD of the player to move.
    fn build_actions(&self) -> Vec<ActTuple> {
        let mut acts = Vec::new();
        if !self.g.done {
            self.g.build_actions(&mut acts);
        }
        acts.iter().map(to_tuple).collect()
    }

    /// Board planes for the learning agent, from the mover's view: bytes of u8[NPLANES, S, S] (see encode.rs).
    #[pyo3(signature = (sel=(-1, -1), dest=(-1, -1)))]
    fn observe<'py>(&self, py: Python<'py>, sel: (i32, i32), dest: (i32, i32)) -> Bound<'py, PyBytes> {
        PyBytes::new_bound(py, &self.g.observe(sel, dest))
    }

    /// Whole-game numbers for the agent (f32 bytes, length NGLOBAL); `phase` 0..3 is one-hot at the start.
    fn globals<'py>(&self, py: Python<'py>, phase: usize) -> Bound<'py, PyBytes> {
        let v = self.g.globals(phase);
        let bytes: Vec<u8> = v.iter().flat_map(|f| f.to_le_bytes()).collect();
        PyBytes::new_bound(py, &bytes)
    }

    /// Tiles the agent can pick in phase 0 (bytes of u8[S * S]: 1 unit, 2 factory).
    fn select_mask<'py>(&self, py: Python<'py>) -> Bound<'py, PyBytes> {
        PyBytes::new_bound(py, &self.g.select_mask())
    }

    /// Id of the unit standing on (x, y), or None.
    fn unit_id_at(&self, x: i32, y: i32) -> Option<i64> {
        if x < 0 || y < 0 || x >= self.g.w || y >= self.g.h { None } else { self.g.unit_at(x, y) }
    }

    /// Displayed-HP army value and income properties of player p (for reward shaping).
    fn score(&self, p: usize) -> (i64, i64) {
        let v = self.g.units.iter().filter(|u| u.owner == p).map(|u| UNIT_COST[u.t as usize] * game::disp(u.hp) / 10).sum();
        (v, self.g.count_income_props(p))
    }

    /// Available CO powers and End Turn.
    fn global_actions(&self) -> Vec<ActTuple> {
        self.g.global_actions().iter().map(to_tuple).collect()
    }

    /// Decisions per second the way an agent plays: pick a unit (or a build, or End Turn), then one of its
    /// actions, step without re-validation. Returns (decisions, seconds).
    #[pyo3(signature = (n, seed=0))]
    fn bench_decisions(&mut self, n: usize, seed: u64) -> (usize, f64) {
        let t0 = std::time::Instant::now();
        let mut k = 0u64;
        let mut done = 0;
        let mut rnd = || {
            k += 1;
            game::splitmix(seed.wrapping_add(k))
        };
        while done < n && !self.g.done {
            let units = self.g.actionable_units();
            let r = rnd();
            let a = if !units.is_empty() && r % 10 != 0 {
                let id = units[(rnd() % units.len() as u64) as usize];
                let mut acts = Vec::new();
                self.g.unit_actions(id, &mut acts);
                acts[(rnd() % acts.len() as u64) as usize]
            } else {
                let mut acts = Vec::new();
                self.g.build_actions(&mut acts);
                if !acts.is_empty() && r % 3 != 0 {
                    acts[(rnd() % acts.len() as u64) as usize]
                } else {
                    let g = self.g.global_actions();
                    g[(rnd() % g.len() as u64) as usize]
                }
            };
            self.g.step_trusted(a);
            done += 1;
        }
        (done, t0.elapsed().as_secs_f64())
    }

    fn copy(&self) -> Self {
        self.clone()
    }

    /// Every luck roll = the CO's average luck (turn planning: plans compared without luck noise).
    fn set_avg_luck(&mut self, on: bool) {
        self.g.avg_luck = on;
    }

    /// Deterministic luck stream (for tests and reproducible games): roll k uses splitmix64(seed + k).
    fn set_luck(&mut self, seed: u64, counter: u64) {
        self.g.rng_seed = seed;
        self.g.rng_counter = counter;
    }

    #[getter]
    fn done(&self) -> bool {
        self.g.done
    }
    #[getter]
    fn winner(&self) -> Option<i64> {
        opt(self.g.winner)
    }
    #[getter]
    fn cur(&self) -> usize {
        self.g.cur
    }
    #[getter]
    fn day(&self) -> i64 {
        self.g.day
    }
    #[getter]
    fn end_reason(&self) -> Option<&'static str> {
        if self.g.end_reason.is_empty() { None } else { Some(self.g.end_reason) }
    }

    /// Play `n` random legal actions (or until the game ends); returns how many were played. For speed checks.
    #[pyo3(signature = (n, seed=0))]
    fn random_playout(&mut self, n: usize, seed: u64) -> usize {
        let mut k = 0u64;
        let mut played = 0;
        while played < n && !self.g.done {
            let acts = self.g.legal_actions();
            let r = game::splitmix(seed.wrapping_add(k));
            k += 1;
            let a = acts[(r % acts.len() as u64) as usize];
            let _ = self.g.step(a);
            played += 1;
        }
        played
    }

    /// Timing breakdown of a random playout, all inside Rust: (steps, seconds in legal_actions, seconds in step,
    /// mean number of legal actions).
    #[pyo3(signature = (n, seed=0))]
    fn bench(&mut self, n: usize, seed: u64) -> (usize, f64, f64, f64) {
        use std::time::Instant;
        let (mut tl, mut ts, mut nacts) = (0.0, 0.0, 0usize);
        let mut played = 0;
        let mut k = 0u64;
        while played < n && !self.g.done {
            let t0 = Instant::now();
            let acts = self.g.legal_actions();
            tl += t0.elapsed().as_secs_f64();
            nacts += acts.len();
            let r = game::splitmix(seed.wrapping_add(k));
            k += 1;
            let a = acts[(r % acts.len() as u64) as usize];
            let t1 = Instant::now();
            let _ = self.g.step(a);
            ts += t1.elapsed().as_secs_f64();
            played += 1;
        }
        (played, tl, ts, nacts as f64 / played.max(1) as f64)
    }

    /// The whole game as plain Python data (the same shape awbw.fast.py_state builds from a Python Game).
    fn state<'py>(&self, py: Python<'py>) -> PyResult<Bound<'py, PyDict>> {
        let g = &self.g;
        let d = PyDict::new_bound(py);
        d.set_item("w", g.w)?;
        d.set_item("h", g.h)?;
        d.set_item("kinds", g.kinds.clone())?;
        d.set_item("owners", g.owners.clone())?;
        d.set_item("cp", g.cp.clone())?;
        d.set_item("cur", g.cur)?;
        d.set_item("day", g.day)?;
        d.set_item("weather", weather_name(g.weather))?;
        d.set_item("default_weather", weather_name(g.default_weather))?;
        d.set_item("weather_expires", opt(g.weather_expires))?;
        d.set_item("done", g.done)?;
        d.set_item("winner", opt(g.winner))?;
        d.set_item("end_reason", if g.end_reason.is_empty() { None } else { Some(g.end_reason) })?;
        d.set_item("next_id", g.next_id)?;
        d.set_item("income_per_prop", g.income_per_prop)?;
        d.set_item("max_days", opt(g.max_days))?;
        d.set_item("capture_limit", opt(g.capture_limit))?;
        d.set_item("unit_limit", opt(g.unit_limit))?;
        d.set_item("banned_units", (0..32u32).filter(|t| g.banned >> t & 1 == 1).collect::<Vec<_>>())?;
        d.set_item("first_turn_income", g.first_turn_income)?;
        d.set_item("lab_hq", g.lab_hq)?;
        d.set_item("lab_players", vec![g.lab_players[0], g.lab_players[1]])?;
        let pl = PyList::empty_bound(py);
        for p in &g.players {
            let pd = PyDict::new_bound(py);
            pd.set_item("co", CO_NAME[p.co as usize])?;
            pd.set_item("country", p.country)?;
            pd.set_item("funds", p.funds)?;
            pd.set_item("charge", p.charge)?;
            pd.set_item("power", p.power)?;
            pd.set_item("uses", p.uses)?;
            pd.set_item("had_units", p.had_units)?;
            pl.append(pd)?;
        }
        d.set_item("players", pl)?;
        let ul = PyList::empty_bound(py);
        for u in &g.units {
            let ud = PyDict::new_bound(py);
            ud.set_item("id", u.id)?;
            ud.set_item("owner", u.owner)?;
            ud.set_item("type", u.t)?;
            ud.set_item("x", u.x)?;
            ud.set_item("y", u.y)?;
            ud.set_item("hp", u.hp)?;
            ud.set_item("fuel", u.fuel)?;
            ud.set_item("ammo", u.ammo)?;
            ud.set_item("acted", u.acted)?;
            ud.set_item("moved", u.moved)?;
            ud.set_item("hidden", u.hidden)?;
            ud.set_item("stunned", u.stunned)?;
            ud.set_item("loaded_in", opt(u.loaded_in))?;
            ud.set_item("cargo", u.cargo.clone())?;
            ul.append(ud)?;
        }
        d.set_item("units", ul)?;
        d.set_item("last_missiles", g.last_missiles.clone())?;
        d.set_item("last_missile_options", g.last_missile_options.clone())?;
        Ok(d)
    }

    /// Build a game from a state dict (see state()); luck continues from `seed` / `counter` if given.
    #[staticmethod]
    #[pyo3(signature = (s, seed=0, counter=0))]
    fn from_state(s: &Bound<'_, PyDict>, seed: u64, counter: u64) -> PyResult<Self> {
        let w: i32 = get(s, "w")?;
        let h: i32 = get(s, "h")?;
        let kinds: Vec<u8> = get(s, "kinds")?;
        let owners: Vec<i8> = get(s, "owners")?;
        let rows = |v: &Vec<u8>| v.chunks(w as usize).map(|c| c.to_vec()).collect::<Vec<_>>();
        let orows: Vec<Vec<i8>> = owners.chunks(w as usize).map(|c| c.to_vec()).collect();
        let pls: Vec<Bound<'_, PyDict>> = get(s, "players")?;
        let cos = [co_index(&get::<String>(&pls[0], "co")?)?, co_index(&get::<String>(&pls[1], "co")?)?];
        let countries = [get(&pls[0], "country")?, get(&pls[1], "country")?];
        let mut g = Game::new(
            rows(&kinds), orows, cos, &[], 0, weather_code(&get::<String>(s, "default_weather")?)?, seed,
            get(s, "income_per_prop")?, get::<Option<i64>>(s, "max_days")?.unwrap_or(NONE),
            get::<Option<i64>>(s, "unit_limit")?.unwrap_or(NONE), get::<Option<i64>>(s, "capture_limit")?.unwrap_or(NONE),
            get(s, "first_turn_income")?, countries,
        );
        if let Some(b) = s.get_item("banned_units")? {
            g.banned = b.extract::<Vec<u32>>()?.iter().fold(0, |m, t| m | 1 << t);
        }
        assert_eq!(g.w, w);
        assert_eq!(g.h, h);
        g.cp = get(s, "cp")?;
        g.cur = get(s, "cur")?;
        g.day = get(s, "day")?;
        g.weather = weather_code(&get::<String>(s, "weather")?)?;
        g.weather_expires = get::<Option<i64>>(s, "weather_expires")?.unwrap_or(NONE);
        g.done = get(s, "done")?;
        g.winner = get::<Option<i64>>(s, "winner")?.unwrap_or(NONE);
        g.end_reason = match get::<Option<String>>(s, "end_reason")?.as_deref() {
            Some("rout") => "rout",
            Some("hq") => "hq",
            Some("labs") => "labs",
            Some("days") => "days",
            Some("capture_limit") => "capture_limit",
            _ => "",
        };
        g.next_id = get(s, "next_id")?;
        g.lab_hq = get(s, "lab_hq")?;
        let lp: Vec<bool> = get(s, "lab_players")?;
        g.lab_players = [lp[0], lp[1]];
        for (i, pd) in pls.iter().enumerate() {
            let p = &mut g.players[i];
            p.funds = get(pd, "funds")?;
            p.charge = get(pd, "charge")?;
            p.power = get(pd, "power")?;
            p.uses = get(pd, "uses")?;
            p.had_units = get(pd, "had_units")?;
        }
        g.units.clear();
        g.pos = vec![NONE; (w * h) as usize];
        let us: Vec<Bound<'_, PyDict>> = get(s, "units")?;
        for ud in us {
            let u = Unit {
                id: get(&ud, "id")?,
                owner: get(&ud, "owner")?,
                t: get(&ud, "type")?,
                x: get(&ud, "x")?,
                y: get(&ud, "y")?,
                hp: get(&ud, "hp")?,
                fuel: get(&ud, "fuel")?,
                ammo: get(&ud, "ammo")?,
                acted: get(&ud, "acted")?,
                moved: get(&ud, "moved")?,
                hidden: get(&ud, "hidden")?,
                stunned: get(&ud, "stunned")?,
                loaded_in: get::<Option<i64>>(&ud, "loaded_in")?.unwrap_or(NONE),
                cargo: get(&ud, "cargo")?,
            };
            if u.loaded_in == NONE {
                let i = g.idx(u.x, u.y);
                g.pos[i] = u.id;
            }
            g.units.push(u);
        }
        g.reindex();
        if let Some(v) = s.get_item("last_missiles")? {
            g.last_missiles = v.extract()?;
        }
        if let Some(v) = s.get_item("last_missile_options")? {
            g.last_missile_options = v.extract()?;
        }
        g.rng_seed = seed;
        g.rng_counter = counter;
        Ok(PyGame { g })
    }
}

/// The agent's decision phases around a game (see decide.rs; mirrors awbw/rl/env.py's Env).
#[pyclass(name = "DecisionEnv", module = "awbw_rs")]
#[derive(Clone)]
struct PyDecisionEnv {
    d: decide::Decider,
}

#[pymethods]
impl PyDecisionEnv {
    #[new]
    #[pyo3(signature = (game, canvas=encode::S, shaping=0.0, keep_log=false))]
    fn new(game: &PyGame, canvas: usize, shaping: f64, keep_log: bool) -> Self {
        let mut d = decide::Decider::new(game.g.clone(), canvas, shaping);
        d.keep_log = keep_log;
        PyDecisionEnv { d }
    }

    #[getter]
    fn phase(&self) -> u8 { self.d.phase }
    #[getter]
    fn canvas(&self) -> usize { self.d.c }
    #[getter]
    fn done(&self) -> bool { self.d.g.done }
    #[getter]
    fn cur(&self) -> usize { self.d.g.cur }
    #[getter]
    fn day(&self) -> i64 { self.d.g.day }
    #[getter]
    fn winner(&self) -> Option<i64> { opt(self.d.g.winner) }
    #[getter]
    fn end_reason(&self) -> Option<&'static str> { if self.d.g.end_reason.is_empty() { None } else { Some(self.d.g.end_reason) } }
    #[getter]
    fn decisions(&self) -> i64 { self.d.decisions }
    #[getter]
    fn sel(&self) -> (i32, i32) { self.d.sel }
    #[getter]
    fn dest(&self) -> (i32, i32) { self.d.dest }
    #[setter]
    fn set_shaping(&mut self, v: f64) { self.d.shaping = v; }

    /// A copy of the game (for state(), score(), ...).
    fn game(&self) -> PyGame { PyGame { g: self.d.g.clone() } }

    /// An independent copy at the same decision point; with luck_seed it rolls its own luck from then on.
    #[pyo3(name = "clone", signature = (luck_seed=None))]
    fn clone_env(&self, luck_seed: Option<u64>) -> Self {
        let mut c = Clone::clone(self);
        if let Some(s) = luck_seed {
            c.d.g.rng_seed = s;
            c.d.g.rng_counter = 0;
        }
        c.d.log.clear();
        c
    }

    fn act(&mut self, choice: usize) -> usize { self.d.act(choice) }

    /// (luck seed, rolls used): with the position, decides every later luck roll exactly (play-out cache keys).
    fn luck_state(&self) -> (u64, u64) { (self.d.g.rng_seed, self.d.g.rng_counter) }

    /// Every luck roll of this env's game = the CO's average luck (turn planning).
    fn set_avg_luck(&mut self, on: bool) { self.d.g.avg_luck = on; }

    /// Choice carrying out the mover's best attack worth >= min_gain funds (expected), or -1 (decide.rs tactical).
    fn tactical(&mut self, min_gain: i64) -> i64 { self.d.tactical(min_gain) }

    fn take_reward(&mut self, p: usize) -> f64 { self.d.take_reward(p) }

    /// Actions applied since the last call (only with keep_log=True), as tuples.
    fn drain_log(&mut self) -> Vec<ActTuple> { self.d.log.drain(..).map(|a| to_tuple(&a)).collect() }

    /// (planes bytes u8[NPLANES*C*C], globals bytes f32[NGLOBAL]).
    fn observation<'py>(&self, py: Python<'py>) -> (Bound<'py, PyBytes>, Bound<'py, PyBytes>) {
        let (np_, ng, _) = decide::sizes(self.d.c);
        let mut planes = vec![0u8; np_];
        let mut glob = vec![0f32; ng];
        self.d.observation(&mut planes, &mut glob);
        let gb: Vec<u8> = glob.iter().flat_map(|f| f.to_le_bytes()).collect();
        (PyBytes::new_bound(py, &planes), PyBytes::new_bound(py, &gb))
    }

    /// (mask bytes u8[C*C+3], candidates bytes i16[K*2], n candidates).
    fn legal<'py>(&self, py: Python<'py>) -> (Bound<'py, PyBytes>, Bound<'py, PyBytes>, i32) {
        let mut mask = vec![0u8; self.d.nsel()];
        let mut cand = vec![0i16; decide::K * 2];
        let n = self.d.legal(&mut mask, &mut cand);
        let cb: Vec<u8> = cand.iter().flat_map(|v| v.to_le_bytes()).collect();
        (PyBytes::new_bound(py, &mask), PyBytes::new_bound(py, &cb), n)
    }
}

/// Everything the network needs for a batch of envs (all on the same canvas), in one call:
/// (planes u8[B,NPLANES,C,C], globals f32[B,NGLOBAL], phase u8[B], mask u8[B,C*C+3], cand i16[B,K,2], ncand i32[B],
///  cur u8[B]) as bytes.
#[pyfunction]
fn batch_inputs<'py>(py: Python<'py>, envs: Vec<PyRef<'py, PyDecisionEnv>>) -> PyResult<Bound<'py, PyTuple>> {
    let b = envs.len();
    let c = if b > 0 { envs[0].d.c } else { encode::S };
    let (np_, ng, ns) = decide::sizes(c);
    let mut planes = vec![0u8; b * np_];
    let mut glob = vec![0f32; b * ng];
    let mut phase = vec![0u8; b];
    let mut mask = vec![0u8; b * ns];
    let mut cand = vec![0i16; b * decide::K * 2];
    let mut ncand = vec![0i32; b];
    let mut cur = vec![0u8; b];
    if envs.iter().any(|e| e.d.c != c) {
        return Err(PyValueError::new_err("all envs in a batch must use the same canvas"));
    }
    let ds: Vec<&decide::Decider> = envs.iter().map(|e| &e.d).collect();
    let k2 = decide::K * 2;
    py.allow_threads(|| {
        let n = chunk_len(b);
        std::thread::scope(|sc| {
            let parts = ds.chunks(n).zip(planes.chunks_mut(n * np_)).zip(glob.chunks_mut(n * ng))
                .zip(mask.chunks_mut(n * ns)).zip(cand.chunks_mut(n * k2)).zip(ncand.chunks_mut(n))
                .zip(phase.chunks_mut(n)).zip(cur.chunks_mut(n));
            for (((((((d, pl), gl), ma), ca), nc), ph), cu) in parts {
                sc.spawn(move || {
                    for (i, e) in d.iter().enumerate() {
                        e.observation(&mut pl[i * np_..(i + 1) * np_], &mut gl[i * ng..(i + 1) * ng]);
                        nc[i] = e.legal(&mut ma[i * ns..(i + 1) * ns], &mut ca[i * k2..(i + 1) * k2]);
                        ph[i] = e.phase;
                        cu[i] = e.g.cur as u8;
                    }
                });
            }
        });
    });
    let f = |v: Vec<u8>| PyBytes::new_bound(py, &v).into_any();
    let gb: Vec<u8> = glob.iter().flat_map(|x| x.to_le_bytes()).collect();
    let cb: Vec<u8> = cand.iter().flat_map(|x| x.to_le_bytes()).collect();
    let nb: Vec<u8> = ncand.iter().flat_map(|x| x.to_le_bytes()).collect();
    Ok(PyTuple::new_bound(py, [f(planes), f(gb), f(phase), f(mask), f(cb), f(nb), f(cur)]))
}

/// env.act(choice) for each (env, choice) pair.
#[pyfunction]
fn batch_act(py: Python<'_>, mut envs: Vec<PyRefMut<'_, PyDecisionEnv>>, choices: Vec<usize>) {
    let mut ds: Vec<&mut decide::Decider> = envs.iter_mut().map(|e| &mut e.d).collect();
    let n = chunk_len(ds.len());
    py.allow_threads(|| {
        std::thread::scope(|sc| {
            for (d, c) in ds.chunks_mut(n).zip(choices.chunks(n)) {
                sc.spawn(move || {
                    for (e, &ch) in d.iter_mut().zip(c) {
                        e.act(ch);
                    }
                });
            }
        });
    });
}

/// Envs per worker thread for a batch of `b` (one thread below 64 envs; AWBW_THREADS caps the threads, default:
/// all cores up to 16).
fn chunk_len(b: usize) -> usize {
    let threads = std::env::var("AWBW_THREADS").ok().and_then(|v| v.parse().ok())
        .unwrap_or_else(|| std::thread::available_parallelism().map(|n| n.get()).unwrap_or(1).min(16));
    let t = if b < 64 { 1 } else { threads.max(1) };
    b.div_ceil(t).max(1)
}

#[pymodule]
fn awbw_rs(m: &Bound<'_, PyModule>) -> PyResult<()> {
    m.add_class::<PyGame>()?;
    m.add_class::<PyDecisionEnv>()?;
    m.add_function(wrap_pyfunction!(batch_inputs, m)?)?;
    m.add_function(wrap_pyfunction!(batch_act, m)?)?;
    m.add("K", decide::K)?;
    m.add("CO_NAMES", CO_NAME.to_vec())?;
    m.add("CANVAS", encode::S)?;
    m.add("NPLANES", encode::NPLANES)?;
    m.add("NGLOBAL", encode::NGLOBAL)?;
    Ok(())
}
