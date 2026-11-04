"""Dormant legacy settings retained solely for lossless loading and saving.

There is no image-start UI, watcher or execution path in this version.
"""
from dataclasses import dataclass
import math
from .model import validate_region


@dataclass
class ImageStart:
    enabled: bool = False
    image: str = ''
    name: str = ''
    threshold: float = .9
    interval: float = 3
    region: dict | None = None

    def validate(self):
        if type(self.enabled) is not bool or not isinstance(self.name, str) or len(self.name) > 256:
            raise ValueError('Top départ invalide.')
        if not isinstance(self.image, str):
            raise ValueError('Image de départ invalide.')
        for value, low, high in [(self.threshold, .5, 1), (self.interval, 1, 60)]:
            if type(value) not in (int, float) or not math.isfinite(value) or not low <= value <= high:
                raise ValueError('Seuil ou fréquence du top départ invalide.')
        validate_region(self.region)


def load_image_start(data):
    if data is None:
        return ImageStart()
    if not isinstance(data, dict) or set(data) - set(ImageStart.__dataclass_fields__):
        raise ValueError('Top départ invalide.')
    config = ImageStart(**data)
    config.validate()
    return config
