"""A module condition is active only when an image has been imported."""
from dataclasses import dataclass
import time
from .vision import decode_template, locate

POLL_SECONDS = 3
MATCH_THRESHOLD = .9


@dataclass
class ImageCondition:
    image: str = ''
    name: str = ''

    def validate(self):
        if not isinstance(self.image, str) or not isinstance(self.name, str) or len(self.name) > 256:
            raise ValueError('Condition de séquence invalide.')
        if self.image:
            decode_template(self.image)


def load_condition(data):
    if data is None:
        return ImageCondition()
    if not isinstance(data, dict) or set(data) - {'image', 'name'}:
        raise ValueError('Condition de séquence invalide.')
    condition = ImageCondition(**data)
    condition.validate()
    return condition


def wait_for_condition(condition, stop, capture):
    condition.validate()
    if not condition.image:
        return not stop.is_set()
    template = decode_template(condition.image)
    while not stop.is_set():
        if hasattr(stop, 'checkpoint') and not stop.checkpoint():
            return False
        started = time.monotonic()
        screen, _, _ = capture()
        match = locate(screen, template, MATCH_THRESHOLD, occurrence='first')
        if stop.is_set():
            return False
        if match:
            return True
        if stop.wait(max(0, POLL_SECONDS - (time.monotonic() - started))):
            return False
    return False
