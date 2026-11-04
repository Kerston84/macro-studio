"""Validated actions and versioned, atomic JSON persistence."""
from dataclasses import dataclass, field, asdict
import json
import math
import os
from pathlib import Path
import tempfile

DEFAULTS = {
    "mouse": {"x": 0, "y": 0, "button": "left"},
    "mouse_image": {"image": "", "name": "", "threshold": 0.9, "timeout": 10.0, "button": "left", "occurrence": "unique"},
    "keyboard": {"keys": "ctrl+a"},
    "text": {"text": "Bonjour"},
    "wait": {"seconds": 1.0},
    "scroll": {"direction": "down", "amount": 3, "pause": 0.5, "use_position": False, "x": 0, "y": 0,
               "region": None, "focus_click": False},
}
DEFAULTS["scroll_image"] = {**DEFAULTS["mouse_image"], **DEFAULTS["scroll"], "max_scrolls": 20, "timeout": 30.0}
DEFAULTS["wait_image_absent"] = {"image": "", "name": "", "threshold": 0.9, "timeout": 120.0,
    "interval": 0.25, "absent_for": 1.0, "wait_for_appearance": False, "region": None}
IMAGE_KINDS = ("mouse_image", "scroll_image", "wait_image_absent")
CLICK_KINDS = ("mouse", "mouse_image", "scroll_image")
AFTER_CLICK_DEFAULTS = {"enabled": False, "image": "", "name": "", "threshold": .9,
    "appearance_timeout": 3.0, "timeout": 120.0, "interval": .25, "absent_for": 1.0, "region": None}
LABELS = {"mouse": "Clic souris", "mouse_image": "Clic sur image", "keyboard": "Raccourci clavier",
          "text": "Saisir du texte", "wait": "Attente", "scroll": "Défiler",
          "scroll_image": "Défiler jusqu’à l’image", "wait_image_absent": "Attendre la disparition d’une image"}

def validate_scroll(params):
    if type(params["focus_click"]) is not bool:
        raise ValueError("Option de focus invalide.")
    validate_region(params["region"])
    if params["direction"] not in ("up", "down", "left", "right"):
        raise ValueError("Direction de défilement invalide.")
    if type(params["amount"]) is not int or not 1 <= params["amount"] <= 100:
        raise ValueError("Choisissez entre 1 et 100 crans par défilement.")
    if type(params["pause"]) not in (int, float) or not math.isfinite(params["pause"]) or not .05 <= params["pause"] <= 10:
        raise ValueError("La pause après défilement doit être de 0,05 à 10 secondes.")
    if type(params["use_position"]) is not bool:
        raise ValueError("Mode de ciblage de la zone invalide.")
    if any(type(params[key]) is not int or not -100000 <= params[key] <= 100000 for key in ("x", "y")):
        raise ValueError("Coordonnées de défilement invalides.")

def validate_region(region):
    if region is not None:
        if not isinstance(region, dict) or set(region) != {"left", "top", "width", "height"}:
            raise ValueError("Zone d’écran invalide.")
        if any(type(v) is not int for v in region.values()):
            raise ValueError("Les coordonnées de la zone doivent être entières.")
        if any(abs(region[k]) > 100000 for k in ("left", "top")) or not all(20 <= region[k] <= 16384 for k in ("width", "height")):
            raise ValueError("La zone doit mesurer au moins 20 pixels et au plus 16384 pixels par dimension.")

def validate_after_click(config):
    if config is None:
        return
    if not isinstance(config, dict) or set(config) != set(AFTER_CLICK_DEFAULTS):
        raise ValueError("Réglages de chargement après clic invalides.")
    if type(config["enabled"]) is not bool or not isinstance(config["name"], str) or len(config["name"]) > 256:
        raise ValueError("Option ou nom d’image de chargement invalide.")
    if not isinstance(config["image"], str) or len(config["image"]) > 2_666_672:
        raise ValueError("Image de chargement invalide.")
    for key, low, high in (("threshold", .5, 1), ("appearance_timeout", 0, 60), ("timeout", 0, 86400),
                           ("interval", .05, 10), ("absent_for", 0, 30)):
        value = config[key]
        if type(value) not in (int, float) or not math.isfinite(value) or not low <= value <= high:
            raise ValueError(f"Paramètre de chargement {key} invalide.")
    validate_region(config["region"])
    if config["enabled"] or config["image"]:
        from .vision import decode_template
        decode_template(config["image"])
    if config["enabled"]:
        if config["absent_for"] > config["timeout"]:
            raise ValueError("Le délai de chargement doit couvrir la confirmation de disparition.")
SPECIAL_KEYS = {"ctrl", "alt", "shift", "cmd", "enter", "tab", "space",
                "backspace", "delete", "esc", "home", "end", "up", "down",
                "left", "right", "page_up", "page_down", "alt_gr", "insert", "caps_lock", "num_lock",
                "scroll_lock", "print_screen", "pause", "menu", "plus", *(f"f{i}" for i in range(1, 25))}

def parse_keys(value):
    if not isinstance(value, str):
        raise ValueError("Les touches doivent être une chaîne.")
    keys = [key.strip().lower() for key in value.split("+")]
    if not keys or len(keys) > 8 or any(not k or (len(k) != 1 and k not in SPECIAL_KEYS) for k in keys):
        raise ValueError("Touches invalides. Exemple : ctrl+shift+s, enter ou f5.")
    return keys

def upgrade_action(action):
    if isinstance(action.params, dict):
        if action.kind == "mouse_image":
            action.params.setdefault("occurrence", "unique")
        if action.kind in ("scroll", "scroll_image"):
            action.params.setdefault("region", None)
            action.params.setdefault("focus_click", False)
    return action

@dataclass
class Action:
    kind: str
    params: dict = field(default_factory=dict)

    @classmethod
    def create(cls, kind):
        return cls(kind, DEFAULTS[kind].copy())

    def summary(self):
        p = self.params
        if self.kind in IMAGE_KINDS:
            return p["name"] or ("Choisissez l’image à surveiller" if self.kind == "wait_image_absent" else "Choisissez l’image du bouton")
        if self.kind == "scroll":
            direction = {"up": "haut", "down": "bas", "left": "gauche", "right": "droite"}[p["direction"]]
            return f"Vers {direction} · {p['amount']} cran(s)"
        if self.kind == "mouse":
            button = {"left": "gauche", "right": "droit", "middle": "milieu"}[p["button"]]
            return f"({p['x']}, {p['y']}) · {button}"
        if self.kind == "wait":
            return f"{p['seconds']:g} s"
        if self.kind == "keyboard":
            return p["keys"]
        return p["text"].replace("\n", " ↵ ")[:65]

    def validate(self):
        if self.kind not in DEFAULTS or not isinstance(self.params, dict):
            raise ValueError("Type de bloc inconnu.")
        keys = set(self.params) - ({"after_click"} if self.kind in CLICK_KINDS else set())
        if keys != set(DEFAULTS[self.kind]):
            raise ValueError("Paramètres du bloc invalides.")
        p = self.params
        if self.kind in CLICK_KINDS:
            validate_after_click(p.get("after_click"))
        if self.kind == "mouse":
            if any(type(p[k]) is not int or not -100000 <= p[k] <= 100000 for k in ("x", "y")):
                raise ValueError("Coordonnées invalides.")
            if p["button"] not in ("left", "right", "middle"):
                raise ValueError("Bouton invalide.")
        elif self.kind in IMAGE_KINDS:
            from .vision import decode_template
            if self.kind != "wait_image_absent" and p["occurrence"] not in ("unique", "first", "last"):
                raise ValueError("Choix de correspondance invalide.")
            if not isinstance(p["name"], str) or len(p["name"]) > 256:
                raise ValueError("Nom d’image invalide.")
            for key, low, high in (("threshold", 0.5, 1), ("timeout", 0, 86400 if self.kind == "wait_image_absent" else 300)):
                value = p[key]
                if type(value) not in (int, float) or not math.isfinite(value) or not low <= value <= high:
                    raise ValueError(f"Paramètre {key} invalide ({low} à {high}).")
            if self.kind != "wait_image_absent" and p["button"] not in ("left", "right", "middle"):
                raise ValueError("Bouton invalide.")
            decode_template(p["image"])
            if self.kind == "wait_image_absent":
                validate_region(p["region"])
                if type(p["wait_for_appearance"]) is not bool:
                    raise ValueError("Option d’attente d’apparition invalide.")
                for key, low, high in (("interval", .05, 10), ("absent_for", 0, 30)):
                    value = p[key]
                    if type(value) not in (int, float) or not math.isfinite(value) or not low <= value <= high:
                        raise ValueError(f"Paramètre {key} invalide ({low} à {high} secondes).")
                if p["absent_for"] > p["timeout"]:
                    raise ValueError("Le délai maximal doit couvrir la confirmation de disparition.")
            if self.kind == "scroll_image":
                validate_scroll(p)
                if type(p["max_scrolls"]) is not int or not 1 <= p["max_scrolls"] <= 200:
                    raise ValueError("La limite de défilements doit être entre 1 et 200.")
        elif self.kind == "scroll":
            validate_scroll(p)
        elif self.kind == "keyboard":
            parse_keys(p["keys"])
        elif self.kind == "text":
            if not isinstance(p["text"], str) or len(p["text"]) > 100000:
                raise ValueError("Texte invalide ou trop long.")
        elif type(p["seconds"]) not in (int, float) or not math.isfinite(p["seconds"]) or not 0 <= p["seconds"] <= 86400:
            raise ValueError("Durée invalide (0 à 86400 secondes).")

def save(path, actions, *, name=None):
    for action in actions:
        action.validate()
    target = Path(path)
    payload = {"version": 1, "actions": [asdict(a) for a in actions]}
    if name is not None:
        if not isinstance(name, str) or not name.strip() or len(name) > 120:
            raise ValueError("Le nom de la séquence doit contenir 1 à 120 caractères.")
        payload["name"] = name
    write_payload(target, payload)

def write_payload(path, payload, max_bytes=10_000_000):
    target = Path(path)
    serialized = json.dumps(payload, ensure_ascii=False, indent=2, allow_nan=False)
    if max_bytes is not None and len(serialized.encode("utf-8")) > max_bytes:
        raise ValueError("Macro trop volumineuse (10 Mo maximum). Réduisez la taille des images.")
    name = None
    try:
        with tempfile.NamedTemporaryFile(mode="w", encoding="utf-8", dir=target.parent,
                                         suffix=".tmp", delete=False) as handle:
            name = handle.name
            handle.write(serialized)
        os.replace(name, target)
    finally:
        if name and os.path.exists(name):
            os.unlink(name)

def load(path):
    if Path(path).stat().st_size > 10_000_000:
        raise ValueError("Fichier trop volumineux.")
    data = json.loads(Path(path).read_text(encoding="utf-8"))
    if not isinstance(data, dict) or type(data.get("version")) is not int or data["version"] != 1:
        raise ValueError("Version de fichier non prise en charge.")
    rows = data.get("actions")
    if not isinstance(rows, list) or len(rows) > 10000:
        raise ValueError("Liste de blocs invalide.")
    actions = []
    for row in rows:
        if not isinstance(row, dict) or set(row) != {"kind", "params"} or not isinstance(row["kind"], str):
            raise ValueError("Bloc invalide.")
        action = Action(**row)
        # Macros created before the occurrence selector retain strict matching.
        upgrade_action(action)
        action.validate()
        actions.append(action)
    return actions
