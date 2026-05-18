from __future__ import annotations

import argparse
import math
import sys
from pathlib import Path

import numpy as np
from scipy.integrate import solve_ivp

PROJECT_ROOT = Path(__file__).resolve().parents[1]
SRC_DIR = PROJECT_ROOT / "src"
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))
if str(SRC_DIR) not in sys.path:
    sys.path.insert(0, str(SRC_DIR))

from motor_sim.config import load_config
from motor_sim.core.builder import ModelBuilder
from motor_sim.paths import build_paths, initialize_workspace, resolve_reference_file

DEFAULT_PROJECT = str((PROJECT_ROOT / "Projekte").resolve())
DEFAULT_TEST_SPACE = str((PROJECT_ROOT.parent / "test_space").resolve())
print ("PROJEKT_ROOT",PROJECT_ROOT)

#DEFAULT_TEST_SPACE = str((ROOT.parent / "test_space").resolve())

def generate_reference(project_dir: str | Path, test_space: str | Path, config_name: str = "config.json", output_name: str = "cycle_reference_default.npz") -> Path:
    paths = build_paths(project_dir=project_dir, test_space_dir=test_space)
    initialize_workspace(paths, copy_defaults=True, copy_reference_data=False)
    cfg_path = (paths.project_dir / config_name).resolve()
    cfg = load_config(str(cfg_path))
    _S, ctx, model, _t_span, y0 = ModelBuilder(cfg).build()

    cycle_deg = float(ctx.engine.cycle_deg)
    cycle_rad = math.radians(cycle_deg)
    omega = float(ctx.engine.omega_rad_s)

    t0 = 0.0
    t1 = cycle_rad / omega
    t_eval = np.linspace(t0, t1, 361)
    theta_deg = np.degrees(omega * t_eval)

    sol = solve_ivp(
        fun=model.rhs,
        t_span=(t0, t1),
        y0=np.array(y0, dtype=float),
        t_eval=t_eval,
        method="RK45",
        rtol=1e-8,
        atol=1e-10,
        max_step=(t1 - t0) / 1000.0,
    )
    if not sol.success:
        raise RuntimeError(sol.message)

    p = []
    V = []
    mdot_in = []
    mdot_out = []
    qdot = []
    p_int = []
    p_ex = []

    for k in range(sol.y.shape[1]):
        model.rhs(float(sol.t[k]), sol.y[:, k].copy())
        sig = ctx.signals
        p.append(float(sig.get("p", np.nan)))
        V.append(float(sig.get("V", np.nan)))
        mdot_in.append(float(sig.get("mdot_intake_port_to_cyl_kg_s", sig.get("mdot_in", np.nan))))
        mdot_out.append(float(sig.get("mdot_exhaust_port_to_cyl_kg_s", sig.get("mdot_out", np.nan))))
        qdot.append(float(sig.get("qdot_combustion_W", 0.0)))
        p_int.append(float(sig.get("p_int_plenum_pa", np.nan)))
        p_ex.append(float(sig.get("p_ex_plenum_pa", np.nan)))

    out = resolve_reference_file(output_name, test_space_dir=paths.test_space_dir)
    out.parent.mkdir(parents=True, exist_ok=True)

    np.savez_compressed(
        out,
        theta_deg=theta_deg,
        p_pa=np.asarray(p),
        V_m3=np.asarray(V),
        mdot_in=np.asarray(mdot_in),
        mdot_out=np.asarray(mdot_out),
        qdot_comb_W=np.asarray(qdot),
        p_int_plenum_pa=np.asarray(p_int),
        p_ex_plenum_pa=np.asarray(p_ex),
    )
    return out


def _parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Generate MotorSim cycle reference data.")
    parser.add_argument("--project", default=DEFAULT_PROJECT, help="Project directory containing config.json and data/.")
    parser.add_argument("--test-space", default=DEFAULT_TEST_SPACE, help="Target test_space directory.")
    parser.add_argument("--config-name", default="config.json", help="Config filename inside the project directory.")
    parser.add_argument("--output-name", default="cycle_reference_default.npz", help="Reference filename inside test_space/reference_data/.")
    return parser.parse_args()


def main() -> int:
    args = _parse_args()
    out = generate_reference(args.project, args.test_space, args.config_name, args.output_name)
    print(f"written: {out}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
