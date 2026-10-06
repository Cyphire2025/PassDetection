"""Exercise publication/reuse through mocked GitHub metadata and asset downloads."""
from __future__ import annotations

import copy
import json
import subprocess
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch
from urllib.parse import parse_qs, urlsplit

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
        self.release = {"id": 101, "tag_name": TAG, "target_commitish": SHA, "draft": False, "assets": entries}
        self.published = copy.deepcopy(self.release)
        self.draft = None
        self.pending_release = None
        self.tag_target = SHA
        self.commands = []
        self.creations = []

    def gh(self, args, **kwargs):
        self.commands.append(args)
        self.assertEqual(args[:4], ["gh", "api", "--hostname", "github.com"])
        endpoint = args[5] if args[4] == "--include" else args[4]
        method = args[args.index("--method") + 1] if "--method" in args else "GET"
        self.assertIn(method, ("GET", "POST", "PATCH"))  # no DELETE in any failure/retry path
        if endpoint == "graphql":
            self.assertEqual(method, "POST")
            payload = json.loads(kwargs["input"])
            self.assertIn("release(tagName: $tag)", payload["query"])
            self.assertEqual(payload["variables"], {"owner": "Cyphire2025", "name": "PassDetection", "tag": TAG})
            return subprocess.CompletedProcess(args, 0, "HTTP/2.0 200 OK\n\n" + json.dumps({
                "data": {"repository": {"release": self.pending_release}}}))
        if method == "POST" and endpoint == "repos/Cyphire2025/PassDetection/releases":
            self.creations.append(args)
            payload = json.loads(kwargs["input"])
            self.assertEqual(payload["target_commitish"], SHA)
            self.assertEqual(payload["tag_name"], TAG)
            self.assertIs(payload["draft"], True)
            self.draft = {**copy.deepcopy(self.release), "draft": True, "assets": []}
            return subprocess.CompletedProcess(args, 0, "HTTP/2.0 201 Created\r\n\r\n" + json.dumps(self.draft))
        if method == "POST" and endpoint.startswith("https://uploads.github.com/"):
            self.assertIsNone(self.published)  # immutable published releases cannot accept new assets
            url = urlsplit(endpoint)
            self.assertEqual(url.path, "/repos/Cyphire2025/PassDetection/releases/101/assets")
            name = parse_qs(url.query)["name"][0]
            path = Path(args[args.index("--input") + 1])
            self.assertEqual(path, self.assets[name])
            self.assertIn("Content-Type: application/octet-stream", args)
            entry = copy.deepcopy(next(e for e in self.release["assets"] if e["name"] == name))
            self.draft["assets"].append(entry)
            return subprocess.CompletedProcess(args, 0, "HTTP/2.0 201 Created\n\n" + json.dumps(entry))
        if method == "PATCH":
            self.assertEqual(endpoint, "repos/Cyphire2025/PassDetection/releases/101")
            self.assertEqual(json.loads(kwargs["input"]), {"draft": False})
            self.published = {**copy.deepcopy(self.draft), "draft": False, "immutable": True}
            self.tag_target = SHA
            return subprocess.CompletedProcess(args, 0, "HTTP/2.0 200 OK\n\n" + json.dumps(self.published))
        if "/releases/assets/" in endpoint:
            self.assertEqual(args[-2:], ["--header", "Accept: application/octet-stream"])
            kwargs["stdout"].write(self.downloads[int(endpoint.rsplit("/", 1)[1])])
            return subprocess.CompletedProcess(args, 0)
        if "/releases/tags/" in endpoint:
            value = self.published
        elif endpoint == "repos/Cyphire2025/PassDetection/releases/101":
            value = self.draft
        elif "/git/ref/tags/" in endpoint:
            value = None if self.tag_target is None else {
                "ref": "refs/tags/" + TAG, "object": {"type": "commit", "sha": self.tag_target}}
        else:
            self.fail("Unexpected endpoint: " + endpoint)
        if value is None:
            return subprocess.CompletedProcess(args, 1, "HTTP/2.0 404 Not Found\n\n{}")
        return subprocess.CompletedProcess(args, 0, "HTTP/2.0 200 OK\n\n" + json.dumps(value))

    def publish(self, transport=None):
        with patch.object(publication, "verified_assets", return_value=self.assets), \
                patch.object(publication.subprocess, "run", side_effect=transport or self.gh):
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
        self.assertIs(self.published["immutable"], True)
        self.assertEqual(sum("/releases/assets/" in " ".join(args) for args in self.commands), 14)
        publish_at = next(n for n, args in enumerate(self.commands) if "PATCH" in args)
        self.assertEqual(sum("/releases/assets/" in " ".join(args) for args in self.commands[:publish_at]), 7)

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

    def test_partial_upload_failure_retains_draft_and_every_uploaded_asset_without_retry(self):
        self.published = self.tag_target = None
        def fail(args, **kwargs):
            result = self.gh(args, **kwargs)
            if args[5].startswith("https://uploads.github.com/") and len(self.draft["assets"]) == 2:
                return subprocess.CompletedProcess(args, 1, "HTTP/2.0 500 Server Error\n\n{}")
            return result
        with self.assertRaisesRegex(ValueError, "without cleanup"):
            self.publish(fail)
        self.assertEqual(len(self.creations), 1)
        self.assertEqual(len(self.draft["assets"]), 2)
        self.assertIsNone(self.published)
        self.assertFalse(any("PATCH" in args for args in self.commands))

    def test_ambiguous_draft_creation_stops_without_retry_and_preserves_created_draft(self):
        self.published = self.tag_target = None
        def fail(args, **kwargs):
            result = self.gh(args, **kwargs)
            if "POST" in args and args[5] != "graphql":
                return subprocess.CompletedProcess(args, 1, "connection closed")
            return result
        with self.assertRaisesRegex(ValueError, "Cannot establish"):
            self.publish(fail)
        self.assertEqual(len(self.creations), 1)
        self.assertEqual(self.draft["assets"], [])
        self.assertIsNone(self.published)

    def test_ambiguous_publish_stops_without_cleanup_even_if_server_published(self):
        self.published = self.tag_target = None
        def fail(args, **kwargs):
            result = self.gh(args, **kwargs)
            if "PATCH" in args:
                return subprocess.CompletedProcess(args, 1, "HTTP/2.0 502 Bad Gateway\n\n{}")
            return result
        with self.assertRaisesRegex(ValueError, "without cleanup"):
            self.publish(fail)
        self.assertIs(self.published["draft"], False)
        self.assertEqual(len(self.published["assets"]), 7)
        self.assertEqual(sum("PATCH" in args for args in self.commands), 1)

    def test_draft_readback_with_different_bytes_is_never_published(self):
        self.published = self.tag_target = None
        self.downloads[1] = b"x" * len(self.downloads[1])
        with self.assertRaisesRegex(ValueError, "bytes differ"):
            self.publish()
        self.assertEqual(len(self.draft["assets"]), 7)
        self.assertIsNone(self.published)
        self.assertFalse(any("PATCH" in args for args in self.commands))

    def test_changed_draft_target_or_publication_state_is_not_published(self):
        for change in ({"target_commitish": OTHER}, {"draft": False}, {"id": 102}):
            self.published = self.tag_target = None
            self.commands = []
            def changed(args, _change=change, **kwargs):
                if len(args) > 5 and args[5].endswith("/releases/101") and "--method" not in args:
                    self.draft.update(_change)
                return self.gh(args, **kwargs)
            with self.subTest(change=change), self.assertRaisesRegex(ValueError, "draft identity"):
                self.publish(changed)
            self.assertFalse(any("PATCH" in args for args in self.commands))

    def test_wrong_tag_created_during_draft_readback_blocks_publication(self):
        self.published = self.tag_target = None
        def changed(args, **kwargs):
            result = self.gh(args, **kwargs)
            if "/releases/assets/" in " ".join(args):
                self.tag_target = OTHER
            return result
        with self.assertRaisesRegex(ValueError, "selected commit"):
            self.publish(changed)
        self.assertFalse(any("PATCH" in args for args in self.commands))

    def test_write_404_is_failure_not_resource_absence(self):
        github = publication.GitHub("Cyphire2025/PassDetection")
        with patch.object(publication.subprocess, "run", return_value=subprocess.CompletedProcess(
                [], 1, "HTTP/2.0 404 Not Found\n\n{}")), self.assertRaisesRegex(ValueError, "without cleanup"):
            github.request("releases", method="POST", payload={"draft": True})

    def test_pending_draft_hidden_by_rest_404_stops_before_creating_or_resuming(self):
        self.published = self.tag_target = None
        self.pending_release = {"databaseId": 909, "isDraft": True, "tagName": TAG}
        with self.assertRaisesRegex(ValueError, "pending tag"):
            self.publish()
        self.assertEqual(self.creations, [])
        self.assertFalse(any("PATCH" in args or args[5].startswith("https://uploads.github.com/")
                             for args in self.commands))

    def test_concurrent_published_release_seen_by_pending_lookup_stops_creation(self):
        self.published = self.tag_target = None
        self.pending_release = {"databaseId": 909, "isDraft": False, "tagName": TAG}
        with self.assertRaisesRegex(ValueError, "pending tag"):
            self.publish()
        self.assertEqual(self.creations, [])

    def test_pending_release_lookup_errors_or_missing_fields_are_not_absence(self):
        github = publication.GitHub("Cyphire2025/PassDetection")
        for response in ({"errors": [{"message": "denied"}], "data": {"repository": {"release": None}}},
                         {"data": {"repository": None}}, {"data": {"repository": {}}}, {}):
            with self.subTest(response=response), patch.object(publication.subprocess, "run",
                    return_value=subprocess.CompletedProcess([], 0, "HTTP/2.0 200 OK\n\n" + json.dumps(response))), \
                    self.assertRaisesRegex(ValueError, "pending release state"):
                github.require_no_pending_release(TAG)

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
