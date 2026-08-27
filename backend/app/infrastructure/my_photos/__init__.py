"""Infrastructure adapters and durable runtime for My Photos."""

from app.infrastructure.my_photos.providers import MyPhotosProviderBundle, build_provider_bundle

MY_PHOTOS_SEARCH_QUEUE = "my_photos_search"
MY_PHOTOS_MEDIA_QUEUE = "my_photos_media"
MY_PHOTOS_INDEX_QUEUE = "my_photos_index"
MY_PHOTOS_CONTROL_QUEUE = "my_photos_control"
MY_PHOTOS_SEARCH_TASK = "my_photos.search_passenger"
MY_PHOTOS_INDEX_TASK = "my_photos.process_index_job"
MY_PHOTOS_MEDIA_TASK = "my_photos.process_media_job"
MY_PHOTOS_RECOVERY_TASK = "my_photos.recover_durable_jobs"

__all__ = [
    "MY_PHOTOS_INDEX_QUEUE",
    "MY_PHOTOS_CONTROL_QUEUE",
    "MY_PHOTOS_MEDIA_QUEUE",
    "MY_PHOTOS_SEARCH_QUEUE",
    "MY_PHOTOS_SEARCH_TASK",
    "MY_PHOTOS_INDEX_TASK",
    "MY_PHOTOS_MEDIA_TASK",
    "MY_PHOTOS_RECOVERY_TASK",
    "MyPhotosProviderBundle",
    "build_provider_bundle",
]
