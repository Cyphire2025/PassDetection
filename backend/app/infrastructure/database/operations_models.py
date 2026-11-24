"""Stable aliases for cohesive Rooming, QR and attendance model owners."""

from .attendance_activity_models import AttendanceRecordModel as AttendanceRecordModel
from .attendance_activity_models import AttendanceSessionModel as AttendanceSessionModel
from .attendance_batch_models import AttendanceScanBatchModel as AttendanceScanBatchModel
from .attendance_batch_models import (
    AttendanceScanBatchResultModel as AttendanceScanBatchResultModel,
)
from .attendance_closeout_models import (
    AttendanceCloseoutCheckpointModel as AttendanceCloseoutCheckpointModel,
)
from .attendance_closeout_models import (
    AttendanceDiscardTombstoneModel as AttendanceDiscardTombstoneModel,
)
from .attendance_runtime_models import (
    AttendanceRuntimeRegistrationModel as AttendanceRuntimeRegistrationModel,
)
from .attendance_runtime_models import (
    AttendanceSessionRuntimeParticipantModel as AttendanceSessionRuntimeParticipantModel,
)
from .model_base import JSONB as JSONB
from .model_base import Base as Base
from .model_base import _utcnow as _utcnow
from .passenger_qr_models import PassengerQRTokenModel as PassengerQRTokenModel
from .passenger_qr_models import (
    PassengerQrWhatsAppDeliveryModel as PassengerQrWhatsAppDeliveryModel,
)
from .rooming_allocation_models import RoomingAssignmentModel as RoomingAssignmentModel
from .rooming_allocation_models import RoomingCheckinModel as RoomingCheckinModel
from .rooming_allocation_models import (
    RoomingPassengerPreferenceModel as RoomingPassengerPreferenceModel,
)
from .rooming_property_models import RoomingHotelModel as RoomingHotelModel
from .rooming_property_models import RoomingHotelPassengerModel as RoomingHotelPassengerModel
from .rooming_property_models import RoomingRoomModel as RoomingRoomModel

__all__ = [
    "AttendanceCloseoutCheckpointModel",
    "AttendanceDiscardTombstoneModel",
    "AttendanceRecordModel",
    "AttendanceRuntimeRegistrationModel",
    "AttendanceScanBatchModel",
    "AttendanceScanBatchResultModel",
    "AttendanceSessionModel",
    "AttendanceSessionRuntimeParticipantModel",
    "PassengerQRTokenModel",
    "PassengerQrWhatsAppDeliveryModel",
    "RoomingAssignmentModel",
    "RoomingCheckinModel",
    "RoomingHotelModel",
    "RoomingHotelPassengerModel",
    "RoomingPassengerPreferenceModel",
    "RoomingRoomModel",
]
