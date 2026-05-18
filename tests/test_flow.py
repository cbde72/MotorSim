from thermo0d.physics.flow import de_st_venant_wantzel_signed


def test_flow_sign_changes_with_pressure_direction():
    mdot_lr = de_st_venant_wantzel_signed(2.0e5, 300.0, 1.0e5, 300.0, 1.0e-4, 0.8, 0.7, 1.4, 287.0)
    mdot_rl = de_st_venant_wantzel_signed(1.0e5, 300.0, 2.0e5, 300.0, 1.0e-4, 0.8, 0.7, 1.4, 287.0)
    assert mdot_lr > 0.0
    assert mdot_rl < 0.0
