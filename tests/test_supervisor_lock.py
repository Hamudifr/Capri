import errno
import os
import stat
import tempfile
import unittest
from unittest import mock

from capri_runtime import PosixSupervisorLock


@unittest.skipUnless(os.name == "posix", "POSIX flock is required")
class PosixSupervisorLockTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.lock_dir = os.path.realpath(self.temp.name)
        self.path = os.path.join(self.lock_dir, "supervisor.lock")

    def tearDown(self):
        self.temp.cleanup()

    def test_lock_file_is_private_and_reentrant(self):
        lock = PosixSupervisorLock(self.path, timeout_seconds=0.1)
        try:
            self.assertFalse(os.get_inheritable(lock._fd))
            self.assertFalse(os.get_inheritable(lock._parent_fd))
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
        target = os.path.join(self.lock_dir, "target")
        with open(target, "w", encoding="utf-8"):
            pass
        os.chmod(target, 0o600)
        symlink = os.path.join(self.lock_dir, "symlink")
        os.symlink(target, symlink)
        with self.assertRaises(OSError):
            PosixSupervisorLock(symlink)

        lock = PosixSupervisorLock(self.path)
        lock.close()
        alias = os.path.join(self.lock_dir, "alias")
        os.link(self.path, alias)
        with self.assertRaises(PermissionError):
            PosixSupervisorLock(self.path)

    def test_rejects_symlink_in_parent_path(self):
        real_parent = os.path.join(self.lock_dir, "real-parent")
        os.mkdir(real_parent, 0o700)
        alias_parent = os.path.join(self.lock_dir, "alias-parent")
        os.symlink(real_parent, alias_parent)
        with self.assertRaises(OSError):
            PosixSupervisorLock(os.path.join(alias_parent, "supervisor.lock"))

    def test_rejects_non_private_parent_directory(self):
        parent = os.path.join(self.lock_dir, "shared")
        os.mkdir(parent)
        os.chmod(parent, 0o755)
        with self.assertRaises(PermissionError):
            PosixSupervisorLock(os.path.join(parent, "supervisor.lock"))

    def test_rejects_replaced_lock_inode(self):
        lock = PosixSupervisorLock(self.path)
        replacement = os.path.join(self.lock_dir, "replacement")
        with open(replacement, "w", encoding="utf-8"):
            pass
        os.chmod(replacement, 0o600)
        os.replace(replacement, self.path)
        try:
            with self.assertRaises(PermissionError):
                with lock:
                    pass
        finally:
            lock.close()

    def test_rejects_replaced_parent_path(self):
        parent = os.path.join(self.lock_dir, "service")
        os.mkdir(parent, 0o700)
        lock_path = os.path.join(parent, "supervisor.lock")
        lock = PosixSupervisorLock(lock_path)
        moved_parent = os.path.join(self.lock_dir, "service-moved")
        os.rename(parent, moved_parent)
        os.mkdir(parent, 0o700)
        try:
            with self.assertRaises(PermissionError):
                with lock:
                    pass
        finally:
            lock.close()

    def test_fails_closed_without_secure_dirfd_support(self):
        with mock.patch(
            "capri_runtime.supervisor_lock._supports_secure_dirfd_walk",
            return_value=False,
        ):
            with self.assertRaises(OSError):
                PosixSupervisorLock(self.path)

    @unittest.skipUnless(
        hasattr(os, "fork") and hasattr(os, "register_at_fork"),
        "Python fork hooks are required",
    )
    def test_fork_closes_inherited_descriptors_and_contends_across_processes(self):
        lock = PosixSupervisorLock(self.path, timeout_seconds=0.5)
        contender = PosixSupervisorLock(self.path, timeout_seconds=0.05)
        try:
            with lock:
                inherited_descriptors = (lock._fd, lock._parent_fd)
                pid = os.fork()
                if pid == 0:
                    try:
                        for descriptor in inherited_descriptors:
                            try:
                                os.fstat(descriptor)
                            except OSError as exc:
                                if exc.errno != errno.EBADF:
                                    os._exit(20)
                            else:
                                os._exit(21)

                        try:
                            with lock:
                                os._exit(22)
                        except RuntimeError:
                            pass

                        child_lock = PosixSupervisorLock(
                            self.path,
                            timeout_seconds=0.05,
                        )
                        try:
                            try:
                                with child_lock:
                                    exit_code = 23
                            except TimeoutError:
                                exit_code = 0
                        finally:
                            child_lock.close()
                        os._exit(exit_code)
                    except BaseException:
                        os._exit(24)

                _, status = os.waitpid(pid, 0)
                self.assertTrue(os.WIFEXITED(status))
                self.assertEqual(os.WEXITSTATUS(status), 0)
                with self.assertRaises(TimeoutError):
                    with contender:
                        pass

            with contender:
                pass
        finally:
            contender.close()
            lock.close()


if __name__ == "__main__":
    unittest.main()
