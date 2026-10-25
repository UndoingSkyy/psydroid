"""Lifecycle regressions using a fake emulator; no Android download or launch."""
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import Mock, patch

from PySide6.QtCore import QCoreApplication

from psydroid.ui import controller as module


def immediate(work, then=None, failed=None):
    try:
        result = work()
    except Exception as error:
        if failed:
            failed(error)
        else:
            raise
    else:
        if then:
            then(result)


class ControllerLifecycleTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.app = QCoreApplication.instance() or QCoreApplication([])

    def setUp(self):
        self.instance = SimpleNamespace(name="Test Android", api="36", wipe_next=False,
                                        log=Path("unused-test.log"), fps=60)
        self.emulator = Mock()
        self.emulator.running.return_value = False
        self.emulator.crashed.return_value = False
        self.emulator.booted.return_value = False
        self.emulator.stuck.return_value = False
        self.emulator.grpc_token.return_value = None
        self.emulator.usage.return_value = None
        self.emulator.fully_stopped.return_value = True
        with patch.object(module.emulator, "Emulator", return_value=self.emulator), \
                patch.object(module.Controller, "poll"):
            self.controller = module.Controller(self.instance, [self.instance])
        self.controller.timer.stop()
        self.controller.save = Mock()
        self.notifications = []
        self.controller.notify.connect(lambda message, kind: self.notifications.append((message, kind)))
        self.image_patch = patch.object(module.installer, "image_installed", return_value=True)
        self.image_patch.start()
        self.addCleanup(self.image_patch.stop)

    def tearDown(self):
        self.controller.timer.stop()
        self.controller.video_timer.stop()
        self.controller.deleteLater()

    def test_spawn_error_remains_visible_and_can_be_retried(self):
        self.emulator.start.side_effect = FileNotFoundError("emulator.exe is missing")
        self.controller.start()
        self.assertEqual(self.controller.state, "crashed")
        self.assertIsNone(self.controller.boot_started)
        self.assertIn("emulator.exe is missing", self.notifications[-1][0])
        self.assertEqual(self.controller.check(False)[0], "crashed")

        self.emulator.start.side_effect = None
        self.controller.start()
        self.assertEqual(self.controller.state, "booting")
        self.assertIsNone(self.controller.boot_error)
        self.assertIsNotNone(self.controller.boot_started)

    def test_failed_spawn_preserves_pending_reset(self):
        self.instance.wipe_next = True
        self.emulator.start.side_effect = PermissionError("cannot launch")
        self.controller.start()
        self.assertTrue(self.instance.wipe_next)
        self.assertEqual(self.controller.save.call_count, 2)
        self.emulator.start.assert_called_once_with(True, False)

    def test_missing_image_does_not_start_emulator(self):
        missing = Mock()
        self.controller.image_missing.connect(missing)
        with patch.object(module.installer, "image_installed", return_value=False):
            self.controller.start()
        self.emulator.start.assert_not_called()
        missing.assert_called_once_with()

    def test_cold_boot_timeout_boundary_and_success(self):
        self.controller.phase = "booting"
        self.controller.boot_started = 100.0
        self.emulator.running.return_value = True
        with patch.object(module.time, "monotonic", return_value=100 + module.COLD_BOOT_LIMIT - 1):
            self.assertEqual(self.controller.check(False)[0], "booting")
        with patch.object(module.time, "monotonic", return_value=100 + module.COLD_BOOT_LIMIT):
            self.assertEqual(self.controller.check(False)[0], "timed_out")
            self.emulator.booted.return_value = True
            self.assertEqual(self.controller.check(False)[0], "on")

    def test_reattached_emulator_has_no_artificial_boot_deadline(self):
        self.emulator.running.return_value = True
        with patch.object(module.time, "monotonic", return_value=1000000):
            self.assertEqual(self.controller.check(False)[0], "booting")

    def test_timeout_stops_once_without_reset_or_restart(self):
        self.controller.phase = "booting"
        self.controller.boot_started = 10.0
        epoch = self.controller.epoch
        with patch.object(module, "background", side_effect=immediate):
            self.controller.apply("timed_out", None, None, epoch)
            self.controller.apply("timed_out", None, None, epoch)
        self.emulator.stop.assert_called_once_with()
        self.emulator.start.assert_not_called()
        self.assertEqual(self.controller.state, "crashed")
        self.assertEqual(self.controller.check(False)[0], "crashed")
        self.assertFalse(self.instance.wipe_next)
        self.assertEqual(len(self.notifications), 1)

    def test_quick_boot_recovery_starts_fresh_without_wiping(self):
        self.controller.phase = "booting"
        with patch.object(module, "background", side_effect=immediate):
            self.controller.apply("stuck", None, None, self.controller.epoch)
        self.emulator.stop.assert_called_once_with()
        self.emulator.start.assert_called_once_with(False, True)
        self.assertEqual(self.controller.state, "booting")

    def test_failed_shutdown_does_not_restart_a_live_process(self):
        self.controller.phase = "booting"
        self.emulator.fully_stopped.return_value = False
        again = Mock()
        with patch.object(module, "background", side_effect=immediate):
            self.controller.stop(then=again)
        again.assert_not_called()
        self.assertEqual(self.controller.state, "booting")
        self.assertIn("still running", self.notifications[-1][0])
        self.emulator.running.return_value = True
        self.emulator.stuck.return_value = True
        self.assertEqual(self.controller.check(False)[0], "booting")

    def test_old_poll_result_cannot_cancel_new_launch(self):
        previous_epoch = self.controller.epoch
        self.controller.start()
        self.controller.apply("off", None, None, previous_epoch)
        self.assertEqual(self.controller.state, "booting")


if __name__ == "__main__":
    unittest.main()
