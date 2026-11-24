"""Draw the daw2score icon with Qt and write gp_export/assets/daw2score.ico (Windows), daw2score.icns (macOS)
and a 256 px png.

A rounded square with a five-line staff and an eighth note. Run once after changing the drawing:
    uv run python packaging/make_icon.py
"""
import os, struct, sys
from PySide6.QtCore import Qt, QRectF, QBuffer, QByteArray, QIODevice, QPointF
from PySide6.QtGui import QGuiApplication, QImage, QPainter, QColor, QPen, QBrush, QPainterPath

OUT = os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "gp_export", "assets")
SIZES = (16, 24, 32, 48, 64, 128, 256)


def draw(n):
    img = QImage(n, n, QImage.Format_ARGB32)
    img.fill(Qt.transparent)
    p = QPainter(img)
    p.setRenderHint(QPainter.Antialiasing)
    p.scale(n / 256.0, n / 256.0)
    p.setPen(Qt.NoPen)
    p.setBrush(QColor("#1f3b5c"))
    p.drawRoundedRect(QRectF(8, 8, 240, 240), 44, 44)
    # staff
    pen = QPen(QColor("#d9e4f0"), 7 if n >= 48 else 10)
    p.setPen(pen)
    for k in range(5):
        y = 70 + k * 29
        p.drawLine(QPointF(34, y), QPointF(222, y))
    # eighth note: head on the 4th line, stem up, flag
    p.setPen(Qt.NoPen)
    p.setBrush(QColor("#ff8a3d"))
    p.save()
    p.translate(112, 157)
    p.rotate(-22)
    p.drawEllipse(QRectF(-30, -21, 60, 42))
    p.restore()
    p.drawRect(QRectF(132, 48, 13, 108))
    flag = QPainterPath(QPointF(132, 48))
    flag.cubicTo(QPointF(150, 70), QPointF(196, 82), QPointF(178, 132))
    flag.cubicTo(QPointF(182, 100), QPointF(160, 88), QPointF(140, 84))
    flag.closeSubpath()
    p.setBrush(QBrush(QColor("#ff8a3d")))
    p.drawPath(flag)
    p.end()
    return img


def png_bytes(img):
    ba = QByteArray()
    buf = QBuffer(ba)
    buf.open(QIODevice.WriteOnly)
    img.save(buf, "PNG")
    return bytes(ba)


def main():
    QGuiApplication(sys.argv)
    os.makedirs(OUT, exist_ok=True)
    pngs = [png_bytes(draw(n)) for n in SIZES]
    # ICO container with PNG entries (supported since Windows Vista)
    head = struct.pack("<HHH", 0, 1, len(SIZES))
    off = 6 + 16 * len(SIZES)
    dirs, data = b"", b""
    for n, d in zip(SIZES, pngs):
        dirs += struct.pack("<BBBBHHII", n % 256, n % 256, 0, 0, 1, 32, len(d), off + len(data))
        data += d
    with open(os.path.join(OUT, "daw2score.ico"), "wb") as f:
        f.write(head + dirs + data)
    with open(os.path.join(OUT, "daw2score.png"), "wb") as f:
        f.write(pngs[-1])
    # ICNS container with PNG entries (type codes per pixel size)
    body = b""
    for code, n in (("icp4", 16), ("icp5", 32), ("icp6", 64), ("ic07", 128), ("ic08", 256), ("ic09", 512),
                    ("ic10", 1024), ("ic11", 32), ("ic12", 64), ("ic13", 256), ("ic14", 512)):
        d = png_bytes(draw(n))
        body += code.encode() + struct.pack(">I", 8 + len(d)) + d
    with open(os.path.join(OUT, "daw2score.icns"), "wb") as f:
        f.write(b"icns" + struct.pack(">I", 8 + len(body)) + body)
    print("written", os.path.normpath(OUT))


if __name__ == "__main__":
    main()
