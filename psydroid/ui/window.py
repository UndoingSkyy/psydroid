import ctypes
import re
import time
from pathlib import Path

from PySide6.QtCore import QStandardPaths, Qt, QTimer, QUrl
from PySide6.QtGui import QDesktopServices, QIcon
from PySide6.QtWidgets import (QApplication, QComboBox, QFileDialog, QFrame, QHBoxLayout, QLineEdit, QMainWindow,
                               QMenu, QScrollArea, QSystemTrayIcon, QVBoxLayout, QWidget)

from .. import (VERSION, REPOSITORY, browser, claude, emulator, installer, instances, paths, presets, relocate,
                settings, system, updates)
from ..hotkeys import Hotkeys
from . import tasks
from .motion import AnimatedStackWidget
from .controller import Controller
from .host import ScreenActions
from .pages import (InstancesPage, LibraryPage, NoAccelerationPage, Progress, ScreenPage, SettingsPage, SetupPage,
                    app_name, show_text)
from .popout import PopoutWindow
from .theme import COLORS, ICONS
from .widgets import (STATUS_COLORS, InstanceButton, Modal, NavButton, Toast, ToolButton, button, column, confirm,
                      divider, glyph_css, label, row, style_title_bar)

PAGES = {
    "screen": ("screen", "Screen"),
    "library": ("library", "Apps"),
    "settings": ("settings", "Settings"),
    "instances": ("apps", "All instances"),
}

GLOBAL_PAGES = ("instances",)

UPDATE_CHECK_HOURS = 6
STATES = {"on": "Running", "booting": "Starting…", "stopping": "Shutting down…", "crashed": "Stopped unexpectedly"}
BACKUP_FILTER = "PsyDroid backup (*.psydroid)"


def documents():
    return Path(QStandardPaths.writableLocation(QStandardPaths.StandardLocation.DocumentsLocation))


class MainWindow(QMainWindow, ScreenActions):
    def __init__(self, background=False, request=None):
        super().__init__()
        self.setWindowTitle("PsyDroid")
        self.setWindowIcon(QIcon(str(paths.ICON)))
        self.resize(1220, 800)
        self.setMinimumSize(980, 660)
        self.prefs = settings.load()
        QApplication.instance().setProperty("reduceMotion", self.prefs["reduce_motion"])
        if self.prefs["claude_access"]:
            claude.enable()
        self.instances = instances.load()
        self.controllers = {}
        self.instance_buttons = {}
        self.popouts = {}
        self.deleting = set()
        self.current = None
        self.page = "instances"
        self.closing = False
        self.was_maximized = False
        self.background = background
        self.startup_request = request if request and (request["instance"] or request["launch"]) else None
        self.boss_hidden = False
        self.hidden_popouts = []
        self.told_about_tray = False
        self.pending_update = None
        self.offered_update = None
        self.update_timer = QTimer(self, interval=UPDATE_CHECK_HOURS * 3600 * 1000, timeout=self.check_for_updates)
        self.hotkeys = Hotkeys(QApplication.instance())
        tasks.relay.on_error = self.report

        central = QWidget()
        self.setCentralWidget(central)
        root = QHBoxLayout(central)
        root.setContentsMargins(0, 0, 0, 0)
        root.setSpacing(0)
        root.addWidget(self.build_sidebar())
        main = QWidget()
        main.setObjectName("Main")
        main.setAttribute(Qt.WidgetAttribute.WA_StyledBackground)
        main_layout = QVBoxLayout(main)
        main_layout.setContentsMargins(0, 0, 0, 0)
        main_layout.setSpacing(0)
        main_layout.addWidget(self.build_header())
        self.stack = AnimatedStackWidget()
        main_layout.addWidget(self.stack, 1)
        root.addWidget(main, 1)
        self.toaster = Toast(central)

        self.screen = ScreenPage(self)
        self.pages = {
            "screen": self.screen,
            "library": LibraryPage(self),
            "settings": SettingsPage(self),
            "instances": InstancesPage(self),
        }
        self.setup = SetupPage(self)
        self.no_acceleration = NoAccelerationPage(self)
        for page in (*self.pages.values(), self.setup, self.no_acceleration):
            self.stack.addWidget(page)
        self.install_shortcuts()
        self.tray = None
        self.setup_tray()
        self.update_hotkeys()
        self.apply_always_on_top()
        self.run(relocate.clean_up_old_location, failed=lambda _: None)

        if installer.is_installed():
            self.open_instances()
        else:
            self.show_onboarding(self.setup)
            self.setup.begin()

    def showEvent(self, event):
        style_title_bar(self)

    def build_sidebar(self):
        self.sidebar = QWidget()
        self.sidebar.setObjectName("Sidebar")
        self.sidebar.setAttribute(Qt.WidgetAttribute.WA_StyledBackground)
        self.sidebar.setFixedWidth(232)
        layout = QVBoxLayout(self.sidebar)
        layout.setContentsMargins(10, 0, 10, 12)
        layout.setSpacing(2)

        logo = label()
        logo.setPixmap(QIcon(str(paths.ICON)).pixmap(30, 30))
        brand = row(logo, label("PsyDroid", "Brand"), None, spacing=10, margins=(8, 0, 0, 0))
        brand.setFixedHeight(76)
        layout.addWidget(brand)

        add = ToolButton(ICONS["add"], "Create an instance", self.new_instance)
        add.setFixedSize(26, 26)
        layout.addWidget(row(label("Instances", "Section"), None, add, margins=(8, 4, 2, 2)))
        self.instance_list = QVBoxLayout()
        self.instance_list.setContentsMargins(0, 0, 0, 0)
        self.instance_list.setSpacing(2)
        list_holder = QWidget()
        list_holder.setLayout(self.instance_list)
        self.instance_scroll = QScrollArea()
        self.instance_scroll.setWidget(list_holder)
        self.instance_scroll.setWidgetResizable(True)
        self.instance_scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        layout.addWidget(self.instance_scroll)
        self.overview = NavButton(ICONS["apps"], "All instances")
        self.overview.clicked.connect(lambda: self.select(None))
        layout.addWidget(self.overview)

        self.page_section = QWidget()
        pages_layout = QVBoxLayout(self.page_section)
        pages_layout.setContentsMargins(0, 10, 0, 0)
        pages_layout.setSpacing(2)
        pages_layout.addWidget(divider())
        pages_layout.addSpacing(8)
        self.page_title = label("", "Section")
        self.page_title.setContentsMargins(8, 0, 0, 4)
        pages_layout.addWidget(self.page_title)
        self.nav_buttons = {}
        for name in ("screen", "library", "settings"):
            glyph, text = PAGES[name]
            nav = NavButton(ICONS[glyph], text)
            nav.clicked.connect(lambda _=False, page=name: self.show_page(page))
            self.nav_buttons[name] = nav
            pages_layout.addWidget(nav)
        layout.addWidget(self.page_section)
        layout.addStretch(1)

        self.status = label("", "Small")
        self.status.setContentsMargins(8, 0, 0, 6)
        self.power = button("Start Android", self.toggle_power)
        self.power_area = column(self.status, self.power, spacing=0)
        layout.addWidget(self.power_area)
        return self.sidebar

    def build_header(self):
        self.header = QFrame()
        self.header.setObjectName("Header")
        self.header.setFixedHeight(52)
        layout = QHBoxLayout(self.header)
        layout.setContentsMargins(20, 0, 20, 0)
        layout.setSpacing(10)
        self.header_icon = label("")
        self.header_icon.setStyleSheet(f"color: {COLORS['faint']}; {glyph_css(17)}")
        self.header_title = label("", "Title")
        self.header_detail = label("", "Small")
        layout.addWidget(self.header_icon)
        layout.addWidget(self.header_title)
        layout.addWidget(self.header_detail)
        layout.addStretch(1)
        return self.header

    def run(self, work, then=None, failed=None):
        tasks.background(work, then, failed)

    def later(self, callback):
        tasks.on_main_thread(callback)

    def toast(self, text, tone="text"):
        self.toaster.show_message(text, tone)

    def dialog_parent(self):
        return self.centralWidget()

    def report(self, details):
        paths.DATA.mkdir(parents=True, exist_ok=True)
        paths.CRASH_LOG.write_text(details)
        modal = Modal(self.dialog_parent(), "Something went wrong", details.strip().splitlines()[-1])
        modal.action("OK")
        modal.open()

    def active(self):
        return self.controllers.get(self.current)

    def show_onboarding(self, page):
        self.sidebar.hide()
        self.header.hide()
        self.stack.setCurrentWidget(page)

    def open_instances(self):
        self.sidebar.show()
        self.header.show()
        if not self.instances:
            cores, ram = system.suggested_hardware()
            instances.create(self.instances, "Main", cores=cores, ram=ram)
        for instance in self.instances:
            self.add_controller(instance)
        selected = self.prefs["selected"]
        self.select(selected if selected in self.controllers else self.instances[0].id)
        self.check_acceleration()
        self.check_for_updates()
        if REPOSITORY:
            self.update_timer.start()
        for controller in self.controllers.values():
            if controller.instance.autostart:
                controller.start()
        if self.startup_request:
            request, self.startup_request = self.startup_request, None
            self.handle_request(request)

    def setup_finished(self):
        self.open_instances()
        if self.active():
            self.active().start()

    def check_acceleration(self):
        def checked(result):
            ok, reason = result
            if not ok:
                self.show_onboarding(self.no_acceleration)
            elif self.stack.currentWidget() is self.no_acceleration:
                self.sidebar.show()
                self.header.show()
                self.select(self.current)

        self.run(emulator.hardware_acceleration, checked)

    def add_controller(self, instance):
        controller = Controller(instance, self.instances)
        self.controllers[instance.id] = controller
        controller.changed.connect(lambda: self.controller_changed(controller))
        controller.app_changed.connect(lambda: self.app_changed(controller))
        controller.image_missing.connect(lambda: self.get_image(controller))
        controller.notify.connect(self.toast)
        item = InstanceButton(instance)
        item.clicked.connect(lambda: self.select(instance.id))
        self.instance_buttons[instance.id] = item
        self.instance_list.addWidget(item)
        self.fit_instance_list()
        return controller

    def remove_controller(self, controller):
        controller.timer.stop()
        controller.detach()
        del self.controllers[controller.instance.id]
        self.instance_buttons.pop(controller.instance.id).deleteLater()
        self.fit_instance_list()

    def fit_instance_list(self):
        rows = min(len(self.instance_buttons), 6)
        self.instance_scroll.setFixedHeight(rows * 44 + max(rows - 1, 0) * 2)

    def select(self, instance_id):
        if instance_id not in self.controllers:
            instance_id = None
        if instance_id != self.current:
            target = self.controllers.get(instance_id)
            self.screen.phone.show_controller(None if instance_id in self.popouts else target)
        self.current = instance_id
        self.prefs["selected"] = instance_id
        settings.save(self.prefs, "selected")
        self.overview.setChecked(instance_id is None)
        for key, item in self.instance_buttons.items():
            item.setChecked(key == instance_id)
        self.page_section.setVisible(instance_id is not None)
        self.power_area.setVisible(instance_id is not None)
        if instance_id:
            self.page_title.setText(self.active().instance.name)
        self.update_power()
        self.show_page("screen" if instance_id else "instances")

    def update_power(self):
        controller = self.active()
        if not controller:
            return
        state = controller.state
        color = STATUS_COLORS.get(state, COLORS["dim"])
        self.status.setText(f"<span style='color:{color}'>●</span>&nbsp; {STATES.get(state, 'Off')} · "
                            f"{controller.instance.android}")
        off = state in ("off", "crashed")
        self.power.setText("Start Android" if off else "Stop Android")
        self.power.setProperty("kind", None if off else "secondary")
        self.power.setEnabled(state != "stopping")
        self.power.style().unpolish(self.power)
        self.power.style().polish(self.power)

    def show_page(self, name):
        controller = self.active()
        if not controller and name not in GLOBAL_PAGES:
            name = "instances"
        self.page = name
        page = self.pages[name]
        if name in GLOBAL_PAGES:
            page.refresh()
        elif name == "screen":
            page.refresh(controller, controller.instance.id in self.popouts)
        else:
            page.refresh(controller)
        self.stack.setCurrentWidget(page)
        for key, nav in self.nav_buttons.items():
            nav.setChecked(key == name)
        self.overview.setChecked(self.current is None and name == "instances")
        self.update_header()

    def show_screen(self):
        if self.page != "screen":
            self.show_page("screen")

    def update_header(self):
        glyph, title = PAGES[self.page]
        controller = self.active()
        detail = ""
        if self.page == "screen" and controller and controller.on:
            detail = controller.package or ""
        elif self.page == "instances":
            running = sum(1 for c in self.controllers.values() if c.state == "on")
            detail = f"{running} of {len(self.controllers)} running"
        self.header_icon.setText(ICONS[glyph])
        self.header_title.setText(title)
        self.header_detail.setText(detail)

    def controller_changed(self, controller):
        item = self.instance_buttons.get(controller.instance.id)
        if item:
            item.set_state(controller.state)
        popout = self.popouts.get(controller.instance.id)
        if popout:
            popout.refresh()
        if self.page == "instances":
            self.pages["instances"].refresh()
            self.update_header()
        if controller is self.active():
            self.update_power()
            self.update_header()
            if self.page in ("screen", "settings", "library"):
                self.show_page(self.page)

    def app_changed(self, controller):
        if controller is self.active():
            self.update_header()

    def set_pref(self, key, value):
        self.prefs[key] = value
        settings.save(self.prefs, key)
        if key == "reduce_motion":
            QApplication.instance().setProperty("reduceMotion", value)
        if key == "claude_access":
            claude.enable() if value else claude.disable()
        if key == "close_to_tray":
            self.update_tray()
        if key == "always_on_top":
            self.apply_always_on_top()
        self.refresh_tools()
        for popout in self.popouts.values():
            popout.refresh_tools()

    def toggle_power(self):
        controller = self.active()
        if controller:
            if controller.state in ("off", "crashed"):
                controller.start()
            else:
                controller.stop()

    def pop_out(self, controller):
        key = controller.instance.id
        if key in self.popouts:
            self.popouts[key].raise_()
            self.popouts[key].activateWindow()
            return
        if key == self.current:
            self.screen.phone.show_controller(None)
        window = PopoutWindow(self, controller)
        self.popouts[key] = window
        self.apply_always_on_top()
        window.show()
        if key == self.current:
            self.show_page(self.page)
        self.refresh_tools()

    def toggle_popout(self):
        controller = self.active()
        if not controller:
            return
        popout = self.popouts.get(controller.instance.id)
        if popout:
            popout.close()
        else:
            self.pop_out(controller)

    def docked(self, controller):
        self.popouts.pop(controller.instance.id, None)
        if controller is self.active() and not self.closing:
            self.screen.phone.show_controller(controller)
            self.show_page(self.page)

    def set_up_browser(self, controller):
        if not controller.on:
            self.toast("Start Android first")
            return
        progress = Progress(self.dialog_parent(), "Ad-free browser",
                            "Getting Firefox from Mozilla, then opening uBlock Origin in it.")
        last = [0.0]

        def report(stage, done, total):
            now = time.monotonic()
            if stage == "download" and now - last[0] < 0.1 and done < total:
                return
            last[0] = now
            if stage == "download":
                text, fraction = f"Downloading Firefox · {done / 1e6:,.0f} of {total / 1e6:,.0f} MB", done / total
            else:
                text, fraction = "Installing Firefox…", 1.0
            self.later(lambda: progress.update_progress(text, fraction))

        def finished(_):
            progress.done("One more tap", "Firefox is now your browser and it's open on uBlock Origin. Tap "
                          "Add to Firefox, then Add. After that, ads are blocked on every website, YouTube included.")
            if controller is self.active():
                self.show_page("screen")

        self.run(lambda: browser.set_up(controller.emulator, report), finished,
                 lambda error: progress.done("Couldn't set up Firefox", str(error)))

    def check_for_updates(self, manual=False):
        if not REPOSITORY:
            if manual:
                self.toast("PsyDroid is a personal build. Updates are installed manually.")
            return
        if not (manual or self.prefs["check_updates"]):
            return

        def found(release):
            if not updates.newer(release.version):
                if manual:
                    self.toast(f"PsyDroid {VERSION} is the newest version", "good")
                return
            if not manual and self.prefs["skipped_version"] == release.version:
                return
            if self.pending_update and self.pending_update[0].version == release.version:
                return self.offer_update(manual)
            if not (release.installable and system.can_update()):
                self.offer_download_page(release)
            elif self.prefs["auto_update"] and not manual:
                self.fetch_update(release, quiet=True)
            else:
                self.offer_update_download(release)

        def failed(error):
            if manual:
                self.toast("Couldn't reach GitHub. Check your internet connection", "bad")

        self.run(updates.latest, found, failed)

    def notes_for(self, release):
        return f"\n\nWhat's new:\n{release.notes}" if release.notes else ""

    def offer_download_page(self, release):
        # A copy run from source, or a release without a checksum, is downloaded by hand
        modal = Modal(self.dialog_parent(), f"PsyDroid {release.version} is out",
                      f"You have {VERSION}. The new version is on GitHub, ready to download.{self.notes_for(release)}")
        modal.action("Skip this version", lambda: self.set_pref("skipped_version", release.version), kind="secondary")
        modal.action("Download", lambda: QDesktopServices.openUrl(QUrl(release.page)))
        modal.open()

    def offer_update_download(self, release):
        modal = Modal(self.dialog_parent(), f"PsyDroid {release.version} is out",
                      f"You have {VERSION}. PsyDroid can download the new version now, check it against GitHub's "
                      f"checksum, and then ask before restarting to install it.{self.notes_for(release)}")
        modal.action("Skip this version", lambda: self.set_pref("skipped_version", release.version), kind="secondary")
        modal.action("Download", lambda: self.fetch_update(release, quiet=False))
        modal.open()

    def fetch_update(self, release, quiet):
        progress = None if quiet else Progress(self.dialog_parent(), f"PsyDroid {release.version}",
                                               "Downloading the update from GitHub.")
        last = [0.0]

        def report(done, total):
            now = time.monotonic()
            if progress and (now - last[0] >= 0.1 or done >= total):
                last[0] = now
                self.later(lambda: progress.update_progress(f"{done / 1e6:,.0f} of {total / 1e6:,.0f} MB",
                                                            done / max(total, 1)))

        def fetched(file):
            if progress:
                progress.close_modal()
            self.pending_update = (release, file)
            self.offer_update(manual=not quiet)

        def failed(error):
            if progress:
                progress.done("The update didn't download", f"{error}. Try again later, or get it from GitHub.")

        self.run(lambda: updates.download(release, report), fetched, failed)

    def offer_update(self, manual=False):
        # Offered once a session, and only where it will be seen: a copy hidden in the tray shows a notice instead
        release, file = self.pending_update
        if self.offered_update == release.version and not manual:
            return
        if not self.isVisible():
            if self.tray_active() and self.offered_update != release.version:
                self.offered_update = release.version
                self.tray.showMessage(f"PsyDroid {release.version} is ready", "Open PsyDroid to install it.",
                                      QSystemTrayIcon.MessageIcon.Information, 8000)
            return
        self.offered_update = release.version
        modal = Modal(self.dialog_parent(), f"PsyDroid {release.version} is ready",
                      "PsyDroid saves your Androids, installs the update and opens again. Windows may ask for "
                      f"permission first.{self.notes_for(release)}")
        modal.action("Later", kind="secondary")
        modal.action("Restart and update", self.install_update)
        modal.open()

    def install_update(self):
        release, file = self.pending_update
        system.install_update(file)
        self.quit_app()

    def arrange(self):
        running = [controller for controller in self.controllers.values() if controller.on]
        if not running:
            return
        for controller in running:
            self.pop_out(controller)
        area = self.windowHandle().screen().availableGeometry()
        width = area.width() // len(running)
        for index, controller in enumerate(running):
            window = self.popouts[controller.instance.id]
            window.showNormal()
            extra_width = window.frameGeometry().width() - window.width()
            extra_height = window.frameGeometry().height() - window.height()
            window.resize(width - extra_width, area.height() - extra_height)
            window.move(area.left() + index * width, area.top())

    def get_image(self, controller):
        instance = controller.instance

        def resolved(result):
            packages, licenses = result
            size = sum(package.size for package in packages if not package.installed) / 1e9
            modal = Modal(self.dialog_parent(), f"Download {instance.android}",
                          f"{instance.name} runs {instance.android}, which isn't on this PC yet. It's a {size:.1f} GB "
                          "download from Google, and you only need it once.")
            terms = "\n\n".join(licenses.values())
            modal.add(button("Read the license", lambda: show_text(self.dialog_parent(), "License", terms),
                             kind="link"))
            modal.cancel()
            modal.action("Agree and download", lambda: self.download_image(controller, packages))
            modal.open()

        self.run(lambda: installer.resolve(instance.api, tools=False), resolved,
                 lambda _: self.toast("Couldn't reach Google. Check your internet connection", "bad"))

    def download_image(self, controller, packages):
        name = controller.instance.android
        progress = Progress(self.dialog_parent(), f"Getting {name}", "Straight from Google. This happens once.")
        last = [0.0]

        def report(package, done, total, stage):
            now = time.monotonic()
            if now - last[0] < 0.1 and done < total:
                return
            last[0] = now
            verb = {"download": "Downloading", "verify": "Verifying", "unpack": "Unpacking"}[stage]
            amount = f" · {done / 1e6:,.0f} of {total / 1e6:,.0f} MB" if stage == "download" else ""
            self.later(lambda: progress.update_progress(f"{verb} {name}{amount}", done / max(total, 1)))

        def installed(_):
            progress.close_modal()
            controller.start()

        self.run(lambda: installer.install(packages, report), installed,
                 lambda error: progress.done("Download stopped", f"{error}. Start the instance again to resume."))

    def back_up(self, controller):
        instance = controller.instance
        if controller.state not in ("off", "crashed"):
            self.toast(f"Stop {instance.name} before backing it up")
            return
        file, _ = QFileDialog.getSaveFileName(self, "Back up instance",
                                              str(documents() / f"{instance.name} backup.psydroid"), BACKUP_FILTER)
        if not file:
            return
        progress = Progress(self.dialog_parent(), "Backing up", f"Saving {instance.name} to {Path(file).name}.")
        self.run(lambda: instances.backup(instance, file, self.byte_progress(progress)),
                 lambda _: progress.done("Backup saved", f"{instance.name} is saved in {file}. Restore it any time "
                                                         "from All instances."),
                 lambda error: progress.done("Backup failed", str(error)))

    def restore_backup(self):
        file, _ = QFileDialog.getOpenFileName(self, "Restore a backup", str(documents()), BACKUP_FILTER)
        if not file:
            return
        try:
            slot = instances.free_slot(self.instances)
        except RuntimeError as error:
            self.toast(str(error), "bad")
            return
        progress = Progress(self.dialog_parent(), "Restoring", f"Unpacking {Path(file).name}.")

        def restored(instance):
            if any(existing.name == instance.name for existing in self.instances):
                instance.name = f"{instance.name} (restored)"
            instances.adopt(self.instances, instance)
            self.add_controller(instance)
            progress.done("Restored", f"{instance.name} is back, with its apps and data.")
            self.select(instance.id)

        self.run(lambda: instances.restore(file, slot, self.byte_progress(progress)), restored,
                 lambda error: progress.done("Restore failed", str(error)))

    def byte_progress(self, progress):
        last = [0.0]

        def report(done, total):
            now = time.monotonic()
            if now - last[0] >= 0.1 or done >= total:
                last[0] = now
                self.later(lambda: progress.update_progress(f"{done / 1e9:.1f} of {total / 1e9:.1f} GB",
                                                            done / total))

        return report

    def new_instance(self):
        try:
            instances.free_slot(self.instances)
        except RuntimeError as error:
            self.toast(str(error), "bad")
            return
        modal = Modal(self.dialog_parent(), "New instance",
                      "A separate Android with its own apps, accounts and settings.")
        name = QLineEdit(f"Android {len(self.instances) + 1}")
        name.setMaxLength(32)
        display = QComboBox()
        for preset, (width, height, _) in instances.RESOLUTIONS.items():
            display.addItem(f"{preset}  ·  {width}×{height}", preset)
        display.setCurrentIndex(display.findData("Phone (light)"))
        android = QComboBox()
        android.addItem("Android 16 (recommended)", "36")
        android.addItem("Android 11 (for older apps)", "30")
        storage = QComboBox()
        for size in instances.DISK_SIZES:
            storage.addItem(f"{size} GB", size)
        modal.add(label("Name", "Section"))
        modal.add(name)
        saved = presets.load()
        start = QComboBox()
        start.addItem("Standard settings", None)
        for values in saved:
            start.addItem(values["name"], values)
        custom = [label("Display", "Section"), display, label("Android version", "Section"), android,
                  label("Storage", "Section"), storage]
        if saved:
            modal.add(label("Start from", "Section"))
            modal.add(start)

            def pick():
                for widget in custom:
                    widget.setVisible(start.currentData() is None)

            start.currentIndexChanged.connect(pick)
        for widget in custom:
            modal.add(widget)
        modal.cancel()
        modal.action("Create", lambda: self.create_instance(name.text(), display.currentData(), android.currentData(),
                                                            start.currentData(), storage.currentData()))
        modal.open()
        name.setFocus()
        name.selectAll()

    def create_instance(self, name, display="Phone (light)", api=installer.DEFAULT_API, preset=None,
                        disk=instances.DISK_SIZES[0]):
        if preset:
            hardware = {key: preset[key] for key in presets.FIELDS if key in preset}
            if hardware.get("api") not in installer.ANDROID_VERSIONS:
                hardware.pop("api", None)
        else:
            width, height, density = instances.RESOLUTIONS[display]
            cores, ram = system.suggested_hardware()
            hardware = {"width": width, "height": height, "density": density, "api": api, "disk": disk,
                        "cores": cores, "ram": ram}
        instance = instances.create(self.instances, name.strip() or "Android", **hardware)
        self.add_controller(instance)
        self.select(instance.id)
        self.toast(f"Created {instance.name}. Its first start takes a little longer.", "good")

    def clone_instance(self, controller):
        if controller.state not in ("off", "crashed"):
            self.toast(f"Stop {controller.instance.name} before cloning it")
            return
        try:
            slot = instances.free_slot(self.instances)
        except RuntimeError as error:
            self.toast(str(error), "bad")
            return
        self.toast(f"Cloning {controller.instance.name}…")

        def cloned(copy):
            instances.adopt(self.instances, copy)
            self.add_controller(copy)
            self.pages["instances"].refresh()
            self.toast(f"Created {copy.name}", "good")

        self.run(lambda: instances.clone(controller.instance, slot), cloned)

    def delete_instance(self, controller):
        instance = controller.instance

        def delete():
            # Stopping can take a while, and a second click used to start a second delete
            if instance.id in self.deleting:
                return
            self.deleting.add(instance.id)

            def stopped():
                instances.forget(self.instances, instance)
                self.remove_controller(controller)
                self.select(None)
                self.run(lambda: instances.erase(instance), erased, erased)

            def erased(_=None):
                self.deleting.discard(instance.id)
                self.toast(f"Deleted {instance.name}", "good")

            popout = self.popouts.get(instance.id)
            if popout:
                popout.close()
            self.toast(f"Deleting {instance.name}…")
            controller.stop(then=stopped)

        confirm(self.dialog_parent(), f"Delete {instance.name}?", "This removes the instance with all of its apps "
                "and data. This can't be undone.", "Delete", delete, danger=True)

    def rename(self, controller, text):
        text = text.strip()
        if not text or text == controller.instance.name:
            return
        controller.instance.name = text
        controller.save()
        self.instance_buttons[controller.instance.id].update()
        self.page_title.setText(text)
        popout = self.popouts.get(controller.instance.id)
        if popout:
            popout.refresh()

    def set_hardware(self, controller, **changes):
        for key, value in changes.items():
            setattr(controller.instance, key, value)
        controller.save()
        if controller.state in ("on", "booting"):
            self.toast("Saved. Restart Android to use it")

    def set_resolution(self, controller, preset):
        width, height, density = instances.RESOLUTIONS[preset]
        self.set_hardware(controller, width=width, height=height, density=density)

    def pick_display(self, controller, value):
        if value == "custom":
            self.custom_resolution(controller)
        elif value != "Custom":
            self.set_resolution(controller, value)

    def custom_resolution(self, controller):
        instance = controller.instance
        modal = Modal(self.dialog_parent(), "Custom display",
                      "Any size from 320 to 3840 pixels. Density is how large things look: 160 is small, 420 is a "
                      "phone and 640 is huge.")
        fields = {key: QLineEdit(str(getattr(instance, key))) for key in instances.SIZE_LIMITS}
        modal.add(label("Width and height, in pixels", "Section"))
        modal.add(row(fields["width"], fields["height"]))
        modal.add(label("Density, in dpi", "Section"))
        modal.add(fields["density"])

        def apply():
            try:
                values = {key: int(field.text()) for key, field in fields.items()}
            except ValueError:
                self.toast("Use whole numbers", "bad")
                return False
            for key, (low, high) in instances.SIZE_LIMITS.items():
                if not low <= values[key] <= high:
                    self.toast(f"{key.capitalize()} has to be between {low} and {high}", "bad")
                    return False
            self.set_hardware(controller, **values)

        modal.cancel()
        modal.action("Use this display", apply)
        modal.closed.connect(self.refresh_settings)
        modal.open()

    def refresh_settings(self):
        if self.page == "settings" and self.active():
            self.show_page("settings")

    def set_storage(self, controller, size):
        instance = controller.instance
        if size == instance.disk:
            return

        def erase():
            instance.disk = size
            instance.wipe_next = True
            controller.save()
            if controller.state in ("on", "booting"):
                controller.stop(then=controller.start)
            else:
                self.toast(f"{instance.name} gets {size} GB the next time it starts")

        modal = confirm(self.dialog_parent(), "Change storage?", f"{instance.name} gets {size} GB, which erases every "
                        "app and all data on it. This can't be undone.", "Erase and change", erase, danger=True)
        modal.closed.connect(self.refresh_settings)

    def ask(self, title, text, default, action, submit):
        modal = Modal(self.dialog_parent(), title, text)
        field = QLineEdit(default)
        field.setMaxLength(presets.NAME_LIMIT)
        modal.add(field)
        modal.cancel()
        confirm_button = modal.action(action, lambda: submit(field.text()))
        field.returnPressed.connect(confirm_button.click)
        modal.open()
        field.setFocus()
        field.selectAll()

    def save_preset(self, controller):
        instance = controller.instance

        def submit(text):
            try:
                name = presets.save(text, instance)
            except (OSError, ValueError) as error:
                self.toast(str(error), "bad")
                return False
            self.toast(f"Saved the preset {name}", "good")

        self.ask("Save as a preset", "Name it, and it shows up when you create an instance.", instance.name, "Save",
                 submit)

    def delete_preset(self, name):
        presets.delete(name)
        self.pages["instances"].refresh()

    def stop_all(self):
        for controller in self.controllers.values():
            controller.stop()

    def start_all(self):
        for controller in self.controllers.values():
            controller.start()

    def uninstall_app(self, controller, package):
        def uninstall():
            def finished(ok):
                controller.apps = None
                if self.page == "library":
                    self.show_page("library")
                text = f"Removed {app_name(package)}" if ok else f"Couldn't remove {package}"
                self.toast(text, "good" if ok else "bad")

            self.run(lambda: controller.emulator.uninstall(package), finished)

        confirm(self.dialog_parent(), f"Uninstall {app_name(package)}?", "Its data on this instance goes with it.",
                "Uninstall", uninstall, danger=True)

    def shortcut_for(self, controller, package=None):
        instance = controller.instance
        name = app_name(package) if package else instance.name
        title = re.sub(r'[\\/:*?"<>|]', "", f"{name} on {instance.name}" if package else f"{name} (PsyDroid)").strip()
        arguments = ["--instance", instance.id] + (["--launch", package] if package else [])
        desktop = Path(QStandardPaths.writableLocation(QStandardPaths.StandardLocation.DesktopLocation))
        text = f"Opens {name} in PsyDroid" if package else f"Starts {instance.name} in PsyDroid"
        self.run(lambda: system.shortcut(desktop / f"{title}.lnk", arguments, text),
                 lambda _: self.toast(f"Put {title} on your desktop", "good"),
                 lambda error: self.toast(f"Couldn't make the shortcut: {error}", "bad"))

    def find_instance(self, wanted):
        wanted = (wanted or "").lower()
        return next((controller for controller in self.controllers.values()
                     if wanted in (controller.instance.id.lower(), controller.instance.name.lower())), None)

    def handle_request(self, request):
        # A second PsyDroid, or a desktop shortcut, asks this one to start an instance or open an app
        quiet = request.get("background")
        if not quiet:
            self.bring_back()
        controller = self.find_instance(request.get("instance")) or (self.active() if request.get("launch") else None)
        if request.get("instance") and not controller:
            self.toast(f"There's no instance called {request['instance']}", "bad")
        if not controller:
            return
        if request.get("launch"):
            controller.launch(request["launch"])
        elif request.get("instance") and controller.state in ("off", "crashed"):
            controller.start()
        if not quiet:
            self.select(controller.instance.id)

    def setup_tray(self):
        if not QSystemTrayIcon.isSystemTrayAvailable():
            return
        self.tray = QSystemTrayIcon(QIcon(str(paths.ICON)), self)
        self.tray.setToolTip("PsyDroid")
        self.tray_menu = QMenu()
        self.tray_menu.aboutToShow.connect(self.fill_tray_menu)
        self.tray.setContextMenu(self.tray_menu)
        self.tray.activated.connect(lambda reason: reason in (QSystemTrayIcon.ActivationReason.Trigger,
                                                              QSystemTrayIcon.ActivationReason.DoubleClick)
                                    and self.bring_back())
        self.update_tray()

    def tray_active(self):
        return bool(self.tray and self.tray.isVisible())

    def update_tray(self):
        if self.tray:
            self.tray.setVisible(self.prefs["close_to_tray"] or self.background)

    def fill_tray_menu(self):
        menu = self.tray_menu
        menu.clear()
        menu.addAction("Open PsyDroid", self.bring_back)
        menu.addSeparator()
        for controller in self.controllers.values():
            verb = "Stop" if controller.state not in ("off", "crashed") else "Start"
            menu.addAction(f"{verb} {controller.instance.name}", lambda c=controller: self.toggle_controller(c))
        menu.addSeparator()
        menu.addAction("Quit PsyDroid", self.quit_app)

    def toggle_controller(self, controller):
        if controller.state in ("off", "crashed"):
            controller.start()
        else:
            controller.stop()

    def bring_back(self):
        self.boss_hidden = False
        if self.isMinimized():
            self.showNormal()
        self.show()
        for popout in self.hidden_popouts:
            popout.show()
        self.hidden_popouts = []
        ctypes.windll.user32.SetForegroundWindow(int(self.winId()))
        self.raise_()
        if self.pending_update:
            QTimer.singleShot(600, self.offer_update)

    def hide_to_tray(self):
        self.hidden_popouts = [popout for popout in self.popouts.values() if popout.isVisible()]
        for popout in self.hidden_popouts:
            popout.hide()
        self.hide()

    def update_hotkeys(self, announce=False):
        wanted = {}
        if self.prefs["boss_key"]:
            wanted[self.prefs["boss_key"]] = self.boss
        refused = self.hotkeys.set(wanted)
        if refused and announce:
            self.toast(f"Windows won't give PsyDroid {', '.join(refused)}. Use Ctrl, Alt, Shift or Win with a key, "
                       "and one no other program has taken", "bad")

    def set_boss_key(self, text):
        self.set_pref("boss_key", text)
        self.update_hotkeys(announce=True)

    def boss(self):
        quiet = not self.boss_hidden
        for controller in self.controllers.values():
            controller.hush(quiet)
        if quiet:
            self.boss_hidden = True
            self.hide_to_tray()
        else:
            self.bring_back()

    def apply_always_on_top(self):
        on = self.prefs["always_on_top"]
        for window in (self, *self.popouts.values()):
            if bool(window.windowFlags() & Qt.WindowType.WindowStaysOnTopHint) != on:
                shown = window.isVisible()
                window.setWindowFlag(Qt.WindowType.WindowStaysOnTopHint, on)
                if shown:
                    window.show()

    def set_start_with_windows(self, enabled):
        try:
            system.start_with_windows(enabled)
        except OSError as error:
            self.toast(f"Windows wouldn't allow that: {error}", "bad")
            return
        self.toast("PsyDroid will open in the tray when you sign in" if enabled else "PsyDroid no longer starts "
                   "with Windows")

    def move_files(self):
        if any(controller.state not in ("off", "crashed") for controller in self.controllers.values()):
            self.toast("Stop every Android first", "bad")
            return
        folder = QFileDialog.getExistingDirectory(self, "Choose where PsyDroid keeps its files",
                                                  str(paths.HOME.parent))
        if not folder:
            return
        target = relocate.target_for(folder)
        confirm(self.dialog_parent(), "Move PsyDroid's files?",
                f"Everything moves to {target}. That can take a few minutes, and PsyDroid restarts when it's done. "
                "The old copy is deleted after the restart.", "Move", lambda: self.start_move(folder))

    def start_move(self, folder):
        progress = Progress(self.dialog_parent(), "Moving files", "Copying Android's files to the new place.")

        def moved(target):
            progress.close_modal()
            modal = Modal(self.dialog_parent(), "Files moved", f"PsyDroid now keeps its files in {target}. It has "
                          "to restart to use them.", dismissable=False)
            modal.action("Restart PsyDroid", self.restart)
            modal.open()

        self.run(lambda: relocate.move(folder, self.byte_progress(progress)), moved,
                 lambda error: progress.done("Couldn't move the files", str(error)))

    def restart(self):
        system.restart()
        self.quit_app()


    def toggle_fullscreen(self):
        chrome = (self.sidebar, self.header, self.screen.tools)
        if self.isFullScreen():
            for part in chrome:
                part.show()
            if self.was_maximized:
                self.showMaximized()
            else:
                self.showNormal()
            return
        if not self.active():
            return
        self.show_page("screen")
        self.was_maximized = self.isMaximized()
        for part in chrome:
            part.hide()
        self.showFullScreen()
        self.toast("Press F11 to leave full screen")

    def closeEvent(self, event):
        event.ignore()
        if self.prefs["close_to_tray"] and self.tray_active() and not self.closing:
            self.hide_to_tray()
            if not self.told_about_tray:
                self.told_about_tray = True
                self.tray.showMessage("PsyDroid is still running", "Open it again from the tray icon. Quit from "
                                      "there to shut Android down.", QSystemTrayIcon.MessageIcon.Information, 5000)
            return
        self.quit_app()

    def quit_app(self):
        if self.closing:
            return
        self.closing = True
        self.hotkeys.set({})
        if self.tray:
            self.tray.hide()
        for popout in list(self.popouts.values()):
            popout.close()
        running = [c for c in self.controllers.values() if c.state not in ("off", "crashed")]
        if not running:
            QApplication.quit()
            return
        self.hide()
        remaining = [len(running)]

        def stopped():
            remaining[0] -= 1
            if remaining[0] == 0:
                QApplication.quit()

        for controller in running:
            controller.stop(then=stopped)
        QTimer.singleShot(90_000, QApplication.quit)
