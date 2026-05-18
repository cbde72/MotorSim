from __future__ import annotations

import base64
import csv
from pathlib import Path

import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt
import numpy as np

from tests.support_test_cases import case_dir as case_dir
from thermo0d.physics.flow import de_st_venant_wantzel_signed


def _psi_from_signed_function(pr: float, gamma: float) -> float:
    p_total = 1.0
    t_total = 1.0
    gas_constant = 287.0
    area = 1.0
    mdot = de_st_venant_wantzel_signed(
        p_total,
        t_total,
        max(1.0e-12, min(1.0, pr) * p_total),
        t_total,
        area,
        1.0,
        1.0,
        gamma,
        gas_constant,
    )
    # Bild-Definition der Ausflussfunktion: ψ = Φ / sqrt(2)
    denom = area * p_total / np.sqrt(gas_constant * t_total)
    return float(mdot / (denom * np.sqrt(2.0)))


def test_de_st_venant_wantzel_visualization_case() -> None:
    out_dir = case_dir("flow_function_visualization")
    csv_path = out_dir / "flow_function_curves.csv"
    png_path = out_dir / "flow_function_curves.png"
    html_path = out_dir / "index.html"

    gammas = [1.2, 1.3, 1.4]
    pressure_ratios = np.linspace(1.0, 0.0, 800)
    curves = {gamma: np.array([_psi_from_signed_function(pr, gamma) for pr in pressure_ratios]) for gamma in gammas}

    with csv_path.open("w", newline="", encoding="utf-8") as f:
        writer = csv.writer(f, delimiter=';')
        writer.writerow(["p_over_pt0", *[f"psi_k_{gamma:.1f}" for gamma in gammas]])
        for i, pr in enumerate(pressure_ratios):
            writer.writerow([f"{pr:.8f}", *[f"{curves[gamma][i]:.8f}" for gamma in gammas]])

    fig, ax = plt.subplots(figsize=(8.6, 5.9), dpi=150)
    peak_annotations: dict[float, tuple[float, float]] = {}
    for gamma in gammas:
        ax.plot(pressure_ratios, curves[gamma], linewidth=2.2, label=f"κ={gamma:.1f}")
        crit = (2.0 / (gamma + 1.0)) ** (gamma / (gamma - 1.0))
        peak_val = _psi_from_signed_function(crit, gamma)
        peak_annotations[gamma] = (crit, peak_val)
        if abs(gamma - 1.4) < 1.0e-12:
            ax.axvline(crit, color='red', linestyle='--', linewidth=1.4, alpha=0.9)
            ax.plot([crit], [peak_val], marker='o', markersize=6, color='red')
            ax.annotate(
                f"x={crit:.3f}\ny={peak_val:.4f}",
                xy=(crit, peak_val),
                xytext=(crit - 0.18, peak_val - 0.11),
                textcoords='data',
                color='red',
                fontsize=9,
                arrowprops=dict(arrowstyle='->', color='red', lw=1.0),
                bbox=dict(boxstyle='round,pad=0.25', fc='white', ec='red', alpha=0.9),
            )
        else:
            ax.plot([crit], [peak_val], marker='o', markersize=4)
    ax.set_xlim(1.0, 0.0)
    ax.set_ylim(0.0, 0.52)
    ax.set_xlabel("Düsen-Druckverhältnis p/pₜ₀")
    ax.set_ylabel("Ausflussfunktion ψ")
    ax.set_title("de St. Venant–Wantzel: Ausflussfunktion nach Bilddefinition")
    ax.grid(True, alpha=0.35)
    ax.legend()
    fig.tight_layout()
    fig.savefig(png_path)
    plt.close(fig)

    ref_img = Path(__file__).resolve().parent / "assets" / "flow_nozzle_reference.png"
    ref_b64 = base64.b64encode(ref_img.read_bytes()).decode("ascii")
    plot_b64 = base64.b64encode(png_path.read_bytes()).decode("ascii")
    html_text = f"""<!doctype html>
<html lang=\"de\"><head><meta charset=\"utf-8\"><title>Durchflussfunktion</title>
<style>
body{{font-family:Arial,sans-serif;background:#0f172a;color:#e2e8f0;margin:0;padding:24px}}
main{{display:grid;grid-template-columns:1fr 1fr;gap:20px;align-items:start}}
section{{background:#111827;border:1px solid #334155;border-radius:14px;padding:18px}}
img{{max-width:100%;border-radius:10px;background:white}}
h1,h2{{margin:0 0 12px}}
.formula{{font-size:1.05rem;line-height:1.7}}
code{{background:#0b1220;padding:2px 6px;border-radius:6px}}
</style>
</head><body><h1>Testfall: de_st_venant_wantzel_signed</h1>
<p>Die Kurven wurden direkt mit <code>thermo0d.physics.flow.de_st_venant_wantzel_signed</code> berechnet und auf die Ausflussfunktion ψ in der Bilddefinition normiert. Für κ=1.4 ist der kritische Punkt rot markiert.</p>
<main>
<section><h2>Referenzbild</h2><img alt=\"Referenz\" src=\"data:image/png;base64,{ref_b64}\"></section>
<section><h2>Erzeugter Plot</h2><img alt=\"Plot\" src=\"data:image/png;base64,{plot_b64}\"></section>
<section class=\"formula\"><h2>Verwendete Gleichungen</h2>
<div><strong>Massenstrom:</strong> ṁ = C<sub>d</sub> A · p<sub>u</sub>/√(R T<sub>u</sub>) · Φ</div>
<div><strong>Nicht gechoked:</strong> Φ = √((2κ/(κ-1)) [Π<sup>2/κ</sup> - Π<sup>(κ+1)/κ</sup>])</div>
<div><strong>Gechoked:</strong> Φ = √(κ (2/(κ+1))<sup>(κ+1)/(κ-1)</sup>)</div>
<div><strong>Normierung gemäß Bild:</strong> ψ = ṁ / (A p<sub>t0</sub>/√(R T<sub>t0</sub>) · √2)</div>
<div><strong>Kritisches Druckverhältnis:</strong> Π<sub>krit</sub> = (2/(κ+1))<sup>κ/(κ-1)</sup></div>
<div><strong>Für κ=1.4:</strong> Π<sub>krit</sub> ≈ 0.5283 und ψ<sub>max</sub> ≈ 0.4842</div>
<div><strong>Druckverhältnis:</strong> Π = p / p<sub>t0</sub></div></section>
<section><h2>Dateien</h2><ul><li><a href=\"flow_function_curves.csv\">flow_function_curves.csv</a></li><li><a href=\"flow_function_curves.png\">flow_function_curves.png</a></li></ul></section>
</main></body></html>"""
    html_path.write_text(html_text, encoding="utf-8")

    for gamma, values in curves.items():
        assert np.all(values >= -1.0e-12)
        crit = (2.0 / (gamma + 1.0)) ** (gamma / (gamma - 1.0))
        peak_val = _psi_from_signed_function(crit, gamma)
        assert abs(float(np.max(values)) - peak_val) < 2.0e-3
    crit_14 = (2.0 / (1.4 + 1.0)) ** (1.4 / (1.4 - 1.0))
    psi_14 = _psi_from_signed_function(crit_14, 1.4)
    assert abs(crit_14 - 0.5282817877) < 5.0e-4
    assert abs(psi_14 - 0.4841964865) < 5.0e-4
