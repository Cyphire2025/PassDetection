"""Stable imports for cohesive My Photos model owners; persistent schema unchanged."""

from app.application.my_photos.limits import MAX_MY_PHOTOS_MEDIA_BYTES as MAX_MY_PHOTOS_MEDIA_BYTES
from app.infrastructure.database.model_base import Base as Base
from app.infrastructure.database.model_base import _utcnow as _utcnow
from app.infrastructure.database.my_photo_delivery_models import (
    MyPhotoDeliveryAuthorizationModel as MyPhotoDeliveryAuthorizationModel,
)
from app.infrastructure.database.my_photo_enrollment_models import (
    MyPhotoEnrollmentModel as MyPhotoEnrollmentModel,
)
from app.infrastructure.database.my_photo_face_models import (
    MyPhotoFaceOccurrenceModel as MyPhotoFaceOccurrenceModel,
)
from app.infrastructure.database.my_photo_gallery_models import (
    MyPhotoGalleryManifestBatchModel as MyPhotoGalleryManifestBatchModel,
)
from app.infrastructure.database.my_photo_gallery_models import (
    MyPhotoGalleryManifestModel as MyPhotoGalleryManifestModel,
)
from app.infrastructure.database.my_photo_gallery_models import (
    MyPhotoGalleryModel as MyPhotoGalleryModel,
)
from app.infrastructure.database.my_photo_job_models import (
    MyPhotoJobModel as MyPhotoJobModel,
)
from app.infrastructure.database.my_photo_liveness_models import (
    MyPhotoLivenessSessionModel as MyPhotoLivenessSessionModel,
)
from app.infrastructure.database.my_photo_media_models import (
    MyPhotoAssetVariantModel as MyPhotoAssetVariantModel,
)
from app.infrastructure.database.my_photo_media_models import (
    MyPhotoMediaAssetModel as MyPhotoMediaAssetModel,
)
from app.infrastructure.database.my_photo_search_models import (
    MyPhotoMatchModel as MyPhotoMatchModel,
)
from app.infrastructure.database.my_photo_search_models import (
    MyPhotoSearchRunModel as MyPhotoSearchRunModel,
)

__all__ = [
    "MyPhotoAssetVariantModel",
    "MyPhotoDeliveryAuthorizationModel",
    "MyPhotoEnrollmentModel",
    "MyPhotoFaceOccurrenceModel",
    "MyPhotoGalleryModel",
    "MyPhotoJobModel",
    "MyPhotoLivenessSessionModel",
    "MyPhotoMatchModel",
    "MyPhotoMediaAssetModel",
    "MyPhotoSearchRunModel",
]
