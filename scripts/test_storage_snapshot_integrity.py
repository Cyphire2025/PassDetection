"""Fail-closed migration checks for source access and retention semantics."""

from __future__ import annotations

import copy
import importlib.util
import json
import unittest
from pathlib import Path
from unittest.mock import Mock

from botocore.exceptions import ClientError

SPEC = importlib.util.spec_from_file_location(
    "migration_integrity_tests_target",
    Path(__file__).resolve().parents[1] / "backend/scripts/storage_snapshot_integrity.py",
)
assert SPEC is not None and SPEC.loader is not None
integrity = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(integrity)

BUCKET = "synthetic-private-passports"
VERSION = "historical-version"
ABSENT = {
    "get_object_lock_configuration": "ObjectLockConfigurationNotFoundError",
    "get_bucket_encryption": "ServerSideEncryptionConfigurationNotFoundError",
    "get_bucket_lifecycle_configuration": "NoSuchLifecycleConfiguration",
    "get_bucket_policy": "NoSuchBucketPolicy",
    "get_bucket_cors": "NoSuchCORSConfiguration",
}


def private_acl(owner="canonical-owner"):
    return {"Owner": {"ID": owner}, "Grants": [{
        "Grantee": {"Type": "CanonicalUser", "ID": owner}, "Permission": "FULL_CONTROL",
    }]}


def api_error(operation, code):
    return ClientError({"Error": {"Code": code, "Message": "Synthetic failure"}}, operation)


def private_source():
    source = Mock(spec=[*ABSENT, "get_bucket_acl", "head_object", "get_object_acl", "get_object_tagging"])
    for name, code in ABSENT.items():
        getattr(source, name).side_effect = api_error(name, code)
    source.get_bucket_acl.return_value = private_acl()
    source.head_object.return_value = {"ContentType": "application/octet-stream", "Metadata": {"source": "synthetic"}}
    source.get_object_acl.return_value = private_acl()
    source.get_object_tagging.return_value = {"TagSet": []}
    return source


class StorageSnapshotIntegrityTests(unittest.TestCase):
    def test_private_canonical_and_minio_compatibility_acls_are_accepted(self):
        for owner in ("canonical-owner", ""):
            with self.subTest(owner=owner):
                integrity.require_private_acl(private_acl(owner))

    def test_public_authenticated_and_custom_grants_are_rejected(self):
        cases = {
            "public-read": {"Type": "Group", "URI": "http://acs.amazonaws.com/groups/global/AllUsers"},
            "authenticated-users": {"Type": "Group", "URI": "http://acs.amazonaws.com/groups/global/AuthenticatedUsers"},
            "different-owner": {"Type": "CanonicalUser", "ID": "another-account"},
            "email-grantee": {"Type": "AmazonCustomerByEmail", "EmailAddress": "synthetic@example.invalid"},
            "canonical-with-uri": {"Type": "CanonicalUser", "ID": "canonical-owner", "URI": "unexpected"},
            "canonical-with-email": {"Type": "CanonicalUser", "ID": "canonical-owner", "EmailAddress": "synthetic@example.invalid"},
        }
        for name, grantee in cases.items():
            with self.subTest(name=name):
                acl = private_acl()
                acl["Grants"][0]["Grantee"] = grantee
                with self.assertRaisesRegex(RuntimeError, "Custom ACL"):
                    integrity.require_private_acl(acl)

    def test_missing_multiple_and_non_full_control_grants_are_rejected(self):
        extra = private_acl()
        extra["Grants"].append(copy.deepcopy(extra["Grants"][0]))
        readonly = private_acl()
        readonly["Grants"][0]["Permission"] = "READ"
        for acl in ({}, {"Owner": {"ID": "canonical-owner"}, "Grants": []}, extra, readonly):
            with self.subTest(acl=acl), self.assertRaisesRegex(RuntimeError, "Custom ACL"):
                integrity.require_private_acl(acl)

    def test_only_recognized_absent_configuration_errors_are_accepted(self):
        source = private_source()
        integrity.require_supported_source(source, BUCKET)
        for name in (*ABSENT, "get_bucket_acl"):
            getattr(source, name).assert_called_once_with(Bucket=BUCKET)

    def test_access_denied_and_unknown_provider_errors_are_not_treated_as_absent(self):
        for operation in (*ABSENT, "get_bucket_acl"):
            for code in ("AccessDenied", "NotImplemented", "InternalError", "404"):
                with self.subTest(operation=operation, code=code):
                    source = private_source()
                    error = api_error(operation, code)
                    getattr(source, operation).side_effect = error
                    with self.assertRaises(ClientError) as caught:
                        integrity.require_supported_source(source, BUCKET)
                    self.assertIs(caught.exception, error)

    def test_policy_cors_encryption_retention_and_lifecycle_cannot_be_silently_dropped(self):
        configured = {
            "get_object_lock_configuration": {"ObjectLockConfiguration": {"ObjectLockEnabled": "Enabled"}},
            "get_bucket_encryption": {"ServerSideEncryptionConfiguration": {"Rules": [{"ApplyServerSideEncryptionByDefault": {"SSEAlgorithm": "AES256"}}]}},
            "get_bucket_lifecycle_configuration": {"Rules": [{"ID": "retention", "Status": "Enabled", "Expiration": {"Days": 365}}]},
            "get_bucket_policy": {"Policy": json.dumps({"Version": "2012-10-17", "Statement": [{"Effect": "Deny", "Action": "s3:DeleteObjectVersion", "Resource": "*", "Principal": "*"}]})},
            "get_bucket_cors": {"CORSRules": [{"AllowedOrigins": ["https://synthetic.example.invalid"], "AllowedMethods": ["GET"]}]},
        }
        for operation, response in configured.items():
            with self.subTest(operation=operation):
                source = private_source()
                method = getattr(source, operation)
                method.side_effect = None
                method.return_value = {**response, "ResponseMetadata": {"HTTPStatusCode": 200}}
                with self.assertRaisesRegex(RuntimeError, "separately reviewed migration"):
                    integrity.require_supported_source(source, BUCKET)

    def test_response_metadata_alone_is_not_a_storage_policy(self):
        source = private_source()
        for operation in ABSENT:
            getattr(source, operation).side_effect = None
            getattr(source, operation).return_value = {"ResponseMetadata": {"HTTPStatusCode": 200}}
        integrity.require_supported_source(source, BUCKET)

    def test_public_bucket_acl_rejects_source(self):
        source = private_source()
        source.get_bucket_acl.return_value["Grants"].append({
            "Grantee": {"Type": "Group", "URI": "http://acs.amazonaws.com/groups/global/AllUsers"},
            "Permission": "READ",
        })
        with self.assertRaisesRegex(RuntimeError, "Custom ACL"):
            integrity.require_supported_source(source, BUCKET)

    def test_historical_version_acl_is_checked_before_accepting_attributes(self):
        source = private_source()
        source.get_object_acl.return_value["Grants"][0]["Grantee"]["ID"] = "other-account"
        with self.assertRaisesRegex(RuntimeError, "Custom ACL"):
            integrity.attributes(source, BUCKET, "passport", VERSION)
        source.get_object_acl.assert_called_once_with(Bucket=BUCKET, Key="passport", VersionId=VERSION)
        source.get_object_tagging.assert_not_called()

    def test_object_acl_access_denied_fails_closed(self):
        source = private_source()
        source.get_object_acl.side_effect = api_error("get_object_acl", "AccessDenied")
        with self.assertRaises(ClientError):
            integrity.attributes(source, BUCKET, "passport", VERSION)
        source.get_object_tagging.assert_not_called()

    def test_object_encryption_and_retention_are_rejected_per_version(self):
        for property_name, value in (
            ("ServerSideEncryption", "AES256"), ("SSECustomerAlgorithm", "AES256"),
            ("ObjectLockMode", "GOVERNANCE"), ("ObjectLockRetainUntilDate", "2030-01-01"),
            ("ObjectLockLegalHoldStatus", "ON"),
        ):
            with self.subTest(property_name=property_name):
                source = private_source()
                source.head_object.return_value[property_name] = value
                with self.assertRaisesRegex(RuntimeError, "Protected object"):
                    integrity.attributes(source, BUCKET, "passport", VERSION)
                source.get_object_tagging.assert_not_called()

    def test_private_attributes_preserve_metadata_and_canonical_tags(self):
        source = private_source()
        source.get_object_acl.return_value = private_acl("")
        source.get_object_tagging.return_value = {"TagSet": [{"Key": "z", "Value": "last"}, {"Key": "a", "Value": "first"}]}
        result = json.loads(integrity.attributes(source, BUCKET, "passport", VERSION))
        self.assertEqual(result["Metadata"], {"source": "synthetic"})
        self.assertEqual(result["Tags"], [{"Key": "a", "Value": "first"}, {"Key": "z", "Value": "last"}])
        source.head_object.assert_called_once_with(Bucket=BUCKET, Key="passport", VersionId=VERSION)
        source.get_object_tagging.assert_called_once_with(Bucket=BUCKET, Key="passport", VersionId=VERSION)


if __name__ == "__main__":
    unittest.main()
