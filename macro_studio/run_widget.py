"""Small non-activating execution dashboard with per-module active timers."""
import time
from pathlib import Path
from PySide6.QtCore import Qt, QTimer, Signal, QSize, QEvent
from PySide6.QtGui import QIcon
from PySide6.QtWidgets import QWidget, QVBoxLayout, QHBoxLayout, QLabel, QPushButton, QProgressBar, QLayout, QApplication

def duration(seconds):
    seconds = max(0, int(seconds))
    return f"{seconds // 3600:02}:{seconds // 60 % 60:02}:{seconds % 60:02}"

class RunWidget(QWidget):
    pause_requested = Signal()
    resume_requested = Signal()
    stop_requested = Signal()

    def __init__(self):
        super().__init__(None, Qt.Tool | Qt.FramelessWindowHint | Qt.WindowStaysOnTopHint | Qt.WindowDoesNotAcceptFocus)
        self.setAttribute(Qt.WA_ShowWithoutActivating)
        self.setWindowTitle("Macro Studio · Exécution")
        self.setFixedWidth(355)
        self.drag_title = None
        self.compact = False
        self._drag_origin = None
        self._dragging = False
        self.running, self.paused, self.control = False, False, None
        self.module_id = None
        self.workflow_cycle = (1, 1)
        self.condition_message = ''
        self.workflow_started = self.module_started = None
        self.last_times = (0, 0)
        shell = QVBoxLayout(self)
        shell.setContentsMargins(0, 0, 0, 0)
        shell.setSizeConstraint(QLayout.SetNoConstraint)
        self.restore_button = QPushButton()
        self.restore_button.setIcon(QIcon(str(Path(__file__).with_name('icons') / 'app.svg')))
        self.restore_button.setIconSize(QSize(28, 28))
        self.restore_button.setFixedSize(44, 44)
        self.restore_button.setToolTip("Ouvrir le suivi du workflow")
        self.restore_button.setAccessibleName("Ouvrir le suivi du workflow")
        self.restore_button.setFocusPolicy(Qt.NoFocus)
        self.restore_button.installEventFilter(self)
        self.restore_button.clicked.connect(lambda: self.set_compact(False))
        shell.addWidget(self.restore_button)
        self.restore_button.hide()
        self.content = QWidget()
        shell.addWidget(self.content)
        layout = QVBoxLayout(self.content)
        header = QHBoxLayout()
        self.drag_title = QLabel("Suivi du workflow")
        self.drag_title.setToolTip("Glisser pour déplacer le suivi")
        self.drag_title.installEventFilter(self)
        header.addWidget(self.drag_title)
        header.addStretch()
        self.collapse_button = QPushButton("Réduire")
        self.collapse_button.setToolTip("Réduire en icône sans interrompre le workflow")
        self.collapse_button.setFocusPolicy(Qt.NoFocus)
        self.collapse_button.clicked.connect(lambda: self.set_compact(True))
        header.addWidget(self.collapse_button)
        layout.addLayout(header)
        self.state = QLabel("Prêt")
        self.state.setWordWrap(True)
        layout.addWidget(self.state)
        self.sequence = QLabel("Préparation…")
        self.sequence.setWordWrap(True)
        layout.addWidget(self.sequence)
        self.details = QLabel()
        layout.addWidget(self.details)
        self.timers = QLabel("Workflow 00:00:00\nSéquence 00:00:00")
        self.timers.setStyleSheet("font-size:18px; padding:6px")
        layout.addWidget(self.timers)
        self.progress = QProgressBar()
        layout.addWidget(self.progress)
        row = QHBoxLayout()
        self.pause_button = QPushButton("Pause")
        self.pause_button.clicked.connect(self.toggle_pause)
        row.addWidget(self.pause_button)
        self.stop_button = QPushButton("Arrêter · F8")
        self.stop_button.clicked.connect(self.stop_requested)
        row.addWidget(self.stop_button)
        layout.addLayout(row)
        self.timer = QTimer(self)
        self.timer.setInterval(200)
        self.timer.timeout.connect(self.tick)

    def eventFilter(self, watched, event):
        if watched in (self.restore_button, self.drag_title):
            if event.type() == QEvent.MouseButtonPress and event.button() == Qt.LeftButton:
                self._drag_origin = event.globalPosition().toPoint()
                self._drag_position = self.pos()
                self._dragging = False
            elif event.type() == QEvent.MouseMove and self._drag_origin is not None:
                delta = event.globalPosition().toPoint() - self._drag_origin
                if delta.manhattanLength() >= QApplication.startDragDistance():
                    self._dragging = True
                if self._dragging:
                    self.move(self._drag_position + delta)
                    return True
            elif event.type() == QEvent.MouseButtonRelease and self._drag_origin is not None:
                dragged = self._dragging
                self._drag_origin = None
                self._dragging = False
                if dragged:
                    self.restore_button.setDown(False)
                    return True
        return super().eventFilter(watched, event)

    def set_compact(self, compact):
        """Change only presentation; keep the same native window and run control."""
        if self.compact == compact:
            return
        self.compact = compact
        self.content.setVisible(not compact)
        self.restore_button.setVisible(compact)
        self.setFixedWidth(44 if compact else 355)
        self.setMinimumHeight(0)
        self.setMaximumHeight(16777215)
        self.resize(44 if compact else 355, 44 if compact else self.content.sizeHint().height())
        # Keep the restored panel reachable near the edge of a screen.
        screen = self.screen()
        if screen:
            bounds = screen.availableGeometry()
            self.move(max(bounds.left(), min(self.x(), bounds.right() - self.width() + 1)),
                      max(bounds.top(), min(self.y(), bounds.bottom() - self.height() + 1)))

    def begin(self, control, total):
        self.control, self.running, self.paused = control, True, False
        self.module_id = self.workflow_started = self.module_started = None
        self.workflow_cycle = (1, 1)
        self.condition_message = ''
        self.progress.setRange(0, total)
        self.progress.setValue(0)
        self.state.setText("Démarrage dans 3 secondes…")
        self.sequence.setText("Placez la fenêtre cible au premier plan.")
        self.details.clear()
        self.last_times = (0, 0)
        self.pause_button.setText("Pause")
        self.pause_button.setEnabled(True)
        self.stop_button.setEnabled(True)
        self.timer.start()
        self.tick()
        self.show()

    def update_progress(self, module_id, name, iteration, repeat, row, count, index):
        now = self.control.active_time() if self.control else time.monotonic()
        if self.workflow_started is None:
            self.workflow_started = now
        if module_id != self.module_id:
            self.module_started = now
            self.module_id = module_id
        self.sequence.setText(name)
        cycle, total = self.workflow_cycle
        prefix = f'Tour {cycle}/{total or "∞"} · ' if total != 1 else ''
        self.details.setText(prefix + f"Répétition {iteration}/{repeat} · Action {row + 1}/{count}")
        self.progress.setValue(index + 1)
        if not self.paused:
            self.state.setText("En cours")
        self.tick()

    def set_paused(self, paused, reason):
        self.paused = paused
        self.pause_button.setText("Reprendre" if paused else "Pause")
        self.state.setText(reason if paused else self.condition_message or "En cours")
        self.state.setStyleSheet("color:#ffc56e;" if paused else "color:#8ce5c2;")
        self.tick()

    def toggle_pause(self):
        if self.paused:
            self.resume_requested.emit()
        else:
            self.pause_requested.emit()

    def tick(self):
        if self.control and self.workflow_started is not None and self.running:
            now = self.control.active_time()
            self.last_times = (now - self.workflow_started, now - self.module_started)
        self.timers.setText(f"Workflow {duration(self.last_times[0])}\nSéquence {duration(self.last_times[1])}")
        self.restore_button.setToolTip(
            f"{self.state.text()} · {self.sequence.text()}\n"
            f"Workflow {duration(self.last_times[0])} · Séquence {duration(self.last_times[1])}\n"
            "Cliquer pour ouvrir le suivi")

    def finish(self, result):
        self.tick()
        self.running = False
        self.timer.stop()
        self.state.setText(result)
        self.pause_button.setEnabled(False)
        self.stop_button.setEnabled(False)

    def closeEvent(self, event):
        if self.running:
            self.stop_requested.emit()
            self.state.setText("Arrêt demandé…")
            event.ignore()
        else:
            event.accept()
