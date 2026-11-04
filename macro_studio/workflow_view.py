"""Native Qt node canvas: movable modules, clickable ports, zoom and pan."""
import copy
import math
import base64
from pathlib import Path
from PySide6.QtCore import Qt, QRectF, QPointF, Signal, QTimer
from PySide6.QtGui import QColor, QPen, QBrush, QPainter, QPainterPath, QFont, QImageReader, QPixmap, QIcon
from PySide6.QtWidgets import (QGraphicsView, QGraphicsScene, QGraphicsObject,
    QGraphicsItem, QGraphicsEllipseItem, QGraphicsPathItem, QWidget, QVBoxLayout,
    QHBoxLayout, QPushButton, QLabel, QInputDialog, QFileDialog, QMessageBox, QSpinBox, QGraphicsProxyWidget, QSlider)
from .workflow import Module, load_workflow
from .ui_style import FlowLayout
from .conditions import ImageCondition

class Port(QGraphicsEllipseItem):
    def __init__(self, node, output):
        super().__init__(-8, -8, 16, 16, node)
        self.node, self.output = node, output
        self.setPos(260 if output else 0, 69)
        self.setBrush(QColor("#70b9ff" if output else "#8ce5c2"))
        self.setPen(QPen(QColor("#111722"), 3))
        self.setCursor(Qt.PointingHandCursor)
        self.setToolTip("Sortie : cliquez, puis cliquez sur l’entrée du module suivant" if output else "Entrée du module")

    def mousePressEvent(self, event):
        if event.button() == Qt.LeftButton:
            canvas, identifier, output = self.node.canvas, self.node.module.id, self.output
            # Rebuilding the scene must happen after this port's mouse event.
            QTimer.singleShot(0, lambda: canvas.port_clicked(identifier, output))
            event.accept()
        else:
            super().mousePressEvent(event)

class Node(QGraphicsObject):
    def __init__(self, module, canvas):
        super().__init__()
        self.module, self.canvas = module, canvas
        self.setFlags(QGraphicsItem.ItemIsMovable | QGraphicsItem.ItemIsSelectable |
                      QGraphicsItem.ItemSendsGeometryChanges)
        self.setPos(module.x, module.y)
        self.input = Port(self, False)
        self.output = Port(self, True)
        self.repeat_editor = self.controls_proxy = None
        self.condition_import = self.condition_status = self.condition_clear = None
        self.setAcceptHoverEvents(True)
        if canvas.eager_controls:
            self.ensure_controls()
        self.setToolTip("Glissez pour déplacer · Double-cliquez pour modifier la séquence")

    def ensure_controls(self):
        if self.controls_proxy is not None:
            return
        module = self.module
        controls = QWidget()
        controls.setStyleSheet("QWidget { background:#202c3d; color:#dce9f8; }")
        stack = QVBoxLayout(controls)
        stack.setContentsMargins(0, 0, 0, 0)
        stack.setSpacing(4)
        row = QHBoxLayout()
        row.setSpacing(10)
        row.addWidget(QLabel("Répéter"))
        self.repeat_editor = QSpinBox()
        self.repeat_editor.setObjectName(f"repeat_{module.id}")
        self.repeat_editor.setAccessibleName(f"Répétitions de {module.name}")
        self.repeat_editor.setRange(1, 1000)
        self.repeat_editor.setSuffix(" fois")
        self.repeat_editor.setFixedWidth(130)
        self.repeat_editor.setValue(module.repeat)
        self.repeat_editor.valueChanged.connect(self.change_repeat)
        row.addWidget(self.repeat_editor)
        stack.addLayout(row)
        condition_row = QHBoxLayout()
        condition_row.setSpacing(6)
        condition_row.addWidget(QLabel('Condition'))
        self.condition_import = QPushButton('Importer…')
        self.condition_import.setFixedWidth(100)
        self.condition_import.setStyleSheet('padding:5px;')
        self.condition_import.setAccessibleName('Importer la condition de ' + module.name)
        self.condition_import.clicked.connect(lambda: QTimer.singleShot(0, self.choose_condition))
        condition_row.addWidget(self.condition_import)
        self.condition_status = QLabel()
        self.condition_status.setFixedWidth(18)
        self.condition_status.setStyleSheet('color:#8ce5a4; font-size:18px; font-weight:600;')
        self.condition_status.setToolTip('Le ✓ vert indique qu’une image a été importée.')
        condition_row.addWidget(self.condition_status)
        self.condition_clear = QPushButton()
        self.condition_clear.setIcon(QIcon(str(Path(__file__).parent / 'icons/trash.svg')))
        self.condition_clear.setFixedSize(26, 28)
        self.condition_clear.setStyleSheet('padding:2px;')
        self.condition_clear.setToolTip('Retirer l’image : la séquence démarrera normalement')
        self.condition_clear.setAccessibleName('Retirer la condition de ' + module.name)
        self.condition_clear.clicked.connect(self.clear_condition)
        condition_row.addWidget(self.condition_clear)
        stack.addLayout(condition_row)
        self.sync_condition()
        self.controls_proxy = QGraphicsProxyWidget(self)
        self.controls_proxy.setWidget(controls)
        self.controls_proxy.setPos(18, 100)
        self.controls_proxy.resize(224, 78)

    def sync_condition(self):
        if self.condition_import is None:
            return
        condition = self.module.condition
        present = bool(condition.image)
        self.condition_status.clear()
        self.condition_status.setAccessibleName('Image importée' if present else 'Aucune image')
        if present:
            self.condition_status.setPixmap(QPixmap(str(Path(__file__).parent / 'icons/condition-check.svg')))
        self.condition_clear.setEnabled(present)
        self.condition_import.setText('Image' if present else 'Importer…')
        self.condition_import.setToolTip(condition.name if present else 'Importer une image de top départ (facultatif)')
        icon = QIcon()
        if present:
            pixmap = QPixmap()
            pixmap.loadFromData(base64.b64decode(condition.image))
            icon = QIcon(pixmap)
        self.condition_import.setIcon(icon)

    def choose_condition(self):
        from PySide6.QtCore import QByteArray, QBuffer, QIODevice
        path, _ = QFileDialog.getOpenFileName(self.canvas, 'Condition de « ' + self.module.name + ' »', '',
                                            'Images (*.png *.jpg *.jpeg *.bmp)')
        if not path:
            return
        try:
            reader = QImageReader(path)
            size = reader.size()
            if not (8 <= size.width() <= 1024 and 8 <= size.height() <= 1024):
                raise ValueError('Recadrez l’image entre 8 et 1024 pixels par dimension.')
            image = reader.read()
            data = QByteArray()
            buffer = QBuffer(data)
            buffer.open(QIODevice.WriteOnly)
            if image.isNull() or not image.save(buffer, 'PNG'):
                raise ValueError('Image illisible.')
            condition = ImageCondition(base64.b64encode(bytes(data)).decode('ascii'), Path(path).name[:256])
            condition.validate()
            self.module.condition = condition
            self.sync_condition()
            self.update()
            self.canvas.modified.emit()
        except (ValueError, OSError) as exc:
            QMessageBox.warning(self.canvas, 'Condition invalide', str(exc))

    def clear_condition(self):
        if not self.module.condition.image:
            return
        self.module.condition = ImageCondition()
        self.sync_condition()
        self.update()
        self.canvas.modified.emit()

    def hoverEnterEvent(self, event):
        if self.canvas.transform().m11() >= .35:
            self.ensure_controls()
        super().hoverEnterEvent(event)

    def change_repeat(self, count):
        self.module.repeat = count
        self.setSelected(True)
        self.update()
        self.canvas.modified.emit()

    def boundingRect(self):
        return QRectF(-10, -3, 280, 229)

    def paint(self, painter, option, widget=None):
        active = self.canvas.active_id == self.module.id
        selected = self.isSelected() or self.canvas.pending == self.module.id
        painter.setRenderHint(QPainter.Antialiasing)
        painter.setPen(QPen(QColor("#8ce5c2" if active else "#70b9ff" if selected else "#38475c"), 2))
        painter.setBrush(QColor("#202c3d"))
        painter.drawRoundedRect(QRectF(0, 0, 260, 220), 10, 10)
        if painter.worldTransform().m11() < .15:
            return
        painter.setPen(Qt.NoPen)
        painter.setBrush(QColor("#275581" if selected else "#293f58"))
        painter.drawRoundedRect(QRectF(2, 2, 256, 34), 8, 8)
        painter.setPen(QColor("#f2f6ff"))
        painter.setFont(QFont("Segoe UI", 10, QFont.Bold))
        painter.drawText(QRectF(14, 5, 230, 26), Qt.AlignVCenter,
                         painter.fontMetrics().elidedText(self.module.name, Qt.ElideRight, 230))
        painter.setFont(QFont("Segoe UI", 9))
        painter.setPen(QColor("#aebfd5"))
        painter.drawText(18, 65, f"{len(self.module.actions)} action(s)")
        painter.drawText(18, 88, f"Passage {self.canvas.active_repeat}/{self.module.repeat}" if active else "Double-clic pour éditer")
        if self.controls_proxy is None:
            painter.drawText(18, 123, f"Répéter {self.module.repeat} fois")
            painter.setPen(QColor('#8ce5a4' if self.module.condition.image else '#aebfd5'))
            painter.drawText(18, 163, 'Condition ✓' if self.module.condition.image else 'Condition : aucune')
        painter.setPen(QColor("#8ce5c2" if self.canvas.workflow.entry == self.module.id else "#7890ac"))
        painter.drawText(18, 205, "DÉPART DU WORKFLOW" if self.canvas.workflow.entry == self.module.id else "MODULE SÉQUENCE")

    def itemChange(self, change, value):
        if change == QGraphicsItem.ItemSelectedHasChanged and value:
            self.ensure_controls()
        if change == QGraphicsItem.ItemPositionHasChanged and self.scene():
            self.module.x, self.module.y = value.x(), value.y()
            self.canvas.update_edges(self.module.id)
            self.canvas.modified.emit()
        return super().itemChange(change, value)

    def mouseDoubleClickEvent(self, event):
        self.canvas.edit_requested.emit(self.module.id)
        event.accept()

class Canvas(QGraphicsView):
    zoom_changed = Signal(float)
    modified = Signal()
    edit_requested = Signal(str)
    notice = Signal(str)

    def __init__(self, workflow):
        super().__init__()
        self.workflow = workflow
        self.nodes, self.edges = {}, []
        self.incident = {}
        self.pending = self.active_id = None
        self.active_repeat = None
        self.eager_controls = len(workflow.modules) <= 200
        self._scene = QGraphicsScene(self)
        self.setScene(self._scene)
        self._scene.setMinimumRenderSize(1)
        self.setRenderHint(QPainter.Antialiasing)
        self.setDragMode(QGraphicsView.ScrollHandDrag)
        self.setTransformationAnchor(QGraphicsView.AnchorUnderMouse)
        self.setMinimumHeight(80)
        self.rebuild()

    def rebuild(self):
        try:
            chain = self.workflow.chain()
            self.loop_source = chain[-1].id if chain and chain[-1].next_id == self.workflow.entry else None
        except ValueError:
            self.loop_source = None
        selected = self.selected_id()
        self.eager_controls = len(self.workflow.modules) <= 200
        self.pending = None
        if (len(self.nodes) == len(self.workflow.modules)
            and all(m.id in self.nodes and self.nodes[m.id].module is m for m in self.workflow.modules)
            and {(a, b) for a, b, _ in self.edges} == {(m.id, m.next_id) for m in self.workflow.modules if m.next_id}):
            for module in self.workflow.modules:
                self.nodes[module.id].sync_condition()
                editor = self.nodes[module.id].repeat_editor
                if editor:
                    editor.blockSignals(True)
                    editor.setValue(module.repeat)
                    editor.blockSignals(False)
            self._scene.update()
            self.update_edges()
            return
        self.nodes, self.edges = {}, []
        self.incident = {}
        self._scene.clear()
        for module in self.workflow.modules:
            node = Node(module, self)
            self._scene.addItem(node)
            self.nodes[module.id] = node
            node.setSelected(module.id == selected)
        for module in self.workflow.modules:
            if module.next_id:
                edge = QGraphicsPathItem()
                edge.setPen(QPen(QColor("#70b9ff"), 3))
                edge.setZValue(-1)
                edge.setToolTip("Ordre d’exécution →")
                self._scene.addItem(edge)
                self.edges.append((module.id, module.next_id, edge))
                record = self.edges[-1]
                self.incident.setdefault(module.id, []).append(record)
                self.incident.setdefault(module.next_id, []).append(record)
        self.update_edges()
        self.setSceneRect(self._scene.itemsBoundingRect().adjusted(-1000, -1000, 1000, 1000))

    def selected_id(self):
        return next((item.module.id for item in self._scene.selectedItems() if isinstance(item, Node)), None)

    def update_edges(self, identifier=None):
        for source, target, edge in self.edges if identifier is None else self.incident.get(identifier, []):
            start = self.nodes[source].pos() + QPointF(260, 69)
            end = self.nodes[target].pos() + QPointF(0, 69)
            distance = max(70, abs(end.x() - start.x()) / 2)
            path = QPainterPath(start)
            returning = source == self.loop_source and target == self.workflow.entry
            if returning:
                top = min(start.y(), end.y()) - 120
                path.cubicTo(QPointF(start.x() + 100, top), QPointF(end.x() - 100, top), end)
                edge.setPen(QPen(QColor('#f0ba76'), 3, Qt.DashLine))
                edge.setToolTip('Retour au départ — ' + ('jusqu’à arrêt (F8)' if self.workflow.loop_count == 0 else f'{self.workflow.loop_count} tours'))
            else:
                path.cubicTo(start + QPointF(distance, 0), end - QPointF(distance, 0), end)
                edge.setPen(QPen(QColor('#70b9ff'), 3))
                edge.setToolTip('Ordre d’exécution →')
            # Small arrow at the destination makes the execution direction clear.
            path.moveTo(end - QPointF(13, 6))
            path.lineTo(end)
            path.lineTo(end - QPointF(13, -6))
            edge.setPath(path)
        if identifier is not None and identifier in self.nodes:
            self.setSceneRect(self.sceneRect().united(self.nodes[identifier].sceneBoundingRect().adjusted(-500, -500, 500, 500)))

    def port_clicked(self, identifier, output):
        if output:
            self.pending = identifier
            self.notice.emit("Cliquez sur le point d’entrée à gauche du module suivant. Échap pour annuler.")
            self._scene.update()
        elif self.pending:
            try:
                self.workflow.connect(self.pending, identifier)
            except ValueError as exc:
                self.notice.emit(str(exc))
                self.pending = None
                self._scene.update()
                return
            self.rebuild()
            self.modified.emit()
            self.notice.emit('Boucle reliée : réglez les tours du workflow, ou 0 pour arrêter avec F8.' if self.workflow.is_loop()
                             else "Modules reliés. Le lien indique l’ordre d’exécution.")
        else:
            self.notice.emit("Cliquez d’abord sur la sortie à droite du module précédent.")

    def fit_nodes(self):
        self.resetTransform()
        bounds = self._scene.itemsBoundingRect().adjusted(-70, -70, 70, 70)
        self.fitInView(bounds, Qt.KeepAspectRatio)
        if self.transform().m11() > 1.3:
            self.resetTransform()
            self.centerOn(bounds.center())
        self.zoom_changed.emit(self.transform().m11())

    def set_zoom(self, value):
        value = max(.1, min(3.0, value))
        current = self.transform().m11()
        anchor = self.transformationAnchor()
        self.setTransformationAnchor(QGraphicsView.AnchorViewCenter)
        self.scale(value / current, value / current)
        self.setTransformationAnchor(anchor)
        self.zoom_changed.emit(self.transform().m11())

    def zoom_by(self, factor, under_mouse=False):
        current = self.transform().m11()
        # Fit-all can go below 10% for very large graphs. Zoom-out must not
        # accidentally enlarge that view when reaching the manual lower bound.
        if factor < 1 and current <= .1:
            return
        value = max(.1, min(3.0, current * factor))
        if under_mouse:
            self.scale(value / current, value / current)
            self.zoom_changed.emit(self.transform().m11())
        else:
            self.set_zoom(value)

    def wheelEvent(self, event):
        delta = event.angleDelta().y()
        if delta:
            self.zoom_by(1.15 if delta > 0 else 1 / 1.15, under_mouse=True)
        event.accept()

    def keyPressEvent(self, event):
        if event.key() == Qt.Key_Escape:
            self.pending = None
            self._scene.update()
            self.notice.emit("Liaison annulée.")
        else:
            super().keyPressEvent(event)

    def drawBackground(self, painter, rect):
        painter.fillRect(rect, QColor("#111721"))
        painter.setPen(QPen(QColor("#202c3b"), 1))
        zoom = max(self.transform().m11(), .000001)
        step = 32 * 2 ** max(0, math.ceil(math.log2(12 / (32 * zoom))))
        for x in range(math.floor(rect.left() / step) * step, math.ceil(rect.right()), step):
            painter.drawLine(QPointF(x, rect.top()), QPointF(x, rect.bottom()))
        for y in range(math.floor(rect.top() / step) * step, math.ceil(rect.bottom()), step):
            painter.drawLine(QPointF(rect.left(), y), QPointF(rect.right(), y))

class WorkflowPanel(QWidget):
    modified = Signal()
    edit_requested = Signal(str)
    fullscreen_requested = Signal()

    def __init__(self, workflow):
        super().__init__()
        self.workflow = workflow
        layout = QVBoxLayout(self)
        bar = FlowLayout()
        for label, callback in (("+ Séquence", self.add_module), ("Importer workflow / séquence", self.import_module),
            ("Renommer", self.rename), ("Dupliquer", self.duplicate), ("Définir départ", self.set_entry),
            ("Délier sortie", self.disconnect), ("Supprimer module", self.remove), ("Cadrer", self.fit)):
            button = QPushButton(label)
            button.clicked.connect(callback)
            bar.addWidget(button)
        layout.addLayout(bar)
        self.fullscreen_button = QPushButton('Agrandir le workflow · F11')
        self.fullscreen_button.clicked.connect(self.fullscreen_requested)
        bar.addWidget(self.fullscreen_button)
        loop_bar = QHBoxLayout()
        loop_bar.addWidget(QLabel('Boucle du workflow :'))
        self.loop_editor = QSpinBox()
        self.loop_editor.setRange(0, 10000)
        self.loop_editor.setSpecialValueText('Jusqu’à arrêt (F8)')
        self.loop_editor.setSuffix(' tours')
        self.loop_editor.setMinimumWidth(180)
        self.loop_editor.valueChanged.connect(self.change_loop_count)
        loop_bar.addWidget(self.loop_editor)
        self.loop_hint = QLabel()
        self.loop_hint.setWordWrap(True)
        loop_bar.addWidget(self.loop_hint, 1)
        layout.addLayout(loop_bar)
        self.canvas = Canvas(workflow)
        self.canvas.modified.connect(self.modified)
        self.canvas.edit_requested.connect(self.edit_requested)
        self.hint = QLabel("Déplacez les modules · Molette : zoom · Glissez le fond : déplacement · Double-clic : éditer")
        self.hint.setWordWrap(True)
        self.canvas.notice.connect(self.hint.setText)
        layout.addWidget(self.canvas, 1)
        zoom_bar = QHBoxLayout()
        zoom_bar.addWidget(QLabel("Zoom"))
        self.zoom_out = QPushButton("−")
        self.zoom_out.setObjectName('workflow_zoom_out')
        self.zoom_out.setToolTip('Dézoomer le workflow')
        self.zoom_out.clicked.connect(lambda: self.canvas.zoom_by(1 / 1.15))
        zoom_bar.addWidget(self.zoom_out)
        self.zoom_slider = QSlider(Qt.Horizontal)
        self.zoom_slider.setRange(10, 300)
        self.zoom_slider.setValue(100)
        self.zoom_slider.setMaximumWidth(240)
        self.zoom_slider.setMinimumWidth(90)
        self.zoom_slider.setToolTip('Niveau de zoom : 10 à 300 %')
        self.zoom_slider.valueChanged.connect(lambda value: self.canvas.set_zoom(value / 100))
        zoom_bar.addWidget(self.zoom_slider, 1)
        self.zoom_in = QPushButton("+")
        self.zoom_in.setObjectName('workflow_zoom_in')
        self.zoom_in.setToolTip('Zoomer le workflow')
        self.zoom_in.clicked.connect(lambda: self.canvas.zoom_by(1.15))
        zoom_bar.addWidget(self.zoom_in)
        self.zoom_label = QLabel("100 %")
        self.zoom_label.setMinimumWidth(54)
        zoom_bar.addWidget(self.zoom_label)
        self.zoom_reset = QPushButton("100 %")
        self.zoom_reset.setToolTip('Revenir à la taille réelle, autour du centre de la vue')
        self.zoom_reset.clicked.connect(lambda: self.canvas.set_zoom(1))
        zoom_bar.addWidget(self.zoom_reset)
        zoom_bar.addStretch()
        self.canvas.zoom_changed.connect(self.update_zoom)
        layout.addLayout(zoom_bar)
        layout.addWidget(self.hint)
        self.canvas.modified.connect(self.sync_loop)
        self.sync_loop()

    def sync_loop(self):
        self.loop_editor.blockSignals(True)
        self.loop_editor.setValue(self.workflow.loop_count)
        self.loop_editor.blockSignals(False)
        try:
            looping = self.workflow.is_loop()
        except ValueError:
            looping = False
        self.loop_editor.setEnabled(looping)
        self.loop_hint.setText('Retour au départ actif · 0 = jusqu’à arrêt.' if looping else 'Reliez la dernière sortie à l’entrée du module de départ.')

    def change_loop_count(self, count):
        self.workflow.loop_count = count
        self.canvas.update_edges()
        self.modified.emit()

    def update_zoom(self, value):
        percent = value * 100
        self.zoom_label.setText(f"{percent:.0f} %" if percent >= 1 else "< 1 %")
        self.zoom_slider.blockSignals(True)
        self.zoom_slider.setValue(round(percent))
        self.zoom_slider.blockSignals(False)
        self.zoom_out.setEnabled(value > .1 + 1e-8)
        self.zoom_in.setEnabled(value < 3 - 1e-8)

    def selected(self):
        identifier = self.canvas.selected_id()
        if not identifier:
            self.hint.setText("Sélectionnez d’abord un module sur le tableau.")
            return None
        return self.workflow.get(identifier)

    def refresh(self):
        self.canvas.workflow = self.workflow
        self.canvas.rebuild()
        self.sync_loop()

    def fit(self):
        self.canvas.fit_nodes()

    def add_module(self):
        name, ok = QInputDialog.getText(self, "Nouvelle séquence", "Nom du module :")
        if ok and name.strip():
            self.insert(Module(name=name.strip()[:120]))

    def insert(self, module):
        center = self.canvas.mapToScene(self.canvas.viewport().rect().center())
        module.x, module.y = center.x() - 130, center.y() - 110
        self.workflow.modules.append(module)
        self.refresh()
        self.canvas.nodes[module.id].setSelected(True)
        self.modified.emit()

    def import_module(self):
        path, _ = QFileDialog.getOpenFileName(self, "Importer un workflow complet ou une séquence", "", "Workflow / Séquence (*.json)")
        if path:
            try:
                imported = load_workflow(path)
                blank = (len(self.workflow.modules) == 1 and not self.workflow.modules[0].actions
                         and self.workflow.modules[0].name == "Ma séquence" and self.workflow.modules[0].repeat == 1
                         and self.workflow.modules[0].next_id is None
                         and not self.workflow.popups.rules and not self.workflow.popups.enabled
                         and self.workflow.safety_enabled
                         and not self.workflow.report.enabled and not self.workflow.report.terms
                         and self.workflow.report.region is None and self.workflow.report.at == '19:00'
                         and self.workflow.report.interval == 5
                         and not self.workflow.image_start.enabled and not self.workflow.image_start.image
                         and self.workflow.image_start.region is None and self.workflow.image_start.interval == 3
                         and self.workflow.image_start.threshold == .9
                         and self.workflow.loop_count == 2
                         and self.workflow.modules[0].image_start == type(self.workflow.modules[0].image_start)()
                         and not self.workflow.modules[0].condition.image
                         and (self.workflow.modules[0].x, self.workflow.modules[0].y) == (80, 80))
                modules, entry = self.workflow.import_modules(imported, replace_empty=blank)
                self.refresh()
                self.canvas.scene().clearSelection()
                self.canvas.nodes[entry].setSelected(True)
                self.modified.emit()
                self.fit()
                self.hint.setText(f"{len(modules)} module(s) importé(s), liens et répétitions conservés. "
                                  + ("Le module de départ a été restauré." if blank else
                                     "Le départ actuel est conservé. Reliez les nouveaux modules ou choisissez Définir départ."))
            except (ValueError, OSError, TypeError) as exc:
                QMessageBox.warning(self, "Import impossible", str(exc))

    def rename(self):
        module = self.selected()
        if module:
            name, ok = QInputDialog.getText(self, "Renommer", "Nom :", text=module.name)
            if ok and name.strip():
                module.name = name.strip()[:120]
                self.refresh()
                self.modified.emit()

    def duplicate(self):
        module = self.selected()
        if module:
            duplicate = Module(name=(module.name + " — copie")[:120], actions=copy.deepcopy(module.actions), repeat=module.repeat,
                               image_start=copy.deepcopy(module.image_start), condition=copy.deepcopy(module.condition))
            self.insert(duplicate)
            self.canvas.nodes[duplicate.id].setPos(module.x + 50, module.y + 250)

    def set_entry(self):
        module = self.selected()
        if module:
            self.workflow.entry = module.id
            self.refresh()
            self.modified.emit()

    def disconnect(self):
        module = self.selected()
        if module:
            module.next_id = None
            self.refresh()
            self.modified.emit()

    def remove(self):
        module = self.selected()
        if not module:
            return
        if len(self.workflow.modules) == 1:
            self.hint.setText("Conservez au moins un module.")
            return
        if QMessageBox.question(self, "Supprimer le module", f"Supprimer « {module.name} » et ses actions ?",
                                QMessageBox.Yes | QMessageBox.No, QMessageBox.No) != QMessageBox.Yes:
            return
        self.workflow.modules.remove(module)
        for other in self.workflow.modules:
            if other.next_id == module.id:
                other.next_id = None
        if self.workflow.entry == module.id:
            self.workflow.entry = self.workflow.modules[0].id
        self.refresh()
        self.modified.emit()
