"""FFmpeg drawtext 워터마크 처리."""

import re
import subprocess
import threading
from enum import Enum
from pathlib import Path
from typing import Callable, Optional, TypeVar

from app.ffmpeg_utils import (
    detect_gpu_encoder,
    find_ffmpeg,
    get_default_font,
    probe_video,
    quality_to_crf,
)
from app.models import WatermarkPosition, WatermarkRequest

E = TypeVar("E", bound=Enum)


def _enum_str(value: Enum | str) -> str:
    if isinstance(value, Enum):
        return value.value
    return str(value)


def _as_enum(enum_cls: type[E], value: E | str) -> E:
    if isinstance(value, enum_cls):
        return value
    return enum_cls(value)


def build_watermark_text(buyer_name: str, contact: str) -> str:
    return f"이 강의는 {buyer_name} ({contact}) 님이 구매하신 영상입니다."


def escape_drawtext(text: str) -> str:
    """drawtext 필터용 텍스트 이스케이프."""
    return (
        text.replace("\\", "\\\\")
        .replace(":", "\\:")
        .replace("'", "\\'")
        .replace("%", "\\%")
    )


def escape_font_path(path: str) -> str:
    return path.replace("\\", "/").replace(":", "\\:")


def position_to_xy(position: WatermarkPosition) -> tuple[str, str]:
    mapping = {
        WatermarkPosition.TOP_LEFT: ("10", "10"),
        WatermarkPosition.TOP_CENTER: ("(w-text_w)/2", "10"),
        WatermarkPosition.TOP_RIGHT: ("w-text_w-10", "10"),
        WatermarkPosition.CENTER: ("(w-text_w)/2", "(h-text_h)/2"),
        WatermarkPosition.BOTTOM_LEFT: ("10", "h-text_h-10"),
        WatermarkPosition.BOTTOM_CENTER: ("(w-text_w)/2", "h-text_h-10"),
        WatermarkPosition.BOTTOM_RIGHT: ("w-text_w-10", "h-text_h-10"),
    }
    return mapping[position]


def build_enable_expression(
    mode: str,
    start: float,
    end: Optional[float],
    interval: float,
    show: float,
    video_duration: float,
) -> str:
    effective_end = end if end is not None else video_duration
    if effective_end <= start:
        effective_end = video_duration

    if mode == "static":
        return f"between(t,{start},{effective_end})"

    # 주기적: 시작~종료 구간 안에서 interval마다 show초 동안 표시
    return (
        f"between(t,{start},{effective_end})*"
        f"between(mod(t,{interval}),0,{show})"
    )


def build_drawtext_filter(
    text: str,
    request: WatermarkRequest,
    video_duration: float,
    font_path: str,
) -> str:
    position = _as_enum(WatermarkPosition, request.position)
    x, y = position_to_xy(position)
    alpha = request.opacity
    escaped_text = escape_drawtext(text)
    escaped_font = escape_font_path(font_path)
    enable = build_enable_expression(
        _enum_str(request.mode),
        request.start_seconds,
        request.end_seconds,
        request.interval_seconds,
        request.show_seconds,
        video_duration,
    )

    return (
        f"drawtext=fontfile='{escaped_font}'"
        f":text='{escaped_text}'"
        f":fontsize={request.font_size}"
        f":fontcolor=white@{alpha}"
        f":box=1:boxcolor=black@0.3:boxborderw=4"
        f":x={x}:y={y}"
        f":enable='{enable}'"
    )


def parse_ffmpeg_progress(line: str, total_duration: float) -> Optional[float]:
    match = re.search(r"time=(\d{2}):(\d{2}):(\d{2}\.\d+)", line)
    if not match or total_duration <= 0:
        return None
    hours, minutes, seconds = match.groups()
    current = int(hours) * 3600 + int(minutes) * 60 + float(seconds)
    return min(100.0, (current / total_duration) * 100)


class WatermarkProcessor:
    def __init__(self) -> None:
        self._ffmpeg = find_ffmpeg()
        self._font_path = get_default_font()
        self._gpu_encoder = detect_gpu_encoder(self._ffmpeg)

    @property
    def gpu_available(self) -> bool:
        return self._gpu_encoder is not None

    @property
    def gpu_encoder_name(self) -> Optional[str]:
        return self._gpu_encoder

    def probe(self, input_path: Path) -> dict:
        return probe_video(input_path)

    def process(
        self,
        input_path: Path,
        output_path: Path,
        request: WatermarkRequest,
        on_progress: Optional[Callable[[float, str], None]] = None,
    ) -> None:
        info = probe_video(input_path)
        duration = info["duration"]
        text = build_watermark_text(request.buyer_name, request.contact)
        vf = build_drawtext_filter(text, request, duration, self._font_path)

        cmd = [
            self._ffmpeg,
            "-y",
            "-i",
            str(input_path),
            "-vf",
            vf,
            "-c:a",
            "copy",
        ]

        use_gpu = request.use_gpu and self._gpu_encoder is not None
        if use_gpu:
            cmd.extend(["-c:v", self._gpu_encoder, "-preset", "p4"])
        else:
            crf = quality_to_crf(_enum_str(request.quality))
            cmd.extend(["-c:v", "libx264", "-crf", str(crf), "-preset", "medium"])

        cmd.extend(["-movflags", "+faststart", str(output_path)])

        if on_progress:
            on_progress(0, "FFmpeg 처리 시작...")

        process = subprocess.Popen(
            cmd,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True,
            encoding="utf-8",
            errors="replace",
        )

        stderr_lines: list[str] = []

        def read_stderr() -> None:
            for line in process.stderr:
                stderr_lines.append(line)
                if on_progress:
                    progress = parse_ffmpeg_progress(line, duration)
                    if progress is not None:
                        on_progress(progress, f"인코딩 중... {progress:.1f}%")

        reader = threading.Thread(target=read_stderr, daemon=True)
        reader.start()
        process.wait()
        reader.join(timeout=5)

        if process.returncode != 0:
            tail = "\n".join(stderr_lines[-20:])
            raise RuntimeError(f"FFmpeg 처리 실패 (코드 {process.returncode}):\n{tail}")

        if on_progress:
            on_progress(100, "완료")
