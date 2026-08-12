"""백그라운드 FFmpeg 워터마크 작업."""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

from PySide6.QtCore import QThread, Signal

from app.models import WatermarkRequest
from app.watermark import WatermarkProcessor


class WatermarkWorker(QThread):
    progress_changed = Signal(float, str)
    completed = Signal(str)
    failed = Signal(str)

    def __init__(
        self,
        processor: WatermarkProcessor,
        input_path: Path,
        output_path: Path,
        request: WatermarkRequest,
    ) -> None:
        super().__init__()
        self._processor = processor
        self._input_path = input_path
        self._output_path = output_path
        self._request = request

    def run(self) -> None:
        try:
            self._processor.process(
                self._input_path,
                self._output_path,
                self._request,
                on_progress=self._on_progress,
            )
            self.completed.emit(str(self._output_path))
        except Exception as exc:
            self.failed.emit(str(exc))

    def _on_progress(self, progress: float, message: str) -> None:
        self.progress_changed.emit(progress, message)


@dataclass
class BatchJob:
    input_path: Path
    output_path: Path
    request: WatermarkRequest

    @property
    def label(self) -> str:
        return f"{self.request.buyer_name} × {self.input_path.name}"


class BatchWatermarkWorker(QThread):
    """영상×구매자 작업을 순차 처리."""

    job_started = Signal(int, int, str)  # index(1-based), total, label
    job_progress = Signal(float, str)
    job_completed = Signal(int, str)
    job_failed = Signal(int, str)
    batch_finished = Signal(int, int)  # success_count, fail_count

    def __init__(
        self,
        processor: WatermarkProcessor,
        jobs: list[BatchJob],
    ) -> None:
        super().__init__()
        self._processor = processor
        self._jobs = jobs
        self._cancel = False

    def cancel(self) -> None:
        self._cancel = True

    def run(self) -> None:
        total = len(self._jobs)
        ok = 0
        failed = 0
        for index, job in enumerate(self._jobs, start=1):
            if self._cancel:
                break
            self.job_started.emit(index, total, job.label)
            try:
                job.output_path.parent.mkdir(parents=True, exist_ok=True)
                self._processor.process(
                    job.input_path,
                    job.output_path,
                    job.request,
                    on_progress=lambda p, m: self.job_progress.emit(p, m),
                )
                ok += 1
                self.job_completed.emit(index, str(job.output_path))
            except Exception as exc:
                failed += 1
                self.job_failed.emit(index, str(exc))
        self.batch_finished.emit(ok, failed)
