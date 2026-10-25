"""Draw the original PsyDroid monogram as a Windows multi-size icon."""
from pathlib import Path
from PySide6.QtCore import QRectF, Qt
from PySide6.QtGui import QColor, QIcon, QImage, QImageWriter, QPainter, QPen
from PySide6.QtWidgets import QApplication
import struct

app = QApplication([])
root = Path(__file__).resolve().parents[1]
images = []
for size in (16, 24, 32, 48, 64, 128, 256):
    image = QImage(size, size, QImage.Format.Format_ARGB32)
    image.fill(Qt.GlobalColor.transparent)
    p = QPainter(image)
    p.setRenderHint(QPainter.RenderHint.Antialiasing)
    p.scale(size / 64, size / 64)
    p.setPen(Qt.PenStyle.NoPen)
    p.setBrush(QColor('#1d1d1d'))
    p.drawRoundedRect(QRectF(1, 1, 62, 62), 12, 12)
    p.setPen(QPen(QColor('#f2f2f2'), 5, Qt.PenStyle.SolidLine, Qt.PenCapStyle.RoundCap, Qt.PenJoinStyle.RoundJoin))
    p.drawLine(23, 45, 23, 19)
    p.drawLine(23, 19, 35, 19)
    p.drawArc(QRectF(28, 19, 16, 16), -90 * 16, 180 * 16)
    p.drawLine(23, 35, 35, 35)
    p.setPen(Qt.PenStyle.NoPen)
    p.setBrush(QColor('#5b9cf0'))
    p.drawEllipse(QRectF(39, 42, 6, 6))
    p.end()
    from PySide6.QtCore import QBuffer, QIODevice
    buffer = QBuffer()
    buffer.open(QIODevice.OpenModeFlag.WriteOnly)
    image.save(buffer, 'PNG')
    images.append((size, bytes(buffer.data())))
offset = 6 + 16 * len(images)
header = struct.pack('<HHH', 0, 1, len(images))
data = b''
for size, png in images:
    header += struct.pack('<BBBBHHII', size % 256, size % 256, 0, 0, 1, 32, len(png), offset)
    offset += len(png)
    data += png
(root / 'assets' / 'psydroid.ico').write_bytes(header + data)
