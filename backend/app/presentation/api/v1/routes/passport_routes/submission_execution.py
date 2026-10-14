"""One typed invocation of the ordinary collection validation use case."""
import uuid

from app.application.dtos.passport_dtos import PassportSubmissionOutputDTO
from app.application.use_cases.passports.client_submit_passport_use_case import (
    ClientSubmitPassportUseCase,
)
from app.presentation.api.v1.schemas.passport_schemas import ClientSubmitPassportRequest


async def execute_client_review(use_case: ClientSubmitPassportUseCase, submission_id: uuid.UUID,
    body: ClientSubmitPassportRequest,
) -> PassportSubmissionOutputDTO:
    return await use_case.execute(
            submission_id,
            group_token=body.group_token,
            confirmed_fields=body.confirmed_fields,
            client_email=str(body.client_email) if body.client_email else None,
            client_phone=body.client_phone,
            departure_city=body.departure_city,
            nearest_domestic_airport=body.nearest_domestic_airport,
            base_city=body.base_city,
            staff_code=body.staff_code,
            agent_employee_type=body.agent_employee_type,
            agent_employee_code=body.agent_employee_code,
            designation=body.designation,
            agency_dealership_name=body.agency_dealership_name,
            meal_preference=body.meal_preference,
            submission_mode=body.submission_mode,
            family_group_id=body.family_group_id,
            family_member_index=body.family_member_index,
            family_relation=body.family_relation,
            family_gender=body.family_gender,
            family_head_name=body.family_head_name,
            family_head_email=str(body.family_head_email) if body.family_head_email else None,
            family_head_phone=body.family_head_phone,
            custom_answers=[answer.model_dump(mode="json") for answer in body.custom_answers],
            custom_detail_answers=[
                answer.model_dump(mode="json") for answer in body.custom_detail_answers
            ],
        )
