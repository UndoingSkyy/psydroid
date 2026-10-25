import re
import subprocess
import time

from PySide6.QtCore import QRectF, Qt, QTimer
from PySide6.QtGui import QColor, QIcon, QKeySequence, QPainter, QPainterPath
from PySide6.QtWidgets import (QComboBox, QFrame, QHBoxLayout, QKeySequenceEdit, QLineEdit, QMenu, QPlainTextEdit,
                               QScrollArea, QStackedWidget, QToolButton, QVBoxLayout, QWidget)

from .. import VERSION, REPOSITORY, installer, instances, paths, presets, system
from .phone import PhoneView
from .theme import COLORS, ICONS
from .tools import ToolRail
from .widgets import Modal, Toggle, avatar, button, column, confirm, divider, glyph_css, label, recolor, row

STATES = {"on": "Running", "booting": "Starting…", "stopping": "Shutting down…", "crashed": "Stopped unexpectedly"}


class Bar(QWidget):
    def __init__(self, height=6, busy=False):
        super().__init__()
        self.setFixedHeight(height)
        self.fraction = 0.0
        self.busy = busy
        self.timer = QTimer(self, interval=16, timeout=self.update)
        if busy:
            self.timer.start()

    def set_fraction(self, fraction):
        self.fraction = min(max(fraction, 0.0), 1.0)
        self.update()

    def paintEvent(self, event):
        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)
        radius = 2
        painter.setPen(Qt.PenStyle.NoPen)
        painter.setBrush(QColor(COLORS["raised"]))
        painter.drawRoundedRect(QRectF(self.rect()), radius, radius)
        painter.setBrush(QColor(COLORS["accent"]))
        if self.busy:
            clip = QPainterPath()
            clip.addRoundedRect(QRectF(self.rect()), radius, radius)
            painter.setClipPath(clip)
            cycle = (time.monotonic() % 1.4) / 1.4
            width = self.width() * 0.35
            painter.drawRoundedRect(QRectF(-width + cycle * (self.width() + width), 0, width, self.height()),
                                    radius, radius)
        elif self.fraction > 0:
            painter.drawRoundedRect(QRectF(0, 0, max(self.height(), self.width() * self.fraction), self.height()),
                                    radius, radius)


class Progress(Modal):
    def __init__(self, parent, title, text):
        super().__init__(parent, title, text)
        self.status = self.add(label("", "Small"))
        self.bar = self.add(Bar(8))
        self.finished = False
        self.open()

    def update_progress(self, text, fraction):
        self.status.setText(text)
        self.bar.set_fraction(fraction)

    def done(self, title, text):
        self.finished = True
        self.close_modal()
        modal = Modal(self.parentWidget(), title, text)
        modal.action("OK")
        modal.open()

    def keyPressEvent(self, event):
        if self.finished:
            super().keyPressEvent(event)

    def mousePressEvent(self, event):
        if self.finished:
            super().mousePressEvent(event)


class Page(QScrollArea):
    def __init__(self, width=720):
        super().__init__()
        self.setWidgetResizable(True)
        holder = QWidget()
        holder.setObjectName("Page")
        outer = QHBoxLayout(holder)
        outer.setContentsMargins(24, 24, 24, 32)
        self.content = QWidget()
        self.content.setMaximumWidth(width)
        self.body = QVBoxLayout(self.content)
        self.body.setContentsMargins(0, 0, 0, 0)
        self.body.setSpacing(16)
        self.body.setAlignment(Qt.AlignmentFlag.AlignTop)
        outer.addWidget(self.content, 1)
        outer.addStretch(0)
        self.setWidget(holder)

    def clear(self):
        while self.body.count():
            item = self.body.takeAt(0)
            if item.widget():
                item.widget().deleteLater()

    def add(self, *widgets):
        for widget in widgets:
            self.body.addWidget(widget)

    def intro(self, title, text):
        self.add(label(title, "Heading"), label(text, "Muted", wrap=True))


def card(*widgets, spacing=12):
    frame = QFrame()
    frame.setObjectName("Card")
    layout = QVBoxLayout(frame)
    layout.setContentsMargins(16, 16, 16, 16)
    layout.setSpacing(spacing)
    for widget in widgets:
        layout.addWidget(widget)
    return frame


def setting(title, text, control):
    words = column(label(title, "Subheading"), label(text, "Small", wrap=True), spacing=2)
    line = QWidget()
    layout = QHBoxLayout(line)
    layout.setContentsMargins(0, 0, 0, 0)
    layout.setSpacing(24)
    layout.addWidget(words, 1)
    layout.addWidget(control, 0, Qt.AlignmentFlag.AlignVCenter)
    return line


def pair(title, text):
    line = QWidget()
    layout = QHBoxLayout(line)
    layout.setContentsMargins(0, 0, 0, 0)
    layout.setSpacing(16)
    heading = label(title, "Subheading")
    heading.setFixedWidth(130)
    layout.addWidget(heading, 0, Qt.AlignmentFlag.AlignTop)
    layout.addWidget(label(text, "Muted", wrap=True), 1)
    return line


def choice(options, current):
    combo = QComboBox()
    for text, value in options:
        combo.addItem(text, value)
    combo.setCurrentIndex(max(0, combo.findData(current)))
    combo.setMinimumWidth(220)
    combo.setCursor(Qt.CursorShape.PointingHandCursor)
    return combo


def show_text(parent, title, text):
    modal = Modal(parent, title, width=640)
    page = QPlainTextEdit(text)
    page.setReadOnly(True)
    page.setMinimumHeight(380)
    page.setStyleSheet(f"background: {COLORS['input']}; border: 1px solid {COLORS['line']}; border-radius: 6px; "
                       "padding: 8px;")
    modal.add(page)
    modal.action("Close")
    return modal.open()


def menu_button(actions):
    more = QToolButton()
    more.setText(ICONS["more"])
    more.setFixedSize(32, 32)
    more.setCursor(Qt.CursorShape.PointingHandCursor)
    more.setPopupMode(QToolButton.ToolButtonPopupMode.InstantPopup)
    more.setToolTip("More actions")
    more.setStyleSheet(f"""
        QToolButton {{ border: 1px solid {COLORS["control"]}; border-radius: 6px; background: {COLORS["raised"]};
                       color: {COLORS["text"]}; {glyph_css(14)} }}
        QToolButton:hover {{ background: {COLORS["hover"]}; }}
        QToolButton::menu-indicator {{ image: none; width: 0; }}
    """)
    menu = QMenu(more)
    for text, action in actions:
        if text is None:
            menu.addSeparator()
        else:
            menu.addAction(text, action)
    more.setMenu(menu)
    return more


class StateView(QWidget):
    def __init__(self, host):
        super().__init__()
        self.host = host
        layout = QVBoxLayout(self)
        layout.setAlignment(Qt.AlignmentFlag.AlignCenter)
        layout.setSpacing(10)
        self.badge = avatar(ICONS["screen"], COLORS["main"], 64, glyph=True)
        self.title = label("", "Heading")
        self.text = label("", "Muted", wrap=True)
        self.text.setFixedWidth(420)
        self.text.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.bar = Bar(busy=True)
        self.bar.setFixedWidth(280)
        self.actions = QHBoxLayout()
        self.actions.setSpacing(10)
        for widget in (self.badge, self.title, self.text, self.bar):
            layout.addWidget(widget, alignment=Qt.AlignmentFlag.AlignHCenter)
        layout.addSpacing(8)
        layout.addLayout(self.actions)

    def show_state(self, controller, popped=False):
        while self.actions.count():
            self.actions.takeAt(0).widget().deleteLater()
        state = controller.state
        if popped:
            title, text = "Open in its own window", f"{controller.instance.name} is showing in a separate window."
        elif state == "booting":
            title, text = "Starting Android…", "This takes a few seconds, or up to a minute on the very first start."
        elif state == "stopping":
            title, text = "Shutting down…", "Android is saving its state so it resumes quickly next time."
        elif state == "crashed":
            title, text = "Android stopped unexpectedly", "The log may say why. Starting again usually fixes it."
        elif state == "on":
            title, text = "Connecting…", "Android is running. Connecting to its screen."
        else:
            title, text = "Android is off", "Start it to use your apps. Drop APK files here to install them."
        self.title.setText(title)
        self.text.setText(text)
        busy = state in ("booting", "stopping", "on") and not popped
        self.bar.setVisible(busy)
        if busy:
            self.bar.timer.start()
        else:
            self.bar.timer.stop()
        recolor(self.badge, COLORS["main"], COLORS["red"] if state == "crashed" and not popped else COLORS["faint"])
        if popped:
            self.actions.addWidget(button("Bring it back", self.host.toggle_popout, size="large"))
        elif state in ("off", "crashed"):
            self.actions.addWidget(button("Start Android", controller.start, size="large"))
        if state == "crashed" and not popped:
            self.actions.addWidget(button("Open log", controller.open_log, kind="secondary", size="large"))


class ScreenPage(QWidget):
    def __init__(self, host):
        super().__init__()
        self.host = host
        self.stack = QStackedWidget()
        self.state = StateView(host)
        self.phone = PhoneView(host)
        self.stack.addWidget(self.state)
        self.stack.addWidget(self.phone)
        self.tools = ToolRail(host)
        layout = QHBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(0)
        self.holder = QWidget()
        self.holder.setObjectName("Page")
        inner = QVBoxLayout(self.holder)
        inner.setContentsMargins(16, 16, 16, 16)
        inner.addWidget(self.stack)
        layout.addWidget(self.holder, 1)
        layout.addWidget(self.tools)

    def refresh(self, controller, popped=False):
        if controller.on and not popped:
            if self.stack.currentWidget() is not self.phone:
                self.stack.setCurrentWidget(self.phone)
                self.phone.setFocus()
        else:
            self.stack.setCurrentWidget(self.state)
            self.state.show_state(controller, popped)
        self.tools.refresh(controller, self.host.prefs)


class SettingsPage(Page):
    def __init__(self, host):
        super().__init__()
        self.host = host

    def refresh(self, controller):
        self.clear()
        host = self.host
        instance = controller.instance
        self.intro("Settings", f"{instance.name} runs {instance.android}. Hardware changes apply the next time it "
                               "starts.")

        def apply_preset(cores, ram, width, height, density):
            host.set_hardware(controller, cores=min(cores, system.host_cores()),
                              ram=min(ram, max(2048, system.host_memory() - 4096)),
                              width=width, height=height, density=density)
            host.refresh_settings()
            host.toast("Saved. It applies the next time Android starts.", "good")

        self.add(card(label("Quick setup", "Subheading"),
                      label("Light uses 2 GB of memory. Balanced is the default. High detail uses 4 GB and a "
                            "1080p display.", "Small", wrap=True),
                      row(button("Light · 2 GB", lambda: apply_preset(2, 2048, 720, 1280, 320), kind="secondary"),
                          button("Balanced · 3 GB", lambda: apply_preset(4, 3072, 720, 1280, 320), kind="secondary"),
                          button("High detail · 4 GB", lambda: apply_preset(4, 4096, 1080, 1920, 420),
                                 kind="secondary"),
                          None)))

        name = QLineEdit(instance.name)
        name.setMaxLength(32)
        name.editingFinished.connect(lambda: host.rename(controller, name.text()))
        self.add(card(label("Name", "Subheading"), name))

        cores = choice([(f"{count} cores", count) for count in system.core_options(instance.cores)], instance.cores)
        memory = choice([(f"{size // 1024} GB" if size % 1024 == 0 else f"{size / 1024:.1f} GB", size)
                         for size in system.memory_options(instance.ram)], instance.ram)
        shown = [(f"{preset}  ·  {width}×{height}", preset)
                 for preset, (width, height, _) in instances.RESOLUTIONS.items()]
        if instance.resolution == "Custom":
            shown.append((f"Custom  ·  {instance.width}×{instance.height}  ·  {instance.density} dpi", "Custom"))
        display = choice([*shown, ("Custom…", "custom")], instance.resolution)
        graphics = choice([(name, key) for key, name in instances.GPU_MODES.items()], instance.gpu_mode)
        disk = choice([(f"{size} GB", size) for size in sorted({*instances.DISK_SIZES, instance.disk})], instance.disk)
        cores.currentIndexChanged.connect(lambda: host.set_hardware(controller, cores=cores.currentData()))
        memory.currentIndexChanged.connect(lambda: host.set_hardware(controller, ram=memory.currentData()))
        display.currentIndexChanged.connect(lambda: host.pick_display(controller, display.currentData()))
        graphics.currentIndexChanged.connect(lambda: host.set_hardware(controller, gpu=graphics.currentData()))
        disk.currentIndexChanged.connect(lambda: host.set_storage(controller, disk.currentData()))
        restart = []
        if controller.state in ("on", "booting"):
            restart = [divider(), row(label("Restart Android to use new hardware settings.", "Muted"), None,
                                      button("Restart", controller.restart, kind="secondary"))]
        self.add(card(label("Hardware", "Subheading"),
                      setting("Processor", "More cores help heavier apps.", cores), divider(),
                      setting("Memory", "3 GB suits most apps.", memory), divider(),
                      setting("Display", "Phone suits most apps. Tablet runs in landscape.", display), divider(),
                      setting("Graphics", "Your graphics card keeps the screen smooth. If Android crashes while "
                                          "starting, try Software, which is much slower.", graphics), divider(),
                      setting("Storage", "Room for apps and their data. Changing it erases this instance's apps "
                                         "and data.", disk), *restart))

        muted = Toggle(instance.muted)
        muted.toggled.connect(controller.set_muted)
        autostart = Toggle(instance.autostart)
        autostart.toggled.connect(controller.set_autostart)
        webcam = Toggle(instance.camera)
        webcam.toggled.connect(lambda on: host.set_hardware(controller, camera=on))
        ads = Toggle(instance.block_ads)
        ads.toggled.connect(controller.set_block_ads)
        browser = button("Set up", lambda: host.set_up_browser(controller), kind="secondary")
        self.add(card(label("Apps and web", "Subheading"),
                      setting("Block ads", "Blocks ad networks inside apps. It can't remove ads that come from the "
                                           "same servers as the content, like YouTube's.", ads), divider(),
                      setting("Ad-free browser", "Installs Firefox and uBlock Origin, which blocks ads on every "
                                                 "website, YouTube included.", browser), divider(),
                      setting("Webcam", "Lets Android apps use your PC's webcam as their camera. Applies the "
                                        "next time Android starts.", webcam), divider(),
                      setting("Mute", "Silences this instance's sound.", muted), divider(),
                      setting("Start with PsyDroid", "Starts this instance whenever PsyDroid opens, including "
                                                       "when Windows starts it.", autostart)))

        preset = button("Save…", lambda: host.save_preset(controller), kind="secondary")
        backup = button("Back up", lambda: host.back_up(controller), kind="secondary")
        self.add(card(label("Keep", "Subheading"),
                      setting("Save as a preset", "Keeps this instance's processor, memory, display and extras, so "
                                                  "a new instance can start the same way.", preset), divider(),
                      setting("Back up this instance", "Saves its apps, data and settings to one file you can "
                                                       "restore from All instances.", backup)))

        reset = button("Factory reset", lambda: confirm(
            host.dialog_parent(), "Factory reset", f"Erase every app and all data on {instance.name}? "
            "This can't be undone.", "Erase everything", controller.factory_reset, danger=True), kind="danger")
        delete = button("Delete instance", lambda: host.delete_instance(controller), kind="danger")
        self.add(card(label("Reset or delete", "Subheading"),
                      setting("Factory reset", "Erases all apps and data, like a new phone.", reset), divider(),
                      setting("Delete instance", "Removes this instance and everything in it.", delete)))


class InstancesPage(Page):
    def __init__(self, host):
        super().__init__(width=820)
        self.host = host

    def refresh(self):
        self.clear()
        host = self.host
        self.intro("Instances", "Each instance is a separate Android with its own apps, accounts and settings.")
        running = any(c.state not in ("off", "crashed") for c in host.controllers.values())
        stop_all = button("Stop all", host.stop_all, kind="secondary")
        stop_all.setEnabled(running)
        start_all = button("Start all", host.start_all, kind="secondary")
        start_all.setEnabled(any(c.state in ("off", "crashed") for c in host.controllers.values()))
        tile = button("Side by side", host.arrange, kind="secondary")
        tile.setEnabled(any(c.on for c in host.controllers.values()))
        self.add(row(button("New instance", host.new_instance),
                     button("Restore a backup", host.restore_backup, kind="secondary"), tile, start_all, stop_all,
                     None))
        rows = []
        for controller in host.controllers.values():
            instance = controller.instance
            color = COLORS["green"] if controller.state == "on" else COLORS["faint"]
            words = column(label(instance.name, "Subheading"),
                           label(f"<span style='color:{color}'>●</span>  {STATES.get(controller.state, 'Off')}  ·  "
                                 f"{instance.android}  ·  {instance.resolution}  ·  {instance.cores} cores  ·  "
                                 f"{instance.ram // 1024} GB", "Small"), spacing=2)
            if controller.state in ("off", "crashed"):
                power = button("Start", controller.start, kind="secondary")
            else:
                power = button("Stop", controller.stop, kind="secondary")
                power.setEnabled(controller.state != "stopping")
            more = menu_button([
                ("Open in its own window", lambda c=controller: host.pop_out(c)),
                ("Create desktop shortcut", lambda c=controller: host.shortcut_for(c)),
                ("Clone", lambda c=controller: host.clone_instance(c)),
                ("Back up", lambda c=controller: host.back_up(c)),
                (None, None),
                ("Delete", lambda c=controller: host.delete_instance(c)),
            ])
            show = button("Open", lambda _=False, c=controller: host.select(c.instance.id), kind="secondary")
            rows.append(row(words, None, power, show, more, spacing=8))
        if rows:
            lines = [label(f"Your instances ({len(rows)})", "Subheading")]
            for number, line in enumerate(rows):
                if number:
                    lines.append(divider())
                lines.append(line)
            self.add(card(*lines, spacing=12))
        self.add(self.presets_card())

        updates = Toggle(host.prefs["check_updates"] and bool(REPOSITORY))
        updates.setEnabled(bool(REPOSITORY))
        updates.toggled.connect(lambda on: host.set_pref("check_updates", on))
        automatic = Toggle(host.prefs["auto_update"] and system.can_update())
        automatic.setEnabled(system.can_update())
        automatic.toggled.connect(lambda on: host.set_pref("auto_update", on))
        check_now = button("Check now", host.check_now, kind="secondary")
        check_now.setEnabled(bool(REPOSITORY))
        motion = Toggle(host.prefs["reduce_motion"])
        motion.toggled.connect(lambda on: host.set_pref("reduce_motion", on))
        access = Toggle(host.prefs["claude_access"])
        access.toggled.connect(lambda on: host.set_pref("claude_access", on))
        self.add(card(label("Everywhere", "Subheading"),
                      setting("Reduce motion", "Skip page transitions and animations. Android's own animations "
                                               "are set inside Android Settings.", motion), divider(),
                      setting("Check for updates", f"PsyDroid {VERSION} is a personal build. Updates are manual "
                                                   "until a release feed is configured.", updates), divider(),
                      setting("Download updates automatically", "Fetches a new version in the background and checks "
                                                                "it against GitHub's checksum. PsyDroid then asks "
                                                                "before restarting to install it." +
                              ("" if system.can_update() else " Only the installed app can do this."),
                              automatic), divider(),
                      setting("Look for an update now", "Checks GitHub right away.", check_now), divider(),
                      setting("Let Claude Code control Android", "Lets Claude Code on this PC tap, type, take "
                                                                  "screenshots and install apps on your running "
                                                                  "instances to test them, through a helper "
                                                                  "script in your PsyDroid folder.", access)))

        tray = Toggle(host.prefs["close_to_tray"])
        tray.toggled.connect(lambda on: host.set_pref("close_to_tray", on))
        windows = Toggle(system.starts_with_windows())
        windows.toggled.connect(host.set_start_with_windows)
        boss = QKeySequenceEdit(QKeySequence(host.prefs["boss_key"]))
        boss.setMaximumSequenceLength(1)
        boss.setClearButtonEnabled(True)
        boss.setFixedWidth(170)
        boss.editingFinished.connect(lambda: host.set_boss_key(boss.keySequence().toString()))
        move = button("Move…", host.move_files, kind="secondary")
        self.add(card(label("This PC", "Subheading"),
                      setting("Keep running in the tray", "Closing the window hides PsyDroid and leaves Android "
                                                          "running. Quit from the tray icon.", tray), divider(),
                      setting("Start with Windows", "Opens PsyDroid in the tray when you sign in, and starts the "
                                                    "instances set to start with PsyDroid.", windows), divider(),
                      setting("Hide shortcut", "A shortcut that works in any program. It hides every PsyDroid window "
                                               "and mutes Android, and brings them back when you press it again. It "
                                               "needs Ctrl, Alt, Shift or Win with a key.", boss), divider(),
                      setting("Where PsyDroid keeps its files", f"{paths.HOME}\nAndroid images, instances and "
                                                                  "settings. Move them to another drive if this one "
                                                                  "is running out of space.", move)))

        shortcuts = [("F11", "Full screen"), ("Ctrl+Shift+S", "Screenshot"), ("Ctrl+Shift+R", "Record the screen"),
                     ("Ctrl+Shift+O", "Rotate"), ("Ctrl+Shift+W", "Open in its own window"),
                     ("Ctrl+scroll", "Zoom in or out"), ("Esc", "Back in Android")]
        lines = [row(label(keys, "Subheading"), label(what, "Muted"), None, spacing=16) for keys, what in shortcuts]
        for line in lines:
            line.layout().itemAt(0).widget().setFixedWidth(140)
        self.add(card(label("Keyboard shortcuts", "Subheading"), *lines, spacing=6))

    def presets_card(self):
        saved = presets.load()
        lines = [label("Presets", "Subheading")]
        if not saved:
            lines.append(label("None yet. In an instance's Settings, choose Save as a preset. Presets show up when "
                               "you create a new instance.", "Muted", wrap=True))
        for number, values in enumerate(saved):
            if number:
                lines.append(divider())
            example = instances.from_dict(values, id="preset", slot=0)
            words = column(label(values["name"], "Subheading"),
                           label(f"{example.android}  ·  {example.resolution}  ·  {example.cores} cores  ·  "
                                 f"{example.ram // 1024} GB", "Small"), spacing=2)
            lines.append(row(words, None, button("Delete", lambda _=False, n=values["name"]: self.host.delete_preset(n),
                                                 kind="secondary")))
        return card(*lines)


GENERIC_WORDS = {"android", "app", "apps", "game", "games", "mobile", "gp", "google", "free", "lite", "prod", "release"}


def app_name(package):
    # Android keeps an app's real name inside its package, so this guesses one from the package's own name
    parts = [part for part in package.split(".") if part]
    fallback = parts[-1] if parts else package
    word = next((part for part in reversed(parts) if part.lower() not in GENERIC_WORDS), fallback)
    return re.sub(r"[_-]+", " ", word).strip().title() or package


class LibraryPage(Page):
    def __init__(self, host):
        super().__init__(width=820)
        self.host = host

    def refresh(self, controller):
        self.clear()
        host = self.host
        self.intro("Apps", f"What's installed on {controller.instance.name}. Open an app, uninstall it, or put a "
                           "shortcut to it on your desktop.")
        if not controller.on:
            self.add(card(label("Start Android to see what's installed.", "Muted"),
                          row(button("Start Android", controller.start), None)))
            return
        if controller.apps is None:
            self.add(card(label("Looking at what's installed…", "Muted")))
            host.run(controller.emulator.apps, lambda found: self.loaded(controller, found), lambda _: None)
            return
        refresh = button("Refresh", lambda: self.reload(controller), kind="secondary")
        self.add(row(refresh, None))
        rows = []
        for package in controller.apps:
            words = column(label(app_name(package), "Subheading"), label(package, "Small"), spacing=2)
            more = menu_button([
                ("Create desktop shortcut", lambda p=package: host.shortcut_for(controller, p)),
                (None, None),
                ("Uninstall", lambda p=package: host.uninstall_app(controller, p)),
            ])
            rows.append(row(words, None, button("Open", lambda _=False, p=package: self.open_app(controller, p),
                                                kind="secondary"), more, spacing=8))
        if rows:
            lines = [label(f"Installed ({len(rows)})", "Subheading")]
            for number, line in enumerate(rows):
                if number:
                    lines.append(divider())
                lines.append(line)
            self.add(card(*lines, spacing=10))
        else:
            self.add(card(label("Nothing installed yet. Get apps from Google Play, or drop an APK file on the screen.",
                                "Muted", wrap=True)))

    def loaded(self, controller, found):
        controller.apps = found
        if self.host.page == "library" and self.host.active() is controller:
            self.refresh(controller)

    def reload(self, controller):
        controller.apps = None
        self.refresh(controller)

    def open_app(self, controller, package):
        controller.launch(package)
        self.host.show_page("screen")


class SetupPage(QWidget):
    def __init__(self, host):
        super().__init__()
        self.setObjectName("Page")
        self.setAttribute(Qt.WidgetAttribute.WA_StyledBackground)
        self.host = host
        self.packages = []
        self.licenses = {}
        layout = QVBoxLayout(self)
        layout.setContentsMargins(32, 32, 32, 32)
        layout.setAlignment(Qt.AlignmentFlag.AlignCenter)
        box = QFrame()
        box.setObjectName("Card")
        box.setFixedWidth(480)
        layout.addWidget(box)
        inner = QVBoxLayout(box)
        inner.setContentsMargins(28, 28, 28, 24)
        inner.setSpacing(10)
        logo = label()
        logo.setPixmap(QIcon(str(paths.ICON)).pixmap(32, 32))
        inner.addWidget(row(logo, label("PsyDroid", "Title"), None, spacing=10))
        inner.addSpacing(8)
        self.title = label("Install Android", "Heading")
        self.text = label(f"PsyDroid runs Android apps on this PC with Google's Android Emulator and "
                          f"{installer.IMAGE_NAME} with Google Play. Both download once, straight from Google.",
                          "Muted", wrap=True)
        self.detail = label("Checking download size…", "Small", wrap=True)
        self.bar = Bar(6)
        self.bar.hide()
        self.action = button("Download and install", self.install)
        self.action.setEnabled(False)
        self.legal = button("Read the Android SDK License", self.show_license, kind="link")
        self.legal.hide()
        for widget in (self.title, self.text, self.detail, self.bar):
            inner.addWidget(widget)
        inner.addSpacing(8)
        inner.addWidget(row(self.action, self.legal, None, spacing=4))
        inner.addSpacing(8)
        inner.addWidget(divider())
        inner.addSpacing(4)
        inner.addWidget(label("Needs Windows Hypervisor Platform and about 4 GB of free disk space. Each instance "
                              "starts with a 720p display and 3 GB of memory, which you can change later.",
                              "Small", wrap=True))

    def begin(self, error=None):
        self.bar.hide()
        self.action.setText("Download and install")
        self.action.setEnabled(False)
        self.detail.setText(error or "Checking download size…")
        self.detail.setStyleSheet(f"color: {COLORS['red']};" if error else "")
        self.host.run(installer.resolve, self.ready, self.offline)

    def ready(self, result):
        self.packages, self.licenses = result
        missing = [package for package in self.packages if not package.installed]
        size = sum(package.size for package in missing) / 1e9
        if self.detail.styleSheet() == "":
            self.detail.setText(f"{size:.1f} GB download. Continuing means you accept the Android SDK License.")
        self.action.setEnabled(True)
        self.legal.show()

    def offline(self, error):
        self.detail.setText("Couldn't reach Google. Check your internet connection.")
        self.detail.setStyleSheet(f"color: {COLORS['red']};")
        self.action.setText("Try again")
        self.action.setEnabled(True)
        self.action.clicked.disconnect()
        self.action.clicked.connect(self.retry)

    def retry(self):
        self.action.clicked.disconnect()
        self.action.clicked.connect(self.install)
        self.begin()

    def show_license(self):
        show_text(self.host.dialog_parent(), "Android SDK License", "\n\n".join(self.licenses.values()))

    def install(self):
        missing = [package for package in self.packages if not package.installed]
        self.title.setText("Installing Android")
        self.action.hide()
        self.legal.hide()
        self.bar.show()
        self.detail.setStyleSheet("")
        last = [0.0]

        def progress(package, done, total, stage):
            now = time.monotonic()
            if now - last[0] >= 0.1 or done >= total:
                last[0] = now
                self.host.later(lambda: self.show_progress(missing.index(package), len(missing), package.label,
                                                           done, total, stage))

        self.host.run(lambda: installer.install(missing, progress), self.installed, self.failed)

    def show_progress(self, index, count, name, done, total, stage):
        verb = {"download": "Downloading", "verify": "Verifying", "unpack": "Unpacking"}[stage]
        amount = f"  ·  {done / 1e6:,.0f} of {total / 1e6:,.0f} MB" if stage == "download" else ""
        self.text.setText(f"{verb} {name}…")
        self.detail.setText(f"Part {index + 1} of {count}{amount}")
        self.bar.set_fraction(done / max(total, 1))

    def installed(self, _):
        self.host.setup_finished()

    def failed(self, error):
        self.title.setText("Install Android")
        self.action.show()
        self.begin(f"Setup stopped: {error}")


class NoAccelerationPage(QWidget):
    def __init__(self, host):
        super().__init__()
        self.setObjectName("Page")
        self.setAttribute(Qt.WidgetAttribute.WA_StyledBackground)
        layout = QVBoxLayout(self)
        layout.setAlignment(Qt.AlignmentFlag.AlignCenter)
        box = card(label("Turn on virtualization", "Heading"),
                   label("Android needs Windows Hypervisor Platform. Turn it on in Windows Features, restart your "
                         "PC, then open PsyDroid again.", "Muted", wrap=True),
                   row(button("Open Windows Features", lambda: subprocess.Popen(["OptionalFeatures.exe"])),
                       button("Check again", host.check_acceleration, kind="secondary"), None))
        box.setFixedWidth(480)
        layout.addWidget(box)
