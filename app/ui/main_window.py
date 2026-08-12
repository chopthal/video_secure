"""PySide6 메인 윈도우 — 단일 / 일괄 처리 탭."""

from __future__ import annotations

import os
import subprocess
import sys
from pathlib import Path

from PySide6.QtGui import QFont
from PySide6.QtWidgets import (
    QGroupBox,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QMainWindow,
    QMessageBox,
    QProgressBar,
    QPushButton,
    QScrollArea,
    QTabWidget,
    QVBoxLayout,
    QWidget,
    QFileDialog,
    QFormLayout,
)

from app.batch_utils import build_output_path
from app.ui.batch_panel import BatchPanel
from app.ui.settings_form import WatermarkSettingsForm
from app.time_utils import format_seconds
from app.watermark import build_watermark_text, WatermarkProcessor
from app.worker import WatermarkWorker


class SinglePanel(QWidget):
    def __init__(
        self,
        processor: WatermarkProcessor | None,
        processor_error: str | None = None,
        parent: QWidget | None = None,
    ) -> None:
        super().__init__(parent)
        self._processor = processor
        self._processor_error = processor_error
        self._input_path: Path | None = None
        self._output_path: Path | None = None
        self._worker: WatermarkWorker | None = None

        self._build_ui()
        if processor and processor.gpu_available:
            self.settings.set_gpu_status(True, f"사용 가능: {processor.gpu_encoder_name}")
        else:
            msg = processor_error or "GPU 인코더를 사용할 수 없습니다 (CPU 사용)"
            self.settings.set_gpu_status(False, msg)
            if processor is None:
                self._submit_btn.setEnabled(False)

        self._buyer_name.textChanged.connect(self._update_preview)
        self._contact.textChanged.connect(self._update_preview)
        self._file_pick_btn.clicked.connect(self._pick_video)
        self._submit_btn.clicked.connect(self._start_processing)
        self._open_output_btn.clicked.connect(self._open_output_folder)
        self._update_preview()

    def _build_ui(self) -> None:
        layout = QVBoxLayout(self)
        layout.setSpacing(12)

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

        buyer_group = QGroupBox("구매자 정보")
        buyer_form = QFormLayout(buyer_group)
        self._buyer_name = QLineEdit("김개똥")
        self._contact = QLineEdit("01011111111")
        buyer_form.addRow("구매자 이름", self._buyer_name)
        buyer_form.addRow("연락처", self._contact)
        layout.addWidget(buyer_group)

        self.settings = WatermarkSettingsForm()
        layout.addWidget(self.settings)

        preview_group = QGroupBox("미리보기")
        preview_layout = QVBoxLayout(preview_group)
        self._preview_label = QLabel()
        self._preview_label.setWordWrap(True)
        self._preview_label.setStyleSheet(
            "background: #f0f0f0; padding: 12px; border-radius: 4px;"
        )
        preview_layout.addWidget(self._preview_label)
        layout.addWidget(preview_group)

        self._progress_bar = QProgressBar()
        self._progress_bar.setValue(0)
        self._progress_message = QLabel("")
        self._progress_message.setStyleSheet("color: #888; font-size: 12px;")
        layout.addWidget(self._progress_bar)
        layout.addWidget(self._progress_message)

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

    def _update_preview(self) -> None:
        name = self._buyer_name.text().strip() or "김개똥"
        contact = self._contact.text().strip() or "01011111111"
        self._preview_label.setText(build_watermark_text(name, contact))

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
                + (
                    f" · {info['video_bitrate'] // 1000}kbps"
                    if info.get("video_bitrate")
                    else ""
                )
                + (f" · {info['codec_name']}" if info.get("codec_name") else "")
            )
        except Exception as exc:
            self._video_info_label.setText(f"정보 읽기 실패: {exc}")

    def _start_processing(self) -> None:
        if self._processor is None:
            QMessageBox.critical(
                self, "오류", self._processor_error or "FFmpeg를 사용할 수 없습니다."
            )
            return
        if self._input_path is None:
            QMessageBox.warning(self, "입력 오류", "원본 동영상을 선택해 주세요.")
            return
        if self._worker is not None and self._worker.isRunning():
            return

        request = self.settings.build_request(
            self._buyer_name.text(), self._contact.text(), self
        )
        if request is None:
            return

        out_dir = self.settings.output_dir or self._input_path.parent
        output_path = build_output_path(out_dir, request.buyer_name, self._input_path)

        self._output_path = output_path
        self._progress_bar.setValue(0)
        self._progress_message.setText("준비 중...")
        self._submit_btn.setEnabled(False)
        self._open_output_btn.setEnabled(False)

        self._worker = WatermarkWorker(
            self._processor, self._input_path, output_path, request
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
        QMessageBox.information(self, "완료", f"처리가 완료되었습니다.\n\n{output_path}")

    def _on_failed(self, error: str) -> None:
        self._progress_message.setText("실패")
        self._submit_btn.setEnabled(True)
        QMessageBox.critical(self, "처리 실패", error)

    def _open_output_folder(self) -> None:
        if self._output_path is None:
            return
        folder = str(self._output_path.parent)
        if sys.platform == "win32":
            os.startfile(folder)  # noqa: S606
        elif sys.platform == "darwin":
            subprocess.run(["open", folder], check=False)
        else:
            subprocess.run(["xdg-open", folder], check=False)


class MainWindow(QMainWindow):
    def __init__(self) -> None:
        super().__init__()
        self.setWindowTitle("동영상 보안 처리")
        self.setMinimumSize(560, 760)

        self._processor: WatermarkProcessor | None = None
        self._processor_error: str | None = None
        try:
            self._processor = WatermarkProcessor()
        except RuntimeError as exc:
            self._processor_error = str(exc)
            QMessageBox.critical(self, "시작 오류", str(exc))

        root = QWidget()
        root_layout = QVBoxLayout(root)
        root_layout.setContentsMargins(12, 12, 12, 12)

        title = QLabel("동영상 보안 처리")
        title_font = QFont()
        title_font.setPointSize(16)
        title_font.setBold(True)
        title.setFont(title_font)
        subtitle = QLabel("모든 처리는 이 PC에서만 수행됩니다. 외부 서버로 전송되지 않습니다.")
        subtitle.setStyleSheet("color: #666;")
        subtitle.setWordWrap(True)
        root_layout.addWidget(title)
        root_layout.addWidget(subtitle)

        tabs = QTabWidget()
        single = SinglePanel(self._processor, self._processor_error)
        batch = BatchPanel(self._processor, self._processor_error)

        single_scroll = QScrollArea()
        single_scroll.setWidgetResizable(True)
        single_scroll.setFrameShape(QScrollArea.Shape.NoFrame)
        single_scroll.setWidget(single)

        batch_scroll = QScrollArea()
        batch_scroll.setWidgetResizable(True)
        batch_scroll.setFrameShape(QScrollArea.Shape.NoFrame)
        batch_scroll.setWidget(batch)

        tabs.addTab(single_scroll, "단일 처리")
        tabs.addTab(batch_scroll, "일괄 처리")
        root_layout.addWidget(tabs)
        self.setCentralWidget(root)
