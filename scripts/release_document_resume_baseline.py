"""Bind the document Fast build's intentional worker stop/start separately.

Docker can reset historical RestartCount to zero on an explicit start. Preserve
the original inspection and accept that reset only for the recorded controlled
restart; a later restart, new OOM or immutable configuration change still fails.
"""
from __future__ import annotations

from datetime import datetime

from mcp_direct_activate import clean_stop
from mcp_direct_release import bound_original
from mcp_direct_state import WORKERS
from release_mcp_database import digest_json
from release_retained_update import require

SERVICES = {*WORKERS, 'email-beat'}
SOURCE_KEY = 'document_background_quiescence'
RESUME_KEY = 'document_background_resume'


def process(row: dict) -> dict:
    state = row['State']
    result = {'started_at': state.get('StartedAt'), 'pid': state.get('Pid'),
              'restart_count': row.get('RestartCount', 0), 'oom_killed': state.get('OOMKilled')}
    require(isinstance(result['started_at'], str) and bool(result['started_at'])
            and type(result['pid']) is int and result['pid'] > 0
            and type(result['restart_count']) is int and result['restart_count'] >= 0
            and type(result['oom_killed']) is bool, 'background_process_identity_invalid')
    return result


def binding(release) -> dict:
    return {'version': 1, 'revision': release.revision, 'source': str(release.source), 'project': release.project,
            'originals_sha256': digest_json({name: release.record['live'][name] for name in sorted(SERVICES)})}


def capture_background_source(release) -> None:
    require(SOURCE_KEY not in release.record and RESUME_KEY not in release.record,
            'background_restart_baseline_already_exists')
    processes = {}
    for name in sorted(SERVICES):
        original = release.record['live'][name]
        current = bound_original(original)
        require(current['State'].get('Running') is True
                and digest_json(process(current)) == digest_json(process(original)),
                'background_source_process_changed')
        processes[name] = process(current)
    release.event('background-quiescence-bound', **{SOURCE_KEY: {**binding(release), 'processes': processes}})


def verify_resume(before: dict, after: dict) -> None:
    require(set(before) == set(after) == {'started_at', 'pid', 'restart_count', 'oom_killed'},
            'background_resume_process_invalid')
    # Reuse strict typed validation for retained snapshots, without trusting a
    # receipt's booleans as integer restart counts.
    for row in (before, after):
        process({'State': {'StartedAt': row['started_at'], 'Pid': row['pid'], 'OOMKilled': row['oom_killed']},
                 'RestartCount': row['restart_count']})
    # Explicit Docker start resets both fields. An equal historical nonzero
    # count/flag could instead be a new failure after that reset, so it cannot
    # authorize the fresh process merely because the old process had it too.
    require(after['restart_count'] == 0 and after['oom_killed'] is False,
            'background_resume_restart_or_oom')
    try:
        old_time = datetime.fromisoformat(before['started_at'].replace('Z', '+00:00'))
        new_time = datetime.fromisoformat(after['started_at'].replace('Z', '+00:00'))
        changed = old_time.tzinfo is not None and new_time.tzinfo is not None and new_time > old_time
    except (TypeError, ValueError):
        changed = False
    require(changed, 'background_resume_start_identity_changed')


def validate_source(release) -> dict:
    source = release.record.get(SOURCE_KEY)
    expected = {**binding(release), 'processes': {
        name: process(release.record['live'][name]) for name in sorted(SERVICES)}}
    require(digest_json(source) == digest_json(expected), 'background_restart_source_binding_changed')
    return expected


def verify_background_stopped(release) -> None:
    source = validate_source(release)
    for name in sorted(SERVICES):
        original = release.record['live'][name]
        current = bound_original(original)
        clean_stop(current, original)
        require(current['State'].get('StartedAt') == source['processes'][name]['started_at'],
                'background_process_restarted_during_build')


def capture_background_resume(release) -> None:
    source = validate_source(release)
    require(RESUME_KEY not in release.record, 'background_restart_baseline_already_exists')
    processes = {}
    for name in sorted(SERVICES):
        current = bound_original(release.record['live'][name])
        require(current['State'].get('Running') is True, 'background_resume_not_running')
        processes[name] = process(current)
        verify_resume(source['processes'][name], processes[name])
    payload = {'source_sha256': digest_json(source), 'processes': processes}
    release.event('background-resume-verified', **{RESUME_KEY: {**payload, 'sha256': digest_json(payload)}})


def fence_baseline(release, name: str, current: dict) -> dict:
    original = release.record['live'][name]
    if SOURCE_KEY not in release.record and RESUME_KEY not in release.record:
        return original
    source = validate_source(release)
    resume = release.record.get(RESUME_KEY)
    require(isinstance(resume, dict) and set(resume) == {'source_sha256', 'processes', 'sha256'}
            and resume['source_sha256'] == digest_json(source)
            and isinstance(resume['processes'], dict) and set(resume['processes']) == SERVICES,
            'background_restart_receipt_binding_changed')
    payload = {key: value for key, value in resume.items() if key != 'sha256'}
    require(resume['sha256'] == digest_json(payload), 'background_restart_receipt_changed')
    for service in SERVICES:
        verify_resume(source['processes'][service], resume['processes'][service])
    if name not in SERVICES:
        return original
    after = resume['processes'][name]
    require(current['Id'] == original['Id'] and current['State'].get('StartedAt') == after['started_at']
            and type(current.get('RestartCount')) is int and current['RestartCount'] == after['restart_count'],
            'background_process_restarted_after_resume')
    # Only clean_stop's comparison baseline changes. Original receipts and
    # their immutable container/DB/image bindings remain untouched.
    return {**original, 'RestartCount': after['restart_count'],
            'State': {**original['State'], 'StartedAt': after['started_at'], 'OOMKilled': after['oom_killed']}}
