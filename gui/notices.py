"""Non-blocking notices that any view can post to the main window's notice bar."""

from typing import Callable, Optional

from PySide6.QtCore import QObject, Signal


class NoticeHub(QObject):
    """Carries notices from views to whichever notice bar is listening."""

    posted = Signal(str, str, str, object)


hub = NoticeHub()

QUEUED_HINT = "Downloads start when you press Start Downloads."


def notify(text: str, kind: str = "info", action_label: str = "", action: Optional[Callable[[], None]] = None):
    """Show a short message in the notice bar without interrupting the user.

    @param text: Message to show.
    @param kind: "info", "success" or "warning", which sets the bar colour.
    @param action_label: Optional button text, such as "Go to Downloads".
    @param action: Called when the button is clicked.
    """
    hub.posted.emit(text, kind, action_label, action)
