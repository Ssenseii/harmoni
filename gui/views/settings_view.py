"""Settings view for configuration management."""

import os
from PySide6.QtWidgets import (
    QWidget, QVBoxLayout, QHBoxLayout, QLabel,
    QPushButton, QLineEdit, QComboBox, QCheckBox,
    QGroupBox, QFormLayout, QFileDialog, QMessageBox,
    QSpacerItem, QSizePolicy, QScrollArea, QFrame,
    QProgressBar, QSpinBox
)
from PySide6.QtCore import Signal

from config import save_config, validate_config, DEFAULT_CONFIG, load_config
from gui.styles import COLORS
from utils.ffmpeg import check_ffmpeg_available
from tools.ytdlp_update_checker import check_ytdlp_updates


class SettingsView(QWidget):
    """Settings configuration view."""

    config_saved = Signal()  # Emits when config is saved

    def __init__(self, config: dict, parent=None):
        super().__init__(parent)
        self.config = config
        self.ffmpeg_worker = None
        self.ytdlp_worker = None
        self._setup_ui()
        self._load_values()
        self._check_ffmpeg_status()
        self._check_ytdlp_status()

    def _setup_ui(self):
        """Set up the settings UI."""
        # Main layout with scroll area
        main_layout = QVBoxLayout(self)
        main_layout.setContentsMargins(0, 0, 0, 0)

        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        scroll.setFrameShape(QFrame.NoFrame)

        scroll_widget = QWidget()
        layout = QVBoxLayout(scroll_widget)
        layout.setContentsMargins(30, 20, 30, 20)
        layout.setSpacing(16)

        # Title
        title = QLabel("Settings")
        title.setObjectName("title")
        layout.addWidget(title)

        # Dependencies Group
        deps_group = QGroupBox("Dependencies")
        deps_layout = QVBoxLayout(deps_group)
        deps_layout.setSpacing(14)

        # --- FFmpeg section ---
        ffmpeg_header = QLabel("FFmpeg")
        ffmpeg_header.setObjectName("section")
        deps_layout.addWidget(ffmpeg_header)

        ffmpeg_desc = QLabel("Required for audio conversion.")
        ffmpeg_desc.setObjectName("muted")
        deps_layout.addWidget(ffmpeg_desc)

        status_row = QHBoxLayout()
        self.ffmpeg_status_icon = QLabel("●")
        self.ffmpeg_status_icon.setFixedWidth(20)
        status_row.addWidget(self.ffmpeg_status_icon)
        self.ffmpeg_status_label = QLabel("Checking...")
        status_row.addWidget(self.ffmpeg_status_label, 1)
        self.ffmpeg_install_btn = QPushButton("Install FFmpeg")
        self.ffmpeg_install_btn.setObjectName("secondary")
        self.ffmpeg_install_btn.clicked.connect(self._install_ffmpeg)
        status_row.addWidget(self.ffmpeg_install_btn)
        self.ffmpeg_refresh_btn = QPushButton("Refresh")
        self.ffmpeg_refresh_btn.setObjectName("secondary")
        self.ffmpeg_refresh_btn.setFixedWidth(70)
        self.ffmpeg_refresh_btn.clicked.connect(self._check_ffmpeg_status)
        status_row.addWidget(self.ffmpeg_refresh_btn)
        deps_layout.addLayout(status_row)

        self.ffmpeg_progress = QProgressBar()
        self.ffmpeg_progress.setVisible(False)
        deps_layout.addWidget(self.ffmpeg_progress)
        self.ffmpeg_progress_label = QLabel("")
        self.ffmpeg_progress_label.setObjectName("subtitle")
        self.ffmpeg_progress_label.setVisible(False)
        deps_layout.addWidget(self.ffmpeg_progress_label)

        # FFmpeg custom path
        ffmpeg_path_label = QLabel("Custom path")
        ffmpeg_path_label.setObjectName("muted")
        deps_layout.addWidget(ffmpeg_path_label)
        ffmpeg_path_row = QHBoxLayout()
        self.ffmpeg_path_input = QLineEdit()
        self.ffmpeg_path_input.setPlaceholderText("Auto-detect (leave empty)")
        ffmpeg_path_row.addWidget(self.ffmpeg_path_input, 1)
        ffmpeg_browse_btn = QPushButton("Browse")
        ffmpeg_browse_btn.setObjectName("secondary")
        ffmpeg_browse_btn.setFixedWidth(70)
        ffmpeg_browse_btn.clicked.connect(self._browse_ffmpeg_path)
        ffmpeg_path_row.addWidget(ffmpeg_browse_btn)
        deps_layout.addLayout(ffmpeg_path_row)

        # --- Separator ---
        sep = QFrame()
        sep.setFrameShape(QFrame.HLine)
        sep.setStyleSheet(f"color: {COLORS['border']};")
        sep.setFixedHeight(1)
        deps_layout.addWidget(sep)

        # --- yt-dlp section ---
        ytdlp_header = QLabel("yt-dlp")
        ytdlp_header.setObjectName("section")
        deps_layout.addWidget(ytdlp_header)

        ytdlp_desc = QLabel("Required for downloading from YouTube and other sources.")
        ytdlp_desc.setObjectName("muted")
        deps_layout.addWidget(ytdlp_desc)

        ytdlp_status_row = QHBoxLayout()
        self.ytdlp_status_icon = QLabel("●")
        self.ytdlp_status_icon.setFixedWidth(20)
        ytdlp_status_row.addWidget(self.ytdlp_status_icon)
        self.ytdlp_status_label = QLabel("Checking...")
        ytdlp_status_row.addWidget(self.ytdlp_status_label, 1)
        self.ytdlp_update_btn = QPushButton("Check for Updates")
        self.ytdlp_update_btn.setObjectName("secondary")
        self.ytdlp_update_btn.clicked.connect(self._check_ytdlp_updates)
        ytdlp_status_row.addWidget(self.ytdlp_update_btn)
        self.ytdlp_refresh_btn = QPushButton("Refresh")
        self.ytdlp_refresh_btn.setObjectName("secondary")
        self.ytdlp_refresh_btn.setFixedWidth(70)
        self.ytdlp_refresh_btn.clicked.connect(self._check_ytdlp_status)
        ytdlp_status_row.addWidget(self.ytdlp_refresh_btn)
        deps_layout.addLayout(ytdlp_status_row)

        self.ytdlp_progress = QProgressBar()
        self.ytdlp_progress.setVisible(False)
        deps_layout.addWidget(self.ytdlp_progress)
        self.ytdlp_progress_label = QLabel("")
        self.ytdlp_progress_label.setObjectName("subtitle")
        self.ytdlp_progress_label.setVisible(False)
        deps_layout.addWidget(self.ytdlp_progress_label)

        # yt-dlp custom path
        ytdlp_path_label = QLabel("Custom path")
        ytdlp_path_label.setObjectName("muted")
        deps_layout.addWidget(ytdlp_path_label)
        ytdlp_path_row = QHBoxLayout()
        self.ytdlp_path_input = QLineEdit()
        self.ytdlp_path_input.setPlaceholderText("Auto-detect (leave empty)")
        ytdlp_path_row.addWidget(self.ytdlp_path_input, 1)
        ytdlp_browse_btn = QPushButton("Browse")
        ytdlp_browse_btn.setObjectName("secondary")
        ytdlp_browse_btn.setFixedWidth(70)
        ytdlp_browse_btn.clicked.connect(self._browse_ytdlp_path)
        ytdlp_path_row.addWidget(ytdlp_browse_btn)
        deps_layout.addLayout(ytdlp_path_row)

        layout.addWidget(deps_group)

        # Output Settings Group
        output_group = QGroupBox("Output Settings")
        output_layout = QVBoxLayout(output_group)
        output_layout.setSpacing(10)

        output_dir_label = QLabel("Output directory")
        output_dir_label.setObjectName("muted")
        output_layout.addWidget(output_dir_label)
        output_dir_row = QHBoxLayout()
        self.output_dir_input = QLineEdit()
        self.output_dir_input.setPlaceholderText("Select output directory...")
        output_dir_row.addWidget(self.output_dir_input, 1)
        browse_btn = QPushButton("Browse")
        browse_btn.setObjectName("secondary")
        browse_btn.setFixedWidth(70)
        browse_btn.clicked.connect(self._browse_output_dir)
        output_dir_row.addWidget(browse_btn)
        output_layout.addLayout(output_dir_row)

        format_label = QLabel("Audio format")
        format_label.setObjectName("muted")
        output_layout.addWidget(format_label)
        self.format_combo = QComboBox()
        self.format_combo.addItems(["mp3", "flac", "wav", "aac", "ogg", "m4a"])
        output_layout.addWidget(self.format_combo)

        layout.addWidget(output_group)

        # Spotify Settings Group
        spotify_group = QGroupBox("Spotify Settings")
        spotify_layout = QVBoxLayout(spotify_group)
        spotify_layout.setSpacing(10)

        client_id_label = QLabel("Client ID")
        client_id_label.setObjectName("muted")
        spotify_layout.addWidget(client_id_label)
        self.client_id_input = QLineEdit()
        self.client_id_input.setPlaceholderText("Enter your Spotify Client ID")
        spotify_layout.addWidget(self.client_id_input)

        redirect_label = QLabel("Redirect URI")
        redirect_label.setObjectName("muted")
        spotify_layout.addWidget(redirect_label)
        self.redirect_uri_input = QLineEdit()
        self.redirect_uri_input.setReadOnly(True)
        spotify_layout.addWidget(self.redirect_uri_input)

        help_label = QLabel(
            "To get a Spotify Client ID:\n"
            "1. Go to developer.spotify.com/dashboard\n"
            "2. Create a new app\n"
            "3. Add http://127.0.0.1:8888/callback to Redirect URIs\n"
            "4. Copy the Client ID here"
        )
        help_label.setObjectName("subtitle")
        help_label.setWordWrap(True)
        spotify_layout.addWidget(help_label)

        layout.addWidget(spotify_group)

        # Download Settings Group
        download_group = QGroupBox("Download Settings")
        download_layout = QVBoxLayout(download_group)
        download_layout.setSpacing(10)

        sleep_label = QLabel("Sleep between downloads (seconds)")
        sleep_label.setObjectName("muted")
        download_layout.addWidget(sleep_label)
        self.sleep_input = QLineEdit()
        self.sleep_input.setPlaceholderText("5")
        self.sleep_input.setMaximumWidth(200)
        download_layout.addWidget(self.sleep_input)

        retry_label = QLabel("Retry attempts")
        retry_label.setObjectName("muted")
        download_layout.addWidget(retry_label)
        self.retry_input = QLineEdit()
        self.retry_input.setPlaceholderText("3")
        self.retry_input.setMaximumWidth(200)
        download_layout.addWidget(self.retry_input)

        concurrent_label = QLabel("Max concurrent downloads")
        concurrent_label.setObjectName("muted")
        download_layout.addWidget(concurrent_label)
        self.concurrent_spinbox = QSpinBox()
        self.concurrent_spinbox.setMinimum(1)
        self.concurrent_spinbox.setMaximum(8)
        self.concurrent_spinbox.setValue(3)
        self.concurrent_spinbox.setMaximumWidth(200)
        download_layout.addWidget(self.concurrent_spinbox)

        layout.addWidget(download_group)

        # Metadata Settings Group
        metadata_group = QGroupBox("Metadata Settings")
        metadata_layout = QVBoxLayout(metadata_group)
        metadata_layout.setSpacing(10)

        self.metadata_check = QCheckBox("Enable metadata embedding")
        metadata_layout.addWidget(self.metadata_check)

        template_label = QLabel("Template")
        template_label.setObjectName("muted")
        metadata_layout.addWidget(template_label)
        self.template_combo = QComboBox()
        self.template_combo.addItems(["basic", "comprehensive", "dj-mix"])
        metadata_layout.addWidget(self.template_combo)

        self.musicbrainz_check = QCheckBox("Enable MusicBrainz lookup")
        metadata_layout.addWidget(self.musicbrainz_check)

        layout.addWidget(metadata_group)

        # Backup Settings Group
        backup_group = QGroupBox("Backup Settings")
        backup_layout = QVBoxLayout(backup_group)
        backup_layout.setSpacing(10)

        self.backup_check = QCheckBox("Enable automatic backups")
        backup_layout.addWidget(self.backup_check)

        max_backups_label = QLabel("Max backups")
        max_backups_label.setObjectName("muted")
        backup_layout.addWidget(max_backups_label)
        self.max_backups_input = QLineEdit()
        self.max_backups_input.setPlaceholderText("10")
        self.max_backups_input.setMaximumWidth(200)
        backup_layout.addWidget(self.max_backups_input)

        layout.addWidget(backup_group)

        # Spacer
        layout.addSpacerItem(QSpacerItem(20, 20, QSizePolicy.Minimum, QSizePolicy.Expanding))

        # Buttons
        buttons_layout = QHBoxLayout()
        buttons_layout.addStretch()

        reset_btn = QPushButton("Reset to Defaults")
        reset_btn.setObjectName("secondary")
        reset_btn.clicked.connect(self._reset_to_defaults)
        buttons_layout.addWidget(reset_btn)

        save_btn = QPushButton("Save Settings")
        save_btn.clicked.connect(self._save_settings)
        buttons_layout.addWidget(save_btn)

        layout.addLayout(buttons_layout)

        scroll.setWidget(scroll_widget)
        main_layout.addWidget(scroll)

    def _load_values(self):
        """Load current config values into the form."""
        self.output_dir_input.setText(self.config.get("output_dir", "music"))
        self.format_combo.setCurrentText(self.config.get("audio_format", "mp3"))
        self.client_id_input.setText(self.config.get("spotify_client_id", ""))
        self.redirect_uri_input.setText(self.config.get("spotify_redirect_uri", "http://127.0.0.1:8888/callback"))
        self.sleep_input.setText(str(self.config.get("sleep_between", 5)))
        self.retry_input.setText(str(self.config.get("retry_attempts", 3)))
        self.concurrent_spinbox.setValue(self.config.get("max_concurrent_downloads", 3))
        self.metadata_check.setChecked(self.config.get("enable_metadata_embedding", True))
        self.template_combo.setCurrentText(self.config.get("metadata_template", "basic"))
        self.musicbrainz_check.setChecked(self.config.get("enable_musicbrainz_lookup", True))
        self.backup_check.setChecked(self.config.get("auto_backup", True))
        self.max_backups_input.setText(str(self.config.get("max_backups", 10)))
        self.ffmpeg_path_input.setText(self.config.get("ffmpeg_path", ""))
        self.ytdlp_path_input.setText(self.config.get("ytdlp_path", ""))

    def _check_ffmpeg_status(self):
        """Check FFmpeg installation status."""
        available, message = check_ffmpeg_available()

        if available:
            self.ffmpeg_status_icon.setStyleSheet("color: #4caf50; font-size: 14px;")
            self.ffmpeg_status_label.setText(f"Installed: {message.replace('FFmpeg found at: ', '')}")
            self.ffmpeg_status_label.setStyleSheet("color: #4caf50;")
            self.ffmpeg_install_btn.setText("Reinstall")
        else:
            self.ffmpeg_status_icon.setStyleSheet("color: #ef5350; font-size: 14px;")
            self.ffmpeg_status_label.setText("Not installed")
            self.ffmpeg_status_label.setStyleSheet("color: #ef5350;")
            self.ffmpeg_install_btn.setText("Install FFmpeg")

    def _install_ffmpeg(self):
        """Start FFmpeg installation."""
        from gui.workers.ffmpeg_installer import FFmpegInstallerWorker

        # Confirm installation
        reply = QMessageBox.question(
            self,
            "Install FFmpeg",
            "This will download and install FFmpeg (~100MB).\n\n"
            "The installation is required for audio conversion.\n\n"
            "Continue?",
            QMessageBox.Yes | QMessageBox.No,
            QMessageBox.Yes
        )

        if reply != QMessageBox.Yes:
            return

        # Disable buttons during installation
        self.ffmpeg_install_btn.setEnabled(False)
        self.ffmpeg_refresh_btn.setEnabled(False)

        # Show progress
        self.ffmpeg_progress.setVisible(True)
        self.ffmpeg_progress_label.setVisible(True)
        self.ffmpeg_progress.setValue(0)

        # Create and start worker
        self.ffmpeg_worker = FFmpegInstallerWorker()
        self.ffmpeg_worker.progress.connect(self._on_ffmpeg_progress)
        self.ffmpeg_worker.finished.connect(self._on_ffmpeg_finished)
        self.ffmpeg_worker.start()

    def _on_ffmpeg_progress(self, percent: int, message: str):
        """Handle FFmpeg installation progress."""
        self.ffmpeg_progress.setValue(percent)
        self.ffmpeg_progress_label.setText(message)

    def _on_ffmpeg_finished(self, success: bool, message: str):
        """Handle FFmpeg installation completion."""
        # Hide progress
        self.ffmpeg_progress.setVisible(False)
        self.ffmpeg_progress_label.setVisible(False)

        # Re-enable buttons
        self.ffmpeg_install_btn.setEnabled(True)
        self.ffmpeg_refresh_btn.setEnabled(True)

        # Show result
        if success:
            QMessageBox.information(self, "Installation Complete", message)
            self._check_ffmpeg_status()
        else:
            QMessageBox.warning(self, "Installation Failed", message)
            self._check_ffmpeg_status()

        # Clean up worker
        self.ffmpeg_worker = None

    def _check_ytdlp_status(self):
        """Check yt-dlp installation and version status."""
        import shutil
        import subprocess

        version = None
        found_path = None

        # Check custom path from config first
        custom_path = self.config.get("ytdlp_path", "")
        if custom_path and os.path.isfile(custom_path):
            found_path = custom_path
            try:
                result = subprocess.run(
                    [custom_path, "--version"],
                    capture_output=True, text=True, timeout=3
                )
                if result.returncode == 0:
                    version = result.stdout.strip()
            except Exception:
                pass
        else:
            # Check PATH
            ytdlp_bin = shutil.which("yt-dlp")
            if ytdlp_bin:
                found_path = ytdlp_bin
                try:
                    result = subprocess.run(
                        [ytdlp_bin, "--version"],
                        capture_output=True, text=True, timeout=3
                    )
                    if result.returncode == 0:
                        version = result.stdout.strip()
                except Exception:
                    pass

        if found_path and version:
            self.ytdlp_status_icon.setStyleSheet("color: #4caf50; font-size: 14px;")
            self.ytdlp_status_label.setText(f"Installed: {version} ({found_path})")
            self.ytdlp_status_label.setStyleSheet("color: #4caf50;")
            self.ytdlp_update_btn.setText("Check for Updates")
            self.ytdlp_update_btn.setEnabled(True)
        elif found_path:
            self.ytdlp_status_icon.setStyleSheet("color: #4caf50; font-size: 14px;")
            self.ytdlp_status_label.setText(f"Installed: {found_path}")
            self.ytdlp_status_label.setStyleSheet("color: #4caf50;")
            self.ytdlp_update_btn.setText("Check for Updates")
            self.ytdlp_update_btn.setEnabled(True)
        else:
            self.ytdlp_status_icon.setStyleSheet("color: #ef5350; font-size: 14px;")
            self.ytdlp_status_label.setText("Not installed")
            self.ytdlp_status_label.setStyleSheet("color: #ef5350;")
            self.ytdlp_update_btn.setText("Install yt-dlp")
            self.ytdlp_update_btn.setEnabled(True)

    def _check_ytdlp_updates(self):
        """Start yt-dlp update check and installation."""
        import shutil

        # Fast local check only — no network call
        ytdlp_bin = self.config.get("ytdlp_path", "") or shutil.which("yt-dlp")
        use_standalone = not (ytdlp_bin and os.path.isfile(ytdlp_bin))

        if use_standalone:
            message = (
                "yt-dlp is not installed. Install it now?\n\n"
                "This will download the standalone yt-dlp binary.\n\n"
                "Continue?"
            )
        else:
            message = (
                "Download and install the latest yt-dlp?\n\n"
                "Continue?"
            )

        reply = QMessageBox.question(
            self,
            "Update yt-dlp",
            message,
            QMessageBox.Yes | QMessageBox.No,
            QMessageBox.Yes
        )

        if reply != QMessageBox.Yes:
            return

        self.ytdlp_update_btn.setEnabled(False)
        self.ytdlp_refresh_btn.setEnabled(False)

        self.ytdlp_progress.setVisible(True)
        self.ytdlp_progress_label.setVisible(True)
        self.ytdlp_progress.setValue(0)

        if use_standalone:
            from gui.workers.ytdlp_installer import YtdlpInstallerWorker
            self.ytdlp_worker = YtdlpInstallerWorker()
        else:
            from gui.workers.ytdlp_updater import YtdlpUpdaterWorker
            self.ytdlp_worker = YtdlpUpdaterWorker()

        self.ytdlp_worker.progress.connect(self._on_ytdlp_progress)
        self.ytdlp_worker.finished.connect(self._on_ytdlp_finished)
        self.ytdlp_worker.start()

    def _on_ytdlp_progress(self, percent: int, message: str):
        """Handle yt-dlp update progress."""
        self.ytdlp_progress.setValue(percent)
        self.ytdlp_progress_label.setText(message)

    def _on_ytdlp_finished(self, success: bool, message: str):
        """Handle yt-dlp update completion."""
        self.ytdlp_progress.setVisible(False)
        self.ytdlp_progress_label.setVisible(False)
        self.ytdlp_update_btn.setEnabled(True)
        self.ytdlp_refresh_btn.setEnabled(True)

        if success:
            # Ensure newly installed binary's dir is on PATH
            if hasattr(self.ytdlp_worker, 'install_dir'):
                install_dir = self.ytdlp_worker.install_dir
                if install_dir not in os.environ.get('PATH', ''):
                    os.environ['PATH'] = install_dir + os.pathsep + os.environ.get('PATH', '')
            QMessageBox.information(self, "Success", message)
        else:
            QMessageBox.warning(self, "Install Failed", message)

        self.ytdlp_worker = None
        self._check_ytdlp_status()

    def _browse_ffmpeg_path(self):
        """Open file browser for FFmpeg binary."""
        path, _ = QFileDialog.getOpenFileName(self, "Select FFmpeg Binary")
        if path:
            self.ffmpeg_path_input.setText(path)

    def _browse_ytdlp_path(self):
        """Open file browser for yt-dlp binary."""
        path, _ = QFileDialog.getOpenFileName(self, "Select yt-dlp Binary")
        if path:
            self.ytdlp_path_input.setText(path)

    def _browse_output_dir(self):
        """Open folder browser for output directory."""
        current_dir = self.output_dir_input.text() or os.path.expanduser("~")

        # Make sure the current dir exists, otherwise use home
        if not os.path.isdir(current_dir):
            current_dir = os.path.expanduser("~")

        folder = QFileDialog.getExistingDirectory(
            self,
            "Select Output Directory",
            current_dir,
            QFileDialog.ShowDirsOnly | QFileDialog.DontResolveSymlinks
        )
        if folder:
            # Use the selected folder path
            self.output_dir_input.setText(folder)
            # Auto-save to make sure it takes effect
            self._update_config_value("output_dir", folder)

    def _update_config_value(self, key: str, value):
        """Update a single config value and save."""
        self.config[key] = value
        try:
            save_config(self.config)
        except Exception:
            pass  # Silently fail for individual updates

    def _safe_int(self, text: str, default: int) -> int:
        text = text.strip()
        if not text:
            return default
        try:
            return int(text)
        except ValueError:
            return default

    def _save_settings(self):
        """Save current settings to config."""
        try:
            # Update config dict
            output_dir = self.output_dir_input.text().strip()
            if not output_dir:
                output_dir = "music"

            self.config["output_dir"] = output_dir
            self.config["audio_format"] = self.format_combo.currentText()
            self.config["spotify_client_id"] = self.client_id_input.text().strip()
            self.config["sleep_between"] = self._safe_int(self.sleep_input.text(), 5)
            self.config["retry_attempts"] = self._safe_int(self.retry_input.text(), 3)
            self.config["max_concurrent_downloads"] = self.concurrent_spinbox.value()
            self.config["enable_metadata_embedding"] = self.metadata_check.isChecked()
            self.config["metadata_template"] = self.template_combo.currentText()
            self.config["enable_musicbrainz_lookup"] = self.musicbrainz_check.isChecked()
            self.config["auto_backup"] = self.backup_check.isChecked()
            self.config["max_backups"] = self._safe_int(self.max_backups_input.text(), 10)
            self.config["ffmpeg_path"] = self.ffmpeg_path_input.text().strip()
            self.config["ytdlp_path"] = self.ytdlp_path_input.text().strip()

            # Validate
            is_valid, errors = validate_config(self.config)
            if not is_valid:
                QMessageBox.warning(
                    self,
                    "Validation Error",
                    "Invalid settings:\n" + "\n".join(errors)
                )
                return

            # Create output directory if it doesn't exist
            if output_dir and not os.path.isabs(output_dir):
                # For relative paths, create from current working directory
                os.makedirs(output_dir, exist_ok=True)
            elif output_dir:
                # For absolute paths, try to create
                os.makedirs(output_dir, exist_ok=True)

            # Save
            save_config(self.config)
            # Reload config to ensure fresh state
            self.config = load_config()
            self._load_values()  # Refresh UI to show saved values
            self.config_saved.emit()
            QMessageBox.information(self, "Success", "Settings saved successfully!")

        except ValueError as e:
            QMessageBox.warning(self, "Error", f"Invalid value: {e}")
        except PermissionError:
            QMessageBox.warning(
                self,
                "Permission Error",
                f"Cannot create output directory:\n{output_dir}\n\n"
                "Please choose a different location."
            )
        except Exception as e:
            QMessageBox.critical(self, "Error", f"Failed to save settings: {e}")

    def _reset_to_defaults(self):
        """Reset all settings to defaults."""
        reply = QMessageBox.question(
            self,
            "Reset Settings",
            "Are you sure you want to reset all settings to defaults?",
            QMessageBox.Yes | QMessageBox.No,
            QMessageBox.No
        )
        if reply == QMessageBox.Yes:
            for key, value in DEFAULT_CONFIG.items():
                self.config[key] = value
            self._load_values()
            QMessageBox.information(self, "Reset", "Settings reset to defaults.")
