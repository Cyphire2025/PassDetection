import sys
import unittest

from qa.python_runtime_security import probe_python_security, require_patched_python


class PythonRuntimeSecurityTests(unittest.TestCase):
    def test_older_security_releases_and_unreviewed_series_fail_closed(self):
        for version in ((3, 11, 15), (3, 11, 16), (3, 10, 99), (3, 12, 0)):
            with self.subTest(version=version), self.assertRaisesRegex(RuntimeError, "3.11.17"):
                require_patched_python(version)

    def test_current_and_later_security_releases_are_accepted(self):
        for version in ((3, 11, 17), (3, 11, 18)):
            with self.subTest(version=version):
                require_patched_python(version)

    @unittest.skipUnless(sys.version_info[:2] == (3, 11) and sys.version_info[:3] >= (3, 11, 17),
                         "Real TLS probes require the patched production interpreter")
    def test_actual_in_memory_tls_rejects_client_only_server_arguments(self):
        self.assertEqual(probe_python_security()["ssl_wrap_bio_argument_negatives"], 2)


if __name__ == "__main__":
    unittest.main()
