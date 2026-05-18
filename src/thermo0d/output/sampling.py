from __future__ import annotations

import numpy as np


class OutputSampler:
    @staticmethod
    def _validate_step(step: float) -> float:
        if step <= 0.0:
            raise ValueError('sampling step must be > 0')
        return float(step)

    @staticmethod
    def _grid_targets(start: float, end: float, step: float, include_endpoint: bool = True) -> np.ndarray:
        step = OutputSampler._validate_step(step)
        if end < start:
            raise ValueError('sampling range end must be >= start')
        tol = max(1.0e-12, abs(step) * 1.0e-9)
        span = max(0.0, float(end) - float(start))
        n_steps = int(np.floor((span + tol) / step))
        targets = float(start) + step * np.arange(n_steps + 1, dtype=np.float64)
        if include_endpoint:
            targets = targets[targets <= float(end) + tol]
        else:
            targets = targets[targets < float(end) - tol]
        if targets.size == 0:
            return np.array([float(start)], dtype=np.float64)
        targets[0] = float(start)
        if include_endpoint and abs(float(targets[-1]) - float(end)) <= tol:
            targets[-1] = float(end)
        return targets

    @classmethod
    def build_sample_times_time(cls, t: np.ndarray, step_s: float) -> np.ndarray:
        if t.size == 0:
            return np.zeros(0, dtype=np.float64)
        return cls._grid_targets(float(t[0]), float(t[-1]), float(step_s))

    @classmethod
    def build_sample_times_angle(cls, t: np.ndarray, cycle_period_s: float, cycle_deg: float, step_deg: float) -> np.ndarray:
        if t.size == 0:
            return np.zeros(0, dtype=np.float64)
        omega_deg_per_s = cycle_deg / cycle_period_s
        theta_start_deg = float(t[0]) * omega_deg_per_s
        theta_end_deg = float(t[-1]) * omega_deg_per_s
        theta_targets_deg = cls._grid_targets(theta_start_deg, theta_end_deg, float(step_deg))
        return theta_targets_deg / omega_deg_per_s


    @classmethod
    def build_single_cycle_times_angle(cls, cycle_start_s: float, cycle_period_s: float, cycle_deg: float, step_deg: float, include_endpoint: bool = True) -> np.ndarray:
        step_deg = cls._validate_step(step_deg)
        theta_targets_deg = cls._grid_targets(0.0, float(cycle_deg), float(step_deg), include_endpoint=include_endpoint)
        omega_deg_per_s = float(cycle_deg) / float(cycle_period_s)
        return float(cycle_start_s) + theta_targets_deg / omega_deg_per_s

    @classmethod
    def build_sample_times(cls, t: np.ndarray, cycle_period_s: float, cycle_deg: float, sampling_mode: str, sampling_step: float) -> np.ndarray:
        if sampling_mode == 'time':
            return cls.build_sample_times_time(t, sampling_step)
        if sampling_mode == 'crank_angle':
            return cls.build_sample_times_angle(t, cycle_period_s, cycle_deg, sampling_step)
        raise ValueError(f'Unsupported sampling mode: {sampling_mode}')

    @staticmethod
    def interpolate_states(t: np.ndarray, y: np.ndarray, sample_t: np.ndarray) -> np.ndarray:
        if y.ndim != 2:
            raise ValueError('y must be a 2D array with shape (n_states, n_times)')
        if t.ndim != 1:
            raise ValueError('t must be a 1D array')
        if y.shape[1] != t.size:
            raise ValueError('y.shape[1] must match t.size')
        y_interp = np.empty((y.shape[0], sample_t.size), dtype=np.float64)
        for i in range(y.shape[0]):
            y_interp[i, :] = np.interp(sample_t, t, y[i, :])
        return y_interp

    @staticmethod
    def build_cycle_indices(sample_t: np.ndarray, cycle_period_s: float, total_cycles: int) -> np.ndarray:
        if cycle_period_s <= 0.0:
            raise ValueError('cycle_period_s must be > 0')
        idx = np.floor(np.asarray(sample_t, dtype=np.float64) / float(cycle_period_s) - 1.0e-12).astype(int)
        idx[idx < 0] = 0
        idx[idx >= total_cycles] = total_cycles - 1
        return idx

    @classmethod
    def resample(cls, t: np.ndarray, y: np.ndarray, cycle_period_s: float, cycle_deg: float, sampling_mode: str, sampling_step: float, total_cycles: int) -> tuple[np.ndarray, np.ndarray, np.ndarray]:
        sample_t = cls.build_sample_times(t, cycle_period_s, cycle_deg, sampling_mode, sampling_step)
        sample_y = cls.interpolate_states(t, y, sample_t)
        sample_cycles = cls.build_cycle_indices(sample_t, cycle_period_s, total_cycles)
        return sample_t, sample_y, sample_cycles

    @classmethod
    def build_keep_mask_time(cls, t: np.ndarray, step_s: float) -> np.ndarray:
        sample_t = cls.build_sample_times_time(t, step_s)
        return np.isin(t, sample_t)

    @classmethod
    def build_keep_mask_angle(cls, t: np.ndarray, cycle_period_s: float, cycle_deg: float, step_deg: float) -> np.ndarray:
        sample_t = cls.build_sample_times_angle(t, cycle_period_s, cycle_deg, step_deg)
        return np.isin(t, sample_t)

    @classmethod
    def build_keep_mask(cls, t: np.ndarray, cycle_period_s: float, cycle_deg: float, sampling_mode: str, sampling_step: float) -> np.ndarray:
        if sampling_mode == 'time':
            return cls.build_keep_mask_time(t, sampling_step)
        if sampling_mode == 'crank_angle':
            return cls.build_keep_mask_angle(t, cycle_period_s, cycle_deg, sampling_step)
        raise ValueError(f'Unsupported sampling mode: {sampling_mode}')
