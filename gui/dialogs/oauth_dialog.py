"""Spotify OAuth dialog for authentication."""

import errno
import webbrowser
from html import escape
from http.server import HTTPServer, BaseHTTPRequestHandler
import urllib.parse
from typing import Callable, Optional

from PySide6.QtWidgets import (
    QApplication, QDialog, QVBoxLayout, QHBoxLayout, QLabel,
    QPushButton, QLineEdit, QProgressBar, QMessageBox,
    QGroupBox, QFormLayout
)
from PySide6.QtCore import Qt, Signal, QThread, QTimer, QUrl
from PySide6.QtGui import QDesktopServices

from spotify_api.auth import (
    DEFAULT_SPOTIFY_REDIRECT_URI,
    SpotifyPKCEAuth,
    PKCEPair,
    check_spotify_credentials,
    extract_code_from_redirect_url,
)

_PORT_BUSY_ERRNOS = {errno.EADDRINUSE, errno.EACCES, 10048, 10013}


SPOTIFY_DASHBOARD_URL = "https://developer.spotify.com/dashboard"


class SpotifySetupDialog(QDialog):
    """Step-by-step guide for creating the Spotify app HARMONI needs before it can connect."""

    def __init__(self, redirect_uri: str, parent=None):
        """Build the guide.

        @param redirect_uri: Redirect URI the user must add to their Spotify app.
        @param parent: Optional Qt parent.
        """
        super().__init__(parent)
        self.setWindowTitle("Set Up Spotify")
        self.setMinimumWidth(560)
        layout = QVBoxLayout(self)
        layout.setSpacing(14)

        title = QLabel("Create your own Spotify app")
        title.setObjectName("section")
        layout.addWidget(title)
        intro = QLabel(
            "Spotify only lets HARMONI read your playlists through an app you own. "
            "It's free and takes about two minutes."
        )
        intro.setWordWrap(True)
        layout.addWidget(intro)

        dashboard_btn = QPushButton("Open Spotify Dashboard")
        dashboard_btn.clicked.connect(lambda: QDesktopServices.openUrl(QUrl(SPOTIFY_DASHBOARD_URL)))
        self._add_step(layout, 1, "Open the Spotify Developer Dashboard and log in with your Spotify account.", dashboard_btn)
        self._add_step(layout, 2, "Click Create app. Any name and description will do. Tick Web API.")

        uri_row = QHBoxLayout()
        uri_field = QLineEdit(redirect_uri)
        uri_field.setReadOnly(True)
        uri_row.addWidget(uri_field)
        copy_btn = QPushButton("Copy")
        copy_btn.setObjectName("secondary")

        def copy_uri():
            QApplication.clipboard().setText(redirect_uri)
            copy_btn.setText("Copied")

        copy_btn.clicked.connect(copy_uri)
        uri_row.addWidget(copy_btn)
        self._add_step(layout, 3, "Under Redirect URIs, paste this address exactly, click Add, then Save.", uri_row)

        self._add_step(layout, 4, "Open User Management in your new app and add the email of every Spotify account that will use HARMONI, including your own.")
        self._add_step(layout, 5, "Open the app's Settings page and copy the Client ID.")
        self._add_step(layout, 6, "Paste the Client ID into HARMONI's Settings, click Save, then come back here and click Connect.")

        note = QLabel("The Spotify account that owns the app needs Premium. Spotify requires it for apps in Development Mode.")
        note.setObjectName("subtitle")
        note.setWordWrap(True)
        layout.addWidget(note)

        buttons = QHBoxLayout()
        buttons.addStretch()
        close_btn = QPushButton("Close")
        close_btn.setObjectName("secondary")
        close_btn.clicked.connect(self.reject)
        buttons.addWidget(close_btn)
        settings_btn = QPushButton("Open HARMONI Settings")
        settings_btn.clicked.connect(self.accept)
        buttons.addWidget(settings_btn)
        layout.addLayout(buttons)

    @staticmethod
    def _add_step(layout, number: int, text: str, extra=None):
        """Add one numbered step, with an optional button or row under it.

        @param layout: Layout the step is added to.
        @param number: Step number shown to the user.
        @param text: What the user does in this step.
        @param extra: Optional widget or layout placed under the text.
        """
        label = QLabel(f"<b>{number}.</b> {escape(text)}")
        label.setWordWrap(True)
        layout.addWidget(label)
        if extra is None:
            return
        row = QHBoxLayout()
        row.setContentsMargins(20, 0, 0, 0)
        if isinstance(extra, QHBoxLayout):
            row.addLayout(extra)
        else:
            row.addWidget(extra)
            row.addStretch()
        layout.addLayout(row)


def prompt_spotify_setup(parent, redirect_uri: str) -> bool:
    """Show the Spotify setup guide and return True when the user picks Open HARMONI Settings.

    @param parent: Widget that owns the dialog.
    @param redirect_uri: Redirect URI the user must add to their Spotify app.
    """
    return SpotifySetupDialog(redirect_uri or DEFAULT_SPOTIFY_REDIRECT_URI, parent).exec() == QDialog.Accepted


class FunctionThread(QThread):
    """Run one blocking callable off the UI thread and report its result or exception."""

    succeeded = Signal(object)
    failed = Signal(object)

    _alive = set()

    def __init__(self, fn: Callable[[], object]):
        """Wrap the callable. The thread has no parent and keeps itself alive until it finishes.

        @param fn: Zero-argument callable to run on the worker thread.
        """
        super().__init__()
        self._fn = fn
        self.finished.connect(self._release)

    def start(self, *args):
        """Start the thread and hold a reference until it finishes.

        @param args: Passed through to QThread.start.
        """
        FunctionThread._alive.add(self)
        super().start(*args)

    def run(self):
        """Call the wrapped function and emit its outcome."""
        try:
            result = self._fn()
        except Exception as e:
            self.failed.emit(e)
        else:
            self.succeeded.emit(result)

    def _release(self):
        """Drop the self reference once the thread has finished."""
        FunctionThread._alive.discard(self)


class CallbackHandler(BaseHTTPRequestHandler):
    """HTTP handler for OAuth callback."""

    def log_message(self, format, *args):
        """Suppress logging."""
        pass

    def do_GET(self):
        """Handle GET request (OAuth callback)."""
        path, _, query = self.path.partition("?")
        if path != getattr(self.server, "expected_path", "/callback"):
            self.send_response(404)
            self.send_header("Content-Type", "text/plain; charset=utf-8")
            self.end_headers()
            self.wfile.write(b"Not Found")
            return

        params = urllib.parse.parse_qs(query)
        error = (params.get("error") or [""])[0]
        if not error and not params.get("code"):
            error = "no authorization code in the redirect"

        self.send_response(200)
        self.send_header("Content-Type", "text/html")
        self.end_headers()

        html = """
        <html>
        <head>
            <title>HARMONI - Spotify Auth</title>
            <style>
                body {
                    font-family: 'Segoe UI', Arial, sans-serif;
                    background: linear-gradient(135deg, #1a1a2e 0%, #16213e 100%);
                    color: #fff;
                    display: flex;
                    justify-content: center;
                    align-items: center;
                    min-height: 100vh;
                    margin: 0;
                }
                .container {
                    text-align: center;
                    padding: 40px;
                }
                h1 { color: #1db954; }
                p { color: #a0a0a0; }
            </style>
        </head>
        <body>
            <div class="container">
                <h1>Authentication Successful!</h1>
                <p>You can close this window and return to HARMONI.</p>
            </div>
        </body>
        </html>
        """
        if error:
            html = (
                html.replace("#1db954", "#e74c3c")
                .replace("Authentication Successful!", "Authentication Failed")
                .replace(
                    "You can close this window and return to HARMONI.",
                    f"Spotify reported: {escape(error)}. Return to HARMONI for details.",
                )
            )
        self.wfile.write(html.encode())

        self.server.callback_path = self.path


class _CallbackHTTPServer(HTTPServer):
    """Loopback server that refuses to share a port another process already holds."""

    allow_reuse_address = False
    allow_reuse_port = False


class CallbackServerThread(QThread):
    """Thread for running the OAuth callback server."""

    callback_received = Signal(str)  # Emits the callback URL path
    server_error = Signal(str)  # Emits error message

    def __init__(self, port: int = 8888, path: str = "/callback", parent=None):
        super().__init__(parent)
        self.port = port
        self.path = path
        self.server = None
        self._running = True

    def bind(self):
        """Bind the loopback server now, raising OSError when the port is unavailable."""
        server = _CallbackHTTPServer(("127.0.0.1", self.port), CallbackHandler)
        server.expected_path = self.path
        server.callback_path = None
        server.timeout = 0.2
        self.server = server

    def run(self):
        """Run the callback server."""
        try:
            if self.server is None:
                self.bind()

            while self._running:
                self.server.handle_request()
                if self.server.callback_path:
                    self.callback_received.emit(
                        f"http://127.0.0.1:{self.port}{self.server.callback_path}"
                    )
                    break

        except OSError as e:
            self.server_error.emit(f"Could not start callback server: {e}")
        finally:
            self.close_server()

    def stop(self):
        """Stop the callback server."""
        self._running = False

    def close_server(self):
        """Release the listening socket if it is still open."""
        server, self.server = self.server, None
        if server is not None:
            server.server_close()


class SpotifyOAuthDialog(QDialog):
    """Dialog for Spotify OAuth authentication."""

    auth_completed = Signal(bool, str)  # success, message
    open_settings_requested = Signal()

    def __init__(self, config: dict, parent=None):
        super().__init__(parent)
        self.config = config
        self.auth = SpotifyPKCEAuth(config)
        self.callback_thread = None
        self._exchange_thread: Optional[FunctionThread] = None
        self.pkce_pair: Optional[PKCEPair] = None
        self.state: Optional[str] = None

        self.setWindowTitle("Connect to Spotify")
        self.setMinimumWidth(500)
        self.setModal(True)

        self._setup_ui()

    def _setup_ui(self):
        """Set up the dialog UI."""
        layout = QVBoxLayout(self)
        layout.setSpacing(20)

        # Title
        title = QLabel("Connect your Spotify Account")
        title.setObjectName("section")
        layout.addWidget(title)

        # Instructions
        instructions = QLabel(
            "Click the button below to open Spotify in your browser.\n"
            "After logging in, you'll be redirected back here automatically."
        )
        instructions.setWordWrap(True)
        layout.addWidget(instructions)

        # Start button
        self.start_btn = QPushButton("Open Spotify Login")
        self.start_btn.clicked.connect(self._start_oauth)
        layout.addWidget(self.start_btn)

        # Progress indicator
        self.progress = QProgressBar()
        self.progress.setRange(0, 0)  # Indeterminate
        self.progress.hide()
        layout.addWidget(self.progress)

        # Status label
        self.status_label = QLabel("")
        self.status_label.setWordWrap(True)
        layout.addWidget(self.status_label)

        # Manual entry fallback
        manual_group = QGroupBox("Manual Entry (if redirect doesn't work)")
        manual_layout = QFormLayout(manual_group)

        self.url_input = QLineEdit()
        self.url_input.setPlaceholderText("Paste the full redirect URL here...")
        manual_layout.addRow("Redirect URL:", self.url_input)

        submit_btn = QPushButton("Submit")
        submit_btn.setObjectName("secondary")
        submit_btn.clicked.connect(self._submit_manual_url)
        manual_layout.addRow("", submit_btn)

        layout.addWidget(manual_group)

        # Cancel button
        btn_layout = QHBoxLayout()
        btn_layout.addStretch()
        cancel_btn = QPushButton("Cancel")
        cancel_btn.setObjectName("secondary")
        cancel_btn.clicked.connect(self.reject)
        btn_layout.addWidget(cancel_btn)
        layout.addLayout(btn_layout)

    def _start_oauth(self):
        """Start the OAuth flow."""
        creds = check_spotify_credentials(self.config)
        if not creds.get("ok"):
            if prompt_spotify_setup(self, creds.get("redirect_uri")):
                self.open_settings_requested.emit()
                self.reject()
            return

        try:
            # Begin OAuth flow
            flow = self.auth.begin_oauth_flow(show_dialog=True)
            self.pkce_pair = flow["pkce_pair"]
            self.state = flow["state"]
            auth_url = flow["auth_url"]

            redirect_uri = self.config.get("spotify_redirect_uri") or DEFAULT_SPOTIFY_REDIRECT_URI
            parsed = urllib.parse.urlparse(redirect_uri)
            port = parsed.port or 8888
            path = parsed.path or "/"

            self._stop_callback_server()
            thread = CallbackServerThread(port, path)
            port_message = ""
            try:
                thread.bind()
            except OSError as e:
                if e.errno in _PORT_BUSY_ERRNOS or getattr(e, "winerror", None) in _PORT_BUSY_ERRNOS:
                    port_message = f"Port {port} is already in use, so HARMONI cannot catch the Spotify redirect."
                else:
                    port_message = f"Could not start the callback server on port {port}: {e}"
            else:
                thread.callback_received.connect(self._on_callback_received)
                thread.server_error.connect(self._on_server_error)
                self.callback_thread = thread
                thread.start()

            # Open browser
            webbrowser.open(auth_url)

            if port_message:
                self._on_server_error(
                    port_message + "\nAfter approving in the browser, copy the full address from the address bar."
                )
                return

            # Update UI
            self.start_btn.setEnabled(False)
            self.progress.show()
            self.status_label.setText("Waiting for Spotify login...\nA browser window should have opened.")

        except Exception as e:
            self.status_label.setText(f"Error starting OAuth: {e}")
            self.status_label.setStyleSheet("color: #e74c3c;")

    def _on_callback_received(self, callback_url: str):
        """Handle OAuth callback received."""
        self._process_callback_url(callback_url)

    def _on_server_error(self, error: str):
        """Handle callback server error."""
        self.progress.hide()
        self.start_btn.setEnabled(True)
        self.status_label.setText(f"Server error: {error}\n\nYou can paste the redirect URL manually below.")
        self.status_label.setStyleSheet("color: #f39c12;")

    def _submit_manual_url(self):
        """Handle manual URL submission."""
        url = self.url_input.text().strip()
        if not url:
            QMessageBox.warning(self, "Empty URL", "Please paste the redirect URL.")
            return
        self._process_callback_url(url)

    def _process_callback_url(self, callback_url: str):
        """Validate the OAuth callback URL and exchange its code for a token off the UI thread."""
        if self._exchange_thread is not None and self._exchange_thread.isRunning():
            return
        try:
            # Extract code from URL
            params = extract_code_from_redirect_url(callback_url)

            if params.get("error"):
                raise RuntimeError(f"Spotify returned error: {params['error']}")

            code = params.get("code")
            if not code:
                raise RuntimeError("No authorization code found in redirect URL")

            # Verify state
            returned_state = params.get("state")
            if self.state and returned_state != self.state:
                raise RuntimeError("State mismatch - possible CSRF attack")

            if not self.pkce_pair:
                raise RuntimeError("PKCE pair not found - please restart the login process")

        except Exception as e:
            self._show_failure(str(e))
            return

        self.status_label.setText("Exchanging code for access token...")
        auth = self.auth
        verifier = self.pkce_pair.code_verifier
        self._exchange_thread = FunctionThread(
            lambda: auth.exchange_code_for_token(code=code, code_verifier=verifier)
        )
        self._exchange_thread.succeeded.connect(self._on_exchange_succeeded)
        self._exchange_thread.failed.connect(self._on_exchange_failed)
        self._exchange_thread.start()

    def _on_exchange_succeeded(self, _token):
        """Report a successful token exchange and close shortly after.

        @param _token: The TokenInfo saved by the exchange.
        """
        self.progress.hide()
        self.status_label.setText("Successfully connected to Spotify!")
        self.status_label.setStyleSheet("color: #1db954;")
        self.auth_completed.emit(True, "Successfully connected to Spotify")
        QTimer.singleShot(1500, self.accept)

    def _on_exchange_failed(self, error):
        """Report a failed token exchange.

        @param error: The exception raised by the exchange.
        """
        self._show_failure(str(error))

    def _show_failure(self, message: str):
        """Show an authentication failure and let the user try again.

        @param message: Reason shown to the user.
        """
        self.progress.hide()
        self.start_btn.setEnabled(True)
        self.status_label.setText(f"Authentication failed: {message}")
        self.status_label.setStyleSheet("color: #e74c3c;")
        self.auth_completed.emit(False, message)

    def _stop_callback_server(self):
        """Stop the callback thread, wait for it, and free its port."""
        thread, self.callback_thread = self.callback_thread, None
        if thread is None:
            return
        thread.stop()
        if thread.isRunning():
            thread.wait(3000)
        thread.close_server()

    def _detach_exchange_thread(self):
        """Stop a running token exchange from calling back into this dialog."""
        thread, self._exchange_thread = self._exchange_thread, None
        if thread is not None and thread.isRunning():
            thread.succeeded.disconnect(self._on_exchange_succeeded)
            thread.failed.disconnect(self._on_exchange_failed)

    def done(self, result):
        """Stop background work before the dialog closes with any result.

        @param result: The QDialog result code.
        """
        self._stop_callback_server()
        self._detach_exchange_thread()
        super().done(result)

    def closeEvent(self, event):
        """Handle dialog close."""
        self._stop_callback_server()
        super().closeEvent(event)
