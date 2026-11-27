import os
import stat
import tempfile
import unittest

from capri_runtime import PosixSupervisorLock


@unittest.skipUnless(os.name == "posix", "POSIX flock is required")
class PosixSupervisorLockTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.path = os.path.join(self.temp.name, "supervisor.lock")

    def tearDown(self):
        self.temp.cleanup()

    def test_lock_file_is_private_and_reentrant(self):
        lock = PosixSupervisorLock(self.path, timeout_seconds=0.1)
        try:
            with lock:
                with lock:
                    pass
            info = os.stat(self.path, follow_symlinks=False)
            self.assertEqual(stat.S_IMODE(info.st_mode), 0o600)
            self.assertEqual(info.st_nlink, 1)
            self.assertEqual(info.st_uid, os.geteuid())
        finally:
            lock.close()

    def test_independent_instances_contend_and_release(self):
        first = PosixSupervisorLock(self.path, timeout_seconds=0.05)
        second = PosixSupervisorLock(self.path, timeout_seconds=0.05)
        try:
            with first:
                with self.assertRaises(TimeoutError):
                    with second:
                        pass
            with second:
                pass
        finally:
            first.close()
            second.close()

    def test_rejects_symlink_and_hard_link_aliases(self):
        target = os.path.join(self.temp.name, "target")
        with open(target, "w", encoding="utf-8"):
            pass
        os.chmod(target, 0o600)
        symlink = os.path.join(self.temp.name, "symlink")
        os.symlink(target, symlink)
        with self.assertRaises(OSError):
            PosixSupervisorLock(symlink)

        lock = PosixSupervisorLock(self.path)
        lock.close()
        alias = os.path.join(self.temp.name, "alias")
        os.link(self.path, alias)
        with self.assertRaises(PermissionError):
            PosixSupervisorLock(self.path)

    def test_rejects_non_private_parent_directory(self):
        parent = os.path.join(self.temp.name, "shared")
        os.mkdir(parent)
        os.chmod(parent, 0o755)
        try:
            with self.assertRaises(PermissionError):
                PosixSupervisorLock(os.path.join(parent, "supervisor.lock"))
        finally:
            os.chmod(parent, 0o700)

    def test_inherited_descriptor_is_rejected(self):
        lock = PosixSupervisorLock(self.path)
        try:
            lock._owner_pid -= 1
            with self.assertRaises(RuntimeError):
                with lock:
                    pass
        finally:
            lock.close()


if __name__ == "__main__":
    unittest.main()
