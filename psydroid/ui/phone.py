import queue
import threading
import time

from PySide6.QtCore import QPointF, QRectF, Qt, QTimer, Signal
from PySide6.QtGui import QColor, QImage, QPainter, QPainterPath
from PySide6.QtWidgets import QWidget

from ..bridge import KEYDOWN, KEYUP
from .theme import COLORS

MOUSE_TOUCH = 0
SCROLL_TOUCH = 9
SCROLL_STEP = 0.12
SCROLL_LIMIT = 0.6
PINCH_TOUCHES = (7, 8)

ANDROID_KEYS = {
    Qt.Key.Key_Return: "Enter", Qt.Key.Key_Enter: "Enter", Qt.Key.Key_Backspace: "Backspace",
    Qt.Key.Key_Tab: "Tab", Qt.Key.Key_Escape: "Escape", Qt.Key.Key_Delete: "Delete",
    Qt.Key.Key_Left: "ArrowLeft", Qt.Key.Key_Right: "ArrowRight", Qt.Key.Key_Up: "ArrowUp",
    Qt.Key.Key_Down: "ArrowDown", Qt.Key.Key_Home: "Home", Qt.Key.Key_End: "End",
    Qt.Key.Key_PageUp: "PageUp", Qt.Key.Key_PageDown: "PageDown", Qt.Key.Key_Shift: "Shift",
    Qt.Key.Key_Control: "Control", Qt.Key.Key_Alt: "Alt", Qt.Key.Key_Space: " ",
}


class Scroller:
    def __init__(self, phone):
        self.phone = phone
        self.lock = threading.Lock()
        self.origin = (0.5, 0.5)
        self.pending = (0.0, 0.0)
        self.busy = False

    def push(self, u, v, du, dv):
        with self.lock:
            self.origin = (u, v)
            self.pending = (self.pending[0] + du, self.pending[1] + dv)
            if self.busy:
                return
            self.busy = True
        threading.Thread(target=self.drain, daemon=True).start()

    def drain(self):
        while True:
            with self.lock:
                du, dv = self.pending
                if not du and not dv:
                    self.busy = False
                    return
                take = (max(-SCROLL_LIMIT, min(SCROLL_LIMIT, du)), max(-SCROLL_LIMIT, min(SCROLL_LIMIT, dv)))
                self.pending = (du - take[0], dv - take[1])
                u, v = self.origin
            self.drag(u, v, *take)

    def drag(self, u, v, du, dv):
        u = min(max(u, 0.05 - min(du, 0)), 0.95 - max(du, 0))
        v = min(max(v, 0.05 - min(dv, 0)), 0.95 - max(dv, 0))
        steps = 8
        self.touch(u, v, True)
        for step in range(1, steps + 1):
            time.sleep(0.01)
            self.touch(u + du * step / steps, v + dv * step / steps, True)
        time.sleep(0.05)
        self.touch(u + du, v + dv, False)

    def touch(self, u, v, down):
        bridge = self.phone.bridge
        if bridge and self.phone.controller:
            bridge.touch((SCROLL_TOUCH, *self.phone.device_point(u, v), down))


class Pincher:
    """Ctrl and the scroll wheel pinch in and out, for maps, photos and web pages"""

    def __init__(self, phone):
        self.phone = phone
        self.queue = queue.Queue()
        threading.Thread(target=self.run, daemon=True).start()

    def run(self):
        while True:
            for touches, pause in self.queue.get():
                bridge = self.phone.bridge
                if bridge and self.phone.controller:
                    for identifier, u, v, down in touches:
                        bridge.touch((identifier, *self.phone.device_point(u, v), down))
                time.sleep(pause)

    def pinch(self, u, v, closer):
        steps = 10
        spread = [0.18 - 0.14 * step / steps if closer else 0.04 + 0.14 * step / steps for step in range(steps + 1)]
        path = [([(PINCH_TOUCHES[0], u - gap, v, True), (PINCH_TOUCHES[1], u + gap, v, True)], 0.012)
                for gap in spread]
        path.append(([(PINCH_TOUCHES[0], u - spread[-1], v, False), (PINCH_TOUCHES[1], u + spread[-1], v, False)], 0))
        self.queue.put(path)


class PhoneView(QWidget):
    frame_ready = Signal()

    def __init__(self, host):
        super().__init__()
        self.host = host
        self.controller = None
        self.bridge = None
        self.image = None
        self.buffer = None
        self.rotation = 0
        self.latest = None
        self.scheduled = False
        self.touching = False
        self.held = {}

        self.setFocusPolicy(Qt.FocusPolicy.StrongFocus)
        self.setAcceptDrops(True)
        self.setAttribute(Qt.WidgetAttribute.WA_OpaquePaintEvent)
        self.frame_ready.connect(self.take_frame, Qt.ConnectionType.QueuedConnection)
        self.restream_timer = QTimer(self, singleShot=True, interval=120, timeout=self.restream)
        self.pincher = Pincher(self)
        self.scroller = Scroller(self)

    def show_controller(self, controller):
        if self.controller:
            self.controller.attached.disconnect(self.restream)
        self.stop_stream()
        self.release_input()
        self.controller = controller
        self.image = None
        if controller:
            controller.attached.connect(self.restream)
        self.restream()

    def restream(self):
        self.stop_stream()
        if not (self.controller and self.controller.bridge and self.isVisible()):
            return
        self.bridge = self.controller.bridge
        ratio = self.devicePixelRatioF()
        self.bridge.watch(max(1, int(self.width() * ratio)), max(1, int(self.height() * ratio)), self.receive)

    def stop_stream(self):
        if self.bridge:
            self.bridge.unwatch()
        self.bridge = None

    def receive(self, data, width, height, rotation, depth):
        self.latest = (data, width, height, rotation, depth)
        if not self.scheduled:
            self.scheduled = True
            self.frame_ready.emit()

    def take_frame(self):
        self.scheduled = False
        if not self.latest:
            return
        self.buffer, width, height, self.rotation, depth = self.latest
        pixel = QImage.Format.Format_RGBX8888 if depth == 4 else QImage.Format.Format_RGB888
        self.image = QImage(self.buffer, width, height, width * depth, pixel)
        self.image.setDevicePixelRatio(self.devicePixelRatioF())
        self.update()

    def frame_rect(self):
        if not self.image:
            return QRectF(self.rect())
        size = self.image.deviceIndependentSize()
        return QRectF((self.width() - size.width()) / 2, (self.height() - size.height()) / 2,
                      size.width(), size.height())

    def showEvent(self, event):
        self.restream()

    def hideEvent(self, event):
        self.stop_stream()
        self.release_input()

    def resizeEvent(self, event):
        self.restream_timer.start()

    def paintEvent(self, event):
        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)
        painter.setRenderHint(QPainter.RenderHint.SmoothPixmapTransform)
        painter.fillRect(self.rect(), QColor(COLORS["main"]))
        if not self.image:
            return
        rect = self.frame_rect()
        clip = QPainterPath()
        clip.addRoundedRect(rect, 6, 6)
        painter.save()
        painter.setClipPath(clip)
        painter.drawImage(rect, self.image)
        painter.restore()
        if self.controller and self.controller.recording_video:
            painter.setPen(Qt.PenStyle.NoPen)
            painter.setBrush(QColor(COLORS["red"]))
            painter.drawEllipse(QPointF(rect.right() - 18, rect.top() + 18), 6, 6)

    def normalized(self, position):
        rect = self.frame_rect()
        u = (position.x() - rect.left()) / rect.width()
        v = (position.y() - rect.top()) / rect.height()
        return min(max(u, 0.0), 1.0), min(max(v, 0.0), 1.0)

    def inside(self, position):
        return self.image is not None and self.frame_rect().contains(position)

    def device_point(self, u, v):
        width, height = self.controller.instance.width, self.controller.instance.height
        if self.rotation == 1:
            return (1 - v) * width, u * height
        if self.rotation == 2:
            return (1 - u) * width, (1 - v) * height
        if self.rotation == 3:
            return v * width, (1 - u) * height
        return u * width, v * height

    def send_touch(self, u, v, down):
        if self.bridge:
            self.bridge.touch((MOUSE_TOUCH, *self.device_point(u, v), down))

    def mousePressEvent(self, event):
        self.setFocus()
        if self.bridge and self.image is None:
            self.controller.wake()
            return
        if not self.bridge or not self.inside(event.position()):
            return
        if event.button() == Qt.MouseButton.LeftButton:
            self.touching = True
            self.send_touch(*self.normalized(event.position()), True)
        elif event.button() == Qt.MouseButton.RightButton:
            self.bridge.key("GoBack")
        elif event.button() == Qt.MouseButton.MiddleButton:
            self.bridge.key("GoHome")

    def mouseMoveEvent(self, event):
        if self.touching and self.bridge:
            self.send_touch(*self.normalized(event.position()), True)

    def mouseReleaseEvent(self, event):
        if self.touching and event.button() == Qt.MouseButton.LeftButton and self.bridge:
            self.touching = False
            self.send_touch(*self.normalized(event.position()), False)

    def wheelEvent(self, event):
        if not self.bridge:
            return
        if event.modifiers() & Qt.KeyboardModifier.ControlModifier and event.angleDelta().y():
            self.pincher.pinch(*self.normalized(event.position()), closer=event.angleDelta().y() < 0)
            return
        frame = self.frame_rect()
        du = event.angleDelta().x() / 120 * SCROLL_STEP * frame.height() / frame.width()
        dv = event.angleDelta().y() / 120 * SCROLL_STEP
        self.scroller.push(*self.normalized(event.position()), du, dv)

    def keyPressEvent(self, event):
        if not self.bridge:
            return
        key = ANDROID_KEYS.get(event.key()) or (event.text() if event.text().isprintable() else "")
        if key:
            self.held[event.key()] = key
            self.bridge.key(key, KEYDOWN)

    def keyReleaseEvent(self, event):
        if not self.bridge or event.isAutoRepeat():
            return
        key = self.held.pop(event.key(), None)
        if key:
            self.bridge.key(key, KEYUP)

    def focusNextPrevChild(self, forward):
        return False

    def focusOutEvent(self, event):
        self.release_input()

    def release_input(self):
        if not self.bridge:
            self.held.clear()
            return
        for key in self.held.values():
            self.bridge.key(key, KEYUP)
        self.held.clear()
        if self.touching:
            self.touching = False
            self.bridge.touch((MOUSE_TOUCH, 0, 0, False))

    def dragEnterEvent(self, event):
        if event.mimeData().hasUrls():
            event.acceptProposedAction()

    def dropEvent(self, event):
        files = [url.toLocalFile() for url in event.mimeData().urls() if url.isLocalFile()]
        if files and self.controller:
            self.controller.open_files(files)
