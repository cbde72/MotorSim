from __future__ import annotations

from enum import IntEnum


class CycleType(IntEnum):
    TWO_STROKE = 2
    FOUR_STROKE = 4


class VolumeType(IntEnum):
    CYLINDER = 1
    PLENUM = 2
    ENVIRONMENT = 3
    BOUNCE_CHAMBER = 4


class ConnectionType(IntEnum):
    VALVE = 1
    SLOT = 2
    ORIFICE = 3
    CHECK_VALVE = 4


class KinematicsType(IntEnum):
    CRANK_SLIDER = 1
    FIXED_VOLUME = 2
    FREE_PISTON = 3


class AngleReference(IntEnum):
    ABSOLUTE = 1
    COMPRESSION_TDC = 2
    GAS_EXCHANGE_TDC = 3


class AngleDomain(IntEnum):
    CRANK = 1
    CAM = 2


class SlotOpenMode(IntEnum):
    BY_DISTANCE = 1
    BY_ANGLE = 2


class FlowCoeffMode(IntEnum):
    CONSTANT = 1
    TABLE = 2


class HeatTransferModel(IntEnum):
    NONE = 0
    WOSCHNI = 1


class WoschniVariant(IntEnum):
    LEGACY = 0
    PROMO = 1
    GT = 2
    CLASSIC = 3
    SWIRL = 4
    HUBER = 5


class WoschniDpMode(IntEnum):
    OFF = 0
    INSTANT = 1
    MOTORED = 2


class WoschniReferenceMode(IntEnum):
    NONE = 0
    PRE_COMBUSTION_LATCH = 1
    CYCLE_START_LATCH = 2


class WoschniPhaseMode(IntEnum):
    LEGACY = 0
    PROMO = 1
    CLASSIC = 2
    GT = 3


class CombustionModel(IntEnum):
    NONE = 0
    VIBE = 1
    HCCI_DIESEL = 2


class CombStartMode(IntEnum):
    ANGLE = 1
    COMPRESSION_HUB = 2
    HIGN_POSITION = 3
    AUTOIGNITION = 4


class CombDurationMode(IntEnum):
    ANGLE = 1
    COMPRESSION_HUB = 2
    TIME = 3


class EvaporationModel(IntEnum):
    NONE = 0
    SIMPLE = 1


class VolumeCol(IntEnum):
    TYPE = 0
    KIN_ROW = 1
    FIXED_VOLUME = 2
    WALL_ROW = 3
    COMB_ROW = 4
    EVAP_ROW = 5


class KinCol(IntEnum):
    TYPE = 0
    BORE = 1
    STROKE = 2
    CONROD = 3
    COMPRESSION_RATIO = 4
    PHASE_DEG = 5
    SPEED_RPM = 6
    CYCLE_DEG = 7


class ConnCol(IntEnum):
    TYPE = 0
    FROM_VOL = 1
    TO_VOL = 2
    PRIMARY_DIM = 3
    SECONDARY_DIM = 4
    OPEN_VALUE = 5
    OPEN_MODE = 6
    REF_TYPE = 7
    ANGLE_DOMAIN = 8
    LIFT_SCALE = 9
    LASH = 10
    N_HOLES = 11
    ENTRANCE_ANGLE_DEG = 12
    OPEN_FILLET_RADIUS = 13
    FULL_FILLET_RADIUS = 14
    PROFILE_START = 15
    PROFILE_LEN = 16
    ALPHA_START = 17
    ALPHA_LEN = 18
    CD_MODE = 19
    CD_FORWARD = 20
    CD_REVERSE = 21
    CD_TABLE_START = 22
    CD_TABLE_LEN = 23
    REF_FLOW_AREA = 24


class WallCol(IntEnum):
    MODEL = 0
    C1 = 1
    C2 = 2
    C3 = 3
    WALL_TEMP = 4
    WALL_AREA = 5
    VARIANT = 6
    DP_MODE = 7
    REF_MODE = 8
    PHASE_MODE = 9
    MULTIPLIER = 10
    CUCM = 11
    SWIRL_NUMBER = 12
    IMEP_BAR = 13
    CLEARANCE_VOL = 14
    MAX_VOL = 15


class WallRefCol(IntEnum):
    P_REF = 0
    T_REF = 1
    V_REF = 2
    P_MOTORED = 3
    VALID = 4
    CYCLE_INDEX = 5


class CombCol(IntEnum):
    MODEL = 0
    START_DEG = 1
    DURATION_DEG = 2
    A = 3
    M = 4
    FUEL_MASS_PER_CYCLE = 5
    LHV = 6
    REF_TYPE = 7
    START_MODE = 8
    DURATION_MODE = 9


class EvapCol(IntEnum):
    MODEL = 0
    START_DEG = 1
    DURATION_DEG = 2
    EVAP_MASS_PER_CYCLE = 3
    LATENT_HEAT = 4
    REF_TYPE = 5


class FeatureCol(IntEnum):
    MASS_FLOW = 0
    WALL_HEAT = 1
    COMBUSTION = 2
    EVAPORATION = 3
    PV_WORK = 4


class WallTemperatureCol(IntEnum):
    AREA = 0
    CONDUCTANCE = 1
    COOLANT_TEMP = 2
    RELAXATION = 3
    ENABLED = 4


class WallTemperatureZone(IntEnum):
    CYLINDER = 0
    HEAD = 1
    PISTON = 2
