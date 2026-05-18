"""
Integration template for stroke frame export into thermo0d.app.runner

This module shows how to integrate export_free_piston_last_ut_ot_ut_frames()
into the existing simulation runner workflow.

Usage in runner.py:
    from thermo0d.output.stroke_export_integration import export_stroke_frames
    
    # After simulation completes:
    if bundle.free_piston_last_ut_ot_ut_export_enabled:
        export_stroke_frames(
            bundle=bundle,
            export_rows=export_rows,
            config=bundle,
            project_root=project_root,
        )
"""

from __future__ import annotations

from pathlib import Path
import logging
from typing import Optional

import numpy as np

logger = logging.getLogger(__name__)


def export_stroke_frames(
    bundle,
    export_rows: list[dict[str, float | int]],
    config: Optional[object] = None,
    project_root: Optional[str | Path] = None,
    run_config_path: Optional[str | Path] = None,
) -> list[str]:
    """
    Integrated stroke frame export function.
    
    Respects bundle.free_piston_last_ut_ot_ut_export_* settings.
    
    Args:
        bundle: ModelBundle with configuration
        export_rows: CSV export data
        config: Configuration object (optional, for metadata)
        project_root: Project root directory
        run_config_path: Path to run config file
    
    Returns:
        List of exported file paths
    """
    from thermo0d.output.plots import export_free_piston_last_ut_ot_ut_frames
    
    # Check if export is enabled
    if not getattr(bundle, 'free_piston_last_ut_ot_ut_export_enabled', False):
        logger.debug("Stroke frame export disabled")
        return []
    
    # Get settings
    step_deg = float(getattr(bundle, 'free_piston_last_ut_ot_ut_export_step_deg', 1.0))
    axis_min_deg = float(getattr(bundle, 'free_piston_last_ut_ot_ut_export_axis_min_deg', 0.0))
    axis_max_deg = float(getattr(bundle, 'free_piston_last_ut_ot_ut_export_axis_max_deg', 360.0))
    
    # Determine output directory
    if project_root:
        output_dir = Path(project_root).resolve() / "results" / "stroke_frames"
    else:
        output_dir = Path.cwd() / "results" / "stroke_frames"
    
    output_dir.mkdir(parents=True, exist_ok=True)
    
    logger.info(f"Starting stroke frame export:")
    logger.info(f"  Step: {step_deg}°")
    logger.info(f"  Range: {axis_min_deg}°–{axis_max_deg}°")
    logger.info(f"  Output: {output_dir}")
    
    try:
        paths = export_free_piston_last_ut_ot_ut_frames(
            bundle=bundle,
            rows=export_rows,
            output_dir=output_dir,
            step_deg=step_deg,
            axis_min_deg=axis_min_deg,
            axis_max_deg=axis_max_deg,
            export_video=True,
            video_fps=30,
            run_config_path=run_config_path,
        )
        
        if paths:
            logger.info(f"✓ Exported {len(paths)} files")
            frame_count = len([p for p in paths if p.endswith('.png')])
            video_count = len([p for p in paths if p.endswith('.mp4')])
            logger.info(f"  Frames: {frame_count}")
            logger.info(f"  Videos: {video_count}")
            return paths
        else:
            logger.warning("No frames exported (data invalid or UT/OT not detected)")
            return []
    
    except Exception as e:
        logger.error(f"Stroke frame export failed: {e}")
        raise


def add_stroke_export_to_runner(runner_module_path: str | Path):
    """
    Helper function to patch stroke export into existing runner.
    
    This shows where to add the export call in app/runner.py.
    """
    code_snippet = '''
    # --- ADD THIS AFTER LAST CYCLE PRESSURE PLOT EXPORT ---
    
    # Export stroke frames (if enabled in config)
    from thermo0d.output.stroke_export_integration import export_stroke_frames
    
    stroke_paths = export_stroke_frames(
        bundle=bundle,
        export_rows=export_rows,
        config=config,
        project_root=project_root,
        run_config_path=config_path,
    )
    
    if stroke_paths:
        print(f"Stroke frames exported to: {Path(stroke_paths[0]).parent}")
    '''
    
    print("Integration point in app/runner.py:")
    print(code_snippet)
    return code_snippet


# Configuration template for config.yaml
CONFIG_TEMPLATE = """
# Add this to your config.yaml postprocessing section:

postprocessing:
  # ... existing settings ...
  
  free_piston_last_ut_ot_ut_export:
    enabled: true              # Enable/disable stroke frame export
    step_deg: 5.0              # Frame step in degrees (5.0 = 72 frames)
    axis_min_deg: 0.0          # Min angle for plots
    axis_max_deg: 360.0        # Max angle for plots
"""


if __name__ == "__main__":
    print(__doc__)
    print()
    print("=" * 70)
    print("CONFIGURATION TEMPLATE")
    print("=" * 70)
    print(CONFIG_TEMPLATE)
    print()
    print("=" * 70)
    print("INTEGRATION INSTRUCTIONS")
    print("=" * 70)
    add_stroke_export_to_runner("dummy_path")
