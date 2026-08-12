"""일괄 처리용 구매자 파싱·파일명 유틸."""

from __future__ import annotations

import csv
import io
import re
from dataclasses import dataclass
from pathlib import Path


@dataclass
class BuyerInfo:
    name: str
    contact: str


def sanitize_filename(name: str) -> str:
    for ch in '<>:"/\\|?*':
        name = name.replace(ch, "_")
    return name.strip() or "unknown"


def parse_buyer_lines(text: str) -> list[BuyerInfo]:
    """
    엑셀/메모장에서 붙여넣은 텍스트를 구매자 목록으로 변환.

    지원 형식:
    - 이름<TAB>연락처
    - 이름,연락처
    - 이름 연락처 (공백)
    """
    buyers: list[BuyerInfo] = []
    for raw in text.splitlines():
        line = raw.strip()
        if not line:
            continue
        # 헤더 스킵
        lower = line.lower().replace(" ", "")
        if lower in {"이름,연락처", "name,contact", "구매자,연락처"}:
            continue
        if "\t" in line:
            parts = [p.strip() for p in line.split("\t") if p.strip()]
        elif "," in line:
            parts = [p.strip() for p in line.split(",") if p.strip()]
        else:
            parts = re.split(r"\s+", line, maxsplit=1)
            parts = [p.strip() for p in parts if p.strip()]

        if len(parts) < 2:
            continue
        name, contact = parts[0], parts[1]
        if name and contact:
            buyers.append(BuyerInfo(name=name, contact=contact))
    return buyers


def load_buyers_from_csv(path: Path) -> list[BuyerInfo]:
    text = path.read_text(encoding="utf-8-sig")
    # 탭/쉼표 자동 판별
    sample = text[:2048]
    try:
        dialect = csv.Sniffer().sniff(sample, delimiters=",\t;")
    except csv.Error:
        dialect = csv.excel

    readers = csv.reader(io.StringIO(text), dialect)
    buyers: list[BuyerInfo] = []
    for i, row in enumerate(readers):
        cells = [c.strip() for c in row if c.strip()]
        if len(cells) < 2:
            continue
        if i == 0 and cells[0] in {"이름", "name", "구매자", "Name"}:
            continue
        buyers.append(BuyerInfo(name=cells[0], contact=cells[1]))
    return buyers


def build_output_path(output_dir: Path, buyer_name: str, input_path: Path) -> Path:
    buyer = sanitize_filename(buyer_name)
    return output_dir / f"{buyer}_{input_path.stem}.mp4"
