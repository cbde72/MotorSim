from thermo0d.config.constants import CycleType, VolumeType


def test_constants_are_int_enums():
    assert int(CycleType.TWO_STROKE) == 2
    assert int(VolumeType.CYLINDER) == 1
