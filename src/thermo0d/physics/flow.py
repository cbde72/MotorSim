"""Flow-law helpers used by the RHS.

This module contains the piecewise table interpolation used for lift, alphaK and
slot discharge tables as well as the signed de Saint-Venant–Wantzel mass-flow
relation.

Sign convention:
- positive  -> flow from FROM_VOL to TO_VOL
- negative  -> flow from TO_VOL to FROM_VOL

This topology-based sign is used internally in the RHS. User-facing cylinder
signals are derived from it as separate positive magnitudes for inflow and
outflow.
"""

from __future__ import annotations

import math

import numba as nb
import numpy as np


@nb.njit(cache=True)
def interpolate_piecewise(x: float, table: np.ndarray, start: int, length: int, x_col: int, y_col: int) -> float:
    if length <= 0:
        return 0.0
    x0 = table[start, x_col]
    x1 = table[start + length - 1, x_col]
    if x <= x0:
        return table[start, y_col]
    if x >= x1:
        return table[start + length - 1, y_col]
    for i in range(start, start + length - 1):
        xa = table[i, x_col]
        xb = table[i + 1, x_col]
        if xa <= x <= xb:
            ya = table[i, y_col]
            yb = table[i + 1, y_col]
            if abs(xb - xa) < 1.0e-18:
                return ya
            frac = (x - xa) / (xb - xa)
            return ya + frac * (yb - ya)
    return table[start + length - 1, y_col]


@nb.njit(cache=True)
def de_st_venant_wantzel_signed(
    p_left: float,
    t_left: float,
    p_right: float,
    t_right: float,
    area: float,
    cd_forward: float,
    cd_reverse: float,
    kappa: float,
    gas_constant: float,
) -> float:
    """Signed de Saint-Venant–Wantzel nozzle relation.

    Positive results denote flow from the left volume to the right volume. The
    routine automatically selects forward or reverse coefficients according to
    the pressure gradient and switches to the choked expression below the
    critical pressure ratio.
    """
    if area <= 0.0:
        return 0.0

    if p_left >= p_right:
        p_up = p_left
        t_up = t_left
        p_down = p_right
        cd = cd_forward
        sign = 1.0
    else:
        p_up = p_right
        t_up = t_right
        p_down = p_left
        cd = cd_reverse
        sign = -1.0

    if p_up <= 0.0 or t_up <= 0.0:
        return 0.0

    pr = p_down / p_up
    crit = (2.0 / (kappa + 1.0)) ** (kappa / (kappa - 1.0))
    prefac = cd * area * p_up / math.sqrt(gas_constant * t_up)

    if pr <= crit:
        phi = math.sqrt(kappa * (2.0 / (kappa + 1.0)) ** ((kappa + 1.0) / (kappa - 1.0)))
    else:
        term = (pr ** (2.0 / kappa)) - (pr ** ((kappa + 1.0) / kappa))
        if term < 0.0:
            term = 0.0
        phi = math.sqrt((2.0 * kappa / (kappa - 1.0)) * term)
    return sign * prefac * phi
