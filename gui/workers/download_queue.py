"""Download queue manager with Qt signals for GUI updates."""

from dataclasses import dataclass, field
from enum import Enum
from typing import List, Optional
import uuid

from PySide6.QtCore import QObject, Signal


class DownloadStatus(Enum):
    """Status of a download item."""
    PENDING = "pending"
    DOWNLOADING = "downloading"
    COMPLETED = "completed"
    FAILED = "failed"
    CANCELLED = "cancelled"


@dataclass
class QueueItem:
    """A single item in the download queue."""
    id: str
    artist: str
    track: str
    album: Optional[str] = None
    album_art_url: Optional[str] = None
    playlist: Optional[str] = None
    status: DownloadStatus = DownloadStatus.PENDING
    progress: int = 0  # 0-100
    error_message: Optional[str] = None
    file_path: Optional[str] = None


class DownloadQueue(QObject):
    """
    Central download queue manager with Qt signals.

    Signals:
        item_added: Emitted when a new item is added
        item_updated: Emitted when an item's status changes
        item_removed: Emitted when an item is removed
        queue_updated: Emitted with total pending count
        queue_started: Emitted when downloads begin
        queue_paused: Emitted when downloads are paused
        queue_completed: Emitted when all downloads finish
    """

    # Signals
    item_added = Signal(object)  # QueueItem
    item_updated = Signal(object)  # QueueItem
    item_removed = Signal(str)  # item_id
    queue_updated = Signal(int)  # pending count
    queue_started = Signal()
    queue_paused = Signal()
    queue_completed = Signal(int, int)  # success_count, fail_count

    def __init__(self, parent=None):
        super().__init__(parent)
        self._items: List[QueueItem] = []
        self._is_running = False
        self._is_paused = False

    @property
    def items(self) -> List[QueueItem]:
        """Get all queue items."""
        return self._items.copy()

    @property
    def pending_count(self) -> int:
        """Get count of pending items."""
        return len([i for i in self._items if i.status == DownloadStatus.PENDING])

    @property
    def downloading_count(self) -> int:
        """Get count of currently downloading items."""
        return len([i for i in self._items if i.status == DownloadStatus.DOWNLOADING])

    @property
    def completed_count(self) -> int:
        """Get count of completed items."""
        return len([i for i in self._items if i.status == DownloadStatus.COMPLETED])

    @property
    def failed_count(self) -> int:
        """Get count of failed items."""
        return len([i for i in self._items if i.status == DownloadStatus.FAILED])

    @property
    def is_running(self) -> bool:
        """Check if downloads are currently running."""
        return self._is_running

    @property
    def is_paused(self) -> bool:
        """Check if downloads are paused."""
        return self._is_paused

    def add_track(self, artist: str, track: str, playlist: Optional[str] = None,
                  album: Optional[str] = None, album_art_url: Optional[str] = None) -> QueueItem:
        """Add a single track to the queue."""
        item = QueueItem(
            id=str(uuid.uuid4()),
            artist=artist,
            track=track,
            album=album,
            album_art_url=album_art_url,
            playlist=playlist,
            status=DownloadStatus.PENDING,
            progress=0
        )
        self._items.append(item)
        self.item_added.emit(item)
        self.queue_updated.emit(self.pending_count)
        return item

    def add_item(self, artist: str, track: str, album: str = "", playlist: str = "",
                 album_art_url: str = "") -> QueueItem:
        """Add a single item to the queue (alias for add_track with album support)."""
        return self.add_track(artist, track, playlist or None,
                              album=album or None, album_art_url=album_art_url or None)

    def add_tracks(self, tracks: list, playlist: Optional[str] = None) -> List[QueueItem]:
        """
        Add multiple tracks to the queue.

        Args:
            tracks: List of dicts with 'artist' and 'track' keys
            playlist: Optional playlist name

        Returns:
            List of created QueueItems
        """
        items = []
        for track in tracks:
            artist = track.get("artist", "").strip()
            track_name = track.get("track", "").strip()
            if artist and track_name:
                item = self.add_track(
                    artist, track_name,
                    playlist=track.get("playlist") or playlist,
                    album=track.get("album"),
                    album_art_url=track.get("album_art_url"),
                )
                items.append(item)
        return items

    def get_item(self, item_id: str) -> Optional[QueueItem]:
        """Get an item by ID."""
        for item in self._items:
            if item.id == item_id:
                return item
        return None

    def update_item_status(self, item_id: str, status: DownloadStatus,
                          progress: int = None, error_message: str = None,
                          file_path: str = None):
        """Update an item's status."""
        item = self.get_item(item_id)
        if item:
            item.status = status
            if progress is not None:
                item.progress = progress
            if error_message is not None:
                item.error_message = error_message
            if file_path is not None:
                item.file_path = file_path
            self.item_updated.emit(item)
            self.queue_updated.emit(self.pending_count)

    def remove_item(self, item_id: str):
        """Remove an item from the queue."""
        item = self.get_item(item_id)
        if item:
            self._items.remove(item)
            self.item_removed.emit(item_id)
            self.queue_updated.emit(self.pending_count)

    def clear_completed(self):
        """Remove all completed and failed items."""
        self._items = [i for i in self._items
                      if i.status not in (DownloadStatus.COMPLETED, DownloadStatus.FAILED)]
        self.queue_updated.emit(self.pending_count)

    def clear_all(self):
        """Clear all items from the queue."""
        self._items.clear()
        self.queue_updated.emit(0)

    def get_pending_items(self) -> List[QueueItem]:
        """Get all pending items."""
        return [i for i in self._items if i.status == DownloadStatus.PENDING]

    def get_next_pending(self) -> Optional[QueueItem]:
        """Get the next pending item."""
        for item in self._items:
            if item.status == DownloadStatus.PENDING:
                return item
        return None

    def set_running(self, running: bool):
        """Set whether the queue is currently processing."""
        self._is_running = running
        if running:
            self._is_paused = False
            self.queue_started.emit()

    def set_paused(self, paused: bool):
        """Set whether the queue is paused."""
        self._is_paused = paused
        if paused:
            self.queue_paused.emit()

    def mark_queue_completed(self):
        """Mark the queue as completed and emit signal."""
        self._is_running = False
        self._is_paused = False
        self.queue_completed.emit(self.completed_count, self.failed_count)

    def has_pending(self) -> bool:
        """Check if there are pending items."""
        return self.pending_count > 0

    def retry_failed(self):
        """Reset all failed items to pending."""
        for item in self._items:
            if item.status == DownloadStatus.FAILED:
                item.status = DownloadStatus.PENDING
                item.progress = 0
                item.error_message = None
                self.item_updated.emit(item)
        self.queue_updated.emit(self.pending_count)
