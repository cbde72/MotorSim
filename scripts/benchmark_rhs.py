from pathlib import Path
import timeit
import cProfile
import pstats
import numpy as np

from thermo0d.app.paths import PathManager
from thermo0d.input.config_loader import ConfigLoader
from thermo0d.input.model_builder import build_model_bundle
from thermo0d.physics.rhs import RHSWrapper

def main():
    root = PathManager.settings().project_root
    config_path = root / 'test_cases' / 'configs' / 'config_01_4t_base.yaml'
    
    cfg = ConfigLoader.load(config_path)
    bundle = build_model_bundle(cfg, config_path)
    
    rhs = RHSWrapper(bundle)
    
    y = bundle.y_init.copy()
    t = 0.0
    
    # 1 call to trigger numba compilation
    rhs(t, y)
    
    # Now time it
    N = 100000
    
    print("Running timeit benchmarking...")
    start = timeit.default_timer()
    for _ in range(N):
        rhs(t, y)
    end = timeit.default_timer()
    
    total_time = end - start
    per_call = (total_time / N) * 1e6 # microseconds
    
    print(f"RHS Function Benchmark over {N} iterations:")
    print(f"Total time: {total_time:.4f} s")
    print(f"Time per call: {per_call:.2f} µs/call")
    
    print("\nProfiling with cProfile...")
    profiler = cProfile.Profile()
    profiler.enable()
    for _ in range(N):
        rhs(t, y)
    profiler.disable()
    
    stats = pstats.Stats(profiler)
    stats.sort_stats('tottime').print_stats(15)

if __name__ == "__main__":
    main()
