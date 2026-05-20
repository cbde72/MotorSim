from __future__ import annotations

from types import SimpleNamespace

import numpy as np

from thermo0d.config.constants import VolumeCol, VolumeType
from thermo0d.output.reconstruction import _add_single_instance_compat_aliases, _free_piston_local_kinematics


def test_free_piston_local_kinematics_mirrors_negative_motion_sign() -> None:
    fp = SimpleNamespace(
        x_min_m=0.0,
        x_max_m=0.108,
        x_state_index=0,
        v_state_index=1,
        mechanical_x_state_indices=np.array([0], dtype=np.int64),
        mechanical_v_state_indices=np.array([1], dtype=np.int64),
        volume_mechanical_dof=np.array([0, 0], dtype=np.int64),
        volume_mechanical_sign=np.array([1.0, -1.0], dtype=np.float64),
    )
    bundle = SimpleNamespace(free_piston=fp)
    y = np.array([[0.020], [3.0]], dtype=np.float64)

    x_pos, v_pos = _free_piston_local_kinematics(bundle, 0, y, 0)
    x_neg, v_neg = _free_piston_local_kinematics(bundle, 1, y, 0)

    assert np.isclose(x_pos, 0.020)
    assert np.isclose(v_pos, 3.0)
    assert np.isclose(x_neg, 0.088)
    assert np.isclose(v_neg, -3.0)


def test_single_instance_compat_aliases_keep_legacy_free_piston_names() -> None:
    columns = {
        'cylinder_1_p_Pa': np.array([1.0]),
        'compressor_1_m_kg': np.array([2.0]),
        'compressor_1_in_cv_mdot_kg_per_s': np.array([3.0]),
        'transfer_slot_1_mdot_kg_per_s': np.array([4.0]),
    }
    vol_matrix = np.zeros((2, len(VolumeCol)), dtype=np.float64)
    vol_matrix[0, VolumeCol.TYPE] = float(VolumeType.CYLINDER)
    vol_matrix[1, VolumeCol.TYPE] = float(VolumeType.BOUNCE_CHAMBER)
    bundle = SimpleNamespace(
        vol_matrix=vol_matrix,
        volume_names=['cylinder_1', 'compressor_1'],
        connection_names=['compressor_1_in_cv', 'transfer_slot_1'],
    )

    _add_single_instance_compat_aliases(columns, bundle)

    assert columns['cylinder_p_Pa'] is columns['cylinder_1_p_Pa']
    assert columns['bounce_m_kg'] is columns['compressor_1_m_kg']
    assert columns['bounce_in_cv_mdot_kg_per_s'] is columns['compressor_1_in_cv_mdot_kg_per_s']
    assert columns['transfer_slot_mdot_kg_per_s'] is columns['transfer_slot_1_mdot_kg_per_s']


def test_multi_instance_compat_aliases_do_not_create_ambiguous_singulars() -> None:
    columns = {
        'cylinder_1_p_Pa': np.array([1.0]),
        'cylinder_2_p_Pa': np.array([2.0]),
    }
    vol_matrix = np.zeros((2, len(VolumeCol)), dtype=np.float64)
    vol_matrix[:, VolumeCol.TYPE] = float(VolumeType.CYLINDER)
    bundle = SimpleNamespace(
        vol_matrix=vol_matrix,
        volume_names=['cylinder_1', 'cylinder_2'],
        connection_names=[],
    )

    _add_single_instance_compat_aliases(columns, bundle)

    assert 'cylinder_p_Pa' not in columns
