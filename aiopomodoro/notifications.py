import warnings
import typing
from functools import partial
import dataclasses
import atexit
from contextlib import contextmanager
from PySide2.QtGui import QImage, QPixmap
import gi
with warnings.catch_warnings():
    warnings.simplefilter("ignore", gi.PyGIWarning)
    from gi.repository import Notify as GINotify, GdkPixbuf

__all__ = ["Notification"]

initialized = False

# QImage => GdkPixbuf conversion helper
def _qimage_to_gdkpixbuf(image):
    image = image.convertToFormat(QImage.Format_RGBA8888)
    width = image.width()
    height = image.height()
    data = image.constBits()
    return GdkPixbuf.Pixbuf.new_from_data(
        data,
        GdkPixbuf.Colorspace.RGB,
        image.hasAlphaChannel(),
        8,
        width, height,
        image.bytesPerLine()
    )

@dataclasses.dataclass
class Notification:
    """Desktop notification builder."""
    
    @staticmethod
    def initialize(appname):
        global initialized
        if initialized:
            return
        if (code := GINotify.init(appname)):
            atexit.register(GINotify.uninit)
        else:
            raise ValueError(f"Failed to initialize libnotify: {code}")
        initialized = True

    class NotifyError(Exception):
        """libnotify domain error."""

    class Action(typing.NamedTuple):
        """Notification action item."""
        id: str
        label: str
        callback: typing.Callable
        data: typing.Any = None

    summary: str = ""
    body: str = ""
    icon: typing.Optional[QPixmap] = None
    timeout: int = GINotify.EXPIRES_DEFAULT
    urgency: int = GINotify.Urgency.LOW
    actions: typing.List[Action] = dataclasses.field(default_factory=list)
    hints: typing.Mapping[str, typing.Any] = dataclasses.field(default_factory=dict)

    def action(self, id, label, callback=None, data=None):
        """Adds a notification action."""
        if callback is None:
            return partial(self.action, id, label)
        else:
            self.actions.append(self.Action(id, label, callback, data))
        return callback

    def build(self):
        """Builds the notification."""
        it = GINotify.Notification.new(self.summary, self.body)
        if self.icon:
            it.set_image_from_pixbuf(
                _qimage_to_gdkpixbuf(self.icon.toImage())
            )
        it.set_timeout(self.timeout)
        it.set_urgency(self.urgency)
        for item in self.hints.items():
            it.add_hint(*item)
        for item in self.actions:
            it.add_action(*item)
        if not it.show():
            raise self.NotifyError
        return it

    @contextmanager
    def display(self):
        """Enters a notification context. Closes the notification on exit."""
        it = self.build()
        try:
            yield it
        finally:
            it.close() 
