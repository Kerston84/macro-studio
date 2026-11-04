"""Capture one chord locally without sending it to other applications."""
from PySide6.QtCore import Qt, QEvent
from PySide6.QtWidgets import QApplication, QDialog, QVBoxLayout, QLabel, QPushButton, QWidget

MODIFIERS = {Qt.Key_Control: "ctrl", Qt.Key_Alt: "alt", Qt.Key_Shift: "shift",
             Qt.Key_Meta: "cmd", Qt.Key_AltGr: "alt_gr"}
ORDER = ("ctrl", "alt", "alt_gr", "shift", "cmd")
SPECIAL = {Qt.Key_Return: "enter", Qt.Key_Enter: "enter", Qt.Key_Escape: "esc",
    Qt.Key_Tab: "tab", Qt.Key_Backtab: "tab", Qt.Key_Space: "space",
    Qt.Key_Backspace: "backspace", Qt.Key_Delete: "delete", Qt.Key_Insert: "insert",
    Qt.Key_Home: "home", Qt.Key_End: "end", Qt.Key_Up: "up", Qt.Key_Down: "down",
    Qt.Key_Left: "left", Qt.Key_Right: "right", Qt.Key_PageUp: "page_up", Qt.Key_PageDown: "page_down",
    Qt.Key_CapsLock: "caps_lock", Qt.Key_NumLock: "num_lock", Qt.Key_ScrollLock: "scroll_lock",
    Qt.Key_Print: "print_screen", Qt.Key_Pause: "pause", Qt.Key_Menu: "menu", Qt.Key_Plus: "plus"}
NAMES = {"ctrl": "Ctrl", "alt": "Alt", "alt_gr": "AltGr", "shift": "Maj", "cmd": "Windows",
    "enter": "Entrée", "esc": "Échap", "tab": "Tab", "space": "Espace", "backspace": "Retour arrière",
    "delete": "Suppr", "insert": "Inser", "page_up": "Page haut", "page_down": "Page bas",
    "home": "Début", "end": "Fin", "up": "Haut", "down": "Bas", "left": "Gauche", "right": "Droite",
    "caps_lock": "Verr. Maj", "num_lock": "Verr. Num", "scroll_lock": "Arrêt défil.",
    "print_screen": "Impr. écran", "pause": "Pause", "menu": "Menu", "plus": "+"}

def format_keys(keys):
    return " + ".join(NAMES.get(key, key.upper()) for key in keys.split("+"))

def key_token(event):
    key = event.key()
    if key in SPECIAL:
        return SPECIAL[key]
    if Qt.Key_F1 <= key <= Qt.Key_F24:
        return f"f{key - Qt.Key_F1 + 1}"
    if 33 <= key <= 0x10ffff:
        value = chr(key).lower()
        if len(value) == 1 and value.isprintable():
            return value
    return None

class KeyCaptureDialog(QDialog):
    def __init__(self, parent=None):
        super().__init__(parent)
        self.setWindowTitle("Capturer une touche ou un raccourci")
        self.setWindowModality(Qt.ApplicationModal)
        self.resize(460, 200)
        self.value = None
        self.down = set()
        self.modifier_chord = set()
        self.invalid_chord = False
        layout = QVBoxLayout(self)
        label = QLabel("Appuyez sur une touche ou une combinaison, puis relâchez toutes les touches.\n"
                       "Exemples : Entrée, Tab, Ctrl+C, Ctrl+Maj+S.\n"
                       "Échap peut être capturé. Pour annuler, cliquez sur Annuler.")
        label.setWordWrap(True)
        layout.addWidget(label)
        self.feedback = QLabel("En attente de votre touche…")
        self.feedback.setWordWrap(True)
        self.feedback.setStyleSheet("font-size:18px; padding:12px; color:#8ce5c2;")
        layout.addWidget(self.feedback)
        cancel = QPushButton("Annuler")
        cancel.setAutoDefault(False)
        cancel.clicked.connect(self.reject)
        layout.addWidget(cancel)

    def showEvent(self, event):
        super().showEvent(event)
        QApplication.instance().installEventFilter(self)
        self.setFocus()

    def hideEvent(self, event):
        QApplication.instance().removeEventFilter(self)
        super().hideEvent(event)

    def eventFilter(self, watched, event):
        if not isinstance(watched, QWidget) or not (watched is self or self.isAncestorOf(watched)):
            return super().eventFilter(watched, event)
        if event.type() == QEvent.ShortcutOverride:
            event.accept()
            return True
        if event.type() not in (QEvent.KeyPress, QEvent.KeyRelease):
            return super().eventFilter(watched, event)
        if event.isAutoRepeat():
            return True
        key = event.key()
        tracked = Qt.Key_Tab if key == Qt.Key_Backtab else key
        if event.type() == QEvent.KeyPress:
            self.down.add(tracked)
            if key == Qt.Key_F8:
                self.invalid_chord = True
                self.value = None
                self.feedback.setText("F8 est réservé à l’arrêt. Choisissez une autre touche.")
            elif key in MODIFIERS:
                self.modifier_chord.add(MODIFIERS[key])
                if not self.invalid_chord:
                    self.feedback.setText(format_keys("+".join(m for m in ORDER if m in self.modifier_chord)))
            elif not self.invalid_chord and self.value is None:
                token = key_token(event)
                if token is None:
                    self.invalid_chord = True
                    self.feedback.setText("Cette touche n’est pas prise en charge. Essayez une autre touche.")
                else:
                    mods = set(self.modifier_chord)
                    for flag, name in ((Qt.ControlModifier, "ctrl"), (Qt.AltModifier, "alt"),
                                       (Qt.ShiftModifier, "shift"), (Qt.MetaModifier, "cmd")):
                        if event.modifiers() & flag:
                            mods.add(name)
                    if event.modifiers() & Qt.GroupSwitchModifier or "alt_gr" in mods:
                        mods.difference_update({"ctrl", "alt"})
                        mods.add("alt_gr")
                    self.value = "+".join([m for m in ORDER if m in mods] + [token])
                    self.feedback.setText(format_keys(self.value) + " — relâchez les touches")
        else:
            self.down.discard(tracked)
            if not self.down:
                if self.invalid_chord:
                    self.invalid_chord = False
                    self.modifier_chord.clear()
                else:
                    if self.value is None and self.modifier_chord:
                        self.value = "+".join(m for m in ORDER if m in self.modifier_chord)
                    if self.value:
                        self.accept()
        event.accept()
        return True
