"""일괄 처리 패널: 다중 영상 × 구매자 목록."""

from __future__ import annotations

import os
import subprocess
import sys
from pathlib import Path

from PySide6.QtGui import QKeySequence, QShortcut
from PySide6.QtWidgets import (
    QAbstractItemView,
    QFileDialog,
    QGroupBox,
    QHBoxLayout,
    QLabel,
    QListWidget,
    QMessageBox,
    QProgressBar,
    QPushButton,
    QTableWidget,
    QTableWidgetItem,
    QVBoxLayout,
    QWidget,
)

from app.models import WatermarkRequest
from app.batch_utils import (
    BuyerInfo,
    build_output_path,
    load_buyers_from_csv,
    parse_buyer_lines,
)
from app.ui.settings_form import WatermarkSettingsForm
from app.worker import BatchJob, BatchWatermarkWorker
from app.watermark import WatermarkProcessor


class BatchPanel(QWidget):
    def __init__(
        self,
        processor: WatermarkProcessor | None,
        processor_error: str | None = None,
        parent: QWidget | None = None,
    ) -> None:
        super().__init__(parent)
        self._processor = processor
        self._processor_error = processor_error
        self._videos: list[Path] = []
        self._worker: BatchWatermarkWorker | None = None
        self._last_output_dir: Path | None = None

        self._build_ui()
        if processor and processor.gpu_available:
            self.settings.set_gpu_status(True, f"사용 가능: {processor.gpu_encoder_name}")
        else:
            msg = processor_error or "GPU 인코더를 사용할 수 없습니다 (CPU 사용)"
            self.settings.set_gpu_status(False, msg)
            if processor is None:
                self._start_btn.setEnabled(False)

    def _build_ui(self) -> None:
        layout = QVBoxLayout(self)
        layout.setSpacing(12)

        hint = QLabel(
            "영상 여러 개 × 구매자 여러 명 = 전체 조합으로 일괄 처리합니다.\n"
            "구매자 표에 엑셀에서 복사한 내용을 Ctrl+V로 붙여넣을 수 있습니다."
        )
        hint.setStyleSheet("color: #666;")
        hint.setWordWrap(True)
        layout.addWidget(hint)

        # 영상 목록
        video_group = QGroupBox("원본 동영상 (여러 개)")
        video_layout = QVBoxLayout(video_group)
        self._video_list = QListWidget()
        self._video_list.setSelectionMode(QAbstractItemView.SelectionMode.ExtendedSelection)
        self._video_list.setMinimumHeight(100)
        video_layout.addWidget(self._video_list)

        video_btns = QHBoxLayout()
        self._add_videos_btn = QPushButton("영상 추가")
        self._remove_videos_btn = QPushButton("선택 제거")
        self._clear_videos_btn = QPushButton("전체 비우기")
        video_btns.addWidget(self._add_videos_btn)
        video_btns.addWidget(self._remove_videos_btn)
        video_btns.addWidget(self._clear_videos_btn)
        video_btns.addStretch()
        video_layout.addLayout(video_btns)
        layout.addWidget(video_group)

        # 구매자 표
        buyer_group = QGroupBox("구매자 목록")
        buyer_layout = QVBoxLayout(buyer_group)
        self._buyer_table = QTableWidget(0, 2)
        self._buyer_table.setHorizontalHeaderLabels(["이름", "연락처"])
        self._buyer_table.horizontalHeader().setStretchLastSection(True)
        self._buyer_table.setMinimumHeight(140)
        self._buyer_table.setSelectionBehavior(QAbstractItemView.SelectionBehavior.SelectRows)
        buyer_layout.addWidget(self._buyer_table)

        buyer_btns = QHBoxLayout()
        self._add_row_btn = QPushButton("행 추가")
        self._remove_row_btn = QPushButton("선택 행 삭제")
        self._paste_btn = QPushButton("붙여넣기")
        self._csv_btn = QPushButton("CSV 불러오기")
        self._clear_buyers_btn = QPushButton("전체 비우기")
        buyer_btns.addWidget(self._add_row_btn)
        buyer_btns.addWidget(self._remove_row_btn)
        buyer_btns.addWidget(self._paste_btn)
        buyer_btns.addWidget(self._csv_btn)
        buyer_btns.addWidget(self._clear_buyers_btn)
        buyer_btns.addStretch()
        buyer_layout.addLayout(buyer_btns)

        paste_hint = QLabel("형식: 이름[TAB]연락처 또는 이름,연락처 (한 줄에 한 명)")
        paste_hint.setStyleSheet("color: #888; font-size: 11px;")
        buyer_layout.addWidget(paste_hint)
        layout.addWidget(buyer_group)

        self._job_summary = QLabel("예상 작업: 0개")
        self._job_summary.setStyleSheet("font-weight: bold;")
        layout.addWidget(self._job_summary)

        self.settings = WatermarkSettingsForm()
        layout.addWidget(self.settings)

        self._progress_bar = QProgressBar()
        self._progress_bar.setValue(0)
        self._progress_message = QLabel("")
        self._progress_message.setStyleSheet("color: #888; font-size: 12px;")
        layout.addWidget(self._progress_bar)
        layout.addWidget(self._progress_message)

        btn_row = QHBoxLayout()
        self._open_output_btn = QPushButton("결과 폴더 열기")
        self._open_output_btn.setEnabled(False)
        self._cancel_btn = QPushButton("중지")
        self._cancel_btn.setEnabled(False)
        self._start_btn = QPushButton("일괄 처리 시작")
        self._start_btn.setStyleSheet(
            "background: #2e7d32; color: white; font-weight: bold; padding: 10px 20px;"
        )
        btn_row.addWidget(self._open_output_btn)
        btn_row.addStretch()
        btn_row.addWidget(self._cancel_btn)
        btn_row.addWidget(self._start_btn)
        layout.addLayout(btn_row)
        layout.addStretch()

        self._add_videos_btn.clicked.connect(self._add_videos)
        self._remove_videos_btn.clicked.connect(self._remove_selected_videos)
        self._clear_videos_btn.clicked.connect(self._clear_videos)
        self._add_row_btn.clicked.connect(lambda: self._add_buyer_row())
        self._remove_row_btn.clicked.connect(self._remove_selected_buyers)
        self._paste_btn.clicked.connect(self._paste_buyers)
        self._csv_btn.clicked.connect(self._load_csv)
        self._clear_buyers_btn.clicked.connect(self._clear_buyers)
        self._start_btn.clicked.connect(self._start_batch)
        self._cancel_btn.clicked.connect(self._cancel_batch)
        self._open_output_btn.clicked.connect(self._open_output_folder)
        self._buyer_table.itemChanged.connect(lambda *_: self._update_summary())

        paste_shortcut = QShortcut(QKeySequence.StandardKey.Paste, self._buyer_table)
        paste_shortcut.activated.connect(self._paste_buyers)

        self._add_buyer_row("김개똥", "01011111111")
        self._update_summary()

    def _add_videos(self) -> None:
        paths, _ = QFileDialog.getOpenFileNames(
            self,
            "원본 동영상 선택",
            "",
            "동영상 (*.mp4 *.mkv *.mov *.avi *.webm);;모든 파일 (*)",
        )
        for path in paths:
            p = Path(path)
            if p not in self._videos:
                self._videos.append(p)
                self._video_list.addItem(str(p))
        self._update_summary()

    def _remove_selected_videos(self) -> None:
        for item in self._video_list.selectedItems():
            row = self._video_list.row(item)
            self._video_list.takeItem(row)
            if 0 <= row < len(self._videos):
                self._videos.pop(row)
        self._update_summary()

    def _clear_videos(self) -> None:
        self._videos.clear()
        self._video_list.clear()
        self._update_summary()

    def _add_buyer_row(self, name: str = "", contact: str = "") -> None:
        row = self._buyer_table.rowCount()
        self._buyer_table.insertRow(row)
        self._buyer_table.setItem(row, 0, QTableWidgetItem(name))
        self._buyer_table.setItem(row, 1, QTableWidgetItem(contact))
        self._update_summary()

    def _remove_selected_buyers(self) -> None:
        rows = sorted({idx.row() for idx in self._buyer_table.selectedIndexes()}, reverse=True)
        for row in rows:
            self._buyer_table.removeRow(row)
        self._update_summary()

    def _clear_buyers(self) -> None:
        self._buyer_table.setRowCount(0)
        self._update_summary()

    def _set_buyers(self, buyers: list[BuyerInfo]) -> None:
        self._buyer_table.blockSignals(True)
        self._buyer_table.setRowCount(0)
        for buyer in buyers:
            self._add_buyer_row(buyer.name, buyer.contact)
        self._buyer_table.blockSignals(False)
        self._update_summary()

    def _paste_buyers(self) -> None:
        from PySide6.QtWidgets import QApplication

        text = QApplication.clipboard().text()
        buyers = parse_buyer_lines(text)
        if not buyers:
            QMessageBox.warning(
                self,
                "붙여넣기",
                "인식된 구매자가 없습니다.\n이름과 연락처를 탭/쉼표/공백으로 구분해 주세요.",
            )
            return
        # 기존이 예시 1행만 있으면 교체, 아니면 추가
        if self._buyer_table.rowCount() == 1:
            name_item = self._buyer_table.item(0, 0)
            contact_item = self._buyer_table.item(0, 1)
            if (
                name_item
                and contact_item
                and name_item.text() == "김개똥"
                and contact_item.text() == "01011111111"
            ):
                self._set_buyers(buyers)
                return
        for buyer in buyers:
            self._add_buyer_row(buyer.name, buyer.contact)

    def _load_csv(self) -> None:
        path, _ = QFileDialog.getOpenFileName(
            self, "CSV 불러오기", "", "CSV (*.csv *.txt);;모든 파일 (*)"
        )
        if not path:
            return
        try:
            buyers = load_buyers_from_csv(Path(path))
        except OSError as exc:
            QMessageBox.critical(self, "오류", f"파일을 읽을 수 없습니다.\n{exc}")
            return
        if not buyers:
            QMessageBox.warning(self, "CSV", "구매자 데이터를 찾지 못했습니다.")
            return
        self._set_buyers(buyers)

    def _collect_buyers(self) -> list[BuyerInfo]:
        buyers: list[BuyerInfo] = []
        for row in range(self._buyer_table.rowCount()):
            name_item = self._buyer_table.item(row, 0)
            contact_item = self._buyer_table.item(row, 1)
            name = name_item.text().strip() if name_item else ""
            contact = contact_item.text().strip() if contact_item else ""
            if name and contact:
                buyers.append(BuyerInfo(name=name, contact=contact))
        return buyers

    def _update_summary(self) -> None:
        n_videos = len(self._videos)
        n_buyers = len(self._collect_buyers())
        total = n_videos * n_buyers
        self._job_summary.setText(
            f"예상 작업: {total}개  (영상 {n_videos} × 구매자 {n_buyers})"
        )

    def _start_batch(self) -> None:
        if self._processor is None:
            QMessageBox.critical(
                self, "오류", self._processor_error or "FFmpeg를 사용할 수 없습니다."
            )
            return
        if self._worker is not None and self._worker.isRunning():
            return

        if not self._videos:
            QMessageBox.warning(self, "입력 오류", "원본 동영상을 추가해 주세요.")
            return

        buyers = self._collect_buyers()
        if not buyers:
            QMessageBox.warning(self, "입력 오류", "구매자 이름과 연락처를 입력해 주세요.")
            return

        # 공통 설정 검증 (첫 구매자로 템플릿 확인)
        template = self.settings.build_request(buyers[0].name, buyers[0].contact, self)
        if template is None:
            return

        jobs: list[BatchJob] = []
        for video in self._videos:
            out_dir = self.settings.output_dir or video.parent
            for buyer in buyers:
                request = WatermarkRequest(
                    buyer_name=buyer.name,
                    contact=buyer.contact,
                    mode=template.mode,
                    start_seconds=template.start_seconds,
                    end_seconds=template.end_seconds,
                    interval_seconds=template.interval_seconds,
                    show_seconds=template.show_seconds,
                    position=template.position,
                    font_size=template.font_size,
                    opacity=template.opacity,
                    quality=template.quality,
                    use_gpu=template.use_gpu,
                )
                output_path = build_output_path(out_dir, buyer.name, video)
                jobs.append(BatchJob(video, output_path, request))

        self._last_output_dir = self.settings.output_dir or self._videos[0].parent
        total = len(jobs)
        reply = QMessageBox.question(
            self,
            "일괄 처리 확인",
            f"총 {total}개 작업을 시작합니다.\n계속할까요?",
        )
        if reply != QMessageBox.StandardButton.Yes:
            return

        self._progress_bar.setValue(0)
        self._progress_message.setText("준비 중...")
        self._start_btn.setEnabled(False)
        self._cancel_btn.setEnabled(True)
        self._open_output_btn.setEnabled(False)

        self._worker = BatchWatermarkWorker(self._processor, jobs)
        self._worker.job_started.connect(self._on_job_started)
        self._worker.job_progress.connect(self._on_job_progress)
        self._worker.job_completed.connect(self._on_job_completed)
        self._worker.job_failed.connect(self._on_job_failed)
        self._worker.batch_finished.connect(self._on_batch_finished)
        self._worker.start()

    def _cancel_batch(self) -> None:
        if self._worker is not None:
            self._worker.cancel()
            self._progress_message.setText("중지 요청됨 (현재 작업 완료 후 중단)...")
            self._cancel_btn.setEnabled(False)

    def _on_job_started(self, index: int, total: int, label: str) -> None:
        overall = int(((index - 1) / total) * 100) if total else 0
        self._progress_bar.setValue(overall)
        self._current_job_label = f"[{index}/{total}] {label}"
        self._progress_message.setText(self._current_job_label)

    def _on_job_progress(self, progress: float, message: str) -> None:
        label = getattr(self, "_current_job_label", "")
        self._progress_message.setText(f"{label} · {message}")
        # 개별 작업 진행을 전체 바에 소폭 반영
        text = label
        if text.startswith("[") and "/" in text:
            try:
                part = text[1 : text.index("]")]
                index_s, total_s = part.split("/")
                index, total = int(index_s), int(total_s)
                overall = ((index - 1) + progress / 100.0) / total * 100
                self._progress_bar.setValue(int(overall))
            except ValueError:
                pass

    def _on_job_completed(self, index: int, output_path: str) -> None:
        del index, output_path

    def _on_job_failed(self, index: int, error: str) -> None:
        self._progress_message.setText(f"작업 {index} 실패: {error}")

    def _on_batch_finished(self, ok: int, failed: int) -> None:
        self._progress_bar.setValue(100)
        self._start_btn.setEnabled(True)
        self._cancel_btn.setEnabled(False)
        self._open_output_btn.setEnabled(self._last_output_dir is not None)
        self._progress_message.setText(f"완료 — 성공 {ok}개, 실패 {failed}개")
        QMessageBox.information(
            self,
            "일괄 처리 완료",
            f"성공: {ok}개\n실패: {failed}개",
        )

    def _open_output_folder(self) -> None:
        if self._last_output_dir is None:
            return
        folder = str(self._last_output_dir)
        if sys.platform == "win32":
            os.startfile(folder)  # noqa: S606
        elif sys.platform == "darwin":
            subprocess.run(["open", folder], check=False)
        else:
            subprocess.run(["xdg-open", folder], check=False)
