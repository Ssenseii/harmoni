"""Main window with custom title bar and sidebar navigation for HARMONI GUI."""

from PySide6.QtWidgets import (
    QMainWindow, QWidget, QHBoxLayout, QVBoxLayout,
    QListWidget, QListWidgetItem, QStackedWidget,
    QStatusBar, QLabel, QFrame, QPushButton
)
import os

from PySide6.QtCore import QEvent, Qt, QSize, QPointF, QRectF, QTimer, QUrl
from PySide6.QtGui import QColor, QDesktopServices, QIcon, QMouseEvent, QPainter, QPen

from gui import notices
from gui.styles import COLORS
from gui.views.welcome_view import WelcomeView
from gui.views.spotify_view import SpotifyView
from gui.views.youtube_view import YouTubeView
from gui.views.downloads_view import DownloadsView
from gui.views.settings_view import SettingsView
from gui.workers.download_queue import DownloadQueue
from gui.workers.app_update_worker import AppUpdateCheckWorker
from gui.workers.ytdlp_update_worker import YtdlpUpdateCheckWorker
from version import __version__


class WindowButton(QPushButton):
    """(this is a... way to do it)"""

    def __init__(self, kind: str, parent=None):
        super().__init__(parent)
        self.kind = kind
        self.setFixedSize(46, 40)
        self.setCursor(Qt.ArrowCursor)
        self.setFocusPolicy(Qt.NoFocus)
        self.setAttribute(Qt.WA_Hover, True)

    def set_kind(self, kind: str):
        """Switch the glyph (maximize <-> restore)."""
        self.kind = kind
        self.update()

    def paintEvent(self, event):
        painter = QPainter(self)
        painter.setRenderHint(QPainter.Antialiasing, True)
        hovered = self.underMouse()
        pressed = self.isDown()
        close = self.kind == "close"
        if hovered:
            if close:
                bg = QColor(COLORS["error_pressed"] if pressed else COLORS["error"])
            else:
                bg = QColor(COLORS["border_light"] if pressed else COLORS["background_light"])
            painter.fillRect(self.rect(), bg)
        if close and hovered:
            color = QColor("white")
        else:
            color = QColor(COLORS["text"] if hovered else COLORS["text_secondary"])
        pen = QPen(color, 1.2)
        pen.setCapStyle(Qt.SquareCap)
        painter.setPen(pen)
        cx, cy = self.width() / 2, self.height() / 2
        if self.kind == "min":
            painter.drawLine(QPointF(cx - 5, cy + 0.5), QPointF(cx + 5, cy + 0.5))
        elif self.kind == "max":
            painter.drawRect(QRectF(cx - 5, cy - 5, 10, 10))
        elif self.kind == "restore":
            painter.drawRect(QRectF(cx - 5, cy - 2, 7, 7))
            painter.drawPolyline([QPointF(cx - 2, cy - 2), QPointF(cx - 2, cy - 5),
                                  QPointF(cx + 5, cy - 5), QPointF(cx + 5, cy + 2),
                                  QPointF(cx + 2, cy + 2)])
        else:
            painter.drawLine(QPointF(cx - 5, cy - 5), QPointF(cx + 5, cy + 5))
            painter.drawLine(QPointF(cx - 5, cy + 5), QPointF(cx + 5, cy - 5))


class StatusChip(QWidget):
    """status indicator"""

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setAttribute(Qt.WA_TranslucentBackground, True)
        layout = QHBoxLayout(self)
        layout.setContentsMargins(6, 0, 6, 0)
        layout.setSpacing(7)
        self.dot = QLabel()
        self.dot.setFixedSize(8, 8)
        self.label = QLabel()
        layout.addWidget(self.dot)
        layout.addWidget(self.label)

    def set_state(self, text: str, color: str, text_color: str = None, pulse: bool = False):
        """Update the text and dot color.

        @param text: Label text.
        @param color: Dot color.
        @param text_color: Label color (defaults to the secondary text color).
        @param pulse: Draw a soft ring around the dot to show activity.
        """
        self.label.setText(text)
        self.label.setStyleSheet(
            f"background: transparent; font-size: 12px; font-weight: 500; "
            f"color: {text_color or COLORS['text_secondary']};")
        ring = f"border: 2px solid {color}; background: transparent;" if pulse else f"background: {color};"
        self.dot.setStyleSheet(f"{ring} border-radius: 4px;")


class TitleBar(QWidget):
    """Custom title bar for the frameless window: brand, current page and window controls."""

    def __init__(self, parent=None):
        super().__init__(parent)
        self.parent_window = parent
        self.setObjectName("titleBar")
        self.setFixedHeight(40)
        self._setup_ui()

    def _setup_ui(self):
        """Set up the title bar UI."""
        from gui.resources.icons import get_app_icon

        layout = QHBoxLayout(self)
        layout.setContentsMargins(14, 0, 0, 0)
        layout.setSpacing(8)

        app_icon = get_app_icon()
        if not app_icon.isNull():
            icon_label = QLabel()
            icon_label.setPixmap(app_icon.pixmap(20, 20))
            icon_label.setFixedSize(22, 22)
            icon_label.setStyleSheet("background: transparent;")
            layout.addWidget(icon_label)

        self.title_label = QLabel("HARMONI")
        self.title_label.setStyleSheet(
            f"background: transparent; font-size: 14px; font-weight: 700; "
            f"color: {COLORS['text']}; letter-spacing: 2px;")
        layout.addWidget(self.title_label)

        version_label = QLabel(f"v{__version__}")
        version_label.setStyleSheet(
            f"background: transparent; font-size: 11px; font-weight: 500; color: {COLORS['text_muted']};")
        layout.addWidget(version_label)

        divider = QFrame()
        divider.setFixedSize(1, 16)
        divider.setStyleSheet(f"background-color: {COLORS['border_light']};")
        layout.addSpacing(6)
        layout.addWidget(divider)
        layout.addSpacing(6)

        self.page_label = QLabel("Home")
        self.page_label.setStyleSheet(
            f"background: transparent; font-size: 13px; font-weight: 500; color: {COLORS['text_secondary']};")
        layout.addWidget(self.page_label)

        layout.addStretch()

        self.queue_chip = StatusChip()
        self.spotify_chip = StatusChip()
        self.set_queue_state(0, 0)
        self.set_spotify_connected(False)
        layout.addWidget(self.queue_chip)
        layout.addWidget(self.spotify_chip)
        layout.addSpacing(10)

        self.min_btn = WindowButton("min")
        self.min_btn.setToolTip("Minimize")
        self.min_btn.clicked.connect(self._minimize)
        self.max_btn = WindowButton("max")
        self.max_btn.setToolTip("Maximize")
        self.max_btn.clicked.connect(self._toggle_maximize)
        self.close_btn = WindowButton("close")
        self.close_btn.setToolTip("Close")
        self.close_btn.clicked.connect(self._close)
        for btn in (self.min_btn, self.max_btn, self.close_btn):
            layout.addWidget(btn)

    def set_queue_state(self, pending: int, downloading: int):
        """Show queue activity: items downloading now and items still waiting.

        @param pending: Items waiting to download.
        @param downloading: Items downloading right now.
        """
        if downloading:
            text = f"Downloading {downloading}" + (f" · {pending} queued" if pending else "")
            self.queue_chip.set_state(text, COLORS["accent_hover"], COLORS["text"], pulse=True)
        elif pending:
            self.queue_chip.set_state(f"Queue: {pending}", COLORS["accent_hover"], COLORS["text"])
        else:
            self.queue_chip.set_state("Queue: 0", COLORS["text_muted"])

    def set_spotify_connected(self, connected: bool):
        """Show the Spotify connection state."""
        if connected:
            self.spotify_chip.set_state("Spotify: Connected", COLORS["success"], COLORS["text"])
        else:
            self.spotify_chip.set_state("Spotify: Not connected", COLORS["text_muted"])

    def set_page(self, name: str):
        """Show the name of the current page."""
        self.page_label.setText(name)

    def sync_window_state(self):
        """Match the maximize button to the real window state."""
        maximized = bool(self.parent_window and self.parent_window.isMaximized())
        self.max_btn.set_kind("restore" if maximized else "max")
        self.max_btn.setToolTip("Restore" if maximized else "Maximize")

    def _minimize(self):
        if self.parent_window:
            self.parent_window.showMinimized()

    def _toggle_maximize(self):
        if self.parent_window:
            if self.parent_window.isMaximized():
                self.parent_window.showNormal()
            else:
                self.parent_window.showMaximized()
            self.sync_window_state()

    def _close(self):
        if self.parent_window:
            self.parent_window.close()

    def mousePressEvent(self, event: QMouseEvent):
        """Start a native window move (keeps Windows snap and multi-monitor behavior)."""
        if event.button() == Qt.LeftButton and self.parent_window:
            if self.parent_window.isMaximized():
                self._toggle_maximize()
            handle = self.parent_window.windowHandle()
            if handle:
                handle.startSystemMove()
            event.accept()

    def mouseDoubleClickEvent(self, event: QMouseEvent):
        if event.button() == Qt.LeftButton:
            self._toggle_maximize()


class MainWindow(QMainWindow):
    """Main application window with custom title bar and sidebar navigation."""

    RESIZE_MARGIN = 5

    NAV_ITEMS = ["Home", "Spotify", "YouTube", "Downloads", "Settings"]

    def __init__(self, config: dict):
        super().__init__()
        self.config = config
        self.download_queue = DownloadQueue()

        # Frameless window with custom styling
        self.setWindowFlags(Qt.FramelessWindowHint)
        self.setAttribute(Qt.WA_TranslucentBackground, False)

        self.setMouseTracking(True)
        self.setContentsMargins(self.RESIZE_MARGIN, self.RESIZE_MARGIN, self.RESIZE_MARGIN, self.RESIZE_MARGIN)

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
        self.notice_bar = self._create_notice_bar()
        main_v_layout.addWidget(self.notice_bar)

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

    def _create_notice_bar(self) -> QFrame:
        """Create the bar that shows non-blocking notices from the views, laid out like the update banner."""
        bar = QFrame()
        bar.setObjectName("noticeBar")
        bar.setVisible(False)
        layout = QHBoxLayout(bar)
        layout.setContentsMargins(16, 8, 12, 8)
        layout.setSpacing(12)

        self.notice_label = QLabel()
        self.notice_label.setWordWrap(True)
        layout.addWidget(self.notice_label, 1)

        self.notice_action_btn = QPushButton()
        self.notice_action_btn.setObjectName("ghost")
        self.notice_action_btn.setStyleSheet("color: white; border-color: white;")
        self.notice_action_btn.clicked.connect(self._run_notice_action)
        layout.addWidget(self.notice_action_btn)

        dismiss_btn = QPushButton("Dismiss")
        dismiss_btn.setObjectName("ghost")
        dismiss_btn.setStyleSheet("color: white; border-color: white;")
        dismiss_btn.clicked.connect(lambda: bar.setVisible(False))
        layout.addWidget(dismiss_btn)

        self._notice_action = None
        self._notice_timer = QTimer(self)
        self._notice_timer.setSingleShot(True)
        self._notice_timer.timeout.connect(lambda: bar.setVisible(False))
        notices.hub.posted.connect(self._show_notice)
        return bar

    def _show_notice(self, text: str, kind: str, action_label: str, action):
        """Show a notice, replacing any current one, and hide it after a few seconds.

        @param text: Message to show.
        @param kind: "info", "success" or "warning".
        @param action_label: Button text, or "" for no button.
        @param action: Callable run by the button.
        """
        colors = {"success": "#2f7d4f", "warning": COLORS["warning"], "info": COLORS["accent_pressed"]}
        self.notice_bar.setStyleSheet(
            f"#noticeBar {{ background-color: {colors.get(kind, colors['info'])}; }}"
            "#noticeBar QLabel { color: white; font-size: 12px; }"
        )
        self.notice_label.setText(text)
        self._notice_action = action
        self.notice_action_btn.setText(action_label)
        self.notice_action_btn.setVisible(bool(action_label and action))
        self.notice_bar.setVisible(True)
        self._notice_timer.start(10000 if kind == "warning" else 6000)

    def _run_notice_action(self):
        """Run the current notice's action and close the bar."""
        self.notice_bar.setVisible(False)
        if self._notice_action:
            self._notice_action()

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
        for label in self.NAV_ITEMS:
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

        # Queue and Spotify status live in the title bar chips

    def _connect_signals(self):
        """Connect signals and slots."""
        # Sidebar navigation
        self.sidebar.currentRowChanged.connect(self._on_nav_changed)

        # Download queue updates
        self.download_queue.queue_updated.connect(self._update_download_count)
        self.download_queue.item_updated.connect(self._update_download_count)
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
        if 0 <= index < len(self.NAV_ITEMS):
            self.title_bar.set_page(self.NAV_ITEMS[index])

    def changeEvent(self, event):
        """Keep the title bar's maximize button in sync with the window state."""
        super().changeEvent(event)
        if event.type() == QEvent.WindowStateChange and hasattr(self, "title_bar"):
            self.title_bar.sync_window_state()
            # No resize border while maximized or fullscreen
            m = 0 if self.isMaximized() or self.isFullScreen() else self.RESIZE_MARGIN
            self.setContentsMargins(m, m, m, m)

    def _edges_at(self, pos) -> Qt.Edges:
        """Window edges under a point in window coordinates (empty when not on the resize border)."""
        if self.isMaximized() or self.isFullScreen():
            return Qt.Edges()
        m = self.RESIZE_MARGIN
        edges = Qt.Edges()
        if pos.x() < m:
            edges |= Qt.LeftEdge
        elif pos.x() >= self.width() - m:
            edges |= Qt.RightEdge
        if pos.y() < m:
            edges |= Qt.TopEdge
        elif pos.y() >= self.height() - m:
            edges |= Qt.BottomEdge
        return edges

    def mouseMoveEvent(self, event: QMouseEvent):
        """Show a resize cursor over the window border."""
        edges = self._edges_at(event.position().toPoint())
        left, right = bool(edges & Qt.LeftEdge), bool(edges & Qt.RightEdge)
        top, bottom = bool(edges & Qt.TopEdge), bool(edges & Qt.BottomEdge)
        if (left and top) or (right and bottom):
            self.setCursor(Qt.SizeFDiagCursor)
        elif (right and top) or (left and bottom):
            self.setCursor(Qt.SizeBDiagCursor)
        elif left or right:
            self.setCursor(Qt.SizeHorCursor)
        elif top or bottom:
            self.setCursor(Qt.SizeVerCursor)
        else:
            self.unsetCursor()
        super().mouseMoveEvent(event)

    def mousePressEvent(self, event: QMouseEvent):
        """Start a native resize when the border is pressed."""
        edges = self._edges_at(event.position().toPoint())
        if event.button() == Qt.LeftButton and edges and self.windowHandle():
            self.windowHandle().startSystemResize(edges)
            event.accept()
            return
        super().mousePressEvent(event)

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

    def _update_download_count(self, *_):
        """Refresh the queue chip from the queue (pending and currently downloading)."""
        self.title_bar.set_queue_state(self.download_queue.pending_count, self.download_queue.downloading_count)

    def _update_spotify_status(self, connected: bool):
        """Update Spotify connection status."""
        self.title_bar.set_spotify_connected(connected)

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
