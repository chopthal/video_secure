"""워터마크 작업 설정 모델."""

from dataclasses import dataclass
from enum import Enum
from typing import Optional


class WatermarkMode(str, Enum):
    STATIC = "static"
    PERIODIC = "periodic"


class WatermarkPosition(str, Enum):
    TOP_LEFT = "top_left"
    TOP_CENTER = "top_center"
    TOP_RIGHT = "top_right"
    CENTER = "center"
    BOTTOM_LEFT = "bottom_left"
    BOTTOM_CENTER = "bottom_center"
    BOTTOM_RIGHT = "bottom_right"


class QualityPreset(str, Enum):
    HIGH = "high"
    STANDARD = "standard"
    SMALL = "small"


@dataclass
class WatermarkRequest:
    buyer_name: str
    contact: str
    mode: WatermarkMode = WatermarkMode.STATIC
    start_seconds: float = 0.0
    end_seconds: Optional[float] = None
    interval_seconds: float = 30.0
    show_seconds: float = 5.0
    position: WatermarkPosition = WatermarkPosition.BOTTOM_CENTER
    font_size: int = 24
    opacity: float = 0.7
    quality: QualityPreset = QualityPreset.STANDARD
    use_gpu: bool = False
