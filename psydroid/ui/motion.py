"""Short, event-driven transitions with no idle render loop or persistent effects."""

from PySide6.QtCore import QEasingCurve, QRectF, Qt, QVariantAnimation
from PySide6.QtGui import QPainter, QPixmap
from PySide6.QtWidgets import QApplication, QStackedWidget, QWidget


def reduced_motion():
    app = QApplication.instance()
    return bool(app and app.property("reduceMotion"))


class _PageSnapshot(QWidget):
    """A single outgoing-page capture; live video never gets an opacity effect."""

    def __init__(self, parent, pixmap):
        super().__init__(parent)
        self.pixmap = pixmap
        self.progress = 0.0
        self.setAttribute(Qt.WidgetAttribute.WA_TransparentForMouseEvents)
        self.setAttribute(Qt.WidgetAttribute.WA_NoSystemBackground)
        self.setGeometry(parent.rect())

    def paintEvent(self, event):
        painter = QPainter(self)
        painter.setOpacity(1.0 - self.progress)
        painter.translate(-8.0 * self.progress, 0)
        painter.drawPixmap(QRectF(self.rect()), self.pixmap, QRectF(self.pixmap.rect()))


class AnimatedStackWidget(QStackedWidget):
    """Drop-in QStackedWidget with a 180 ms dissolve/slide on page changes.

    The snapshot is released at completion. Set QApplication's ``reduceMotion``
    property to true to disable all PsyDroid transitions, or a page's
    ``skipTransition`` property to true to avoid capturing that page.
    """

    def __init__(self, parent=None):
        super().__init__(parent)
        self._snapshot = None
        self._transition = QVariantAnimation(self)
        self._transition.setDuration(180)
        self._transition.setStartValue(0.0)
        self._transition.setEndValue(1.0)
        self._transition.setEasingCurve(QEasingCurve.Type.OutCubic)
        self._transition.valueChanged.connect(self._advance)
        self._transition.finished.connect(self._clear)

    def setCurrentWidget(self, widget):
        index = self.indexOf(widget)
        if index >= 0:
            self.setCurrentIndex(index)

    def setCurrentIndex(self, index):
        if index == self.currentIndex() or index < 0 or index >= self.count():
            return
        self._clear()
        old, target = self.currentWidget(), self.widget(index)
        animate = (self.isVisible() and old is not None and not reduced_motion()
                   and not old.property("skipTransition")
                   and not target.property("skipTransition"))
        captured = old.grab() if animate else None
        super().setCurrentIndex(index)
        if captured is not None and not captured.isNull():
            self._snapshot = _PageSnapshot(self, captured)
            self._snapshot.show()
            self._snapshot.raise_()
            self._transition.start()

    def _advance(self, progress):
        if self._snapshot is not None:
            self._snapshot.progress = progress
            self._snapshot.update()

    def _clear(self):
        self._transition.stop()
        if self._snapshot is not None:
            self._snapshot.hide()
            self._snapshot.pixmap = QPixmap()
            self._snapshot.deleteLater()
            self._snapshot = None

    def resizeEvent(self, event):
        self._clear()
        super().resizeEvent(event)

    def hideEvent(self, event):
        self._clear()
        super().hideEvent(event)
