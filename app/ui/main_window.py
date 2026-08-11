"""PySide6 메인 윈도우."""

from pathlib import Path

from PySide6.QtCore import Qt
from PySide6.QtGui import QFont
from PySide6.QtWidgets import (
    QCheckBox,
    QComboBox,
    QFileDialog,
    QFormLayout,
    QGroupBox,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QMainWindow,
    QMessageBox,
    QProgressBar,
    QPushButton,
    QScrollArea,
    QSlider,
    QVBoxLayout,
    QWidget,
)

from app.models import QualityPreset, WatermarkMode, WatermarkPosition, WatermarkRequest
from app.time_utils import format_seconds, parse_time_to_seconds
from app.watermark import build_watermark_text, WatermarkProcessor
from app.worker import WatermarkWorker

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
    QualityPreset.HIGH: "고화질 (용량 큼)",
    QualityPreset.STANDARD: "표준",
    QualityPreset.SMALL: "작은 파일 (용량 작음)",
}


def _sanitize_filename(name: str) -> str:
    for ch in '<>:"/\\|?*':
        name = name.replace(ch, "_")
    return name.strip() or "unknown"


class MainWindow(QMainWindow):
    def __init__(self) -> None:
        super().__init__()
        self.setWindowTitle("동영상 보안 처리")
        self.setMinimumSize(520, 720)

        self._input_path: Path | None = None
        self._output_path: Path | None = None
        self._worker: WatermarkWorker | None = None
        self._processor: WatermarkProcessor | None = None
        self._processor_error: str | None = None

        self._build_ui()
        self._init_processor()
        self._wire_events()
        self._update_preview()
        self._toggle_mode_ui()
        self._toggle_end_time_ui()

    def _build_ui(self) -> None:
        root = QWidget()
        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        scroll.setFrameShape(QScrollArea.Shape.NoFrame)

        content = QWidget()
        layout = QVBoxLayout(content)
        layout.setSpacing(12)

        title = QLabel("동영상 보안 처리")
        title_font = QFont()
        title_font.setPointSize(16)
        title_font.setBold(True)
        title.setFont(title_font)

        subtitle = QLabel("모든 처리는 이 PC에서만 수행됩니다. 외부 서버로 전송되지 않습니다.")
        subtitle.setStyleSheet("color: #666;")
        subtitle.setWordWrap(True)

        layout.addWidget(title)
        layout.addWidget(subtitle)

        # 원본 동영상
        file_group = QGroupBox("원본 동영상")
        file_layout = QVBoxLayout(file_group)
        file_row = QHBoxLayout()
        self._file_path_label = QLabel("파일을 선택해 주세요.")
        self._file_path_label.setWordWrap(True)
        self._file_pick_btn = QPushButton("파일 선택")
        file_row.addWidget(self._file_path_label, stretch=1)
        file_row.addWidget(self._file_pick_btn)
        file_layout.addLayout(file_row)
        self._video_info_label = QLabel("")
        self._video_info_label.setStyleSheet("color: #888; font-size: 12px;")
        file_layout.addWidget(self._video_info_label)
        layout.addWidget(file_group)

        # 구매자 정보
        buyer_group = QGroupBox("구매자 정보")
        buyer_form = QFormLayout(buyer_group)
        self._buyer_name = QLineEdit("김개똥")
        self._contact = QLineEdit("01011111111")
        buyer_form.addRow("구매자 이름", self._buyer_name)
        buyer_form.addRow("연락처", self._contact)
        layout.addWidget(buyer_group)

        # 워터마크 설정
        wm_group = QGroupBox("워터마크 설정")
        wm_form = QFormLayout(wm_group)

        self._mode_combo = QComboBox()
        self._mode_combo.addItem("정적 (계속 표시)", WatermarkMode.STATIC)
        self._mode_combo.addItem("주기적 (간격마다 표시)", WatermarkMode.PERIODIC)
        wm_form.addRow("모드", self._mode_combo)

        self._start_time = QLineEdit("00:00:00")
        wm_form.addRow("시작 시간", self._start_time)

        end_row = QWidget()
        end_layout = QHBoxLayout(end_row)
        end_layout.setContentsMargins(0, 0, 0, 0)
        self._end_time = QLineEdit()
        self._end_time.setPlaceholderText("00:30:00")
        self._until_end = QCheckBox("끝까지")
        self._until_end.setChecked(True)
        end_layout.addWidget(self._end_time, stretch=1)
        end_layout.addWidget(self._until_end)
        wm_form.addRow("종료 시간", end_row)

        self._periodic_widget = QWidget()
        periodic_layout = QFormLayout(self._periodic_widget)
        periodic_layout.setContentsMargins(0, 0, 0, 0)
        self._interval_seconds = QLineEdit("30")
        self._show_seconds = QLineEdit("5")
        periodic_layout.addRow("주기 (초)", self._interval_seconds)
        self._interval_hint = QLabel("한 주기 길이 (예: 30 → 30초마다 반복)")
        self._interval_hint.setStyleSheet("color: #888; font-size: 11px;")
        periodic_layout.addRow("", self._interval_hint)
        periodic_layout.addRow("표시 시간 (초)", self._show_seconds)
        self._show_hint = QLabel("주기 안에서 표시할 시간 (주기보다 짧게)")
        self._show_hint.setStyleSheet("color: #888; font-size: 11px;")
        periodic_layout.addRow("", self._show_hint)
        wm_form.addRow(self._periodic_widget)

        self._position_combo = QComboBox()
        for pos, label in POSITION_LABELS.items():
            self._position_combo.addItem(label, pos)
        self._position_combo.setCurrentIndex(5)  # bottom_center
        wm_form.addRow("위치", self._position_combo)

        self._font_size = QLineEdit("24")
        wm_form.addRow("글자 크기", self._font_size)

        opacity_row = QWidget()
        opacity_layout = QHBoxLayout(opacity_row)
        opacity_layout.setContentsMargins(0, 0, 0, 0)
        self._opacity_slider = QSlider(Qt.Orientation.Horizontal)
        self._opacity_slider.setRange(10, 100)
        self._opacity_slider.setValue(70)
        self._opacity_label = QLabel("70%")
        opacity_layout.addWidget(self._opacity_slider, stretch=1)
        opacity_layout.addWidget(self._opacity_label)
        wm_form.addRow("불투명도", opacity_row)

        layout.addWidget(wm_group)

        # 출력 설정
        output_group = QGroupBox("출력 설정")
        output_form = QFormLayout(output_group)

        self._quality_combo = QComboBox()
        for preset, label in QUALITY_LABELS.items():
            self._quality_combo.addItem(label, preset)
        self._quality_combo.setCurrentIndex(1)
        output_form.addRow("출력 품질", self._quality_combo)

        out_row = QWidget()
        out_layout = QHBoxLayout(out_row)
        out_layout.setContentsMargins(0, 0, 0, 0)
        self._output_dir_label = QLabel("원본과 같은 폴더")
        self._output_dir_label.setWordWrap(True)
        self._output_pick_btn = QPushButton("폴더 선택")
        out_layout.addWidget(self._output_dir_label, stretch=1)
        out_layout.addWidget(self._output_pick_btn)
        output_form.addRow("출력 폴더", out_row)
        self._output_dir: Path | None = None

        self._use_gpu = QCheckBox("GPU 가속 사용")
        output_form.addRow(self._use_gpu)
        self._gpu_info = QLabel("")
        self._gpu_info.setStyleSheet("color: #888; font-size: 12px;")
        output_form.addRow(self._gpu_info)

        layout.addWidget(output_group)

        # 미리보기
        preview_group = QGroupBox("미리보기")
        preview_layout = QVBoxLayout(preview_group)
        self._preview_label = QLabel()
        self._preview_label.setWordWrap(True)
        self._preview_label.setStyleSheet(
            "background: #f0f0f0; padding: 12px; border-radius: 4px;"
        )
        preview_layout.addWidget(self._preview_label)
        layout.addWidget(preview_group)

        # 진행률
        self._progress_bar = QProgressBar()
        self._progress_bar.setValue(0)
        self._progress_message = QLabel("")
        self._progress_message.setStyleSheet("color: #888; font-size: 12px;")
        layout.addWidget(self._progress_bar)
        layout.addWidget(self._progress_message)

        # 버튼
        btn_row = QHBoxLayout()
        self._open_output_btn = QPushButton("결과 폴더 열기")
        self._open_output_btn.setEnabled(False)
        self._submit_btn = QPushButton("처리 시작")
        self._submit_btn.setStyleSheet(
            "background: #2e7d32; color: white; font-weight: bold; padding: 10px 20px;"
        )
        btn_row.addWidget(self._open_output_btn)
        btn_row.addStretch()
        btn_row.addWidget(self._submit_btn)
        layout.addLayout(btn_row)

        layout.addStretch()

        scroll.setWidget(content)
        root_layout = QVBoxLayout(root)
        root_layout.setContentsMargins(12, 12, 12, 12)
        root_layout.addWidget(scroll)
        self.setCentralWidget(root)

    def _init_processor(self) -> None:
        try:
            self._processor = WatermarkProcessor()
            if self._processor.gpu_available:
                self._gpu_info.setText(f"사용 가능: {self._processor.gpu_encoder_name}")
                self._use_gpu.setEnabled(True)
            else:
                self._gpu_info.setText("GPU 인코더를 사용할 수 없습니다 (CPU 사용)")
                self._use_gpu.setEnabled(False)
                self._use_gpu.setChecked(False)
        except RuntimeError as exc:
            self._processor_error = str(exc)
            self._processor = None
            self._gpu_info.setText(str(exc))
            self._use_gpu.setEnabled(False)
            self._submit_btn.setEnabled(False)
            QMessageBox.critical(self, "시작 오류", str(exc))

    def _wire_events(self) -> None:
        self._file_pick_btn.clicked.connect(self._pick_video)
        self._output_pick_btn.clicked.connect(self._pick_output_dir)
        self._buyer_name.textChanged.connect(self._update_preview)
        self._contact.textChanged.connect(self._update_preview)
        self._mode_combo.currentIndexChanged.connect(self._toggle_mode_ui)
        self._until_end.toggled.connect(self._toggle_end_time_ui)
        self._opacity_slider.valueChanged.connect(self._update_opacity_label)
        self._submit_btn.clicked.connect(self._start_processing)
        self._open_output_btn.clicked.connect(self._open_output_folder)

    def _update_preview(self) -> None:
        name = self._buyer_name.text().strip() or "김개똥"
        contact = self._contact.text().strip() or "01011111111"
        self._preview_label.setText(build_watermark_text(name, contact))

    def _update_opacity_label(self, value: int) -> None:
        self._opacity_label.setText(f"{value}%")

    def _get_mode(self) -> WatermarkMode:
        data = self._mode_combo.currentData()
        if isinstance(data, WatermarkMode):
            return data
        return WatermarkMode(str(data))

    def _toggle_mode_ui(self) -> None:
        is_periodic = self._get_mode() == WatermarkMode.PERIODIC
        self._periodic_widget.setVisible(is_periodic)

    def _toggle_end_time_ui(self) -> None:
        self._end_time.setEnabled(not self._until_end.isChecked())

    def _pick_video(self) -> None:
        path, _ = QFileDialog.getOpenFileName(
            self,
            "원본 동영상 선택",
            "",
            "동영상 (*.mp4 *.mkv *.mov *.avi *.webm);;모든 파일 (*)",
        )
        if not path:
            return

        self._input_path = Path(path)
        self._file_path_label.setText(str(self._input_path))
        self._open_output_btn.setEnabled(False)
        self._output_path = None

        if self._processor is None:
            self._video_info_label.setText("")
            return

        try:
            info = self._processor.probe(self._input_path)
            self._video_info_label.setText(
                f"{info['filename']} · {format_seconds(info['duration'])} · "
                f"{info['width']}x{info['height']}"
            )
        except Exception as exc:
            self._video_info_label.setText(f"정보 읽기 실패: {exc}")

    def _pick_output_dir(self) -> None:
        path = QFileDialog.getExistingDirectory(self, "출력 폴더 선택")
        if path:
            self._output_dir = Path(path)
            self._output_dir_label.setText(str(self._output_dir))

    def _build_request(self) -> WatermarkRequest | None:
        buyer = self._buyer_name.text().strip()
        contact = self._contact.text().strip()
        if not buyer or not contact:
            QMessageBox.warning(self, "입력 오류", "구매자 이름과 연락처를 입력해 주세요.")
            return None

        start = parse_time_to_seconds(self._start_time.text())
        if start is None or start < 0:
            QMessageBox.warning(
                self, "입력 오류", "시작 시간 형식이 올바르지 않습니다. (예: 00:05:00)"
            )
            return None

        end: float | None = None
        if not self._until_end.isChecked():
            parsed_end = parse_time_to_seconds(self._end_time.text())
            if parsed_end is None or parsed_end < 0:
                QMessageBox.warning(self, "입력 오류", "종료 시간 형식이 올바르지 않습니다.")
                return None
            if parsed_end <= start:
                QMessageBox.warning(self, "입력 오류", "종료 시간은 시작 시간보다 뒤여야 합니다.")
                return None
            end = parsed_end

        try:
            font_size = int(self._font_size.text().strip())
            if not 8 <= font_size <= 120:
                raise ValueError
        except ValueError:
            QMessageBox.warning(self, "입력 오류", "글자 크기는 8~120 사이여야 합니다.")
            return None

        interval = 30.0
        show = 5.0
        mode = self._get_mode()
        if mode == WatermarkMode.PERIODIC:
            try:
                interval = float(self._interval_seconds.text().strip())
                show = float(self._show_seconds.text().strip())
                if interval <= 0 or show <= 0:
                    raise ValueError
            except ValueError:
                QMessageBox.warning(self, "입력 오류", "주기와 표시 시간은 0보다 커야 합니다.")
                return None
            if show >= interval:
                QMessageBox.warning(
                    self,
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
            position=self._position_combo.currentData(),
            font_size=font_size,
            opacity=self._opacity_slider.value() / 100.0,
            quality=self._quality_combo.currentData(),
            use_gpu=self._use_gpu.isChecked(),
        )

    def _resolve_output_path(self, request: WatermarkRequest) -> Path | None:
        if self._input_path is None:
            return None

        out_dir = self._output_dir or self._input_path.parent
        buyer = _sanitize_filename(request.buyer_name)
        stem = self._input_path.stem
        return out_dir / f"{buyer}_{stem}.mp4"

    def _start_processing(self) -> None:
        if self._processor is None:
            QMessageBox.critical(self, "오류", self._processor_error or "FFmpeg를 사용할 수 없습니다.")
            return

        if self._input_path is None:
            QMessageBox.warning(self, "입력 오류", "원본 동영상을 선택해 주세요.")
            return

        if self._worker is not None and self._worker.isRunning():
            return

        request = self._build_request()
        if request is None:
            return

        output_path = self._resolve_output_path(request)
        if output_path is None:
            return

        self._output_path = output_path
        self._progress_bar.setValue(0)
        self._progress_message.setText("준비 중...")
        self._submit_btn.setEnabled(False)
        self._open_output_btn.setEnabled(False)

        self._worker = WatermarkWorker(
            self._processor,
            self._input_path,
            output_path,
            request,
        )
        self._worker.progress_changed.connect(self._on_progress)
        self._worker.completed.connect(self._on_completed)
        self._worker.failed.connect(self._on_failed)
        self._worker.start()

    def _on_progress(self, progress: float, message: str) -> None:
        self._progress_bar.setValue(int(progress))
        self._progress_message.setText(message)

    def _on_completed(self, output_path: str) -> None:
        self._output_path = Path(output_path)
        self._progress_bar.setValue(100)
        self._progress_message.setText("완료")
        self._submit_btn.setEnabled(True)
        self._open_output_btn.setEnabled(True)
        QMessageBox.information(
            self,
            "완료",
            f"처리가 완료되었습니다.\n\n{output_path}",
        )

    def _on_failed(self, error: str) -> None:
        self._progress_message.setText("실패")
        self._submit_btn.setEnabled(True)
        QMessageBox.critical(self, "처리 실패", error)

    def _open_output_folder(self) -> None:
        if self._output_path is None:
            return
        folder = str(self._output_path.parent)
        import os
        import subprocess
        import sys

        if sys.platform == "win32":
            os.startfile(folder)  # noqa: S606
        elif sys.platform == "darwin":
            subprocess.run(["open", folder], check=False)
        else:
            subprocess.run(["xdg-open", folder], check=False)
