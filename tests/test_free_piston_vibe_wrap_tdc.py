from thermo0d.physics.combustion import vibe_heat_release_rate


def _comb_row(start_deg: float, duration_deg: float, q_total: float = 500.0):
    # Matches CombCol layout used by vibe_heat_release_rate:
    # MODEL, START, DURATION, A, M, FUEL, LHV, REF
    # Model 1 == VIBE, Ref 1 == COMPRESSION_TDC in current enum layout.
    # q_total is represented as FUEL*LHV.
    return [1.0, float(start_deg), float(duration_deg), 6.9, 2.0, float(q_total), 1.0, 2.0]


def test_vibe_window_continues_across_tdc_wrap():
    row = _comb_row(355.0, 12.0)
    q_before_tdc = vibe_heat_release_rate(359.0, 0.0, 1.0, row, 360.0)
    q_after_tdc = vibe_heat_release_rate(1.0, 0.0, 1.0, row, 360.0)
    assert q_before_tdc > 0.0
    assert q_after_tdc > 0.0


def test_vibe_window_outside_wrap_is_zero():
    row = _comb_row(355.0, 12.0)
    q_far_from_window = vibe_heat_release_rate(40.0, 0.0, 1.0, row, 360.0)
    assert q_far_from_window == 0.0
