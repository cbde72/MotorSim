import numpy as np

from thermo0d.physics.kinematics import cylinder_volume_and_dvdt


def test_cylinder_volume_positive():
    kin_row = np.array([1.0, 0.086, 0.086, 0.143, 10.5, 0.0, 2500.0, 720.0], dtype=float)
    volume, dvdt, theta = cylinder_volume_and_dvdt(kin_row, 0.0)
    assert volume > 0.0
    assert theta >= 0.0
    assert isinstance(dvdt, float)
