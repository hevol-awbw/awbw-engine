# awbw_rs - the fast engine

A port of `awbw/game.py` + `awbw/cos.py` to Rust, used from Python as `import awbw_rs`. The Python engine stays the
reference (it is the one checked against real AWBW replays); this one must match it exactly.

Build and install (also regenerates `src/tables.rs` from `awbw/data.py` / `awbw/cos.py`):

    python tools/build_rust.py

Check it matches the Python engine (random games through both with the same luck; full state and legal actions
compared after every action):

    python -m pytest tests/test_rust_engine.py

Use:

    from awbw.fast import to_rust, act_to_tuple, tuple_to_act
    rg = to_rust(python_game)           # or awbw_rs.Game(kinds, owners, cos=(..), units=[..], ...) like awbw.game.Game
    rg.legal_actions()                  # all actions as (type, unit, dest_x, dest_y, target_x, target_y, arg)
    rg.actionable_units(); rg.unit_actions(unit_id); rg.build_actions(); rg.global_actions()   # per-unit, cheap
    rg.step(action)                     # validated
    rg.step_trusted(action)             # for actions taken from the lists above (training fast path)
    rg.copy(); rg.state(); awbw_rs.Game.from_state(d)

Speed (one core, fuzz map): ~85,000 agent decisions/s with the per-unit API + step_trusted (330x Python),
~9,500 steps/s when generating the full legal list every step (37x).

Windows note: without the MSVC build tools, build with the GNU toolchain (`AWBW_RUST_GNU=1`, which runs
`rustup override set stable-x86_64-pc-windows-gnu` in this folder). Rules change? Change the Python engine
first, then `src/game.rs` the same way, rebuild, and run the comparison test.
