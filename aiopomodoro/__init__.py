import os
from contextlib import contextmanager
from functools import partial
import signal
import typing
import dataclasses
import subprocess
import asyncio
from PySide2.QtWidgets import (
    QApplication,
    QFileDialog,
    QSystemTrayIcon,
    QMenu,
    QDialog,
    QGroupBox,
    QPushButton,
    QLabel,
    QLineEdit,
    QSpinBox,
    QCheckBox,
    QVBoxLayout,
    QHBoxLayout
)
from PySide2.QtGui import QIcon, QImage, QPixmap, QColor, QPainter
from PySide2.QtMultimedia import QMediaPlayer
from PySide2.QtCore import QUrl, QSize, Qt
import qasync
import dotenv
from xdg import BaseDirectory as xdgbase

from .aioobserve import ObservableMixIn, observe, notify, DELETED
from .qimm import immediate
from .notifications import Notification

# Application state
class State(ObservableMixIn):
    # Environment variables
    ENV = {
        "AIOPOMODORO_INTERVAL",
        "AIOPOMODORO_BREAK",
        "AIOPOMODORO_NOTIFY",
        "AIOPOMODORO_ALLOWSKIP",
        "AIOPOMODORO_LOCK",
        "AIOPOMODORO_AUDIO",
        "AIOPOMODORO_JINGLE"
    }

    # Defaults

    rest = False
    suspend = False

    # Delegate to the process environment for all
    # settings

    @property
    def interval(self):
        return int(os.getenv("AIOPOMODORO_INTERVAL", 30))

    @interval.setter
    def interval(self, value):
        os.environ["AIOPOMODORO_INTERVAL"] = str(value)

    @property
    def duration(self):
        return int(os.getenv("AIOPOMODORO_BREAK", 15))

    @duration.setter
    def duration(self, value):
        os.environ["AIOPOMODORO_BREAK"] = str(value)

    @property
    def notify(self):
        return int(os.getenv("AIOPOMODORO_NOTIFY", 30))

    @notify.setter
    def notify(self, value):
        os.environ["AIOPOMODORO_NOTIFY"] = str(value)

    @property
    def skip(self):
        return int(os.getenv("AIOPOMODORO_ALLOWSKIP", 1))

    @skip.setter
    def skip(self, value):
        os.environ["AIOPOMODORO_ALLOWSKIP"] = str(value)

    @property
    def lock(self):
        return int(os.getenv("AIOPOMODORO_LOCK", 1))

    @lock.setter
    def lock(self, value):
        os.environ["AIOPOMODORO_LOCK"] = str(int(value))

    @property
    def audio(self):
        return int(os.getenv("AIOPOMODORO_AUDIO", 1))

    @audio.setter
    def audio(self, value):
        os.environ["AIOPOMODORO_AUDIO"] = str(int(value))

    @property
    def jingle(self):
        return os.getenv("AIOPOMODORO_JINGLE", "")

    @jingle.setter
    def jingle(self, value):
        os.environ["AIOPOMODORO_JINGLE"] = value

    # Switch between break/activity delays based on state
    @property
    def delay(self):
        return self.duration if self.rest else self.interval

    # Returns the audio filename if it exists and audio output is enabled
    @property
    def audiofile(self):
        return self.jingle if self.audio and os.path.isfile(self.jingle) else ""

    # Load configuration from XDG configuration store
    def load(self, resource="aiopomodoro", loader=dotenv.load_dotenv):
        loader(os.path.join(xdgbase.save_config_path(resource), "env"))

    # Save configuration to XDG configuration store
    def save(self, resource="aiopomodoro", write=dotenv.set_key):
        path = os.path.join(xdgbase.save_config_path(resource), "env")
        for key, value in ((k, v) for k in self.ENV if (v := os.getenv(k)) is not None):
            write(path, key, value)

# Configuration dialog
class Configurator:
    def __init__(self, title):
        dialog = QDialog()
        dialog.setWindowTitle(title)
        dialog.setWindowIcon(QIcon.fromTheme("settings"))
        # File selection handler
        def select(factory):
            selection, _ = factory(
                dialog,
                "Open File",
                dir=os.getenv("HOME", None),
                filter="Audio Files (*.wav *.mp3 *.flac *.ogg *.aac)"
            )
            if selection:
                self.jingle = selection
        ico = QSize(16, 16)
        # Build dialog content
        with immediate.on(dialog) as imm:
            with imm.add(QVBoxLayout()):
                with imm.add(QHBoxLayout()):
                    with imm.add(QHBoxLayout()):
                        with immediate.on(imm.add(QGroupBox("Timers"))) as gimm:
                            with gimm.add(QVBoxLayout()):
                                with gimm.add(QHBoxLayout()):
                                    w = gimm.add(QLabel())
                                    w.setPixmap(QIcon.fromTheme("hourglass").pixmap(ico))
                                    w.setMaximumSize(ico)
                                    w = gimm.add(QLabel("Interval"))
                                    interval = gimm.add(QSpinBox())
                                    interval.setMinimum(1)
                                    interval.setSuffix("min")
                                    interval.setToolTip("Time interval between breaks")
                                with gimm.add(QHBoxLayout()):
                                    w = gimm.add(QLabel())
                                    w.setPixmap(QIcon.fromTheme("media-pause").pixmap(ico))
                                    w.setMaximumSize(ico)
                                    w = gimm.add(QLabel("Duration"))
                                    duration = gimm.add(QSpinBox())
                                    duration.setMinimum(1)
                                    duration.setSuffix("min")
                                    duration.setToolTip("Break duration")
                with immediate.on(imm.add(QGroupBox("Interactions"))) as gimm:
                    with gimm.add(QVBoxLayout()):
                        skip = gimm.add(QCheckBox("Allow break &skipping"))
                        skip.setToolTip("Shows the 'Skip' button on the break notification")
                        lock = gimm.add(QCheckBox("&Lock screen on break"))
                        lock.setToolTip("Lock screen on break start")
                with immediate.on(imm.add(QGroupBox("Audio"))) as gimm:
                    with gimm.add(QVBoxLayout()):
                        audio = gimm.add(QCheckBox("Enable &audio notification"))
                        audio.setToolTip("Plays the specified audio file before the break reminder")
                        with gimm.add(QHBoxLayout()):
                            jinglesym = gimm.add(QLabel())
                            jinglesym.setPixmap(
                                QIcon.fromTheme("sound",
                                    QIcon.fromTheme("audio-headphones")).pixmap(ico))
                            jinglesym.setMaximumSize(ico)
                            jingle = gimm.add(QLineEdit())
                            jingle.setReadOnly(True)
                            jingle.setEnabled(audio.isChecked())
                            # Change icon depending on whether file exists
                            @jingle.textChanged.connect
                            def _(
                                value,
                                error=QIcon.fromTheme("state-error", QIcon.fromTheme("error")),
                                sound=QIcon.fromTheme("sound", QIcon.fromTheme("audio-headphones"))
                            ):
                                isfile = os.path.isfile(value)
                                jinglesym.setPixmap((sound if isfile else error).pixmap(ico))
                                jinglesym.setToolTip("" if isfile else "Could not find file")
                            audio.stateChanged.connect(jingle.setEnabled)
                            w = gimm.add(QPushButton("..."))
                            w.setEnabled(audio.isChecked())
                            audio.stateChanged.connect(w.setEnabled)
                            w.clicked.connect(partial(select, QFileDialog.getOpenFileName))
                with imm.add(QHBoxLayout()):
                    w = imm.add(QPushButton("&OK"))
                    w.setIcon(QIcon.fromTheme("ok"))
                    w.clicked.connect(dialog.accept)
                    w = imm.add(QPushButton("&Cancel"))
                    w.setIcon(QIcon.fromTheme("cancel"))
                    w.clicked.connect(dialog.reject)
        self.dialog = dialog
        self.controls = {
            "interval": interval, "duration": duration, "skip": skip, "lock": lock,
            "audio": audio, "jingle": jingle
        }

    @property
    def interval(self):
        return self.controls["interval"].value()

    @interval.setter
    def interval(self, value):
        self.controls["interval"].setValue(value)

    @property
    def duration(self):
        return self.controls["duration"].value()

    @duration.setter
    def duration(self, value):
        self.controls["duration"].setValue(value)

    @property
    def skip(self):
        return self.controls["skip"].isChecked()

    @skip.setter
    def skip(self, value):
        self.controls["skip"].setCheckState(Qt.Checked if value else Qt.Unchecked)

    @property
    def lock(self):
        return self.controls["lock"].isChecked()

    @lock.setter
    def lock(self, value):
        self.controls["lock"].setCheckState(Qt.Checked if value else Qt.Unchecked)

    @property
    def audio(self):
        return self.controls["audio"].isChecked()

    @audio.setter
    def audio(self, value):
        self.controls["audio"].setCheckState(Qt.Checked if value else Qt.Unchecked)

    @property
    def jingle(self):
        return self.controls["jingle"].text()

    @jingle.setter
    def jingle(self, value):
        self.controls["jingle"].setText(value)

    def run(self):
        return self.dialog.exec_() == QDialog.Accepted

    @contextmanager
    def use(self, state):
        # Load settings into dialog controls
        self.interval = state.interval
        self.duration = state.duration
        self.skip = state.skip
        self.lock = state.lock
        self.audio = state.audio
        self.jingle = state.jingle
        # Yield to caller
        yield state
        # Show the dialog
        if self.run():
            # If accepted, update model state ignoring
            # unchanged properties
            if self.interval != state.interval: state.interval = self.interval
            if self.duration != state.duration: state.duration = self.duration
            if self.skip != state.skip: state.skip = self.skip
            if self.lock != state.lock: state.lock = self.lock
            if self.audio != state.audio: state.audio = self.audio
            if self.jingle != state.jingle: state.jingle = self.jingle

async def display(application, close, state, setup):
    # Initialize the context menu
    menu = QMenu()
    trigger = menu.addAction(QIcon.fromTheme("media-pause"), "&Pause")
    settings = menu.addAction(QIcon.fromTheme("settings"), "&Settings")
    menu.addSeparator()
    menu.addAction(QIcon.fromTheme("exit"), "&Exit").triggered.connect(close.set)

    # Play/pause trigger action
    @trigger.triggered.connect
    def _():
        state.suspend = not state.suspend

    configurator = Configurator("Settings")

    # Configuration action
    @settings.triggered.connect
    def _():
        suspend = state.suspend
        with configurator.use(state):
            state.suspend = True
            state.configuring = True
        state.suspend = suspend
        state.configuring = False

    # Set up the tray icon
    tray = QSystemTrayIcon(application)
    tray.setContextMenu(menu)

    # Used to handle asynchronous initialization tasks
    # on start + handle any pending asynchronous events
    async def show(awaitable):
        await awaitable
        # Yield to the event loop once to allow
        # observers triggered by the awaitable to process
        await asyncio.sleep(0)
        tray.show()

    # Propagate the icon state to the tray icon
    @observe.seq(state, "icon")
    def icon(value):
        tray.setIcon(value)

    # Colorize the icon based on elapsed time and current
    # mode
    @observe.seq(state, "elapsed")
    def colorize(value):
        pixmap = state.base.pixmap(state.base.actualSize(QSize(22, 22)))
        painter = QPainter(pixmap)
        try:
            painter.setCompositionMode(QPainter.CompositionMode_SourceAtop)
            painter.fillRect(
                0, 0,
                pixmap.width(), pixmap.height(),
                QColor(0, 0, 255, 128 * (1 - (value / (state.delay * 60)))) if state.rest else (
                    QColor(255, 0, 0, 128 * value / (state.delay * 60)))
            )
        finally:
            painter.end()
        state.icon = QIcon(pixmap)

    # Update tray icon tooltip with the remaining time
    @observe.seq(state, "elapsed")
    def tooltip(value):
        remainder = state.delay * 60 - value
        m, s = divmod(remainder, 60)
        tray.setToolTip(f"Break ends in {m}m{s}s" if state.rest else f"Next break in {m}m{s}s")

    # Display break start/end notifications
    @observe.switch(state, "remind")
    async def reminder(value):
        if value is not DELETED:
            notification = Notification(
                "Break time",
                f"Break ends in {state.notify} seconds" if state.rest else f"Next break in {state.notify} seconds",
                QIcon.fromTheme("hourglass").pixmap(16, 16),
                state.notify * 1000
            )

            @notification.action("pause", "Pause")
            def _(*args, **kwargs):
                state.suspend = True

            if not state.rest and state.skip:
                @notification.action("skip", "Skip")
                def _(*args, **kwargs):
                    notify(state, "delay")

            if (audiofile := state.audiofile):
                player = QMediaPlayer()
                player.setMedia(QUrl.fromLocalFile(audiofile))
                player.play()

            # Keep notification alive until the break window
            # fully ends
            with notification.display() as it:
                await value.wait()

    # Change icon of pause/continue trigger based on the
    # suspension state in the model
    @observe.seq(state, "suspend")
    def suspended(value):
        trigger.setIcon(QIcon.fromTheme("media-play" if value else "media-pause"))
        trigger.setText("&Resume" if value else "&Pause")

    # Disable context menu interactions (except exit) as long
    # as the configuration dialog is visible
    @observe.seq(state, "configuring")
    def configuring(value):
        trigger.setEnabled(not value)
        settings.setEnabled(not value)

    await asyncio.gather(
        icon,
        colorize,
        tooltip,
        suspended,
        configuring,
        reminder,
        show(setup(state))
    )

async def terminate(awaitable, *callables):
    await awaitable
    for function in callables:
        function()

async def initialize(state):
    # Perform any initialization tasks that depend on
    # Qt or other externals
    state.icon = state.base = QIcon.fromTheme("display")
    # Kickstart the timer by notifying observers
    # about the initial mode
    notify(state, "rest", "notify")

async def control(state):
    # Signals whether we are active (set) or paused (clear)
    active = asyncio.Event()
    active.set()

    # Reset the timer whenever we change modes from rest => activity
    # or activity => rest
    @observe.seq(state, "rest")
    def modeswitch(value):
        notify(state, "delay")

    # Check whether we need to remind the user of an incoming
    # break or activity window
    @observe.switch(state, "notify")
    async def notifier(remainder):
        if remainder > 0:
            @observe.seq(state, "elapsed")
            def elapsed(value):
                delta = state.delay * 60 - value
                if delta <= remainder:
                    if not hasattr(state, "remind"):
                        state.remind = asyncio.Event()
            await elapsed

    # Main timer coroutine
    @observe.switch(state, "delay")
    async def delay(value):
        # Convert minutes => seconds
        value *= 60
        # Delete existing reminder event, if any
        try:
            del state.remind
        except AttributeError:
            pass
        state.elapsed = 0
        while True:
            # Wait for 1s, assuming we are active. Otherwise
            # we block until we are no longer suspended
            await asyncio.gather(asyncio.sleep(1), active.wait())
            state.elapsed += 1
            if state.elapsed >= value:
                state.elapsed = 0
                # If the end of the activity/rest window is reached,
                # trigger the reminder signal. This should immediately
                # hide the reminder notification
                try:
                    state.remind.set()
                    del state.remind
                except AttributeError:
                    pass
                # If we're at the end of an activity window and the
                # user asked to lock the screen, call xdg-screensaver.
                # xdg-screensaver exits with inane status codes so
                # we avoid check=True
                if not state.rest and state.lock:
                    subprocess.run(
                        ("/usr/bin/xdg-screensaver", "lock"),
                        stdin=subprocess.DEVNULL,
                        stdout=subprocess.DEVNULL,
                        stderr=subprocess.PIPE,
                    )
                # Flip the activity state
                state.rest = not state.rest

    # React to changes in the suspension state, this pauses
    # the `delay' coroutine
    @observe.seq(state, "suspend")
    def suspended(value):
        if value:
            active.clear()
        else:
            active.set()

    @observe.seq(state, "configuring")
    def configured(value):
        if not value:
            state.save()

    # Make sure Changes in break/activity window durations reset
    # the timer
    @observe.seq(state, "interval")
    def interval(value):
        if not state.rest:
            notify(state, "delay")
    
    @observe.seq(state, "duration")
    def duration(value):
        if state.rest:
            notify(state, "delay")

    await asyncio.gather(delay, suspended, notifier, modeswitch, configured, interval, duration)

async def amain(appname):
    loop = asyncio.get_event_loop()
    application = QApplication.instance()
    application.setApplicationName(appname)
    # Avoid terminating the application if the settings
    # dialog is closed
    application.setQuitOnLastWindowClosed(False)
    # Graceful shutdown event
    close = asyncio.Event()
    loop.add_signal_handler(signal.SIGINT, close.set)
    application.aboutToQuit.connect(close.set)
    state = State()
    state.load()
    # SIGUSR1 pauses the timer
    loop.add_signal_handler(
        signal.SIGUSR1,
        lambda: getattr(state, "configuring", False) or setattr(state, "suspend", not state.suspend)
    )
    # SIGUSR2 resets the timer
    loop.add_signal_handler(signal.SIGUSR2, notify, state, "delay")
    try:
        await asyncio.gather(
            ctrl := asyncio.create_task(control(state)),
            view := asyncio.create_task(display(application, close, state, initialize)),
            terminate(close.wait(), view.cancel, ctrl.cancel)
        )
    except asyncio.CancelledError:
        pass

def main(appname="Pomodoro timer", run=qasync.run):
    Notification.initialize(appname)
    run(amain(appname))

if __name__ == "__main__":
    main()
