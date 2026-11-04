"""Workflow-level region and daily OCR report settings."""
from PySide6.QtCore import Signal, QTime
from PySide6.QtWidgets import (QWidget, QVBoxLayout, QLabel, QCheckBox, QPlainTextEdit,
                              QTimeEdit, QSpinBox, QPushButton, QFormLayout)
from .ui_style import configure_form


class ReportPanel(QWidget):
    modified = Signal()
    region_requested = Signal()
    test_requested = Signal()

    def __init__(self, workflow, service):
        super().__init__()
        self.workflow, self.service = workflow, service
        self.refreshing = False
        layout = QVBoxLayout(self)
        layout.setContentsMargins(20, 18, 20, 18)
        layout.setSpacing(12)
        self.enabled = QCheckBox('Activer le compte rendu des termes observés')
        layout.addWidget(self.enabled)
        self.enabled.toggled.connect(self.update_config)
        explanation = QLabel('Pendant le workflow, le logiciel lit uniquement la zone choisie avec l’OCR Windows local.\n'
                             'Un texte qui reste visible compte une fois. Il doit disparaître sur deux lectures avant d’être recompté.\n'
                             'Le suivi s’arrête pendant les pauses et à la fin du workflow. Le compte rendu reste programmé.')
        explanation.setWordWrap(True)
        layout.addWidget(explanation)
        form = QFormLayout()
        configure_form(form)
        form.setContentsMargins(0, 0, 0, 0)
        self.at = QTimeEdit()
        self.at.setDisplayFormat('HH:mm')
        self.at.timeChanged.connect(self.update_config)
        form.addRow('Compte rendu quotidien à :', self.at)
        self.interval = QSpinBox()
        self.interval.setRange(1, 300)
        self.interval.setSuffix(' s après chaque lecture')
        self.interval.valueChanged.connect(self.update_config)
        form.addRow('Fréquence OCR :', self.interval)
        self.terms = QPlainTextEdit()
        self.terms.setPlaceholderText('Un terme ou une expression par ligne\nAjout de data a relever')
        self.terms.setMaximumHeight(85)
        self.terms.textChanged.connect(self.update_config)
        form.addRow('Termes à compter (30 maximum) :', self.terms)
        layout.addLayout(form)
        self.region_label = QLabel()
        layout.addWidget(self.region_label)
        self.choose = QPushButton('Sélectionner la zone à lire à l’écran…')
        self.choose.clicked.connect(self.region_requested)
        layout.addWidget(self.choose)
        self.test_button = QPushButton('Tester la lecture OCR de cette zone (sans compter)')
        self.test_button.clicked.connect(self.test_requested)
        layout.addWidget(self.test_button)
        self.preview = QLabel('Les termes, la zone et l’heure sont enregistrés avec le workflow.')
        self.preview.setWordWrap(True)
        layout.addWidget(self.preview)
        self.results = QPlainTextEdit()
        self.results.setReadOnly(True)
        self.results.setMaximumHeight(130)
        layout.addWidget(self.results)
        note = QLabel('Laissez Macro Studio ouvert et le PC éveillé à l’heure prévue. Activez aussi « Alertes Discord ».\n'
                      'La période va de l’heure du dernier bilan à celle du prochain (19 h → 19 h par défaut).\n'
                      'Le comptage dépend des lectures : les apparitions très brèves, le texte masqué et les erreurs OCR peuvent être manqués.')
        note.setWordWrap(True)
        layout.addWidget(note)
        layout.addStretch()
        service.changed.connect(self.refresh_counts)
        self.refresh()

    def refresh(self):
        self.refreshing = True
        config = self.workflow.report
        self.enabled.setChecked(config.enabled)
        self.at.setTime(QTime.fromString(config.at, 'HH:mm'))
        self.interval.setValue(config.interval)
        self.terms.setPlainText('\n'.join(config.terms))
        region = config.region
        self.region_label.setText('Zone : aucune sélection' if not region else
            f'Zone : x={region["left"]}, y={region["top"]} · {region["width"]} × {region["height"]} pixels')
        self.refreshing = False
        self.refresh_counts()

    def update_config(self, *args):
        if self.refreshing:
            return
        config = self.workflow.report
        config.enabled = self.enabled.isChecked()
        config.at = self.at.time().toString('HH:mm')
        config.interval = self.interval.value()
        config.terms = [line.strip() for line in self.terms.toPlainText().splitlines() if line.strip()]
        try:
            self.service.book.policy(config)
        except ValueError as exc:
            self.preview.setText(str(exc))
        self.modified.emit()

    def refresh_counts(self):
        rows = [r for r in self.service.book.records.values() if r['config_id'] == self.workflow.report.id]
        lines = []
        for row in sorted(rows, key=lambda r: r['due'])[-3:]:
            status = 'envoyé' if row['sent'] else 'en attente' if row['enabled'] else 'désactivé'
            lines.append(f'Bilan prévu : {row["due"]} — {status}')
            lines.extend(f'{term} : {count}' for term, count in row['counts'].items())
            lines.append(f'Lectures : {row["samples"]} · erreurs : {row["errors"]}')
        self.results.setPlainText('\n'.join(lines) or self.service.book.load_error or 'Aucun relevé. Configurez le suivi puis lancez le workflow.')
