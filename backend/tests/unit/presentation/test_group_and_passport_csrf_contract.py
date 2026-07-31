from __future__ import annotations

import inspect

from fastapi.params import Depends

from app.presentation.api.v1.routes.client_groups import (
    create_client_group,
    delete_client_group,
    permanently_delete_client_group,
    replace_client_group_whatsapp_links,
    restore_client_group,
    revoke_client_group,
    update_client_group,
)
from app.presentation.api.v1.routes.passports import (
    cancel_passport_processing,
    import_passports_by_group,
    reextract_passport,
    save_passport_documents_by_group,
)
from app.presentation.dependencies.csrf import require_cookie_csrf


def test_authenticated_group_and_passport_mutations_require_cookie_csrf() -> None:
    mutation_endpoints = (
        create_client_group,
        replace_client_group_whatsapp_links,
        revoke_client_group,
        update_client_group,
        delete_client_group,
        permanently_delete_client_group,
        restore_client_group,
        import_passports_by_group,
        save_passport_documents_by_group,
        reextract_passport,
        cancel_passport_processing,
    )

    for endpoint in mutation_endpoints:
        csrf_parameter = inspect.signature(endpoint).parameters["_csrf"]
        dependency = csrf_parameter.default
        assert isinstance(dependency, Depends), endpoint.__name__
        assert dependency.dependency is require_cookie_csrf, endpoint.__name__
