
from __future__ import annotations


def velocity_reversal_detected(v_prev_m_per_s: float, v_curr_m_per_s: float) -> bool:
    return float(v_prev_m_per_s) * float(v_curr_m_per_s) < 0.0
