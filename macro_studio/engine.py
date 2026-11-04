"""Interruptible execution independent from the Qt UI."""
from .model import parse_keys
import sys
from contextlib import nullcontext

def scroll_vector(direction):
    return {"up": (0, 1), "down": (0, -1), "left": (-1, 0), "right": (1, 0)}[direction]

class DesktopBackend:
    def __init__(self):
        from pynput import keyboard, mouse
        self.keyboard_module = keyboard
        self.mouse_module = mouse
        self.keyboard = keyboard.Controller()
        self.mouse = mouse.Controller()
        if sys.platform == "win32":
            from .text_input import WindowsTextSender
            self.text_sender = WindowsTextSender()
        else:
            self.text_sender = None

    def click(self, x, y, button):
        control = getattr(self, "execution_control", None)
        if control and not control.ensure_point(x, y):
            return
        self.mouse.position = (x, y)
        self.mouse.click(getattr(self.mouse_module.Button, button))

    def capture_popup(self, region):
        from .vision import capture_region, capture_desktop
        return capture_region(region) if region else capture_desktop()

    def find_image(self, params, stop):
        from .vision import find_on_screen
        return find_on_screen(params["image"], params["threshold"], params["timeout"], stop,
                              occurrence=params.get("occurrence", "unique"))

    def scroll(self, params, stop):
        if hasattr(stop, "checkpoint") and not stop.checkpoint():
            return
        if stop.is_set():
            return
        region = params.get("region")
        if region:
            self.mouse.position = (region["left"] + region["width"] // 2,
                                   region["top"] + region["height"] // 2)
        elif params["use_position"]:
            self.mouse.position = (params["x"], params["y"])
        if region or params["use_position"]:
            if stop.wait(.08):
                return
        if params.get("focus_click"):
            if stop.is_set():
                return
            self.mouse.click(self.mouse_module.Button.left)
            if stop.wait(.1):
                return
        dx, dy = scroll_vector(params["direction"])
        for _ in range(params["amount"]):
            if hasattr(stop, "checkpoint") and not stop.checkpoint():
                return
            if stop.is_set():
                break
            self.mouse.scroll(dx, dy)

    def find_scrolling_image(self, params, stop, log):
        from .vision import find_with_scroll, capture_region, capture_desktop
        capture = (lambda: capture_region(params["region"])) if params.get("region") else capture_desktop
        return find_with_scroll(params, stop, lambda: self.scroll(params, stop), capture=capture, log=log)

    def wait_image_absent(self, params, stop, log):
        from .vision import wait_until_absent, capture_region, capture_desktop
        capture = (lambda: capture_region(params["region"])) if params.get("region") else capture_desktop
        return wait_until_absent(params, stop, capture=capture, log=log)

    def wait_after_click(self, config, stop, log):
        from .vision import wait_after_click, capture_region, capture_desktop
        capture = (lambda: capture_region(config["region"])) if config.get("region") else capture_desktop
        return wait_after_click(config, stop, capture=capture, log=log)

    def hotkey(self, keys, stop):
        held = []
        try:
            for key in keys:
                if stop.is_set():
                    break
                resolved = "+" if key == "plus" else getattr(self.keyboard_module.Key, key) if len(key) > 1 else key
                self.keyboard.press(resolved)
                held.append(resolved)
        finally:
            for key in reversed(held):
                self.keyboard.release(key)

    def type_text(self, text, stop):
        for character in text:
            if hasattr(stop, "checkpoint") and not stop.checkpoint():
                break
            if stop.is_set():
                break
            if self.text_sender is not None and character not in ("\n", "\r", "\t"):
                self.text_sender.send_character(character)
            else:
                self.keyboard.type(character)
            if stop.wait(.03):
                break
        stop.wait(.1)

def execution_steps(actions, cycles, stop, cycle_progress):
    if not actions:
        return
    cycle = 1
    while not stop.is_set() and (cycles == 0 or cycle <= cycles):
        cycle_progress(cycle, cycles)
        for index, action in enumerate(actions):
            if stop.is_set():
                return
            yield index, action
        if cycles and cycle == cycles:
            return
        if stop.wait(.01):
            return
        cycle += 1


def execute(actions, backend, stop, log, progress=lambda index: None, countdown=3, popup_mode=None,
            cycles=1, cycle_progress=lambda current, total: None, conditions=None,
            condition_progress=lambda index, waiting, message: None):
    if type(cycles) is not int or not 0 <= cycles <= 10000:
        raise ValueError('Nombre de tours du workflow invalide.')
    validated = set()
    for action in actions:
        if stop.is_set():
            return "Arrêté"
        if id(action) not in validated:
            action.validate()
            validated.add(id(action))
    log(f"Démarrage dans {countdown:g} s — F8 pour arrêter.")
    if stop.wait(countdown):
        return "Arrêté"
    if hasattr(stop, "arm"):
        stop.arm()
    monitor = None
    if popup_mode and popup_mode.enabled and any(r.enabled for r in popup_mode.rules):
        from .popups import PopupMonitor, MonitoredStop
        monitor = PopupMonitor(popup_mode, backend, stop, log)
        stop = MonitoredStop(stop, monitor)
        log("Mode popups activé pour cette exécution.")
    for index, action in execution_steps(actions, cycles, stop, cycle_progress):
        if monitor:
            monitor.check()
        if hasattr(stop, "checkpoint") and not stop.checkpoint():
            return "Arrêté"
        if stop.is_set():
            return "Arrêté"
        progress(index)
        gate = (conditions or {}).get(index)
        if gate:
            from .conditions import wait_for_condition
            message = f'Condition de « {gate["name"]} » : attente de {gate["condition"].name or "l’image"} · vérification toutes les 3 s.'
            log(message)
            condition_progress(index, True, message)
            try:
                if not wait_for_condition(gate['condition'], stop, lambda: backend.capture_popup(None)):
                    return 'Arrêté'
                log(f'Condition remplie : séquence « {gate["name"]} ».')
            finally:
                condition_progress(index, False, '')
            if hasattr(stop, 'checkpoint') and not stop.checkpoint():
                return 'Arrêté'
            if stop.is_set():
                return 'Arrêté'
        log(f"Bloc {index + 1} : {action.kind}")
        p = action.params
        if action.kind == "wait":
            stop.wait(p["seconds"])
        elif action.kind == "wait_image_absent":
            if not backend.wait_image_absent(p, stop, log) or stop.is_set():
                return "Arrêté"
        elif action.kind == "mouse":
            backend.click(p["x"], p["y"], p["button"])
        elif action.kind == "scroll":
            backend.scroll(p, stop)
            stop.wait(p["pause"])
        elif action.kind in ("mouse_image", "scroll_image"):
            while True:
                try:
                    found = (backend.find_scrolling_image(p, stop, log) if action.kind == "scroll_image"
                             else backend.find_image(p, stop))
                    break
                except (TimeoutError, ValueError) as exc:
                    if not getattr(stop, "safety_enabled", False):
                        raise
                    if not stop.visual_failure(exc):
                        return "Arrêté"
            if stop.is_set() or found is None:
                return "Arrêté"
            x, y, score = found
            if hasattr(stop, "checkpoint") and not stop.checkpoint():
                return "Arrêté"
            log(f"Bouton trouvé en ({x}, {y}) · similarité {score:.0%}")
            backend.click(x, y, p["button"])
        elif action.kind == "keyboard":
            with stop.atomic_input() if monitor else nullcontext():
                backend.hotkey(parse_keys(p["keys"]), stop)
        else:
            with stop.atomic_input() if monitor else nullcontext():
                backend.type_text(p["text"], stop)
        config = p.get("after_click")
        if config and config["enabled"]:
            if stop.is_set() or not backend.wait_after_click(config, stop, log):
                return "Arrêté"
        if monitor:
            monitor.check(force=index == len(actions) - 1)
    return "Arrêté" if stop.is_set() else "Terminé"
