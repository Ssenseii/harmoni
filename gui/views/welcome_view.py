"""Welcome view with quick start guide and Exportify import."""

import os
import csv
from PySide6.QtWidgets import (
    QWidget, QVBoxLayout, QHBoxLayout, QLabel,
    QPushButton, QFrame, QSizePolicy,
    QMessageBox, QScrollArea, QGridLayout
)
from PySide6.QtCore import Qt, Signal

from gui.workers.download_queue import DownloadQueue


class DropZone(QFrame):
    """Drop zone widget for Exportify CSV files."""

    files_dropped = Signal(list)

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setObjectName("dropZone")
        self.setAcceptDrops(True)
        self.setMinimumHeight(180)
        self._setup_ui()

    def _setup_ui(self):
        layout = QVBoxLayout(self)
        layout.setAlignment(Qt.AlignCenter)
        layout.setSpacing(12)
        layout.setContentsMargins(40, 30, 40, 30)

        # Upload icon using text
        icon = QLabel("+")
        icon.setStyleSheet("""
            font-size: 48px;
            font-weight: 300;
            color: #6a6a80;
            background: transparent;
        """)
        icon.setAlignment(Qt.AlignCenter)
        layout.addWidget(icon)

        title = QLabel("Drop your Exportify CSV file here")
        title.setObjectName("section")
        title.setStyleSheet("font-size: 16px;")
        title.setAlignment(Qt.AlignCenter)
        layout.addWidget(title)

        hint = QLabel("or click anywhere in this box to browse")
        hint.setObjectName("muted")
        hint.setStyleSheet("font-size: 13px;")
        hint.setAlignment(Qt.AlignCenter)
        layout.addWidget(hint)

    def dragEnterEvent(self, event):
        if event.mimeData().hasUrls():
            for url in event.mimeData().urls():
                if url.toLocalFile().lower().endswith('.csv'):
                    event.acceptProposedAction()
                    self.setObjectName("dropZoneActive")
                    self.style().unpolish(self)
                    self.style().polish(self)
                    return
        event.ignore()

    def dragLeaveEvent(self, event):
        self.setObjectName("dropZone")
        self.style().unpolish(self)
        self.style().polish(self)

    def dropEvent(self, event):
        self.setObjectName("dropZone")
        self.style().unpolish(self)
        self.style().polish(self)

        files = []
        for url in event.mimeData().urls():
            file_path = url.toLocalFile()
            if file_path.lower().endswith('.csv'):
                files.append(file_path)

        if files:
            self.files_dropped.emit(files)
            event.acceptProposedAction()
        else:
            event.ignore()

    def mousePressEvent(self, event):
        if event.button() == Qt.LeftButton:
            from PySide6.QtWidgets import QFileDialog
            files, _ = QFileDialog.getOpenFileNames(
                self,
                "Select Exportify CSV Files",
                "",
                "CSV Files (*.csv)"
            )
            if files:
                self.files_dropped.emit(files)


class StepCard(QFrame):
    """A numbered step card for instructions."""

    def __init__(self, number: int, title: str, description: str, parent=None):
        super().__init__(parent)
        self.setObjectName("card")
        self.setStyleSheet("StepCard { background-color: #282840; }")
        self._setup_ui(number, title, description)

    def _setup_ui(self, number: int, title: str, description: str):
        layout = QHBoxLayout(self)
        layout.setContentsMargins(20, 20, 20, 20)
        layout.setSpacing(16)

        # Number badge
        number_label = QLabel(str(number))
        number_label.setFixedSize(40, 40)
        number_label.setAlignment(Qt.AlignCenter)
        number_label.setStyleSheet("""
            background-color: #3c92de;
            color: white;
            font-size: 18px;
            font-weight: 700;
            border-radius: 20px;
        """)
        layout.addWidget(number_label)

        # Text content
        text_layout = QVBoxLayout()
        text_layout.setSpacing(4)

        title_label = QLabel(title)
        title_label.setStyleSheet("font-size: 15px; font-weight: 600;")
        text_layout.addWidget(title_label)

        desc_label = QLabel(description)
        desc_label.setObjectName("muted")
        desc_label.setStyleSheet("font-size: 13px;")
        desc_label.setWordWrap(True)
        text_layout.addWidget(desc_label)

        layout.addLayout(text_layout, 1)


class FeatureCard(QFrame):
    """A feature card with icon, title, description and action button."""

    clicked = Signal()

    def __init__(self, title: str, description: str, button_text: str, parent=None):
        super().__init__(parent)
        self.setObjectName("card")
        self.setCursor(Qt.PointingHandCursor)
        self.setMinimumWidth(200)
        self.setMinimumHeight(150)
        self.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Minimum)
        self._setup_ui(title, description, button_text)

    def _setup_ui(self, title: str, description: str, button_text: str):
        layout = QVBoxLayout(self)
        layout.setContentsMargins(24, 24, 24, 24)
        layout.setSpacing(12)

        # Title
        title_label = QLabel(title)
        title_label.setStyleSheet("font-size: 18px; font-weight: 600;")
        layout.addWidget(title_label)

        # Description
        desc_label = QLabel(description)
        desc_label.setObjectName("subtitle")
        desc_label.setStyleSheet("font-size: 14px;")
        desc_label.setWordWrap(True)
        layout.addWidget(desc_label)

        layout.addStretch()

        # Button
        btn = QPushButton(button_text)
        btn.setMinimumWidth(80)
        btn.setSizePolicy(QSizePolicy.Minimum, QSizePolicy.Fixed)
        btn.clicked.connect(self.clicked.emit)
        layout.addWidget(btn)

    def mousePressEvent(self, event):
        if event.button() == Qt.LeftButton:
            self.clicked.emit()


class WelcomeView(QWidget):
    """Welcome screen with quick start instructions and Exportify import."""

    navigate_to = Signal(str)

    def __init__(self, config: dict, download_queue: DownloadQueue = None, parent=None):
        super().__init__(parent)
        self.config = config
        self.download_queue = download_queue
        self._setup_ui()

    def _setup_ui(self):
        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        scroll.setFrameShape(QFrame.NoFrame)

        scroll_widget = QWidget()
        layout = QVBoxLayout(scroll_widget)
        layout.setContentsMargins(48, 40, 48, 40)
        layout.setSpacing(32)

        # Header
        header = QVBoxLayout()
        header.setSpacing(12)

        title = QLabel("Welcome to HARMONI")
        title.setObjectName("title")
        title.setStyleSheet("font-size: 32px; font-weight: 700;")
        header.addWidget(title)

        subtitle = QLabel("Download your favorite music from Spotify playlists and YouTube")
        subtitle.setObjectName("subtitle")
        subtitle.setStyleSheet("font-size: 16px;")
        header.addWidget(subtitle)

        layout.addLayout(header)

        # ============================================================
        # EASIEST WAY SECTION - Exportify
        # ============================================================
        easiest_section = QFrame()
        easiest_section.setObjectName("cardAccent")
        easiest_layout = QVBoxLayout(easiest_section)
        easiest_layout.setContentsMargins(28, 24, 28, 28)
        easiest_layout.setSpacing(20)

        # Section header
        easiest_header = QHBoxLayout()

        easiest_title = QLabel("Easiest Way to Download Your Spotify Music")
        easiest_title.setStyleSheet("font-size: 20px; font-weight: 700; color: #3c92de;")
        easiest_header.addWidget(easiest_title)

        easiest_header.addStretch()

        easiest_badge = QLabel("RECOMMENDED")
        easiest_badge.setStyleSheet("""
            background-color: #3c92de;
            color: white;
            font-size: 11px;
            font-weight: 700;
            padding: 4px 12px;
            border-radius: 4px;
        """)
        easiest_header.addWidget(easiest_badge)

        self.toggle_help_btn = QPushButton("Hide Guide")
        self.toggle_help_btn.setObjectName("ghost")
        self.toggle_help_btn.clicked.connect(self._toggle_help)
        easiest_header.addWidget(self.toggle_help_btn)

        easiest_layout.addLayout(easiest_header)

        # Collapsible help content
        self.help_container = QWidget()
        self.help_container.setStyleSheet("background: transparent;")
        help_layout = QVBoxLayout(self.help_container)
        help_layout.setContentsMargins(0, 0, 0, 0)
        help_layout.setSpacing(12)

        # Explanation
        explanation = QLabel(
            "Exportify is a free website that exports your Spotify playlists to CSV files. "
            "This is the simplest way to download your music - no Spotify API setup required!"
        )
        explanation.setStyleSheet("font-size: 14px; line-height: 1.5;")
        explanation.setWordWrap(True)
        help_layout.addWidget(explanation)

        # Steps
        steps_layout = QVBoxLayout()
        steps_layout.setSpacing(12)

        step1 = StepCard(
            1,
            "Go to exportify.net",
            "Open your web browser and visit exportify.net - it's free and safe to use"
        )
        steps_layout.addWidget(step1)

        step2 = StepCard(
            2,
            "Log in with your Spotify account",
            "Click the green button to connect your Spotify. Exportify will show all your playlists."
        )
        steps_layout.addWidget(step2)

        step3 = StepCard(
            3,
            "Export the playlist you want",
            "Click 'Export' next to any playlist. A CSV file will download to your computer."
        )
        steps_layout.addWidget(step3)

        step4 = StepCard(
            4,
            "Drag the CSV file below",
            "Drag and drop the downloaded CSV file into the box below, or click to browse."
        )
        steps_layout.addWidget(step4)

        help_layout.addLayout(steps_layout)
        easiest_layout.addWidget(self.help_container)

        # Link to exportify
        link_layout = QHBoxLayout()
        link_layout.setSpacing(12)

        exportify_btn = QPushButton("\u2197  Open exportify.net")
        exportify_btn.setStyleSheet("""
            QPushButton {
                background-color: rgba(255, 255, 255, 0.12);
                color: #e3e4e0;
                border: 1px solid rgba(255, 255, 255, 0.2);
                padding: 10px 20px;
                border-radius: 6px;
                font-weight: 600;
                font-size: 13px;
            }
            QPushButton:hover {
                background-color: rgba(255, 255, 255, 0.2);
                border-color: rgba(255, 255, 255, 0.35);
            }
            QPushButton:pressed { background-color: rgba(255, 255, 255, 0.08); }
        """)
        exportify_btn.setCursor(Qt.PointingHandCursor)
        exportify_btn.clicked.connect(self._open_exportify)
        link_layout.addWidget(exportify_btn)

        link_layout.addStretch()

        easiest_layout.addLayout(link_layout)

        # Drop zone
        self.drop_zone = DropZone()
        self.drop_zone.files_dropped.connect(self._handle_dropped_files)
        easiest_layout.addWidget(self.drop_zone)

        layout.addWidget(easiest_section)

        # Divider with "OR"
        divider_layout = QHBoxLayout()
        divider_layout.setSpacing(16)

        left_line = QFrame()
        left_line.setObjectName("divider")
        left_line.setFrameShape(QFrame.HLine)
        left_line.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Fixed)
        divider_layout.addWidget(left_line)

        or_label = QLabel("OR USE OTHER METHODS")
        or_label.setObjectName("sectionSmall")
        or_label.setStyleSheet("font-size: 12px; color: #6a6a80;")
        divider_layout.addWidget(or_label)

        right_line = QFrame()
        right_line.setObjectName("divider")
        right_line.setFrameShape(QFrame.HLine)
        right_line.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Fixed)
        divider_layout.addWidget(right_line)

        layout.addLayout(divider_layout)

        # Feature cards in 2x2 grid layout
        cards_grid = QGridLayout()
        cards_grid.setSpacing(16)

        # Spotify Card
        spotify_card = FeatureCard(
            "Spotify Direct",
            "Connect to Spotify with API credentials to browse and download playlists directly from the app. Requires setup.",
            "Open Spotify"
        )
        spotify_card.clicked.connect(lambda: self.navigate_to.emit("spotify"))
        cards_grid.addWidget(spotify_card, 0, 0)

        # YouTube Card
        youtube_card = FeatureCard(
            "YouTube",
            "Download audio from YouTube by pasting a video or playlist URL, or search for songs directly.",
            "Open YouTube"
        )
        youtube_card.clicked.connect(lambda: self.navigate_to.emit("youtube"))
        cards_grid.addWidget(youtube_card, 0, 1)

        # Downloads Card
        downloads_card = FeatureCard(
            "Downloads",
            "View and manage your download queue. Track progress and see completed downloads.",
            "View Queue"
        )
        downloads_card.clicked.connect(lambda: self.navigate_to.emit("downloads"))
        cards_grid.addWidget(downloads_card, 1, 0)

        # Settings Card
        settings_card = FeatureCard(
            "Settings",
            "Configure output folder, audio format (MP3, FLAC, etc.), quality settings, and more.",
            "Open Settings"
        )
        settings_card.clicked.connect(lambda: self.navigate_to.emit("settings"))
        cards_grid.addWidget(settings_card, 1, 1)

        layout.addLayout(cards_grid)

        # Spacer
        layout.addStretch()

        # Warning card if Spotify not configured
        if not self.config.get("spotify_client_id"):
            warning_card = QFrame()
            warning_card.setObjectName("cardWarning")
            warning_layout = QHBoxLayout(warning_card)
            warning_layout.setContentsMargins(24, 20, 24, 20)
            warning_layout.setSpacing(16)

            warning_icon = QLabel("!")
            warning_icon.setFixedSize(32, 32)
            warning_icon.setAlignment(Qt.AlignCenter)
            warning_icon.setStyleSheet("""
                background-color: #ff9800;
                color: white;
                font-size: 18px;
                font-weight: 700;
                border-radius: 16px;
            """)
            warning_layout.addWidget(warning_icon)

            warning_text = QVBoxLayout()
            warning_text.setSpacing(4)

            warning_title = QLabel("Spotify API not configured")
            warning_title.setStyleSheet("font-weight: 600; font-size: 14px;")
            warning_text.addWidget(warning_title)

            warning_desc = QLabel(
                "To use Spotify Direct mode, set up your Spotify Client ID in Settings. "
                "Or use Exportify above - it works without any setup!"
            )
            warning_desc.setObjectName("muted")
            warning_desc.setStyleSheet("font-size: 13px;")
            warning_desc.setWordWrap(True)
            warning_text.addWidget(warning_desc)

            warning_layout.addLayout(warning_text, 1)

            setup_btn = QPushButton("Set Up")
            setup_btn.setObjectName("secondary")
            setup_btn.clicked.connect(lambda: self.navigate_to.emit("settings"))
            warning_layout.addWidget(setup_btn)

            layout.addWidget(warning_card)

        scroll.setWidget(scroll_widget)

        main_layout = QVBoxLayout(self)
        main_layout.setContentsMargins(0, 0, 0, 0)
        main_layout.addWidget(scroll)

    def _toggle_help(self):
        visible = self.help_container.isVisible()
        self.help_container.setVisible(not visible)
        self.toggle_help_btn.setText("Show Guide" if visible else "Hide Guide")

    def _open_exportify(self):
        """Open Exportify website in browser."""
        import webbrowser
        webbrowser.open("https://exportify.net")

    def _handle_dropped_files(self, files: list):
        if not self.download_queue:
            QMessageBox.warning(self, "Error", "Download queue not available")
            return

        total_tracks = []

        for file_path in files:
            try:
                tracks = self._parse_exportify_csv(file_path)
                if tracks:
                    total_tracks.extend(tracks)
            except Exception as e:
                QMessageBox.warning(
                    self,
                    "Import Error",
                    f"Failed to parse {os.path.basename(file_path)}:\n{str(e)}"
                )

        if not total_tracks:
            QMessageBox.information(
                self,
                "No Tracks Found",
                "No valid tracks were found in the dropped files.\n\n"
                "Make sure you're using a CSV file exported from Exportify."
            )
            return

        reply = QMessageBox.question(
            self,
            "Import Tracks",
            f"Found {len(total_tracks)} tracks.\n\nAdd them to the download queue?",
            QMessageBox.Yes | QMessageBox.No,
            QMessageBox.Yes
        )

        if reply == QMessageBox.Yes:
            self._add_tracks_to_queue(total_tracks)
            QMessageBox.information(
                self,
                "Import Complete",
                f"Added {len(total_tracks)} tracks to the queue.\n\n"
                "Go to Downloads to start downloading."
            )
            self.navigate_to.emit("downloads")

    def _parse_exportify_csv(self, file_path: str) -> list:
        tracks = []

        with open(file_path, 'r', encoding='utf-8') as f:
            reader = csv.DictReader(f)

            for row in reader:
                track_name = row.get('Track Name') or row.get('track_name') or row.get('name')
                artist_name = row.get('Artist Name(s)') or row.get('artist_name') or row.get('artist')
                album_name = row.get('Album Name') or row.get('album_name') or row.get('album')
                playlist_name = row.get('Playlist Name') or row.get('playlist_name') or os.path.basename(file_path)

                if track_name and artist_name:
                    if ',' in artist_name:
                        artist_name = artist_name.split(',')[0].strip()
                    elif ';' in artist_name:
                        artist_name = artist_name.split(';')[0].strip()

                    tracks.append({
                        'track': track_name.strip(),
                        'artist': artist_name.strip(),
                        'album': album_name.strip() if album_name else '',
                        'playlist': playlist_name.replace('.csv', '').strip() if playlist_name else 'Import'
                    })

        return tracks

    def _add_tracks_to_queue(self, tracks: list):
        if not self.download_queue:
            return

        for track_data in tracks:
            self.download_queue.add_item(
                artist=track_data['artist'],
                track=track_data['track'],
                album=track_data.get('album', ''),
                playlist=track_data.get('playlist', ''),
                album_art_url=track_data.get('album_art_url', ''),
            )
