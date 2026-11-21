import errno
import os
import sys
import tempfile
import unittest
from unittest.mock import Mock, patch

from capri_runtime import atomic_publish


class AtomicPublishTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.source = os.path.join(self.temp.name, "source")
        self.destination = os.path.join(self.temp.name, "destination")
        with open(self.source, "wb") as stream:
            stream.write(b"original")

    def tearDown(self):
        self.temp.cleanup()

    def test_hard_link_publication_is_no_replace(self):
        if not callable(getattr(os, "link", None)):
            self.skipTest("Python os.link is unavailable")
        self.assertEqual(
            atomic_publish.publish_no_replace(self.source, self.destination),
            "hard-link",
        )
        self.assertTrue(os.path.exists(self.source))
        os.unlink(self.source)
        self.assertFalse(os.path.exists(self.source))
        with open(self.destination, "rb") as stream:
            self.assertEqual(stream.read(), b"original")

    def test_android_platform_attempts_to_load_renameat2(self):
        fake_libc = Mock()
        fake_renameat2 = Mock()
        fake_libc.renameat2 = fake_renameat2
        with patch.object(atomic_publish.sys, "platform", "android"), patch.object(
            atomic_publish.ctypes, "CDLL", return_value=fake_libc
        ) as load_library:
            self.assertIs(atomic_publish._load_renameat2(), fake_renameat2)
        load_library.assert_called_once_with(None, use_errno=True)

    @unittest.skipUnless(
        os.name == "posix" and sys.platform.startswith(("linux", "android")),
        "Linux or Android renameat2 is required",
    )
    def test_renameat2_publication_and_collision_preservation(self):
        if atomic_publish._load_renameat2() is None:
            self.skipTest("libc renameat2 is unavailable")
        with patch.object(atomic_publish.os, "link", None, create=True):
            self.assertEqual(
                atomic_publish.publish_no_replace(self.source, self.destination),
                "renameat2",
            )
            self.assertFalse(os.path.exists(self.source))
            with open(self.destination, "rb") as stream:
                self.assertEqual(stream.read(), b"original")
            collision_source = os.path.join(self.temp.name, "collision")
            with open(collision_source, "wb") as stream:
                stream.write(b"replacement")
            with self.assertRaises(OSError) as caught:
                atomic_publish.publish_no_replace(collision_source, self.destination)
            self.assertEqual(caught.exception.errno, errno.EEXIST)
            self.assertTrue(os.path.exists(collision_source))
            with open(self.destination, "rb") as stream:
                self.assertEqual(stream.read(), b"original")

    def test_missing_primitives_fail_closed(self):
        with patch.object(atomic_publish.os, "link", None, create=True), patch.object(
            atomic_publish, "_load_renameat2", return_value=None
        ):
            with self.assertRaises(OSError) as caught:
                atomic_publish.publish_no_replace(self.source, self.destination)
        self.assertEqual(caught.exception.errno, errno.ENOTSUP)
        self.assertTrue(os.path.exists(self.source))
        self.assertFalse(os.path.exists(self.destination))


if __name__ == "__main__":
    unittest.main()
