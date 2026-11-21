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
        try:
            method = atomic_publish.publish_no_replace(self.source, self.destination)
        except OSError as exc:
            unsupported = {
                errno.ENOTSUP,
                errno.ENOSYS,
                getattr(errno, "EOPNOTSUPP", errno.ENOTSUP),
            }
            if exc.errno in unsupported:
                self.assertTrue(os.path.exists(self.source))
                self.assertFalse(os.path.exists(self.destination))
                self.skipTest(
                    f"filesystem does not support hard-link publication: errno={exc.errno}"
                )
            raise
        self.assertEqual(method, "hard-link")
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
        try:
            with patch.object(atomic_publish.os, "link", None, create=True):
                method = atomic_publish.publish_no_replace(
                    self.source, self.destination
                )
        except OSError as exc:
            unsupported = {
                errno.ENOTSUP,
                errno.ENOSYS,
                getattr(errno, "EOPNOTSUPP", errno.ENOTSUP),
            }
            if exc.errno in unsupported:
                self.assertTrue(os.path.exists(self.source))
                self.assertFalse(os.path.exists(self.destination))
                self.skipTest(
                    f"filesystem does not support renameat2(RENAME_NOREPLACE): "
                    f"errno={exc.errno}"
                )
            raise
        self.assertEqual(method, "renameat2")
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


    def test_renameat2_filesystem_probe_default_temp_and_repo(self):
        """Report no-replace syscall support on default temp and ~/Capri."""
        renameat2_available = atomic_publish._load_renameat2() is not None
        repo_root = os.path.join(os.path.expanduser("~"), "Capri")
        candidates = (
            ("default_tmp", tempfile.gettempdir()),
            ("repo", repo_root),
        )
        unsupported_errnos = {errno.ENOTSUP, errno.ENOSYS}
        if hasattr(errno, "EOPNOTSUPP"):
            unsupported_errnos.add(errno.EOPNOTSUPP)

        for label, base in candidates:
            if not os.path.isdir(base) or os.path.realpath(base) != base:
                print(
                    f"RENAMEAT2_PROBE label={label} base={base!r} "
                    "status=missing_or_symlink"
                )
                continue

            try:
                with tempfile.TemporaryDirectory(
                    prefix="capri-renameat2-probe-", dir=base
                ) as directory:
                    hardlink_result = "unavailable"
                    if callable(getattr(os, "link", None)):
                        hard_source = os.path.join(directory, "hard-source")
                        hard_destination = os.path.join(directory, "hard-destination")
                        with open(hard_source, "wb") as stream:
                            stream.write(b"hard-link-probe")
                        try:
                            os.link(
                                hard_source, hard_destination, follow_symlinks=False
                            )
                            hardlink_result = "success"
                        except OSError as exc:
                            hardlink_result = (
                                f"errno={exc.errno}:"
                                f"{errno.errorcode.get(exc.errno, 'UNKNOWN')}"
                            )

                    source = os.path.join(directory, "source")
                    destination = os.path.join(directory, "destination")
                    with open(source, "wb") as stream:
                        stream.write(b"renameat2-probe")

                    try:
                        with patch.object(
                            atomic_publish.os, "link", None, create=True
                        ):
                            method = atomic_publish.publish_no_replace(
                                source, destination
                            )
                        self.assertEqual(method, "renameat2")
                        self.assertFalse(os.path.exists(source))
                        with open(destination, "rb") as stream:
                            self.assertEqual(stream.read(), b"renameat2-probe")

                        collision_source = os.path.join(directory, "collision-source")
                        with open(collision_source, "wb") as stream:
                            stream.write(b"must-not-replace")
                        with patch.object(
                            atomic_publish.os, "link", None, create=True
                        ):
                            with self.assertRaises(OSError) as caught:
                                atomic_publish.publish_no_replace(
                                    collision_source, destination
                                )
                        self.assertEqual(caught.exception.errno, errno.EEXIST)
                        self.assertTrue(os.path.exists(collision_source))
                        with open(destination, "rb") as stream:
                            self.assertEqual(stream.read(), b"renameat2-probe")
                        status = "success"
                        operation_errno = 0
                    except OSError as exc:
                        status = (
                            "unsupported"
                            if exc.errno in unsupported_errnos
                            else "error"
                        )
                        operation_errno = exc.errno
                        self.assertTrue(os.path.exists(source))
                        self.assertFalse(os.path.exists(destination))
                        if status != "unsupported":
                            self.fail(
                                f"{label} renameat2 failed unexpectedly: "
                                f"errno={exc.errno} {exc.strerror}"
                            )

                    print(
                        f"RENAMEAT2_PROBE label={label} base={base!r} "
                        f"temp={directory!r} libc_symbol={renameat2_available} "
                        f"hardlink={hardlink_result} status={status} "
                        f"errno={operation_errno} "
                        f"errno_name={errno.errorcode.get(operation_errno, 'NONE')}"
                    )
            except OSError as exc:
                print(
                    f"RENAMEAT2_PROBE label={label} base={base!r} "
                    f"status=setup_error errno={exc.errno} "
                    f"errno_name={errno.errorcode.get(exc.errno, 'UNKNOWN')}"
                )


if __name__ == "__main__":
    unittest.main()
