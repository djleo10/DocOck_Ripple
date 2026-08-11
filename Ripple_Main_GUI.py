import os
import queue
import sys
import os
import psutil
from datetime import datetime
import pandas as pd
import seaborn as sns
import matplotlib.pyplot as plt
import numpy as np
from scipy.signal import find_peaks
from PyQt5.QtWidgets import (
    QApplication, QMainWindow, QWidget, QVBoxLayout,
    QHBoxLayout, QLabel, QPushButton, QFrame
)
from PyQt5.QtCore import Qt, QTimer, QThread, QPoint, pyqtSignal, QElapsedTimer
from PyQt5.QtGui import QPainter, QPen, QColor, QFont, QPixmap, QPolygon,  QStandardItem, QStandardItemModel, QDoubleValidator
from PyQt5.QtWidgets import QCheckBox, QGridLayout,QGraphicsProxyWidget, QGraphicsScene, QGraphicsView, QLineEdit, QMessageBox, QInputDialog, QComboBox, QTextEdit, QListWidget, QAbstractItemView, QDialog
import pyqtgraph as pqtg

import collections as c

import xipppy as xp

from Ripple_USB_Finder_SUPPORT import Ripple_USBFinder
from Ripple_Signal_Acquisition import RippleController, RippleThread
from Ripple_Signal_Filtering_SUPPORT import SignalProcessor
from Ripple_Settings_SUPPORT  import *


class RippleGUI(QMainWindow):
    status_signal = pyqtSignal(str)
    def __init__(self, active_channels):
        super().__init__()
        self.active_channels = active_channels
        self.num_channels = len(active_channels)
        self.Channel_Names = [f"CH {i+1}" for i in active_channels]
        self.setWindowTitle("Ripple Real-Time Streaming + Stimulation GUI")
        self.setStyleSheet("background-color: black;")
        self.setGeometry(50, 50, 2000, 2000)

        self.central_widget = QWidget()
        self.setCentralWidget(self.central_widget)
        self.main_layout = QHBoxLayout(self.central_widget)

        # Left Panel 
        self.left_widget = QWidget()
        self.left_widget.setStyleSheet("background-color: #A51C30; color: black")
        self.left_widget.setFixedSize(750, 1000)
        self.left_layout = QVBoxLayout(self.left_widget)

        self.Base_path_label = QLabel("Base Path:")
        self.finder   = Ripple_USBFinder("BIONICS_USB", status_callback=None)  # status_box doesn't exist yet
        self.usb_path = self.finder.find_usb_drive()
        self.Base_path_input = QLineEdit(f"BIONICS_USB: {self.usb_path}" if self.usb_path else "USB not found")
        self.Base_path_input.setStyleSheet("background-color: black; color: white")
        self.left_layout.addWidget(self.Base_path_label)
        self.left_layout.addWidget(self.Base_path_input)

        self.today_str = datetime.now().strftime('%Y_%m_%d')
        self.default_filename = f"HBL_DocOck_Ripple_{self.today_str}"

        self.filelabel = QLabel("Filename:")
        self.filename_input = QLineEdit(self.default_filename)
        self.filename_input.setStyleSheet("background-color: black; color: white")
        self.left_layout.addWidget(self.filelabel)
        self.left_layout.addWidget(self.filename_input)

        self.line = QFrame()
        self.line.setFrameShape(QFrame.HLine)
        self.line.setFrameShadow(QFrame.Sunken)
        self.line.setStyleSheet("background-color: black;")
        self.left_layout.addWidget(self.line)

        # Choice Recording/Stimulation:
        self.establish_connection_btn = QPushButton("Connect to Ripple Processor")
        self.establish_connection_btn.clicked.connect(self.Connection_Ripple)
        self.establish_connection_btn.setStyleSheet("background-color: black; color: white")
        self.left_layout.addWidget(self.establish_connection_btn)

        self.choice_label = QLabel("Select Mode:")
        self.choice_label.setStyleSheet("font-size: 18px; font-weight: bold; color: black")
        self.choice_label.setAlignment(Qt.AlignCenter)
        self.left_layout.addWidget(self.choice_label)

        self.choice_layout = QHBoxLayout()
        self.Recording_btn = QPushButton("Recording Mode")
        self.Recording_btn.clicked.connect(self._mode_select)
        self.Recording_btn.setStyleSheet("background-color: black; color: white")

        self.Stimulation_btn = QPushButton("Stimulation Mode")
        self.Stimulation_btn.clicked.connect(self._mode_select)
        self.Stimulation_btn.setStyleSheet("background-color: black; color: white")

        self.choice_layout.addWidget(self.Recording_btn)
        self.choice_layout.addWidget(self.Stimulation_btn)
        self.left_layout.addLayout(self.choice_layout)

        self.Reg_data_Label = QLabel()
        self.Reg_data_Label.setText(" ____ MODE")
        self.Reg_data_Label.setStyleSheet("font-size: 18px; font-weight: bold; color: black")
        self.Reg_data_Label.setAlignment(Qt.AlignCenter)
        self.left_layout.addWidget(self.Reg_data_Label)

        # Stream-type selector. Populated for real from the hardware in
        # Connection_Ripple(); these placeholders only show until then.
        # NOTE: named stream_dropdown, not control_dropdown - the latter is the
        # MVC gesture selector built in _mode_select().
        self.InputSignal_layout = QHBoxLayout()
        self.stream_label = QLabel("Input Stream:")
        self.stream_label.setStyleSheet("color: black")
        self.stream_dropdown = QComboBox()
        self.stream_dropdown.setStyleSheet("background-color: black; color: white")
        self.stream_dropdown.setEnabled(False)
        for canon in STREAM_PREFERENCE:
            self.stream_dropdown.addItem(STREAM_LABELS.get(canon, canon), canon)
        self.InputSignal_layout.addWidget(self.stream_label)
        self.InputSignal_layout.addWidget(self.stream_dropdown)
        self.left_layout.addLayout(self.InputSignal_layout)

        # Slot for the mode panel (calibration + stream buttons), claimed here
        # so _mode_select() fills it ABOVE the status box. Appending straight to
        # left_layout would put those controls below the status box, the game
        # buttons and the logos, since those are added next.
        self.mode_panel_layout = QVBoxLayout()
        self.left_layout.addLayout(self.mode_panel_layout)

        self.status_display()
        self.game_button_display()

        # Logos
        logo1_path = os.path.join("Logo_Assets","Harvard_University_shield.png")
        logo2_path = os.path.join("Logo_Assets","HBL_Logo.png")
        logo3_path = os.path.join("Logo_Assets","RippleLogo.png")
        logo_frame = QFrame()
        logo_layout = QHBoxLayout()
        logo_layout.setAlignment(Qt.AlignCenter)

        logo1 = QLabel()
        logo2 = QLabel()
        logo3 = QLabel()

        logo1.setPixmap(QPixmap(logo1_path).scaled(240, 120, Qt.KeepAspectRatio))
        logo2.setPixmap(QPixmap(logo2_path).scaled(240, 120, Qt.KeepAspectRatio))
        logo3.setPixmap(QPixmap(logo3_path).scaled(240, 120, Qt.KeepAspectRatio))

        logo_layout.addWidget(logo1)
        logo_layout.addWidget(logo2)
        logo_layout.addWidget(logo3)
        logo_frame.setLayout(logo_layout)
        self.left_layout.addWidget(logo_frame)

        # Right Panel 
        self.right_widget = QWidget()
        self.right_widget.setStyleSheet("background-color: black; color: white")
        self.right_layout = QVBoxLayout(self.right_widget)

        self.EMG_IMU_Layout = QVBoxLayout()

        # EMG display
        self.EMG_IMU_Layout.addWidget(self.EMG_Plotting_layout(y_min_range = -2000, y_max_range = 4000), alignment=Qt.AlignCenter)
        self.right_layout.addLayout(self.EMG_IMU_Layout)
        
        self.main_layout.addWidget(self.left_widget)
        self.main_layout.addWidget(self.right_widget)

        # Initializers
        # Built at the placeholder rate; reinitialise_filters() re-designs them
        # at the real stream rate the moment a stream is enabled.
        self.signal_processor = SignalProcessor(num_channels=self.num_channels,
                                                fs=EMG_SAMPLE_RATE)
        self.ripplestream = None      # RippleController, made on connect
        self.stream        = None      # RippleThread, made on connect
        self.emg_control = False

        # Window sizes in SAMPLES at the live rate. Recomputed per stream.
        self.fs_active   = EMG_SAMPLE_RATE
        self.win_rms     = samples_for_ms(WINDOW_MS,   EMG_SAMPLE_RATE)
        self.win_control = samples_for_ms(WIN_SAMP_MS, EMG_SAMPLE_RATE)
        self.baseline_sample_limit = BASELINE_SAMPLE_LIMIT
        self.mvc_sample_limit      = MVC_SAMPLE_LIMIT

        # Per-muscle MVC store. M<i> is captured while contracting the muscle on
        # electrode <i>, and contributes channel i's value to action_mvc.
        self.option_selected_channels = {}
        self.option_mvc_values = {}
        self.full_mvc_values = {}
        self.muscle_names = muscle_names(self.num_channels)
        self.current_gesture = self.muscle_names[0]
        self._mvc_gesture = self.muscle_names[0]   # muscle latched at capture start
        self._baseline_elapsed = QElapsedTimer()
        self._mvc_elapsed = QElapsedTimer()
        self.baseline_mean_data = np.zeros(self.num_channels)
        self.baseline_std_data  = np.zeros(self.num_channels)
        self.action_mvc = np.zeros(self.num_channels)    
        self.filtered_buffers       = [np.zeros(BUFFER_SIZE)] * self.num_channels
        self.smoothed_buffers       = [np.zeros(BUFFER_SIZE)] * self.num_channels
        self.post_processed_buffers = [np.zeros(BUFFER_SIZE)] * self.num_channels
        self.normalized_buffers       = [np.zeros(BUFFER_SIZE)] * self.num_channels

        self.win_metric = []
        # Latest 2-channel control signal (control_signal_calc_v1 tuple) that the
        # games read from. Updated every rt_buffer_processing tick once calibrated.
        self._latest_control_signal = None
        # Continuous per-channel proportional %MVC (0-100) for the bar game.
        self._latest_norm_pct = None
        # Hold a reference to a running game so it isn't garbage-collected while
        # its QTimer drives it inside our Qt event loop.
        self._active_game = None
        self._plot_timer = QTimer()
        self._plot_timer.setInterval(PLOT_TIMER_MS)  # ~30 fps
        self._plot_timer.timeout.connect(self._update_plots)
        self._plot_timer.timeout.connect(self.rt_buffer_processing)
        self._recording_ui_built = False

        # State
        self.pairing         = False
        self.selectedSensor  = None

        self.emg_queue = queue.Queue()

        self._baseline_timer = QTimer()
        self._baseline_timer.setInterval(50)          # poll every 50 ms
        self._baseline_timer.timeout.connect(self._on_baseline_timer_poll)

        self._mvc_timer = QTimer()
        self._mvc_timer.setInterval(50)          # poll every 50 ms
        self._mvc_timer.timeout.connect(self._on_mvc_timer_poll)
        self.calib_done = False

    def Connection_Ripple(self):
        self.ripplestream = RippleController(active_channels=self.active_channels,
                                             status_update=self.status_signal)
        if not self.ripplestream.connect_to_processor():
            self.establish_connection_btn.setStyleSheet("background-color: red; color: white")
            self.log_status("[Connect] No processor. Is Trellis running / the NIP powered?")
            return

        for key, val in self.ripplestream.get_processor_info().items():
            self.log_status(f"{key}: {val}")

        # Map CH 1..N onto the first N detected electrodes, then ask the
        # hardware which streams they all support and offer only those.
        try:
            elecs = self.ripplestream.select_channels(self.num_channels)
        except RuntimeError as e:
            self.establish_connection_btn.setStyleSheet("background-color: red; color: white")
            self.log_status(f"[Connect] {e}")
            return

        # The detected electrode count wins over the requested one.
        self.num_channels = self.ripplestream.num_channels
        self.signal_processor.reinitialise_filters(num_channels=self.num_channels)
        self.baseline_mean_data = np.zeros(self.num_channels)
        self.baseline_std_data  = np.zeros(self.num_channels)
        self.action_mvc         = np.zeros(self.num_channels)
        # M1..Mn follow the electrodes that were actually detected.
        self._rebuild_muscle_options()
        self.log_status(f"[MVC] muscles: "
                        + ", ".join(f"{m}->e{e}" for m, e in
                                    zip(self.muscle_names, elecs)))

        self.Channel_Names = [f"CH {i+1} (e{e})" for i, e in enumerate(elecs)]
        for i, lbl in enumerate(self.channel_labels):
            lbl.setText(self.Channel_Names[i] if i < len(self.Channel_Names) else "")
            lbl.setVisible(i < self.num_channels)
            self.graph_widgets[i].setVisible(i < self.num_channels)

        streams = self.ripplestream.available_streams()
        self.stream_dropdown.clear()
        for canon in streams:
            self.stream_dropdown.addItem(STREAM_LABELS.get(canon, canon), canon)
        if streams:
            self.stream_dropdown.setEnabled(True)
        else:
            self.log_status("[Connect] No readable streams common to the selected electrodes.")

        self.stream = RippleThread(self.ripplestream)
        self.stream.status_update.connect(self.log_status)

        self.establish_connection_btn.setStyleSheet("background-color: green; color: black")

    # Recording/Stimulation Mode:
    def _mode_select(self):
        sender = self.sender()

        if sender == self.Stimulation_btn:
            self.Stimulation_btn.setStyleSheet("background-color: green; color: black")
            self.Recording_btn.setStyleSheet("background-color: black; color: white")
            self.Reg_data_Label.setText("STIMULATION")
            self.Reg_data_Label.setStyleSheet("font-size: 18px; font-weight: bold; color: black")
            self.Reg_data_Label.setAlignment(Qt.AlignCenter)

        elif sender == self.Recording_btn:
            self.Recording_btn.setStyleSheet("background-color: green; color: black")
            self.Stimulation_btn.setStyleSheet("background-color: black; color: white")
            self.Reg_data_Label.setText("RECORDING")
            self.Reg_data_Label.setStyleSheet("font-size: 18px; font-weight: bold; color: black")
            self.Reg_data_Label.setAlignment(Qt.AlignCenter)

            # Build the recording controls once - re-clicking the button used to
            # stack a fresh copy of every widget into left_layout.
            if self._recording_ui_built:
                return
            self._recording_ui_built = True

            # Muscle selector - M<i> is the muscle on electrode <i>. Each gets
            # its own 3 s MVC trial, and contributes channel i's value.
            self.gesture_layout = QHBoxLayout()
            self.gesture_label = QLabel("MVC Muscle:")
            self.gesture_label.setStyleSheet("color: black")
            self.control_dropdown = QComboBox()
            self.control_dropdown.setStyleSheet("background-color: black; color: white")
            for option in self.muscle_names:
                self.control_dropdown.addItem(option)
                self.option_selected_channels[option] = self.muscle_channel(option) or 0
                self.option_mvc_values.setdefault(option, [0.0] * self.num_channels)

            self.add_option_button = QPushButton("+")
            self.add_option_button.setFixedWidth(30)
            self.add_option_button.setStyleSheet("background-color: black; color: white")
            self.add_option_button.clicked.connect(self.add_new_option)
            self.control_dropdown.currentTextChanged.connect(self.on_dropdown_changed)

            self.gesture_layout.addWidget(self.gesture_label)
            self.gesture_layout.addWidget(self.control_dropdown)
            self.gesture_layout.addWidget(self.add_option_button)
            self.mode_panel_layout.addLayout(self.gesture_layout)

            self.same_mvc_checkbox = QCheckBox(
                "Use the selected muscle's MVC for all muscles")
            self.same_mvc_checkbox.setStyleSheet("color: black")
            self.same_mvc_checkbox.stateChanged.connect(self.on_same_mvc_checkbox_changed)
            self.mode_panel_layout.addWidget(self.same_mvc_checkbox)

            self.mvc_display = QLabel(f"MVC [{self.current_gesture}]:\nnot calibrated")
            self.mvc_display.setStyleSheet("color: black")
            self.mode_panel_layout.addWidget(self.mvc_display)

            self.calib_layout = QHBoxLayout()
            self.baseline_btn = QPushButton("BASELINE")
            self.baseline_btn.clicked.connect(self._baseline_collect)
            self.baseline_btn.setStyleSheet("background-color: black; color: white")

            self.MVC_btn = QPushButton("MVC")
            self.MVC_btn.clicked.connect(self._MVC_collect)
            self.MVC_btn.setStyleSheet("background-color: black; color: white")

            self.calib_layout.addWidget(self.baseline_btn)
            self.calib_layout.addWidget(self.MVC_btn)
            self.mode_panel_layout.addLayout(self.calib_layout)

            self.button_layout = QHBoxLayout()
            self.start_btn = QPushButton("Start Stream")
            self.start_btn.clicked.connect(self._start_streaming)
            self.start_btn.setStyleSheet("background-color: black; color: white")
            self.button_layout.addWidget(self.start_btn)

            self.stop_btn = QPushButton("Stop Stream")
            self.stop_btn.clicked.connect(self._stop_streaming)
            self.stop_btn.setStyleSheet("background-color: black; color: white")
            self.button_layout.addWidget(self.stop_btn)

            self.mode_panel_layout.addLayout(self.button_layout)
    
            self.Goodtogo_label = QLabel("Ready to use the device !!!")
            self.Goodtogo_label.setStyleSheet("font-size: 14px; font-weight: bold; color: Green")
            self.Goodtogo_label.setAlignment(Qt.AlignCenter)
            self.Goodtogo_label.setVisible(False)
            self.mode_panel_layout.addWidget(self.Goodtogo_label)
    
            self.save_layout = QHBoxLayout()
            self.save_emg_btn = QPushButton("SAVE EMG")
            self.save_emg_btn.clicked.connect(self._save_emg_data)
            self.save_emg_btn.setStyleSheet("background-color: black; color: white")
            self.save_layout.addWidget(self.save_emg_btn)
    
            self.mode_panel_layout.addLayout(self.save_layout)

    # Muscles / MVC options >>>
    def muscle_channel(self, name):
        """Channel index a muscle name maps to: M1 -> 0, M2 -> 1, ... else None."""
        if not name.startswith(MUSCLE_PREFIX):
            return None
        try:
            idx = int(name[len(MUSCLE_PREFIX):]) - 1
        except ValueError:
            return None
        return idx if 0 <= idx < self.num_channels else None

    def _rebuild_muscle_options(self):
        """
        Re-derive M1..Mn from the channel count (electrodes are only known after
        connecting). Extra names added with '+' are preserved.
        """
        self.muscle_names = muscle_names(self.num_channels)
        extras = [g for g in self.option_mvc_values if g not in self.muscle_names]

        new_values = {}
        for name in self.muscle_names + extras:
            new_values[name] = [0.0] * self.num_channels
            self.option_selected_channels.setdefault(name, self.muscle_channel(name) or 0)
        self.option_mvc_values = new_values
        self.full_mvc_values = {}

        if getattr(self, "control_dropdown", None) is not None:
            self.control_dropdown.blockSignals(True)
            self.control_dropdown.clear()
            for name in self.muscle_names + extras:
                self.control_dropdown.addItem(name)
            self.control_dropdown.blockSignals(False)
            self.current_gesture = self.control_dropdown.currentText() or self.muscle_names[0]
            self._refresh_mvc_display()

    def _compose_action_mvc(self):
        """
        Assemble the normalization vector from each muscle's own trial:
        action_mvc[i] comes from M<i+1>'s capture, at channel i.

        With 'use same MVC' ticked every option holds the same vector, so this
        naturally collapses to that shared vector.
        """
        composed = np.zeros(self.num_channels)
        for name, vals in self.option_mvc_values.items():
            ch = self.muscle_channel(name)
            if ch is None or ch >= len(vals):
                continue
            composed[ch] = float(vals[ch])
        self.action_mvc = composed
        return composed

    def _mvc_is_done(self, name):
        """A muscle counts as calibrated when its own channel has a value."""
        vals = self.option_mvc_values.get(name)
        if not vals:
            return False
        ch = self.muscle_channel(name)
        return bool(vals[ch]) if ch is not None and ch < len(vals) else any(vals)

    def _refresh_mvc_display(self):
        """Keep the MVC label and button text in step with the selection."""
        name = self.current_gesture
        vals = self.option_mvc_values.get(name, [])
        if getattr(self, "mvc_display", None) is not None:
            if self._mvc_is_done(name):
                ch = self.muscle_channel(name)
                own = f"  (ch {ch + 1} = {vals[ch]:.3f})" if ch is not None else ""
                self.mvc_display.setText(
                    f"MVC [{name}]:\n" + ", ".join(f"{v:.3f}" for v in vals) + own)
            else:
                self.mvc_display.setText(f"MVC [{name}]:\nnot calibrated")

        if getattr(self, "MVC_btn", None) is not None and self.MVC_btn.isEnabled():
            self.MVC_btn.setText(f"MVC [{name}] DONE" if self._mvc_is_done(name)
                                 else f"MVC [{name}]")

    def _mvc_progress_summary(self):
        done = [m for m in self.muscle_names if self._mvc_is_done(m)]
        todo = [m for m in self.muscle_names if m not in done]
        return done, todo

    # Add widgets and options>>>
    def add_new_option(self):
        text, ok = QInputDialog.getText(self, "Add New Option", "Enter new option:")
        if ok and text.strip():
            option_name = text.strip()
            if self.control_dropdown.findText(option_name) == -1:
                self.control_dropdown.addItem(option_name)
                self.option_selected_channels[option_name] = 0
                # MVC arrays span every streamed channel.
                self.option_mvc_values[option_name] = [0.0] * self.num_channels
                self.option_selected_channels[option_name] = 0
                self.log_status(
                    f"Added new option: {option_name} (note: only M1..M"
                    f"{self.num_channels} map to channels and feed normalization)")
                self.control_dropdown.setCurrentText(option_name)
            else:
                self.log_status(f"Option '{option_name}' already exists")

    def on_dropdown_changed(self, text):
        """
        Selecting a muscle only changes which one the next MVC capture is for.
        action_mvc is the composite across all muscles, so it does not change
        here - every channel keeps the value from its own trial.
        """
        if not text:
            return
        self.current_gesture = text
        self._refresh_mvc_display()
        self._refresh_calibration_state()

    def on_same_mvc_checkbox_changed(self, state):
        """
        Ticked: take the currently selected muscle's MVC and use it for every
        muscle, so all channels normalize against that one trial.
        Unticked: nothing is restored automatically - re-run the muscles you
        want back on their own values.
        """
        if state == Qt.Checked:
            current = self.current_gesture
            vals = self.option_mvc_values.get(current)
            if not (vals and any(vals)):
                self.log_status(
                    f"[MVC] '{current}' is not calibrated yet - nothing to copy. "
                    f"Run its MVC first, then tick the box.")
                self.same_mvc_checkbox.blockSignals(True)
                self.same_mvc_checkbox.setChecked(False)
                self.same_mvc_checkbox.blockSignals(False)
                return
            for option in self.option_mvc_values:
                self.option_mvc_values[option] = list(vals)
            self.log_status(f"[MVC] Applied '{current}' MVC {np.round(vals, 3)} "
                            f"to all muscles.")

            # Only the selected muscle's own channel was maximally contracted in
            # that trial; the other channels hold its crosstalk. Say which ones
            # have little headroom over baseline, since those traces will run
            # well past 1.0 on a real contraction.
            own = self.muscle_channel(current)
            base = self.baseline_mean_data + self.baseline_std_data
            thin = []
            for ch in range(min(len(vals), self.num_channels)):
                if ch == own or not np.any(base):
                    continue
                headroom = (vals[ch] - base[ch]) / max(base[ch], 1e-9)
                if headroom < 2.0:
                    name = self.Channel_Names[ch] if ch < len(self.Channel_Names) else f"CH {ch+1}"
                    thin.append(f"{name} ({vals[ch]:.1f} vs baseline {base[ch]:.1f})")
            if thin:
                self.log_status(
                    f"[WARN] '{current}' only maximally contracted channel "
                    f"{(own or 0) + 1}; these channels are now normalized against "
                    f"its crosstalk and will read well above 1.0: {thin}. "
                    f"Untick and run their own MVC for per-channel scaling.")
        else:
            self.log_status("[MVC] Same-MVC unticked - each muscle uses its own "
                            "trial again (re-run any you want to change).")

        self._compose_action_mvc()
        self._refresh_mvc_display()
        self._refresh_calibration_state()

    def _refresh_calibration_state(self):
        """calib_done drives normalized plotting and the control-signal path."""
        has_baseline = bool(np.any(self.baseline_mean_data))
        # EVERY channel needs an MVC - normalization divides per channel, so one
        # uncalibrated channel would divide by ~0 and blow that trace up.
        has_mvc = bool(np.all(self.action_mvc > 0)) if self.action_mvc.size else False
        was_done = self.calib_done
        self.calib_done = has_baseline and has_mvc
        self.emg_control = self.calib_done and self.running

        if self.calib_done and not was_done:
            for gw in self.graph_widgets:
                gw.disableAutoRange(axis='y')
                gw.setYRange(NORM_Y_MIN, NORM_Y_MAX)
            self.log_status("[Calib] Normalization active - plots now show 0-1 %MVC.")
        elif not self.calib_done and was_done:
            for gw in self.graph_widgets:
                gw.enableAutoRange(axis='y')

    def status_display(self):
        # State Display:
        self.status_layout = QVBoxLayout() 
        self.status_label = QLabel("Status")
        self.status_box = QTextEdit()
        self.status_box.setReadOnly(True)
        self.status_box.setStyleSheet("background-color: #1e1e1e; color: white;")
        self.status_box.setPlaceholderText("Status output will appear here...")
        self.status_layout.addWidget(self.status_label)
        self.status_layout.addWidget(self.status_box)
        self.left_layout.addLayout(self.status_layout)
        self.finder.status_callback = self.log_status
        self.status_signal.connect(self.log_status)

    def game_button_display(self):
        # Game Layout:
        self.line = QFrame()
        self.line.setFrameShape(QFrame.HLine)
        self.line.setFrameShadow(QFrame.Sunken)
        self.line.setStyleSheet("background-color: black;")
        self.left_layout.addWidget(self.line)

        self.Game_Label = QLabel()
        self.Game_Label.setText("GAMES")
        self.Game_Label.setStyleSheet("font-size: 18px; font-weight: bold; color: black")
        self.Game_Label.setAlignment(Qt.AlignCenter)
        self.left_layout.addWidget(self.Game_Label)

        self.bargame_btn = QPushButton("Bar Game")
        self.bargame_btn.clicked.connect(self.bargame_v2)
        self.bargame_btn.setStyleSheet("background-color: black; color: white")
        self.left_layout.addWidget(self.bargame_btn)

        self.blockgame_btn = QPushButton("Block Game")
        self.blockgame_btn.clicked.connect(self.blockgame_v1)
        self.blockgame_btn.setStyleSheet("background-color: black; color: white")
        self.left_layout.addWidget(self.blockgame_btn)

        self.cursorgame_btn = QPushButton("Cursor Game")
        self.cursorgame_btn.clicked.connect(self.cursorgame_v1)
        self.cursorgame_btn.setStyleSheet("background-color: black; color: white")
        self.left_layout.addWidget(self.cursorgame_btn)

        self.spacegame_btn = QPushButton("Space Game")
        self.spacegame_btn.clicked.connect(self.spacegame)
        self.spacegame_btn.setStyleSheet("background-color: black; color: white")
        self.left_layout.addWidget(self.spacegame_btn)

        self.jetpackgame_btn = QPushButton("Jetpack Game")
        self.jetpackgame_btn.clicked.connect(self.jetpackgame)
        self.jetpackgame_btn.setStyleSheet("background-color: black; color: white")
        self.left_layout.addWidget(self.jetpackgame_btn)


            
    # log_status:
    def log_status(self, message: str):
        self.status_box.append(str(message))

    # EMG Widget:
    def EMG_Plotting_layout(self, y_min_range=-2000, y_max_range=4000):
        self.emg_widget = QWidget()
        self.emg_layout = QGraphicsScene()
        self.emg_view   = QGraphicsView(self.emg_layout, self.emg_widget)
        self.emg_view.setStyleSheet("background-color: black; border: none;")

        self.graph_widgets = []
        self.data_lines    = []
        self.graph_proxies = []
        self.label_proxies = []
        self.channel_labels = []
        self._baseline_was_streaming = False
        self._mvc_was_streaming = False
        self.running = False

        for ch in range(self.num_channels):
            gw = pqtg.PlotWidget()
            gw.setFrameStyle(0)
            gw.setBackground('k')
            # Raw Ripple counts have no fixed range we can assume ahead of the
            # front end reporting in, so let Y follow the data.
            gw.enableAutoRange(axis='y')
            gw.setXRange(0, BUFFER_SIZE)
            gw.setFixedSize(GRAPH_W, GRAPH_H)
            pen  = pqtg.mkPen(color=CHANNEL_COLORS[ch % len(CHANNEL_COLORS)], width=2)
            line = gw.plot(pen=pen)
            # 30 kHz raw is ~60k points per window; draw the envelope instead.
            line.setDownsampling(auto=True, method='peak')
            line.setClipToView(True)
            self.graph_widgets.append(gw)
            self.data_lines.append(line)

            y = ch * (GRAPH_H + ROW_SPACING)

            proxy = QGraphicsProxyWidget()
            proxy.setWidget(gw)
            proxy.setPos(LEFT_MARGIN, y)
            self.emg_layout.addItem(proxy)
            self.graph_proxies.append(proxy)

            lbl = QLabel(self.Channel_Names[ch])
            lbl.setAlignment(Qt.AlignRight | Qt.AlignVCenter)
            lbl.setFixedSize(LABEL_W, GRAPH_H)
            lbl.setStyleSheet("color: white; background-color: transparent;")
            plbl = QGraphicsProxyWidget()
            plbl.setWidget(lbl)
            plbl.setPos(0, y)
            self.emg_layout.addItem(plbl)
            self.label_proxies.append(plbl)
            self.channel_labels.append(lbl)

        return self.emg_view

    def _ensure_streaming(self, tag):
        """Calibration needs samples flowing; start the stream if it isn't."""
        if self.ripplestream is None:
            self.log_status(f"[{tag}] Connect to the processor first.")
            return False
        if not self.running:
            self._start_streaming()
        if not self.running:
            self.log_status(f"[{tag}] Could not start the stream.")
            return False
        return True

    # Calibration (baseline)>>>
    #
    # Both captures are fixed-duration and stop themselves: a short settle
    # period during which nothing is kept, then exactly BASELINE/MVC_DURATION_MS
    # of collection. The elapsed clock is the sole authority for stopping -
    # sample count is reported afterwards and only used to warn if the stream
    # under-delivered, so a slow or stalled stream can never silently shorten
    # or extend a capture.
    def _baseline_collect(self):
        if not self._ensure_streaming("Baseline"):
            return
        if self.ripplestream.calib_mode is not None:
            self.log_status("[Baseline] A calibration capture is already running.")
            return

        self.baseline_btn.setEnabled(False)
        self.MVC_btn.setEnabled(False)
        self.baseline_btn.setStyleSheet("background-color: #4DB848; color: white")
        self.baseline_btn.setText("BASELINE… settling")

        self._baseline_was_streaming = True
        QTimer.singleShot(CALIB_SETTLE_MS, self._begin_baseline)

    def _begin_baseline(self):
        """Settle period over - start the 3 s capture."""
        if self.ripplestream is None:
            return
        # Discard anything caught during settling; the capture starts now.
        self.ripplestream.calib_baseline = []
        self.ripplestream.calib_mode = "baseline"
        self._baseline_elapsed = QElapsedTimer()
        self._baseline_elapsed.start()
        self._baseline_timer.start()
        QTimer.singleShot(BASELINE_DURATION_MS, self._finish_baseline)

    def _on_baseline_timer_poll(self):
        """Progress readout only - the elapsed clock decides when to stop."""
        pct = int(self._baseline_elapsed.elapsed() / BASELINE_DURATION_MS * 100)
        self.baseline_btn.setText(f"BASELINE… {min(pct, 100)}%")

    def _report_capture(self, tag, n_samples, expected, duration_ms):
        """Warn when a fixed-duration capture under-delivered samples."""
        self.status_box.append(
            f"[{tag}] captured {n_samples} samples in "
            f"{duration_ms/1000:.0f}s (expected ~{expected} at "
            f"{self.fs_active} Hz)")
        if expected and n_samples < 0.8 * expected:
            self.status_box.append(
                f"[WARN] {tag} collected only {100*n_samples/expected:.0f}% of the "
                f"expected samples - the stream is not keeping up. Check the "
                f"resync count in the status log before trusting this calibration.")

    def _finish_baseline(self):
        if self.ripplestream is None or self.ripplestream.calib_mode != "baseline":
            return   # already finished
        self.ripplestream.calib_mode = None
        self._baseline_timer.stop()

        n_samples = len(self.ripplestream.calib_baseline)

        # A calibration capture is self-contained: it started the stream, so it
        # stops it too. Stop BEFORE processing so no further samples land in the
        # log while the 3 s window is being analysed.
        self._stop_streaming()
        self.status_box.append("[Baseline] 3 s capture complete - streaming stopped.")

        ok = False
        try:
            array = self._build_emg_array("baseline")
            if array is not None:
                self._report_capture("Baseline", n_samples, self.baseline_sample_limit,
                                     BASELINE_DURATION_MS)
                self.baseline_calculation(array)
                ok = True
            else:
                self.status_box.append("[Baseline] No data collected.")
        except Exception as exc:
            import traceback
            self.status_box.append(f"[Baseline] finish/calculation error: {exc}")
            traceback.print_exc()
        finally:
            # Always reset the button, even on error, so it never sticks at "…".
            self.baseline_btn.setEnabled(True)
            self.baseline_btn.setStyleSheet("background-color: black; color: white")
            self.baseline_btn.setText("BASELINE [DONE]" if ok else "BASELINE [FAILED]")
            self.MVC_btn.setEnabled(True)
            self._refresh_mvc_display()
            self._maybe_enable_start()

    # Calibration (MVC)>>>

    def get_emg_data(self):
        if not self.post_processed_buffers:
            return None
        result = []
        for i in range(len(self.post_processed_buffers)):
            chunk = self.post_processed_buffers[i][-self.win_control:]
            if len(chunk) > 0:
                result.append(float(np.mean(chunk)))
            else:
                result.append(0.0)
        return result

    # --- Game EMG sources (fed from control_signal_calc_v1's latest output) ---
    # control_signal_calc_v1 returns a tuple; index 2 == data_packet ([ch0%, ch1%]),
    # index 4 == chan_send (0 -> ch0 dominant, 1 -> ch1 dominant, else no drive).
    def _emg_source_bar(self):
        """BarGame source: proportional control. Each bar's height = that
        channel's continuous normalized %MVC (0-100), independent of the
        chan_send dominance gating. chan_send only selects the target bar."""
        return self._latest_norm_pct  # None until the first calibrated tick

    def _emg_source_box(self):
        """BoxDropGame source: [data_packet, chan_send]. chan_send 0 -> LEFT,
        1 -> RIGHT; data_packet magnitude sets the movement strength."""
        cs = self._latest_control_signal
        if cs is None:
            return None
        return [[float(v) for v in cs[2]], cs[4]]

    def _MVC_collect(self):
        """One fixed 3 s capture for the gesture currently selected."""
        if not self._ensure_streaming("MVC"):
            return
        if self.ripplestream.calib_mode is not None:
            self.log_status("[MVC] A calibration capture is already running.")
            return

        # Latch the gesture at the start so switching the dropdown mid-capture
        # can't file the result under the wrong name.
        self._mvc_gesture = self.control_dropdown.currentText()
        self.MVC_btn.setEnabled(False)
        self.baseline_btn.setEnabled(False)
        self.MVC_btn.setStyleSheet("background-color: #4DB848; color: white")
        self.MVC_btn.setText(f"MVC [{self._mvc_gesture}]… settling")

        self._mvc_was_streaming = True
        QTimer.singleShot(CALIB_SETTLE_MS, self._begin_mvc)

    def _begin_mvc(self):
        """Settle period over - start the 3 s capture."""
        if self.ripplestream is None:
            return
        self.ripplestream.calib_mvc = []
        self.ripplestream.calib_mode = "mvc"
        self._mvc_elapsed = QElapsedTimer()
        self._mvc_elapsed.start()
        self._mvc_timer.start()
        QTimer.singleShot(MVC_DURATION_MS, self._finish_mvc)

    def _on_mvc_timer_poll(self):
        """Progress readout only - the elapsed clock decides when to stop."""
        pct = int(self._mvc_elapsed.elapsed() / MVC_DURATION_MS * 100)
        self.MVC_btn.setText(f"MVC [{self._mvc_gesture}]… {min(pct, 100)}%")

    def _finish_mvc(self):
        if self.ripplestream is None or self.ripplestream.calib_mode != "mvc":
            return   # already finished
        self.ripplestream.calib_mode = None
        self._mvc_timer.stop()

        n_samples = len(self.ripplestream.calib_mvc)
        muscle = self._mvc_gesture

        # Same contract as baseline: each muscle's 3 s capture stops the stream
        # when it finishes, so the subject can relax between muscles.
        self._stop_streaming()
        self.status_box.append(
            f"[MVC:{muscle}] 3 s capture complete - streaming stopped.")

        try:
            array = self._build_emg_array("mvc")
            if array is not None:
                self._report_capture(f"MVC:{muscle}", n_samples,
                                     self.mvc_sample_limit, MVC_DURATION_MS)
                # File under the muscle latched at capture start.
                self.mvc_calculation(array, gesture=muscle)
            else:
                self.status_box.append(f"[MVC] No data collected for '{muscle}'.")
        except Exception as exc:
            import traceback
            self.status_box.append(f"[MVC] finish/calculation error: {exc}")
            traceback.print_exc()
        finally:
            # Always reset the button, even on error, so MVC never sticks at "…%".
            self.MVC_btn.setEnabled(True)
            self.MVC_btn.setStyleSheet("background-color: black; color: white")
            self.MVC_btn.setText(f"MVC [{muscle}] DONE" if self._mvc_is_done(muscle)
                                 else f"MVC [{muscle}] FAILED")
            self.baseline_btn.setEnabled(True)

            done, todo = self._mvc_progress_summary()
            self.status_box.append(
                f"[MVC] calibrated: {done or 'none'}"
                + (f" | remaining: {todo}" if todo else " | all muscles done"))
            self._maybe_enable_start()

    def _maybe_enable_start(self):
        have_baseline = bool(np.any(self.baseline_mean_data))
        # Every channel needs its own muscle's MVC before normalization is valid.
        have_mvc = bool(np.all(self.action_mvc > 0)) if self.action_mvc.size else False
        if have_baseline and not have_mvc:
            _, todo = self._mvc_progress_summary()
            if todo:
                self.status_box.append(
                    f"[Calib] baseline done - still need MVC for: {todo} "
                    f"(or tick 'use the selected muscle's MVC for all muscles')")
        if have_baseline and have_mvc:
            self.start_btn.setEnabled(True)
            self.start_btn.setStyleSheet("background-color: black; color: white")
            self.stop_btn.setEnabled(True)
            self.stop_btn.setStyleSheet("background-color: black; color: white")

            self._refresh_calibration_state()

            # Sanity check: normalization ((sig - base) / (mvc - base)) can only
            # land in 0-1 when MVC is genuinely above the resting baseline. If it
            # isn't, warn loudly instead of silently plotting exploded values.
            base = self.baseline_mean_data + self.baseline_std_data
            bad = [self.Channel_Names[i] for i in range(self.num_channels)
                   if self.action_mvc[i] <= base[i]]
            if bad:
                self.status_box.append(
                    f"[WARN] MVC <= baseline on {bad}: "
                    f"MVC={np.round(self.action_mvc, 3)} vs baseline+std={np.round(base, 3)}. "
                    f"Normalized output will NOT be 0-1. Re-run MVC with a stronger "
                    f"contraction, and check electrode contact / shared ground."
                )
            else:
                self.status_box.append("[OK] MVC > baseline on all channels; normalization is valid.")

    def baseline_calculation(self, baseline_array):
        data = baseline_array
        n_ch = self.num_channels

        self.baseline_mean_data = np.zeros(n_ch)
        self.baseline_std_data  = np.zeros(n_ch)

        for ch in range(n_ch):
            raw            = data[:, ch + 2]
            filtered       = self.signal_processor.preprocess_filters_offline(raw, ch)
            preprocessed   = self.signal_processor.rectify_emg(filtered)
            smoothed       = self.signal_processor.moving_window_rms(preprocessed, window_size=self.win_rms)
            post_processed = self.signal_processor.postprocess_filter_offline(smoothed, ch)
            self.baseline_mean_data[ch] = np.mean(post_processed)
            self.baseline_std_data[ch]  = np.std(post_processed)

        # mean_str = np.array2string(self.baseline_mean_data, separator=", ", max_line_width=np.inf)[1:-1]
        # std_str  = np.array2string(self.baseline_std_data,  separator=", ", max_line_width=np.inf)[1:-1]
        # self.Baseline_input.setText(f"mean = {mean_str}\nstd = {std_str}")
        self.status_box.append(f"50 samp Baseline:{post_processed[:50]}")
        self.status_box.append(f"Baseline Mean: {self.baseline_mean_data}")
        self.status_box.append(f"Baseline Std:  {self.baseline_std_data}")
        # This mean+std value is the actual resting threshold used for normalization.
        self.status_box.append(f"Baseline (mean+std) -> used for normalization: "
                               f"{np.round(self.baseline_mean_data + self.baseline_std_data, 4)}")

    def mvc_calculation(self, mvc_array, gesture=None):
        gesture = gesture or self.current_gesture
        self.full_mvc_values[gesture] = mvc_array
        n_ch = mvc_array.shape[1] - 2
        action_mvc = np.zeros(n_ch)

        for ch in range(n_ch):
            raw            = mvc_array[:, ch + 2]
            filtered       = self.signal_processor.preprocess_filters_offline(raw, ch)
            rectified      = self.signal_processor.rectify_emg(filtered)
            smoothed       = self.signal_processor.moving_window_rms(rectified, window_size=self.win_rms)
            post_processed = self.signal_processor.postprocess_filter_offline(smoothed, ch)

            if len(post_processed) > 0:
                peaks, _ = find_peaks(post_processed, height=0)
                action_mvc[ch] = (float(np.max(post_processed[peaks]))
                                if len(peaks) > 0 else float(np.max(post_processed)))

        self.option_mvc_values[gesture] = action_mvc.tolist()

        # Ticked box: this trial becomes the MVC for every muscle.
        if getattr(self, "same_mvc_checkbox", None) is not None \
                and self.same_mvc_checkbox.isChecked():
            for option in self.option_mvc_values:
                self.option_mvc_values[option] = action_mvc.tolist()
            self.status_box.append(
                f"[MVC] same-MVC is on - '{gesture}' applied to all muscles.")

        # action_mvc[i] comes from M<i+1>'s own trial.
        composed = self._compose_action_mvc()
        self._refresh_mvc_display()

        ch = self.muscle_channel(gesture)
        own = f" | contributes ch {ch + 1} = {action_mvc[ch]:.3f}" if ch is not None else ""
        self.status_box.append(f"[MVC][{gesture}] Peak amplitude : {action_mvc}{own}")
        self.status_box.append(f"[MVC] action_mvc (per channel) : {np.round(composed, 3)}")

    def _apply_sample_rate(self, fs):
        """
        Re-point every rate-dependent quantity at the live stream rate:
        filter coefficients, the RMS/control window lengths, and how many
        samples a 3 s calibration capture needs.
        """
        if not fs or fs == self.fs_active:
            return

        # Baseline/MVC are amplitudes out of a filter chain designed at a
        # specific rate. Mixing a 2 kHz baseline with a 30 kHz MVC would produce
        # a normalization that looks fine and is meaningless, so a rate change
        # invalidates whatever has been calibrated so far.
        had_calib = bool(np.any(self.baseline_mean_data)) or \
            any(any(v) for v in self.option_mvc_values.values())
        if had_calib:
            self.baseline_mean_data = np.zeros(self.num_channels)
            self.baseline_std_data  = np.zeros(self.num_channels)
            self.action_mvc         = np.zeros(self.num_channels)
            for g in list(self.option_mvc_values):
                self.option_mvc_values[g] = [0.0] * self.num_channels
            self.log_status(
                f"[WARN] Stream rate changed {self.fs_active} -> {fs} Hz. "
                f"Baseline and all gesture MVCs have been cleared - they are "
                f"only valid for the rate they were captured at. Re-run them.")
            if getattr(self, "baseline_btn", None) is not None:
                self.baseline_btn.setText("BASELINE")
                self.baseline_btn.setStyleSheet("background-color: black; color: white")
            self._refresh_mvc_display()
            self._refresh_calibration_state()

        self.fs_active = fs

        self.signal_processor.reinitialise_filters(fs=fs,
                                                   num_channels=self.num_channels)
        self.win_rms     = samples_for_ms(WINDOW_MS,   fs)
        self.win_control = samples_for_ms(WIN_SAMP_MS, fs)
        self.baseline_sample_limit = samples_for_ms(BASELINE_DURATION_MS, fs)
        self.mvc_sample_limit      = samples_for_ms(MVC_DURATION_MS, fs)

        self.log_status(
            f"[Filters] re-designed at {fs} Hz | RMS window {self.win_rms} samp "
            f"({WINDOW_MS:.0f} ms) | control window {self.win_control} samp "
            f"({WIN_SAMP_MS:.0f} ms) | calib target {self.baseline_sample_limit} samp")

    def _start_streaming(self):
        if self.stream is None or self.ripplestream is None:
            self.log_status("[Stream] Connect to the processor first.")
            return
        if self.running:
            return

        stream_name = self.stream_dropdown.currentData()
        if stream_name is None:
            self.log_status("[Stream] No stream type selected.")
            return

        # Selecting the signal on the NIP is what actually starts data flowing;
        # do it here so the dropdown can be changed between runs.
        if not self.ripplestream.enable_stream(stream_name):
            self.start_btn.setStyleSheet("background-color: red; color: white")
            return

        # Buffer length is stream-dependent (2 s of data), so the x-axis has to
        # follow whichever stream was just enabled.
        for gw in self.graph_widgets:
            gw.setXRange(0, self.ripplestream.buffer_len)

        # Re-design the filters at the stream's ACTUAL rate and re-derive every
        # window from its duration. A 10 Hz highpass and a 50 ms RMS window mean
        # different coefficients/sample counts at 2 k vs 30 kHz.
        self._apply_sample_rate(self.ripplestream.sample_rate)

        self.running = True
        # Games only make sense on normalized data, so EMG control follows
        # calibration rather than merely "streaming".
        self.emg_control = self.calib_done
        self.ripplestream.calib_mode = None
        self.stream.calib_mode = None
        self.stream.start()
        self._plot_timer.start()
        self.start_btn.setStyleSheet("background-color: #4DB848; color: white")
        self.stop_btn.setStyleSheet("background-color: black; color: white")
        self.stream_dropdown.setEnabled(False)
        self.Goodtogo_label.setVisible(True)

    def _stop_streaming(self):
        if not self.running:
            return
        self.running = False
        self.emg_control = False
        self._plot_timer.stop()
        self._baseline_timer.stop()
        self._mvc_timer.stop()
        if self.stream is not None:
            self.stream.stop()
        if self.ripplestream is not None:
            self.ripplestream.calib_mode = None
            self.ripplestream.disable_stream()

        self.stop_btn.setStyleSheet("background-color: red; color: white")
        self.start_btn.setStyleSheet("background-color: black; color: white")
        self.stream_dropdown.setEnabled(True)
        self.Goodtogo_label.setVisible(False)

    # SAVING DATA>>>>
    def _build_emg_array(self, mode: str):
        """Build (N, n_ch+2) array from baseline, mvc, or full-session logs."""
        if self.ripplestream is None:
            return None

        source = {
            "baseline": self.ripplestream.calib_baseline,
            "mvc":      self.ripplestream.calib_mvc,
            "data":     self.ripplestream.Entire_Signal,
        }.get(mode)

        if not source:
            return None

        time         = np.array([t[0] for t in source])
        timestamp_us = np.array([t[1] for t in source])
        emg_data     = np.array([t[2] for t in source])
        return np.column_stack([time, timestamp_us, emg_data])
        
    def _resolve_save_root(self):
        """
        Looks for the BIONICS_USB drive and saves there if found; otherwise
        falls back to a local "Data" folder (mirrors the fallback behavior
        in Ripple_USB_Finder_SUPPORT.py's __main__ block).
        """
        self.usb_path = self.finder.find_usb_drive()
        if self.usb_path:
            root = os.path.join(self.usb_path, "Data")
            self.status_box.append(f"[Save] USB drive found ({self.finder.vol_name}) -> {root}")
        else:
            root = os.path.join(os.getcwd(), "Data")
            self.status_box.append(f"[Save] BIONICS_USB not found. Saving locally -> {root}")
        os.makedirs(root, exist_ok=True)
        return root

    def _get_unique_filepath(self, directory, base_filename, ext=".csv"):
        """
        Returns a free path inside `directory` for base_filename+ext.
        If that name is already taken, appends _1, _2, ... instead of
        overwriting the existing file.
        """
        os.makedirs(directory, exist_ok=True)
        candidate = os.path.join(directory, f"{base_filename}{ext}")
        if not os.path.exists(candidate):
            return candidate

        i = 1
        while True:
            candidate = os.path.join(directory, f"{base_filename}_{i}{ext}")
            if not os.path.exists(candidate):
                return candidate
            i += 1

    def _build_win_metric_dataframe(self):
        """
        Converts self.win_metric (list of control_signal tuples from
        SignalProcessor.control_signal_calc_v1) into a DataFrame where every
        channel and every metric gets its own column.

        Expected tuple layout per entry (see control_signal_calc_v1's return):
            (time_elapsed, timestamp_us, data_packet, emg_window_array, chan_send,
            percen_act_1, percen_act_2,
            percen_diffsum_1, percen_diffsum_2,
            co_contraction_index,
            act_error1, act_error2,
            act_std1, act_std2,
            ratio2target_1, ratio2target_2)
        """
        if not self.win_metric:
            return None

        rows = []
        for entry in self.win_metric:
            (time_elapsed, timestamp_us, data_packet, win_arrays, chan_send,
            percen_act_1, percen_act_2,
            percen_diffsum_1, percen_diffsum_2,
            co_contraction_index,
            act_error1, act_error2,
            act_std1, act_std2,
            ratio2target_1, ratio2target_2) = entry

            row = {}
            row["Time_Elapsed"] = time_elapsed
            row["Timestamp_us"] = timestamp_us
            for ch, val in enumerate(data_packet):
                ch_name = self.Channel_Names[ch] if ch < len(self.Channel_Names) else f"CH {ch+1}"
                row[f"{ch_name}_control_signal"] = val

            # Windowed normalized signal, one column per channel, stored as a
            # ';'-separated string of the WIN_SAMP samples used for this row.
            for ch, arr in enumerate(win_arrays):
                ch_name = self.Channel_Names[ch] if ch < len(self.Channel_Names) else f"CH {ch+1}"
                row[f"{ch_name}_window"] = ";".join(f"{v:.5f}" for v in np.asarray(arr).ravel())

            row["label"]               = chan_send
            row["percen_act_ch1"]      = percen_act_1
            row["percen_act_ch2"]      = percen_act_2
            row["percen_diffsum_ch1"]  = percen_diffsum_1
            row["percen_diffsum_ch2"]  = percen_diffsum_2
            row["cocontraction_index"] = co_contraction_index
            row["act_error_ch1"]       = act_error1
            row["act_error_ch2"]       = act_error2
            row["act_std_ch1"]         = act_std1
            row["act_std_ch2"]         = act_std2
            row["ratio2target_ch1"]    = ratio2target_1
            row["ratio2target_ch2"]    = ratio2target_2

            rows.append(row)

        return pd.DataFrame(rows)

    def _save_emg_data(self):
        self.save_emg_btn.setStyleSheet("background-color: green; color: white")

        root      = self._resolve_save_root()
        base_name = self.filename_input.text()
        trial_dir = os.path.join(root, self.today_str, base_name)
        os.makedirs(trial_dir, exist_ok=True)

        saved_any = False

        # windowed control-signal metrics
        win_df = self._build_win_metric_dataframe()
        if win_df is not None:
            path = self._get_unique_filepath(trial_dir, f"{base_name}_win_metric")
            win_df.to_csv(path, index=False)
            self.status_box.append(f"[Save] win_metric -> {path}")
            saved_any = True
        else:
            self.status_box.append("[Save] No win_metric data to save.")

        # full-session raw stream and baseline
        for mode, label in (("data", "EMG"), ("baseline", "baseline")):
            array = self._build_emg_array(mode)
            if array is not None and len(array) > 0:
                n_ch    = array.shape[1] - 2
                columns = ["time_s", "timestamp_us"] + self.Channel_Names[:n_ch]
                df      = pd.DataFrame(array, columns=columns)
                path    = self._get_unique_filepath(trial_dir, f"{base_name}_{label}")
                df.to_csv(path, index=False)
                self.status_box.append(f"[Save] {label} -> {path}")
                saved_any = True
            else:
                self.status_box.append(f"[Save] No {label} data to save.")

        # One raw MVC file per muscle. calib_mvc is cleared at the start of each
        # capture, so without full_mvc_values only the last muscle would survive.
        if self.full_mvc_values:
            for muscle, array in self.full_mvc_values.items():
                if array is None or len(array) == 0:
                    continue
                n_ch    = array.shape[1] - 2
                columns = ["time_s", "timestamp_us"] + self.Channel_Names[:n_ch]
                df      = pd.DataFrame(array, columns=columns)
                path    = self._get_unique_filepath(trial_dir, f"{base_name}_MVC_{muscle}")
                df.to_csv(path, index=False)
                self.status_box.append(f"[Save] MVC {muscle} -> {path}")
                saved_any = True
        else:
            self.status_box.append("[Save] No MVC data to save.")

        # Per-muscle MVC amplitudes plus the composed normalization vector.
        if any(any(v) for v in self.option_mvc_values.values()):
            rows = []
            for muscle, vals in self.option_mvc_values.items():
                row = {"muscle": muscle,
                       "maps_to_channel": self.muscle_channel(muscle)}
                for ch, v in enumerate(vals):
                    name = self.Channel_Names[ch] if ch < len(self.Channel_Names) else f"CH {ch+1}"
                    row[name] = v
                rows.append(row)
            summary = {"muscle": "action_mvc (used for normalization)",
                       "maps_to_channel": ""}
            for ch, v in enumerate(self.action_mvc):
                name = self.Channel_Names[ch] if ch < len(self.Channel_Names) else f"CH {ch+1}"
                summary[name] = v
            rows.append(summary)
            base_row = {"muscle": "baseline (mean+std)", "maps_to_channel": ""}
            for ch, v in enumerate(self.baseline_mean_data + self.baseline_std_data):
                name = self.Channel_Names[ch] if ch < len(self.Channel_Names) else f"CH {ch+1}"
                base_row[name] = v
            rows.append(base_row)

            path = self._get_unique_filepath(trial_dir, f"{base_name}_calibration")
            pd.DataFrame(rows).to_csv(path, index=False)
            self.status_box.append(f"[Save] calibration summary -> {path}")
            saved_any = True

        if not saved_any:
            self.save_emg_btn.setStyleSheet("background-color: red; color: white")

        

    # Buffer Processing >>>
    def rt_buffer_processing(self):
        if self.signal_processor is None or self.ripplestream is None \
                or not self.running:
            return

        snap, ts_last = self.ripplestream.snapshot_buffers()
        n = len(snap)
        if n == 0:
            return

        raws = [np.array(snap[ch], dtype=float) for ch in range(n)]
        self.filtered_buffers       = []
        self.smoothed_buffers       = []
        self.post_processed_buffers = []
        self.normalized_buffers     = []

        for channel, raw in enumerate(raws):
            if raw.size < 10:
                self.filtered_buffers.append(raw)
                self.smoothed_buffers.append(raw)
                self.post_processed_buffers.append(raw)
                self.normalized_buffers.append(raw)
                continue

            # Offline (stateless) variants on purpose: this re-filters the WHOLE
            # rolling window every tick, so carrying zi across ticks would
            # advance the filter state by a full buffer per tick instead of by
            # the samples that actually arrived. The offline path primes zi from
            # each window's first sample, which is also exactly how baseline and
            # MVC are processed - so calibration stats and the live signal come
            # out of an identical transform, which is what makes the normalized
            # values comparable. Measured at 7.4 ms/tick for 2 ch @ 30 kHz.
            filtered       = self.signal_processor.preprocess_filters_offline(raw, channel)
            rectified      = self.signal_processor.rectify_emg(filtered)
            smoothed       = self.signal_processor.moving_window_rms(rectified, window_size=self.win_rms)
            post_processed = self.signal_processor.postprocess_filter_offline(smoothed, channel)
            self.filtered_buffers.append(filtered)
            self.smoothed_buffers.append(smoothed)
            self.post_processed_buffers.append(post_processed)

            if self.calib_done:
                normalized = self.signal_processor.normalize_signal(
                    post_processed,
                    self.baseline_mean_data[channel],
                    self.baseline_std_data[channel],
                    self.action_mvc[channel]
                )
                self.normalized_buffers.append(normalized)
            else:
                self.normalized_buffers.append(post_processed)

        # print(f"normbuff : {self.normalized_buffers}")
        # print(f"timestamp : {self.ripplestream.timestamp_buffers_emg}")
        
        if self.calib_done:
            # Defensive empty-chunk handling combined with the thread-safe
            # snapshot timestamp (ts_last) from snapshot_buffers().
            emg_window_val = []
            for i in range(n):
                chunk = self.normalized_buffers[i][-self.win_control:]
                if len(chunk) > 0:
                    emg_window_val.append(float(np.mean(chunk)))
                else:
                    emg_window_val.append(0.0)

            # Continuous proportional %MVC per channel (0-100) for the bar game:
            # each bar's height tracks that channel's normalized activation
            # DIRECTLY and ungated, so it doesn't collapse to 0 during the
            # cocontraction / no-activation branches of control_signal_calc_v1.
            # chan_send only selects which bar is the target.
            self._latest_norm_pct = [float(np.clip(v, 0.0, 1.0) * 100.0)
                                     for v in emg_window_val]

            win_arrays = [self.normalized_buffers[i][-self.win_control:] for i in range(n)]
            # ts_last is the (time_elapsed_s, nip_ticks) PAIR - control_signal_calc_v1
            # reads it as emg_time_comb[1][0] and [1][1].
            emg_time_comb_val = [emg_window_val, ts_last]

            control_signal = None
            if n >= 2:
                # control_signal_calc_v1 is a 2-channel discriminator (it indexes
                # clean_sig[0] and [1]); with >2 channels it uses the first two.
                control_signal = self.signal_processor.control_signal_calc_v1(
                    emg_time_comb=emg_time_comb_val, emg_window_array=win_arrays)

            if control_signal is not None:
                # Publish for the games to consume (see _emg_source_bar/_box).
                self._latest_control_signal = control_signal
                self.win_metric.append(control_signal)
                try:
                    self.emg_queue.put_nowait(control_signal)
                except queue.Full:
                    pass



    def _update_plots(self):
        if not self.running or self.ripplestream is None:
            return

        if self.calib_done and self.normalized_buffers:
            # Calibrated: show the normalized 0-1 %MVC envelope.
            buffers = [np.asarray(b, dtype=np.float64) for b in self.normalized_buffers]
        else:
            # Uncalibrated: raw straight off the NIP, no filtering or scaling.
            snap, _ = self.ripplestream.snapshot_buffers()
            buffers = [np.asarray(b, dtype=np.float64) for b in snap]

        for i, line in enumerate(self.data_lines):
            if i >= len(buffers):
                break
            data = buffers[i]
            if data.size:
                line.setData(data)

    # Games>>>
    def bargame_v2(self):
        dialog = QInputDialog(self)
        dialog.setWindowTitle("Bar Game Setup")
        dialog.setLabelText("Number of bars:")
        dialog.setTextValue("2")
        dialog.setStyleSheet("""
            QInputDialog, QWidget {
                background-color: black;
                color: white;
            }
            QLineEdit {
                background-color: #222;
                color: white;
                border: 1px solid gray;
            }
            QPushButton {
                background-color: #333;
                color: white;
                border: 1px solid gray;
                padding: 4px 10px;
            }
            QPushButton:hover {
                background-color: #555;
            }
        """)
        ok = dialog.exec_()
        if not ok:
            return

        try:
            num_channels = int(dialog.textValue())
        except ValueError:
            msg = QMessageBox(self)
            msg.setIcon(QMessageBox.Warning)
            msg.setWindowTitle('Invalid Input')
            msg.setText('Please enter a valid integer for the number of bars.')
            msg.setStyleSheet("QLabel { color: white; }")
            msg.exec_()
            return

        try:
            from games.BarGame_v2_DJ.BarGame_main import BarGame_v2
        except Exception as e:
            self.log_status(f"[BarGame] could not import game: {e}")
            return

        # data_packet -> [M1, M2] bars. EMG only if calibrated & streaming,
        # otherwise the game falls back to keyboard (keys '1'/'2').
        self.active_game = BarGame_v2(
            num_channels=num_channels,
            save_root=self._resolve_save_root(),
            emg_source=self._emg_source_bar if self.emg_control else None,
            emg_control=self.emg_control,
            on_finished=self._on_game_finished
        )

        self.log_status(f"[BarGame] launching — "
                        f"{'EMG' if self.emg_control else 'keyboard'} control, {num_channels} bars")
        self.bargame_btn.setEnabled(False)
        self.bargame_btn.setText("Bar Game (Running...)")
        self.active_game.start_game()

    def blockgame_v1(self):
        try:
            from games.BoxDropGame_v1_DJ.BoxDropGame_main import BoxDropGame_v1
        except Exception as e:
            self.log_status(f"[BoxDrop] could not import game: {e}")
            return

        # chan_send -> LEFT/RIGHT movement, data_packet magnitude -> strength.
        self.active_game = BoxDropGame_v1(
            num_channels=self.num_channels,
            save_root=self._resolve_save_root(),
            emg_source=self._emg_source_box if self.emg_control else None,
            emg_control=self.emg_control,
            on_finished=self._on_game_finished
        )

        self.log_status(f"[BoxDrop] launching — "
                        f"{'EMG' if self.emg_control else 'keyboard'} control")
        self.blockgame_btn.setEnabled(False)
        self.blockgame_btn.setText("Block Game (Running...)")
        self.active_game.start_game()
    
    def cursorgame_v1(self):
        dialog = QInputDialog(self)
        dialog.setWindowTitle("Cursor Game Setup")
        dialog.setLabelText("Number of channels:")
        dialog.setTextValue("2")
        dialog.setStyleSheet("""
            QInputDialog, QWidget {
                background-color: black;
                color: white;
            }
            QLineEdit {
                background-color: #222;
                color: white;
                border: 1px solid gray;
            }
            QPushButton {
                background-color: #333;
                color: white;
                border: 1px solid gray;
                padding: 4px 10px;
            }
            QPushButton:hover {
                background-color: #555;
            }
        """)
        ok = dialog.exec_()
        if not ok:
            return

        try:
            num_channels = int(dialog.textValue())
        except ValueError:
            msg = QMessageBox(self)
            msg.setIcon(QMessageBox.Warning)
            msg.setWindowTitle("Invalid Input")
            msg.setText("Please enter a valid integer.")
            msg.setStyleSheet("QLabel { color: white; }")
            msg.exec_()
            return

        from games.CursorGame_v1.CursorGame_Main import CursorGame_v1

        self.active_game = CursorGame_v1(
            num_channels=num_channels,
            save_root=self._resolve_save_root(),
            emg_source=self.get_emg_data if self.emg_control else None,
            emg_control=self.emg_control,
            on_finished=self._on_game_finished
        )

        self.cursorgame_btn.setEnabled(False)
        self.cursorgame_btn.setText("Cursor Game (Running...)")
        self.active_game.start_game()

    def spacegame(self):
        from games.SpaceGame.main import SpaceGame

        self.active_game = SpaceGame(
            num_channels=2,
            save_root=self._resolve_save_root(),
            emg_source=self.get_emg_data if self.emg_control else None,
            emg_control=self.emg_control,
            on_finished=self._on_game_finished
        )

        self.spacegame_btn.setEnabled(False)
        self.spacegame_btn.setText("Space Game (Running...)")
        self.active_game.start_game()

    def jetpackgame(self):
        from games.JetpackJoyride.Jetpack_Game import JetpackGame
        self.active_game = JetpackGame(
            num_channels=1,
            save_root=self._resolve_save_root(),
            emg_source=self.get_emg_data if self.emg_control else None,
            emg_control=self.emg_control,
            on_finished=self._on_game_finished
        )

        self.jetpackgame_btn.setEnabled(False)
        self.jetpackgame_btn.setText("Jetpack Game (Running...)")
        self.active_game.start_game()

    def closeEvent(self, event):
        self._plot_timer.stop()
        self.running = False
        if self.stream is not None:
            self.stream.stop()
        if self.ripplestream is not None:
            self.ripplestream.close()
        event.accept()

    def _on_game_finished(self):
        self.bargame_btn.setEnabled(True)
        self.bargame_btn.setText("Bar Game")
        self.blockgame_btn.setEnabled(True)
        self.blockgame_btn.setText("Block Game")
        self.cursorgame_btn.setEnabled(True)
        self.cursorgame_btn.setText("Cursor Game")
        self.spacegame_btn.setEnabled(True)
        self.spacegame_btn.setText("Space Game")
        self.jetpackgame_btn.setEnabled(True)
        self.jetpackgame_btn.setText("Jetpack Game")
        self.active_game = None
        print("[App] Game finished")


if __name__ == "__main__":
    app = QApplication(sys.argv)
    app.setApplicationName("Ripple EMG Plotter")
    num_chans, ok = QInputDialog.getInt(None, "Setup", "Number of EMG channels to view:",
                                         value=2, min=1, max=8)  # cap at firmware max
    if not ok:
        sys.exit(0)
    active_channels = list(range(num_chans))   # e.g. [0, 1] for first two
    window = RippleGUI(active_channels)
    window.show()
    sys.exit(app.exec_())