"""백그라운드 FFmpeg 워터마크 작업."""

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
