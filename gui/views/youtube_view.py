"""YouTube download view."""

import json
import subprocess
import os

from PySide6.QtWidgets import (
    QWidget, QVBoxLayout, QHBoxLayout, QLabel,
    QPushButton, QLineEdit, QGroupBox,
    QMessageBox, QTextEdit, QScrollArea, QFrame,
    QSpacerItem, QSizePolicy, QListWidget, QListWidgetItem,
    QProgressBar
)
from PySide6.QtCore import Qt, QThread, Signal

from gui.workers.download_queue import DownloadQueue


class PlaylistFetchWorker(QThread):
    """Worker thread to fetch YouTube playlist metadata without blocking the GUI."""

    track_fetched = Signal(str, str)  # artist, track
    finished = Signal(list)  # list of (artist, track) tuples
    error = Signal(str)  # error message
    progress = Signal(int)  # number of tracks fetched so far

    def __init__(self, url: str, parent=None):
        super().__init__(parent)
        self.url = url

    def run(self):
        """Fetch playlist metadata using yt-dlp --flat-playlist."""
        try:
            cmd = [
                "yt-dlp",
                "--flat-playlist",
                "--dump-json",
                self.url
            ]
            process = subprocess.Popen(
                cmd,
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                text=True,
                creationflags=subprocess.CREATE_NO_WINDOW if os.name == 'nt' else 0
            )

            tracks = []
            for line in process.stdout:
                line = line.strip()
                if not line:
                    continue
                try:
                    data = json.loads(line)
                    title = data.get("title", "")
                    if not title:
                        continue
                    artist, track = self._parse_title(title)
                    tracks.append((artist, track))
                    self.track_fetched.emit(artist, track)
                    self.progress.emit(len(tracks))
                except json.JSONDecodeError:
                    continue

            process.wait()
            if process.returncode != 0 and not tracks:
                stderr = process.stderr.read()
                self.error.emit(stderr.strip() if stderr else "Failed to fetch playlist")
                return

            self.finished.emit(tracks)

        except FileNotFoundError:
            self.error.emit("yt-dlp not found. Please install yt-dlp.")
        except Exception as e:
            self.error.emit(str(e))

    @staticmethod
    def _parse_title(title: str) -> tuple:
        """Parse a video title into artist and track."""
        for sep in [" - ", " – ", " — ", " | "]:
            if sep in title:
                parts = title.split(sep, 1)
                return parts[0].strip(), parts[1].strip()
        return "Unknown Artist", title


class YouTubeView(QWidget):
    """View for downloading from YouTube URLs or search."""

    def __init__(self, config: dict, queue: DownloadQueue, parent=None):
        super().__init__(parent)
        self.config = config
        self.queue = queue
        self._playlist_tracks = []
        self._playlist_worker = None
        self._setup_ui()

    def _setup_ui(self):
        """Set up the YouTube UI."""
        main_layout = QVBoxLayout(self)
        main_layout.setContentsMargins(0, 0, 0, 0)

        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        scroll.setFrameShape(QFrame.NoFrame)

        scroll_widget = QWidget()
        layout = QVBoxLayout(scroll_widget)
        layout.setContentsMargins(40, 30, 40, 30)
        layout.setSpacing(20)

        # Title
        title = QLabel("YouTube Download")
        title.setObjectName("title")
        layout.addWidget(title)

        subtitle = QLabel("Download music from YouTube by URL or search query")
        subtitle.setObjectName("subtitle")
        layout.addWidget(subtitle)

        # Single URL/Search Group
        single_group = QGroupBox("Download Single Track")
        single_layout = QVBoxLayout(single_group)
        single_layout.setSpacing(12)

        url_label = QLabel("URL or search query")
        url_label.setObjectName("muted")
        single_layout.addWidget(url_label)

        self.url_input = QLineEdit()
        self.url_input.setPlaceholderText("Enter YouTube URL or search query (e.g., 'Artist - Song Name')")
        self.url_input.returnPressed.connect(self._add_single_to_queue)
        single_layout.addWidget(self.url_input)

        single_btn_layout = QHBoxLayout()
        single_btn_layout.addStretch()
        add_btn = QPushButton("Add to Queue")
        add_btn.clicked.connect(self._add_single_to_queue)
        single_btn_layout.addWidget(add_btn)
        single_layout.addLayout(single_btn_layout)

        layout.addWidget(single_group)

        # Playlist group
        playlist_group = QGroupBox("Download YouTube Playlist")
        playlist_layout = QVBoxLayout(playlist_group)
        playlist_layout.setSpacing(12)

        playlist_label = QLabel("Paste a YouTube playlist URL to fetch all tracks")
        playlist_label.setObjectName("muted")
        playlist_layout.addWidget(playlist_label)

        playlist_input_layout = QHBoxLayout()
        self.playlist_url_input = QLineEdit()
        self.playlist_url_input.setPlaceholderText("https://www.youtube.com/playlist?list=...")
        self.playlist_url_input.returnPressed.connect(self._fetch_playlist)
        playlist_input_layout.addWidget(self.playlist_url_input)

        self.fetch_playlist_btn = QPushButton("Fetch Playlist")
        self.fetch_playlist_btn.clicked.connect(self._fetch_playlist)
        playlist_input_layout.addWidget(self.fetch_playlist_btn)
        playlist_layout.addLayout(playlist_input_layout)

        self.playlist_progress = QProgressBar()
        self.playlist_progress.setTextVisible(True)
        self.playlist_progress.setFormat("Fetching tracks... %v found")
        self.playlist_progress.setRange(0, 0)
        self.playlist_progress.hide()
        playlist_layout.addWidget(self.playlist_progress)

        self.playlist_list = QListWidget()
        self.playlist_list.setMinimumHeight(120)
        self.playlist_list.setMaximumHeight(250)
        self.playlist_list.hide()
        playlist_layout.addWidget(self.playlist_list)

        playlist_btn_layout = QHBoxLayout()
        playlist_btn_layout.addStretch()

        self.clear_playlist_btn = QPushButton("Clear")
        self.clear_playlist_btn.setObjectName("secondary")
        self.clear_playlist_btn.clicked.connect(self._clear_playlist)
        self.clear_playlist_btn.hide()
        playlist_btn_layout.addWidget(self.clear_playlist_btn)

        self.add_playlist_btn = QPushButton("Add All to Queue")
        self.add_playlist_btn.clicked.connect(self._add_playlist_to_queue)
        self.add_playlist_btn.hide()
        playlist_btn_layout.addWidget(self.add_playlist_btn)

        playlist_layout.addLayout(playlist_btn_layout)

        layout.addWidget(playlist_group)

        # Batch input group
        batch_group = QGroupBox("Batch Download")
        batch_layout = QVBoxLayout(batch_group)
        batch_layout.setSpacing(12)

        help_label = QLabel("Enter multiple search queries, one per line (format: Artist - Track Name)")
        help_label.setObjectName("muted")
        help_label.setWordWrap(True)
        batch_layout.addWidget(help_label)

        self.batch_input = QTextEdit()
        self.batch_input.setPlaceholderText(
            "Example:\n"
            "The Weeknd - Blinding Lights\n"
            "Dua Lipa - Levitating\n"
            "Ed Sheeran - Shape of You"
        )
        self.batch_input.setMinimumHeight(150)
        self.batch_input.setMaximumHeight(250)
        batch_layout.addWidget(self.batch_input)

        batch_btn_layout = QHBoxLayout()
        batch_btn_layout.addStretch()

        clear_btn = QPushButton("Clear")
        clear_btn.setObjectName("secondary")
        clear_btn.clicked.connect(self._clear_batch)
        batch_btn_layout.addWidget(clear_btn)

        add_batch_btn = QPushButton("Add All to Queue")
        add_batch_btn.clicked.connect(self._add_batch_to_queue)
        batch_btn_layout.addWidget(add_batch_btn)

        batch_layout.addLayout(batch_btn_layout)

        layout.addWidget(batch_group)

        # Tips section
        tips_group = QGroupBox("Tips")
        tips_layout = QVBoxLayout(tips_group)
        tips_layout.setSpacing(8)

        tips_text = QLabel(
            "- For best results, use the format: Artist - Track Name\n"
            "- YouTube URLs are also supported (paste the full URL)\n"
            "- YouTube playlist URLs are auto-detected - use the playlist section to preview tracks\n"
            "- The search will find the first matching result on YouTube\n"
            "- Check the Downloads tab to monitor progress"
        )
        tips_text.setWordWrap(True)
        tips_text.setObjectName("subtitle")
        tips_layout.addWidget(tips_text)

        layout.addWidget(tips_group)

        layout.addSpacerItem(QSpacerItem(20, 20, QSizePolicy.Minimum, QSizePolicy.Expanding))

        scroll.setWidget(scroll_widget)
        main_layout.addWidget(scroll)

    @staticmethod
    def _is_playlist_url(url: str) -> bool:
        """Check if a URL is a YouTube playlist URL."""
        return ("youtube.com" in url or "youtu.be" in url) and "list=" in url

    def _parse_query(self, query: str) -> tuple:
        """
        Parse a search query into artist and track.

        Returns:
            Tuple of (artist, track)
        """
        query = query.strip()
        if not query:
            return None, None

        # Check if it's a URL
        if query.startswith(("http://", "https://", "www.")):
            # Detect playlist URLs and redirect user
            if self._is_playlist_url(query):
                return "playlist", query
            return "YouTube", query

        # Try to split by common separators
        for sep in [" - ", " – ", " — ", " | "]:
            if sep in query:
                parts = query.split(sep, 1)
                return parts[0].strip(), parts[1].strip()

        # No separator found, use query as track name
        return "Unknown Artist", query

    def _add_single_to_queue(self):
        """Add single URL/search to queue."""
        query = self.url_input.text().strip()
        if not query:
            QMessageBox.warning(self, "Empty Input", "Please enter a URL or search query.")
            return

        artist, track = self._parse_query(query)
        if artist == "playlist":
            QMessageBox.information(
                self,
                "Playlist Detected",
                "This looks like a YouTube playlist URL.\n\n"
                "Please use the 'Download YouTube Playlist' section below "
                "to fetch and preview all tracks before adding them to the queue."
            )
            self.playlist_url_input.setText(track)
            return

        if artist and track:
            self.queue.add_track(artist, track)
            self.url_input.clear()
            QMessageBox.information(
                self,
                "Added to Queue",
                f"Added '{artist} - {track}' to download queue.\n\n"
                "Go to Downloads to start downloading."
            )
        else:
            QMessageBox.warning(self, "Invalid Input", "Could not parse the input.")

    def _add_batch_to_queue(self):
        """Add batch queries to queue."""
        text = self.batch_input.toPlainText().strip()
        if not text:
            QMessageBox.warning(self, "Empty Input", "Please enter some search queries.")
            return

        lines = text.split("\n")
        added = 0
        skipped = 0

        for line in lines:
            line = line.strip()
            if not line:
                continue

            artist, track = self._parse_query(line)
            if artist and track:
                self.queue.add_track(artist, track)
                added += 1
            else:
                skipped += 1

        if added > 0:
            self.batch_input.clear()
            message = f"Added {added} tracks to download queue."
            if skipped > 0:
                message += f"\n{skipped} lines were skipped (empty or invalid)."
            message += "\n\nGo to Downloads to start downloading."
            QMessageBox.information(self, "Added to Queue", message)
        else:
            QMessageBox.warning(self, "No Tracks Added", "No valid tracks found in the input.")

    def _clear_batch(self):
        """Clear batch input."""
        self.batch_input.clear()

    def _fetch_playlist(self):
        """Fetch playlist metadata from a YouTube playlist URL."""
        url = self.playlist_url_input.text().strip()
        if not url:
            QMessageBox.warning(self, "Empty Input", "Please enter a YouTube playlist URL.")
            return

        if not self._is_playlist_url(url):
            QMessageBox.warning(
                self,
                "Invalid URL",
                "This does not appear to be a YouTube playlist URL.\n"
                "Playlist URLs contain a 'list=' parameter."
            )
            return

        # Reset state
        self._playlist_tracks = []
        self.playlist_list.clear()
        self.playlist_list.hide()
        self.add_playlist_btn.hide()
        self.clear_playlist_btn.hide()

        # Show progress
        self.playlist_progress.setValue(0)
        self.playlist_progress.show()
        self.fetch_playlist_btn.setEnabled(False)
        self.fetch_playlist_btn.setText("Fetching...")

        # Start worker thread
        self._playlist_worker = PlaylistFetchWorker(url)
        self._playlist_worker.track_fetched.connect(self._on_playlist_track_fetched)
        self._playlist_worker.progress.connect(self._on_playlist_progress)
        self._playlist_worker.finished.connect(self._on_playlist_finished)
        self._playlist_worker.error.connect(self._on_playlist_error)
        self._playlist_worker.start()

    def _on_playlist_track_fetched(self, artist: str, track: str):
        """Handle a single track fetched from the playlist."""
        item = QListWidgetItem(f"{artist} - {track}")
        self.playlist_list.addItem(item)

    def _on_playlist_progress(self, count: int):
        """Update progress as tracks are fetched."""
        self.playlist_progress.setValue(count)

    def _on_playlist_finished(self, tracks: list):
        """Handle playlist fetch completion."""
        self._playlist_tracks = tracks
        self.playlist_progress.hide()
        self.fetch_playlist_btn.setEnabled(True)
        self.fetch_playlist_btn.setText("Fetch Playlist")

        if tracks:
            self.playlist_list.show()
            self.add_playlist_btn.show()
            self.clear_playlist_btn.show()
            self.playlist_progress.setFormat(f"{len(tracks)} tracks found")
        else:
            QMessageBox.warning(
                self,
                "No Tracks Found",
                "No tracks were found in this playlist.\n"
                "The playlist may be empty or private."
            )

    def _on_playlist_error(self, error_msg: str):
        """Handle playlist fetch error."""
        self.playlist_progress.hide()
        self.fetch_playlist_btn.setEnabled(True)
        self.fetch_playlist_btn.setText("Fetch Playlist")
        QMessageBox.warning(
            self,
            "Playlist Error",
            f"Failed to fetch playlist:\n\n{error_msg}"
        )

    def _add_playlist_to_queue(self):
        """Add all fetched playlist tracks to the download queue."""
        if not self._playlist_tracks:
            QMessageBox.warning(self, "No Tracks", "No tracks to add. Fetch a playlist first.")
            return

        added = 0
        for artist, track in self._playlist_tracks:
            if artist and track:
                self.queue.add_track(artist, track)
                added += 1

        if added > 0:
            self._clear_playlist()
            QMessageBox.information(
                self,
                "Added to Queue",
                f"Added {added} tracks from playlist to download queue.\n\n"
                "Go to Downloads to start downloading."
            )

    def _clear_playlist(self):
        """Clear the playlist preview."""
        self._playlist_tracks = []
        self.playlist_list.clear()
        self.playlist_list.hide()
        self.add_playlist_btn.hide()
        self.clear_playlist_btn.hide()
        self.playlist_url_input.clear()
