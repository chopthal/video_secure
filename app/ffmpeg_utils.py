"""FFmpeg 유틸리티: 폰트·인코더·프로브."""

import json
import os
import shutil
import subprocess
import sys
from pathlib import Path


def _winget_ffmpeg_bin_dirs() -> list[Path]:
    """winget Gyan.FFmpeg 패키지의 bin 폴더 (PATH 미등록 시)."""
    local = Path(os.environ.get("LOCALAPPDATA", ""))
    packages = local / "Microsoft" / "WinGet" / "Packages"
    if not packages.is_dir():
        return []

    dirs: list[Path] = []
    for pkg in packages.glob("Gyan.FFmpeg_*"):
        for bin_dir in pkg.glob("ffmpeg-*/bin"):
            if bin_dir.is_dir():
                dirs.append(bin_dir)
    return dirs


def find_ffmpeg_binary(name: str) -> str:
    path = shutil.which(name)
    if path is not None:
        return path

    exe_name = f"{name}.exe" if sys.platform == "win32" else name
    for bin_dir in _winget_ffmpeg_bin_dirs():
        candidate = bin_dir / exe_name
        if candidate.is_file():
            return str(candidate)

    label = "FFmpeg" if name == "ffmpeg" else "ffprobe"
    raise RuntimeError(
        f"{label}를 찾을 수 없습니다. "
        "https://ffmpeg.org 에서 설치하거나 winget install Gyan.FFmpeg 후 "
        "bin 폴더를 PATH에 추가해 주세요."
    )


def find_ffmpeg() -> str:
    return find_ffmpeg_binary("ffmpeg")


def find_ffprobe() -> str:
    return find_ffmpeg_binary("ffprobe")


_SUBPROCESS_TEXT = {"text": True, "encoding": "utf-8", "errors": "replace"}


def get_default_font() -> str:
    candidates: list[Path] = []
    if sys.platform == "win32":
        candidates = [
            Path("C:/Windows/Fonts/malgun.ttf"),
            Path("C:/Windows/Fonts/malgunbd.ttf"),
        ]
    elif sys.platform == "darwin":
        candidates = [
            Path("/System/Library/Fonts/Supplemental/AppleGothic.ttf"),
            Path("/Library/Fonts/Arial Unicode.ttf"),
            Path("/System/Library/Fonts/Supplemental/Arial Unicode.ttf"),
        ]
    else:
        candidates = [
            Path("/usr/share/fonts/truetype/noto/NotoSansCJK-Regular.ttc"),
            Path("/usr/share/fonts/opentype/noto/NotoSansCJK-Regular.ttc"),
            Path("/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf"),
        ]

    for candidate in candidates:
        if candidate.exists():
            return str(candidate)

    raise RuntimeError(
        "한글 워터마크용 폰트를 찾을 수 없습니다. 시스템에 한글 폰트를 설치해 주세요."
    )


def probe_video(path: Path) -> dict:
    ffprobe = find_ffprobe()
    result = subprocess.run(
        [
            ffprobe,
            "-v",
            "quiet",
            "-print_format",
            "json",
            "-show_format",
            "-show_streams",
            str(path),
        ],
        capture_output=True,
        check=True,
        **_SUBPROCESS_TEXT,
    )
    data = json.loads(result.stdout)
    duration = float(data.get("format", {}).get("duration", 0))
    width, height = 0, 0
    for stream in data.get("streams", []):
        if stream.get("codec_type") == "video":
            width = int(stream.get("width", 0))
            height = int(stream.get("height", 0))
            break
    return {
        "duration": duration,
        "width": width,
        "height": height,
        "filename": path.name,
    }


def detect_gpu_encoder(ffmpeg: str) -> str | None:
    result = subprocess.run(
        [ffmpeg, "-hide_banner", "-encoders"],
        capture_output=True,
        **_SUBPROCESS_TEXT,
    )
    encoders = result.stdout + result.stderr
    if "h264_nvenc" in encoders:
        return "h264_nvenc"
    if "h264_qsv" in encoders:
        return "h264_qsv"
    if "h264_amf" in encoders:
        return "h264_amf"
    return None


def quality_to_crf(preset: str) -> int:
    mapping = {"high": 18, "standard": 23, "small": 28}
    return mapping.get(preset, 23)
