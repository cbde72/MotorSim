from __future__ import annotations

from dataclasses import dataclass

import numpy as np


@dataclass(slots=True, frozen=True)
class TurningPoint:
    sample_index: int
    t_s: float
    x_m: float
    v_before_m_per_s: float
    v_after_m_per_s: float


@dataclass(slots=True, frozen=True)
class FreePistonOscillationSummary:
    x_min_m: float
    x_max_m: float
    x_mean_m: float
    stroke_window_m: float
    turning_points_count: int
    oscillation_count: int
    mean_period_s: float | None
    mean_frequency_Hz: float | None
    last_period_s: float | None
    last_frequency_Hz: float | None
    last_halfstroke_m: float | None


def _motion_sign(value: float, slope: float, eps: float) -> int:
    if abs(value) > eps:
        return 1 if value > 0.0 else -1
    if abs(slope) > eps:
        return 1 if slope > 0.0 else -1
    return 0


def detect_turning_points(t_s: np.ndarray, x_m: np.ndarray, v_m_per_s: np.ndarray, *, eps: float = 1.0e-10) -> list[TurningPoint]:
    t_arr = np.asarray(t_s, dtype=np.float64)
    x_arr = np.asarray(x_m, dtype=np.float64)
    v_arr = np.asarray(v_m_per_s, dtype=np.float64)
    n = int(min(t_arr.size, x_arr.size, v_arr.size))
    if n < 3:
        return []

    out: list[TurningPoint] = []
    for i in range(1, n - 1):
        slope_before = float(x_arr[i] - x_arr[i - 1])
        slope_after = float(x_arr[i + 1] - x_arr[i])
        sign_before = _motion_sign(float(v_arr[i - 1]), slope_before, eps)
        sign_after = _motion_sign(float(v_arr[i + 1]), slope_after, eps)
        if sign_before == 0 or sign_after == 0 or sign_before == sign_after:
            continue
        tp = TurningPoint(
            sample_index=i,
            t_s=float(t_arr[i]),
            x_m=float(x_arr[i]),
            v_before_m_per_s=float(v_arr[i - 1]),
            v_after_m_per_s=float(v_arr[i + 1]),
        )
        if out and tp.sample_index - out[-1].sample_index <= 1:
            prev = out[-1]
            prev_strength = abs(prev.v_before_m_per_s) + abs(prev.v_after_m_per_s)
            cur_strength = abs(tp.v_before_m_per_s) + abs(tp.v_after_m_per_s)
            if cur_strength < prev_strength:
                out[-1] = tp
            continue
        out.append(tp)
    return out


def _strict_velocity_sign(value: float, eps: float) -> int:
    if abs(float(value)) <= eps:
        return 0
    return 1 if float(value) > 0.0 else -1


def _has_strict_velocity_reversal(tp: TurningPoint, eps: float) -> bool:
    before = _strict_velocity_sign(float(tp.v_before_m_per_s), eps)
    after = _strict_velocity_sign(float(tp.v_after_m_per_s), eps)
    return before != 0 and after != 0 and before != after


def find_last_ut_ot_ut_turning_points(
    t_s: np.ndarray,
    x_m: np.ndarray,
    v_m_per_s: np.ndarray,
    *,
    eps: float = 1.0e-10,
    min_halfstroke_m: float = 1.0e-15,
) -> tuple[TurningPoint, TurningPoint, TurningPoint] | None:
    turning_points = detect_turning_points(t_s, x_m, v_m_per_s, eps=eps)
    if len(turning_points) < 3:
        return None
    for i in range(len(turning_points) - 3, -1, -1):
        a = turning_points[i]
        b = turning_points[i + 1]
        c = turning_points[i + 2]
        if a.sample_index >= b.sample_index or b.sample_index >= c.sample_index:
            continue
        if not all(_has_strict_velocity_reversal(tp, eps) for tp in (a, b, c)):
            continue
        if not (float(a.x_m) > float(b.x_m) and float(c.x_m) > float(b.x_m)):
            continue
        if abs(float(a.x_m) - float(b.x_m)) <= min_halfstroke_m:
            continue
        if abs(float(c.x_m) - float(b.x_m)) <= min_halfstroke_m:
            continue
        return a, b, c
    return None


def count_ut_ot_ut_cycles(
    t_s: np.ndarray,
    x_m: np.ndarray,
    v_m_per_s: np.ndarray,
    *,
    eps: float = 1.0e-10,
    min_halfstroke_m: float = 1.0e-15,
) -> int:
    t_arr = np.asarray(t_s, dtype=np.float64)
    turning_points = detect_turning_points(t_s, x_m, v_m_per_s, eps=eps)
    count = 0
    cycle_start_times: list[float] = []
    for i in range(0, max(0, len(turning_points) - 2)):
        a = turning_points[i]
        b = turning_points[i + 1]
        c = turning_points[i + 2]
        if a.sample_index >= b.sample_index or b.sample_index >= c.sample_index:
            continue
        if not all(_has_strict_velocity_reversal(tp, eps) for tp in (a, b, c)):
            continue
        if not (float(a.x_m) > float(b.x_m) and float(c.x_m) > float(b.x_m)):
            continue
        if abs(float(a.x_m) - float(b.x_m)) <= min_halfstroke_m:
            continue
        if abs(float(c.x_m) - float(b.x_m)) <= min_halfstroke_m:
            continue
        count += 1
        cycle_start_times.append(float(a.t_s))
    if len(cycle_start_times) >= 2 and t_arr.size >= 2:
        periods = np.diff(np.asarray(cycle_start_times, dtype=np.float64))
        periods = periods[np.isfinite(periods) & (periods > 1.0e-15)]
        if periods.size:
            duration_s = float(np.nanmax(t_arr) - np.nanmin(t_arr))
            estimated = int(round(duration_s / float(np.median(periods))))
            if estimated > count:
                count = estimated
    return count


def summarize_oscillation(t_s: np.ndarray, x_m: np.ndarray, v_m_per_s: np.ndarray) -> FreePistonOscillationSummary | None:
    t_arr = np.asarray(t_s, dtype=np.float64)
    x_arr = np.asarray(x_m, dtype=np.float64)
    v_arr = np.asarray(v_m_per_s, dtype=np.float64)
    n = int(min(t_arr.size, x_arr.size, v_arr.size))
    if n <= 0:
        return None
    t_arr = t_arr[:n]
    x_arr = x_arr[:n]
    v_arr = v_arr[:n]

    turning_points = detect_turning_points(t_arr, x_arr, v_arr)
    periods = [
        float(turning_points[i].t_s - turning_points[i - 2].t_s)
        for i in range(2, len(turning_points))
        if float(turning_points[i].t_s - turning_points[i - 2].t_s) > 1.0e-15
    ]
    if not periods and len(turning_points) >= 2:
        half_periods = [
            float(turning_points[i].t_s - turning_points[i - 1].t_s)
            for i in range(1, len(turning_points))
            if float(turning_points[i].t_s - turning_points[i - 1].t_s) > 1.0e-15
        ]
        periods = [2.0 * value for value in half_periods]
    mean_period_s = float(np.mean(periods)) if periods else None
    mean_frequency_Hz = float(1.0 / mean_period_s) if mean_period_s and mean_period_s > 0.0 else None
    last_period_s = periods[-1] if periods else None
    last_frequency_Hz = float(1.0 / last_period_s) if last_period_s and last_period_s > 0.0 else None
    last_halfstroke_m = abs(float(turning_points[-1].x_m - turning_points[-2].x_m)) if len(turning_points) >= 2 else None
    oscillation_count = max(0, len(periods))

    return FreePistonOscillationSummary(
        x_min_m=float(np.min(x_arr)),
        x_max_m=float(np.max(x_arr)),
        x_mean_m=float(np.mean(x_arr)),
        stroke_window_m=float(np.max(x_arr) - np.min(x_arr)),
        turning_points_count=len(turning_points),
        oscillation_count=oscillation_count,
        mean_period_s=mean_period_s,
        mean_frequency_Hz=mean_frequency_Hz,
        last_period_s=last_period_s,
        last_frequency_Hz=last_frequency_Hz,
        last_halfstroke_m=last_halfstroke_m,
    )
