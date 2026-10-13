import pyexpat
import unittest

from qa.expat_runtime_security import probe_expat_security, require_patched_expat


class ExpatRuntimeSecurityTests(unittest.TestCase):
    def test_old_library_is_rejected_before_invalid_native_calls(self):
        for version in ((2, 5, 0), (2, 8, 4), (2, 8, 5)):
            with self.subTest(version=version), self.assertRaisesRegex(RuntimeError, "2.9.0"):
                require_patched_expat(version)

    def test_fixed_version_is_admitted(self):
        require_patched_expat((2, 9, 0))

    @unittest.skipUnless(pyexpat.version_info >= (2, 9, 0), "Requires patched Linux image XML library")
    def test_actual_library_rejects_buffer_overrun_and_accepts_valid_control(self):
        self.assertEqual(probe_expat_security()["expat_buffer_bound_negatives"], 4)


if __name__ == "__main__":
    unittest.main()
