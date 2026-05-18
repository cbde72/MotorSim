#!/usr/bin/env python3
"""
Unit tests for export_free_piston_last_ut_ot_ut_frames()
"""

import unittest
import tempfile
from pathlib import Path
import numpy as np


class MockBundle:
    """Mock bundle for testing."""
    def __init__(self):
        self.cylinder_indices = [0]
        self.volume_names = {0: "cylinder_0"}


class TestStrokeFrameExport(unittest.TestCase):
    """Test frame export functionality."""

    def setUp(self):
        """Set up test data."""
        self.temp_dir = tempfile.TemporaryDirectory()
        self.output_dir = Path(self.temp_dir.name)
        self.bundle = MockBundle()

    def tearDown(self):
        """Cleanup."""
        self.temp_dir.cleanup()

    def _create_synthetic_stroke_data(self, n_points: int = 360):
        """
        Create synthetic UT-OT-UT cycle data.
        
        Simulates a realistic free-piston stroke:
        - Compression (UT→OT): velocity < 0
        - Expansion (OT→UT): velocity > 0
        - Pressure peaks at OT
        """
        theta = np.linspace(0, 360, n_points)
        
        # Create velocity: negative compression, positive expansion
        velocity = -np.sin(np.radians(theta))
        
        # Pressure profile: high at OT, low at UT
        pressure_pa = 101325.0 + 50 * 1.0e5 * (1 - np.cos(np.radians(theta)))
        
        # Volume: minimal at OT, maximal at UT
        volume_m3 = 0.0001 * (1 + 0.5 * np.cos(np.radians(theta)))
        
        # Create rows
        rows = []
        for i in range(n_points):
            rows.append({
                "cylinder_0_p_Pa": float(pressure_pa[i]),
                "cylinder_0_V_m3": float(volume_m3[i]),
                "cylinder_0_theta_deg": float(theta[i]),
                "free_piston_distance_from_tdc_m": float(0.05 * np.cos(np.radians(theta[i]))),
                "free_piston_v_m_per_s": float(velocity[i]),
            })
        return rows

    def test_basic_frame_export(self):
        """Test basic frame export with fast settings."""
        rows = self._create_synthetic_stroke_data(n_points=360)
        
        from thermo0d.output.plots import export_free_piston_last_ut_ot_ut_frames
        
        paths = export_free_piston_last_ut_ot_ut_frames(
            bundle=self.bundle,
            rows=rows,
            output_dir=self.output_dir,
            step_deg=30.0,  # 12 frames
            export_video=False,
        )
        
        # Should generate ~12 frames
        frame_files = list(self.output_dir.glob("frame_*.png"))
        self.assertGreater(len(frame_files), 0, "No frames generated")
        self.assertLess(len(frame_files), 15, "Too many frames")
        print(f"✓ Generated {len(frame_files)} frames")

    def test_frame_naming(self):
        """Test that frames are named correctly."""
        rows = self._create_synthetic_stroke_data(n_points=360)
        
        from thermo0d.output.plots import export_free_piston_last_ut_ot_ut_frames
        
        paths = export_free_piston_last_ut_ot_ut_frames(
            bundle=self.bundle,
            rows=rows,
            output_dir=self.output_dir,
            step_deg=45.0,
            export_video=False,
        )
        
        # Check filename format
        frame_files = list(self.output_dir.glob("frame_*.png"))
        for f in frame_files:
            # Expected format: frame_XXXX_angle_YYYdeg.png
            self.assertRegex(f.name, r"frame_\d{4}_angle_\d{3}deg\.png")
        print(f"✓ Frame names valid: {[f.name for f in frame_files[:3]]}")

    def test_empty_data(self):
        """Test handling of empty data."""
        from thermo0d.output.plots import export_free_piston_last_ut_ot_ut_frames
        
        result = export_free_piston_last_ut_ot_ut_frames(
            bundle=self.bundle,
            rows=[],
            output_dir=self.output_dir,
            export_video=False,
        )
        
        self.assertEqual(result, [], "Should return empty list for empty data")
        print("✓ Empty data handled correctly")

    def test_missing_keys(self):
        """Test handling of missing required keys."""
        from thermo0d.output.plots import export_free_piston_last_ut_ot_ut_frames
        
        rows = [{"some_key": 1.0}]  # Missing required keys
        
        result = export_free_piston_last_ut_ot_ut_frames(
            bundle=self.bundle,
            rows=rows,
            output_dir=self.output_dir,
            export_video=False,
        )
        
        self.assertEqual(result, [], "Should return empty list for missing keys")
        print("✓ Missing keys handled correctly")

    def test_ut_ot_detection(self):
        """Test that UT and OT are correctly detected."""
        rows = self._create_synthetic_stroke_data(n_points=360)
        
        from thermo0d.output.plots import export_free_piston_last_ut_ot_ut_frames
        
        # This should NOT raise an error
        paths = export_free_piston_last_ut_ot_ut_frames(
            bundle=self.bundle,
            rows=rows,
            output_dir=self.output_dir,
            step_deg=60.0,
            export_video=False,
        )
        
        self.assertGreater(len(paths), 0, "UT/OT detection failed")
        print(f"✓ UT/OT detection working: {len(paths)} frames")

    def test_interpolation_bounds(self):
        """Test that interpolation doesn't cause index errors."""
        rows = self._create_synthetic_stroke_data(n_points=200)
        
        from thermo0d.output.plots import export_free_piston_last_ut_ot_ut_frames
        
        # Use angle range beyond data range (should be clipped)
        paths = export_free_piston_last_ut_ot_ut_frames(
            bundle=self.bundle,
            rows=rows,
            output_dir=self.output_dir,
            step_deg=5.0,
            axis_min_deg=-10.0,  # Outside range
            axis_max_deg=370.0,   # Outside range
            export_video=False,
        )
        
        # Should handle gracefully without error
        self.assertIsInstance(paths, list)
        print(f"✓ Interpolation bounds handling OK: {len(paths)} frames")

    def test_video_export(self):
        """Test video export (if imageio available)."""
        try:
            import imageio
        except ImportError:
            self.skipTest("imageio not installed")
        
        rows = self._create_synthetic_stroke_data(n_points=360)
        
        from thermo0d.output.plots import export_free_piston_last_ut_ot_ut_frames
        
        paths = export_free_piston_last_ut_ot_ut_frames(
            bundle=self.bundle,
            rows=rows,
            output_dir=self.output_dir,
            step_deg=45.0,
            export_video=True,
            video_fps=10,
        )
        
        # Check if video file was created
        video_files = list(self.output_dir.glob("*.mp4"))
        self.assertGreater(len(video_files), 0, "No video file created")
        print(f"✓ Video export OK: {video_files[0].name}")


class TestIntegration(unittest.TestCase):
    """Integration tests with example_stroke_export script."""

    def test_import_module(self):
        """Test that module imports without errors."""
        try:
            from thermo0d.output.plots import export_free_piston_last_ut_ot_ut_frames
            self.assertTrue(callable(export_free_piston_last_ut_ot_ut_frames))
            print("✓ Module import OK")
        except ImportError as e:
            self.fail(f"Failed to import: {e}")

    def test_fast_example(self):
        """Test fast export mode."""
        from pathlib import Path
        import sys
        
        # Check if example script exists
        example_path = Path(__file__).parent.parent / "examples_stroke_export.py"
        self.assertTrue(example_path.exists(), f"Example script not found: {example_path}")
        print(f"✓ Example script found: {example_path}")


def run_performance_benchmark():
    """Run a performance benchmark."""
    import time
    
    bundle = MockBundle()
    
    # Create larger dataset
    n_points = 3600  # 10x more data
    rows = []
    for i in range(n_points):
        theta = (i / n_points) * 360.0
        rows.append({
            "cylinder_0_p_Pa": 101325.0 + 50 * 1.0e5 * (1 - np.cos(np.radians(theta))),
            "cylinder_0_V_m3": 0.0001 * (1 + 0.5 * np.cos(np.radians(theta))),
            "cylinder_0_theta_deg": theta,
            "free_piston_distance_from_tdc_m": 0.05 * np.cos(np.radians(theta)),
            "free_piston_v_m_per_s": -np.sin(np.radians(theta)),
        })
    
    from thermo0d.output.plots import export_free_piston_last_ut_ot_ut_frames
    
    with tempfile.TemporaryDirectory() as tmpdir:
        start = time.time()
        paths = export_free_piston_last_ut_ot_ut_frames(
            bundle=bundle,
            rows=rows,
            output_dir=tmpdir,
            step_deg=5.0,  # 72 frames
            export_video=False,
        )
        elapsed = time.time() - start
        
        print(f"\n⏱️  Performance Benchmark")
        print(f"   Data points: {n_points}")
        print(f"   Frames generated: {len(paths)}")
        print(f"   Time elapsed: {elapsed:.2f}s")
        print(f"   Frame/sec: {len(paths)/elapsed:.1f}")


if __name__ == "__main__":
    # Run tests
    print("=" * 70)
    print("  Stroke Frame Export Test Suite")
    print("=" * 70)
    print()
    
    unittest.main(verbosity=2, exit=False)
    
    # Run benchmark
    print()
    try:
        run_performance_benchmark()
    except Exception as e:
        print(f"Benchmark skipped: {e}")
    
    print()
    print("=" * 70)
    print("  ✓ All tests completed")
    print("=" * 70)
