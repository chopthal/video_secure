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
    video_bitrate: int | None = None
    audio_bitrate = 0
    codec_name = ""
    for stream in data.get("streams", []):
        if stream.get("codec_type") == "audio" and stream.get("bit_rate"):
            audio_bitrate += int(stream.get("bit_rate", 0))
        if stream.get("codec_type") == "video":
            width = int(stream.get("width", 0))
            height = int(stream.get("height", 0))
            codec_name = stream.get("codec_name", "") or ""
            if stream.get("bit_rate"):
                video_bitrate = int(stream.get("bit_rate"))

    if video_bitrate is None:
        format_bitrate = data.get("format", {}).get("bit_rate")
        if format_bitrate:
            video_bitrate = max(int(format_bitrate) - audio_bitrate, 0) or None

    # MOV/HEVC 등에서 bit_rate가 비어 있으면 파일 크기로 추정
    if (video_bitrate is None or video_bitrate < 100_000) and duration > 0:
        try:
            size_bits = path.stat().st_size * 8
            estimated = int(size_bits / duration) - audio_bitrate
            if estimated > 100_000:
                video_bitrate = estimated
        except OSError:
            pass

    return {
        "duration": duration,
        "width": width,
        "height": height,
        "filename": path.name,
        "video_bitrate": video_bitrate,
        "codec_name": codec_name,
    }


def is_hevc_codec(codec_name: str) -> bool:
    return codec_name.lower() in {"hevc", "h265", "hev1", "hvc1"}


def detect_gpu_encoders(ffmpeg: str) -> dict[str, str | None]:
    """가용 GPU 인코더. keys: h264, hevc."""
    result = subprocess.run(
        [ffmpeg, "-hide_banner", "-encoders"],
        capture_output=True,
        **_SUBPROCESS_TEXT,
    )
    encoders = result.stdout + result.stderr
    h264 = None
    hevc = None
    if "h264_nvenc" in encoders:
        h264 = "h264_nvenc"
    elif "h264_qsv" in encoders:
        h264 = "h264_qsv"
    elif "h264_amf" in encoders:
        h264 = "h264_amf"

    if "hevc_nvenc" in encoders:
        hevc = "hevc_nvenc"
    elif "hevc_qsv" in encoders:
        hevc = "hevc_qsv"
    elif "hevc_amf" in encoders:
        hevc = "hevc_amf"

    return {"h264": h264, "hevc": hevc}


def detect_gpu_encoder(ffmpeg: str) -> str | None:
    """하위 호환: H.264 GPU 인코더 우선."""
    found = detect_gpu_encoders(ffmpeg)
    return found["h264"] or found["hevc"]


def _bitrate_floor_kbps(width: int, height: int) -> int:
    pixels = max(width * height, 1)
    if pixels >= 1920 * 1080:
        return 8_000
    if pixels >= 1280 * 720:
        return 5_000
    return 2_500


def resolve_target_bitrate_kbps(
    quality: str,
    source_video_bitrate: int | None,
    width: int = 0,
    height: int = 0,
    keep_hevc: bool = False,
) -> int:
    floor = _bitrate_floor_kbps(width, height)
    source_kbps = int(source_video_bitrate / 1000) if source_video_bitrate else 0

    if quality == "high":
        # 원본 코덱 유지: 비트레이트도 원본에 맞춤 (HEVC→HEVC는 부스트 불필요)
        if source_kbps > 0:
            return max(source_kbps if keep_hevc else int(source_kbps * 1.15), floor)
        return max(floor, 12_000 if keep_hevc else 14_000)

    if quality == "medium":
        if source_kbps > 0:
            return max(int(source_kbps * 0.7), floor)
        return max(floor, 8_000)

    # low
    if source_kbps > 0:
        return max(int(source_kbps * 0.4), 2_000)
    return 4_000


def _append_bitrate_args(args: list[str], target_kbps: int) -> None:
    maxrate = int(target_kbps * 1.5)
    bufsize = int(target_kbps * 2)
    args.extend(
        [
            "-b:v",
            f"{target_kbps}k",
            "-maxrate",
            f"{maxrate}k",
            "-bufsize",
            f"{bufsize}k",
        ]
    )


def _build_h264_gpu_args(
    encoder: str, quality: str, target_kbps: int, cq: int
) -> list[str]:
    args = ["-c:v", encoder]
    if quality == "low":
        if encoder == "h264_nvenc":
            args.extend(["-rc", "vbr", "-cq", str(cq), "-b:v", "0", "-preset", "p4"])
        elif encoder == "h264_qsv":
            args.extend(["-global_quality", str(cq)])
        else:
            args.extend(["-rc", "vbr_latency", "-qp_i", str(cq), "-qp_p", str(cq)])
    else:
        _append_bitrate_args(args, target_kbps)
        if encoder == "h264_nvenc":
            args.extend(["-rc", "vbr", "-cq", str(cq), "-preset", "p5" if quality == "high" else "p4"])
        elif encoder == "h264_amf":
            args.extend(["-rc", "vbr_peak"])
    args.extend(["-pix_fmt", "yuv420p", "-profile:v", "high", "-level", "4.2"])
    return args


def _build_hevc_gpu_args(encoder: str, target_kbps: int, cq: int) -> list[str]:
    args = ["-c:v", encoder]
    _append_bitrate_args(args, target_kbps)
    if encoder == "hevc_nvenc":
        args.extend(["-rc", "vbr", "-cq", str(cq), "-preset", "p5"])
    elif encoder == "hevc_amf":
        args.extend(["-rc", "vbr_peak"])
    # Apple/모바일 MP4 HEVC 호환 태그
    args.extend(["-pix_fmt", "yuv420p", "-tag:v", "hvc1"])
    return args


def build_video_encoder_args(
    gpu_encoders: dict[str, str | None] | str | None,
    quality: str,
    use_gpu: bool,
    source_video_bitrate: int | None = None,
    width: int = 0,
    height: int = 0,
    codec_name: str = "",
) -> list[str]:
    """
    품질 프리셋별 인코더 옵션.

    - high: 원본이 HEVC면 HEVC, 아니면 H.264 (비트레이트 ≈ 원본)
    - medium / low: 항상 H.264
    """
    if isinstance(gpu_encoders, str) or gpu_encoders is None:
        # 하위 호환: 단일 문자열이면 H.264로 취급
        gpu_encoders = {"h264": gpu_encoders, "hevc": None}

    keep_hevc = quality == "high" and is_hevc_codec(codec_name)
    target_kbps = resolve_target_bitrate_kbps(
        quality, source_video_bitrate, width, height, keep_hevc=keep_hevc
    )
    cq_map = {"high": 18, "medium": 23, "low": 28}
    cq = cq_map.get(quality, 23)

    if keep_hevc:
        hevc_gpu = gpu_encoders.get("hevc") if use_gpu else None
        if hevc_gpu:
            return _build_hevc_gpu_args(hevc_gpu, target_kbps, cq)
        # CPU libx265 — 원본 비트레이트에 맞춤
        args = [
            "-c:v",
            "libx265",
            "-preset",
            "medium",
            "-x265-params",
            "log-level=error",
        ]
        _append_bitrate_args(args, target_kbps)
        args.extend(["-pix_fmt", "yuv420p", "-tag:v", "hvc1"])
        return args

    # H.264 경로 (중간/저품질, 또는 원본이 H.264인 고품질)
    h264_gpu = gpu_encoders.get("h264") if use_gpu else None
    if h264_gpu:
        return _build_h264_gpu_args(h264_gpu, quality, target_kbps, cq)

    preset = "slow" if quality == "high" else "medium"
    args = ["-c:v", "libx264", "-preset", preset]
    if quality == "low":
        args.extend(["-crf", str(cq)])
    else:
        _append_bitrate_args(args, target_kbps)
    args.extend(["-pix_fmt", "yuv420p", "-profile:v", "high", "-level", "4.2"])
    return args
