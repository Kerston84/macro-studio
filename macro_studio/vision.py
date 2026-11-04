"""Local template matching; templates are embedded in macro JSON files."""
import base64
import binascii
import time
import cv2
import numpy as np

MAX_BYTES = 2_000_000

def active_time(stop):
    return stop.active_time() if hasattr(stop, "active_time") else time.monotonic()

def decode_template(encoded):
    if not isinstance(encoded, str) or not encoded or len(encoded) > MAX_BYTES * 4 // 3 + 4:
        raise ValueError("Choisissez une image de référence (PNG, 2 Mo maximum).")
    try:
        raw = base64.b64decode(encoded, validate=True)
    except (ValueError, binascii.Error) as exc:
        raise ValueError("Image intégrée invalide.") from exc
    # Inspect PNG dimensions before allocating the decoded image.
    if raw[:8] != b"\x89PNG\r\n\x1a\n" or len(raw) < 24:
        raise ValueError("L’image intégrée doit être un PNG.")
    width = int.from_bytes(raw[16:20], "big")
    height = int.from_bytes(raw[20:24], "big")
    if not (8 <= width <= 1024 and 8 <= height <= 1024):
        raise ValueError("Recadrez l’image : dimensions de 8 à 1024 pixels.")
    template = cv2.imdecode(np.frombuffer(raw, np.uint8), cv2.IMREAD_COLOR)
    if template is None:
        raise ValueError("Image PNG illisible.")
    if float(template.reshape(-1, 3).std(axis=0).max()) < 3:
        raise ValueError("Image trop uniforme : incluez le texte ou l’icône du bouton.")
    return template

def locate(screen, template, threshold, occurrence="unique"):
    """Return one unambiguous match center, or None. Images use BGR pixels."""
    height, width = template.shape[:2]
    if height > screen.shape[0] or width > screen.shape[1]:
        return None
    scores = cv2.matchTemplate(screen, template, cv2.TM_CCOEFF_NORMED)
    matches = []
    while True:
        _, score, _, position = cv2.minMaxLoc(scores)
        if not np.isfinite(score) or score < threshold:
            break
        x, y = position
        matches.append((x + width // 2, y + height // 2, float(score)))
        if occurrence == "unique" and len(matches) > 1:
            raise ValueError("Plusieurs boutons correspondent à l’image. Choisissez Première ou Dernière correspondance dans les propriétés, ou une image plus distinctive.")
        if len(matches) > 1000:
            raise ValueError("Trop de correspondances : utilisez une image plus distinctive.")
        scores[max(0, y-height+1):y+height, max(0, x-width+1):x+width] = -1
    if not matches:
        return None
    matches.sort(key=lambda match: (match[1], match[0]))
    return matches[-1] if occurrence == "last" else matches[0]

def capture_desktop():
    from mss import MSS
    with MSS() as capture:
        monitor = capture.monitors[0]
        shot = capture.grab(monitor)
        return np.asarray(shot)[:, :, :3].copy(), monitor["left"], monitor["top"]

def capture_region(region):
    from mss import MSS
    with MSS() as capture:
        shot = capture.grab(region)
        return np.asarray(shot)[:, :, :3].copy(), region["left"], region["top"]

def find_on_screen(encoded, threshold, timeout, stop, capture=capture_desktop, occurrence="unique"):
    template = decode_template(encoded)
    deadline = active_time(stop) + timeout
    while not stop.is_set():
        screen, left, top = capture()
        found = locate(screen, template, threshold, occurrence)
        if stop.is_set():
            return None
        if found:
            x, y, score = found
            return x + left, y + top, score
        remaining = deadline - active_time(stop)
        if remaining <= 0:
            raise TimeoutError("Bouton introuvable à l’écran dans le délai prévu. Aucun clic effectué.")
        stop.wait(min(0.25, remaining))
    return None

def find_with_scroll(params, stop, scroll, capture=capture_desktop, log=lambda message: None):
    """Inspect before each bounded scroll and click only after a visible match."""
    template = decode_template(params["image"])
    deadline = active_time(stop) + params["timeout"]
    for step in range(params["max_scrolls"] + 1):
        if stop.is_set():
            return None
        if step and active_time(stop) >= deadline:
            break
        screen, left, top = capture()
        found = locate(screen, template, params["threshold"], params["occurrence"])
        if stop.is_set():
            return None
        if found:
            x, y, score = found
            return x + left, y + top, score
        if step == params["max_scrolls"]:
            raise TimeoutError(f"Image introuvable après {step} défilement(s). Aucun clic effectué.")
        remaining = deadline - active_time(stop)
        if remaining <= 0:
            break
        log(f"Défilement {step + 1}/{params['max_scrolls']} · recherche de l’image")
        scroll()
        if stop.wait(min(params["pause"], remaining)):
            return None
    raise TimeoutError("Délai de recherche avec défilement dépassé. Aucun clic effectué.")

def wait_until_absent(params, stop, capture=capture_desktop, log=lambda message: None):
    """Wait for a stable absence; optional appearance gate, no mouse/keyboard input."""
    template = decode_template(params["image"])
    deadline = active_time(stop) + params["timeout"]
    seen = False
    absent_since = None
    previous_state = None
    log("Surveillance de l’image — F8 pour arrêter.")
    while not stop.is_set():
        screen, _, _ = capture()
        if stop.is_set():
            return False
        if template.shape[0] > screen.shape[0] or template.shape[1] > screen.shape[1]:
            raise ValueError("La zone de surveillance est plus petite que l’image. Sélectionnez une zone plus grande.")
        scores = cv2.matchTemplate(screen, template, cv2.TM_CCOEFF_NORMED)
        score = cv2.minMaxLoc(scores)[1]
        present = np.isfinite(score) and score >= params["threshold"]
        now = active_time(stop)
        if present:
            seen = True
            absent_since = None
            state = "Image présente — attente de sa disparition."
        elif params["wait_for_appearance"] and not seen:
            state = "Attente de l’apparition de l’image avant de surveiller sa disparition."
        else:
            state = "Image absente — confirmation de sa disparition."
            if absent_since is None:
                absent_since = now
            if now - absent_since >= params["absent_for"]:
                log("Disparition confirmée — reprise de la séquence.")
                return not stop.is_set()
        if state != previous_state:
            log(state)
            previous_state = state
        remaining = deadline - now
        if remaining <= 0:
            raise TimeoutError("Délai maximal de surveillance dépassé : la séquence est arrêtée.")
        if stop.wait(min(params["interval"], remaining)):
            return False
    return False

def wait_after_click(config, stop, capture=capture_desktop, log=lambda message: None):
    """Optional loading: absence during detection is success, a stuck loader is an error."""
    template = decode_template(config["image"])
    appearance_deadline = active_time(stop) + config["appearance_timeout"]
    disappearance_deadline = None
    absent_since = None
    log("Après le clic : recherche d’un indicateur de chargement.")
    while not stop.is_set():
        screen, _, _ = capture()
        if stop.is_set():
            return False
        if template.shape[0] > screen.shape[0] or template.shape[1] > screen.shape[1]:
            raise ValueError("La zone du chargement est plus petite que son image de référence.")
        score = cv2.minMaxLoc(cv2.matchTemplate(screen, template, cv2.TM_CCOEFF_NORMED))[1]
        present = np.isfinite(score) and score >= config["threshold"]
        now = active_time(stop)
        if disappearance_deadline is None:
            if not present:
                remaining = appearance_deadline - now
                if remaining <= 0:
                    log("Aucun chargement détecté après le clic — reprise de la séquence.")
                    return not stop.is_set()
                if stop.wait(min(config["interval"], remaining)):
                    return False
                continue
            disappearance_deadline = now + config["timeout"]
            log("Chargement détecté — attente de sa disparition.")
        if present:
            absent_since = None
        else:
            if absent_since is None:
                absent_since = now
            if now - absent_since >= config["absent_for"]:
                log("Chargement terminé — reprise de la séquence.")
                return not stop.is_set()
        remaining = disappearance_deadline - now
        if remaining <= 0:
            raise TimeoutError("Le chargement après le clic ne se termine pas : délai maximal dépassé, séquence arrêtée.")
        if stop.wait(min(config["interval"], remaining)):
            return False
    return False
