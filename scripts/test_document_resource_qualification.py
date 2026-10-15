"""Fail-closed exact-image qualification and owned-fixture cleanup; no Docker."""
from __future__ import annotations

import copy
import json
import subprocess
import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

from qa import qualify_document_release_resources as probe

REVISION = 'a' * 40
IMAGES = {name: 'sha256:' + digit * 64 for name, digit in (
    ('backend', 'b'), ('frontend', 'c'), ('redis-broker', 'd'), ('redis-cache', 'e'))}
POSTGRES = 'sha256:' + 'f' * 64


def memory(*, mib: bool = False) -> dict:
    return {'peak_mib' if mib else 'peak_bytes': 64 if mib else 64 * 1024**2,
            'running': True, 'events': {'oom': '0', 'oom_kill': '0', 'max': '0'}}


def evidence() -> dict:
    return {
        'sender': {'passed': True, 'provider_calls': 0, 'backend_image': IMAGES['backend'],
                   'postgres_image': POSTGRES, 'cap_mib': 1024, 'memory': memory()},
        'frontend': {'result': 'passed', 'image': IMAGES['frontend'], 'cap_mib': 256,
                     'memory': memory(mib=True)},
        'redis': [{'service': name, 'image': IMAGES[name], 'cap_mib': probe.LIMITS[name][1],
                   'maxmemory_mib': maximum, 'result': 'passed', 'memory': memory(mib=True),
                   'rewrite_observed': name == 'redis-broker', 'rewrite_overwrites': 64 if name == 'redis-broker' else 0}
                  for name, maximum in probe.DATASETS.items()],
        'lifecycle': [{'service': name, 'image_id': IMAGES[name], 'cap_mib': probe.LIMITS[name][1],
                       'passed': True, 'memory': memory(), 'original_container_retained': True,
                       'same_data_volume': True, 'absolute_ttl_preserved': True,
                       'orphaned_create_recovered': True, 'one_active_writer': True}
                      for name in probe.DATASETS],
    }


class QualificationEvidenceTests(unittest.TestCase):
    def setUp(self):
        self.enterContext(patch.object(probe, 'sha256', return_value='a' * 64))
        self.enterContext(patch.object(probe, 'qualified_source_hashes', return_value={'fixture.py': 'b' * 64}))

    def test_complete_proof_binds_images_source_limits_and_each_evidence_digest(self):
        value = probe.build_receipt(REVISION, IMAGES, evidence())
        self.assertIs(value['qualified'], True)
        self.assertEqual(value['image_ids'], IMAGES)
        self.assertEqual(value['redis_maxmemory_mib'], {'redis-broker': 384, 'redis-cache': 128})
        self.assertEqual(value['limits_mib'], {'worker': 1024, 'frontend': 256, 'redis-broker': 896, 'redis-cache': 192})
        self.assertEqual(set(value['evidence_sha256']), {'sender', 'frontend', 'redis', 'lifecycle'})
        self.assertEqual(value['provider_calls'], 0)

    def test_wrong_image_cap_dataset_or_application_result_cannot_qualify(self):
        for section, index, field, changed in (
            ('sender', None, 'backend_image', POSTGRES), ('frontend', None, 'image', POSTGRES),
            ('sender', None, 'cap_mib', 2048), ('frontend', None, 'cap_mib', 512),
            ('sender', None, 'passed', 1), ('sender', None, 'provider_calls', 1),
            ('sender', None, 'provider_calls', False), ('frontend', None, 'result', 'failed'),
            ('redis', 0, 'image', POSTGRES), ('redis', 1, 'cap_mib', 320),
            ('redis', 1, 'maxmemory_mib', 256), ('lifecycle', 0, 'image_id', POSTGRES),
            ('lifecycle', 1, 'cap_mib', 320),
        ):
            value = evidence()
            target = value[section] if index is None else value[section][index]
            target[field] = changed
            with self.subTest(section=section, field=field, changed=changed), self.assertRaises(ValueError):
                probe.build_receipt(REVISION, IMAGES, value)

    def test_all_workloads_require_complete_zero_oom_and_zero_max_memory_evidence(self):
        for section, index in [('sender', None), ('frontend', None), ('redis', 0), ('redis', 1), ('lifecycle', 0), ('lifecycle', 1)]:
            for event in ('oom', 'oom_kill', 'max', 'missing_memory', 'missing_counter', 'invalid_peak'):
                value = evidence()
                target = value[section] if index is None else value[section][index]
                if event == 'missing_memory':
                    target.pop('memory')
                elif event == 'missing_counter':
                    target['memory']['events'].pop('oom')
                elif event == 'invalid_peak':
                    target['memory']['peak_mib' if section in {'frontend', 'redis'} else 'peak_bytes'] = True
                else:
                    target['memory']['events'][event] = '1'
                with self.subTest(section=section, index=index, event=event), self.assertRaises(ValueError):
                    probe.build_receipt(REVISION, IMAGES, value)

    def test_donor_must_still_be_running_when_memory_is_measured(self):
        for section, index in [('frontend', None), ('redis', 0), ('redis', 1)]:
            value = evidence()
            target = value[section] if index is None else value[section][index]
            target['memory']['running'] = False
            with self.subTest(section=section, index=index), self.assertRaises(ValueError):
                probe.build_receipt(REVISION, IMAGES, value)

    def test_rewrite_and_every_retained_preservation_check_are_mandatory(self):
        for key, changed in [('rewrite_observed', False), ('rewrite_observed', 1), ('rewrite_overwrites', 0)]:
            value = evidence()
            value['redis'][0][key] = changed
            with self.subTest(key=key), self.assertRaises(ValueError):
                probe.build_receipt(REVISION, IMAGES, value)
        for key in ('original_container_retained', 'same_data_volume', 'absolute_ttl_preserved',
                    'orphaned_create_recovered', 'one_active_writer'):
            for replacement in (False, 1, None):
                value = evidence()
                value['lifecycle'][0][key] = replacement
                with self.subTest(key=key, replacement=replacement), self.assertRaises(ValueError):
                    probe.build_receipt(REVISION, IMAGES, value)

    def test_missing_duplicate_or_unrelated_redis_service_fails(self):
        for section in ('redis', 'lifecycle'):
            for replacement in ([], [evidence()[section][0]] * 2):
                value = evidence()
                value[section] = replacement
                with self.subTest(section=section), self.assertRaises(ValueError):
                    probe.build_receipt(REVISION, IMAGES, value)

    def test_cleanup_failure_never_writes_a_qualified_receipt(self):
        for failing in ('sender_probe', 'frontend_probe', 'redis_probe', 'qualify_redis_transition'):
            with self.subTest(failing=failing), tempfile.TemporaryDirectory() as directory:
                values = evidence()
                with patch.object(probe, 'verify_inputs'), \
                     patch.object(probe, 'sender_probe', return_value=values['sender']) as sender, \
                     patch.object(probe, 'frontend_probe', return_value=values['frontend']) as frontend, \
                     patch.object(probe, 'redis_probe', side_effect=values['redis']) as redis, \
                     patch.object(probe, 'qualify_redis_transition', return_value=values['lifecycle']) as lifecycle, \
                     patch.object(probe, 'write_exclusive') as write:
                    mocks = dict(sender_probe=sender, frontend_probe=frontend, redis_probe=redis, qualify_redis_transition=lifecycle)
                    mocks[failing].side_effect = RuntimeError('fixture_cleanup_failed')
                    with self.assertRaisesRegex(RuntimeError, 'fixture_cleanup_failed'):
                        probe.qualify(REVISION, IMAGES, POSTGRES, Path(directory) / 'receipt.json')
                    write.assert_not_called()

    def test_source_changed_after_probes_never_writes_receipt(self):
        values = evidence()
        with tempfile.TemporaryDirectory() as directory, patch.object(probe, 'verify_inputs'), \
             patch.object(probe, 'sender_probe', return_value=values['sender']), \
             patch.object(probe, 'frontend_probe', return_value=values['frontend']), \
             patch.object(probe, 'redis_probe', side_effect=values['redis']), \
             patch.object(probe, 'qualify_redis_transition', return_value=values['lifecycle']), \
             patch.object(probe, 'qualified_source_hashes', side_effect=[{'source': 'before'}, {'source': 'after'}]), \
             patch.object(probe, 'write_exclusive') as write:
            with self.assertRaisesRegex(ValueError, 'source_changed'):
                probe.qualify(REVISION, IMAGES, POSTGRES, Path(directory) / 'receipt.json')
            write.assert_not_called()

    def test_success_persists_evidence_before_exclusive_receipt(self):
        values = evidence()
        with tempfile.TemporaryDirectory() as directory, patch.object(probe, 'verify_inputs') as verify, \
             patch.object(probe, 'sender_probe', return_value=values['sender']), \
             patch.object(probe, 'frontend_probe', return_value=values['frontend']), \
             patch.object(probe, 'redis_probe', side_effect=values['redis']), \
             patch.object(probe, 'qualify_redis_transition', return_value=values['lifecycle']):
            path = Path(directory) / 'receipt.json'
            value = probe.qualify(REVISION, IMAGES, POSTGRES, path)
            self.assertEqual(json.loads(path.read_text()), value)
            self.assertEqual(json.loads(path.with_name('receipt-evidence.json').read_text()), values)
            self.assertEqual(verify.call_count, 2)
            with self.assertRaises(FileExistsError):
                probe.write_exclusive(path, {'qualified': False})
            self.assertEqual(json.loads(path.read_text()), value)


class OwnedSenderCleanupTests(unittest.TestCase):
    def test_create_timeout_still_cleans_label_bound_container_and_network(self):
        run_id = 'pd-document-sender-' + '1' * 32
        network, database = run_id + '-net', run_id + '-db'
        calls = []

        def command(*args, **_kwargs):
            calls.append(args)
            if args[:2] == ('docker', 'create'):
                raise subprocess.TimeoutExpired('docker create', 60)
            if args[:3] == ('docker', 'ps', '-aq'):
                return 'database-id'
            if args[:3] == ('docker', 'network', 'ls'):
                return 'network-id'
            if args[:3] == ('docker', 'network', 'inspect'):
                return json.dumps([{'Name': network, 'Labels': {probe.LABEL: run_id}, 'Internal': True, 'Containers': {}}])
            return ''

        row = {'Id': 'database-id', 'Name': '/' + database,
               'Config': {'Labels': {probe.LABEL: run_id}}, 'NetworkSettings': {'Networks': {network: {}}}}
        with patch.object(probe.uuid, 'uuid4', return_value=SimpleNamespace(hex='1' * 32)), \
             patch.object(probe, 'guard'), patch.object(probe, 'command', side_effect=command), \
             patch.object(probe, 'inspect', return_value=row):
            with self.assertRaises(subprocess.TimeoutExpired):
                probe.sender_probe(IMAGES['backend'], POSTGRES)
        self.assertIn(('docker', 'rm', '-f', '-v', 'database-id'), calls)
        self.assertIn(('docker', 'network', 'rm', 'network-id'), calls)

    def test_cleanup_rejects_changed_ownership_before_removal(self):
        row = {'Id': 'not-owned', 'Name': '/unrelated',
               'Config': {'Labels': {probe.LABEL: 'other'}}, 'NetworkSettings': {'Networks': {}}}
        def command(*args, **_kwargs):
            if args[:3] == ('docker', 'network', 'create'):
                raise subprocess.TimeoutExpired('docker create', 60)
            return 'not-owned' if args[:3] == ('docker', 'ps', '-aq') else ''
        with patch.object(probe, 'guard'), patch.object(probe, 'command', side_effect=command) as run, \
             patch.object(probe, 'inspect', return_value=row):
            with self.assertRaisesRegex(RuntimeError, 'ownership_changed'):
                probe.sender_probe(IMAGES['backend'], POSTGRES)
        self.assertFalse(any(call.args[:2] == ('docker', 'rm') for call in run.call_args_list))


if __name__ == '__main__':
    unittest.main()
