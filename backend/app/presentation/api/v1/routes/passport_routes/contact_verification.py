"""Public contact-verification routes and stable submission authorization imports."""

from fastapi import APIRouter

from .contact_challenges import _locked_challenge as _locked_challenge
from .contact_challenges import _locked_upload as _locked_upload
from .contact_challenges import _no_store as _no_store
from .contact_completion import router as completion_router
from .contact_completion import verify_public_contact_otp as verify_public_contact_otp
from .contact_family import require_verified_family_head as require_verified_family_head
from .contact_issuance import request_public_contact_otp as request_public_contact_otp
from .contact_issuance import router as issuance_router
from .contact_submission_proof import require_public_contact_proof as require_public_contact_proof

router = APIRouter()
router.include_router(issuance_router)
router.include_router(completion_router)
