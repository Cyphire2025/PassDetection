"""Migration admission and recovery must fail closed without touching a VPS."""
from __future__ import annotations

import copy
import json
from pathlib import Path
import sys
import tempfile
import unittest
from unittest.mock import Mock, patch

from release_workspace_branding import WorkspaceBrandingUpdate
from release_workspace_branding_contract import SOURCE, TARGET, source_contract, validate_contract
from release_workspace_branding_policy import BASE, REVIEWED_FILES, digest, validate_source

ROOT = Path(__file__).resolve().parents[1]


class BrandingReleaseTests(unittest.TestCase):
    def test_scheduler_resume_requires_a_tick_from_the_current_process(self):
        release = WorkspaceBrandingUpdate.__new__(WorkspaceBrandingUpdate)
        release.record = {'live': {'email-beat': {'Id': 'bound-scheduler'}}}
        release.pause_email_and_photos = True
        release.event = Mock()
        current = {'State': {'Running': True, 'StartedAt': '2026-10-18T00:00:00Z', 'Pid': 123, 'OOMKilled': False}}
        marker = 'Scheduler: Sending due task record-platform-scheduler-heartbeat (platform.scheduler_heartbeat)'
        with patch('release_workspace_branding.bound_original', return_value=current), \
             patch('release_workspace_branding.command', side_effect=['celery is starting', marker]) as command, \
             patch('release_workspace_branding.time.sleep') as sleep:
            release.wait_resumed_scheduler()
        self.assertEqual(command.call_args.args, ('docker', 'logs', '--since', current['State']['StartedAt'], '--tail', '200', 'bound-scheduler'))
        sleep.assert_called_once_with(3)
        self.assertTrue(release.event.call_args.kwargs['scheduler_resume']['fresh_scheduling_tick'])

    def test_scheduler_restart_while_waiting_fails_closed(self):
        release = WorkspaceBrandingUpdate.__new__(WorkspaceBrandingUpdate)
        release.record = {'live': {'email-beat': {'Id': 'bound-scheduler'}}}
        first = {'State': {'Running': True, 'StartedAt': 'start', 'Pid': 123, 'OOMKilled': False}}
        changed = copy.deepcopy(first)
        changed['State']['Pid'] = 456
        with patch('release_workspace_branding.bound_original', side_effect=[first, changed]), \
             patch('release_workspace_branding.command') as command:
            with self.assertRaisesRegex(ValueError, 'resumed_scheduler_process_changed'):
                release.wait_resumed_scheduler()
        command.assert_not_called()

    def test_fresh_process_can_resume_an_additive_attempt(self):
        release = WorkspaceBrandingUpdate.__new__(WorkspaceBrandingUpdate)
        self.assertFalse(release.installed)
        self.assertEqual(release.initial_schema(), SOURCE)

    def test_actual_contract_and_reviewed_file_hashes(self):
        value = source_contract(ROOT)
        validate_contract(value, TARGET)
        self.assertEqual(value['migrations'][0]['parent'], SOURCE)
        for path, (_, expected) in REVIEWED_FILES.items():
            self.assertEqual(digest((ROOT / path).read_text('utf-8')), expected, path)
        for key in value:
            changed = copy.deepcopy(value)
            changed[key] = None
            with self.subTest(key=key), self.assertRaises((ValueError, TypeError)):
                validate_contract(changed, TARGET)

    def test_wrong_live_baseline_rejected_before_git(self):
        with patch('release_workspace_branding_policy.command') as command:
            with self.assertRaisesRegex(ValueError, 'exact_installed'):
                validate_source(ROOT, 'a' * 40, 'b' * 40)
            command.assert_not_called()

    def test_unreviewed_persistent_path_rejected(self):
        def git(*args):
            if 'rev-parse' in args:
                return 'b' * 40
            if 'diff' in args:
                return 'backend/app/core/config/database.py'
            return ''
        with patch('release_workspace_branding_policy.command', side_effect=git):
            with self.assertRaisesRegex(ValueError, 'unreviewed_branding_persistent'):
                validate_source(ROOT, BASE, 'b' * 40)

    def test_running_migration_helper_prevents_any_recovery_action(self):
        release = WorkspaceBrandingUpdate.__new__(WorkspaceBrandingUpdate)
        release.record = {'branding_rehearsal': {}, 'migration_helpers': [{'Id': 'retained'}]}
        release.schema = Mock()
        release.stop = Mock()
        with patch('release_workspace_branding.bound_migration_helper', return_value={'State': {'Running': True}}):
            with self.assertRaisesRegex(ValueError, 'migration_helper_still_running'):
                release.recover()
        release.stop.assert_not_called()
        release.schema.assert_not_called()

    def test_source_failure_recovers_originals_only_when_no_helper_is_running(self):
        release = WorkspaceBrandingUpdate.__new__(WorkspaceBrandingUpdate)
        release.record = {'branding_rehearsal': {}, 'schema': SOURCE, 'migration_in_progress': True}
        release.schema = lambda: SOURCE
        with patch('release_retained_update.RetainedUpdate.recover') as recover:
            release.recover()
            recover.assert_called_once()
        self.assertFalse(release.record['migration_in_progress'])

    def test_target_failure_never_calls_original_writer_recovery(self):
        release = WorkspaceBrandingUpdate.__new__(WorkspaceBrandingUpdate)
        release.record = {'branding_rehearsal': {}, 'candidates': {}, 'live': {}}
        release.schema = lambda: TARGET
        release.event = Mock()
        with patch('release_retained_update.RetainedUpdate.recover') as recover:
            with self.assertRaises(KeyError):
                release.recover()
            recover.assert_not_called()


if __name__ == '__main__':
    unittest.main()
