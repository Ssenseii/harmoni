"""YouTube download view."""

from PySide6.QtWidgets import (
    QWidget, QVBoxLayout, QHBoxLayout, QLabel,
    QPushButton, QLineEdit, QGroupBox,
    QMessageBox, QTextEdit, QScrollArea, QFrame,
    QSpacerItem, QSizePolicy
)
from PySide6.QtCore import Qt, Signal

from gui.notices import QUEUED_HINT, notify
from gui.workers.download_queue import DownloadQueue


class YouTubeView(QWidget):
    """View for downloading from YouTube URLs or search."""

    navigate_to = Signal(str)

    def __init__(self, config: dict, queue: DownloadQueue, parent=None):
        super().__init__(parent)
        self.config = config
        self.queue = queue
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
            notify("Enter a YouTube link or 'Artist - Song' first.")
            return

        artist, track = self._parse_query(query)
        if artist and track:
            self.queue.add_track(artist, track)
            self.url_input.clear()
            self._notify_queued(f"Added '{artist} - {track}' to the download queue.")
        else:
            notify("Couldn't read that. Use a YouTube link or 'Artist - Song'.", "warning")

    def _notify_queued(self, text: str):
        """Say tracks were queued, that they wait for Start Downloads, and offer to open Downloads.

        @param text: What was added.
        """
        notify(f"{text} {QUEUED_HINT}", "success", "Go to Downloads", lambda: self.navigate_to.emit("downloads"))

    def _add_batch_to_queue(self):
        """Add batch queries to queue."""
        text = self.batch_input.toPlainText().strip()
        if not text:
            notify("Enter one 'Artist - Song' per line first.")
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
            message = f"Added {added} tracks to the download queue."
            if skipped > 0:
                message += f" Skipped {skipped} lines that weren't 'Artist - Song'."
            self._notify_queued(message)
        else:
            notify("No 'Artist - Song' lines found.", "warning")

    def _clear_batch(self):
        """Clear batch input."""
        self.batch_input.clear()
