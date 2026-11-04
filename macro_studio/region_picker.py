"""Transparent drag-to-select overlay; the user's drag supplies physical pixels."""
from PySide6.QtCore import Qt, Signal, QRectF
from PySide6.QtGui import QColor, QPainter, QPen, QFont
from PySide6.QtWidgets import QWidget, QApplication

def physical_region(start, end):
    left, top = min(start[0], end[0]), min(start[1], end[1])
    return {"left": int(left), "top": int(top),
            "width": int(abs(end[0] - start[0])), "height": int(abs(end[1] - start[1]))}

class RegionPicker(QWidget):
    selected = Signal(dict)
    cancelled = Signal()

    def __init__(self, cursor_position=None, message=None):
        super().__init__(None, Qt.FramelessWindowHint | Qt.WindowStaysOnTopHint | Qt.Tool)
        if cursor_position is None:
            from pynput.mouse import Controller
            self.mouse = Controller()
            cursor_position = lambda: self.mouse.position
        self.cursor_position = cursor_position
        self.start = self.end = self.physical_start = None
        self.resolved = False
        self.message = message or "Encadrez le panneau à faire défiler · Échap pour annuler"
        self.setAttribute(Qt.WA_TranslucentBackground)
        self.setGeometry(QApplication.primaryScreen().virtualGeometry())
        self.setCursor(Qt.CrossCursor)
        self.setMouseTracking(True)
        self.setFocusPolicy(Qt.StrongFocus)

    def paintEvent(self, event):
        painter = QPainter(self)
        painter.fillRect(self.rect(), QColor(0, 0, 0, 65))
        painter.setFont(QFont("Segoe UI", 14))
        painter.setPen(QColor("white"))
        # Repeat instructions on each screen, including negative-origin monitors.
        for screen in QApplication.screens():
            rect = screen.geometry().translated(-self.geometry().topLeft())
            box = QRectF(rect.x() + 30, rect.y() + 30, max(200, rect.width() - 60), 65)
            painter.fillRect(box, QColor(18, 26, 40, 230))
            painter.drawText(box.adjusted(15, 8, -15, -8), Qt.AlignCenter | Qt.TextWordWrap, self.message)
        if self.start is not None and self.end is not None:
            rect = QRectF(self.start, self.end).normalized()
            painter.setPen(QPen(QColor("#75c4ff"), 3))
            painter.fillRect(rect, QColor(70, 150, 255, 45))
            painter.drawRect(rect)

    def mousePressEvent(self, event):
        if event.button() == Qt.LeftButton:
            self.start = self.end = event.position()
            self.physical_start = self.cursor_position()
            self.update()

    def mouseMoveEvent(self, event):
        if self.start is not None:
            self.end = event.position()
            self.update()

    def mouseReleaseEvent(self, event):
        if event.button() != Qt.LeftButton or self.physical_start is None:
            return
        region = physical_region(self.physical_start, self.cursor_position())
        if region["width"] < 20 or region["height"] < 20:
            self.message = "Zone trop petite : encadrez un panneau d’au moins 20 × 20 pixels. Échap pour annuler."
            self.start = self.end = self.physical_start = None
            self.update()
            return
        self.hide()
        self.resolved = True
        self.selected.emit(region)
        self.close()

    def keyPressEvent(self, event):
        if event.key() in (Qt.Key_Escape, Qt.Key_F8):
            self.hide()
            self.resolved = True
            self.cancelled.emit()
            self.close()
        else:
            super().keyPressEvent(event)

    def closeEvent(self, event):
        if not self.resolved:
            self.resolved = True
            self.cancelled.emit()
        event.accept()
