"""시간 문자열 파싱·포맷."""

from typing import Optional


def format_seconds(seconds: float) -> str:
    total = int(seconds)
    hours = total // 3600
    minutes = (total % 3600) // 60
    secs = total % 60
    return f"{hours:02d}:{minutes:02d}:{secs:02d}"


def parse_time_to_seconds(text: str) -> Optional[float]:
    trimmed = text.strip()
    if not trimmed:
        return None

    if ":" not in trimmed:
        try:
            return float(trimmed)
        except ValueError:
            return None

    parts = trimmed.split(":")
    try:
        numbers = [float(p) for p in parts]
    except ValueError:
        return None

    if len(numbers) == 3:
        return numbers[0] * 3600 + numbers[1] * 60 + numbers[2]
    if len(numbers) == 2:
        return numbers[0] * 60 + numbers[1]
    return None
