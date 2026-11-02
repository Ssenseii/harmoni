"""Confirmation shown after tracks are added to the download queue."""

from PySide6.QtWidgets import QMessageBox

QUEUED_HINT = "Downloads don't start on their own. Open Downloads and press Start Downloads."


def confirm_queued(parent, text: str) -> bool:
    """Tell the user tracks were queued and return True when they choose Go to Downloads.

    @param parent: Widget that owns the message box.
    @param text: What was added, for example "Added 26 tracks to the download queue."
    """
    box = QMessageBox(parent)
    box.setIcon(QMessageBox.Information)
    box.setWindowTitle("Added to Queue")
    box.setText(text)
    box.setInformativeText(QUEUED_HINT)
    go_btn = box.addButton("Go to Downloads", QMessageBox.AcceptRole)
    box.addButton("Keep Browsing", QMessageBox.RejectRole)
    box.setDefaultButton(go_btn)
    box.exec()
    return box.clickedButton() is go_btn
