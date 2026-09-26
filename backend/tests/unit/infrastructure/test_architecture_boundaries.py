import importlib.util
import json
import subprocess
import sys
from datetime import date
from pathlib import Path


def checker():
    path = Path(__file__).resolve().parents[3] / "scripts/verify_architecture_boundaries.py"
    spec = importlib.util.spec_from_file_location("architecture_checker", path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def test_real_repository_obeys_reviewed_dependencies():
    assert checker().violations() == []


def test_function_local_relative_framework_and_dynamic_import_bypasses_are_rejected(tmp_path):
    application = tmp_path / "app/application"
    domain = tmp_path / "app/domain"
    application.mkdir(parents=True)
    domain.mkdir()
    (application / "bad.py").write_text(
        "def work():\n from ..presentation import api\n import fastapi\n"
        " return __import__('app.infrastructure.database')\n")
    (domain / "bad.py").write_text("from app.application import use_cases\n")
    policy = tmp_path / "policy.json"
    policy.write_text(json.dumps({"version": 1, "transaction_services": {}}))
    errors = checker().violations(tmp_path, policy)
    assert any("app.presentation" in error for error in errors)
    assert any("fastapi" in error for error in errors)
    assert any("dynamic import" in error for error in errors)
    assert any("app.application" in error for error in errors)


def test_infrastructure_allowances_cannot_expand_or_remain_after_expiry(tmp_path):
    application = tmp_path / "app/application"
    application.mkdir(parents=True)
    (application / "service.py").write_text("from app.infrastructure.database import models\n")
    policy = tmp_path / "policy.json"
    policy.write_text(json.dumps({"version": 1, "transaction_services": {
        "app/application/service.py": {"owner": "reviewer", "reason": "SQL scope",
            "review_by": "2026-09-01", "imports": ["app.infrastructure.database"]}}}))
    errors = checker().violations(tmp_path, policy, date(2026, 9, 27))
    assert any("expired" in error for error in errors)
    assert any("contract changed" in error for error in errors)


def test_notification_rules_execute_when_http_framework_imports_are_forbidden():
    script = '''
import importlib.abc, sys, uuid
from datetime import UTC, datetime, timedelta
class DenyHttp(importlib.abc.MetaPathFinder):
    def find_spec(self, fullname, path=None, target=None):
        if fullname.split('.')[0] in {'fastapi', 'starlette'}:
            raise AssertionError('Application attempted HTTP framework import: '+fullname)
sys.meta_path.insert(0, DenyHttp())
from app.application.dtos.gc_notifications import NotificationDraftInput
from app.application.dtos.mobile_security import MobilePushRegistrationRequest
from app.application.mobile.authored_notification_preview import create_preview_token, read_preview_token
from app.application.mobile.notification_errors import NotificationWorkflowError
draft = NotificationDraftInput(title='Synthetic', body='Body', audience='all_active_trips')
assert draft.group_ids == []
agency, actor, identifier = (uuid.uuid4() for _ in range(3))
scope = dict(agency_id=agency, actor_id=actor, draft_id=identifier, revision=2)
token = create_preview_token(**scope, fingerprint='a'*64, expires_at=datetime.now(UTC)+timedelta(minutes=2))
assert read_preview_token(token, **scope)[0] == 'a'*64
try: read_preview_token(token, **{**scope, 'actor_id': uuid.uuid4()})
except NotificationWorkflowError as error: assert error.category == 'conflict'
else: raise AssertionError('Wrong actor accepted')
assert not any(name.split('.')[0] in {'fastapi','starlette'} for name in sys.modules)
'''
    result = subprocess.run([sys.executable, "-c", script], cwd=Path(__file__).resolve().parents[3],
                            capture_output=True, text=True, timeout=30)
    assert result.returncode == 0, result.stderr
