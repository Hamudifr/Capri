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

    def test_hard_link_collision_preserves_both_files(self):
        if not callable(getattr(os, "link", None)):
            self.skipTest("Python os.link is unavailable")
        with open(self.destination, "wb") as stream:
            stream.write(b"existing")
        with self.assertRaises(OSError) as caught:
            atomic_publish.publish_no_replace(self.source, self.destination)
        self.assertEqual(caught.exception.errno, errno.EEXIST)
        self.assertTrue(os.path.exists(self.source))
        self.assertTrue(os.path.exists(self.destination))
        with open(self.source, "rb") as stream:
            self.assertEqual(stream.read(), b"original")
        with open(self.destination, "rb") as stream:
            self.assertEqual(stream.read(), b"existing")

    def test_unsupported_hard_link_falls_back_to_renameat2(self):
        fake_renameat2 = Mock(return_value=0)
        with patch.object(
            atomic_publish.os,
            "link",
            side_effect=OSError(getattr(errno, "EOPNOTSUPP", getattr(errno, "ENOTSUP", errno.EINVAL)), "hard links unsupported"),
        ), patch.object(
            atomic_publish, "_load_renameat2", return_value=fake_renameat2
        ):
            self.assertEqual(
                atomic_publish.publish_no_replace(self.source, self.destination),
                "renameat2",
            )
        fake_renameat2.assert_called_once()

    def test_hard_link_collision_does_not_fall_back(self):
        fake_renameat2 = Mock(return_value=0)
        with patch.object(
            atomic_publish.os,
            "link",
            side_effect=FileExistsError(errno.EEXIST, "destination exists"),
        ), patch.object(
            atomic_publish, "_load_renameat2", return_value=fake_renameat2
        ):
            with self.assertRaises(FileExistsError):
                atomic_publish.publish_no_replace(self.source, self.destination)
        fake_renameat2.assert_not_called()

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
