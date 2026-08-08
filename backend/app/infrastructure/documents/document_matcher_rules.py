"""Bounded constants and deterministic rule vocabularies for document matching."""

MAX_PDF_PAGES_TO_INSPECT = 200
MAX_PDF_TEXT_LAYER_PAGES = 200
MAX_PDF_TOTAL_PAGES = 200
MAX_PDF_PAGE_TEXT_CHARS = 40_000
MAX_PDF_TEXT_CHARS = 120_000
MAX_PDF_SOURCE_BYTES = 16 * 1024 * 1024
MAX_PDF_PARSE_SECONDS = 3.0
MAX_PDF_OCR_SECONDS = 7.0
MAX_PDF_OCR_PAGES = 2
MAX_PDF_OCR_PIXELS = 4_000_000
PDF_OCR_RENDER_SCALE = 1.5
MAX_PASSENGER_NAMES = 12
MAX_PASSENGER_IDENTIFIERS = 96
MAX_SUPPLEMENTAL_IDENTIFIERS_PER_PASSENGER = 24
MAX_SUPPLEMENTAL_IDENTIFIERS_PER_REQUEST = 36_000
MAX_SUPPLEMENTAL_IDENTIFIER_INPUTS = 72_000
MAX_NAME_TOKENS = 8
MAX_FUZZY_CANDIDATES = 32
PDF_OCR_RETRY_REASON = "PDF OCR exceeded the temporary processing budget"


VISA_CORE_TERMS = (
    "visa",
    "evisa",
    "e-visa",
    "electronic visa",
    "entry permit",
    "visa grant",
    "grant notice",
)
VISA_IDENTITY_TERMS = (
    "visa number",
    "visa no",
    "visa type",
    "visa category",
    "grant number",
    "entry permit number",
    "travel document number",
)
VISA_VALIDITY_TERMS = (
    "number of entries",
    "multiple entries",
    "single entry",
    "valid from",
    "valid until",
    "date of issue",
    "date of expiry",
    "duration of stay",
    "permitted to stay",
)
VISA_AUTHORITY_TERMS = (
    "immigration",
    "ministry of interior",
    "ministry of public security",
    "department of immigration",
    "immigration department",
    "immigration authority",
    "vietnam immigration department",
)
VISA_APPLICATION_TERMS = (
    "application received",
    "application status",
    "application form",
    "application submitted",
    "appointment confirmation",
)
PAYMENT_TERMS = (
    "payment confirmation",
    "payment receipt",
    "fee charge payment",
    "application fee",
    "service fee",
    "transaction id",
    "payment details",
    "payment method",
    "total amount",
    "amount paid",
    "tax payment",
    "invoice",
    "receipt",
)

TICKET_CORE_TERMS = (
    "e-ticket",
    "electronic ticket",
    "flight ticket",
    "flight tickets",
    "itinerary",
    "travel summary",
    "ticket itinerary",
    "itinerary receipt",
    "passenger itinerary",
    "passenger receipt",
    "flight summary",
    "boarding pass",
    "booking confirmation",
    "ticket number",
    "ticket no",
)
TICKET_BOOKING_TERMS = (
    "pnr",
    "booking no",
    "booking number",
    "booking reference",
    "reservation code",
    "record locator",
)
TICKET_FLIGHT_TERMS = (
    "flight number",
    "flight no",
    "flight summary",
    "operated by",
    "airline",
    "carrier",
    "sector",
)
TICKET_ROUTE_TERMS = (
    "departure",
    "arrival",
    "departing",
    "origin",
    "destination",
)
TICKET_TRAVEL_TERMS = (
    "boarding",
    "check in",
    "check-in",
    "gate",
    "seat",
    "checked baggage",
    "carry-on baggage",
)
PASSPORT_TERMS = ("passport", "nationality", "place of birth", "date of expiry")

_PASSPORT_KEYS = frozenset(
    {"passport", "passport_no", "passport_num", "passport_number", "passportnumber"}
)
_GIVEN_NAME_KEYS = frozenset({"first_name", "forename", "given_name", "given_names"})
_SURNAME_KEYS = frozenset({"family_name", "last_name", "surname"})
_FULL_NAME_KEYS = frozenset(
    {
        "client_name",
        "employee_name",
        "full_name",
        "name",
        "passenger_name",
        "recipient_name",
        "staff_name",
        "staffname",
        "traveller_name",
        "traveler_name",
    }
)
_STAFF_CODE_KEYS = frozenset(
    {"employee_code", "employee_id", "staff_code", "staff_id", "staffcode"}
)
_AGENT_CODE_KEYS = frozenset({"agent_code", "agent_employee_code", "agent_id", "employee_code"})
_IDENTIFIER_KEY_TOKENS = frozenset(
    {"code", "id", "identifier", "no", "number", "ref", "reference", "serial"}
)
_IDENTIFIER_KEY_EXCLUSIONS = frozenset(
    {
        "agency_id",
        "batch_id",
        "broadcast_group_id",
        "booking_no",
        "booking_number",
        "booking_reference",
        "contact_no",
        "contact_number",
        "date_of_birth",
        "date_of_expiry",
        "date_of_issue",
        "detail_id",
        "document_id",
        "dob",
        "doe",
        "doi",
        "family_group_id",
        "group_id",
        "mobile_no",
        "mobile_number",
        "passenger_id",
        "passport_no",
        "passport_num",
        "passport_number",
        "phone_number",
        "pnr",
        "qualifier_selection_id",
        "question_id",
        "recipient_id",
        "row_number",
        "source_order",
        "source_row",
        "submission_id",
        "ticket_no",
        "ticket_number",
        "transaction_id",
    }
)
_DOCUMENT_FILENAME_WORDS = frozenset(
    {
        "document",
        "evisa",
        "flight",
        "itinerary",
        "pdf",
        "ticket",
        "visa",
    }
)
_NAME_NOISE_TOKENS = frozenset(
    {
        "adult",
        "arrival",
        "booking",
        "child",
        "date",
        "departure",
        "document",
        "female",
        "flight",
        "gender",
        "infant",
        "male",
        "miss",
        "mr",
        "mrs",
        "ms",
        "passenger",
        "passport",
        "ticket",
        "visa",
    }
)

_NON_TRAVEL_DOCUMENT_PATTERNS = (
    r"\b(?:thailand\s+)?digital\s+arrival\s+card\b",
    r"\bnot\s+(?:a|an)\s+(?:e-?visa|visa)\b",
    r"\b(?:visa\s+)?application\s+form\b",
    r"\bapplication\s+received\b",
    r"\bapplication\s+submitted\b",
    r"\bappointment\s+confirmation\b",
    r"\b(?:travel\s+|insurance\s+|travel\s+insurance\s+)?claim\s+form\b",
    r"\btravel\s+insurance\s+claim\b",
    r"\b(?:price\s+)?quotation\b",
    r"\bprice\s+quote\b",
    r"\bpro\s+forma\s+invoice\b",
    r"\b(?:blank|sample)\s+(?:application|claim|form|template)\b",
)

_DATE_VALUE_PATTERN = (
    r"(?:\d{1,4}[./-]\d{1,2}[./-]\d{1,4}"
    r"|\d{1,2}\s+[^\W\d_]{3,15}\s+\d{2,4}"
    r"|[^\W\d_]{3,15}\s+\d{1,2},?\s+\d{2,4})"
)
