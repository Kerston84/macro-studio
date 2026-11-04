"""Workflow-wide popup rules and serialized, cooperative intervention."""
from dataclasses import dataclass, field
import math
import time
from uuid import uuid4
from contextlib import contextmanager, nullcontext
from .model import validate_region
from .vision import decode_template, locate

@dataclass
class PopupRule:
    name: str = "Nouveau popup"
    id: str = field(default_factory=lambda: uuid4().hex)
    enabled: bool = True
    image: str = ""
    image_name: str = ""
    threshold: float = .9
    region: dict | None = None
    response: str = "click_detected"
    target_image: str = ""
    target_name: str = ""
    x: int = 0
    y: int = 0
    point_selected: bool = False
    seconds: float = 10
    cooldown: float = 3
    max_triggers: int = 20

@dataclass
class PopupMode:
    enabled: bool = False
    rules: list = field(default_factory=list)

    def validate(self):
        if type(self.enabled) is not bool or not isinstance(self.rules, list):
            raise ValueError("Mode popups invalide.")
        identifiers = set()
        for rule in self.rules:
            if not isinstance(rule, PopupRule) or not isinstance(rule.id, str) or not rule.id or rule.id in identifiers:
                raise ValueError("Identifiant de règle popup invalide.")
            identifiers.add(rule.id)
            if not isinstance(rule.name, str) or not rule.name.strip() or len(rule.name) > 120 or type(rule.enabled) is not bool:
                raise ValueError("Nom ou activation de règle popup invalide.")
            if rule.response not in ("click_detected", "click_image", "click_point", "wait"):
                raise ValueError("Réaction au popup invalide.")
            for key in ("image", "target_image", "image_name", "target_name"):
                value = getattr(rule, key)
                if not isinstance(value, str) or len(value) > (256 if key.endswith("name") else 2_666_672):
                    raise ValueError("Image de popup invalide.")
            for key, low, high in (("threshold", .5, 1), ("seconds", 0, 3600), ("cooldown", .5, 3600)):
                value = getattr(rule, key)
                if type(value) not in (int, float) or not math.isfinite(value) or not low <= value <= high:
                    raise ValueError(f"Réglage popup {key} invalide.")
            if type(rule.max_triggers) is not int or not 1 <= rule.max_triggers <= 10000:
                raise ValueError("Limite d’interventions popup invalide.")
            if any(type(v) is not int or abs(v) > 100000 for v in (rule.x, rule.y)):
                raise ValueError("Point de clic popup invalide.")
            if type(rule.point_selected) is not bool:
                raise ValueError("Sélection du point de clic invalide.")
            if self.enabled and rule.enabled and rule.response == "click_point" and not rule.point_selected:
                raise ValueError(f"Popup « {rule.name} » : choisissez où cliquer.")
            validate_region(rule.region)
            if rule.image or (self.enabled and rule.enabled):
                decode_template(rule.image)
            if rule.target_image or (self.enabled and rule.enabled and rule.response == "click_image"):
                decode_template(rule.target_image)

def load_popup_mode(data):
    if data is None:
        return PopupMode()
    if not isinstance(data, dict) or set(data) != {"enabled", "rules"} or not isinstance(data["rules"], list):
        raise ValueError("Configuration des popups invalide.")
    try:
        mode = PopupMode(data["enabled"], [PopupRule(**row) for row in data["rules"]])
    except (TypeError, ValueError) as exc:
        raise ValueError("Règle popup invalide.") from exc
    mode.validate()
    return mode

class PopupMonitor:
    def __init__(self, mode, backend, stop, log, clock=time.monotonic):
        mode.validate()
        self.rules = [r for r in mode.rules if mode.enabled and r.enabled]
        self.backend, self.stop, self.log, self.clock = backend, stop, log, clock
        self.templates = {r.id: decode_template(r.image) for r in self.rules}
        self.targets = {r.id: decode_template(r.target_image) for r in self.rules if r.response == "click_image"}
        self.next_scan = 0
        self.next_allowed, self.counts = {}, {}
        self.handling = False
        self.suspended = 0
        self.paused_time = 0

    def check(self, force=False):
        now = self.clock()
        if not self.rules or self.stop.is_set() or self.handling or self.suspended or (not force and now < self.next_scan):
            return
        self.next_scan = now + .5
        captures = {}
        for rule in self.rules:
            if now < self.next_allowed.get(rule.id, 0):
                continue
            key = tuple(sorted(rule.region.items())) if rule.region else None
            if key not in captures:
                captures[key] = self.backend.capture_popup(rule.region)
            frame, left, top = captures[key]
            occurrence = "unique" if rule.response == "click_detected" else "first"
            match = locate(frame, self.templates[rule.id], rule.threshold, occurrence)
            if match is None:
                continue
            if self.counts.get(rule.id, 0) >= rule.max_triggers:
                raise RuntimeError(f"Popup « {rule.name} » : limite d’interventions atteinte, workflow arrêté.")
            if self.stop.is_set():
                return
            base_time = self.stop.active_time if hasattr(self.stop, "active_time") else self.clock
            started = base_time()
            self.handling = True
            try:
                self.log(f"Popup « {rule.name} » détecté — workflow en pause.")
                x, y = match[0] + left, match[1] + top
                if rule.response == "click_point":
                    x, y = rule.x, rule.y
                elif rule.response == "click_image":
                    target = locate(frame, self.targets[rule.id], rule.threshold)
                    if target is None:
                        raise RuntimeError(f"Popup « {rule.name} » : image du bouton à cliquer introuvable.")
                    x, y = target[0] + left, target[1] + top
                with self.stop.suspend_safety() if hasattr(self.stop, "suspend_safety") else nullcontext():
                    if rule.response == "wait":
                        self.log(f"Popup : attente de {rule.seconds:g} seconde(s).")
                        self.stop.wait(rule.seconds)
                    elif not self.stop.is_set():
                        self.backend.click(x, y, "left")
                        self.stop.wait(.2)
                self.counts[rule.id] = self.counts.get(rule.id, 0) + 1
                self.next_allowed[rule.id] = self.clock() + rule.cooldown
                if not self.stop.is_set():
                    self.log("Intervention popup terminée — reprise du workflow.")
            finally:
                self.paused_time += base_time() - started
                self.handling = False
            # Refresh the image before considering any other rule.
            return

class MonitoredStop:
    """An Event-compatible stop token: waits remain interruptible and monitor popups."""
    def __init__(self, raw, monitor):
        self.raw, self.monitor = raw, monitor

    def is_set(self):
        return self.raw.is_set()

    def set(self):
        self.raw.set()

    def active_time(self):
        base = self.raw.active_time() if hasattr(self.raw, "active_time") else self.monitor.clock()
        return base - self.monitor.paused_time

    @property
    def safety_enabled(self):
        return getattr(self.raw, "safety_enabled", False)

    def checkpoint(self):
        self.monitor.check()
        return self.raw.checkpoint() if hasattr(self.raw, "checkpoint") else not self.raw.is_set()

    def visual_failure(self, message):
        return self.raw.visual_failure(message)

    def wait(self, seconds):
        deadline = self.active_time() + seconds
        while not self.raw.is_set():
            self.monitor.check()
            if self.raw.is_set():
                return True
            remaining = deadline - self.active_time()
            if remaining <= 0:
                return False
            if self.raw.wait(min(.1, remaining)):
                return True
        return True

    @contextmanager
    def atomic_input(self):
        self.monitor.suspended += 1
        try:
            yield
        finally:
            self.monitor.suspended -= 1
