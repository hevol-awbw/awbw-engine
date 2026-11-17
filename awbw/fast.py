"""Bridge to the Rust engine (`awbw_rs`, built from rust/ - see rust/README.md).

    from awbw.fast import to_rust, act_to_tuple, tuple_to_act
    rg = to_rust(g)                      # awbw.game.Game -> awbw_rs.Game with the same state
    rg.legal_actions()                   # [(type, unit, dest_x, dest_y, target_x, target_y, arg), ...]
    rg.step(act_to_tuple(Action(AT.END_TURN)))

`py_state(g)` builds from a Python Game the dict that awbw_rs.Game.state() returns, so the two engines can be compared
field by field; `det_luck(seed)` makes a Python Game roll exactly the luck the Rust engine rolls after
`set_luck(seed, 0)` (used by tests/test_rust_engine.py).
"""
from __future__ import annotations

from .data import UT
from .game import AT, Action, Game

MASK = (1 << 64) - 1


def splitmix(z: int) -> int:
    z = (z + 0x9E3779B97F4A7C15) & MASK
    z = ((z ^ (z >> 30)) * 0xBF58476D1CE4E5B9) & MASK
    z = ((z ^ (z >> 27)) * 0x94D049BB133111EB) & MASK
    return z ^ (z >> 31)


def det_luck(g: Game, seed: int, counter: int = 0):
    """A luck_fn for a Python Game that reproduces the Rust engine's deterministic luck stream."""
    state = {"k": counter}

    def luck(p):
        pos, neg = g.co(p).luck(g.lvl(p))
        x = splitmix((seed + state["k"]) & MASK)
        state["k"] += 1
        r = x % (pos + 1)
        if neg:
            r -= (x >> 32) % (neg + 1)
        return r

    luck.state = state
    return luck


def act_to_tuple(a: Action) -> tuple:
    d = a.dest if a.dest is not None else (-1, -1)
    t = a.target if a.target is not None else (-1, -1)
    return (int(a.type), int(a.unit), d[0], d[1], t[0], t[1], int(a.arg))


def tuple_to_act(t) -> Action:
    typ, unit, dx, dy, tx, ty, arg = t
    return Action(AT(typ), unit, (dx, dy) if dx >= 0 else None, (tx, ty) if tx >= 0 else None, arg)


def py_state(g: Game) -> dict:
    flat = lambda rows: [int(v) for r in rows for v in r]  # noqa: E731
    return dict(
        w=g.w, h=g.h, kinds=flat(g.kinds), owners=flat(g.owners), cp=flat(g.cp), cur=g.cur, day=g.day,
        weather=g.weather, default_weather=g.default_weather, weather_expires=g.weather_expires, done=g.done,
        winner=g.winner, end_reason=g.end_reason, next_id=g.next_id, income_per_prop=g.income_per_prop,
        max_days=g.max_days, capture_limit=g.capture_limit, unit_limit=g.unit_limit,
        banned_units=sorted(getattr(g, "banned_units", ())),
        first_turn_income=g.first_turn_income, lab_hq=g.lab_hq, lab_players=[0 in g.lab_players, 1 in g.lab_players],
        players=[dict(co=p.co, country=p.country, funds=p.funds, charge=p.charge, power=p.power, uses=p.uses,
                      had_units=p.had_units) for p in g.players],
        units=[dict(id=u.id, owner=u.owner, type=int(u.type), x=u.x, y=u.y, hp=u.hp, fuel=u.fuel, ammo=u.ammo,
                    acted=u.acted, moved=u.moved, hidden=u.hidden, stunned=u.stunned, loaded_in=u.loaded_in,
                    cargo=list(u.cargo)) for u in g.units.values()],
        last_missiles=[tuple(c) for c in g.last_missiles],
        last_missile_options=[[tuple(c) for c in opts] for opts in g.last_missile_options],
    )


def to_rust(g: Game, seed: int = 0, counter: int = 0):
    import awbw_rs
    return awbw_rs.Game.from_state(py_state(g), seed, counter)
