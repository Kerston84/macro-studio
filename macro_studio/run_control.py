"""Cooperative pause, active clock, and Windows foreground/occlusion checks."""
import ctypes
from ctypes import wintypes
from contextlib import contextmanager
import threading
import time

class WindowGuard:
    def __init__(self, ignored=(), blocked=()):
        self.api = ctypes.WinDLL("user32", use_last_error=True)
        self.api.GetForegroundWindow.restype = wintypes.HWND
        self.api.GetAncestor.argtypes = (wintypes.HWND, wintypes.UINT)
        self.api.GetAncestor.restype = wintypes.HWND
        self.api.WindowFromPoint.argtypes = (wintypes.POINT,)
        self.api.WindowFromPoint.restype = wintypes.HWND
        self.ignored = set(ignored)
        self.blocked = set(blocked)
        self.expected = None

    def foreground(self):
        handle = self.api.GetForegroundWindow()
        return self.api.GetAncestor(handle, 2) if handle else None

    def arm(self):
        current = self.foreground()
        if current and current not in self.ignored and current not in self.blocked:
            self.expected = current

    def reason(self):
        current = self.foreground()
        if self.expected is None or current in self.blocked:
            return "Placez la fenêtre cible au premier plan, puis cliquez sur Reprendre."
        if current in self.ignored:
            return None
        if not current:
            return "La fenêtre cible n’est plus disponible. Vérifiez l’écran."
        if self.expected is not None and current != self.expected:
            return "Une autre fenêtre est passée devant la cible. Vérifiez l’écran avant de reprendre."
        return None

    def point_reason(self, x, y):
        handle = self.api.WindowFromPoint(wintypes.POINT(x, y))
        root = self.api.GetAncestor(handle, 2) if handle else None
        if self.expected is not None and root != self.expected:
            return "Une autre fenêtre masque la zone du clic. Déplacez l’obstacle puis reprenez."
        return None

class RunControl:
    def __init__(self, stop=None, on_state=lambda paused, reason: None, guard=None, clock=time.monotonic):
        self.stop = stop if stop is not None else threading.Event()
        self.on_state, self.guard, self.clock = on_state, guard, clock
        self.lock = threading.RLock()
        self.paused = False
        self.pause_started = None
        self.paused_time = 0
        self.reason = ""
        self.safety_enabled = guard is not None
        self.safety_suspended = 0
        self.armed = False

    def is_set(self): return self.stop.is_set()
    def set(self): self.stop.set()

    def active_time(self):
        with self.lock:
            now = self.clock()
            pending = now - self.pause_started if self.paused else 0
            return now - self.paused_time - pending

    def arm(self):
        if self.guard:
            self.guard.arm()
        self.armed = True

    def pause(self, reason="Pause manuelle"):
        with self.lock:
            if self.paused or self.is_set():
                return
            self.paused = True
            self.pause_started = self.clock()
            self.reason = reason
        self.on_state(True, reason)

    def resume(self):
        with self.lock:
            if not self.paused:
                return
            if self.guard:
                self.guard.arm()
                reason = self.guard.reason()
                if reason:
                    self.reason = "Sécurité : " + reason
                    self.on_state(True, self.reason)
                    return
            self.paused_time += self.clock() - self.pause_started
            self.paused = False
            self.pause_started = None
            self.reason = ""
        self.on_state(False, "Reprise demandée")

    def checkpoint(self):
        if (self.safety_enabled and self.guard is not None and self.armed and not self.safety_suspended
            and not self.paused):
            reason = self.guard.reason()
            if reason:
                self.pause("Sécurité : " + reason)
        while self.paused and not self.is_set():
            self.stop.wait(.05)
        return not self.is_set()

    def wait(self, seconds):
        deadline = self.active_time() + seconds
        while not self.is_set():
            if not self.checkpoint():
                return True
            remaining = deadline - self.active_time()
            if remaining <= 0:
                return False
            if self.stop.wait(min(.05, remaining)):
                return True
        return True

    def ensure_point(self, x, y):
        while self.checkpoint():
            if not self.safety_enabled or self.guard is None or self.safety_suspended or not self.armed:
                return True
            reason = self.guard.point_reason(x, y)
            if not reason:
                return True
            self.pause("Sécurité : " + reason)
        return False

    def visual_failure(self, message):
        self.pause("Sécurité : cible visuelle introuvable ou ambiguë. " + str(message))
        return self.checkpoint()

    @contextmanager
    def suspend_safety(self):
        self.safety_suspended += 1
        try:
            yield
        finally:
            self.safety_suspended -= 1
