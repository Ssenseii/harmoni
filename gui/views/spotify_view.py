"""Spotify view for browsing playlists and downloading tracks."""

import os
from PySide6.QtWidgets import (
    QWidget, QVBoxLayout, QHBoxLayout, QLabel,
    QPushButton, QTableWidget, QTableWidgetItem,
    QHeaderView, QListWidget, QListWidgetItem,
    QSplitter, QProgressBar, QMessageBox,
    QCheckBox, QAbstractItemView, QMenu
)
from PySide6.QtCore import Qt, Signal, QTimer
from PySide6.QtGui import QAction

from gui.workers.download_queue import DownloadQueue
from gui.workers.spotify_worker import SpotifyWorker
from gui.dialogs.oauth_dialog import SpotifyOAuthDialog
from spotify_api.auth import SpotifyPKCEAuth
from spotify_api.token_manager import TokenManager


class SpotifyView(QWidget):
    """View for Spotify playlist browsing and track selection."""

    connection_changed = Signal(bool)  # Emits connection status

    def __init__(self, config: dict, queue: DownloadQueue, parent=None):
        super().__init__(parent)
        self.config = config
        self.queue = queue
        self.worker = None
        self.current_tracks = []
        self._tracks_cache = {}
        self._updating_checks = False
        self._setup_ui()
        self._check_connection()

    def _setup_ui(self):
        layout = QVBoxLayout(self)
        layout.setContentsMargins(40, 30, 40, 30)
        layout.setSpacing(20)

        # Header
        header_layout = QHBoxLayout()
        title = QLabel("Spotify")
        title.setObjectName("title")
        header_layout.addWidget(title)
        header_layout.addStretch()

        # Connection status
        self.status_label = QLabel("Not connected")
        self.status_label.setObjectName("subtitle")
        header_layout.addWidget(self.status_label)

        self.connect_btn = QPushButton("Connect to Spotify")
        self.connect_btn.clicked.connect(self._show_oauth_dialog)
        header_layout.addWidget(self.connect_btn)
        layout.addLayout(header_layout)

        # Progress bar for loading
        self.progress_bar = QProgressBar()
        self.progress_bar.hide()
        layout.addWidget(self.progress_bar)

        # Main content splitter
        splitter = QSplitter(Qt.Horizontal)

        # Left panel - Playlists
        left_panel = QWidget()
        left_layout = QVBoxLayout(left_panel)
        left_layout.setContentsMargins(0, 0, 10, 0)

        playlists_label = QLabel("Playlists")
        playlists_label.setObjectName("section")
        left_layout.addWidget(playlists_label)

        # Refresh button
        btn_row = QHBoxLayout()
        self.refresh_btn = QPushButton("Refresh")
        self.refresh_btn.setObjectName("secondary")
        self.refresh_btn.clicked.connect(self._refresh_playlists)
        self.refresh_btn.setEnabled(False)
        btn_row.addWidget(self.refresh_btn)

        self.liked_btn = QPushButton("Liked Songs")
        self.liked_btn.setObjectName("secondary")
        self.liked_btn.clicked.connect(self._fetch_liked_songs)
        self.liked_btn.setEnabled(False)
        btn_row.addWidget(self.liked_btn)

        btn_row.addStretch()
        left_layout.addLayout(btn_row)

        # Playlist list
        self.playlist_list = QListWidget()
        self.playlist_list.setSelectionMode(QAbstractItemView.ExtendedSelection)
        self.playlist_list.itemDoubleClicked.connect(self._on_playlist_selected)
        self.playlist_list.setContextMenuPolicy(Qt.CustomContextMenu)
        self.playlist_list.customContextMenuRequested.connect(self._show_playlist_context_menu)
        left_layout.addWidget(self.playlist_list)

        bottom_row = QHBoxLayout()
        self.load_selected_btn = QPushButton("Load")
        self.load_selected_btn.setObjectName("secondary")
        self.load_selected_btn.clicked.connect(self._load_selected_playlists)
        bottom_row.addWidget(self.load_selected_btn)

        self.download_selected_btn = QPushButton("Download")
        self.download_selected_btn.clicked.connect(self._download_selected_playlists)
        bottom_row.addWidget(self.download_selected_btn)
        left_layout.addLayout(bottom_row)

        splitter.addWidget(left_panel)

        # Right panel - Tracks
        right_panel = QWidget()
        right_layout = QVBoxLayout(right_panel)
        right_layout.setContentsMargins(10, 0, 0, 0)

        # Tracks header
        tracks_header = QHBoxLayout()
        self.tracks_label = QLabel("Tracks")
        self.tracks_label.setObjectName("section")
        tracks_header.addWidget(self.tracks_label)
        tracks_header.addStretch()

        # Select all checkbox
        self.select_all_check = QCheckBox("Select All")
        self.select_all_check.stateChanged.connect(self._toggle_select_all)
        tracks_header.addWidget(self.select_all_check)
        right_layout.addLayout(tracks_header)

        # Tracks table
        self.tracks_table = QTableWidget()
        self.tracks_table.setColumnCount(4)
        self.tracks_table.setHorizontalHeaderLabels(["", "Artist", "Track", "Album"])
        self.tracks_table.horizontalHeader().setSectionResizeMode(0, QHeaderView.Fixed)
        self.tracks_table.setColumnWidth(0, 40)
        self.tracks_table.horizontalHeader().setSectionResizeMode(1, QHeaderView.Stretch)
        self.tracks_table.horizontalHeader().setSectionResizeMode(2, QHeaderView.Stretch)
        self.tracks_table.horizontalHeader().setSectionResizeMode(3, QHeaderView.Stretch)
        self.tracks_table.setSelectionBehavior(QAbstractItemView.SelectRows)
        self.tracks_table.setSelectionMode(QAbstractItemView.ExtendedSelection)
        self.tracks_table.setEditTriggers(QAbstractItemView.NoEditTriggers)
        self.tracks_table.verticalHeader().setVisible(False)
        self.tracks_table.setShowGrid(False)
        self.tracks_table.itemChanged.connect(self._on_item_changed)
        self.tracks_table.setContextMenuPolicy(Qt.CustomContextMenu)
        self.tracks_table.customContextMenuRequested.connect(self._show_context_menu)
        right_layout.addWidget(self.tracks_table)

        # Add to queue button
        footer = QHBoxLayout()
        footer.addStretch()
        self.track_count_label = QLabel("0 tracks selected")
        footer.addWidget(self.track_count_label)
        self.add_btn = QPushButton("Add to Download Queue")
        self.add_btn.clicked.connect(self._add_selected_to_queue)
        self.add_btn.setEnabled(False)
        footer.addWidget(self.add_btn)
        right_layout.addLayout(footer)

        splitter.addWidget(right_panel)

        # Set splitter proportions
        splitter.setSizes([300, 700])
        layout.addWidget(splitter, 1)

    def _check_connection(self):
        auth = SpotifyPKCEAuth(self.config)
        token = auth.load_cached_token()
        if token and token.access_token:
            # Check if expired
            if TokenManager.is_expired(token):
                if token.refresh_token:
                    try:
                        auth.refresh_access_token(refresh_token=token.refresh_token)
                        self._set_connected(True)
                        return
                    except Exception:
                        pass
                self._set_connected(False)
            else:
                self._set_connected(True)
        else:
            self._set_connected(False)

    def _set_connected(self, connected: bool):
        if connected:
            self.status_label.setText("Connected")
            self.status_label.setStyleSheet("color: #1db954;")
            self.connect_btn.setText("Reconnect")
            self.refresh_btn.setEnabled(True)
            self.liked_btn.setEnabled(True)
            self.connection_changed.emit(True)
            # Auto-refresh playlists
            self._refresh_playlists()
        else:
            self.status_label.setText("Not connected")
            self.status_label.setStyleSheet("")
            self.connect_btn.setText("Connect to Spotify")
            self.refresh_btn.setEnabled(False)
            self.liked_btn.setEnabled(False)
            self.connection_changed.emit(False)

    def _show_oauth_dialog(self):
        dialog = SpotifyOAuthDialog(self.config, self)
        dialog.auth_completed.connect(self._on_auth_completed)
        dialog.exec()

    def _on_auth_completed(self, success: bool, message: str):
        if success:
            self._set_connected(True)
        else:
            QMessageBox.warning(self, "Authentication Failed", message)

    def _prompt_reconnect(self):
        reply = QMessageBox.question(
            self, "Session Expired",
            "Your Spotify session has expired.\nReconnect now?",
            QMessageBox.Yes | QMessageBox.No, QMessageBox.Yes,
        )
        if reply == QMessageBox.Yes:
            self._show_oauth_dialog()

    def _stop_worker(self):
        """Cancel any running worker before starting a new one."""
        if self.worker and self.worker.isRunning():
            self.worker.cancel()
            if not self.worker.wait(2000):
                self.worker.terminate()

    def _refresh_playlists(self):
        self._stop_worker()
        self._tracks_cache.clear()
        self.worker = SpotifyWorker(self.config)
        self.worker.playlists_loaded.connect(self._on_playlists_loaded)
        self.worker.error.connect(self._on_error)
        self.worker.progress.connect(self._on_progress)
        self.worker.fetch_playlists()
        self.progress_bar.setRange(0, 0)
        self.progress_bar.show()
        self.refresh_btn.setEnabled(False)

    def _on_playlists_loaded(self, playlists: list):
        self.progress_bar.hide()
        self.refresh_btn.setEnabled(True)
        self.playlist_list.clear()
        for playlist in playlists:
            count = playlist.get("tracks_total") or 0
            name = playlist.get("name", "")
            label = f"{name} ({count} tracks)" if count > 0 else name
            item = QListWidgetItem(label)
            item.setData(Qt.UserRole, playlist)
            self.playlist_list.addItem(item)

    def _load_selected_playlists(self):
        """Queue all selected playlists for loading."""
        selected = self.playlist_list.selectedItems()
        if not selected:
            QMessageBox.information(self, "No Selection", "Select playlists first (cmd+click for multiple).")
            return
        self._load_queue = []
        for item in selected:
            playlist = item.data(Qt.UserRole)
            if playlist and playlist.get("id") and playlist["id"] not in self._tracks_cache:
                self._load_queue.append((item, playlist))
        if self._load_queue:
            self._load_next_playlist()
        else:
            QMessageBox.information(self, "Already Loaded", "All selected playlists are already loaded.")

    def _load_next_playlist(self):
        if not self._load_queue:
            return
        if self.worker and self.worker.isRunning():
            return
        item, playlist = self._load_queue.pop(0)
        self._on_playlist_selected(item)

    def _download_selected_playlists(self):
        """Queue all selected playlists for download. Uses cache if available, fetches if not."""
        selected = self.playlist_list.selectedItems()
        if not selected:
            QMessageBox.information(self, "No Selection", "Select playlists first (cmd+click for multiple).")
            return

        queued_count = 0
        self._download_queue_playlists = []
        for item in selected:
            playlist = item.data(Qt.UserRole)
            if not playlist or not playlist.get("id"):
                continue
            pid = playlist["id"]
            if pid in self._tracks_cache:
                self.queue.add_tracks(self._tracks_cache[pid], playlist=playlist.get("name", ""))
                queued_count += len(self._tracks_cache[pid])
            else:
                self._download_queue_playlists.append(playlist)

        if self._download_queue_playlists:
            self._fetch_and_queue_next()

        if queued_count > 0:
            msg = f"Added {queued_count} cached tracks to download queue."
            if self._download_queue_playlists:
                msg += f"\nFetching {len(self._download_queue_playlists)} more playlist(s)..."
            QMessageBox.information(self, "Added to Queue", msg)

    def _fetch_and_queue_next(self):
        if not self._download_queue_playlists:
            QMessageBox.information(self, "Done", "All selected playlists have been queued for download.")
            return
        self._stop_worker()
        playlist = self._download_queue_playlists.pop(0)
        self.worker = SpotifyWorker(self.config)
        self.worker.tracks_loaded.connect(self._on_download_tracks_loaded)
        self.worker.error.connect(self._on_error)
        self.worker.progress.connect(self._on_progress)
        self.worker.fetch_playlist_tracks(playlist["id"], playlist["name"])
        self.progress_bar.setRange(0, 0)
        self.progress_bar.show()

    def _on_download_tracks_loaded(self, playlist_id: str, tracks: list):
        self.progress_bar.hide()
        self._tracks_cache[playlist_id] = tracks
        self._update_playlist_track_count(playlist_id, len(tracks))
        name = playlist_id
        for i in range(self.playlist_list.count()):
            item = self.playlist_list.item(i)
            p = item.data(Qt.UserRole)
            if p and p.get("id") == playlist_id:
                name = p.get("name", playlist_id)
                break
        self.queue.add_tracks(tracks, playlist=name)
        QTimer.singleShot(500, self._fetch_and_queue_next)

    def _download_single_playlist(self, playlist: dict):
        """Download a single playlist — use cache if available, fetch otherwise."""
        pid = playlist.get("id")
        name = playlist.get("name", "Unknown")
        if pid in self._tracks_cache:
            tracks = self._tracks_cache[pid]
            self.queue.add_tracks(tracks, playlist=name)
            QMessageBox.information(self, "Added to Queue",
                f"Added {len(tracks)} tracks from \"{name}\" to download queue.")
        else:
            self._download_queue_playlists = [playlist]
            self._fetch_and_queue_next()

    def _update_playlist_track_count(self, playlist_id: str, count: int):
        for i in range(self.playlist_list.count()):
            item = self.playlist_list.item(i)
            playlist = item.data(Qt.UserRole)
            if playlist and playlist.get("id") == playlist_id:
                playlist["tracks_total"] = count
                item.setText(f"{playlist['name']} ({count} tracks)")
                item.setData(Qt.UserRole, playlist)
                break

    def _on_playlist_selected(self, item: QListWidgetItem):
        playlist = item.data(Qt.UserRole)
        if not playlist:
            return
        pid = playlist["id"]
        self.tracks_label.setText(f"Tracks - {playlist['name']}")

        if pid in self._tracks_cache:
            self._populate_tracks(self._tracks_cache[pid])
            return

        self._stop_worker()
        self.worker = SpotifyWorker(self.config)
        self.worker.tracks_batch.connect(self._on_tracks_batch)
        self.worker.tracks_loaded.connect(self._on_tracks_loaded)
        self.worker.error.connect(self._on_error)
        self.worker.progress.connect(self._on_progress)
        self.worker.fetch_playlist_tracks(pid, playlist["name"])
        self.progress_bar.setRange(0, 0)
        self.progress_bar.show()
        self.current_tracks = []
        self.tracks_table.blockSignals(True)
        self.tracks_table.setRowCount(0)
        self.tracks_table.blockSignals(False)

    def _fetch_liked_songs(self):
        self.tracks_label.setText("Tracks - Liked Songs")

        if "__liked_songs__" in self._tracks_cache:
            self._populate_tracks(self._tracks_cache["__liked_songs__"])
            return

        self._stop_worker()
        self.worker = SpotifyWorker(self.config)
        self.worker.tracks_batch.connect(self._on_tracks_batch)
        self.worker.liked_songs_loaded.connect(self._on_liked_songs_loaded)
        self.worker.error.connect(self._on_error)
        self.worker.progress.connect(self._on_progress)
        self.worker.fetch_liked_songs()
        self.progress_bar.setRange(0, 0)
        self.progress_bar.show()
        self.liked_btn.setEnabled(False)
        self.current_tracks = []
        self.tracks_table.blockSignals(True)
        self.tracks_table.setRowCount(0)
        self.tracks_table.blockSignals(False)

    def _on_tracks_batch(self, playlist_id: str, batch: list):
        """Append a batch of tracks to the table as they stream in."""
        self.tracks_table.blockSignals(True)
        for track in batch:
            self.current_tracks.append(track)
            row = self.tracks_table.rowCount()
            self.tracks_table.insertRow(row)
            check_item = QTableWidgetItem()
            check_item.setFlags(Qt.ItemIsUserCheckable | Qt.ItemIsEnabled)
            check_item.setCheckState(Qt.CheckState.Unchecked)
            self.tracks_table.setItem(row, 0, check_item)
            self.tracks_table.setItem(row, 1, QTableWidgetItem(track.get("artist", "")))
            self.tracks_table.setItem(row, 2, QTableWidgetItem(track.get("track", "")))
            self.tracks_table.setItem(row, 3, QTableWidgetItem(track.get("album", "")))
        self.tracks_table.blockSignals(False)
        try:
            self.tracks_table.selectionModel().selectionChanged.disconnect(self._on_selection_changed)
        except RuntimeError:
            pass
        self.tracks_table.selectionModel().selectionChanged.connect(self._on_selection_changed)
        self._update_selection_count()
        self.add_btn.setEnabled(True)

    def _on_liked_songs_loaded(self, tracks: list):
        self.progress_bar.hide()
        self.liked_btn.setEnabled(True)
        self._tracks_cache["__liked_songs__"] = tracks
        self.tracks_table.selectionModel().selectionChanged.connect(self._on_selection_changed)
        self._update_selection_count()

    def _on_tracks_loaded(self, playlist_id: str, tracks: list):
        self.progress_bar.hide()
        self._tracks_cache[playlist_id] = tracks
        self.tracks_table.selectionModel().selectionChanged.connect(self._on_selection_changed)
        self._update_selection_count()
        if hasattr(self, '_load_queue') and self._load_queue:
            QTimer.singleShot(500, self._load_next_playlist)
        self._update_playlist_track_count(playlist_id, len(tracks))

    def _populate_tracks(self, tracks: list):
        self.current_tracks = tracks
        self.tracks_table.blockSignals(True)
        self.tracks_table.setRowCount(0)
        self.select_all_check.blockSignals(True)
        self.select_all_check.setChecked(False)
        self.select_all_check.blockSignals(False)

        for track in tracks:
            row = self.tracks_table.rowCount()
            self.tracks_table.insertRow(row)
            # Checkbox
            check_item = QTableWidgetItem()
            check_item.setFlags(Qt.ItemIsUserCheckable | Qt.ItemIsEnabled)
            check_item.setCheckState(Qt.CheckState.Unchecked)
            self.tracks_table.setItem(row, 0, check_item)

            # Track data
            self.tracks_table.setItem(row, 1, QTableWidgetItem(track.get("artist", "")))
            self.tracks_table.setItem(row, 2, QTableWidgetItem(track.get("track", "")))
            self.tracks_table.setItem(row, 3, QTableWidgetItem(track.get("album", "")))

        self.tracks_table.blockSignals(False)
        self.tracks_table.selectionModel().selectionChanged.connect(self._on_selection_changed)
        self._update_selection_count()
        self.add_btn.setEnabled(len(tracks) > 0)

    def _on_selection_changed(self):
        if self._updating_checks:
            return
        self._updating_checks = True
        selected_rows = {idx.row() for idx in self.tracks_table.selectionModel().selectedRows()}
        self.tracks_table.blockSignals(True)
        for row in range(self.tracks_table.rowCount()):
            item = self.tracks_table.item(row, 0)
            if item:
                item.setCheckState(Qt.CheckState.Checked if row in selected_rows else Qt.CheckState.Unchecked)
        self.tracks_table.blockSignals(False)
        self._updating_checks = False
        self._update_selection_count()

    def _on_item_changed(self, item: QTableWidgetItem):
        if item.column() == 0 and not self._updating_checks:
            self._update_selection_count()

    def _toggle_select_all(self, state):
        self._updating_checks = True
        if bool(state):
            self.tracks_table.selectAll()
        else:
            self.tracks_table.clearSelection()
        target = Qt.CheckState.Checked if bool(state) else Qt.CheckState.Unchecked
        self.tracks_table.blockSignals(True)
        for row in range(self.tracks_table.rowCount()):
            item = self.tracks_table.item(row, 0)
            if item:
                item.setCheckState(target)
        self.tracks_table.blockSignals(False)
        self._updating_checks = False
        self._update_selection_count()

    def _update_selection_count(self):
        count = self._get_selected_count()
        self.track_count_label.setText(f"{count} tracks selected")
        total = self.tracks_table.rowCount()
        self.select_all_check.blockSignals(True)
        self.select_all_check.setChecked(total > 0 and count == total)
        self.select_all_check.blockSignals(False)

    def _get_selected_count(self) -> int:
        count = 0
        for row in range(self.tracks_table.rowCount()):
            item = self.tracks_table.item(row, 0)
            if item and item.checkState() == Qt.CheckState.Checked:
                count += 1
        return count

    def _get_selected_tracks(self) -> list:
        selected = []
        for row in range(self.tracks_table.rowCount()):
            item = self.tracks_table.item(row, 0)
            if item and item.checkState() == Qt.CheckState.Checked:
                if row < len(self.current_tracks):
                    selected.append(self.current_tracks[row])
        return selected

    def _show_context_menu(self, position):
        if self.tracks_table.rowCount() == 0:
            return
        menu = QMenu(self)
        count = self._get_selected_count()

        dl = QAction(f"Download Selected ({count})", self)
        dl.triggered.connect(self._add_selected_to_queue)
        dl.setEnabled(count > 0)
        menu.addAction(dl)
        menu.addSeparator()

        row = self.tracks_table.rowAt(position.y())
        if 0 <= row < len(self.current_tracks):
            t = self.current_tracks[row]
            dl_one = QAction(f"Download \"{t.get('track', '')}\"", self)
            dl_one.triggered.connect(lambda checked, r=row: self._add_single_to_queue(r))
            menu.addAction(dl_one)
            menu.addSeparator()

        sa = QAction("Select All", self)
        sa.triggered.connect(lambda: self._set_all_checked(True))
        menu.addAction(sa)
        da = QAction("Deselect All", self)
        da.triggered.connect(lambda: self._set_all_checked(False))
        menu.addAction(da)
        inv = QAction("Invert Selection", self)
        inv.triggered.connect(self._invert_selection)
        menu.addAction(inv)
        menu.exec(self.tracks_table.viewport().mapToGlobal(position))

    def _show_playlist_context_menu(self, position):
        if self.playlist_list.count() == 0:
            return
        menu = QMenu(self)
        selected = self.playlist_list.selectedItems()
        if len(selected) > 1:
            load_sel = QAction(f"Load {len(selected)} Playlists", self)
            load_sel.triggered.connect(self._load_selected_playlists)
            menu.addAction(load_sel)
            dl_sel = QAction(f"Download {len(selected)} Playlists", self)
            dl_sel.triggered.connect(self._download_selected_playlists)
            menu.addAction(dl_sel)
            menu.addSeparator()
        item = self.playlist_list.itemAt(position)
        if item:
            playlist = item.data(Qt.UserRole)
            if playlist:
                load = QAction(f"Load \"{playlist.get('name', '')}\"", self)
                load.triggered.connect(lambda checked, i=item: self._on_playlist_selected(i))
                menu.addAction(load)

                dl = QAction(f"Download \"{playlist.get('name', '')}\"", self)
                dl.triggered.connect(lambda checked, p=playlist: self._download_single_playlist(p))
                menu.addAction(dl)
        menu.addSeparator()
        sa = QAction("Select All Playlists", self)
        sa.triggered.connect(self.playlist_list.selectAll)
        menu.addAction(sa)
        menu.exec(self.playlist_list.viewport().mapToGlobal(position))

    def _set_all_checked(self, checked: bool):
        self.select_all_check.blockSignals(True)
        self.select_all_check.setChecked(checked)
        self.select_all_check.blockSignals(False)
        self._toggle_select_all(2 if checked else 0)

    def _invert_selection(self):
        self._updating_checks = True
        for row in range(self.tracks_table.rowCount()):
            item = self.tracks_table.item(row, 0)
            if item:
                if item.checkState() == Qt.CheckState.Checked:
                    item.setCheckState(Qt.CheckState.Unchecked)
                else:
                    item.setCheckState(Qt.CheckState.Checked)
        self._updating_checks = False
        self._update_selection_count()

    def _add_single_to_queue(self, row: int):
        if row < len(self.current_tracks):
            track = self.current_tracks[row]
            playlist_name = self.tracks_label.text().replace("Tracks - ", "")
            self.queue.add_track(
                track.get("artist", "").strip(),
                track.get("track", "").strip(),
                playlist_name,
                album=track.get("album"),
                album_art_url=track.get("album_art_url"),
            )
            QMessageBox.information(
                self, "Added to Queue",
                f"Added \"{track.get('track', '')}\" by {track.get('artist', '')} to download queue.",
            )

    def _add_selected_to_queue(self):
        tracks = self._get_selected_tracks()
        if not tracks:
            QMessageBox.information(self, "No Selection", "Please select tracks to download.")
            return
        # Get playlist name for the queue
        playlist_name = self.tracks_label.text().replace("Tracks - ", "")

        # Add to queue
        self.queue.add_tracks(tracks, playlist=playlist_name)
        QMessageBox.information(
            self, "Added to Queue",
            f"Added {len(tracks)} tracks to download queue.\n\nGo to Downloads to start downloading.",
        )

    def _on_progress(self, message: str, current: int, total: int):
        if total > 0:
            self.progress_bar.setRange(0, total)
            self.progress_bar.setValue(current)
        else:
            self.progress_bar.setRange(0, 0)

    def _on_error(self, message: str):
        self.progress_bar.hide()
        self.refresh_btn.setEnabled(True)
        self.liked_btn.setEnabled(True)
        msg_lower = message.lower()
        if "401" in message or "token" in msg_lower or "expired" in msg_lower:
            self._set_connected(False)
            self._prompt_reconnect()
        else:
            QMessageBox.warning(self, "Error", message)
