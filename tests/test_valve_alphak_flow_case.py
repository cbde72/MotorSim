from __future__ import annotations

import csv
from pathlib import Path

import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt
import numpy as np

from tests.support_test_cases import case_dir as case_dir
from thermo0d.config.constants import AngleReference
from thermo0d.config.models import ConfigLoader, CylinderVolumeConfig, ValveConnectionConfig
from thermo0d.input.model_builder import MatrixModelBuilder
from thermo0d.physics.flow import de_st_venant_wantzel_signed, interpolate_piecewise
from thermo0d.physics.kinematics import reference_zero_deg, wrap_angle_deg


def test_valve_alphak_existing_configuration_case() -> None:
    project_root = Path(__file__).resolve().parents[1]
    config_path = project_root / 'Projekte' / 'config_1cyl_4t.yaml'
    cfg = ConfigLoader.load(config_path)
    valve = next(conn for conn in cfg.connections if isinstance(conn, ValveConnectionConfig) and 'intake' in conn.name.lower())
    cyl = next(vol for vol in cfg.volumes if isinstance(vol, CylinderVolumeConfig))
    out_dir = case_dir('valve_alphak_existing_config')
    csv_path = out_dir / 'valve_alphak_flow_case.csv'
    png_path = out_dir / 'valve_alphak_flow_case.png'
    html_path = out_dir / 'index.html'

    lift_table = MatrixModelBuilder._load_csv_table((config_path.parent / valve.lift_file).resolve(), 2, table_kind='valve_lift')
    alpha_table = MatrixModelBuilder._load_csv_table((config_path.parent / valve.alpha_k_file).resolve(), 3, table_kind='generic')
    cycle_deg = 720.0 if cfg.engine.cycle_type == '4t' else 360.0
    ref_map = {
        'absolute': AngleReference.ABSOLUTE,
        'compression_tdc': AngleReference.COMPRESSION_TDC,
        'gas_exchange_tdc': AngleReference.GAS_EXCHANGE_TDC,
    }
    ref_zero = reference_zero_deg(cycle_deg, int(ref_map[valve.opening_reference]))
    cam_ratio = cycle_deg / 360.0 if valve.profile_angle_domain == 'cam' else 1.0
    bore_area = float(np.pi * cyl.kinematics.bore_m * cyl.kinematics.bore_m / 4.0)

    thetas = np.linspace(0.0, cycle_deg, int(cycle_deg) + 1)
    lifts = []
    alpha_f = []
    alpha_r = []
    a_eff_f = []
    mdot_f = []
    p_up = 1.8e5
    p_down = 1.0e5
    t_up = 300.0
    gas_constant = cfg.gas_properties.R_J_per_kgK
    gamma = cfg.gas_properties.cp_J_per_kgK / cfg.gas_properties.cv_J_per_kgK
    for theta in thetas:
        local_crank = wrap_angle_deg(theta - ref_zero - valve.opening_angle_deg, cycle_deg)
        profile_theta = local_crank / cam_ratio
        raw_lift = interpolate_piecewise(profile_theta, lift_table, 0, lift_table.shape[0], 0, 1)
        lift = max(raw_lift * valve.lift_scale - valve.lash_m, 0.0)
        af = interpolate_piecewise(lift, alpha_table, 0, alpha_table.shape[0], 0, 1)
        ar = interpolate_piecewise(lift, alpha_table, 0, alpha_table.shape[0], 0, 2)
        mdot = de_st_venant_wantzel_signed(p_up, t_up, p_down, t_up, bore_area, af, ar, gamma, gas_constant)
        lifts.append(lift)
        alpha_f.append(af)
        alpha_r.append(ar)
        a_eff_f.append(af * bore_area)
        mdot_f.append(mdot)

    with csv_path.open('w', newline='', encoding='utf-8') as f:
        writer = csv.writer(f, delimiter=';')
        writer.writerow(['theta_deg', 'lift_m', 'alphaK_forward', 'alphaK_reverse', 'A_bore_m2', 'A_eff_forward_m2', 'mdot_forward_kg_per_s'])
        for theta, lift, af, ar, aeff, mdot in zip(thetas, lifts, alpha_f, alpha_r, a_eff_f, mdot_f):
            writer.writerow([f'{theta:.3f}', f'{lift:.9f}', f'{af:.9f}', f'{ar:.9f}', f'{bore_area:.9f}', f'{aeff:.9f}', f'{mdot:.9f}'])

    fig, axes = plt.subplots(3, 1, figsize=(8.2, 9.0), dpi=140, sharex=True)
    axes[0].plot(thetas, lifts, label='Ventilhub')
    axes[0].set_ylabel('Lift [m]')
    axes[0].grid(True, alpha=0.3)
    axes[1].plot(thetas, alpha_f, label='alphaK vorwärts')
    axes[1].plot(thetas, alpha_r, label='alphaK rückwärts', linestyle='--')
    axes[1].set_ylabel('alphaK [-]')
    axes[1].grid(True, alpha=0.3)
    axes[1].legend()
    axes[2].plot(thetas, mdot_f, label='ṁ bei festem Δp')
    axes[2].set_ylabel('ṁ [kg/s]')
    axes[2].set_xlabel('Kurbelwinkel [deg]')
    axes[2].grid(True, alpha=0.3)
    fig.tight_layout()
    fig.savefig(png_path)
    plt.close(fig)

    html_path.write_text(f'''<!doctype html><html lang="de"><head><meta charset="utf-8"><title>Valve/AlphaK Test</title>
<style>body{{font-family:Arial,sans-serif;background:#0f172a;color:#e2e8f0;margin:0;padding:24px}}section{{background:#111827;border:1px solid #334155;border-radius:14px;padding:18px;max-width:1080px}}img{{max-width:100%}}code{{background:#0b1220;padding:2px 6px;border-radius:6px}}</style></head><body>
<section><h1>Testfall: vorhandene Ventil- und AlphaK-Konfiguration</h1>
<p>Konfiguration: <code>{config_path.name}</code></p>
<p>Ventil: <code>{valve.name}</code>, Winkelbasis: <code>{valve.profile_angle_domain}</code>, gespeicherter Öffnungswinkel: <code>{valve.opening_angle_deg:.3f} deg</code>.</p>
<p>Für die Auswertung wurde direkt die vorhandene Lift-Datei und AlphaK-Datei benutzt. Der Massenstrom wurde mit <code>de_st_venant_wantzel_signed</code> bei festem Druckgefälle berechnet, wobei im aktuellen Modell für Ventile gilt: <code>C_d = alphaK</code> und <code>A = A_bore</code>.</p>
<img alt="Valve AlphaK Flow" src="valve_alphak_flow_case.png">
<p><a href="valve_alphak_flow_case.csv">CSV-Ausgabe öffnen</a></p>
</section></body></html>''', encoding='utf-8')

    assert max(lifts) > 0.0
    assert max(alpha_f) > 0.0
    assert max(mdot_f) > 0.0
