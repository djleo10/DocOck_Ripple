import csv
import os
import json
import time
import numpy as np
import pygame as pg
from abc import ABC, abstractmethod
from datetime import datetime
from PyQt5.QtCore import QTimer

try:
    from ..Ripple_USB_Finder_SUPPORT import Ripple_USBFinder
except ImportError:
    from Ripple_USB_Finder_SUPPORT import Ripple_USBFinder

class BaseGame(ABC):
    def __init__(self, basepath=None, num_channels=2, save_root=None,
                 emg_signal=None, emg_source=None, emg_control=False,
                 on_finished=None):

        if basepath is None:
            basepath = os.path.dirname(os.path.abspath(__file__))
        self.basepath = basepath

        self._save_root = save_root 

        # EMG
        self.emg_signal      = emg_signal
        self.emg_source      = emg_source
        self.emg_control     = emg_control or emg_signal is not None or emg_source is not None
        self.on_finished     = on_finished

        # Common state
        self.num_channels      = num_channels
        self.session_start = datetime.now()

        # Sampling
        self._last_sample_time = 0.0
        self._sample_interval  = 0.1
        self._recording         = False
        self._phase_samples     = {}
        self._current_phase_key = None
        self._trial_start_time  = None

        # Saving data
        self._csv_file        = None  
        self._csv_writer      = None
        self._csv_fieldnames = []

        # pygame - subclass sets these up properly in setup()
        self.screen = None
        self.clock  = None
        self.font   = None

        # QTimer
        self.timer = QTimer()
        self.timer.setInterval(16)
        self.timer.timeout.connect(self.tick)

    @abstractmethod
    def setup(self):
        """
        Initialise pygame, create screen, clock, font, 
        game-specific variables. Called before timer starts.
        """
        pass

    @abstractmethod
    def game_name(self) -> str:     
        pass

    @abstractmethod
    def tick(self):
        """
        One frame. Handle events, update state, draw.
        Must call pg.display.flip() and clock.tick().
        """
        pass

    @abstractmethod
    def get_current_sample(self) -> dict:
        """
        Return whatever this game wants to record right now as a dict.
        Called by record_sample() when should_sample() returns True.
        """
        pass

    @abstractmethod
    def _load_progress(self):
        """
        Load whatever progress the game wants to load from the data file.
        Called by setup() before starting the game.
        """
        pass

    @abstractmethod
    def get_save_data(self) -> dict:  
        pass

    def on_game_over(self):         
        pass

    def start_game(self):
        self.setup()
        self.timer.start()

    def stop_game(self):
        self.timer.stop()
        self.on_game_over()
        self.save_session_data()
        self._close_csv()
        pg.quit()
        if callable(self.on_finished):
            self.on_finished()

    def _latest_emg_values(self):
        if callable(self.emg_source):
            values = self.emg_source()
            if values is not None:
                return values

        if self.emg_signal is not None:
            latest = None
            while not self.emg_signal.empty():
                latest = self.emg_signal.get_nowait()
            if latest is not None:
                if isinstance(latest, (list, tuple, np.ndarray)) and len(latest) > 0:
                    first = latest[0]
                    if isinstance(first, (list, tuple, np.ndarray)):
                        return first
                return latest

        return None
    
    def apply_control(self):
        if not self.emg_control:
            self.apply_keyboard_control()
        else:
            latest = self._latest_emg_values()
            if latest is not None:
                self.apply_emg_values(latest)

    def apply_keyboard_control(self):
        pass

    def apply_emg_values(self, values):
        pass

    def should_sample(self) -> bool:
        now = time.time()
        if now - self._last_sample_time >= self._sample_interval:
            self._last_sample_time = now
            return True
        return False
    
    def record_sample(self):
        if not self._recording:
            return
        if self._current_phase_key not in self._phase_samples:
            return
        if not self.should_sample():
            return
        sample = self.get_current_sample()
        self._phase_samples[self._current_phase_key].append(sample)

    def start_recording(self, phases: list):
        self._phase_samples     = {p: [] for p in phases}
        self._recording         = True
        self._trial_start_time  = time.time()
        self._current_phase_key = phases[0]

    def set_phase(self, phase_name: str):
        if phase_name in self._phase_samples:
            self._current_phase_key = phase_name

    def stop_recording(self) -> dict:
        self._recording         = False
        samples                 = self._phase_samples.copy()
        self._phase_samples     = {}
        self._current_phase_key = None
        self._trial_start_time  = None
        return samples
    
    def _build_csv_rows(self, data: dict) -> list:
        data_samples = data.get("data_samples", [])
        if not data_samples:
            return []

        latest = data_samples[-1]

        if "samples" not in latest:
            return []   # ← no samples key = nothing to flatten

        ctx = {k: v for k, v in latest.items() if k != "samples"}
        return [
            {k: {**ctx, **s}.get(k, "") for k in self._csv_fieldnames}
            for s in latest["samples"]
            if isinstance(s, dict)
        ]
    
    def _open_csv(self, fieldnames: list):
        self._csv_fieldnames = fieldnames
        save_dir  = self._get_save_dir()
        filename  = f"{self.game_name()}_{self.session_start.strftime('%Y_%m_%d_%H%M%S')}.csv"
        csv_path  = os.path.join(save_dir, filename)

        self._csv_path   = csv_path
        self._csv_file   = open(csv_path, "w", newline="")
        self._csv_writer = csv.DictWriter(
            self._csv_file, fieldnames=fieldnames, extrasaction="ignore")
        self._csv_writer.writeheader()
        self._csv_file.flush()
        print(f"[{self.game_name()}] CSV → {csv_path}")

    def save_session_data(self):
        results = self.get_save_data()

        rows = self._build_csv_rows(results)
        if rows:
            self._flush_rows_to_csv(rows)

        progress_path = os.path.join(
            os.path.dirname(os.path.abspath(__file__)),
            "..", "data",
            f"{self.game_name()}.json"
        )
        os.makedirs(os.path.dirname(progress_path), exist_ok=True)

        progress = {k: v for k, v in results.items() if k != "data_samples"}
        progress_data = {
            "game":         self.game_name(),
            "timestamp":    self.session_start.isoformat(),
            "num_channels": self.num_channels,
            **progress,
        }
        try:
            with open(progress_path, "w") as f:
                json.dump(progress_data, f, indent=2)
            print(f"[{self.game_name()}] Progress JSON → {progress_path}")
        except Exception as e:
            print(f"[{self.game_name()}] Progress JSON failed: {e}")

    def _get_save_dir(self) -> str:
        date_str = datetime.now().strftime("%Y_%m_%d")

        if self._save_root:
            # ← main app already found the USB, just use it
            folder = os.path.join(self._save_root, date_str)
        else:
            # ← standalone / fallback: detect USB ourselves
            finder   = Ripple_USBFinder(None)
            usb_root = finder.find_usb_drive()
            if usb_root:
                folder = os.path.join(usb_root, "Data", date_str)
            else:
                folder = os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "data", date_str)
                print(f"[BaseGame] No USB → saving locally to {folder}")

        os.makedirs(folder, exist_ok=True)
        return folder

    def _flush_rows_to_csv(self, rows: list):
        if self._csv_writer is None:
            return
        for row in rows:
            self._csv_writer.writerow(row)
        self._csv_file.flush()

    def _close_csv(self):
        if self._csv_file and not self._csv_file.closed:
            self._csv_file.close()
            print(f"[{self.game_name()}] CSV closed.")