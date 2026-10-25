"""Instance settings that decide how the emulator is launched; no emulator is started."""
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from psydroid import emulator, instances


class GraphicsModeTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        root = Path(self.temp.name)
        self.sdk = root / "sdk"
        self.sdk.mkdir()
        for name, value in (("AVD_HOME", root / "avd"), ("LOGS", root / "logs"), ("EMULATOR", root / "emulator.exe"),
                            ("SDK", self.sdk)):
            patcher = patch.object(instances.paths, name, value)
            patcher.start()
            self.addCleanup(patcher.stop)

    def test_new_instances_draw_on_the_graphics_card(self):
        self.assertEqual(instances.Instance(id="box1", name="A", slot=0).gpu_mode, "host")

    def test_saved_automatic_mode_launches_on_the_graphics_card(self):
        # Headless "auto" made the emulator pick SwiftShader and draw Android on the processor
        instance = instances.from_dict({"id": "box1", "name": "A", "slot": 0, "gpu": "auto"})
        self.assertEqual(instance.gpu_mode, "host")
        instances.write_avd(instance)
        self.assertIn("hw.gpu.mode=host\n", (instance.folder / "config.ini").read_text())
        with patch.object(emulator.subprocess, "Popen") as popen:
            emulator.Emulator(instance).start()
        args = popen.call_args.args[0]
        self.assertEqual(args[args.index("-gpu") + 1], "host")

    def test_tools_never_start_in_the_folder_psydroid_was_opened_from(self):
        # adb's server outlives PsyDroid and holds its starting folder, which blocked replacing the app folder
        instance = instances.Instance(id="box1", name="A", slot=0)
        with patch.object(emulator.subprocess, "Popen") as popen, patch.object(emulator.subprocess, "run") as run:
            emulator.Emulator(instance).start()
            emulator.run(["adb", "devices"])
        self.assertEqual(popen.call_args.kwargs["cwd"], str(self.sdk))
        self.assertEqual(run.call_args.kwargs["cwd"], str(self.sdk))

    def test_software_mode_is_kept_for_graphics_drivers_that_crash(self):
        instance = instances.from_dict({"id": "box1", "name": "A", "slot": 0, "gpu": "swangle"})
        self.assertEqual(instance.gpu_mode, "swangle")


if __name__ == "__main__":
    unittest.main()
