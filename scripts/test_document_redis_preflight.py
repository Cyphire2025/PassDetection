"""Inventory/headroom failures must precede document schema mutation."""
from __future__ import annotations

import copy
import json
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import Mock, patch

import release_document_resources as resources
import release_redis_dataset_transition as redis
from release_traveller_whatsapp import ReleaseError
from test_release_document_retained_update import redis_original


def fixture():
    broker = redis_original()
    broker['State'].update(Running=True, Health={'Status': 'healthy'})
    cache = copy.deepcopy(broker)
    cache['Id'] = 'cache-id'
    cache['Config']['Labels']['com.docker.compose.service'] = 'redis-cache'
    cache['Config']['Cmd'] = ['redis-server', '--requirepass', 'synthetic', '--maxmemory', '256mb',
                              '--maxmemory-policy', 'allkeys-lru', '--appendonly', 'no', '--save', '']
    release = SimpleNamespace(directory=Path('.'), revision='a' * 40,
        record={'live': {'redis-broker': broker, 'redis-cache': cache}}, assert_writer_fence=Mock(), client=Mock())
    release.event = Mock(side_effect=lambda phase, **values: release.record.update(phase=phase, **values))
    return release


class InventoryBounds(unittest.TestCase):
    def test_broker_bound_does_not_expand_cache_or_unknown_container(self):
        self.assertEqual(redis.MAX_KEYS, 250_000)
        self.assertEqual(redis.key_limit(redis_original()), 250_000)
        self.assertEqual(redis.key_limit(fixture().record['live']['redis-cache']), 20_000)
        self.assertEqual(redis.key_limit({}), 20_000)

    def test_inventory_over_bound_rejects_before_value_reads_with_clear_error(self):
        for container, count, message in ((redis_original(), 250001, '250,000-key'),
                (fixture().record['live']['redis-cache'], 20001, '20,000-key')):
            with self.subTest(message=message), patch.object(redis, '_config', return_value='1'), \
                 patch.object(redis, '_cli', return_value=str(count)) as cli, \
                 self.assertRaisesRegex(ReleaseError, message):
                redis.fingerprint(None, container)
            self.assertEqual(cli.call_count, 1)
            self.assertEqual(cli.call_args.args[2:], ('DBSIZE',))

    def test_qualified_broker_accepts_inventory_above_old_20000_bound(self):
        rows = [[f'{number:040x}', 'a' * 40, -1] for number in range(20001)]
        with patch.object(redis, '_config', return_value='1'), \
             patch.object(redis, '_cli', side_effect=['20001', json.dumps({'rows': rows, 'now_ms': 1000})]) as cli:
            result = redis.fingerprint(None, redis_original())
        self.assertEqual(len(result['rows']), 20001)
        self.assertEqual(cli.call_args.args[-1], '250000')

    def test_limit_is_total_across_databases_and_exact_boundary_is_allowed(self):
        payload = json.dumps({'rows': [['a' * 40, 'b' * 40, -1], ['b' * 40, 'c' * 40, -1]], 'now_ms': 1000})
        one = json.dumps({'rows': [['c' * 40, 'd' * 40, 3000]], 'now_ms': 1000})
        with patch.object(redis, 'MAX_KEYS', 3), patch.object(redis, '_config', return_value='2'), \
             patch.object(redis, '_cli', side_effect=['2', payload, '1', one]) as cli:
            result = redis.fingerprint(None, redis_original())
        self.assertEqual(len(result['rows']), 3)
        self.assertEqual(cli.call_args.args[-1], '1')
        with patch.object(redis, 'MAX_KEYS', 3), patch.object(redis, '_config', return_value='2'), \
             patch.object(redis, '_cli', side_effect=['2', payload, '2']) as cli, \
             self.assertRaisesRegex(ReleaseError, '4 keys observed through database 1'):
            redis.fingerprint(None, redis_original())
        self.assertEqual(cli.call_count, 3)


class Admission(unittest.TestCase):
    def test_readonly_preflight_checks_all_values_and_measures_headroom_afterward(self):
        release = Mock()
        inventory = {'rows': {'key': ['value', -1]}, 'databases': 16, 'now_ms': 1000}
        memory = {'current': 30 * redis.MIB, 'oom': 0, 'oom_kill': 0}
        transition = {'old_maxmemory': 512 * redis.MIB, 'maxmemory': 384 * redis.MIB}
        with patch.object(redis, '_runtime'), patch.object(redis, '_cli', return_value='used_memory:1000000') as cli, \
             patch.object(redis, 'fingerprint', return_value=inventory) as fingerprint, \
             patch('release_persistent_resources.cgroup_memory', return_value=memory) as measure:
            result = redis.preflight_dataset(release, redis_original(), 'redis-broker', transition, 896 * redis.MIB)
        self.assertEqual(result['key_count'], 1)
        self.assertEqual(result['max_keys'], 250000)
        self.assertNotIn('rows', result)
        self.assertEqual(result['container_memory'], memory)
        self.assertEqual(measure.call_count, 2)
        fingerprint.assert_called_once()
        self.assertTrue(all(call.args[2:] == ('INFO', 'memory') for call in cli.call_args_list))
        release.run.assert_not_called()

    def test_low_dataset_headroom_prevents_inventory_and_any_mutation(self):
        transition = {'old_maxmemory': 512 * redis.MIB, 'maxmemory': 384 * redis.MIB}
        release = Mock()
        with patch.object(redis, '_runtime'), patch.object(redis, '_cli', return_value=f'used_memory:{380 * redis.MIB}'), \
             patch.object(redis, 'fingerprint') as fingerprint, self.assertRaisesRegex(ReleaseError, 'dataset lacks headroom'):
            redis.preflight_dataset(release, redis_original(), 'redis-broker', transition, 896 * redis.MIB)
        fingerprint.assert_not_called()
        release.run.assert_not_called()

    def test_fingerprint_memory_growth_must_still_fit_target_cap(self):
        transition = {'old_maxmemory': 512 * redis.MIB, 'maxmemory': 384 * redis.MIB}
        inventory = {'rows': {}, 'databases': 16, 'now_ms': 1000}
        with patch.object(redis, '_runtime'), patch.object(redis, '_cli', return_value='used_memory:1000000'), \
             patch.object(redis, 'fingerprint', return_value=inventory), \
             patch('release_persistent_resources.cgroup_memory', side_effect=[{'current': 30 * redis.MIB}, {'current': 800 * redis.MIB}]), \
             self.assertRaisesRegex(ReleaseError, 'container headroom'):
            redis.preflight_dataset(Mock(), redis_original(), 'redis-broker', transition, 896 * redis.MIB)

    def run_with_counters(self, before, after):
        transition = {'old_maxmemory': 512 * redis.MIB, 'maxmemory': 384 * redis.MIB}
        inventory = {'rows': {}, 'databases': 16, 'now_ms': 1000}
        # The post-read footprint is lower: a current-memory check alone would
        # miss an OOM event or killed process that released memory in between.
        readings = [{'current': 60 * redis.MIB, **before}, {'current': 20 * redis.MIB, **after}]
        with patch.object(redis, '_runtime'), patch.object(redis, '_cli', return_value='used_memory:1000000'), \
             patch.object(redis, 'fingerprint', return_value=inventory), \
             patch('release_persistent_resources.cgroup_memory', side_effect=readings):
            return redis.preflight_dataset(Mock(), redis_original(), 'redis-broker', transition, 896 * redis.MIB)

    def test_new_oom_rejected_even_when_current_memory_falls(self):
        with self.assertRaisesRegex(ReleaseError, 'OOM counters changed'):
            self.run_with_counters({'oom': 0, 'oom_kill': 0}, {'oom': 1, 'oom_kill': 0})

    def test_new_oom_kill_rejected_even_when_current_memory_falls(self):
        with self.assertRaisesRegex(ReleaseError, 'OOM counters changed'):
            self.run_with_counters({'oom': 1, 'oom_kill': 0}, {'oom': 1, 'oom_kill': 1})

    def test_unchanged_historical_oom_counters_are_allowed_and_recorded(self):
        result = self.run_with_counters({'oom': 5, 'oom_kill': 2}, {'oom': 5, 'oom_kill': 2})
        self.assertEqual(result['container_memory_before'], {'current': 60 * redis.MIB, 'oom': 5, 'oom_kill': 2})
        self.assertEqual(result['container_memory'], {'current': 20 * redis.MIB, 'oom': 5, 'oom_kill': 2})

    def test_decreasing_counters_cannot_silently_reset_preflight_identity(self):
        with self.assertRaisesRegex(ReleaseError, 'OOM counters changed'):
            self.run_with_counters({'oom': 5, 'oom_kill': 2}, {'oom': 0, 'oom_kill': 0})


class ResourcePreparation(unittest.TestCase):
    def prepare(self, release, probe):
        with patch.object(resources, 'require_budget'), patch.object(resources, 'qualification', return_value={'bound': True}), \
             patch.object(resources, 'bound_original', side_effect=lambda row: row), patch.object(resources, 'redis_payload'), \
             patch.object(resources, 'volume_identity', return_value={'volume': 'retained'}), \
             patch.object(resources, 'preflight_dataset', probe):
            resources.prepare(release)

    def test_preparation_records_both_readonly_admissions_before_staging(self):
        release = fixture()
        probe = Mock(return_value={'key_count': 187939, 'max_keys': 250000})
        self.prepare(release, probe)
        self.assertEqual([call.args[2] for call in probe.call_args_list], ['redis-broker', 'redis-cache'])
        self.assertEqual(release.record['persistent']['redis-broker']['admission_preflight']['key_count'], 187939)
        release.assert_writer_fence.assert_not_called()
        release.client.request.assert_not_called()

    def test_unsupported_inventory_does_not_publish_prepared_receipt(self):
        release = fixture()
        with self.assertRaisesRegex(ReleaseError, 'unreviewed Redis value type'):
            self.prepare(release, Mock(side_effect=ReleaseError('unreviewed Redis value type')))
        self.assertNotIn('persistent', release.record)
        release.event.assert_not_called()
        release.client.request.assert_not_called()

    def test_fenced_preflight_rechecks_current_admission_and_volume_identity(self):
        release = fixture()
        self.prepare(release, Mock(return_value={'key_count': 1}))
        with patch.object(resources, 'bound_original', side_effect=lambda row: row), \
             patch.object(resources, 'same_redis_process'), \
             patch.object(resources, 'volume_identity', return_value={'volume': 'retained'}), \
             patch.object(resources, 'preflight_dataset', return_value={'key_count': 2}) as probe:
            resources.preflight_fenced(release)
        release.assert_writer_fence.assert_called_once()
        self.assertEqual(probe.call_count, 2)
        self.assertEqual(release.record['resource_preflight']['redis-broker']['key_count'], 2)
        release.record['persistent']['redis-broker']['stage'] = 'complete'
        with patch.object(resources, 'preflight_dataset') as probe, \
             self.assertRaisesRegex(ValueError, 'prepared_redis_inventory_required'):
            resources.preflight_fenced(release)
        probe.assert_not_called()


if __name__ == '__main__':
    unittest.main()
