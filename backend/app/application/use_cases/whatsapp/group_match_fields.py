"""Stable field vocabularies and exact evidence weights for roster matching."""

from __future__ import annotations

_EMAIL_KEYS = frozenset({"email", "email_address", "e_mail", "mail"})


_PASSPORT_KEYS = frozenset({"passport", "passport_no", "passport_number", "passportnumber"})


_STAFF_CODE_KEYS = frozenset(
    {
        "employee_code",
        "staff_code",
        "staff_id",
        "staffcode",
    }
)


_GIVEN_NAME_KEYS = frozenset({"first_name", "given_name", "given_names"})


_SURNAME_KEYS = frozenset({"family_name", "last_name", "surname"})


_NAME_KEYS = frozenset(
    {
        "client_name",
        "employee_name",
        "full_name",
        "name",
        "passenger_name",
        "recipient_name",
        "staff_name",
        "staffname",
    }
)


_PHONE_KEYS = frozenset(
    {
        "contact",
        "contact_number",
        "mobile",
        "mobile_number",
        "phone",
        "phone_number",
        "telephone",
        "whatsapp",
        "whatsapp_number",
    }
)


_STRONG_EVIDENCE_WEIGHTS = {
    "passport_number": 120,
    "staff_code": 110,
    "email": 100,
    "phone": 100,
}


_NAME_EVIDENCE_WEIGHT = 20


_SELECTED_FIELD_EVIDENCE_WEIGHT = 100


_PRIVATE_SELECTED_FIELD_KEYS = frozenset(
    {
        "phone_number",
        "email",
        "passport_number",
        "staff_code",
    }
)


_MATCH_FIELD_KEY_ALIASES = {
    "client_name": "name",
    "contact_name": "name",
    "employee_name": "name",
    "full_name": "name",
    "passenger_name": "name",
    "recipient_name": "name",
    "staff_name": "name",
    "staffname": "name",
    "contact": "phone_number",
    "contact_no": "phone_number",
    "contact_number": "phone_number",
    "mobile": "phone_number",
    "mobile_no": "phone_number",
    "mobile_number": "phone_number",
    "phone": "phone_number",
    "phone_no": "phone_number",
    "telephone": "phone_number",
    "whatsapp": "phone_number",
    "whatsapp_no": "phone_number",
    "whatsapp_number": "phone_number",
    "verified_whatsapp_number": "phone_number",
    "verified_whatsapp_numbers": "phone_number",
    "email_address": "email",
    "e_mail": "email",
    "mail": "email",
    "passport": "passport_number",
    "passport_no": "passport_number",
    "passportnumber": "passport_number",
    "employee_code": "staff_code",
    "staff_id": "staff_code",
    "staffcode": "staff_code",
    "producer_code": "agent_employee_code",
    "agent_code": "agent_employee_code",
    "agentcode": "agent_employee_code",
    "dealer_code": "agent_employee_code",
    "agency_name": "agency_dealership_name",
    "agent_company": "agency_dealership_name",
    "company": "agency_dealership_name",
    "company_name": "agency_dealership_name",
    "birth_date": "date_of_birth",
    "birthdate": "date_of_birth",
    "dob": "date_of_birth",
}


_MATCH_DATE_FIELD_KEYS = frozenset(
    {
        "date_of_birth",
        "birth_date",
        "birthdate",
        "dob",
    }
)


_MATCH_IDENTIFIER_FIELD_KEYS = frozenset(
    {
        "agent_employee_code",
        "employee_code",
        "passport",
        "passport_no",
        "passport_number",
        "passportnumber",
        "staff_code",
        "staff_id",
    }
)


_MISSING_MATCH_VALUES = frozenset(
    {
        "",
        "n a",
        "na",
        "nil",
        "none",
        "not applicable",
        "not available",
        "null",
    }
)
