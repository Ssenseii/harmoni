"""Downloads view showing the download queue and progress."""

from PySide6.QtWidgets import (
    QWidget, QVBoxLayout, QHBoxLayout, QLabel,
    QPushButton, QTableWidget, QTableWidgetItem,
    QHeaderView, QProgressBar, QMessageBox,
    QAbstractItemView, QFrame, QSpacerItem, QSizePolicy
)
from PySide6.QtCore import Qt, Signal
from PySide6.QtGui import QColor

from gui.workers.download_queue import DownloadQueue, DownloadStatus
from gui.workers.download_worker import DownloadWorker

CANCEL_WAIT_MS = 6000


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

    running_changed = Signal(bool)

    def __init__(self, config: dict, queue: DownloadQueue, parent=None):
        super().__init__(parent)
        self.config = config
        self.queue = queue
        self.worker = None
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

        self.waiting_label = QLabel()
        self.waiting_label.setObjectName("accent")
        self.waiting_label.hide()
        controls_layout.addWidget(self.waiting_label)

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

        self.clear_all_btn = QPushButton("Clear All")
        self.clear_all_btn.setObjectName("danger")
        self.clear_all_btn.clicked.connect(self._clear_all)
        controls_layout.addWidget(self.clear_all_btn)

        layout.addWidget(controls)

        # Queue table
        self.table = QTableWidget()
        self.table.setColumnCount(5)
        self.table.setHorizontalHeaderLabels(["ARTIST", "TRACK", "SOURCE", "STATUS", "DETAILS"])

        header_view = self.table.horizontalHeader()
        header_view.setSectionResizeMode(0, QHeaderView.Stretch)
        header_view.setSectionResizeMode(1, QHeaderView.Stretch)
        header_view.setSectionResizeMode(2, QHeaderView.ResizeToContents)
        header_view.setSectionResizeMode(3, QHeaderView.ResizeToContents)
        header_view.setSectionResizeMode(4, QHeaderView.Stretch)

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

        layout.addWidget(progress_frame)

    def _connect_signals(self):
        self.queue.item_added.connect(self._on_item_added)
        self.queue.items_added.connect(self._on_items_added)
        self.queue.item_updated.connect(self._on_item_updated)
        self.queue.item_removed.connect(self._on_item_removed)
        self.queue.queue_updated.connect(self._update_stats)

    def _on_item_added(self, item):
        self._add_row(item)

    def _on_items_added(self, items: list):
        """Add table rows for a batch of queue items with repaints held until the end.

        @param items: QueueItems added in one add_tracks call.
        """
        self.table.setUpdatesEnabled(False)
        try:
            for item in items:
                self._add_row(item)
        finally:
            self.table.setUpdatesEnabled(True)

    def _add_row(self, item):
        """Append one table row for a queue item.

        @param item: QueueItem to show.
        """
        row = self.table.rowCount()
        self.table.insertRow(row)

        artist_item = QTableWidgetItem(item.artist)
        artist_item.setData(Qt.UserRole, item.id)
        self.table.setItem(row, 0, artist_item)

        self.table.setItem(row, 1, QTableWidgetItem(item.track))
        self.table.setItem(row, 2, QTableWidgetItem(item.playlist or "—"))

        status_item = QTableWidgetItem(item.status.value.title())
        self.table.setItem(row, 3, status_item)

        self._set_details_cell(row, item)

    def _set_details_cell(self, row: int, item):
        """Show the failure reason for a failed item, or a progress bar otherwise.

        @param row: Table row of the item.
        @param item: QueueItem shown in that row.
        """
        if item.status == DownloadStatus.FAILED:
            self.table.removeCellWidget(row, 4)
            reason = item.error_message or "Download failed with no error message."
            reason_item = QTableWidgetItem(reason)
            reason_item.setToolTip(reason)
            reason_item.setForeground(QColor("#ef5350"))
            self.table.setItem(row, 4, reason_item)
            return
        progress = self.table.cellWidget(row, 4)
        if progress is None:
            self.table.setItem(row, 4, None)
            progress = QProgressBar()
            progress.setMinimum(0)
            progress.setMaximum(100)
            progress.setTextVisible(False)
            progress.setFixedHeight(6)
            self.table.setCellWidget(row, 4, progress)
        progress.setValue(item.progress)

    def _on_item_updated(self, item):
        for row in range(self.table.rowCount()):
            if self.table.item(row, 0).data(Qt.UserRole) == item.id:
                status_item = self.table.item(row, 3)
                status_item.setText(item.status.value.title())
                if item.status == DownloadStatus.FAILED:
                    status_item.setToolTip(item.error_message or "")
                else:
                    status_item.setToolTip("")

                if item.status == DownloadStatus.COMPLETED:
                    status_item.setForeground(QColor("#4caf50"))
                elif item.status == DownloadStatus.FAILED:
                    status_item.setForeground(QColor("#ef5350"))
                elif item.status == DownloadStatus.DOWNLOADING:
                    status_item.setForeground(QColor("#3c92de"))
                else:
                    status_item.setForeground(QColor("#9a9ab0"))

                self._set_details_cell(row, item)
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
        self._update_waiting_hint()

    def _update_waiting_hint(self):
        """Tell the user queued tracks wait for Start Downloads while nothing is running."""
        pending = self.queue.pending_count
        if pending and self.worker is None:
            noun = "track is" if pending == 1 else "tracks are"
            self.waiting_label.setText(f"{pending} {noun} waiting. Press Start Downloads to begin.")
            self.waiting_label.show()
        else:
            self.waiting_label.hide()

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

    def _on_worker_finished(self, worker):
        """Release a finished worker and re-enable Start once nothing is running.

        @param worker: The DownloadWorker whose finished signal fired.
        """
        worker.deleteLater()
        if self.worker is not worker:
            return
        self.worker = None
        self.start_btn.setEnabled(True)
        self.pause_btn.setEnabled(False)
        self.cancel_btn.setEnabled(False)
        self.pause_btn.setText("Pause")
        self._update_waiting_hint()
        self.running_changed.emit(False)

    def _on_queue_completed(self, success: int, failed: int):
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
        if self.worker is not None:
            return

        if not self.queue.has_pending():
            QMessageBox.information(self, "No Downloads", "No tracks in queue to download.")
            return

        worker = DownloadWorker(self.queue, self.config, parent=self)
        worker.all_completed.connect(self._on_queue_completed)
        worker.finished.connect(lambda: self._on_worker_finished(worker))
        self.worker = worker
        worker.start()
        self._update_waiting_hint()
        self.running_changed.emit(True)

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
                self.worker.wait(CANCEL_WAIT_MS)

            self.queue.clear_all()
            self.table.setRowCount(0)
            self._update_stats(0)
            self._update_overall_progress()
            if self.worker is None:
                self.start_btn.setEnabled(True)
                self.pause_btn.setEnabled(False)
                self.cancel_btn.setEnabled(False)
