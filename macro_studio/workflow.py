"""Sequence modules, linear execution links, and portable workflow persistence."""
from dataclasses import dataclass, field, asdict
import json
import math
import copy
from pathlib import Path
from uuid import uuid4
from .model import Action, load, write_payload, upgrade_action
from .popups import PopupMode, load_popup_mode
from .reporting import ReportConfig, load_report_config
from .image_start import ImageStart, load_image_start
from .conditions import ImageCondition, load_condition

@dataclass
class Module:
    name: str = "Ma séquence"
    actions: list = field(default_factory=list)
    id: str = field(default_factory=lambda: uuid4().hex)
    x: float = 80
    y: float = 80
    next_id: str | None = None
    repeat: int = 1
    image_start: ImageStart = field(default_factory=ImageStart)
    condition: ImageCondition = field(default_factory=ImageCondition)

@dataclass
class Workflow:
    modules: list = field(default_factory=lambda: [Module()])
    entry: str | None = None
    popups: PopupMode = field(default_factory=PopupMode)
    safety_enabled: bool = True
    report: ReportConfig = field(default_factory=ReportConfig)
    image_start: ImageStart = field(default_factory=ImageStart)
    loop_count: int = 2  # Used only when the chain is closed; 0 means until stopped.

    def __post_init__(self):
        if self.entry is None and self.modules:
            self.entry = self.modules[0].id

    def get(self, identifier):
        return next(m for m in self.modules if m.id == identifier)

    def validate(self, actions=True):
        if type(self.safety_enabled) is not bool:
            raise ValueError("Option de sécurité invalide.")
        self.popups.validate()
        self.report.validate()
        if type(self.loop_count) is not int or not 0 <= self.loop_count <= 10000:
            raise ValueError('Le nombre de tours doit être compris entre 1 et 10 000, ou 0 pour un arrêt manuel.')
        if not self.modules:
            raise ValueError("Un workflow doit contenir au moins un module.")
        ids = [m.id for m in self.modules]
        if any(not isinstance(i, str) or not i or len(i) > 128 for i in ids) or len(set(ids)) != len(ids):
            raise ValueError("Identifiants de modules invalides.")
        by_id = {m.id: m for m in self.modules}
        if not isinstance(self.entry, str) or self.entry not in by_id:
            raise ValueError("Module de départ invalide.")
        incoming = set()
        for module in self.modules:
            module.condition.validate()
            if type(module.repeat) is not int or not 1 <= module.repeat <= 1000:
                raise ValueError("Le nombre de répétitions doit être un entier entre 1 et 1000.")
            if not isinstance(module.name, str) or not module.name.strip() or len(module.name) > 120:
                raise ValueError("Le nom d’un module doit contenir 1 à 120 caractères.")
            if any(type(v) not in (int, float) or not math.isfinite(v) for v in (module.x, module.y)):
                raise ValueError("Position de module invalide.")
            if module.next_id is not None:
                if not isinstance(module.next_id, str) or module.next_id not in by_id or module.next_id in incoming:
                    raise ValueError("Lien invalide : une seule entrée par module.")
                incoming.add(module.next_id)
            if not isinstance(module.actions, list) or len(module.actions) > 10000:
                raise ValueError("Séquence de module invalide.")
            if actions:
                for action in module.actions:
                    action.validate()
        # Each node has at most one input/output. Components are paths or rings;
        # traversal and execution bound rings explicitly instead of expanding them.

    def connect(self, source, target):
        module = self.get(source)
        previous = module.next_id
        module.next_id = target
        try:
            self.validate(actions=False)
        except ValueError:
            module.next_id = previous
            raise

    def chain(self):
        self.validate(actions=False)
        by_id = {m.id: m for m in self.modules}
        chain, current, visited = [], self.entry, set()
        while current is not None and current not in visited:
            visited.add(current)
            module = by_id[current]
            chain.append(module)
            current = module.next_id
        return chain

    def is_loop(self):
        modules = self.chain()
        return bool(modules and modules[-1].next_id == self.entry)

    def compile(self, module_id=None):
        actions, mapping = [], []
        self.validate(actions=False)
        modules = self.chain() if module_id is None else [self.get(module_id)]
        if any(m.condition.image and not m.actions for m in modules):
            raise ValueError('Ajoutez au moins une action aux séquences ayant une condition image.')
        if sum(len(m.actions) * m.repeat for m in modules) > 100000:
            raise ValueError("Cette exécution dépasse 100 000 actions. Réduisez les répétitions.")
        for module in modules:
            for index, action in enumerate(module.actions):
                action.validate()
            for iteration in range(1, module.repeat + 1):
                for index, action in enumerate(module.actions):
                    actions.append(action)
                    mapping.append((module.id, index, iteration))
        return actions, mapping

    def conditions(self, mapping):
        by_id = {module.id: module for module in self.modules}
        return {index: {'name': by_id[identifier].name, 'condition': copy.deepcopy(by_id[identifier].condition)}
                for index, (identifier, row, iteration) in enumerate(mapping)
                if row == 0 and iteration == 1 and by_id[identifier].condition.image}

    def import_modules(self, other, replace_empty=False):
        """Copy the complete graph with fresh IDs; commit only after validation."""
        other.validate()
        existing = [] if replace_empty else list(self.modules)
        imported = copy.deepcopy(other.modules)
        identifiers = {module.id: uuid4().hex for module in imported}
        dx = dy = 0
        if existing:
            dx = max(m.x + 260 for m in existing) + 140 - min(m.x for m in imported)
            dy = min(m.y for m in existing) - min(m.y for m in imported)
        for module in imported:
            old_id = module.id
            module.id = identifiers[old_id]
            module.next_id = identifiers[module.next_id] if module.next_id else None
            module.x += dx
            module.y += dy
        entry = self.entry if existing else identifiers[other.entry]
        popups = copy.deepcopy(other.popups) if not existing else copy.deepcopy(self.popups)
        if existing:
            for rule in copy.deepcopy(other.popups.rules):
                rule.id = uuid4().hex
                if not other.popups.enabled:
                    rule.enabled = False
                popups.rules.append(rule)
        proposed = Workflow(existing + imported, entry, popups,
                            self.safety_enabled if existing else other.safety_enabled,
                            copy.deepcopy(self.report if existing else other.report),
                            copy.deepcopy(self.image_start if existing else other.image_start),
                            self.loop_count if existing else other.loop_count)
        proposed.validate(actions=False)
        self.modules, self.entry = proposed.modules, proposed.entry
        self.popups = proposed.popups
        self.safety_enabled = proposed.safety_enabled
        self.report = proposed.report
        self.image_start = proposed.image_start
        self.loop_count = proposed.loop_count
        return imported, identifiers[other.entry]

def save_workflow(path, workflow):
    workflow.validate()
    write_payload(path, {"version": 2, "entry": workflow.entry,
                         "modules": [asdict(m) for m in workflow.modules], "popups": asdict(workflow.popups),
                         "safety_enabled": workflow.safety_enabled, "report": asdict(workflow.report),
                         "image_start": asdict(workflow.image_start), "loop_count": workflow.loop_count}, max_bytes=None)

def load_workflow(path):
    data = json.loads(Path(path).read_text(encoding="utf-8"))
    if isinstance(data, dict) and type(data.get("version")) is int and data["version"] == 1:
        name = data.get("name", Path(path).stem[:120])
        if not isinstance(name, str) or not name.strip() or len(name) > 120:
            raise ValueError("Nom de séquence invalide.")
        return Workflow([Module(name=name, actions=load(path))])
    if not isinstance(data, dict) or type(data.get("version")) is not int or data["version"] != 2:
        raise ValueError("Format de workflow non pris en charge.")
    rows = data.get("modules")
    if not isinstance(rows, list) or not rows:
        raise ValueError("Liste de modules invalide.")
    modules = []
    for row in rows:
        required = {"id", "name", "x", "y", "next_id", "actions"}
        if not isinstance(row, dict) or not required <= set(row) or set(row) - required - {"repeat", "image_start", "condition"}:
            raise ValueError("Module invalide.")
        if not isinstance(row["actions"], list) or len(row["actions"]) > 10000:
            raise ValueError("Séquence invalide.")
        actions = []
        for raw in row["actions"]:
            if not isinstance(raw, dict) or set(raw) != {"kind", "params"} or not isinstance(raw["kind"], str):
                raise ValueError("Bloc invalide.")
            action = Action(**raw)
            upgrade_action(action)
            actions.append(action)
        modules.append(Module(**{**row, "actions": actions, 'image_start': load_image_start(row.get('image_start')),
                                 'condition': load_condition(row.get('condition'))}))
    workflow = Workflow(modules, data.get("entry"), load_popup_mode(data.get("popups")), data.get("safety_enabled", True), load_report_config(data.get("report")), load_image_start(data.get("image_start")), data.get('loop_count', 2))
    if data.get("entry") is None:
        raise ValueError("Module de départ manquant.")
    workflow.validate()
    return workflow
