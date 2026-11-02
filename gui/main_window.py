"""Main window with custom title bar and sidebar navigation for HARMONI GUI."""

from PySide6.QtWidgets import (
    QMainWindow, QWidget, QHBoxLayout, QVBoxLayout,
    QListWidget, QListWidgetItem, QStackedWidget,
    QStatusBar, QLabel, QFrame, QPushButton
)
import os

from PySide6.QtCore import Qt, QSize, QPoint, QUrl
from PySide6.QtGui import QDesktopServices, QIcon, QMouseEvent

from gui.views.welcome_view import WelcomeView
from gui.views.spotify_view import SpotifyView
from gui.views.youtube_view import YouTubeView
from gui.views.downloads_view import DownloadsView
from gui.views.settings_view import SettingsView
from gui.workers.download_queue import DownloadQueue
from gui.workers.app_update_worker import AppUpdateCheckWorker
from gui.workers.ytdlp_update_worker import YtdlpUpdateCheckWorker
from version import __version__


class TitleBar(QWidget):
    """Custom title bar widget for frameless window."""

    def __init__(self, parent=None):
        super().__init__(parent)
        self.parent_window = parent
        self._drag_pos = None
        self._is_maximized = False
        self.setObjectName("titleBar")
        self.setFixedHeight(40)
        self._setup_ui()

    def _setup_ui(self):
        """Set up the title bar UI."""
        from gui.resources.icons import get_app_icon, has_icon

        layout = QHBoxLayout(self)
        layout.setContentsMargins(12, 0, 0, 0)
        layout.setSpacing(8)

        # App icon
        app_icon = get_app_icon()
        if not app_icon.isNull():
            icon_label = QLabel()
            icon_label.setPixmap(app_icon.pixmap(20, 20))
            icon_label.setFixedSize(24, 24)
            icon_label.setStyleSheet("background: transparent;")
            layout.addWidget(icon_label)

        # App name with version badge
        self.title_label = QLabel("HARMONI")
        self.title_label.setStyleSheet("""
            font-size: 15px;
            font-weight: 700;
            color: #e3e4e0;
            letter-spacing: 1px;
        """)
        layout.addWidget(self.title_label)

        # Version badge
        version_label = QLabel(f"v{__version__}")
        version_label.setStyleSheet("""
            font-size: 10px;
            font-weight: 600;
            color: #9a9ab0;
            background-color: #383852;
            padding: 2px 6px;
            border-radius: 4px;
        """)
        layout.addWidget(version_label)

        layout.addStretch()

        # Window control buttons - using simple ASCII for reliability
        self.min_btn = QPushButton()
        self.min_btn.setText("-")
        self.min_btn.setObjectName("titleBarBtn")
        self.min_btn.setFixedSize(46, 40)
        self.min_btn.setStyleSheet("""
            QPushButton {
                font-size: 18px;
                font-weight: 400;
                border: none;
                background: transparent;
                color: #9a9ab0;
            }
            QPushButton:hover {
                background-color: #383852;
                color: #e3e4e0;
            }
        """)
        self.min_btn.clicked.connect(self._minimize)
        layout.addWidget(self.min_btn)

        self.max_btn = QPushButton()
        self.max_btn.setText("[ ]")
        self.max_btn.setObjectName("titleBarBtn")
        self.max_btn.setFixedSize(46, 40)
        self.max_btn.setStyleSheet("""
            QPushButton {
                font-size: 11px;
                font-weight: 600;
                border: none;
                background: transparent;
                color: #9a9ab0;
            }
            QPushButton:hover {
                background-color: #383852;
                color: #e3e4e0;
            }
        """)
        self.max_btn.clicked.connect(self._toggle_maximize)
        layout.addWidget(self.max_btn)

        self.close_btn = QPushButton()
        self.close_btn.setText("X")
        self.close_btn.setObjectName("closeBtn")
        self.close_btn.setFixedSize(46, 40)
        self.close_btn.setStyleSheet("""
            QPushButton {
                font-size: 13px;
                font-weight: 700;
                border: none;
                background: transparent;
                color: #9a9ab0;
            }
            QPushButton:hover {
                background-color: #ef5350;
                color: white;
            }
        """)
        self.close_btn.clicked.connect(self._close)
        layout.addWidget(self.close_btn)

    def _minimize(self):
        """Minimize the window."""
        if self.parent_window:
            self.parent_window.showMinimized()

    def _toggle_maximize(self):
        """Toggle maximize/restore."""
        if self.parent_window:
            if self._is_maximized:
                self.parent_window.showNormal()
                self.max_btn.setText("[ ]")
            else:
                self.parent_window.showMaximized()
                self.max_btn.setText("[=]")
            self._is_maximized = not self._is_maximized

    def _close(self):
        """Close the window."""
        if self.parent_window:
            self.parent_window.close()

    def mousePressEvent(self, event: QMouseEvent):
        """Handle mouse press for dragging."""
        if event.button() == Qt.LeftButton:
            self._drag_pos = event.globalPosition().toPoint() - self.parent_window.frameGeometry().topLeft()
            event.accept()

    def mouseMoveEvent(self, event: QMouseEvent):
        """Handle mouse move for dragging."""
        if event.buttons() == Qt.LeftButton and self._drag_pos:
            # If maximized, restore before dragging
            if self._is_maximized:
                self._toggle_maximize()
                # Adjust drag position for restored window
                self._drag_pos = QPoint(self.parent_window.width() // 2, 18)
            self.parent_window.move(event.globalPosition().toPoint() - self._drag_pos)
            event.accept()

    def mouseDoubleClickEvent(self, event: QMouseEvent):
        """Handle double click for maximize toggle."""
        if event.button() == Qt.LeftButton:
            self._toggle_maximize()


class MainWindow(QMainWindow):
    """Main application window with custom title bar and sidebar navigation."""

    def __init__(self, config: dict):
        super().__init__()
        self.config = config
        self.download_queue = DownloadQueue()

        # Frameless window with custom styling
        self.setWindowFlags(Qt.FramelessWindowHint)
        self.setAttribute(Qt.WA_TranslucentBackground, False)

        self.setWindowTitle("HARMONI")
        self.setMinimumSize(600, 400)
        self.resize(1200, 700)

        self._setup_ui()
        self._connect_signals()
        self._check_for_app_update()

    def _setup_ui(self):
        """Set up the main UI layout."""
        # Central widget
        central_widget = QWidget()
        self.setCentralWidget(central_widget)

        # Main vertical layout (title bar + content)
        main_v_layout = QVBoxLayout(central_widget)
        main_v_layout.setContentsMargins(0, 0, 0, 0)
        main_v_layout.setSpacing(0)

        # Custom title bar
        self.title_bar = TitleBar(self)
        main_v_layout.addWidget(self.title_bar)

        # Update banner (hidden until a newer release is found)
        self.update_banner = self._create_update_banner()
        main_v_layout.addWidget(self.update_banner)

        # Content container
        content_widget = QWidget()
        content_layout = QHBoxLayout(content_widget)
        content_layout.setContentsMargins(0, 0, 0, 0)
        content_layout.setSpacing(0)

        # Sidebar
        self.sidebar = self._create_sidebar()
        content_layout.addWidget(self._create_sidebar_panel(self.sidebar))

        # Content area with stacked widget
        self.view_stack = QStackedWidget()
        self._create_views()
        content_layout.addWidget(self.view_stack, 1)

        main_v_layout.addWidget(content_widget, 1)

        # Status bar
        self._create_status_bar()

    def _create_update_banner(self) -> QFrame:
        """Create the (initially hidden) 'new version available' banner."""
        banner = QFrame()
        banner.setObjectName("updateBanner")
        banner.setStyleSheet("""
            #updateBanner {
                background-color: #2f7d4f;
            }
            #updateBanner QLabel {
                color: white;
                font-size: 12px;
            }
        """)
        banner.setVisible(False)

        layout = QHBoxLayout(banner)
        layout.setContentsMargins(16, 8, 12, 8)
        layout.setSpacing(12)

        self.update_banner_label = QLabel("A new version of HARMONI is available.")
        layout.addWidget(self.update_banner_label)
        layout.addStretch()

        self.app_download_btn = QPushButton("Download")
        self.app_download_btn.setObjectName("ghost")
        self.app_download_btn.setStyleSheet("color: white; border-color: white;")
        self.app_download_btn.clicked.connect(self._open_update_release_page)
        self.app_download_btn.setVisible(False)
        layout.addWidget(self.app_download_btn)

        self.ytdlp_install_btn = QPushButton("Install yt-dlp update")
        self.ytdlp_install_btn.setObjectName("ghost")
        self.ytdlp_install_btn.setStyleSheet("color: white; border-color: white;")
        self.ytdlp_install_btn.clicked.connect(self._install_ytdlp_update)
        self.ytdlp_install_btn.setVisible(False)
        layout.addWidget(self.ytdlp_install_btn)

        dismiss_btn = QPushButton("Dismiss")
        dismiss_btn.setObjectName("ghost")
        dismiss_btn.setStyleSheet("color: white; border-color: white;")
        dismiss_btn.clicked.connect(lambda: banner.setVisible(False))
        layout.addWidget(dismiss_btn)

        self._update_release_url = None
        self._app_update_text = ""
        self._ytdlp_update_text = ""
        return banner

    def _check_for_app_update(self):
        """Kick off a background check for a newer HARMONI release."""
        self.app_update_worker = AppUpdateCheckWorker(self)
        self.app_update_worker.update_available.connect(self._on_app_update_available)
        self.app_update_worker.start()

    def start_ytdlp_update_check(self):
        """Start a background check for a newer yt-dlp, shown in the update banner."""
        self.ytdlp_update_worker = YtdlpUpdateCheckWorker(self.config.get("ytdlp_path"), self)
        self.ytdlp_update_worker.update_available.connect(self._on_ytdlp_update_available)
        self.ytdlp_update_worker.start()

    def _on_app_update_available(self, info: dict):
        """Show the update banner when a newer release is found."""
        self._update_release_url = info.get("release_url")
        self._app_update_text = (
            f"HARMONI {info.get('latest_version')} is available "
            f"(you're on {info.get('current_version')})."
        )
        self.app_download_btn.setVisible(True)
        self._refresh_update_banner()

    def _on_ytdlp_update_available(self, info: dict):
        """Show the update banner with an install choice when a newer yt-dlp is found.

        @param info: Result dict from check_ytdlp_updates with current_version and latest_version.
        """
        self._ytdlp_update_text = (
            f"yt-dlp {info.get('latest_version')} is available "
            f"(you're on {info.get('current_version')})."
        )
        self.ytdlp_install_btn.setVisible(True)
        self._refresh_update_banner()

    def _refresh_update_banner(self):
        """Show the banner with every pending update message."""
        text = " ".join(t for t in (self._app_update_text, self._ytdlp_update_text) if t)
        self.update_banner_label.setText(text)
        self.update_banner.setVisible(bool(text))

    def _install_ytdlp_update(self):
        """Open Settings and offer to install the yt-dlp update."""
        self._navigate_to_view("settings")
        self.settings_view._check_ytdlp_updates()

    def _open_update_release_page(self):
        """Open the GitHub release page for the available update."""
        if self._update_release_url:
            import webbrowser
            webbrowser.open(self._update_release_url)

    def _create_sidebar(self) -> QListWidget:
        """Create the sidebar navigation."""
        sidebar = QListWidget()
        sidebar.setObjectName("sidebar")
        sidebar.setFixedWidth(180)
        sidebar.setIconSize(QSize(20, 20))

        # Navigation items - clean text labels without emojis
        nav_items = [
            "Home",
            "Spotify",
            "YouTube",
            "Downloads",
            "Settings",
        ]

        for label in nav_items:
            item = QListWidgetItem(label)
            item.setSizeHint(QSize(160, 48))
            sidebar.addItem(item)

        # Select first item by default
        sidebar.setCurrentRow(0)

        return sidebar

    def _create_sidebar_panel(self, sidebar: QListWidget) -> QWidget:
        """Put the navigation list above quick actions for the download queue.

        @param sidebar: The navigation list.
        """
        panel = QWidget()
        panel.setObjectName("sidebarPanel")
        panel.setFixedWidth(180)
        layout = QVBoxLayout(panel)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(0)
        layout.addWidget(sidebar, 1)

        actions = QVBoxLayout()
        actions.setContentsMargins(12, 8, 12, 16)
        actions.setSpacing(8)
        layout.addLayout(actions)

        actions_label = QLabel("QUICK ACTIONS")
        actions_label.setObjectName("sectionSmall")
        actions.addWidget(actions_label)

        self.quick_start_btn = QPushButton("Start Downloads")
        self.quick_start_btn.clicked.connect(self._quick_start_downloads)
        self.quick_retry_btn = QPushButton("Retry Failed")
        self.quick_retry_btn.setObjectName("secondary")
        self.quick_retry_btn.clicked.connect(self._quick_retry_failed)
        open_folder_btn = QPushButton("Open Music Folder")
        open_folder_btn.setObjectName("secondary")
        open_folder_btn.clicked.connect(self._open_music_folder)
        for btn in (self.quick_start_btn, self.quick_retry_btn, open_folder_btn):
            btn.setCursor(Qt.PointingHandCursor)
            actions.addWidget(btn)
        return panel

    def _refresh_quick_actions(self, *_):
        """Show queue counts on the quick action buttons and disable the ones with nothing to do."""
        pending = self.download_queue.pending_count
        failed = self.download_queue.failed_count
        running = self.downloads_view.worker is not None
        self.quick_start_btn.setText(f"Start Downloads ({pending})" if pending else "Start Downloads")
        self.quick_start_btn.setEnabled(bool(pending) and not running)
        self.quick_retry_btn.setText(f"Retry Failed ({failed})" if failed else "Retry Failed")
        self.quick_retry_btn.setEnabled(bool(failed))

    def _quick_start_downloads(self):
        """Open Downloads and start the queue."""
        self._navigate_to_view("downloads")
        self.downloads_view._start_downloads()
        self._refresh_quick_actions()

    def _quick_retry_failed(self):
        """Move failed downloads back to the queue and open Downloads."""
        self.downloads_view._retry_failed()
        self._navigate_to_view("downloads")
        self._refresh_quick_actions()

    def _open_music_folder(self):
        """Open the download folder in the system file manager, creating it if needed."""
        folder = self.config.get("output_dir") or "music"
        os.makedirs(folder, exist_ok=True)
        QDesktopServices.openUrl(QUrl.fromLocalFile(os.path.abspath(folder)))

    def _create_views(self):
        """Create and add all views to the stack."""
        # Create views
        self.welcome_view = WelcomeView(self.config, self.download_queue)
        self.spotify_view = SpotifyView(self.config, self.download_queue)
        self.youtube_view = YouTubeView(self.config, self.download_queue)
        self.downloads_view = DownloadsView(self.config, self.download_queue)
        self.settings_view = SettingsView(self.config)

        # Add views to stack (order matches sidebar)
        self.view_stack.addWidget(self.welcome_view)
        self.view_stack.addWidget(self.spotify_view)
        self.view_stack.addWidget(self.youtube_view)
        self.view_stack.addWidget(self.downloads_view)
        self.view_stack.addWidget(self.settings_view)

    def _create_status_bar(self):
        """Create the status bar."""
        status_bar = QStatusBar()
        self.setStatusBar(status_bar)

        # Status label
        self.status_label = QLabel("Ready")
        status_bar.addWidget(self.status_label)

        # Spacer
        spacer = QWidget()
        spacer.setFixedWidth(20)
        status_bar.addWidget(spacer)

        import_btn = QPushButton("Import CSV")
        import_btn.setObjectName("ghost")
        import_btn.setStyleSheet("font-size: 11px; padding: 2px 8px; min-width: 0;")
        import_btn.clicked.connect(self._quick_import_csv)
        status_bar.addPermanentWidget(import_btn)

        exportify_btn = QPushButton("Exportify")
        exportify_btn.setObjectName("ghost")
        exportify_btn.setStyleSheet("font-size: 11px; padding: 2px 8px; min-width: 0;")
        exportify_btn.clicked.connect(self._open_exportify)
        status_bar.addPermanentWidget(exportify_btn)

        # Download count
        self.download_count_label = QLabel("Queue: 0")
        status_bar.addPermanentWidget(self.download_count_label)

        # Spotify status
        self.spotify_status_label = QLabel("Spotify: Not connected")
        status_bar.addPermanentWidget(self.spotify_status_label)

    def _connect_signals(self):
        """Connect signals and slots."""
        # Sidebar navigation
        self.sidebar.currentRowChanged.connect(self._on_nav_changed)

        # Download queue updates
        self.download_queue.queue_updated.connect(self._update_download_count)
        self.download_queue.queue_updated.connect(self._refresh_quick_actions)
        self.download_queue.item_updated.connect(self._refresh_quick_actions)
        self.downloads_view.running_changed.connect(self._refresh_quick_actions)
        self._refresh_quick_actions()

        # Settings changes
        self.settings_view.config_saved.connect(self._on_config_saved)

        # Spotify connection status
        self.spotify_view.connection_changed.connect(self._update_spotify_status)
        self._update_spotify_status(self.spotify_view.is_connected)
        self.spotify_view.navigate_to.connect(self._navigate_to_view)
        self.youtube_view.navigate_to.connect(self._navigate_to_view)

        # Welcome view navigation
        self.welcome_view.navigate_to.connect(self._navigate_to_view)

    def _on_nav_changed(self, index: int):
        """Handle sidebar navigation change."""
        self.view_stack.setCurrentIndex(index)

    def _navigate_to_view(self, view_name: str):
        """Navigate to a specific view by name."""
        view_map = {
            "welcome": 0,
            "spotify": 1,
            "youtube": 2,
            "downloads": 3,
            "settings": 4,
        }
        if view_name == "spotify_settings":
            self.sidebar.setCurrentRow(view_map["settings"])
            self.settings_view.focus_spotify_client_id()
        elif view_name in view_map:
            self.sidebar.setCurrentRow(view_map[view_name])

    def _update_download_count(self, count: int):
        """Update the download count in status bar."""
        self.download_count_label.setText(f"Queue: {count}")

    def _update_spotify_status(self, connected: bool):
        """Update Spotify connection status."""
        if connected:
            self.spotify_status_label.setText("Spotify: Connected")
            self.spotify_status_label.setStyleSheet("color: #4caf50;")
        else:
            self.spotify_status_label.setText("Spotify: Not connected")
            self.spotify_status_label.setStyleSheet("")

    def _on_config_saved(self):
        """Handle config save from settings."""
        # Reload config from file
        from config import load_config
        try:
            self.config = load_config()
            # Update all views with the new config
            self.spotify_view.config = self.config
            self.youtube_view.config = self.config
            self.downloads_view.config = self.config
            self.welcome_view.config = self.config
            self.settings_view.config = self.config
            self.status_label.setText("Settings saved successfully")
        except Exception as e:
            self.status_label.setText(f"Error reloading config: {e}")

    def _quick_import_csv(self):
        from PySide6.QtWidgets import QFileDialog
        files, _ = QFileDialog.getOpenFileNames(self, "Import Exportify CSV", "", "CSV Files (*.csv)")
        if files:
            self.welcome_view._handle_dropped_files(files)

    def _open_exportify(self):
        import webbrowser
        webbrowser.open("https://exportify.net")

    def set_status(self, message: str):
        """Set status bar message."""
        self.status_label.setText(message)

    def get_download_queue(self) -> DownloadQueue:
        """Get the download queue instance."""
        return self.download_queue
