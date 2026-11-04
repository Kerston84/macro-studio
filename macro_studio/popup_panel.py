"""Global popup settings; no rules are inserted into action sequences."""
import base64
from pathlib import Path
from PySide6.QtCore import Qt, Signal, QByteArray, QBuffer, QIODevice, QTimer
from PySide6.QtGui import QImageReader, QPixmap
from PySide6.QtWidgets import (QWidget, QVBoxLayout, QHBoxLayout, QFormLayout, QSplitter,
    QLabel, QPushButton, QCheckBox, QListWidget, QLineEdit, QComboBox, QDoubleSpinBox,
    QSpinBox, QScrollArea, QFileDialog, QMessageBox, QLayout)
from .popups import PopupRule
from .vision import decode_template
from .ui_style import FlowLayout, configure_form

class PopupPanel(QWidget):
    modified = Signal()
    region_requested = Signal(str, str)

    def __init__(self, workflow):
        super().__init__()
        self.workflow = workflow
        layout = QVBoxLayout(self)
        self.enable = QCheckBox("Activer le Mode popups pendant toute l’exécution")
        self.enable.setObjectName("enable_popups")
        self.enable.setChecked(workflow.popups.enabled)
        self.enable.toggled.connect(self.set_enabled)
        layout.addWidget(self.enable)
        intro = QLabel("Règles globales : SI une image apparaît, ALORS cliquer ou attendre, puis reprendre. "
                       "Elles sont vérifiées entre les actions et pendant les attentes, toutes les 0,5 s environ. "
                       "Une saisie ou un raccourci en cours se termine avant toute intervention.")
        intro.setWordWrap(True)
        layout.addWidget(intro)
        bar = FlowLayout()
        add = QPushButton("+ Ajouter un popup")
        add.clicked.connect(self.add_rule)
        bar.addWidget(add)
        remove = QPushButton("Supprimer la règle sélectionnée")
        remove.clicked.connect(self.remove_rule)
        bar.addWidget(remove)
        layout.addLayout(bar)
        splitter = QSplitter()
        self.rules = QListWidget()
        self.rules.currentRowChanged.connect(self.show_rule)
        splitter.addWidget(self.rules)
        properties = QWidget()
        self.form = QFormLayout(properties)
        configure_form(self.form)
        self.form.setSizeConstraint(QLayout.SetMinimumSize)
        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        scroll.setWidget(properties)
        splitter.addWidget(scroll)
        splitter.setSizes([320, 650])
        splitter.setChildrenCollapsible(False)
        layout.addWidget(splitter, 1)
        self.refresh()

    def set_enabled(self, enabled):
        self.workflow.popups.enabled = enabled
        self.modified.emit()

    def refresh(self, selected=None):
        if selected is None:
            selected = self.rules.currentRow()
        self.enable.blockSignals(True)
        self.enable.setChecked(self.workflow.popups.enabled)
        self.enable.blockSignals(False)
        self.rules.blockSignals(True)
        self.rules.clear()
        for rule in self.workflow.popups.rules:
            self.rules.addItem(("● " if rule.enabled else "○ ") + rule.name)
        self.rules.blockSignals(False)
        self.rules.setCurrentRow(selected if 0 <= selected < self.rules.count() else -1)
        self.show_rule(self.rules.currentRow())

    def add_rule(self):
        self.workflow.popups.rules.append(PopupRule(name=f"Popup {len(self.workflow.popups.rules) + 1}"))
        self.refresh(len(self.workflow.popups.rules) - 1)
        self.modified.emit()

    def remove_rule(self):
        index = self.rules.currentRow()
        if index >= 0:
            del self.workflow.popups.rules[index]
            self.refresh(min(index, len(self.workflow.popups.rules) - 1))
            self.modified.emit()

    def update_rule(self, rule, key, value):
        setattr(rule, key, value)
        if key in ("x", "y"):
            rule.point_selected = True
        for index, candidate in enumerate(self.workflow.popups.rules):
            if candidate.id == rule.id:
                self.rules.item(index).setText(("● " if rule.enabled else "○ ") + rule.name)
                break
        self.modified.emit()

    def show_rule(self, index):
        while self.form.rowCount():
            self.form.removeRow(0)
        if not 0 <= index < len(self.workflow.popups.rules):
            self.form.addRow(QLabel("Ajoutez ou sélectionnez une règle popup."))
            return
        rule = self.workflow.popups.rules[index]
        enabled = QCheckBox("Activer cette règle")
        enabled.setChecked(rule.enabled)
        enabled.toggled.connect(lambda value: self.update_rule(rule, "enabled", value))
        self.form.addRow(enabled)
        name = QLineEdit(rule.name)
        name.setMaxLength(120)
        name.textChanged.connect(lambda value: self.update_rule(rule, "name", value))
        self.form.addRow("Nom", name)
        self.image_control(rule, target=False)
        response = QComboBox()
        for label, value in (("Cliquer sur l’image détectée", "click_detected"),
            ("Cliquer sur une autre image", "click_image"), ("Cliquer à une position", "click_point"),
            ("Attendre puis reprendre", "wait")):
            response.addItem(label, value)
        response.setCurrentIndex(response.findData(rule.response))
        response.currentIndexChanged.connect(lambda i: self.change_response(rule, response.itemData(i)))
        self.form.addRow("ALORS", response)
        if rule.response == "click_image":
            self.image_control(rule, target=True)
        elif rule.response == "click_point":
            choose = QPushButton("Choisir où cliquer…")
            choose.clicked.connect(lambda: self.region_requested.emit(rule.id, "point"))
            self.form.addRow(choose)
            for key in ("x", "y"):
                editor = QSpinBox()
                editor.setRange(-100000, 100000)
                editor.setValue(getattr(rule, key))
                editor.valueChanged.connect(lambda value, k=key: self.update_rule(rule, k, value))
                self.form.addRow(key.upper(), editor)
        elif rule.response == "wait":
            self.number(rule, "seconds", "Attendre", 0, 3600, " s")
        self.number(rule, "threshold", "Seuil de similarité", .5, 1)
        self.number(rule, "cooldown", "Délai entre interventions", .5, 3600, " s")
        limit = QSpinBox()
        limit.setRange(1, 10000)
        limit.setValue(rule.max_triggers)
        limit.valueChanged.connect(lambda value: self.update_rule(rule, "max_triggers", value))
        self.form.addRow("Interventions maximum", limit)
        zone = QPushButton("Choisir la zone de détection…")
        zone.clicked.connect(lambda: self.region_requested.emit(rule.id, "region"))
        self.form.addRow(zone)
        label = QLabel(f"Zone : {rule.region['width']} × {rule.region['height']} px" if rule.region else "Détection : tout l’écran")
        self.form.addRow(label)
        if rule.region:
            clear = QPushButton("Surveiller tout l’écran")
            clear.clicked.connect(lambda: self.clear_region(rule))
            self.form.addRow(clear)
        note = QLabel("Une règle à la fois, dans l’ordre de la liste. Un popup qui reste visible peut "
                      "déclencher à nouveau après le délai ; au maximum d’interventions, le workflow s’arrête. "
                      "F8 interrompt aussi les attentes des popups. Utilisez une image distinctive et gardez la cible visible.")
        note.setWordWrap(True)
        self.form.addRow(note)

    def number(self, rule, key, label, low, high, suffix=""):
        editor = QDoubleSpinBox()
        editor.setRange(low, high)
        editor.setDecimals(2)
        editor.setSingleStep(.01 if key == "threshold" else .5)
        editor.setSuffix(suffix)
        editor.setValue(getattr(rule, key))
        editor.valueChanged.connect(lambda value: self.update_rule(rule, key, value))
        self.form.addRow(label, editor)

    def change_response(self, rule, value):
        self.update_rule(rule, "response", value)
        QTimer.singleShot(0, lambda: self.show_rule(self.rules.currentRow()))

    def clear_region(self, rule):
        self.update_rule(rule, "region", None)
        self.show_rule(self.rules.currentRow())

    def image_control(self, rule, target):
        choose = QPushButton("Choisir l’image à cliquer…" if target else "SI cette image apparaît…")
        choose.clicked.connect(lambda: self.choose_image(rule, target))
        self.form.addRow(choose)
        name = rule.target_name if target else rule.image_name
        self.form.addRow(QLabel(name or "Aucune image choisie"))
        encoded = rule.target_image if target else rule.image
        if encoded:
            pixmap = QPixmap()
            pixmap.loadFromData(base64.b64decode(encoded))
            preview = QLabel()
            preview.setPixmap(pixmap.scaled(220, 100, Qt.KeepAspectRatio, Qt.SmoothTransformation))
            self.form.addRow(preview)

    def choose_image(self, rule, target=False):
        path, _ = QFileDialog.getOpenFileName(self, "Image du popup ou du bouton", "", "Images (*.png *.jpg *.jpeg *.bmp)")
        if not path:
            return
        try:
            reader = QImageReader(path)
            size = reader.size()
            if not (8 <= size.width() <= 1024 and 8 <= size.height() <= 1024):
                raise ValueError("Recadrez l’image entre 8 et 1024 pixels par dimension.")
            image = reader.read()
            data = QByteArray()
            buffer = QBuffer(data)
            buffer.open(QIODevice.WriteOnly)
            if image.isNull() or not image.save(buffer, "PNG"):
                raise ValueError("Image illisible.")
            buffer.close()
            encoded = base64.b64encode(bytes(data)).decode("ascii")
            decode_template(encoded)
            setattr(rule, "target_image" if target else "image", encoded)
            setattr(rule, "target_name" if target else "image_name", Path(path).name[:256])
            self.modified.emit()
            self.show_rule(self.rules.currentRow())
        except (OSError, ValueError) as exc:
            QMessageBox.warning(self, "Image invalide", str(exc))
