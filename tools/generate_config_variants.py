from __future__ import annotations

import argparse
import json
from copy import deepcopy
from pathlib import Path


SIGNAL_MODES = ("none", "minimal", "full")


def _ensure_dict(parent: dict, key: str) -> dict:
    value = parent.get(key)
    if not isinstance(value, dict):
        value = {}
        parent[key] = value
    return value


def _with_suffix(filename: str, suffix: str) -> str:
    p = Path(str(filename))
    stem = p.stem or "out"
    ext = p.suffix or ""
    return f"{stem}_{suffix}{ext}"


def _sanitize_case_name(text: str) -> str:
    text = str(text or "case").strip()
    if not text:
        text = "case"
    return text


def _apply_variant(base_cfg: dict, mode: str) -> dict:
    cfg = deepcopy(base_cfg)

    base_case_name = _sanitize_case_name(cfg.get("case_name", "case"))
    variant_tag = f"sig_{mode}__scipy_rk45__evap1_vollverdampft"
    cfg["case_name"] = f"{base_case_name}__{variant_tag}"

    sim = _ensure_dict(cfg, "simulation")
    integrator = _ensure_dict(sim, "integrator")
    integrator["type"] = "scipy"
    integrator["method"] = "RK45"

    output = _ensure_dict(sim, "output")
    # Ausgabe-Dateien je Variante trennen, damit die Fälle sich nicht überschreiben.
    out_files = _ensure_dict(cfg, "output_files")
    if "csv_name" in out_files:
        out_files["csv_name"] = _with_suffix(str(out_files["csv_name"]), variant_tag)
    if "plot_name" in out_files:
        out_files["plot_name"] = _with_suffix(str(out_files["plot_name"]), variant_tag)
    if "out_dir" in out_files:
        out_files["out_dir"] = str(out_files["out_dir"])

    # Signalmodus an mehreren plausiblen Stellen setzen.
    runtime = _ensure_dict(_ensure_dict(cfg, "numerics"), "runtime")
    runtime["signal_mode"] = mode
    runtime["publish_signal_mode"] = mode
    runtime["sample_signal_mode"] = mode
    runtime["record_signal_mode"] = mode
    runtime["publish_signals_each_rhs"] = bool(mode != "none")

    sim["signal_mode"] = mode
    output["signal_mode"] = mode

    # Evaporation-Modell: 1 = vollverdampft
    energy_models = _ensure_dict(cfg, "energy_models")
    evap = _ensure_dict(energy_models, "evaporation")
    evap["enabled"] = True
    evap["model"] = 1
    evap["mode"] = 1
    evap["model_name"] = "vollverdampft"
    evap["full_evaporated"] = True

    # Kleine Metainfo, falls später nachvollzogen werden soll, wie die Datei entstanden ist.
    generated = _ensure_dict(cfg, "_generated")
    generated["base_case_name"] = base_case_name
    generated["variant"] = variant_tag
    generated["signal_mode"] = mode
    generated["integrator_type"] = "scipy"
    generated["integrator_method"] = "RK45"
    generated["evaporation_model"] = 1
    generated["evaporation_model_name"] = "vollverdampft"

    return cfg


def _default_base_config() -> Path | None:
    script_dir = Path(__file__).resolve().parents[1]
    print (script_dir, flush=True)
    root = script_dir.parent if script_dir.name.lower() == "scripts" else script_dir

    candidates = [
        root / "configs" / "config.json",
        Path.cwd() / "configs" / "config.json",
        Path.cwd() / "config.json",
    ]
    for cand in candidates:
        if cand.exists():
            return cand.resolve()
    return None


def generate_variants(base_config_path: Path, out_dir: Path | None = None) -> list[Path]:
    base_config_path = base_config_path.resolve()
    out_dir = (out_dir or base_config_path.parent).resolve()
    out_dir.mkdir(parents=True, exist_ok=True)

    data = json.loads(base_config_path.read_text(encoding="utf-8"))
    if not isinstance(data, dict):
        raise ValueError(f"Config root must be a JSON object: {base_config_path}")

    written: list[Path] = []
    for mode in SIGNAL_MODES:
        cfg = _apply_variant(data, mode)
        filename = f"config_sig_{mode}_scipy_rk45_evap1_vollverdampft.json"
        target = out_dir / filename
        target.write_text(json.dumps(cfg, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
        written.append(target)
    return written


def main() -> int:

    parser = argparse.ArgumentParser(description="Erzeugt Konfigurationsvarianten none/minimal/full auf Basis einer bestehenden config.json.")
    parser.add_argument("--base-config", type=str, default=None, help="Pfad zur Basis-config.json")
    parser.add_argument("--out-dir", type=str, default=None, help="Ausgabeordner für die generierten JSON-Dateien")
    args = parser.parse_args()

    base_cfg = Path(args.base_config).expanduser().resolve() if args.base_config else _default_base_config()
    if base_cfg is None or not base_cfg.exists():
        raise FileNotFoundError(
            "Keine Basis-config.json gefunden. Nutze --base-config <pfad> "
            "oder lege die Datei unter ../configs/config.json relativ zum Script ab."
        )

    out_dir = Path(args.out_dir).expanduser().resolve() if args.out_dir else base_cfg.parent
    files = generate_variants(base_cfg, out_dir=out_dir)

    print(f"[OK] Basis-Config: {base_cfg}")
    for file in files:
        print(f"[OK] geschrieben: {file}")
    return 0


if __name__ == "__main__":
    main()
