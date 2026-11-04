"""Presentation-only layout helpers and shared dark palette."""
from PySide6.QtCore import Qt, QRect, QSize
from PySide6.QtGui import QPainter
from PySide6.QtWidgets import QLayout, QPushButton, QSizePolicy, QStyle, QStyleOptionButton, QFormLayout
from pathlib import Path


class FlowLayout(QLayout):
    """Keep actions in order and wrap rows to the available width."""
    def __init__(self, parent=None, spacing=6):
        super().__init__(parent)
        self.items = []
        self.setContentsMargins(0, 0, 0, 0)
        self.setSpacing(spacing)

    def addItem(self, item): self.items.append(item)
    def count(self): return len(self.items)
    def itemAt(self, index): return self.items[index] if 0 <= index < len(self.items) else None
    def takeAt(self, index): return self.items.pop(index) if 0 <= index < len(self.items) else None
    def expandingDirections(self): return Qt.Orientations()
    def hasHeightForWidth(self): return True
    def heightForWidth(self, width): return self.arrange(QRect(0, 0, width, 0), True)
    def setGeometry(self, rect):
        super().setGeometry(rect)
        self.arrange(rect, False)
    def sizeHint(self): return self.minimumSize()
    def minimumSize(self):
        size = QSize()
        for item in self.items:
            size = size.expandedTo(item.minimumSize())
        return size
    def arrange(self, rect, measure):
        x, y, row_height = rect.x(), rect.y(), 0
        for item in self.items:
            if item.widget() and item.widget().isHidden():
                continue
            size = item.sizeHint()
            width = min(size.width(), max(1, rect.width()))
            if x > rect.x() and x + width > rect.right() + 1:
                x, y, row_height = rect.x(), y + row_height + self.spacing(), 0
            if not measure:
                item.setGeometry(QRect(x, y, width, size.height()))
            x += width + self.spacing()
            row_height = max(row_height, size.height())
        return y + row_height - rect.y()


class BlockButton(QPushButton):
    """Multiline library labels retain their full text on narrow columns."""
    def __init__(self, text):
        super().__init__(text)
        policy = QSizePolicy(QSizePolicy.Expanding, QSizePolicy.Preferred)
        policy.setHeightForWidth(True)
        self.setSizePolicy(policy)
        self.setProperty('role', 'block')
        self.setToolTip(text)
    def minimumSizeHint(self): return QSize(120, 38)
    def sizeHint(self): return QSize(210, self.heightForWidth(210))
    def heightForWidth(self, width):
        text = self.fontMetrics().boundingRect(QRect(0, 0, max(40, width - 28), 1000), Qt.TextWordWrap, self.text())
        return max(38, text.height() + 18)
    def paintEvent(self, event):
        option = QStyleOptionButton()
        self.initStyleOption(option)
        option.text = ''
        painter = QPainter(self)
        self.style().drawControl(QStyle.CE_PushButton, option, painter, self)
        painter.setPen(self.palette().buttonText().color())
        painter.drawText(self.rect().adjusted(14, 6, -12, -6), Qt.AlignVCenter | Qt.AlignLeft | Qt.TextWordWrap, self.text())


def configure_form(form):
    form.setRowWrapPolicy(QFormLayout.WrapLongRows)
    form.setFieldGrowthPolicy(QFormLayout.AllNonFixedFieldsGrow)
    form.setLabelAlignment(Qt.AlignLeft | Qt.AlignVCenter)
    form.setHorizontalSpacing(16)
    form.setVerticalSpacing(10)
    form.setContentsMargins(16, 16, 16, 16)


STYLE = '''
QWidget { background:#171f2c; color:#dfe6f2; font-family:'Segoe UI'; font-size:13px; }
QMainWindow,QDialog { background:#10151e; }
QWidget#workspace { background:#10151e; }
QWidget#panel,QWidget#settingsPanel { background:#171f2c; border-radius:10px; }
QLabel { background:transparent; border:none; padding:0; }
QLabel[role="heading"] { color:#f3f6fc; font-size:23px; font-weight:600; }
QLabel[role="section"] { color:#96abc9; font-size:11px; font-weight:600; padding:3px 0 9px 0; }
QLabel[role="muted"],QLabel#current_file_status { color:#97a7bd; }
QPushButton { background:#222e40; border:1px solid #34435a; padding:7px 12px; border-radius:6px; min-height:18px; }
QPushButton:hover { background:#2c3e56; border-color:#536f95; }
QPushButton:pressed { background:#192b42; }
QPushButton:focus { border-color:#7bb4ff; }
QPushButton:disabled { color:#617086; background:#19212e; border-color:#263245; }
QPushButton[role="primary"] { color:#0d1c30; background:#82b5ff; border-color:#82b5ff; font-weight:600; }
QPushButton[role="primary"]:hover { background:#a2c9ff; }
QPushButton[role="primary"]:disabled { color:#71829b; background:#28394f; border-color:#34435a; }
QPushButton[role="danger"] { color:#ffb8ba; border-color:#60404b; background:#33232e; }
QPushButton[role="danger"]:disabled { color:#79636d; background:#211e28; border-color:#332c39; }
QPushButton[role="block"] { background:#1c293b; text-align:left; }
QLineEdit,QPlainTextEdit,QSpinBox,QDoubleSpinBox,QComboBox,QTimeEdit {
 background:#101823; color:#e2eaf6; border:1px solid #344258; border-radius:5px; padding:6px 8px;
 selection-background-color:#355d8c; selection-color:#ffffff; }
QLineEdit:focus,QPlainTextEdit:focus,QSpinBox:focus,QDoubleSpinBox:focus,QComboBox:focus,QTimeEdit:focus { border-color:#80b3ff; }
QLineEdit,QSpinBox,QDoubleSpinBox,QComboBox,QTimeEdit { min-height:20px; }
QComboBox QAbstractItemView { background:#1b2739; color:#e2eaf6; selection-background-color:#355d8c; }
QListWidget { background:#121b28; border:1px solid #2c3b51; border-radius:7px; outline:0; padding:5px; }
QListWidget::item { padding:10px; border-radius:5px; margin:2px; }
QListWidget::item:hover { background:#203149; }
QListWidget::item:selected { background:#294b75; color:#ffffff; }
QTabWidget::pane { border:1px solid #2c3b51; border-radius:8px; background:#171f2c; top:-1px; }
QTabBar::tab { background:#141d2a; color:#98a9c1; padding:10px 14px; border:1px solid transparent; border-bottom:2px solid transparent; }
QTabBar::tab:selected { color:#e7f1ff; background:#1b2a40; border-bottom-color:#82b5ff; }
QTabBar::tab:hover { color:#ffffff; background:#22324a; }
QTabBar QToolButton { background:#283a53; color:#ffffff; border:1px solid #425d80; }
QScrollArea { border:0; background:transparent; }
QScrollArea>QWidget>QWidget { background:#171f2c; }
QScrollBar:vertical { background:#111a27; width:10px; margin:2px; border-radius:4px; }
QScrollBar::handle:vertical { background:#3b506e; min-height:28px; border-radius:4px; }
QScrollBar:horizontal { background:#111a27; height:10px; margin:2px; }
QScrollBar::handle:horizontal { background:#3b506e; min-width:28px; border-radius:4px; }
QScrollBar::add-line,QScrollBar::sub-line { height:0; width:0; }
QScrollBar::add-page,QScrollBar::sub-page { background:transparent; }
QSplitter::handle { background:#101722; width:8px; height:8px; }
QSplitter::handle:hover { background:#365172; }
QCheckBox { background:transparent; spacing:8px; padding:4px 0; }
QCheckBox::indicator { width:16px; height:16px; border:1px solid #50627f; background:#121b28; border-radius:4px; }
QCheckBox::indicator:checked { background:#82b5ff; border-color:#82b5ff; image:url("@CHECK@"); }
QCheckBox:disabled { color:#65758e; }
QGroupBox { border:1px solid #344258; border-radius:7px; margin-top:12px; padding:14px 6px 6px; }
QGroupBox::title { subcontrol-origin:margin; left:12px; padding:0 5px; color:#b9cbe4; }
QProgressBar { border:1px solid #344258; border-radius:5px; background:#101823; text-align:center; min-height:18px; }
QProgressBar::chunk { background:#568dcd; border-radius:4px; }
QSlider::groove:horizontal { height:5px; background:#34465f; border-radius:2px; }
QSlider::sub-page:horizontal { background:#82b5ff; border-radius:2px; }
QSlider::handle:horizontal { width:14px; margin:-5px 0; background:#a8ccff; border:1px solid #82b5ff; border-radius:7px; }
QStatusBar { color:#8ea2bd; background:#10151e; font-size:11px; }
QToolTip { color:#e9f1ff; background:#23344d; border:1px solid #526d94; padding:6px; }
QComboBox::drop-down { width:24px; border:0; }
QComboBox::down-arrow { image:url("@DOWN@"); width:12px; height:8px; }
QSpinBox::up-button,QDoubleSpinBox::up-button,QTimeEdit::up-button { subcontrol-origin:border; subcontrol-position:top right; width:22px; background:#25364b; border-top-right-radius:5px; }
QSpinBox::down-button,QDoubleSpinBox::down-button,QTimeEdit::down-button { subcontrol-origin:border; subcontrol-position:bottom right; width:22px; background:#25364b; border-bottom-right-radius:5px; }
QSpinBox::up-arrow,QDoubleSpinBox::up-arrow,QTimeEdit::up-arrow { image:url("@UP@"); width:10px; height:6px; }
QSpinBox::down-arrow,QDoubleSpinBox::down-arrow,QTimeEdit::down-arrow { image:url("@DOWN@"); width:10px; height:6px; }
'''
for token, filename in [('@CHECK@', 'check.svg'), ('@UP@', 'chevron-up.svg'), ('@DOWN@', 'chevron-down.svg')]:
    STYLE = STYLE.replace(token, (Path(__file__).parent / 'icons' / filename).as_posix())
