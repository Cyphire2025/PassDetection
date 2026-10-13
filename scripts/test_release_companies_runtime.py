"""Migration receipt framing: real local subprocess streams, no Docker or DB."""
from __future__ import annotations

import json
import subprocess
import sys
import unittest
from unittest.mock import patch

from release_companies_runtime import migration_stdout, read_migration_result

RECEIPT = {'status': 'upgraded', 'preservation_sha256': 'a' * 64,
           'release_proof_sha256': 'b' * 64, 'new_tables_empty': True,
           'runtime_grants_verified': True, 'automatic_downgrade': False}


class MigrationReceiptStreams(unittest.TestCase):
    def process(self, script):
        original = subprocess.Popen

        def launch(arguments, **kwargs):
            self.assertEqual(arguments, ['docker', 'logs', 'immutable-helper-id'])
            self.assertEqual(kwargs['stderr'], subprocess.DEVNULL)
            return original([sys.executable, '-B', '-c', script], **kwargs)

        return patch('release_companies_runtime.subprocess.Popen', side_effect=launch)

    def test_successful_upgrade_receipt_ignores_before_and_after_alembic_stderr(self):
        script = (
            'import sys; print("INFO [alembic.runtime] before",file=sys.stderr); '
            f'print({json.dumps(json.dumps(RECEIPT))}); '
            'print("INFO [alembic.runtime] after synthetic-private-context",file=sys.stderr)'
        )
        with self.process(script):
            self.assertEqual(read_migration_result('immutable-helper-id'), RECEIPT)

    def test_receipt_present_only_in_stderr_is_never_accepted(self):
        with self.process(f'import sys; print({json.dumps(json.dumps(RECEIPT))},file=sys.stderr)'), \
                self.assertRaisesRegex(ValueError, 'result_missing'):
            read_migration_result('immutable-helper-id')

    def test_two_receipts_or_stdout_noise_fail_closed(self):
        payload = json.dumps(RECEIPT)
        for output in (payload + '\n' + payload, 'diagnostic\n' + payload, payload + '\ntrailing diagnostic'):
            with self.subTest(output=output[:20]), self.process(f'print({json.dumps(output)})'), \
                    self.assertRaisesRegex(ValueError, 'result_missing'):
                read_migration_result('immutable-helper-id')

    def test_malformed_json_and_invalid_utf8_are_rejected_without_echoing_content(self):
        for raw in (b'{"status": synthetic-private-context}', b'\xffprivate-context'):
            with self.subTest(raw=raw[:1]), patch('release_companies_runtime.migration_stdout', return_value=raw), \
                    self.assertRaisesRegex(ValueError, '^migration_validation_result_missing$'):
                read_migration_result('immutable-helper-id')

    def test_byte_limit_is_enforced_during_capture(self):
        with self.process('import sys; sys.stdout.write("x"*1048576)'), \
                self.assertRaisesRegex(ValueError, 'budget_exceeded'):
            migration_stdout('immutable-helper-id')

    def test_exact_byte_limit_is_allowed_but_one_extra_byte_is_rejected(self):
        with self.process('import sys; sys.stdout.write(" "*32768)'):
            self.assertEqual(len(migration_stdout('immutable-helper-id')), 32768)
        with self.process('import sys; sys.stdout.write(" "*32769)'), \
                self.assertRaisesRegex(ValueError, 'budget_exceeded'):
            migration_stdout('immutable-helper-id')

    def test_nonzero_log_command_and_timeout_do_not_admit_partial_receipt(self):
        with self.process(f'import sys; print({json.dumps(json.dumps(RECEIPT))}); sys.exit(1)'), \
                self.assertRaisesRegex(ValueError, 'read_failed'):
            read_migration_result('immutable-helper-id')
        with self.process('import time; time.sleep(10)'), self.assertRaisesRegex(ValueError, 'read_failed'):
            migration_stdout('immutable-helper-id', timeout=0.05)

    def test_machine_receipt_status_hash_and_field_allowlist_remain_enforced(self):
        for value in ({**RECEIPT, 'status': 'unknown'}, {**RECEIPT, 'preservation_sha256': 'bad'},
                      {**RECEIPT, 'private_document': 'unexpected'}, [RECEIPT]):
            with self.subTest(value=value), patch('release_companies_runtime.migration_stdout',
                                                return_value=json.dumps(value).encode()), self.assertRaises(ValueError):
                read_migration_result('immutable-helper-id')

    def test_existing_baseline_and_target_noop_receipts_remain_supported(self):
        for status in ('baseline_captured', 'already_at_target'):
            value = {**RECEIPT, 'status': status}
            with self.subTest(status=status), patch('release_companies_runtime.migration_stdout',
                                                   return_value=json.dumps(value).encode()):
                self.assertEqual(read_migration_result('immutable-helper-id'), value)


if __name__ == '__main__':
    unittest.main()
