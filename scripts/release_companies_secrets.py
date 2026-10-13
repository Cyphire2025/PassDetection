"""Provision first-install reuse keys without granting any person/company permission.

The private key file stays with the retained attempt and is never a CI artifact.
Existing configured keys are preserved. Recovery validates the same file; it never
generates replacement keys for already encrypted identity data.
"""
from __future__ import annotations

import base64
import hashlib
import json
import os
import secrets
import stat
from pathlib import Path
from typing import Any, Protocol, cast

from release_code_update import environment
from release_companies_traveller_contract import SOURCE
from release_retained_update import require

PREFIX = 'TRAVELLER_REUSE_'
KEYS = frozenset(PREFIX + name for name in ('LOOKUP_KEY', 'ENCRYPTION_KEY', 'KEY_VERSION', 'DISCLOSURE_ENABLED'))
KEY_FILE = 'traveller-runtime-keys.private.json'


class SecretRelease(Protocol):
    directory: Path
    record: dict[str, Any]

    def event(self, phase: str, **values: Any) -> None: ...


def validate_values(values: dict[str, str]) -> None:
    require(set(values) == KEYS and all(isinstance(value, str) for value in values.values()),
            'reuse_runtime_configuration_incomplete')
    require(len(values[PREFIX + 'LOOKUP_KEY']) >= 32 and 1 <= len(values[PREFIX + 'KEY_VERSION']) <= 32,
            'reuse_runtime_key_invalid')
    try:
        encryption = base64.b64decode(values[PREFIX + 'ENCRYPTION_KEY'], altchars=b'-_', validate=True)
    except (ValueError, UnicodeError):
        raise ValueError('reuse_runtime_key_invalid') from None
    require(len(encryption) == 32 and values[PREFIX + 'DISCLOSURE_ENABLED'] in {'true', 'false'},
            'reuse_runtime_key_invalid')


def verify_configuration(release: SecretRelease) -> dict[str, str]:
    """Read only the exact retained private file, including during recovery."""
    binding = release.record.get('traveller_runtime_configuration')
    require(isinstance(binding, dict) and binding.get('file') == KEY_FILE, 'reuse_runtime_receipt_required')
    binding = cast(dict[str, Any], binding)
    path = release.directory / KEY_FILE
    require(not path.is_symlink(), 'reuse_runtime_key_file_invalid')
    with os.fdopen(os.open(path, os.O_RDONLY | getattr(os, 'O_NOFOLLOW', 0)), 'rb') as stream:
        info = os.fstat(stream.fileno())
        require(stat.S_ISREG(info.st_mode) and info.st_nlink == 1 and 0 < info.st_size <= 4096,
                'reuse_runtime_key_file_invalid')
        if os.name == 'posix':
            require(info.st_uid == getattr(os, 'geteuid', lambda: -1)() and not (info.st_mode & 0o077),
                    'reuse_runtime_key_file_permissions')
        raw = stream.read(4097)
        require(len(raw) <= 4096, 'reuse_runtime_key_file_invalid')
    require(hashlib.sha256(raw).hexdigest() == binding.get('sha256'), 'reuse_runtime_key_binding_changed')
    values = json.loads(raw)
    require(isinstance(values, dict), 'reuse_runtime_configuration_incomplete')
    validate_values(values)
    return cast(dict[str, str], values)


def runtime_values(release: SecretRelease, original: dict[str, Any]) -> dict[str, str]:
    """O(application services) one-time checks; constant-size key material."""
    if original['Config']['Labels']['com.docker.compose.service'] in {'frontend', 'nginx'}:
        return {}
    if 'traveller_runtime_configuration' in release.record:
        return verify_configuration(release)
    require(release.record.get('additive_release') is True and release.record.get('schema') == SOURCE,
            'reuse_key_provisioning_requires_first_install')
    configured: list[dict[str, str] | None] = []
    for name, row in release.record['live'].items():
        if name in {'backend', 'email-beat'} or name.endswith('worker'):
            values = environment(row)
            selected = {key: values[key] for key in KEYS if key in values}
            if selected:
                validate_values(selected)
                configured.append(selected)
            else:
                configured.append(None)
    require(bool(configured) and (all(value is None for value in configured)
                           or all(value == configured[0] and value is not None for value in configured)),
            'reuse_runtime_configuration_differs_between_services')
    values = configured[0] or {
        PREFIX + 'LOOKUP_KEY': secrets.token_urlsafe(48),
        PREFIX + 'ENCRYPTION_KEY': base64.urlsafe_b64encode(secrets.token_bytes(32)).decode('ascii'),
        PREFIX + 'KEY_VERSION': 'v1', PREFIX + 'DISCLOSURE_ENABLED': 'true',
    }
    raw = (json.dumps(values, sort_keys=True) + '\n').encode('ascii')
    path = release.directory / KEY_FILE
    # An orphan file from an interrupted write requires operator inspection.
    # Never overwrite it or quietly replace keys during a retry.
    with os.fdopen(os.open(path, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600), 'wb') as stream:
        stream.write(raw)
        stream.flush()
        os.fsync(stream.fileno())
    release.event('traveller-runtime-configuration-retained', traveller_runtime_configuration={
        'file': KEY_FILE, 'sha256': hashlib.sha256(raw).hexdigest(),
        'new_keys_provisioned': configured[0] is None,
        'disclosure_enabled': values[PREFIX + 'DISCLOSURE_ENABLED'] == 'true',
        'company_group_and_person_permission_required': True,
    })
    return verify_configuration(release)
