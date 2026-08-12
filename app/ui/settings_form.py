"""공유 워터마크·출력 설정 폼."""

from __future__ import annotations

from pathlib import Path

from PySide6.QtCore import Qt
from PySide6.QtWidgets import (
    QCheckBox,
    QComboBox,
    QFileDialog,
    QFormLayout,
    QGroupBox,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QMessageBox,
    QSlider,
    QVBoxLayout,
    QWidget,
    QPushButton,
)

from app.models import QualityPreset, WatermarkMode, WatermarkPosition, WatermarkRequest
from app.time_utils import parse_time_to_seconds

POSITION_LABELS: dict[WatermarkPosition, str] = {
    WatermarkPosition.TOP_LEFT: "상단 좌",
    WatermarkPosition.TOP_CENTER: "상단 중앙",
    WatermarkPosition.TOP_RIGHT: "상단 우",
    WatermarkPosition.CENTER: "중앙",
    WatermarkPosition.BOTTOM_LEFT: "하단 좌",
    WatermarkPosition.BOTTOM_CENTER: "하단 중앙",
    WatermarkPosition.BOTTOM_RIGHT: "하단 우",
}

QUALITY_LABELS: dict[QualityPreset, str] = {
    QualityPreset.HIGH: "고품질 (원본 코덱 사용)",
    QualityPreset.MEDIUM: "중간 (H.264)",
    QualityPreset.LOW: "저품질",
}


class WatermarkSettingsForm(QWidget):
    """모드·위치·품질 등 공통 설정. 구매자 정보는 외부에서 주입."""

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.output_dir: Path | None = None
        self._build()

    def _build(self) -> None:
        root = QVBoxLayout(self)
        root.setContentsMargins(0, 0, 0, 0)

        wm_group = QGroupBox("워터마크 설정")
        wm_form = QFormLayout(wm_group)

        self.mode_combo = QComboBox()
        self.mode_combo.addItem("정적 (계속 표시)", WatermarkMode.STATIC)
        self.mode_combo.addItem("주기적 (간격마다 표시)", WatermarkMode.PERIODIC)
        wm_form.addRow("모드", self.mode_combo)

        self.start_time = QLineEdit("00:00:00")
        wm_form.addRow("시작 시간", self.start_time)

        end_row = QWidget()
        end_layout = QHBoxLayout(end_row)
        end_layout.setContentsMargins(0, 0, 0, 0)
        self.end_time = QLineEdit()
        self.end_time.setPlaceholderText("00:30:00")
        self.until_end = QCheckBox("끝까지")
        self.until_end.setChecked(True)
        end_layout.addWidget(self.end_time, stretch=1)
        end_layout.addWidget(self.until_end)
        wm_form.addRow("종료 시간", end_row)

        self.periodic_widget = QWidget()
        periodic_layout = QFormLayout(self.periodic_widget)
        periodic_layout.setContentsMargins(0, 0, 0, 0)
        self.interval_seconds = QLineEdit("30")
        self.show_seconds = QLineEdit("5")
        periodic_layout.addRow("주기 (초)", self.interval_seconds)
        interval_hint = QLabel("한 주기 길이 (예: 30 → 30초마다 반복)")
        interval_hint.setStyleSheet("color: #888; font-size: 11px;")
        periodic_layout.addRow("", interval_hint)
        periodic_layout.addRow("표시 시간 (초)", self.show_seconds)
        show_hint = QLabel("주기 안에서 표시할 시간 (주기보다 짧게)")
        show_hint.setStyleSheet("color: #888; font-size: 11px;")
        periodic_layout.addRow("", show_hint)
        wm_form.addRow(self.periodic_widget)

        self.position_combo = QComboBox()
        for pos, label in POSITION_LABELS.items():
            self.position_combo.addItem(label, pos)
        self.position_combo.setCurrentIndex(0)
        wm_form.addRow("위치", self.position_combo)

        self.font_size = QLineEdit("24")
        wm_form.addRow("글자 크기", self.font_size)

        opacity_row = QWidget()
        opacity_layout = QHBoxLayout(opacity_row)
        opacity_layout.setContentsMargins(0, 0, 0, 0)
        self.opacity_slider = QSlider(Qt.Orientation.Horizontal)
        self.opacity_slider.setRange(10, 100)
        self.opacity_slider.setValue(70)
        self.opacity_label = QLabel("70%")
        opacity_layout.addWidget(self.opacity_slider, stretch=1)
        opacity_layout.addWidget(self.opacity_label)
        wm_form.addRow("불투명도", opacity_row)
        root.addWidget(wm_group)

        output_group = QGroupBox("출력 설정")
        output_form = QFormLayout(output_group)

        self.quality_combo = QComboBox()
        for preset, label in QUALITY_LABELS.items():
            self.quality_combo.addItem(label, preset)
        self.quality_combo.setCurrentIndex(0)
        output_form.addRow("출력 품질", self.quality_combo)

        out_row = QWidget()
        out_layout = QHBoxLayout(out_row)
        out_layout.setContentsMargins(0, 0, 0, 0)
        self.output_dir_label = QLabel("원본과 같은 폴더")
        self.output_dir_label.setWordWrap(True)
        self.output_pick_btn = QPushButton("폴더 선택")
        out_layout.addWidget(self.output_dir_label, stretch=1)
        out_layout.addWidget(self.output_pick_btn)
        output_form.addRow("출력 폴더", out_row)

        self.use_gpu = QCheckBox("GPU 가속 사용")
        output_form.addRow(self.use_gpu)
        self.gpu_info = QLabel("")
        self.gpu_info.setStyleSheet("color: #888; font-size: 12px;")
        output_form.addRow(self.gpu_info)
        root.addWidget(output_group)

        self.mode_combo.currentIndexChanged.connect(self._toggle_mode_ui)
        self.until_end.toggled.connect(self._toggle_end_time_ui)
        self.opacity_slider.valueChanged.connect(
            lambda v: self.opacity_label.setText(f"{v}%")
        )
        self.output_pick_btn.clicked.connect(self._pick_output_dir)
        self._toggle_mode_ui()
        self._toggle_end_time_ui()

    def _get_mode(self) -> WatermarkMode:
        data = self.mode_combo.currentData()
        if isinstance(data, WatermarkMode):
            return data
        return WatermarkMode(str(data))

    def _get_quality(self) -> QualityPreset:
        data = self.quality_combo.currentData()
        if isinstance(data, QualityPreset):
            return data
        return QualityPreset(str(data))

    def _get_position(self) -> WatermarkPosition:
        data = self.position_combo.currentData()
        if isinstance(data, WatermarkPosition):
            return data
        return WatermarkPosition(str(data))

    def _toggle_mode_ui(self) -> None:
        self.periodic_widget.setVisible(self._get_mode() == WatermarkMode.PERIODIC)

    def _toggle_end_time_ui(self) -> None:
        self.end_time.setEnabled(not self.until_end.isChecked())

    def _pick_output_dir(self) -> None:
        path = QFileDialog.getExistingDirectory(self, "출력 폴더 선택")
        if path:
            self.output_dir = Path(path)
            self.output_dir_label.setText(str(self.output_dir))

    def set_gpu_status(self, available: bool, info: str) -> None:
        self.gpu_info.setText(info)
        self.use_gpu.setEnabled(available)
        if not available:
            self.use_gpu.setChecked(False)

    def build_request(
        self, buyer_name: str, contact: str, parent: QWidget | None = None
    ) -> WatermarkRequest | None:
        host = parent or self
        buyer = buyer_name.strip()
        contact = contact.strip()
        if not buyer or not contact:
            QMessageBox.warning(host, "입력 오류", "구매자 이름과 연락처를 입력해 주세요.")
            return None

        start = parse_time_to_seconds(self.start_time.text())
        if start is None or start < 0:
            QMessageBox.warning(
                host, "입력 오류", "시작 시간 형식이 올바르지 않습니다. (예: 00:05:00)"
            )
            return None

        end: float | None = None
        if not self.until_end.isChecked():
            parsed_end = parse_time_to_seconds(self.end_time.text())
            if parsed_end is None or parsed_end < 0:
                QMessageBox.warning(host, "입력 오류", "종료 시간 형식이 올바르지 않습니다.")
                return None
            if parsed_end <= start:
                QMessageBox.warning(host, "입력 오류", "종료 시간은 시작 시간보다 뒤여야 합니다.")
                return None
            end = parsed_end

        try:
            font_size = int(self.font_size.text().strip())
            if not 8 <= font_size <= 120:
                raise ValueError
        except ValueError:
            QMessageBox.warning(host, "입력 오류", "글자 크기는 8~120 사이여야 합니다.")
            return None

        interval = 30.0
        show = 5.0
        mode = self._get_mode()
        if mode == WatermarkMode.PERIODIC:
            try:
                interval = float(self.interval_seconds.text().strip())
                show = float(self.show_seconds.text().strip())
                if interval <= 0 or show <= 0:
                    raise ValueError
            except ValueError:
                QMessageBox.warning(host, "입력 오류", "주기와 표시 시간은 0보다 커야 합니다.")
                return None
            if show >= interval:
                QMessageBox.warning(
                    host,
                    "입력 오류",
                    "표시 시간이 주기와 같거나 길면 워터마크가 계속 표시됩니다.\n"
                    "표시 시간을 주기보다 짧게 설정해 주세요.\n"
                    "(예: 주기 10초, 표시 3초)",
                )
                return None

        return WatermarkRequest(
            buyer_name=buyer,
            contact=contact,
            mode=mode,
            start_seconds=start,
            end_seconds=end,
            interval_seconds=interval,
            show_seconds=show,
            position=self._get_position(),
            font_size=font_size,
            opacity=self.opacity_slider.value() / 100.0,
            quality=self._get_quality(),
            use_gpu=self.use_gpu.isChecked(),
        )
