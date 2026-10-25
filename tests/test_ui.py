"""Native UI regression checks. Android availability is mocked; no runtime is started.

The scenario runs in its own process so it can use QApplication even when the
controller tests have already created a QCoreApplication. All data is temporary.
Set PSYDROID_UI_CAPTURE=1 to save layout screenshots under artifacts/ui-review.
"""
import os
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest


class NativeUiTests(unittest.TestCase):
    def test_isolated_ui_scenario(self):
        result = subprocess.run([sys.executable, str(Path(__file__).resolve()), "--scenario"],
                                cwd=Path(__file__).resolve().parents[1],
                                capture_output=True, text=True, timeout=45)
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
        self.assertIn("UI scenario passed", result.stdout)


def run_scenario():
    from contextlib import ExitStack
    from unittest.mock import patch

    os.environ["QT_QPA_PLATFORM"] = "offscreen"
    with tempfile.TemporaryDirectory(prefix="psydroid-ui-") as temporary:
        os.environ["PSYDROID_HOME"] = temporary
        sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
        from PySide6.QtCore import QAbstractAnimation, QEvent
        from PySide6.QtTest import QTest
        from PySide6.QtWidgets import QApplication, QComboBox, QLabel, QLineEdit, QPushButton

        app = QApplication([])
        app.setQuitOnLastWindowClosed(False)
        from psydroid import emulator, installer, paths, presets, relocate, settings
        from psydroid.ui.controller import Controller
        from psydroid.ui.theme import Fonts, stylesheet
        from psydroid.ui.widgets import Modal, Toggle
        from psydroid.ui.window import MainWindow

        Fonts.load()
        app.setStyleSheet(stylesheet())
        assert paths.HOME == Path(temporary)
        errors = []
        sys.excepthook = lambda kind, value, tb: errors.append(f"{kind.__name__}: {value}")
        capture = os.environ.get("PSYDROID_UI_CAPTURE") == "1"
        artifacts = Path(__file__).resolve().parents[1] / "artifacts" / "ui-review"
        if capture:
            artifacts.mkdir(parents=True, exist_ok=True)

        def flush():
            app.processEvents()
            app.sendPostedEvents(None, QEvent.Type.DeferredDelete)
            app.processEvents()

        def save(window, name):
            QTest.qWait(220)
            flush()
            if capture:
                assert window.grab().save(str(artifacts / f"{name}.png"))

        def immediate(host, work, then=None, failed=None):
            try:
                value = work()
            except Exception as error:
                if failed:
                    failed(error)
                else:
                    raise
            else:
                if then:
                    then(value)

        def clicked(parent, text):
            widget = next(w for w in parent.findChildren(QPushButton) if w.text() == text)
            widget.click()
            flush()

        def active_modal(window):
            return next(m for m in window.findChildren(Modal) if m.isVisible())

        def dispose(window):
            window.update_timer.stop()
            for controller in window.controllers.values():
                controller.timer.stop()
                controller.video_timer.stop()
            app.removeNativeEventFilter(window.hotkeys)
            window.hide()
            window.deleteLater()
            flush()

        packages = [installer.Package("UI test runtime", "https://example.invalid/runtime.zip", 2_000_000_000,
                                      "0" * 40, "test-license", Path("emulator"))]
        # No SDK payload, emulator process, real device, controller polling or network.
        with ExitStack() as patches:
            patches.enter_context(patch.object(MainWindow, "run", immediate))
            patches.enter_context(patch.object(MainWindow, "setup_tray"))
            patches.enter_context(patch.object(MainWindow, "update_hotkeys"))
            patches.enter_context(patch.object(MainWindow, "check_acceleration"))
            patches.enter_context(patch.object(MainWindow, "check_for_updates"))
            patches.enter_context(patch.object(Controller, "poll"))
            patches.enter_context(patch.object(relocate, "clean_up_old_location"))
            patches.enter_context(patch.object(emulator.Emulator, "start", side_effect=AssertionError("No runtime allowed")))
            patches.enter_context(patch.object(installer, "install", side_effect=AssertionError("No SDK installation allowed")))
            patches.enter_context(patch.object(installer.urllib.request, "urlopen", side_effect=AssertionError("No network allowed")))
            availability = patches.enter_context(patch.object(installer, "is_installed", return_value=False))
            resolve = patches.enter_context(patch.object(installer, "resolve",
                                                        return_value=(packages, {"test-license": "Synthetic test license. Not accepted."})))

            setup = MainWindow()
            setup.show()
            flush()
            assert setup.stack.currentWidget() is setup.setup
            assert setup.setup.action.isEnabled()
            assert setup.setup.legal.isVisible()
            assert not setup.sidebar.isVisible()
            save(setup, "setup-fixture")
            setup.resize(980, 660)
            save(setup, "setup-minimum-fixture")
            setup.setup.legal.click()
            flush()
            modal = active_modal(setup)
            clicked(modal, "Close")
            # A repository lookup failure must offer retry, without starting install.
            setup.setup.offline(OSError("simulated offline"))
            assert setup.setup.action.text() == "Try again"
            setup.setup.action.click()
            assert setup.setup.action.text() == "Download and install"
            assert resolve.call_count == 2
            dispose(setup)

            availability.return_value = True
            window = MainWindow()
            window.show()
            flush()
            assert len(window.instances) == 1
            assert window.active().instance.width == 720
            assert window.active().instance.ram == 3072
            # Game controls, macros and profiles are gone; only general pages remain.
            assert set(window.pages) == {"screen", "library", "settings", "instances"}
            assert set(window.nav_buttons) == {"screen", "library", "settings"}
            assert set(settings.load()) == set(settings.DEFAULTS)
            window.overview.click()
            flush()
            assert window.stack.currentWidget() is window.pages["instances"]
            save(window, "instances")

            # Exercise real preference persistence through the displayed toggle.
            motion = next(t for t in window.pages["instances"].findChildren(Toggle)
                          if any(x.text() == "Reduce motion" for x in t.parentWidget().findChildren(QLabel)))
            motion.click()
            assert app.property("reduceMotion") is True
            assert settings.load()["reduce_motion"] is True

            first = window.instances[0]
            window.instance_buttons[first.id].click()
            window.nav_buttons["settings"].click()
            flush()
            assert window.stack.currentWidget() is window.pages["settings"]
            assert window.stack._snapshot is None
            clicked(window.pages["settings"], "Light · 2 GB")
            assert (first.cores, first.ram, first.width) == (2, 2048, 720)
            clicked(window.pages["settings"], "High detail · 4 GB")
            assert (first.ram, first.width, first.height) == (4096, 1080, 1920)
            clicked(window.pages["settings"], "Balanced · 3 GB")
            assert (first.ram, first.width, first.height) == (3072, 720, 1280)
            save(window, "settings")

            # A hardware preset is stored locally and offered when creating an instance.
            clicked(window.pages["settings"], "Save…")
            modal = active_modal(window)
            modal.findChild(QLineEdit).setText("UI preset")
            clicked(modal, "Save")
            assert [preset["name"] for preset in presets.load()] == ["UI preset"]
            assert presets.load()[0]["ram"] == 3072

            window.show_page("instances")
            clicked(window.pages["instances"], "New instance")
            modal = active_modal(window)
            modal.findChild(QLineEdit).setText("UI second device")
            display = next(c for c in modal.findChildren(QComboBox) if c.findData("Phone (light)") >= 0)
            assert display.currentData() == "Phone (light)", "New device should default to the light display"
            clicked(modal, "Create")
            assert len(window.instances) == 2
            assert window.active().instance.name == "UI second device"
            assert window.active().instance.width == 720

            window.overview.click()
            flush()
            # Buttons pass Qt's checked flag to their handler; it must not replace the bound preset or instance.
            clicked(window.pages["instances"], "Delete")
            assert presets.load() == []
            clicked(window.pages["instances"], "Open")
            assert window.current == window.instances[0].id
            assert window.stack.currentWidget() is window.screen

            window.set_pref("reduce_motion", False)
            for page in ("settings", "library", "screen", "instances"):
                window.show_page(page)
                flush()
            QTest.qWait(250)
            assert window.stack._snapshot is None
            assert window.stack._transition.state() == QAbstractAnimation.State.Stopped
            # Resize cancels an in-flight snapshot so it cannot cover resized content.
            window.show_page("instances")
            window.resize(1000, 700)
            flush()
            assert window.stack._snapshot is None
            assert not paths.CRASH_LOG.exists()
            assert not errors, errors
            dispose(window)

        print("UI scenario passed: setup/retry/license view, page navigation, presets, new instance, saved presets, reduced motion, transition cleanup.")
        print("Android runtime availability was mocked; no SDK downloaded or license accepted.")


if __name__ == "__main__":
    if "--scenario" in sys.argv:
        run_scenario()
    else:
        unittest.main()
