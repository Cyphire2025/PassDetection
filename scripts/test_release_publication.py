"""Exercise publication/reuse through mocked GitHub metadata and asset downloads."""
from __future__ import annotations

import copy
import json
import subprocess
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

import release_publication as publication

SHA = "a" * 40
OTHER = "b" * 40
TAG = "release-" + SHA


class PublicationTests(unittest.TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory()
        self.addCleanup(self.temporary.cleanup)
        root = Path(self.temporary.name)
        self.assets = {}
        self.downloads = {}
        entries = []
        for number, name in enumerate(("release-artifacts.json", "backend.spdx.json", "frontend.spdx.json",
                "connector-artifacts.json", "global_connects_mcp_connector-0.2.0-py3-none-any.whl",
                "connector-requirements.lock", "connector-README.md"), 1):
            data = ("synthetic qualified " + name).encode()
            path = root / name
            path.write_bytes(data)
            self.assets[name] = path
            self.downloads[number] = data
            entries.append({"id": number, "name": name, "size": len(data), "state": "uploaded"})
        self.release = {"tag_name": TAG, "draft": False, "assets": entries}
        self.published = copy.deepcopy(self.release)
        self.tag_target = SHA
        self.commands = []
        self.creations = []

    def gh(self, args, **kwargs):
        self.commands.append(args)
        self.assertEqual(args[:4], ["gh", "api", "--hostname", "github.com"])
        endpoint = args[5] if args[4] == "--include" else args[4]
        if "/releases/assets/" in endpoint:
            self.assertEqual(args[-2:], ["--header", "Accept: application/octet-stream"])
            kwargs["stdout"].write(self.downloads[int(endpoint.rsplit("/", 1)[1])])
            return subprocess.CompletedProcess(args, 0)
        if "/releases/tags/" in endpoint:
            value = self.published
        elif "/git/ref/tags/" in endpoint:
            value = None if self.tag_target is None else {
                "ref": "refs/tags/" + TAG, "object": {"type": "commit", "sha": self.tag_target}}
        else:
            self.fail("Unexpected endpoint: " + endpoint)
        if value is None:
            return subprocess.CompletedProcess(args, 1, "HTTP/2.0 404 Not Found\n\n{}")
        return subprocess.CompletedProcess(args, 0, "HTTP/2.0 200 OK\n\n" + json.dumps(value))

    def create(self, *args):
        self.creations.append(args)
        self.assertEqual(args[:4], ("gh", "release", "create", TAG))
        self.assertEqual(args[args.index("--target") + 1], SHA)
        self.assertEqual(set(args[-len(self.assets):]), {str(path) for path in self.assets.values()})
        self.assertFalse({"--clobber", "delete", "edit", "upload"} & set(args))
        self.published, self.tag_target = copy.deepcopy(self.release), SHA
        return "created"

    def publish(self):
        with patch.object(publication, "verified_assets", return_value=self.assets), \
                patch.object(publication.subprocess, "run", side_effect=self.gh), \
                patch.object(publication, "run", side_effect=self.create):
            return publication.publish(Path("images"), Path("connector"), SHA)

    def test_identical_existing_release_checks_every_actual_asset_without_writing(self):
        self.assertEqual(self.publish(), "reused")
        self.assertEqual(self.creations, [])
        self.assertEqual(sum("/releases/assets/" in " ".join(args) for args in self.commands), 7)
        self.assertEqual(sum("/git/ref/tags/" in " ".join(args) for args in self.commands), 2)

    def test_new_release_is_created_once_and_tag_and_every_byte_are_read_back(self):
        self.published = self.tag_target = None
        self.assertEqual(self.publish(), "created")
        self.assertEqual(len(self.creations), 1)
        self.assertEqual(sum("/releases/assets/" in " ".join(args) for args in self.commands), 7)

    def test_matching_preexisting_tag_allows_new_release_without_moving_tag(self):
        self.published = None
        self.assertEqual(self.publish(), "created")
        self.assertEqual(len(self.creations), 1)

    def test_changed_bytes_of_any_existing_asset_are_refused_even_at_same_size(self):
        for identifier, original in list(self.downloads.items()):
            self.downloads[identifier] = b"x" * len(original)
            with self.subTest(asset=identifier), self.assertRaisesRegex(ValueError, "bytes differ"):
                self.publish()
            self.downloads[identifier] = original
        self.assertEqual(self.creations, [])

    def test_missing_or_extra_assets_are_refused_without_partial_repairs(self):
        for change in ("missing", "extra", "duplicate"):
            self.published = copy.deepcopy(self.release)
            if change == "missing":
                self.published["assets"].pop()
            elif change == "extra":
                self.published["assets"].append({"name": "unexpected"})
            else:
                self.published["assets"][-1] = self.published["assets"][0]
            with self.subTest(change=change), self.assertRaisesRegex(ValueError, "inventory"):
                self.publish()
        self.assertEqual(self.creations, [])

    def test_incomplete_asset_upload_or_size_change_is_refused_before_download(self):
        for change in ({"state": "starter"}, {"size": 1}, {"id": "../other"}):
            self.published = copy.deepcopy(self.release)
            self.published["assets"][0].update(change)
            with self.subTest(change=change), self.assertRaisesRegex(ValueError, "identity or size"):
                self.publish()
        self.assertEqual(self.creations, [])

    def test_wrong_or_missing_tag_prevents_existing_release_reuse(self):
        for target in (OTHER, None):
            self.tag_target = target
            with self.subTest(target=target), self.assertRaisesRegex(ValueError, "tag"):
                self.publish()
        self.assertEqual(self.creations, [])

    def test_wrong_existing_tag_prevents_new_release_creation(self):
        self.published, self.tag_target = None, OTHER
        with self.assertRaisesRegex(ValueError, "selected commit"):
            self.publish()
        self.assertEqual(self.creations, [])

    def test_draft_or_wrong_named_release_is_not_reused(self):
        for change in ({"draft": True}, {"tag_name": "release-" + OTHER}):
            self.published = {**self.release, **change}
            with self.subTest(change=change), self.assertRaisesRegex(ValueError, "publication state"):
                self.publish()
        self.assertEqual(self.creations, [])

    def test_auth_network_or_malformed_lookup_is_not_treated_as_absent(self):
        github = publication.GitHub("Cyphire2025/PassDetection")
        for status, code in (("HTTP/2.0 403 Forbidden\n\n{}", 1),
                             ("HTTP/2.0 500 Server Error\n\n{}", 1), ("network error", 1),
                             ("HTTP/2.0 200 OK\n\n[]", 0)):
            with self.subTest(status=status), patch.object(publication.subprocess, "run",
                    return_value=subprocess.CompletedProcess([], code, status)), self.assertRaises((ValueError, TypeError)):
                github.metadata("releases/tags/" + TAG)

    def test_partial_creation_failure_stops_without_retry_or_mutation_of_retained_assets(self):
        self.published = self.tag_target = None
        with patch.object(publication, "verified_assets", return_value=self.assets), \
                patch.object(publication.subprocess, "run", side_effect=self.gh), \
                patch.object(publication, "run", side_effect=subprocess.CalledProcessError(1, ["gh"])) as create, \
                self.assertRaises(subprocess.CalledProcessError):
            publication.publish(Path("images"), Path("connector"), SHA)
        self.assertEqual(create.call_count, 1)
        self.assertEqual(create.call_args.args[:4], ("gh", "release", "create", TAG))
        self.assertFalse(any("/releases/assets/" in " ".join(args) for args in self.commands))

    def test_tag_changed_during_existing_asset_readback_is_refused(self):
        original = self.gh
        def changed(args, **kwargs):
            result = original(args, **kwargs)
            if "/releases/assets/" in " ".join(args):
                self.tag_target = OTHER
            return result
        with patch.object(publication, "verified_assets", return_value=self.assets), \
                patch.object(publication.subprocess, "run", side_effect=changed), \
                patch.object(publication, "run") as create, \
                self.assertRaisesRegex(ValueError, "selected commit"):
            publication.publish(Path("images"), Path("connector"), SHA)
        create.assert_not_called()

    def test_annotated_tag_must_resolve_to_the_selected_commit(self):
        github = publication.GitHub("Cyphire2025/PassDetection")
        for final in (SHA, OTHER):
            responses = [{"ref": "refs/tags/" + TAG, "object": {"type": "tag", "sha": OTHER}},
                         {"sha": OTHER, "object": {"type": "commit", "sha": final}}]
            with patch.object(github, "metadata", side_effect=responses):
                if final == SHA:
                    github.require_tag(TAG, SHA)
                else:
                    with self.assertRaisesRegex(ValueError, "selected commit"):
                        github.require_tag(TAG, SHA)

    def test_invalid_revision_fails_before_qualification_or_github(self):
        with patch.object(publication, "verified_assets") as verify, self.assertRaises(ValueError):
            publication.publish(Path("images"), Path("connector"), "main")
        verify.assert_not_called()

    def test_bad_local_inventory_signature_stops_before_asset_parsing(self):
        root = next(iter(self.assets.values())).parent
        with patch.object(publication, "run", side_effect=ValueError("invalid signature")) as verify, \
                patch.object(publication, "verify_connector") as connector, \
                self.assertRaisesRegex(ValueError, "invalid signature"):
            publication.verified_assets(root, root, SHA)
        self.assertIn("--source-digest", verify.call_args.args)
        self.assertIn(SHA, verify.call_args.args)
        connector.assert_not_called()


if __name__ == "__main__":
    unittest.main()
