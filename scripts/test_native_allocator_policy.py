"""Fail closed when a low-level allocator exception expands beyond reviewed bytes."""
import hashlib
import unittest
from pathlib import Path
from unittest.mock import patch

from qa import native_allocator_policy as policy


class NativeAllocatorPolicyTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.source = (Path(__file__).resolve().parents[1] /
                      "backend/app/core/native_image_admission.py").read_bytes().replace(b"\r\n", b"\n")
        # The qualified Linux image receives Git's LF source bytes. Windows
        # checkout conversion must not change this test fixture; the production
        # checker still requires the exact complete source and function hashes.

    def test_exact_qualified_call_is_explained_and_bound(self):
        result = policy.reviewed_allocator_source(policy.REVIEWED_PATH, self.source)
        self.assertIsNotNone(result)
        self.assertEqual(result["call"], "malloc_trim(0)")
        self.assertEqual(result["source_sha256"], hashlib.sha256(self.source).hexdigest())
        self.assertEqual(result["argument_types"], "[ctypes.c_size_t]")
        self.assertEqual(result["return_type"], "ctypes.c_int")

    def test_same_code_in_other_or_noncanonical_file_is_denied(self):
        for path in ("/app/app/core/other.py", "/opt/native_image_admission.py",
                     "/app/app/core/../core/native_image_admission.py",
                     "/app/app/core//native_image_admission.py"):
            with self.subTest(path=path):
                self.assertIsNone(policy.reviewed_allocator_source(path, self.source))

    def test_complete_source_binding_rejects_added_calls_outside_function(self):
        for extra in (b"\nctypes.CDLL('libc.so.6').strfmon\n",
                      b"\nctypes.CDLL(None).system(b'id')\n",
                      b"\n# Even a harmless changed source needs a new review.\n"):
            with self.subTest(extra=extra):
                self.assertIsNone(policy.reviewed_allocator_source(policy.REVIEWED_PATH, self.source + extra))

    def test_signature_still_rejects_other_libraries_symbols_or_arguments_if_source_pin_is_updated(self):
        # Updating just a file hash must not silently widen the reviewed FFI
        # signature. The independently pinned complete function AST remains.
        mutations = ((b"ctypes.CDLL(None)", b"ctypes.CDLL('libc.so.6')"),
                     (b"ctypes.CDLL(None)", b"ctypes.PyDLL(None)"),
                     (b"library.malloc_trim", b"library.strfmon"),
                     (b"library.malloc_trim", b"library.system"),
                     (b"trim(0)", b"trim(1)"),
                     (b"trim(0)", b"trim(os.environ['CALL_ARG'])"),
                     (b"[ctypes.c_size_t]", b"[ctypes.c_char_p]"),
                     (b"trim.restype = ctypes.c_int", b"trim.restype = ctypes.c_void_p"),
                     (b'"gnu_get_libc_version"', b'"dlsym"'))
        for old, new in mutations:
            with self.subTest(new=new):
                self.assertIn(old, self.source)
                mutated = self.source.replace(old, new)
                with patch.object(policy, "REVIEWED_SOURCE_SHA256", hashlib.sha256(mutated).hexdigest()):
                    self.assertIsNone(policy.reviewed_allocator_source(policy.REVIEWED_PATH, mutated))


if __name__ == "__main__":
    unittest.main()
