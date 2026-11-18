# awbw-engine

A rules engine for **Advance Wars By Web** (AWBW) style games: standard, no fog, 1v1. Written in Python as the
reference implementation, with a fast Rust port (`awbw_rs`) that is tested to match it exactly.

This is an unofficial fan project. It is not affiliated with AWBW or Nintendo / Intelligent Systems and contains
no game art or map data.

## What it covers

- 25 units, terrain movement costs, fuel and ammo, the secondary machine gun once primary ammo runs out.
- Combat with luck, terrain stars, counter-attacks, pipe seams.
- Capture, build, join, load / unload, supply, repair, hide / unhide (sub, stealth), missile silos, labs and com towers.
- 28 COs with their day-to-day abilities, COPs and SCOPs, and the power meter.
- Income, repairs at turn start, crash on zero fuel, weather.
- Win conditions: HQ capture, rout, capture limit, day limit (most properties), unit limit, unit bans.

The Python engine has been validated against more than 40,000 real AWBW Global League and Live League games:
every action of every game is replayed through the engine from AWBW's own turn snapshots and checked for
legality, damage, power-meter charge, power effects and the full board state at each turn start.

## Python

Needs Python 3.10+ and nothing else.

```python
import random
from awbw.maps import make_game
from awbw.data import UT

# ASCII map: . plain  ^ mountain  @ wood  = road  ~ sea  r river  c city (neutral)
# H/h HQ  B/b base  C/D city  A/a airport  P/p port (upper case = player 0, lower case = player 1)
g = make_game(["H.B.c",
               ".....",
               "c.b.h"],
              units=[(0, UT.INF, 1, 1), (1, UT.TANK, 3, 1)],   # (player, unit, x, y[, hp 1..100])
              cos=("Andy", "Max"), starting_funds=1000, seed=1, max_days=20)

while g.winner is None:
    actions = g.legal_actions()   # list of Action(type, unit, dest, target, arg)
    g.step(random.choice(actions))   # step() raises IllegalAction for anything illegal
print("winner:", g.winner)
```

`Game.copy()` clones a position; `luck_fn` overrides the luck roll (tests use it to make games deterministic).
`awbw.maps.parse_awbw_csv` reads the AWBW text-map format (terrain ids).

## Rust (optional, ~330x faster)

```
pip install maturin
python tools/build_rust.py        # regenerates rust/src/tables.rs from awbw/data.py + awbw/cos.py, builds, installs
```

See [rust/README.md](rust/README.md) for the API. About 85,000 agent decisions per second on one core.

## Tests

```
pip install pytest
python -m pytest                  # includes the Rust-vs-Python comparison if awbw_rs is installed
```

`tests/test_rust_engine.py` plays random games through both engines with the same luck and compares the full state
and the legal actions after every step. If you change a rule, change the Python engine first, then `rust/src/game.rs`,
rebuild and rerun that test.
