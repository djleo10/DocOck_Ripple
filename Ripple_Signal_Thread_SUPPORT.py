import xipppy as xp
from time import time, sleep
import collections as c
from Ripple_Settings_SUPPORT import *
from PyQt5.QtCore import QMutex, QThread, pyqtSignal

class RippleThread(QThread):
    """
    Runs RippleController.acquire() off the GUI thread.

    The controller instance is shared with the GUI, which only ever touches it
    through snapshot_buffers() (mutex-protected), so no data is copied across
    the thread boundary on every sample.
    """
    status_update = pyqtSignal(str)

    def __init__(self, controller, parent=None):
        super().__init__(parent)
        self.ripple = controller
        self._stop = False
        self.calib_mode = None

    def stop_requested(self):
        return self._stop

    def run(self):
        self._stop = False
        try:
            self.ripple.acquire(stop_flag=self.stop_requested,
                                calib_mode=self.calib_mode)
        except Exception as e:
            self.status_update.emit(f"[Stream] acquisition stopped: {e}")

    def stop(self, timeout_ms=2000):
        self._stop = True
        if self.isRunning():
            self.wait(timeout_ms)
