"""Downloads view showing the download queue and progress."""

import time

from PySide6.QtWidgets import (
    QWidget, QVBoxLayout, QHBoxLayout, QLabel,
    QPushButton, QTableWidget, QTableWidgetItem,
    QHeaderView, QProgressBar, QMessageBox,
    QAbstractItemView, QFrame, QSpacerItem, QSizePolicy,
    QSlider
)
from PySide6.QtCore import Qt
from PySide6.QtGui import QColor

from config import save_config
from gui.workers.download_queue import DownloadQueue, DownloadStatus
from gui.workers.download_worker import DownloadWorker

# Downloads-view speed slider range (Mbps); 0 = unlimited.
SPEED_LIMIT_MAX_MBPS = 100

# Parallel-downloads slider range (must match the worker's 1-8 clamp).
PARALLEL_MIN = 1
PARALLEL_MAX = 8


class StatCard(QFrame):
    """A small stat display card."""

    def __init__(self, value: str, label: str, color: str = None, parent=None):
        super().__init__(parent)
        self.setObjectName("card")
        self.setFixedWidth(120)
        self._color = color
        self._setup_ui(value, label)

    def _setup_ui(self, value: str, label: str):
        layout = QVBoxLayout(self)
        layout.setContentsMargins(16, 12, 16, 12)
        layout.setSpacing(4)
        layout.setAlignment(Qt.AlignCenter)

        self.value_label = QLabel(value)
        self.value_label.setObjectName("statValue")
        if self._color:
            self.value_label.setStyleSheet(f"color: {self._color}; background: transparent;")
        self.value_label.setAlignment(Qt.AlignCenter)
        layout.addWidget(self.value_label)

        self.label = QLabel(label)
        self.label.setObjectName("statLabel")
        self.label.setAlignment(Qt.AlignCenter)
        layout.addWidget(self.label)

    def set_value(self, value: str):
        self.value_label.setText(value)


class DownloadsView(QWidget):
    """View showing download queue and controls."""

    def __init__(self, config: dict, queue: DownloadQueue, parent=None):
        super().__init__(parent)
        self.config = config
        self.queue = queue
        self.worker = None
        self._download_start_time = None  # monotonic time when a run began (for ETA)
        self._setup_ui()
        self._connect_signals()

    def _setup_ui(self):
        layout = QVBoxLayout(self)
        layout.setContentsMargins(32, 24, 32, 24)
        layout.setSpacing(24)

        # Header
        header = QHBoxLayout()
        header.setSpacing(16)

        title_section = QVBoxLayout()
        title_section.setSpacing(4)

        title = QLabel("Download Queue")
        title.setObjectName("title")
        title_section.addWidget(title)

        subtitle = QLabel("Manage and monitor your music downloads")
        subtitle.setObjectName("subtitle")
        title_section.addWidget(subtitle)

        header.addLayout(title_section)
        header.addStretch()

        # Stats cards
        stats_layout = QHBoxLayout()
        stats_layout.setSpacing(12)

        self.pending_card = StatCard("0", "PENDING", "#3c92de")
        stats_layout.addWidget(self.pending_card)

        self.completed_card = StatCard("0", "COMPLETED", "#4caf50")
        stats_layout.addWidget(self.completed_card)

        self.failed_card = StatCard("0", "FAILED", "#ef5350")
        stats_layout.addWidget(self.failed_card)

        header.addLayout(stats_layout)

        layout.addLayout(header)

        # Control bar
        controls = QFrame()
        controls.setObjectName("card")
        controls_layout = QHBoxLayout(controls)
        controls_layout.setContentsMargins(16, 12, 16, 12)
        controls_layout.setSpacing(12)

        # Primary actions
        self.start_btn = QPushButton("Start Downloads")
        self.start_btn.clicked.connect(self._start_downloads)
        controls_layout.addWidget(self.start_btn)

        self.pause_btn = QPushButton("Pause")
        self.pause_btn.setObjectName("secondary")
        self.pause_btn.clicked.connect(self._toggle_pause)
        self.pause_btn.setEnabled(False)
        controls_layout.addWidget(self.pause_btn)

        self.cancel_btn = QPushButton("Cancel")
        self.cancel_btn.setObjectName("danger")
        self.cancel_btn.clicked.connect(self._cancel_downloads)
        self.cancel_btn.setEnabled(False)
        controls_layout.addWidget(self.cancel_btn)

        controls_layout.addSpacerItem(QSpacerItem(40, 0, QSizePolicy.Expanding, QSizePolicy.Minimum))

        # Secondary actions
        self.retry_btn = QPushButton("Retry Failed")
        self.retry_btn.setObjectName("secondary")
        self.retry_btn.clicked.connect(self._retry_failed)
        controls_layout.addWidget(self.retry_btn)

        self.clear_done_btn = QPushButton("Clear Done")
        self.clear_done_btn.setObjectName("secondary")
        self.clear_done_btn.clicked.connect(self._clear_completed)
        controls_layout.addWidget(self.clear_done_btn)

        self.open_folder_btn = QPushButton("Open Folder")
        self.open_folder_btn.setObjectName("secondary")
        self.open_folder_btn.clicked.connect(self._open_output_folder)
        controls_layout.addWidget(self.open_folder_btn)

        self.clear_all_btn = QPushButton("Clear All")
        self.clear_all_btn.setObjectName("danger")
        self.clear_all_btn.clicked.connect(self._clear_all)
        controls_layout.addWidget(self.clear_all_btn)

        layout.addWidget(controls)

        # Speed limit bar
        speed_frame = QFrame()
        speed_frame.setObjectName("card")
        speed_layout = QHBoxLayout(speed_frame)
        speed_layout.setContentsMargins(16, 12, 16, 12)
        speed_layout.setSpacing(12)

        speed_title = QLabel("Speed Limit")
        speed_title.setStyleSheet("font-weight: 600; background: transparent;")
        speed_layout.addWidget(speed_title)

        self.speed_slider = QSlider(Qt.Horizontal)
        self.speed_slider.setMinimum(0)
        self.speed_slider.setMaximum(SPEED_LIMIT_MAX_MBPS)
        self.speed_slider.setValue(self._current_speed_limit())
        self.speed_slider.setTickPosition(QSlider.TicksBelow)
        self.speed_slider.setTickInterval(10)
        self.speed_slider.valueChanged.connect(self._on_speed_changed)
        self.speed_slider.sliderReleased.connect(self._save_speed_limit)
        speed_layout.addWidget(self.speed_slider, 1)

        self.speed_value_label = QLabel()
        self.speed_value_label.setMinimumWidth(90)
        self.speed_value_label.setAlignment(Qt.AlignRight | Qt.AlignVCenter)
        self.speed_value_label.setStyleSheet("font-weight: 600; color: #3c92de; background: transparent;")
        speed_layout.addWidget(self.speed_value_label)

        self._update_speed_label(self.speed_slider.value())

        layout.addWidget(speed_frame)

        # Parallel downloads bar
        parallel_frame = QFrame()
        parallel_frame.setObjectName("card")
        parallel_layout = QHBoxLayout(parallel_frame)
        parallel_layout.setContentsMargins(16, 12, 16, 12)
        parallel_layout.setSpacing(12)

        parallel_title = QLabel("Parallel Downloads")
        parallel_title.setStyleSheet("font-weight: 600; background: transparent;")
        parallel_layout.addWidget(parallel_title)

        self.parallel_slider = QSlider(Qt.Horizontal)
        self.parallel_slider.setMinimum(PARALLEL_MIN)
        self.parallel_slider.setMaximum(PARALLEL_MAX)
        self.parallel_slider.setValue(self._current_parallel())
        self.parallel_slider.setTickPosition(QSlider.TicksBelow)
        self.parallel_slider.setTickInterval(1)
        self.parallel_slider.setPageStep(1)
        self.parallel_slider.valueChanged.connect(self._on_parallel_changed)
        self.parallel_slider.sliderReleased.connect(self._save_parallel)
        parallel_layout.addWidget(self.parallel_slider, 1)

        self.parallel_value_label = QLabel()
        self.parallel_value_label.setMinimumWidth(90)
        self.parallel_value_label.setAlignment(Qt.AlignRight | Qt.AlignVCenter)
        self.parallel_value_label.setStyleSheet("font-weight: 600; color: #3c92de; background: transparent;")
        parallel_layout.addWidget(self.parallel_value_label)

        self._update_parallel_label(self.parallel_slider.value())

        layout.addWidget(parallel_frame)

        # Queue table
        self.table = QTableWidget()
        self.table.setColumnCount(5)
        self.table.setHorizontalHeaderLabels(["ARTIST", "TRACK", "SOURCE", "STATUS", "PROGRESS"])

        header_view = self.table.horizontalHeader()
        header_view.setSectionResizeMode(0, QHeaderView.Stretch)
        header_view.setSectionResizeMode(1, QHeaderView.Stretch)
        header_view.setSectionResizeMode(2, QHeaderView.ResizeToContents)
        header_view.setSectionResizeMode(3, QHeaderView.ResizeToContents)
        header_view.setSectionResizeMode(4, QHeaderView.Fixed)
        self.table.setColumnWidth(4, 140)

        self.table.setSelectionBehavior(QAbstractItemView.SelectRows)
        self.table.setEditTriggers(QAbstractItemView.NoEditTriggers)
        self.table.verticalHeader().setVisible(False)
        self.table.setShowGrid(False)

        layout.addWidget(self.table, 1)

        # Progress section
        progress_frame = QFrame()
        progress_frame.setObjectName("cardAccent")
        progress_layout = QHBoxLayout(progress_frame)
        progress_layout.setContentsMargins(20, 16, 20, 16)
        progress_layout.setSpacing(16)

        progress_label = QLabel("Overall Progress")
        progress_label.setStyleSheet("font-weight: 600; background: transparent;")
        progress_layout.addWidget(progress_label)

        self.overall_progress = QProgressBar()
        self.overall_progress.setMinimum(0)
        self.overall_progress.setMaximum(100)
        self.overall_progress.setValue(0)
        self.overall_progress.setTextVisible(False)
        self.overall_progress.setFixedHeight(8)
        progress_layout.addWidget(self.overall_progress, 1)

        self.progress_text = QLabel("0%")
        self.progress_text.setStyleSheet("font-weight: 600; color: #3c92de; background: transparent;")
        progress_layout.addWidget(self.progress_text)

        self.overall_eta_label = QLabel("")
        self.overall_eta_label.setMinimumWidth(110)
        self.overall_eta_label.setAlignment(Qt.AlignRight | Qt.AlignVCenter)
        self.overall_eta_label.setStyleSheet("color: #9a9ab0; background: transparent;")
        progress_layout.addWidget(self.overall_eta_label)

        layout.addWidget(progress_frame)

    def _current_speed_limit(self) -> int:
        """Read the saved speed limit (Mbps) clamped to the slider range."""
        try:
            value = int(round(float(self.config.get("download_speed_limit_mbps", 0) or 0)))
        except (TypeError, ValueError):
            value = 0
        return max(0, min(value, SPEED_LIMIT_MAX_MBPS))

    def _update_speed_label(self, value: int):
        """Update the text next to the speed slider."""
        if value <= 0:
            self.speed_value_label.setText("Unlimited")
        else:
            self.speed_value_label.setText(f"{value} Mbps")

    def _on_speed_changed(self, value: int):
        """Live-apply the slider value to the shared config (no disk write yet)."""
        self._update_speed_label(value)
        # Same dict the worker reads at download time, so it takes effect
        # for downloads that start after this change.
        self.config["download_speed_limit_mbps"] = value

    def _save_speed_limit(self):
        """Persist the speed limit to disk when the user releases the slider."""
        self.config["download_speed_limit_mbps"] = self.speed_slider.value()
        try:
            save_config(self.config)
        except Exception:
            pass  # non-fatal; the in-memory value still applies this session

    def _current_parallel(self) -> int:
        """Read the saved parallel-download count clamped to the slider range."""
        try:
            value = int(self.config.get("concurrent_downloads", 3))
        except (TypeError, ValueError):
            value = 3
        return max(PARALLEL_MIN, min(value, PARALLEL_MAX))

    def _update_parallel_label(self, value: int):
        """Update the text next to the parallel-downloads slider."""
        suffix = "download" if value == 1 else "downloads"
        self.parallel_value_label.setText(f"{value} {suffix}")

    def _on_parallel_changed(self, value: int):
        """Live-apply the parallel count to the shared config (no disk write yet)."""
        self._update_parallel_label(value)
        self.config["concurrent_downloads"] = value

    def _save_parallel(self):
        """Persist the parallel-download count when the user releases the slider."""
        self.config["concurrent_downloads"] = self.parallel_slider.value()
        try:
            save_config(self.config)
        except Exception:
            pass  # non-fatal; the in-memory value still applies this session

    def _connect_signals(self):
        self.queue.item_added.connect(self._on_item_added)
        self.queue.item_updated.connect(self._on_item_updated)
        self.queue.item_removed.connect(self._on_item_removed)
        self.queue.queue_updated.connect(self._update_stats)
        self.queue.queue_completed.connect(self._on_queue_completed)

    def _on_item_added(self, item):
        row = self.table.rowCount()
        self.table.insertRow(row)

        artist_item = QTableWidgetItem(item.artist)
        artist_item.setData(Qt.UserRole, item.id)
        self.table.setItem(row, 0, artist_item)

        self.table.setItem(row, 1, QTableWidgetItem(item.track))
        self.table.setItem(row, 2, QTableWidgetItem(item.playlist or "—"))

        status_item = QTableWidgetItem(item.status.value.title())
        self.table.setItem(row, 3, status_item)

        progress = QProgressBar()
        progress.setMinimum(0)
        progress.setMaximum(100)
        progress.setValue(item.progress)
        progress.setFormat("%p%")
        progress.setTextVisible(True)
        progress.setFixedHeight(16)
        self.table.setCellWidget(row, 4, progress)

        self._update_stats(self.queue.pending_count)

    def _on_item_updated(self, item):
        for row in range(self.table.rowCount()):
            if self.table.item(row, 0).data(Qt.UserRole) == item.id:
                status_item = self.table.item(row, 3)
                if item.status == DownloadStatus.DOWNLOADING:
                    parts = [f"Downloading {item.progress}%"]
                    if getattr(item, "speed", ""):
                        parts.append(item.speed)
                    if getattr(item, "eta", ""):
                        parts.append(f"ETA {item.eta}")
                    status_item.setText("  •  ".join(parts))
                else:
                    status_item.setText(item.status.value.title())

                if item.status == DownloadStatus.COMPLETED:
                    status_item.setForeground(QColor("#4caf50"))
                elif item.status == DownloadStatus.FAILED:
                    status_item.setForeground(QColor("#ef5350"))
                elif item.status == DownloadStatus.DOWNLOADING:
                    status_item.setForeground(QColor("#3c92de"))
                else:
                    status_item.setForeground(QColor("#9a9ab0"))

                progress = self.table.cellWidget(row, 4)
                if progress:
                    progress.setValue(item.progress)
                break

        self._update_overall_progress()

    def _on_item_removed(self, item_id: str):
        for row in range(self.table.rowCount()):
            if self.table.item(row, 0).data(Qt.UserRole) == item_id:
                self.table.removeRow(row)
                break

    def _update_stats(self, pending: int):
        self.pending_card.set_value(str(pending))
        self.completed_card.set_value(str(self.queue.completed_count))
        self.failed_card.set_value(str(self.queue.failed_count))

    def _update_overall_progress(self):
        total = self.table.rowCount()
        if total == 0:
            self.overall_progress.setValue(0)
            self.progress_text.setText("0%")
            return

        completed = self.queue.completed_count + self.queue.failed_count
        percent = int((completed / total) * 100)
        self.overall_progress.setValue(percent)
        self.progress_text.setText(f"{percent}%")
        self._update_overall_eta(total, completed)

    def _update_overall_eta(self, total: int, completed: int):
        """Show a rough estimate of the time remaining for the whole queue."""
        remaining = total - completed
        # Only show an estimate while a run is actually in progress.
        if remaining <= 0 or self._download_start_time is None or not self.queue.is_running:
            self.overall_eta_label.setText("")
            return

        workers = max(1, self._current_parallel())
        if completed > 0:
            # Measured wall-clock average per finished item already reflects
            # how many downloads run in parallel.
            elapsed = time.monotonic() - self._download_start_time
            avg = elapsed / completed
        else:
            # Nothing finished yet: fall back to the configured rough estimate.
            try:
                avg_download = float(self.config.get("average_download_time", 20) or 20)
            except (TypeError, ValueError):
                avg_download = 20.0
            avg = avg_download / workers

        eta_seconds = avg * remaining
        self.overall_eta_label.setText(f"~ {self._format_duration(eta_seconds)} left")

    @staticmethod
    def _format_duration(seconds: float) -> str:
        seconds = int(max(0, seconds))
        if seconds >= 3600:
            return f"{seconds // 3600}h {(seconds % 3600) // 60}m"
        if seconds >= 60:
            return f"{seconds // 60}m {seconds % 60:02d}s"
        return f"{seconds}s"

    def _resolve_output_dir(self) -> str:
        """Resolve the configured output dir to an absolute path (project-root relative)."""
        import os
        import sys
        output_dir = self.config.get("output_dir", "music")
        if not os.path.isabs(output_dir):
            if getattr(sys, "frozen", False):
                base_dir = os.path.dirname(sys.executable)
            else:
                # …/gui/views/downloads_view.py -> project root
                base_dir = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
            output_dir = os.path.join(base_dir, output_dir)
        return output_dir

    def _open_output_folder(self):
        """Open the downloads folder in the OS file manager."""
        import os
        import sys
        import subprocess

        path = self._resolve_output_dir()
        try:
            os.makedirs(path, exist_ok=True)
            if sys.platform == "win32":
                os.startfile(path)  # type: ignore[attr-defined]
            elif sys.platform == "darwin":
                subprocess.Popen(["open", path])
            else:
                subprocess.Popen(["xdg-open", path])
        except Exception as e:
            QMessageBox.warning(self, "Open Folder", f"Could not open folder:\n{path}\n\n{e}")

    def _on_queue_completed(self, success: int, failed: int):
        self.start_btn.setEnabled(True)
        self.pause_btn.setEnabled(False)
        self.cancel_btn.setEnabled(False)
        self.pause_btn.setText("Pause")
        self.overall_eta_label.setText("")

        if failed > 0:
            QMessageBox.information(
                self,
                "Downloads Complete",
                f"Downloaded {success} tracks successfully.\n{failed} tracks failed."
            )
        elif success > 0:
            QMessageBox.information(
                self,
                "Downloads Complete",
                f"Successfully downloaded {success} tracks!"
            )

    def _start_downloads(self):
        if not self.queue.has_pending():
            QMessageBox.information(self, "No Downloads", "No tracks in queue to download.")
            return

        self._download_start_time = time.monotonic()
        self.worker = DownloadWorker(self.queue, self.config)
        self.worker.all_completed.connect(self._on_queue_completed)
        self.worker.start()

        self.start_btn.setEnabled(False)
        self.pause_btn.setEnabled(True)
        self.cancel_btn.setEnabled(True)

    def _toggle_pause(self):
        if not self.worker:
            return

        if self.worker.is_paused:
            self.worker.resume()
            self.pause_btn.setText("Pause")
        else:
            self.worker.pause()
            self.pause_btn.setText("Resume")

    def _cancel_downloads(self):
        reply = QMessageBox.question(
            self,
            "Cancel Downloads",
            "Are you sure you want to cancel all downloads?",
            QMessageBox.Yes | QMessageBox.No,
            QMessageBox.No
        )
        if reply == QMessageBox.Yes and self.worker:
            self.worker.cancel()
            self.start_btn.setEnabled(True)
            self.pause_btn.setEnabled(False)
            self.cancel_btn.setEnabled(False)

    def _retry_failed(self):
        self.queue.retry_failed()
        self._update_stats(self.queue.pending_count)

    def _clear_completed(self):
        self.queue.clear_completed()
        for row in range(self.table.rowCount() - 1, -1, -1):
            item_id = self.table.item(row, 0).data(Qt.UserRole)
            if not self.queue.get_item(item_id):
                self.table.removeRow(row)
        self._update_stats(self.queue.pending_count)
        self._update_overall_progress()

    def _clear_all(self):
        if self.table.rowCount() == 0:
            return

        reply = QMessageBox.question(
            self,
            "Clear Queue",
            "This will remove all items from the queue.\n\nAre you sure?",
            QMessageBox.Yes | QMessageBox.No,
            QMessageBox.No
        )
        if reply == QMessageBox.Yes:
            # Cancel any running downloads first
            if self.worker and self.worker.isRunning():
                self.worker.cancel()
                self.worker.wait()

            self.queue.clear_all()
            self.table.setRowCount(0)
            self._update_stats(0)
            self._update_overall_progress()
            self.start_btn.setEnabled(True)
            self.pause_btn.setEnabled(False)
            self.cancel_btn.setEnabled(False)
