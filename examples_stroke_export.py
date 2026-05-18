#!/usr/bin/env python3
"""
Stroke Frame Export & Visualization Script
==========================================

Complete example for exporting and visualizing UT-OT-UT stroke frames
with various optimization levels.

Usage:
    python examples_stroke_export.py --config Projekte/config.yaml --mode fast
    python examples_stroke_export.py --config Projekte/config.yaml --mode detailed
    python examples_stroke_export.py --config Projekte/config.yaml --mode batch
"""

import argparse
import sys
from pathlib import Path
from typing import Optional

import numpy as np


def setup_paths():
    """Add src to path if needed."""
    src_path = Path(__file__).parent.parent / "src"
    if str(src_path) not in sys.path:
        sys.path.insert(0, str(src_path))


def export_fast(bundle, export_rows, output_dir: Path):
    """
    Fast export: Low resolution, large frame step.
    
    Use case: Quick preview, testing configuration
    Frames: ~36 frames @ 10° step
    Time: ~10 seconds
    """
    print("📊 Mode: FAST (Preview)")
    print(f"   └─ Frame Step: 10°")
    print(f"   └─ Expected Frames: ~36")
    print(f"   └─ Expected Time: ~5-10s")

    from thermo0d.output.plots import export_free_piston_last_ut_ot_ut_frames

    output_dir = output_dir / "fast"
    output_dir.mkdir(parents=True, exist_ok=True)

    paths = export_free_piston_last_ut_ot_ut_frames(
        bundle=bundle,
        rows=export_rows,
        output_dir=output_dir,
        step_deg=10.0,           # Large step = few frames
        axis_min_deg=0.0,
        axis_max_deg=360.0,
        export_video=True,
        video_fps=12,            # Low fps for preview
    )

    print(f"✓ Exported {len(paths)} files")
    print(f"✓ Output: {output_dir}")
    return output_dir


def export_standard(bundle, export_rows, output_dir: Path):
    """
    Standard export: Medium resolution.
    
    Use case: Production renders, publications
    Frames: ~72 frames @ 5° step
    Time: ~30-60 seconds
    """
    print("📊 Mode: STANDARD (Production)")
    print(f"   └─ Frame Step: 5°")
    print(f"   └─ Expected Frames: ~72")
    print(f"   └─ Expected Time: ~30-60s")

    from thermo0d.output.plots import export_free_piston_last_ut_ot_ut_frames

    output_dir = output_dir / "standard"
    output_dir.mkdir(parents=True, exist_ok=True)

    paths = export_free_piston_last_ut_ot_ut_frames(
        bundle=bundle,
        rows=export_rows,
        output_dir=output_dir,
        step_deg=5.0,            # Medium step
        axis_min_deg=0.0,
        axis_max_deg=360.0,
        export_video=True,
        video_fps=30,
    )

    print(f"✓ Exported {len(paths)} files")
    print(f"✓ Output: {output_dir}")
    return output_dir


def export_detailed(bundle, export_rows, output_dir: Path):
    """
    Detailed export: High resolution.
    
    Use case: Detailed analysis, presentations
    Frames: ~180 frames @ 2° step
    Time: ~2-3 minutes
    """
    print("📊 Mode: DETAILED (High-Quality)")
    print(f"   └─ Frame Step: 2°")
    print(f"   └─ Expected Frames: ~180")
    print(f"   └─ Expected Time: ~2-3 minutes")

    from thermo0d.output.plots import export_free_piston_last_ut_ot_ut_frames

    output_dir = output_dir / "detailed"
    output_dir.mkdir(parents=True, exist_ok=True)

    paths = export_free_piston_last_ut_ot_ut_frames(
        bundle=bundle,
        rows=export_rows,
        output_dir=output_dir,
        step_deg=2.0,            # Fine step
        axis_min_deg=0.0,
        axis_max_deg=360.0,
        export_video=True,
        video_fps=60,            # Smooth video
    )

    print(f"✓ Exported {len(paths)} files")
    print(f"✓ Output: {output_dir}")
    return output_dir


def export_ultra_detailed(bundle, export_rows, output_dir: Path):
    """
    Ultra-detailed export: Maximum resolution.
    
    Use case: Scientific papers, frame-by-frame analysis
    Frames: ~360 frames @ 1° step
    Time: ~5-10 minutes
    """
    print("📊 Mode: ULTRA-DETAILED (Maximum Quality)")
    print(f"   └─ Frame Step: 1°")
    print(f"   └─ Expected Frames: ~360")
    print(f"   └─ Expected Time: ~5-10 minutes")
    print("   ⚠ Warning: Large file size!")

    from thermo0d.output.plots import export_free_piston_last_ut_ot_ut_frames

    output_dir = output_dir / "ultra_detailed"
    output_dir.mkdir(parents=True, exist_ok=True)

    paths = export_free_piston_last_ut_ot_ut_frames(
        bundle=bundle,
        rows=export_rows,
        output_dir=output_dir,
        step_deg=1.0,            # Every degree
        axis_min_deg=0.0,
        axis_max_deg=360.0,
        export_video=True,
        video_fps=60,
    )

    print(f"✓ Exported {len(paths)} files")
    print(f"✓ Output: {output_dir}")
    return output_dir


def export_batch(bundle, export_rows, output_dir: Path):
    """
    Batch export: Multiple resolution levels.
    
    Use case: Comprehensive analysis archive
    Generates: fast, standard, detailed variants
    Time: ~10-15 minutes total
    """
    print("📊 Mode: BATCH (All Resolutions)")
    print(f"   └─ Generating: fast, standard, detailed")
    print(f"   └─ Expected Time: ~10-15 minutes")

    results = {}

    # Fast preview
    print("\n1️⃣  Generating FAST export...")
    results['fast'] = export_fast(bundle, export_rows, output_dir)

    # Standard
    print("\n2️⃣  Generating STANDARD export...")
    results['standard'] = export_standard(bundle, export_rows, output_dir)

    # Detailed
    print("\n3️⃣  Generating DETAILED export...")
    results['detailed'] = export_detailed(bundle, export_rows, output_dir)

    return results


def run_simulation(config_path: Path) -> tuple:
    """
    Run simulation and return bundle + export rows.
    
    Placeholder: Assumes simulation module exists.
    """
    print(f"🔧 Loading config: {config_path}")

    # This would normally import and run the simulation
    # For now, return dummy data structure
    try:
        from thermo0d.app.runner import simulate

        bundle, export_rows = simulate(str(config_path))
        return bundle, export_rows
    except ImportError:
        print("⚠ Warning: Could not import simulate(). Returning dummy data.")
        print("  In production, ensure thermo0d is in PYTHONPATH.")

        # Dummy data for testing
        class DummyBundle:
            cylinder_indices = [0]
            volume_names = {0: "cylinder_0"}

        dummy_rows = [
            {
                "cylinder_0_p_Pa": 101325.0 + i * 1000,
                "cylinder_0_V_m3": 0.0001 - i * 0.00000001,
                "free_piston_distance_from_tdc_m": 0.05 - i * 0.0001,
                "free_piston_v_m_per_s": -1.0 + np.sin(i / 100),
                "cylinder_0_theta_deg": (i % 360),
            }
            for i in range(360)
        ]

        return DummyBundle(), dummy_rows


def main():
    parser = argparse.ArgumentParser(
        description="Stroke Frame Export & Visualization",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
Examples:
  # Fast preview (10° steps)
  python examples_stroke_export.py --config Projekte/config.yaml --mode fast

  # Standard production render (5° steps)
  python examples_stroke_export.py --config Projekte/config.yaml --mode standard

  # Detailed analysis (2° steps)
  python examples_stroke_export.py --config Projekte/config.yaml --mode detailed

  # Ultra-detailed (1° steps)
  python examples_stroke_export.py --config Projekte/config.yaml --mode ultra

  # Batch all resolutions
  python examples_stroke_export.py --config Projekte/config.yaml --mode batch

Optimization levels:
  • fast:       10° step, ~36 frames, ~10s    [Preview]
  • standard:    5° step, ~72 frames, ~60s    [Production]
  • detailed:    2° step, ~180 frames, ~2m    [Detailed]
  • ultra:       1° step, ~360 frames, ~5m    [Maximum]
  • batch:       All above, combined          [Archive]
        """,
    )

    parser.add_argument(
        "--config",
        type=Path,
        default=Path("Projekte/config.yaml"),
        help="Path to simulation config (default: Projekte/config.yaml)",
    )

    parser.add_argument(
        "--output",
        type=Path,
        default=Path("results/stroke_exports"),
        help="Output directory (default: results/stroke_exports)",
    )

    parser.add_argument(
        "--mode",
        choices=["fast", "standard", "detailed", "ultra", "batch"],
        default="standard",
        help="Export mode / optimization level (default: standard)",
    )

    parser.add_argument(
        "--no-video",
        action="store_true",
        help="Disable video export (PNG frames only)",
    )

    args = parser.parse_args()

    # Setup
    setup_paths()
    output_dir = Path(args.output).resolve()
    output_dir.mkdir(parents=True, exist_ok=True)

    print("=" * 70)
    print("  Stroke Frame Export & Visualization Tool")
    print("=" * 70)
    print()

    # Run simulation
    print("▶️  Starting simulation...")
    bundle, export_rows = run_simulation(args.config)

    if not export_rows:
        print("❌ Error: No export rows generated!")
        sys.exit(1)

    print(f"✓ Simulation complete: {len(export_rows)} data points")
    print()

    # Export frames based on mode
    print("▶️  Starting frame export...")
    print()

    if args.mode == "fast":
        export_fast(bundle, export_rows, output_dir)
    elif args.mode == "standard":
        export_standard(bundle, export_rows, output_dir)
    elif args.mode == "detailed":
        export_detailed(bundle, export_rows, output_dir)
    elif args.mode == "ultra":
        export_ultra_detailed(bundle, export_rows, output_dir)
    elif args.mode == "batch":
        export_batch(bundle, export_rows, output_dir)

    print()
    print("=" * 70)
    print("  ✓ Export complete!")
    print("=" * 70)
    print(f"📁 Output directory: {output_dir}")
    print()


if __name__ == "__main__":
    main()
