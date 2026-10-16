"""Explicit, reversible email/My Photos pause funding a 3.5 GiB PDF backend.

The shared platform scheduler remains active. No other container ceiling, queue,
volume, database schema or provider credential changes under this profile.
"""
from __future__ import annotations

import copy
from urllib.parse import urlencode

from mcp_direct_containers import clone_payload

MIB = 1024**2
PAUSED = frozenset({'email-worker', 'email-ai-worker', 'my-photos-worker'})
BACKEND_MIB = 3584
LABEL = 'globalconnects.runtime-profile'
PROFILE = 'pdf-checking-email-photos-paused-v1'
DISABLED = {
    'EMAIL_INTEGRATIONS_ENABLED': 'false',
    'EMAIL_SYNC_ENABLED': 'false',
    'EMAIL_ATTACHMENT_PROCESSING_ENABLED': 'false',
    'EMAIL_LINK_RETRIEVAL_ENABLED': 'false',
    'EMAIL_AUTO_ACTIONS_ENABLED': 'false',
    'EMAIL_AI_ENABLED': 'false',
    'EMAIL_AI_NOTIFICATIONS_ENABLED': 'false',
    'MY_PHOTOS_LIVENESS_PROVIDER': 'disabled',
    'MY_PHOTOS_FACE_SEARCH_PROVIDER': 'disabled',
    'MY_PHOTOS_MEDIA_PROVIDER': 'disabled',
}


def planned_budget(live: dict, host_bytes: int) -> dict:
    """Count all serving containers and preserve the fixed 2 GiB host reserve."""
    if not PAUSED <= live.keys() or 'backend' not in live:
        raise ValueError('pdf_profile_inventory_incomplete')
    total = 0
    for name, row in live.items():
        memory = row['HostConfig'].get('Memory')
        if type(memory) is not int or memory <= 0:
            raise ValueError('pdf_profile_unbounded_container')
        if name == 'backend':
            if memory not in {2560 * MIB, BACKEND_MIB * MIB}:
                raise ValueError('pdf_profile_backend_baseline_changed')
            memory = BACKEND_MIB * MIB
        if name in PAUSED:
            if memory != 384 * MIB:
                raise ValueError('pdf_profile_paused_worker_baseline_changed')
            continue
        total += memory
    if total + 2048 * MIB > host_bytes:
        raise ValueError('pdf_profile_exceeds_host_reserve')
    return {'serving_container_bytes': total, 'host_reserve_bytes': 2048 * MIB,
            'host_memory_bytes': host_bytes, 'paused_services': sorted(PAUSED),
            'backend_memory_mib': BACKEND_MIB}


def create_candidate(client, original: dict, options: dict) -> str:
    payload = clone_payload(original, **options)
    name = original['Config']['Labels']['com.docker.compose.service']
    payload['Labels'][LABEL] = PROFILE
    if name == 'backend':
        if payload['HostConfig']['Memory'] not in {2560 * MIB, BACKEND_MIB * MIB}:
            raise ValueError('pdf_profile_backend_baseline_changed')
        payload['HostConfig'].update(Memory=BACKEND_MIB * MIB, MemorySwap=BACKEND_MIB * MIB)
    if name in PAUSED:
        payload['HostConfig']['RestartPolicy'] = {'Name': 'no', 'MaximumRetryCount': 0}
    result = client.request('POST', '/containers/create?' + urlencode({'name': options['name']}), payload)
    return client.identifier(result['Id'])


def live_inventory(running: list[dict], all_rows: list[dict]) -> list[dict]:
    """Include only this serving project's three deliberately stopped workers."""
    backend = [row for row in running if row['Config']['Labels'].get('com.docker.compose.service') == 'backend']
    if len(backend) != 1:
        raise ValueError('ambiguous_running_backend')
    project = backend[0]['Config']['Labels']['com.docker.compose.project']
    result = list(running)
    present = {row['Config']['Labels'].get('com.docker.compose.service') for row in running}
    for row in all_rows:
        labels = row['Config'].get('Labels') or {}
        name = labels.get('com.docker.compose.service')
        if (name in PAUSED - present and labels.get('com.docker.compose.project') == project
                and labels.get(LABEL) == PROFILE):
            result.append(copy.deepcopy(row))
    return result
