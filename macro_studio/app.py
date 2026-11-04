import copy
import base64
from datetime import datetime
from pathlib import Path
import sys
import threading
from PySide6.QtCore import QThread, Signal, Qt, QBuffer, QByteArray, QIODevice, QTimer
from PySide6.QtGui import QImageReader, QPixmap, QShortcut, QKeySequence, QIcon
from PySide6.QtWidgets import (QApplication, QMainWindow, QWidget, QVBoxLayout,
    QHBoxLayout, QSplitter, QLabel, QPushButton, QListWidget, QFormLayout,
    QSpinBox, QDoubleSpinBox, QComboBox, QLineEdit, QPlainTextEdit,
    QFileDialog, QMessageBox, QAbstractItemView, QTabWidget, QScrollArea, QCheckBox, QLayout, QGroupBox, QDialog, QInputDialog)
from .model import Action, DEFAULTS, LABELS, IMAGE_KINDS, CLICK_KINDS, AFTER_CLICK_DEFAULTS, save, load
from .engine import DesktopBackend, execute
from .workflow import Workflow, load_workflow, save_workflow
from .workflow_view import WorkflowPanel
from .region_picker import RegionPicker
from .key_capture import KeyCaptureDialog, format_keys
from .launcher import DocumentLibrary, LaunchDialog, document_type
from .popup_panel import PopupPanel
from .run_control import RunControl, WindowGuard
from .run_widget import RunWidget
from .discord_notifications import DiscordNotifier, DiscordPanel
from .reporting import ReportService
from .report_panel import ReportPanel
from .ui_style import FlowLayout, BlockButton, configure_form, STYLE
from .paths import prepare_workflow_folder
from .version import APP_ID

class Worker(QThread):
    message = Signal(str)
    progress = Signal(int)
    result = Signal(str)
    pause_state = Signal(bool, str)
    cycle_progress = Signal(int, int)
    condition_progress = Signal(int, bool, str)

    def __init__(self, actions, backend_factory=DesktopBackend, popups=None, safety_enabled=False, cycles=1, conditions=None):
        super().__init__()
        self.actions = copy.deepcopy(actions)
        self.stop_event = threading.Event()
        self.backend_factory = backend_factory
        self.popups = copy.deepcopy(popups)
        self.safety_enabled = safety_enabled
        self.cycles = cycles
        self.conditions = copy.deepcopy(conditions or {})
        self.ignored_windows = ()
        self.blocked_windows = ()
        self.control = RunControl(self.stop_event, on_state=self.pause_state.emit)

    def run(self):
        listener = None
        try:
            from pynput.keyboard import Listener, Key
            listener = Listener(on_press=lambda key: self.stop_event.set() if key == Key.f8 else None)
            listener.start()
            listener.wait()
            backend = self.backend_factory()
            if self.safety_enabled:
                self.control.guard = WindowGuard(self.ignored_windows, self.blocked_windows)
                self.control.safety_enabled = True
            if isinstance(backend, DesktopBackend):
                backend.execution_control = self.control
            result = execute(self.actions, backend, self.control,
                             self.message.emit, self.progress.emit, popup_mode=self.popups,
                             cycles=self.cycles, cycle_progress=self.cycle_progress.emit,
                             conditions=self.conditions, condition_progress=self.condition_progress.emit)
            self.result.emit(result)
        except Exception as exc:
            self.result.emit(f"Erreur : {exc}")
        finally:
            if listener:
                listener.stop()
                listener.join(timeout=1)

class MainWindow(QMainWindow):
    def __init__(self):
        super().__init__()
        self.workflow = Workflow()
        self.library_store = DocumentLibrary()
        self.current_module = self.workflow.modules[0].id
        self.actions = self.workflow.modules[0].actions
        self.run_mapping = []
        self.last_module_pass = None
        self.notification_position = "Avant la première action"
        self.picking_region = False
        self.region_picker = None
        self.worker = None
        self.workflow_cycle = 1
        self.run_cycles = 1
        self.focus_mode = False
        self.path = None
        self.document_format = "workflow"
        self.dirty = False
        self.last_result = "Terminé"
        self.run_widget = RunWidget()
        self.run_widget.pause_requested.connect(self.pause_run)
        self.run_widget.resume_requested.connect(self.resume_run)
        self.run_widget.stop_requested.connect(self.stop)
        self.setWindowTitle("Windows Macro Studio • Workflows")
        self.resize(1400, 880)
        root = QWidget()
        root.setObjectName("workspace")
        self.setCentralWidget(root)
        layout = QVBoxLayout(root)
        layout.setContentsMargins(18, 14, 18, 8)
        layout.setSpacing(10)
        header = QHBoxLayout()
        title = QLabel("Windows Macro Studio")
        title.setProperty('role', 'heading')
        header.addWidget(title)
        header.addStretch()
        layout.addLayout(header)
        toolbar = FlowLayout()
        self.edit_buttons = []
        for label, callback in [("Accueil", self.show_launcher), ("Nouveau", self.new), ("Ouvrir…", self.open_file),
                                ("Enregistrer", self.save_file), ("Enregistrer sous…", self.save_as),
                                ("Exporter la séquence", self.export_sequence)]:
            button = QPushButton(label)
            button.clicked.connect(callback)
            toolbar.addWidget(button)
            self.edit_buttons.append(button)
        self.start_button = QPushButton("Démarrer")
        self.start_button.setProperty('role', 'primary')
        self.start_button.clicked.connect(self.start)
        header.addWidget(self.start_button)
        self.stop_button = QPushButton("Arrêter · F8")
        self.stop_button.setProperty('role', 'danger')
        self.stop_button.clicked.connect(self.stop)
        self.stop_button.setEnabled(False)
        header.addWidget(self.stop_button)
        layout.addLayout(toolbar)
        self.file_label = QLabel("Nouveau document — choisissez son nom lors de la première sauvegarde.")
        self.file_label.setObjectName("current_file_status")
        self.file_label.setWordWrap(True)
        self.file_label.setMinimumWidth(0)
        file_row = QHBoxLayout()
        file_row.addWidget(self.file_label, 1)
        rename_file = QPushButton("Renommer le fichier…")
        rename_file.clicked.connect(self.rename_current_file)
        file_row.addWidget(rename_file)
        self.edit_buttons.append(rename_file)
        layout.addLayout(file_row)
        self.save_shortcut = QShortcut(QKeySequence.Save, self)
        self.save_shortcut.activated.connect(self.save_file)
        self.save_as_shortcut = QShortcut(QKeySequence.SaveAs, self)
        self.save_as_shortcut.activated.connect(self.save_as)
        hint = QLabel("Ajoutez un bloc, puis ajustez ses propriétés. Le lancement commence après 3 secondes.")
        hint.setWordWrap(True)
        hint.setProperty('role', 'muted')
        layout.addWidget(hint)
        options = FlowLayout(spacing=24)
        self.safety_checkbox = QCheckBox("Sécurité automatique")
        self.safety_checkbox.setToolTip("Pause si une fenêtre masque la cible ou si une image cible est introuvable.")
        self.safety_checkbox.setChecked(self.workflow.safety_enabled)
        self.safety_checkbox.setObjectName("safety_enabled")
        self.safety_checkbox.toggled.connect(self.set_safety)
        options.addWidget(self.safety_checkbox)
        self.discord_toggle = QCheckBox("Alertes Discord")
        self.discord_toggle.setToolTip("Décochez pendant vos tests : aucune nouvelle alerte automatique. Le webhook reste enregistré.")
        options.addWidget(self.discord_toggle)
        layout.addLayout(options)
        module_bar = QHBoxLayout()
        module_bar.addWidget(QLabel("Séquence en cours :"))
        self.module_selector = QComboBox()
        self.module_selector.currentIndexChanged.connect(self.select_module)
        module_bar.addWidget(self.module_selector, 1)
        rename_sequence = QPushButton("Renommer la séquence…")
        rename_sequence.setObjectName("rename_sequence")
        rename_sequence.clicked.connect(self.rename_sequence)
        module_bar.addWidget(rename_sequence)
        self.edit_buttons.append(rename_sequence)
        layout.addLayout(module_bar)
        self.tabs = QTabWidget()
        self.chrome_items = [layout.itemAt(i) for i in range(layout.count())]
        self.tabs.setDocumentMode(True)
        self.tabs.setUsesScrollButtons(True)
        self.tabs.tabBar().setExpanding(False)
        layout.addWidget(self.tabs, 1)
        splitter = QSplitter(Qt.Horizontal)
        self.editor_splitter = splitter
        self.tabs.addTab(splitter, "Éditeur de séquence")
        self.library = QWidget()
        self.library.setObjectName('panel')
        library_layout = QVBoxLayout(self.library)
        library_layout.setContentsMargins(12, 14, 12, 12)
        library_layout.setSpacing(7)
        library_heading = QLabel("BIBLIOTHÈQUE DE BLOCS")
        library_heading.setProperty('role', 'section')
        library_layout.addWidget(library_heading)
        for kind in DEFAULTS:
            button = BlockButton("+ " + LABELS[kind])
            button.clicked.connect(lambda checked=False, k=kind: self.add_action(k))
            library_layout.addWidget(button)
        library_layout.addStretch()
        library_scroll = QScrollArea()
        self.library_scroll = library_scroll
        library_scroll.setWidgetResizable(True)
        library_scroll.setMinimumWidth(150)
        library_scroll.setWidget(self.library)
        splitter.addWidget(library_scroll)
        center = QWidget()
        center.setObjectName('panel')
        center_layout = QVBoxLayout(center)
        center_layout.setContentsMargins(12, 14, 12, 12)
        sequence_heading = QLabel("SÉQUENCE")
        sequence_heading.setProperty('role', 'section')
        center_layout.addWidget(sequence_heading)
        self.sequence = QListWidget()
        self.sequence.setSelectionMode(QAbstractItemView.SingleSelection)
        self.sequence.currentRowChanged.connect(self.show_properties)
        center_layout.addWidget(self.sequence)
        row = FlowLayout()
        for label, callback in [("↑ Monter", lambda: self.move(-1)),
                                ("↓ Descendre", lambda: self.move(1)),
                                ("Dupliquer", self.duplicate), ("Supprimer", self.remove)]:
            button = QPushButton(label)
            button.clicked.connect(callback)
            row.addWidget(button)
            self.edit_buttons.append(button)
        center_layout.addLayout(row)
        splitter.addWidget(center)
        self.properties = QWidget()
        self.form = QFormLayout(self.properties)
        configure_form(self.form)
        self.form.setSizeConstraint(QLayout.SetMinimumSize)
        properties_scroll = QScrollArea()
        properties_scroll.setWidgetResizable(True)
        properties_scroll.setMinimumWidth(260)
        properties_scroll.setWidget(self.properties)
        splitter.addWidget(properties_scroll)
        splitter.setChildrenCollapsible(False)
        splitter.setStretchFactor(0, 0)
        splitter.setStretchFactor(1, 1)
        splitter.setStretchFactor(2, 1)
        splitter.setSizes([225, 565, 410])
        self.workflow_panel = WorkflowPanel(self.workflow)
        self.workflow_panel.modified.connect(self.workflow_modified)
        self.workflow_panel.edit_requested.connect(self.edit_module)
        self.workflow_panel.fullscreen_requested.connect(self.toggle_workflow_focus)
        self.tabs.addTab(self.workflow_panel, "Workflow • Modules")
        self.popup_panel = PopupPanel(self.workflow)
        self.popup_panel.modified.connect(self.changed)
        self.popup_panel.region_requested.connect(self.choose_popup_region)
        self.tabs.addTab(self.popup_panel, "Mode popups")
        self.discord = DiscordNotifier(self)
        self.discord.remote.command_requested.connect(self.discord_command)
        self.discord_panel = DiscordPanel(self.discord)
        self.discord_toggle.setChecked(self.discord.enabled)
        self.discord_toggle.toggled.connect(self.toggle_discord)
        self.discord.enabled_changed.connect(self.sync_discord_toggle)
        discord_scroll = QScrollArea()
        discord_scroll.setWidgetResizable(True)
        discord_scroll.setWidget(self.discord_panel)
        self.tabs.addTab(discord_scroll, "Notifications Discord")
        self.reports = ReportService(self.discord, self)
        self.report_panel = ReportPanel(self.workflow, self.reports)
        report_scroll = QScrollArea()
        report_scroll.setWidgetResizable(True)
        report_scroll.setWidget(self.report_panel)
        self.tabs.addTab(report_scroll, "Compte rendu OCR")
        self.report_panel.modified.connect(self.changed)
        self.report_panel.region_requested.connect(self.choose_report_region)
        self.report_panel.test_requested.connect(self.test_report_ocr)
        self.reports.message.connect(self.log)
        self.reports.preview_done.connect(self.report_preview_done)
        self.focus_shortcut = QShortcut(QKeySequence('F11'), self)
        self.focus_shortcut.activated.connect(self.toggle_workflow_focus)
        self.focus_escape = QShortcut(QKeySequence('Esc'), self)
        self.focus_escape.setEnabled(False)
        self.focus_escape.activated.connect(self.toggle_workflow_focus)
        self.discord.completed.connect(lambda ok, message: self.log(message))
        self.tabs.currentChanged.connect(self.tab_changed)
        journal_heading = QLabel("JOURNAL D’EXÉCUTION")
        self.journal_heading = journal_heading
        journal_heading.setProperty('role', 'section')
        layout.addWidget(journal_heading)
        self.journal = QPlainTextEdit()
        self.journal.setReadOnly(True)
        self.journal.setMaximumBlockCount(2000)
        self.journal.setMinimumHeight(48)
        self.journal.setMaximumHeight(78)
        layout.addWidget(self.journal)
        self.statusBar().showMessage("Prêt — 0 bloc")
        self.show_properties(-1)
        self.refresh_modules()

    def toggle_workflow_focus(self):
        self.focus_mode = not self.focus_mode
        if self.focus_mode:
            self._focus_previous_state = self.windowState()
            self.tabs.setCurrentIndex(1)
        def visible(item):
            widget = item.widget()
            if widget:
                if widget not in (self.start_button, self.stop_button):
                    widget.setVisible(not self.focus_mode)
            elif item.layout():
                for index in range(item.layout().count()):
                    visible(item.layout().itemAt(index))
        for item in self.chrome_items:
            visible(item)
        self.tabs.tabBar().setVisible(not self.focus_mode)
        self.journal_heading.setVisible(not self.focus_mode)
        self.journal.setVisible(not self.focus_mode)
        self.statusBar().setVisible(not self.focus_mode)
        self.focus_escape.setEnabled(self.focus_mode)
        self.workflow_panel.fullscreen_button.setText('Quitter le plein écran · F11' if self.focus_mode else 'Agrandir le workflow · F11')
        if self.focus_mode:
            self.showFullScreen()
        else:
            self.setWindowState(self._focus_previous_state)
            self.show()

    def resizeEvent(self, event):
        super().resizeEvent(event)
        if hasattr(self, 'library_scroll'):
            compact = self.width() < 1050
            self.library_scroll.setMaximumWidth(185 if compact else 250)
            if compact != getattr(self, '_compact_layout', None):
                self._compact_layout = compact
                self.editor_splitter.setSizes([170, 290, 340] if compact else [225, 565, 410])

    def refresh_modules(self):
        self.module_selector.blockSignals(True)
        self.module_selector.clear()
        for module in self.workflow.modules:
            self.module_selector.addItem(module.name, module.id)
        self.module_selector.setCurrentIndex(self.module_selector.findData(self.current_module))
        self.module_selector.blockSignals(False)

    def select_module(self, index):
        identifier = self.module_selector.itemData(index)
        if identifier:
            self.current_module = identifier
            self.actions = self.workflow.get(identifier).actions
            self.refresh(0 if self.actions else -1)

    def edit_module(self, identifier):
        if self.focus_mode:
            self.toggle_workflow_focus()
        self.module_selector.setCurrentIndex(self.module_selector.findData(identifier))
        self.tabs.setCurrentIndex(0)

    def workflow_modified(self):
        if self.current_module not in [m.id for m in self.workflow.modules]:
            self.current_module = self.workflow.modules[0].id
            self.actions = self.workflow.modules[0].actions
            self.refresh(-1)
        self.refresh_modules()
        self.popup_panel.refresh()
        self.report_panel.refresh()
        self.sync_safety()
        self.changed()

    def tab_changed(self, index):
        self.start_button.setText("Démarrer le workflow" if index != 0 else "Démarrer la séquence")
        if index == 1:
            self.workflow_panel.refresh()
            self.workflow_panel.fit()

    def set_document(self, workflow, path=None, document_format="workflow"):
        self.workflow = workflow
        self.current_module = workflow.modules[0].id
        self.actions = workflow.modules[0].actions
        self.workflow_panel.workflow = workflow
        self.workflow_panel.refresh()
        self.popup_panel.workflow = workflow
        self.popup_panel.refresh()
        self.report_panel.workflow = workflow
        self.report_panel.refresh()
        self.sync_safety()
        self.refresh_modules()
        self.path, self.dirty = path, False
        self.document_format = document_format
        if path:
            self.library_store.remember(path)
        self.update_document_status()
        self.refresh(0 if self.actions else -1)

    def log(self, text):
        self.journal.appendPlainText(f"{datetime.now():%H:%M:%S}  {text}")

    def sync_discord_toggle(self, enabled):
        self.discord_toggle.blockSignals(True)
        self.discord_toggle.setChecked(enabled)
        self.discord_toggle.blockSignals(False)

    def toggle_discord(self, enabled):
        try:
            self.discord.set_enabled(enabled)
            self.log("Alertes Discord activées." if enabled else "Alertes Discord désactivées pour les tests.")
        except ValueError as exc:
            self.sync_discord_toggle(self.discord.enabled)
            self.log(str(exc))

    def sync_safety(self):
        self.safety_checkbox.blockSignals(True)
        self.safety_checkbox.setChecked(self.workflow.safety_enabled)
        self.safety_checkbox.blockSignals(False)

    def set_safety(self, enabled):
        self.workflow.safety_enabled = enabled
        self.changed()

    def changed(self):
        self.dirty = True
        self.update_document_status()

    def update_document_status(self):
        name = Path(self.path).name if self.path else "Nouveau document"
        self.setWindowTitle(f"Windows Macro Studio • {name}{' *' if self.dirty else ''}")
        state = "Modifications non enregistrées" if self.dirty else "Enregistré" if self.path else "Première sauvegarde : choisissez un nom"
        popups = f" · Mode popups actif ({sum(r.enabled for r in self.workflow.popups.rules)} règle(s))" if self.workflow.popups.enabled else ""
        self.file_label.setText(f"{name} · {state}{popups}")
        self.file_label.setToolTip(str(self.path or ""))

    def show_launcher(self, checked=False, *, initial=False):
        if self.worker is not None or self.picking_region:
            return False
        if not initial and not self.confirm_discard():
            return False
        while True:
            dialog = LaunchDialog(self.library_store, self)
            dialog.renamed.connect(self.document_renamed)
            if dialog.exec() != QDialog.Accepted:
                return False
            if dialog.choice == "open":
                if self.open_path(dialog.selected_path):
                    return True
            elif dialog.choice in ("new_workflow", "new_sequence"):
                self.set_document(Workflow(), document_format="sequence" if dialog.choice == "new_sequence" else "workflow")
                self.tabs.setCurrentIndex(1 if dialog.choice == "new_workflow" else 0)
                return True

    def open_path(self, path):
        try:
            workflow = load_workflow(path)
            kind = document_type(path)
            self.set_document(workflow, str(Path(path).resolve()), document_format="sequence" if kind == "Séquence" else "workflow")
            self.tabs.setCurrentIndex(0 if kind == "Séquence" else 1)
            self.log("Document chargé. Enregistrer ou Ctrl+S utilisera ce fichier.")
            return True
        except (OSError, ValueError, TypeError) as exc:
            QMessageBox.warning(self, "Ouverture impossible", str(exc))
            return False

    def rename_sequence(self):
        if self.worker is not None or self.picking_region:
            return
        module = self.workflow.get(self.current_module)
        name, ok = QInputDialog.getText(self, "Renommer la séquence", "Nouveau nom :", text=module.name)
        if not ok:
            return
        name = name.strip()
        if not name or len(name) > 120:
            QMessageBox.warning(self, "Nom invalide", "Choisissez un nom de 1 à 120 caractères.")
            return
        module.name = name
        self.refresh_modules()
        self.workflow_panel.refresh()
        self.changed()

    def document_renamed(self, old_path, new_path):
        if self.path and Path(self.path).resolve() == Path(old_path).resolve():
            self.path = new_path
            self.update_document_status()

    def rename_current_file(self):
        if self.worker is not None or self.picking_region:
            return
        if not self.path:
            self.save_file()
            return
        old_path = self.path
        name, ok = QInputDialog.getText(self, "Renommer le fichier", "Nouveau nom :", text=Path(old_path).stem)
        if not ok:
            return
        try:
            new_path = self.library_store.rename(old_path, name)
            self.document_renamed(old_path, new_path)
            self.log("Fichier renommé. Enregistrer utilisera désormais le nouveau nom.")
        except (OSError, ValueError) as exc:
            QMessageBox.warning(self, "Renommage impossible", str(exc))

    def refresh(self, index=None):
        if index is None:
            index = self.sequence.currentRow()
        self.sequence.blockSignals(True)
        self.sequence.clear()
        for n, action in enumerate(self.actions, 1):
            detail = action.summary()
            self.sequence.addItem(f"{n:02}  {LABELS[action.kind]}  ·  {detail[:65]}")
        self.sequence.blockSignals(False)
        self.sequence.setCurrentRow(index)
        self.show_properties(index)
        self.statusBar().showMessage(f"{len(self.actions)} bloc(s)")

    def add_action(self, kind):
        self.actions.append(Action.create(kind))
        self.changed()
        self.refresh(len(self.actions) - 1)

    def remove(self):
        index = self.sequence.currentRow()
        if index >= 0:
            del self.actions[index]
            self.changed()
            self.refresh(min(index, len(self.actions) - 1))

    def duplicate(self):
        index = self.sequence.currentRow()
        if index >= 0:
            self.actions.insert(index + 1, copy.deepcopy(self.actions[index]))
            self.changed()
            self.refresh(index + 1)

    def move(self, offset):
        index = self.sequence.currentRow()
        target = index + offset
        if index >= 0 and 0 <= target < len(self.actions):
            self.actions[index], self.actions[target] = self.actions[target], self.actions[index]
            self.changed()
            self.refresh(target)

    def update_param(self, action, key, value):
        action.params[key] = value
        self.changed()
        index = self.sequence.currentRow()
        if index >= 0:
            self.sequence.item(index).setText(f"{index + 1:02}  {LABELS[action.kind]}  ·  {action.summary()}")

    def show_properties(self, index):
        while self.form.rowCount():
            self.form.removeRow(0)
        self.form.addRow(QLabel("PROPRIÉTÉS"))
        if not 0 <= index < len(self.actions):
            self.form.addRow(QLabel("Sélectionnez un bloc."))
            return
        action = self.actions[index]
        self.form.addRow(QLabel(LABELS[action.kind]))
        if action.kind in IMAGE_KINDS:
            self.add_image_picker(action)
        if action.kind in ("scroll", "scroll_image", "wait_image_absent"):
            self.add_scroll_picker(action)
        if action.kind in CLICK_KINDS:
            self.add_after_click_editor(action)
        for key, value in action.params.items():
            if key in ("region", "after_click"):
                continue
            if action.kind in ("scroll", "scroll_image") and action.params.get("region") and key in ("use_position", "x", "y"):
                continue
            if action.kind in IMAGE_KINDS and key in ("image", "name"):
                continue
            if key in ("use_position", "focus_click", "wait_for_appearance"):
                editor = QCheckBox({"use_position": "Utiliser X/Y", "focus_click": "Cliquer au centre avant de défiler",
                                    "wait_for_appearance": "Attendre l’apparition"}[key])
                editor.setChecked(value)
                signal = editor.toggled
            elif key == "direction":
                editor = QComboBox()
                for label, code in (("Bas", "down"), ("Haut", "up"), ("Gauche", "left"), ("Droite", "right")):
                    editor.addItem(label, code)
                editor.setCurrentIndex(editor.findData(value))
                editor.currentIndexChanged.connect(lambda i, e=editor, a=action: self.update_param(a, "direction", e.itemData(i)))
                self.form.addRow("Direction", editor)
                continue
            elif key in ("amount", "max_scrolls"):
                editor = QSpinBox()
                editor.setRange(1, 100 if key == "amount" else 200)
                editor.setValue(value)
                signal = editor.valueChanged
            elif key in ("x", "y"):
                editor = QSpinBox()
                editor.setRange(-100000, 100000)
                editor.setValue(value)
                signal = editor.valueChanged
            elif key in ("seconds", "threshold", "timeout", "pause", "interval", "absent_for"):
                editor = QDoubleSpinBox()
                bounds = {"threshold": (.5, 1), "pause": (.05, 10), "interval": (.05, 10),
                          "absent_for": (0, 30), "seconds": (0, 86400),
                          "timeout": (0, 86400 if action.kind == "wait_image_absent" else 300)}
                editor.setRange(*bounds[key])
                editor.setDecimals(3)
                editor.setSingleStep(0.01 if key == "threshold" else 1)
                editor.setSuffix("" if key == "threshold" else " s")
                editor.setValue(value)
                signal = editor.valueChanged
            elif key == "button":
                editor = QComboBox()
                for label, code in (("Gauche", "left"), ("Droit", "right"), ("Milieu (molette)", "middle")):
                    editor.addItem(label, code)
                editor.setCurrentIndex(editor.findData(value))
                editor.currentIndexChanged.connect(lambda i, e=editor, a=action: self.update_param(a, "button", e.itemData(i)))
                self.form.addRow("Bouton souris", editor)
                continue
            elif key == "occurrence":
                editor = QComboBox()
                for label, code in (("Une seule correspondance", "unique"), ("Première (depuis le haut)", "first"), ("Dernière (depuis le bas)", "last")):
                    editor.addItem(label, code)
                editor.setCurrentIndex(editor.findData(value))
                editor.currentIndexChanged.connect(lambda i, e=editor, a=action: self.update_param(a, "occurrence", e.itemData(i)))
                self.form.addRow("Si plusieurs boutons", editor)
                continue
            elif key == "text":
                editor = QPlainTextEdit(value)
                editor.textChanged.connect(lambda a=action, e=editor: self.update_param(a, "text", e.toPlainText()))
                self.form.addRow("Texte", editor)
                continue
            elif key == "keys":
                editor = QLineEdit(format_keys(value))
                editor.setReadOnly(True)
                editor.setObjectName("captured_keys")
                self.form.addRow("Touches", editor)
                button = BlockButton("Capturer une touche ou un raccourci…")
                button.setObjectName("capture_keys")
                button.clicked.connect(lambda checked=False, a=action: self.capture_keys(a))
                self.form.addRow(button)
                continue
            else:
                editor = QLineEdit(value)
                signal = editor.textChanged
            editor.setObjectName(f"param_{key}")
            signal.connect(lambda v, a=action, k=key: self.update_param(a, k, v))
            self.form.addRow({"x": "X (écran)", "y": "Y (écran)", "seconds": "Durée",
                              "button": "Bouton", "keys": "Touches", "threshold": "Seuil (0 à 1)",
                              "timeout": "Délai maximal", "amount": "Crans par défilement",
                              "max_scrolls": "Défilements maximum", "pause": "Pause après défilement",
                              "use_position": "Position manuelle", "focus_click": "Activer le panneau",
                              "interval": "Vérifier toutes les", "absent_for": "Confirmer l’absence pendant",
                              "wait_for_appearance": "Apparition préalable"}[key], editor)
        if action.kind in IMAGE_KINDS and action.kind != "wait_image_absent":
            help_label = QLabel("Importez une capture recadrée du bouton.\n"
                                "Même taille, même zoom et même apparence à l’écran.\n"
                                "Seuil conseillé : 0,90. Choisissez quelle correspondance cliquer.\n"
                                "L’éditeur se réduit pendant la recherche.")
            help_label.setWordWrap(True)
            self.form.addRow(help_label)
        if action.kind == "wait_image_absent":
            help_label = QLabel("Choisissez une image fixe du message Chargement ou En attente. "
                                "Tant qu’elle est visible, le workflow attend. Il reprend après une absence "
                                "continue de 1 seconde par défaut, sans clic ni saisie. Si elle revient, la confirmation recommence. "
                                "Si l’indicateur apparaît avec retard, cochez Apparition préalable. "
                                "Au délai maximal, la séquence s’arrête. F8 pour interrompre.")
            help_label.setWordWrap(True)
            self.form.addRow(help_label)
        if action.kind in ("scroll", "scroll_image"):
            help_label = QLabel("Choisissez le panneau gauche, droit ou central avec Choisir le panneau. "
                                "La souris sera replacée dans cette zone avant chaque défilement. "
                                "Sans zone, utilisez la position manuelle ou placez le pointeur pendant le délai de départ. "
                                "Activer le panneau envoie un clic au centre : choisissez une zone vide si vous utilisez cette option.")
            help_label.setWordWrap(True)
            self.form.addRow(help_label)
            if action.kind == "scroll_image":
                note = QLabel("Observe, défile, attend, puis cherche à nouveau. Clique dès que l’image est visible. "
                              "S’arrête à la limite de défilements ou au délai maximal. F8 pour interrompre.")
                note.setWordWrap(True)
                self.form.addRow(note)
        if action.kind == "keyboard":
            note = QLabel("Cliquez sur Capturer, appuyez sur les touches voulues, puis relâchez-les. "
                          "F8 reste réservé à l’arrêt global. Aucun nom de touche à saisir.")
            note.setWordWrap(True)
            self.form.addRow(note)

    def capture_keys(self, action):
        dialog = KeyCaptureDialog(self)
        if dialog.exec() == QDialog.Accepted and dialog.value:
            self.update_param(action, "keys", dialog.value)
            self.refresh()

    def choose_popup_region(self, identifier, purpose):
        if self.worker is not None or self.picking_region:
            return
        rule = next(r for r in self.workflow.popups.rules if r.id == identifier)
        self.picking_region = True
        self._picker_was_maximized = self.isMaximized()
        self.centralWidget().setEnabled(False)
        self.showMinimized()
        QTimer.singleShot(250, lambda: self.show_popup_picker(rule, purpose))

    def choose_report_region(self):
        if self.worker is not None or self.picking_region:
            return
        self.picking_region = True
        self._picker_was_maximized = self.isMaximized()
        self.centralWidget().setEnabled(False)
        self.showMinimized()
        QTimer.singleShot(250, self.show_report_picker)

    def show_report_picker(self):
        try:
            self.region_picker = RegionPicker(message="Encadrez le texte à compter pour le compte rendu · Échap pour annuler")
            self.region_picker.selected.connect(self.apply_report_region)
            self.region_picker.cancelled.connect(self.restore_after_picker)
            self.region_picker.show()
            self.region_picker.raise_()
            self.region_picker.activateWindow()
            self.region_picker.setFocus()
        except Exception as exc:
            self.restore_after_picker()
            self.log(str(exc))

    def apply_report_region(self, region):
        self.workflow.report.region = dict(region)
        self.report_panel.refresh()
        self.changed()
        self.restore_after_picker()

    def test_report_ocr(self):
        if self.worker is not None or self.picking_region:
            return
        region = self.workflow.report.region
        if not region:
            self.report_panel.preview.setText("Sélectionnez d’abord une zone à lire.")
            return
        self.picking_region = True
        self._picker_was_maximized = self.isMaximized()
        self.centralWidget().setEnabled(False)
        self.report_panel.preview.setText("Lecture OCR en cours…")
        self.showMinimized()
        QTimer.singleShot(350, lambda: self.reports.preview(dict(region)))

    def report_preview_done(self, text, problem):
        self.restore_after_picker()
        self.report_panel.preview.setText(problem or "Texte lu (sans comptage) : " + (text[:1200] or "aucun texte reconnu"))

    def show_popup_picker(self, rule, purpose):
        try:
            self.region_picker = RegionPicker(message="Encadrez la zone à cliquer : le clic sera au centre · Échap pour annuler"
                if purpose == "point" else "Encadrez la zone de détection du popup · Échap pour annuler")
            self.region_picker.selected.connect(lambda region: self.apply_popup_region(rule, purpose, region))
            self.region_picker.cancelled.connect(self.restore_after_picker)
            self.region_picker.show()
            self.region_picker.raise_()
            self.region_picker.activateWindow()
            self.region_picker.setFocus()
        except Exception as exc:
            self.restore_after_picker()
            QMessageBox.warning(self, "Sélection impossible", str(exc))

    def apply_popup_region(self, rule, purpose, region):
        if purpose == "point":
            rule.x, rule.y = region["left"] + region["width"] // 2, region["top"] + region["height"] // 2
            rule.point_selected = True
        else:
            rule.region = dict(region)
        self.popup_panel.refresh()
        self.changed()
        self.restore_after_picker()

    def add_image_picker(self, action):
        choose = BlockButton("Choisir l’image à surveiller…" if action.kind == "wait_image_absent" else "Choisir l’image du bouton…")
        choose.clicked.connect(lambda checked=False, a=action: self.choose_image(a))
        self.form.addRow(choose)
        name_label = QLabel(action.params["name"] or "Aucune image choisie")
        name_label.setWordWrap(True)
        self.form.addRow(name_label)
        if action.params["image"]:
            preview = QLabel()
            pixmap = QPixmap()
            pixmap.loadFromData(base64.b64decode(action.params["image"]))
            preview.setPixmap(pixmap.scaled(230, 130, Qt.KeepAspectRatio, Qt.SmoothTransformation))
            self.form.addRow(preview)

    def add_after_click_editor(self, action):
        config = action.params.get("after_click") or copy.deepcopy(AFTER_CLICK_DEFAULTS)
        group = QGroupBox("Attendre le chargement")
        group.setToolTip("Attendre un chargement après le clic")
        group.setObjectName("after_click_group")
        group.setCheckable(True)
        group.setChecked(config["enabled"])
        layout = QVBoxLayout(group)
        body = QWidget()
        form = QFormLayout(body)
        configure_form(form)
        form.setContentsMargins(4, 8, 4, 4)
        form.setSizeConstraint(QLayout.SetMinimumSize)
        choose = BlockButton("Choisir l’image du chargement…")
        choose.clicked.connect(lambda checked=False: self.choose_image(action, after_click=True))
        form.addRow(choose)
        label = QLabel(config["name"] or "Aucune image de chargement choisie")
        label.setWordWrap(True)
        form.addRow(label)
        if config["image"]:
            pixmap = QPixmap()
            pixmap.loadFromData(base64.b64decode(config["image"]))
            preview = QLabel()
            preview.setPixmap(pixmap.scaled(200, 80, Qt.KeepAspectRatio, Qt.SmoothTransformation))
            form.addRow(preview)
        for key, text, low, high in (("appearance_timeout", "Détecter pendant", 0, 60),
            ("timeout", "Attendre au maximum", 0, 86400), ("absent_for", "Confirmer l’absence", 0, 30),
            ("interval", "Vérifier toutes les", .05, 10), ("threshold", "Seuil", .5, 1)):
            editor = QDoubleSpinBox()
            editor.setObjectName(f"after_click_{key}")
            editor.setRange(low, high)
            editor.setDecimals(2)
            editor.setSingleStep(.05 if key in ("threshold", "interval") else .5)
            editor.setSuffix("" if key == "threshold" else " s")
            editor.setValue(config[key])
            editor.valueChanged.connect(lambda value, k=key: self.set_after_click_field(action, config, k, value))
            form.addRow(text, editor)
        zone = BlockButton("Choisir la zone du chargement…")
        zone.clicked.connect(lambda checked=False: self.choose_scroll_region(action, after_click=True))
        form.addRow(zone)
        region = config["region"]
        zone_label = QLabel(f"Zone : {region['width']} × {region['height']} px" if region else "Surveillance : tout l’écran")
        form.addRow(zone_label)
        if region:
            clear = QPushButton("Surveiller tout l’écran")
            clear.clicked.connect(lambda checked=False: self.clear_after_click_region(action))
            form.addRow(clear)
        note = QLabel("Si l’image apparaît après le clic, attendre sa disparition. "
                      "Si elle n’apparaît pas pendant le délai de détection, continuer. "
                      "Si elle reste bloquée au-delà du délai maximal, arrêter la séquence. F8 pour interrompre.")
        note.setWordWrap(True)
        form.addRow(note)
        layout.addWidget(body)
        body.setVisible(config["enabled"])
        group.toggled.connect(body.setVisible)
        group.toggled.connect(lambda enabled: self.set_after_click_field(action, config, "enabled", enabled))
        self.form.addRow(group)

    def set_after_click_field(self, action, config, key, value):
        config[key] = value
        action.params["after_click"] = config
        self.changed()

    def clear_after_click_region(self, action):
        action.params["after_click"]["region"] = None
        self.changed()
        self.refresh()

    def add_scroll_picker(self, action):
        button = BlockButton("Choisir la zone de surveillance…" if action.kind == "wait_image_absent" else "Choisir le panneau à faire défiler…")
        button.clicked.connect(lambda checked=False, a=action: self.choose_scroll_region(a))
        self.form.addRow(button)
        region = action.params.get("region")
        label = QLabel((f"Panneau : {region['width']} × {region['height']} px · "
                        f"origine ({region['left']}, {region['top']})") if region else "Aucun panneau sélectionné")
        label.setWordWrap(True)
        self.form.addRow(label)
        if region:
            reset = QPushButton("Effacer le panneau sélectionné")
            reset.clicked.connect(lambda checked=False, a=action: self.clear_scroll_region(a))
            self.form.addRow(reset)
            if action.kind in ("scroll_image", "wait_image_absent"):
                note = QLabel("L’image sera recherchée uniquement dans ce panneau.")
                note.setWordWrap(True)
                self.form.addRow(note)

    def clear_scroll_region(self, action):
        action.params["region"] = None
        if action.kind != "wait_image_absent":
            action.params["use_position"] = False
        self.changed()
        self.refresh()

    def choose_scroll_region(self, action, after_click=False):
        if self.worker is not None or self.picking_region:
            return
        self.picking_region = True
        self._picker_was_maximized = self.isMaximized()
        self.centralWidget().setEnabled(False)
        self.showMinimized()
        QTimer.singleShot(250, lambda: self.show_region_picker(action, after_click))

    def show_region_picker(self, action, after_click=False):
        try:
            self.region_picker = RegionPicker(message="Encadrez la zone où l’image sera surveillée · Échap pour annuler"
                                               if after_click or action.kind == "wait_image_absent" else None)
            self.region_picker.selected.connect(lambda region: self.apply_scroll_region(action, region, after_click))
            self.region_picker.cancelled.connect(self.restore_after_picker)
            self.region_picker.show()
            self.region_picker.raise_()
            self.region_picker.activateWindow()
            self.region_picker.setFocus()
        except Exception as exc:
            self.restore_after_picker()
            QMessageBox.warning(self, "Sélection du panneau impossible", str(exc))

    def apply_scroll_region(self, action, region, after_click=False):
        target = action.params["after_click"] if after_click else action.params
        target["region"] = dict(region)
        if not after_click and action.kind != "wait_image_absent":
            action.params.update(use_position=True, x=region["left"] + region["width"] // 2,
                                 y=region["top"] + region["height"] // 2)
        self.changed()
        self.refresh()
        self.restore_after_picker()

    def restore_after_picker(self):
        if self.region_picker:
            self.region_picker.deleteLater()
            self.region_picker = None
        self.picking_region = False
        self.centralWidget().setEnabled(True)
        if getattr(self, "_picker_was_maximized", False):
            self.showMaximized()
        else:
            self.showNormal()
        self.activateWindow()

    def choose_image(self, action, after_click=False):
        path, _ = QFileDialog.getOpenFileName(self, "Image à surveiller (capture recadrée)" if after_click or action.kind == "wait_image_absent" else "Image du bouton (capture recadrée)", "",
                                             "Images (*.png *.jpg *.jpeg *.bmp)")
        if not path:
            return
        try:
            reader = QImageReader(path)
            size = reader.size()
            if not (8 <= size.width() <= 1024 and 8 <= size.height() <= 1024):
                raise ValueError("Recadrez le bouton : entre 8 et 1024 pixels par dimension.")
            image = reader.read()
            if image.isNull():
                raise ValueError("Impossible de lire cette image.")
            data = QByteArray()
            buffer = QBuffer(data)
            buffer.open(QIODevice.WriteOnly)
            if not image.save(buffer, "PNG"):
                raise ValueError("Impossible d’importer cette image.")
            buffer.close()
            encoded = base64.b64encode(bytes(data)).decode("ascii")
            from .vision import decode_template
            decode_template(encoded)
            target = action.params["after_click"] if after_click else action.params
            target.update(image=encoded, name=Path(path).name[:256])
            self.changed()
            self.refresh()
        except (ValueError, OSError) as exc:
            QMessageBox.warning(self, "Image invalide", str(exc))

    def confirm_discard(self):
        if not self.dirty:
            return True
        answer = QMessageBox.question(self, "Modifications", "Enregistrer les modifications ?",
            QMessageBox.Save | QMessageBox.Discard | QMessageBox.Cancel, QMessageBox.Save)
        return self.save_file() if answer == QMessageBox.Save else answer == QMessageBox.Discard

    def new(self):
        if self.confirm_discard():
            self.set_document(Workflow())

    def open_file(self):
        if not self.confirm_discard():
            return
        path, _ = QFileDialog.getOpenFileName(self, "Ouvrir un workflow ou une séquence", "", "Workflow / Séquence JSON (*.json)")
        if path:
            self.open_path(path)

    def save_as(self):
        return self.save_file(force_dialog=True)

    def save_file(self, checked=False, *, force_dialog=False):
        if self.worker is not None or self.picking_region:
            return False
        path = None if force_dialog else self.path
        sequence = (self.document_format == "sequence" and len(self.workflow.modules) == 1
                    and self.workflow.modules[0].repeat == 1 and self.workflow.modules[0].next_id is None
                      and not self.workflow.popups.enabled and not self.workflow.popups.rules and self.workflow.safety_enabled
                      and not self.workflow.report.enabled and not self.workflow.report.terms and self.workflow.report.region is None
                      and self.workflow.report.at == '19:00' and self.workflow.report.interval == 5
                      and not self.workflow.image_start.enabled and not self.workflow.image_start.image
                      and self.workflow.image_start.region is None and self.workflow.image_start.interval == 3
                      and self.workflow.image_start.threshold == .9 and self.workflow.loop_count == 2
                      and self.workflow.modules[0].image_start == type(self.workflow.modules[0].image_start)()
                      and not self.workflow.modules[0].condition.image)
        if not path:
            path, _ = QFileDialog.getSaveFileName(self, "Enregistrer la séquence" if sequence else "Enregistrer le workflow complet",
                  self.path or str(prepare_workflow_folder() / ("sequence.json" if sequence else "workflow.json")), "Document JSON (*.json)")
        if not path:
            return False

        if not path.lower().endswith(".json"):
            path += ".json"
        try:
            if sequence:
                save(path, self.workflow.modules[0].actions, name=self.workflow.modules[0].name)
            else:
                save_workflow(path, self.workflow)
            self.path, self.dirty = path, False
            self.document_format = "sequence" if sequence else "workflow"
            self.library_store.remember(path)
            self.update_document_status()
            self.log(f"{'Séquence' if sequence else 'Workflow'} enregistré : {path} · {len(self.workflow.modules)} module(s).")
            return True
        except (OSError, ValueError) as exc:
            QMessageBox.warning(self, "Enregistrement impossible", str(exc))
            return False

    def export_sequence(self):
        path, _ = QFileDialog.getSaveFileName(self, "Exporter uniquement la séquence active",
                                             "sequence.json", "Macro JSON (*.json)")
        if path:
            if not path.lower().endswith(".json"):
                path += ".json"
            try:
                module = self.workflow.get(self.current_module)
                if module.condition.image or module.image_start != type(module.image_start)() or module.repeat != 1:
                    exported = copy.deepcopy(module)
                    exported.next_id = None
                    save_workflow(path, Workflow([exported], entry=exported.id))
                else:
                    save(path, self.actions, name=module.name)
                self.library_store.remember(path)
                self.log("Séquence active exportée indépendamment du workflow.")
            except (OSError, ValueError) as exc:
                QMessageBox.warning(self, "Export impossible", str(exc))

    def set_running(self, running):
        self.start_button.setEnabled(not running)
        self.stop_button.setEnabled(running)
        self.library.setEnabled(not running)
        self.properties.setEnabled(not running)
        self.module_selector.setEnabled(not running)
        self.workflow_panel.setEnabled(not running)
        self.popup_panel.setEnabled(not running)
        self.safety_checkbox.setEnabled(not running)
        self.discord_panel.setEnabled(not running)
        self.report_panel.setEnabled(not running)
        self.tabs.tabBar().setEnabled(not running)
        self.save_shortcut.setEnabled(not running)
        self.save_as_shortcut.setEnabled(not running)
        for button in self.edit_buttons:
            button.setEnabled(not running)

    def start(self, checked=False, *, force_workflow=False):
        if self.worker is not None or self.picking_region:
            return
        try:
            if force_workflow or self.tabs.currentIndex() != 0:
                actions, self.run_mapping = self.workflow.compile()
                names = " → ".join(m.name for m in self.workflow.chain())
                self.log(f"Workflow : {names}")
            else:
                actions, self.run_mapping = self.workflow.compile(module_id=self.current_module)
            if not actions:
                self.log("Aucune action à exécuter dans cette séquence ou cette chaîne.")
                return
        except ValueError as exc:
            QMessageBox.warning(self, "Bloc invalide", str(exc))
            return
        whole_workflow = force_workflow or self.tabs.currentIndex() != 0
        self.run_cycles = self.workflow.loop_count if whole_workflow and self.workflow.is_loop() else 1
        self.workflow_cycle = 1
        conditions = self.workflow.conditions(self.run_mapping)
        self.worker = Worker(actions, popups=self.workflow.popups, safety_enabled=self.workflow.safety_enabled,
                             cycles=self.run_cycles, conditions=conditions)
        self.last_result = "En cours"
        self.discord.begin()
        self.notification_position = "Avant la première action"
        self.last_module_pass = None
        self.worker.message.connect(self.log)
        self.worker.progress.connect(self.execution_progress)
        self.worker.cycle_progress.connect(self.execution_cycle)
        self.worker.condition_progress.connect(self.condition_waiting)
        self.worker.result.connect(self.execution_result)
        self.worker.pause_state.connect(self.pause_state_changed)
        self.worker.finished.connect(self.finished)
        self.set_running(True)
        self.run_widget.move(self.screen().availableGeometry().right() - self.run_widget.width() - 15,
                             self.screen().availableGeometry().top() + 20)
        self.run_widget.begin(self.worker.control, len(actions) * (self.run_cycles or 1))
        self.worker.ignored_windows = (int(self.run_widget.winId()),)
        self.worker.blocked_windows = (int(self.winId()),)
        if conditions or self.workflow.popups.enabled or any(a.kind in (*IMAGE_KINDS, "scroll") or (a.params.get("after_click") or {}).get("enabled") for a in actions):
            self.log("Éditeur réduit pour laisser les boutons cibles visibles. F8 pour arrêter.")
            self.showMinimized()
        try:
            self.reports.begin(self.workflow.report, Path(self.path).stem if self.path else 'Workflow sans nom', self.worker.control)
        except ValueError as exc:
            self.reports.end()
            self.log(str(exc))
        self.worker.start()
        if self.discord.enabled and self.discord.remote.config.enabled:
            self.discord.dispatch(self.discord.url, '▶️ Workflow démarré\n' + self.notification_context())

    def discord_command(self, session, action, request_id):
        remote = self.discord.remote
        if (not self.discord.enabled or not remote.config.enabled or session != remote.session
                or request_id not in remote.pending or remote.pending[request_id].done()
                or not self.worker or not self.worker.isRunning() or self.worker.control.is_set()):
            remote.answer(request_id, 'Cette exécution est terminée, désactivée ou la demande a expiré.')
            return
        control = self.worker.control
        if action == 'stop':
            self.stop()
            result = 'Arrêt demandé. Le workflow va s’interrompre.'
        elif action == 'resume':
            if not control.paused:
                result = 'Le workflow est déjà en cours.'
            elif (control.safety_enabled and control.guard and control.armed
                    and control.guard.reason()):
                result = 'Reprise refusée : la fenêtre cible doit être rétablie sur le PC.'
            else:
                control.resume()
                result = 'Workflow repris.' if not control.paused else 'La sécurité maintient la pause. Vérifiez le PC.'
        else:
            result = 'Commande inconnue.'
        self.log('Discord : ' + result)
        remote.answer(request_id, result)

    def condition_waiting(self, index, waiting, message):
        self.run_widget.condition_message = message if waiting else ''
        if not self.run_widget.paused:
            self.run_widget.state.setText(message if waiting else 'En cours')

    def pause_run(self):
        if self.worker:
            self.worker.control.pause("Pause manuelle — vérifiez l’écran puis Reprendre.")

    def resume_run(self):
        if self.worker:
            self.worker.control.resume()

    def pause_state_changed(self, paused, reason):
        self.log(reason)
        self.run_widget.set_paused(paused, reason)
        if not paused:
            self.discord.pause_notified = False
        elif reason.startswith("Sécurité"):
            self.discord.alert('safety', self.notification_context(), 'Vérifiez l’écran puis utilisez Reprendre.')

    def notification_context(self):
        name = Path(self.path).stem if self.path else "Workflow sans nom"
        return f"Document : {name}\n{self.notification_position}"

    def execution_result(self, result):
        self.discord.end()
        self.reports.end()
        self.last_result = result
        self.log(result)
        self.run_widget.finish(result)
        if result.startswith("Erreur"):
            self.discord.alert('error', self.notification_context(), 'Consultez le journal de Macro Studio pour le détail de l’erreur.')
        elif result == "Arrêté":
            self.discord.alert('stop', self.notification_context(), 'Exécution interrompue par Arrêter ou F8.')

    def execution_cycle(self, current, total):
        self.workflow_cycle = current
        self.run_widget.workflow_cycle = (current, total)
        if current > 1:
            self.last_module_pass = None
            self.run_widget.module_id = None
        if total != 1:
            self.log(f'Tour du workflow : {current}/{total or "∞"} · F8 pour arrêter.')

    def execution_progress(self, index):
        identifier, row, iteration = self.run_mapping[index]
        module = self.workflow.get(identifier)
        self.notification_position = f"Tour {self.workflow_cycle}/{self.run_cycles or '∞'} · Module : {module.name} · répétition {iteration}/{module.repeat} · action {row + 1}/{len(module.actions)}"
        if self.last_module_pass != (identifier, iteration):
            self.log(f"Module : {module.name} · répétition {iteration}/{module.repeat}")
            self.last_module_pass = identifier, iteration
        self.workflow_panel.canvas.active_id = identifier
        self.workflow_panel.canvas.active_repeat = iteration
        self.workflow_panel.canvas.scene().update()
        self.module_selector.setCurrentIndex(self.module_selector.findData(identifier))
        self.sequence.setCurrentRow(row)
        display_index = (self.workflow_cycle - 1) * len(self.run_mapping) + index if self.run_cycles else index
        self.run_widget.update_progress(identifier, module.name, iteration, module.repeat, row, len(module.actions), display_index)

    def stop(self):
        if self.worker:
            self.worker.stop_event.set()
            self.log("Arrêt demandé.")

    def finished(self):
        worker, self.worker = self.worker, None
        worker.deleteLater()
        self.set_running(False)
        self.workflow_panel.canvas.active_id = None
        self.workflow_panel.canvas.active_repeat = None
        self.workflow_panel.canvas.scene().update()
        self.run_widget.finish(self.last_result)
        # Keep the target application focused; restoring here can steal the tail
        # of a queued text entry. The user can reopen the editor from the taskbar.

    def closeEvent(self, event):
        if self.picking_region:
            event.ignore()
        elif self.worker:
            self.stop()
            self.log("Attendez la fin de l’arrêt puis fermez la fenêtre.")
            event.ignore()
        elif self.confirm_discard():
            self.reports.close()
            self.discord.remote.close()
            self.run_widget.close()
            event.accept()
        else:
            event.ignore()

def main():
    if sys.platform == 'win32':
        import ctypes
        ctypes.windll.shell32.SetCurrentProcessExplicitAppUserModelID(APP_ID)
    app = QApplication(sys.argv)
    app.setWindowIcon(QIcon(str(Path(__file__).parent / 'icons' / 'app.ico')))
    app.setStyle("Fusion")
    app.setStyleSheet(STYLE)
    app.setQuitOnLastWindowClosed(False)
    window = MainWindow()
    available = app.primaryScreen().availableGeometry()
    window.resize(min(1400, available.width() - 24), min(880, available.height() - 24))
    opened = len(sys.argv) > 1 and Path(sys.argv[1]).is_file() and window.open_path(sys.argv[1])
    if not opened and not window.show_launcher(initial=True):
        return
    window.showMaximized()
    app.setQuitOnLastWindowClosed(True)
    if window.tabs.currentIndex() == 1:
        QTimer.singleShot(0, window.workflow_panel.fit)
    sys.exit(app.exec())
