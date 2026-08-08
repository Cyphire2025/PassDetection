from sqlalchemy.orm import configure_mappers

from app.infrastructure.database import (
    communications_models,
    document_models,
    model_base,
    models,
    operations_models,
)


def test_model_facade_keeps_the_shared_registry() -> None:
    assert models.Base is model_base.Base
    assert models.JSONB is model_base.JSONB

    configure_mappers()

    assert len(models.Base.registry.mappers) == len(models.Base.metadata.tables)
    assert len(models.Base.metadata.tables) >= 43


def test_operations_models_remain_available_from_the_stable_facade() -> None:
    names = (
        "AttendanceRecordModel",
        "AttendanceSessionModel",
        "PassengerQRTokenModel",
        "PassengerQrWhatsAppDeliveryModel",
        "RoomingAssignmentModel",
        "RoomingCheckinModel",
        "RoomingHotelModel",
        "RoomingHotelPassengerModel",
        "RoomingPassengerPreferenceModel",
        "RoomingRoomModel",
    )

    for name in names:
        assert getattr(models, name) is getattr(operations_models, name)


def test_operations_tables_share_the_facade_metadata() -> None:
    table_names = {
        "attendance_records",
        "attendance_sessions",
        "passenger_qr_tokens",
        "passenger_qr_whatsapp_deliveries",
        "rooming_assignments",
        "rooming_checkins",
        "rooming_hotel_passengers",
        "rooming_hotels",
        "rooming_passenger_preferences",
        "rooming_rooms",
    }

    assert table_names <= set(models.Base.metadata.tables)


def test_communications_and_document_models_remain_facade_exports() -> None:
    module_names = {
        communications_models: (
            "WhatsAppBroadcastGroupModel",
            "WhatsAppBroadcastRecipientModel",
            "WhatsAppBroadcastRejectedContactModel",
            "WhatsAppBroadcastSupportContactModel",
            "WhatsAppMessageLogModel",
            "WhatsAppRecipientMessageStateModel",
        ),
        document_models: (
            "DistributedDocumentModel",
            "DocumentDistributionBatchModel",
            "DocumentRenameBatchModel",
            "DocumentRenameItemModel",
            "DocumentUploadChunkModel",
            "DocumentWhatsAppDeliveryModel",
            "StorageCleanupJobModel",
        ),
    }

    for module, names in module_names.items():
        for name in names:
            assert getattr(models, name) is getattr(module, name)


def test_communications_and_document_tables_share_the_facade_metadata() -> None:
    table_names = {
        "distributed_documents",
        "document_distribution_batches",
        "document_rename_batches",
        "document_rename_items",
        "document_upload_chunks",
        "document_whatsapp_deliveries",
        "storage_cleanup_jobs",
        "whatsapp_broadcast_groups",
        "whatsapp_broadcast_recipients",
        "whatsapp_broadcast_rejected_contacts",
        "whatsapp_broadcast_support_contacts",
        "whatsapp_message_logs",
        "whatsapp_recipient_message_states",
    }

    assert table_names <= set(models.Base.metadata.tables)
