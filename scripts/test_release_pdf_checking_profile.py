"""Resource reallocation and feature pause must remain explicit and reversible."""
from __future__ import annotations

import copy
import json
import unittest
from pathlib import Path
from unittest.mock import Mock, patch

import release_pdf_checking_profile as profile
from release_retained_update import RetainedUpdate, select_live
from test_release_retained_update import live_rows


class ProfileTests(unittest.TestCase):
    def inventory(self):
        metadata = json.loads((Path(__file__).resolve().parents[1] / 'tooling/deployment-profiles/kvm4.json').read_text())
        return {name: {'HostConfig': {'Memory': mib * profile.MIB}}
                for name, mib in metadata['memory_limits_mib'].items()}

    def test_pause_funds_backend_without_lowering_any_remaining_service_or_host_reserve(self):
        live = self.inventory()
        before = copy.deepcopy(live)
        receipt = profile.planned_budget(live, 15992 * profile.MIB)
        self.assertEqual(receipt['serving_container_bytes'], 13760 * profile.MIB)
        self.assertEqual(receipt['host_reserve_bytes'], 2048 * profile.MIB)
        self.assertEqual(live, before)
        self.assertNotIn('email-beat', profile.PAUSED)
        with self.assertRaisesRegex(ValueError, 'exceeds_host_reserve'):
            profile.planned_budget(live, 15000 * profile.MIB)
        live['backend']['HostConfig']['Memory'] = 4096 * profile.MIB
        with self.assertRaisesRegex(ValueError, 'backend_baseline_changed'):
            profile.planned_budget(live, 20000 * profile.MIB)

    def test_clone_changes_only_backend_cap_paused_restart_and_profile_label(self):
        client = Mock()
        client.request.return_value = {'Id': 'b' * 64}
        client.identifier.side_effect = lambda value: value
        for name in ['backend', 'worker', 'email-beat', *sorted(profile.PAUSED)]:
            original = {'Config': {'Labels': {'com.docker.compose.service': name}}}
            payload = {'Labels': {}, 'HostConfig': {'Memory': 2560 * profile.MIB if name == 'backend' else 384 * profile.MIB,
                                                   'MemorySwap': 2560 * profile.MIB if name == 'backend' else 384 * profile.MIB,
                                                   'RestartPolicy': {'Name': 'unless-stopped'}, 'NanoCpus': 1000000000}}
            before = copy.deepcopy(payload)
            with patch.object(profile, 'clone_payload', return_value=payload):
                profile.create_candidate(client, original, {'name': 'candidate-' + name})
            if name == 'backend':
                self.assertEqual(payload['HostConfig']['Memory'], 3584 * profile.MIB)
                self.assertEqual(payload['HostConfig']['MemorySwap'], 3584 * profile.MIB)
            elif name in profile.PAUSED:
                self.assertEqual(payload['HostConfig']['RestartPolicy']['Name'], 'no')
                self.assertEqual(payload['HostConfig']['Memory'], before['HostConfig']['Memory'])
            else:
                self.assertEqual(payload['HostConfig'], before['HostConfig'])
            self.assertEqual(payload['Labels'][profile.LABEL], profile.PROFILE)

    def test_current_inventory_requires_matching_paused_project_and_explicit_profile(self):
        rows = live_rows()
        paused = []
        running = []
        for row in rows:
            name = row['Config']['Labels']['com.docker.compose.service']
            if name in profile.PAUSED:
                row['State']['Running'] = False
                row['Config']['Labels'][profile.LABEL] = profile.PROFILE
                row['HostConfig'] = {'RestartPolicy': {'Name': 'no'}}
                paused.append(row)
            else:
                running.append(row)
        assembled = profile.live_inventory(running, rows)
        self.assertEqual(set(select_live(assembled, paused_services=profile.PAUSED)), set(self.inventory()))
        with self.assertRaisesRegex(ValueError, 'live_service_not_running'):
            select_live(assembled)
        paused[0]['Config']['Labels']['com.docker.compose.project'] = 'older-project'
        self.assertEqual(len(profile.live_inventory(running, rows)), len(rows) - 1)

    def test_pause_disables_feature_producers_and_preserves_secrets_without_mutation(self):
        release = object.__new__(RetainedUpdate)
        release.revision = 'b' * 40
        release.pause_email_and_photos = True
        original = next(row for row in live_rows() if row['Config']['Labels']['com.docker.compose.service'] == 'backend')
        before = copy.deepcopy(original)
        result = release.candidate_environment(original)
        self.assertEqual(result['EMAIL_INTEGRATIONS_ENABLED'], 'false')
        self.assertEqual(result['EMAIL_SYNC_ENABLED'], 'false')
        self.assertEqual(result['EMAIL_AI_ENABLED'], 'false')
        self.assertEqual(result['PRIVATE_SETTING'], 'retained')
        self.assertEqual(original, before)


if __name__ == '__main__':
    unittest.main()
