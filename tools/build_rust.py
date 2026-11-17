"""Build the Rust engine and install it into this Python: `py -3.12 tools/build_rust.py`.

Regenerates rust/src/tables.rs from the Python data first, builds with maturin and pip-installs the wheel so
`import awbw_rs` picks it up. Needs Rust (rustup) and `pip install maturin`. On Windows without the MSVC build tools,
set AWBW_RUST_GNU=1 to build with the GNU toolchain instead.
"""
import glob
import os
import shutil
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
RUST = ROOT / "rust"
env = dict(os.environ)
cargo_bin = Path.home() / ".cargo" / "bin"
env["PATH"] = str(cargo_bin) + os.pathsep + env.get("PATH", "")


def run(*cmd, cwd=ROOT):
    print(">", " ".join(map(str, cmd)))
    subprocess.run(list(map(str, cmd)), cwd=cwd, env=env, check=True)


run(sys.executable, ROOT / "tools" / "gen_rust_tables.py")
if os.name == "nt" and os.environ.get("AWBW_RUST_GNU"):
    run(shutil.which("rustup", path=env["PATH"]) or "rustup", "override", "set", "stable-x86_64-pc-windows-gnu", cwd=RUST)
shutil.rmtree(RUST / "target" / "wheels", ignore_errors=True)
run(sys.executable, "-m", "maturin", "build", "--release", "-i", sys.executable, cwd=RUST)
wheel = glob.glob(str(RUST / "target" / "wheels" / "*.whl"))[0]
run(sys.executable, "-m", "pip", "install", "--quiet", "--force-reinstall", wheel)
print("installed", Path(wheel).name)
