"""Controlled Fast restart evidence never becomes permission to accept crashes."""
from __future__ import annotations

import copy
import unittest
from unittest.mock import patch

import release_document_resume_baseline as baseline
from mcp_direct_build import BuildError
from mcp_direct_release import bound_original as bind_container
from release_document_retained_update import DocumentRetainedUpdate
from release_retained_update import ACTIVE
from test_release_document_retained_update import fixture


class ControlledResumeTests(unittest.TestCase):
    def setUp(self):
        self.release = fixture()
        self.release.mode = 'fast'
        del self.release.assert_writer_fence
        for index, row in enumerate(self.release.record['live'].values()):
            row['State'].update(StartedAt='2026-10-16T01:00:00.123456789Z', Pid=100 + index)
            row['RestartCount'] = 1 if row['Config']['Labels']['com.docker.compose.service'] == 'email-beat' else 0
            row.setdefault('Mounts', [])
        for row in self.release.record['candidates'].values():
            row['State'].update(Running=False)
            row.setdefault('Mounts', [])
        self.prior = copy.deepcopy(self.release.record['live'])
        rows = [*self.release.record['live'].values(), *self.release.record['candidates'].values()]
        self.current = {row['Id']: copy.deepcopy(row) for row in rows}
        self.release.record['inventory'] = copy.deepcopy(self.current)
        self.release.rows = lambda: [row for row in self.current.values() if row['State']['Running']]
        self.release.stop = self.stop
        self.release.start = self.start
        self.addCleanup(patch.stopall)
        # Execute the real immutable-binding check, mocking only Docker inspect.
        patch('mcp_direct_release.inspect', side_effect=lambda identifier, **_: self.current[identifier]).start()
        patch('release_document_resume_baseline.bound_original', side_effect=bind_container).start()
        patch('release_document_retained_update.bound_original', side_effect=bind_container).start()
        patch('release_retained_update.wait_for_idle').start()

    def stop(self, row):
        self.current[row['Id']]['State'].update(Running=False, Pid=0, ExitCode=0)

    def start(self, row):
        current = self.current[row['Id']]
        current['State'].update(Running=True, Pid=200, StartedAt='2026-10-16T02:00:00.123456789Z')
        current['RestartCount'] = 0

    def resume(self):
        with self.release.background_quiescence():
            self.assertFalse(any(self.current[self.prior[name]['Id']]['State']['Running'] for name in baseline.SERVICES))

    def fence(self):
        for name in ACTIVE:
            self.stop(self.prior[name])
        DocumentRetainedUpdate.assert_writer_fence(self.release)

    def test_actual_beat_one_to_zero_reset_passes_fence_and_preserves_originals(self):
        self.resume()
        self.assertEqual(self.release.record['live'], self.prior)
        self.assertEqual(self.release.record[baseline.SOURCE_KEY]['processes']['email-beat']['restart_count'], 1)
        self.assertEqual(self.release.record[baseline.RESUME_KEY]['processes']['email-beat']['restart_count'], 0)
        self.fence()
        self.assertEqual(self.release.record['live'], self.prior)

    def test_full_path_retains_existing_strict_comparison_without_new_receipts(self):
        self.release.mode = 'full'
        with self.release.background_quiescence():
            pass
        self.assertNotIn(baseline.SOURCE_KEY, self.release.record)
        self.assertNotIn(baseline.RESUME_KEY, self.release.record)
        with self.assertRaisesRegex(BuildError, 'application_not_cleanly_drained'):
            self.fence()

    def test_preexisting_process_drift_blocks_before_any_stop(self):
        current = self.current[self.prior['email-beat']['Id']]
        current['RestartCount'] = 2
        with self.assertRaisesRegex(ValueError, 'background_source_process_changed'):
            self.resume()
        self.assertTrue(all(self.current[self.prior[name]['Id']]['State']['Running'] for name in baseline.SERVICES))
        self.assertNotIn(baseline.SOURCE_KEY, self.release.record)

    def assert_failed_resume(self, change):
        def start(row):
            self.start(row)
            current = self.current[row['Id']]
            if change == 'restart':
                current['RestartCount'] = 2
            else:
                current['State']['OOMKilled'] = True
        self.release.start = start
        with self.assertRaisesRegex(ValueError, 'background_resume_restart_or_oom'):
            self.resume()
        self.assertNotIn(baseline.RESUME_KEY, self.release.record)

    def test_increased_counter_does_not_create_post_resume_evidence(self):
        self.assert_failed_resume('restart')

    def test_new_oom_does_not_create_post_resume_evidence(self):
        self.assert_failed_resume('oom')

    def test_historical_one_then_reset_and_new_one_is_not_a_clean_resume(self):
        def start(row):
            self.start(row)
            if row['Id'] == self.prior['email-beat']['Id']:
                self.current[row['Id']]['RestartCount'] = 1
        self.release.start = start
        with self.assertRaisesRegex(ValueError, 'background_resume_restart_or_oom'):
            self.resume()
        self.assertNotIn(baseline.RESUME_KEY, self.release.record)

    def test_historical_oom_cannot_authorize_new_oom_after_controlled_start(self):
        identifier = self.prior['email-beat']['Id']
        self.release.record['live']['email-beat']['State']['OOMKilled'] = True
        self.current[identifier]['State']['OOMKilled'] = True
        def start(row):
            self.start(row)
            if row['Id'] == identifier:
                self.current[row['Id']]['State']['OOMKilled'] = True
        self.release.start = start
        with self.assertRaisesRegex(ValueError, 'background_resume_restart_or_oom'):
            self.resume()
        self.assertNotIn(baseline.RESUME_KEY, self.release.record)

    def test_immutable_configuration_drift_blocks_post_resume_receipt(self):
        with self.assertRaisesRegex(BuildError, 'original_container_configuration_changed'), \
             self.release.background_quiescence():
            self.current[self.prior['email-beat']['Id']]['Config']['Cmd'] = ['changed']
        self.assertNotIn(baseline.RESUME_KEY, self.release.record)

    def test_failed_build_never_creates_successful_restart_receipt(self):
        with self.assertRaisesRegex(ValueError, 'synthetic_build_failed'), self.release.background_quiescence():
            raise ValueError('synthetic_build_failed')
        self.assertIn(baseline.SOURCE_KEY, self.release.record)
        self.assertNotIn(baseline.RESUME_KEY, self.release.record)
        with self.assertRaisesRegex(ValueError, 'background_restart_receipt_binding_changed'):
            self.fence()

    def test_outside_restart_during_build_cannot_create_controlled_resume_authority(self):
        with self.assertRaisesRegex(ValueError, 'background_process_restarted_during_build'), \
             self.release.background_quiescence():
            row = self.current[self.prior['worker']['Id']]
            row['State']['StartedAt'] = '2026-10-16T01:30:00.123456789Z'
        self.assertNotIn(baseline.RESUME_KEY, self.release.record)

    def test_later_restart_even_with_zero_count_is_rejected(self):
        self.resume()
        current = self.current[self.prior['email-beat']['Id']]
        current['State']['StartedAt'] = '2026-10-16T03:00:00.123456789Z'
        with self.assertRaisesRegex(ValueError, 'background_process_restarted_after_resume'):
            self.fence()

    def test_later_restart_count_or_oom_retains_clean_stop_failure(self):
        self.resume()
        current = self.current[self.prior['email-beat']['Id']]
        current['RestartCount'] = 1
        with self.assertRaisesRegex(ValueError, 'background_process_restarted_after_resume'):
            self.fence()
        current['RestartCount'] = 0
        current['State']['OOMKilled'] = True
        with self.assertRaisesRegex(BuildError, 'application_not_cleanly_drained'):
            self.fence()

    def test_other_service_counter_is_never_normalized(self):
        self.resume()
        self.current[self.prior['backend']['Id']]['RestartCount'] = 1
        with self.assertRaisesRegex(BuildError, 'application_not_cleanly_drained'):
            self.fence()

    def test_tampered_resume_and_foreign_attempt_receipts_are_rejected(self):
        self.resume()
        evidence = self.release.record[baseline.RESUME_KEY]
        evidence['processes']['email-beat']['restart_count'] = 1
        with self.assertRaisesRegex(ValueError, 'background_restart_receipt_changed'):
            self.fence()
        evidence['processes']['email-beat']['restart_count'] = 0
        self.release.project = 'foreign-attempt'
        with self.assertRaisesRegex(ValueError, 'background_restart_source_binding_changed'):
            self.fence()

    def test_same_schema_path_never_creates_additive_restart_authority(self):
        self.release.record['additive_release'] = False
        with self.release.background_quiescence():
            pass
        self.assertNotIn(baseline.RESUME_KEY, self.release.record)


if __name__ == '__main__':
    unittest.main()
