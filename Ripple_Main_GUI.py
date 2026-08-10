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
from PyQt5.QtCore import Qt, QTimer, QThread, QPoint, pyqtSignal
from PyQt5.QtGui import QPainter, QPen, QColor, QFont, QPixmap, QPolygon,  QStandardItem, QStandardItemModel, QDoubleValidator
from PyQt5.QtWidgets import QCheckBox, QGridLayout,QGraphicsProxyWidget, QGraphicsScene, QGraphicsView, QLineEdit, QMessageBox, QInputDialog, QComboBox, QTextEdit, QListWidget, QAbstractItemView, QDialog
import pyqtgraph as pqtg

import collections as c

import xipppy as xp

from Ripple_USB_Finder_SUPPORT import Ripple_USBFinder
from Ripple_Signal_Acquisition import RippleController
from Ripple_Settings_SUPPORT  import *


class RippleGUI(QMainWindow):
    # Status lines from non-GUI code (RippleController, worker threads) come in
    # through this signal so they land in status_box on the GUI thread. Qt queues
    # the call automatically when the sender lives in another thread.
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

        # Logos
        logo1_path = os.path.join("Logo_Assets","Harvard_University_shield.png")
        logo2_path = os.path.join("Logo_Assets","HBL_Logo.png")
        logo3_path = os.path.join("Logo_Assets","MyowareLogo.png")
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
        # self.signal_processor = SignalProcessor(
        #                         fs=EMG_SAMPLE_RATE,
        #                         num_channels = self.num_channels
        #                     )
        self.emg_control = False
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
        self._plot_timer.setInterval(TIMER_MS)  # ~100 fps
        self._plot_timer.timeout.connect(self._update_plots)
        self._plot_timer.timeout.connect(self.rt_buffer_processing)

        # State
        self.pairing         = False
        self.selectedSensor  = None

        # self.stream = MyoThread(active_channels=self.active_channels)
        # self.stream.status_update.connect(self.log_status)
        # self.stream.connect_hardware()
        # self.emg_queue = queue.Queue()

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
        self.ripplestream.connect_to_processor()

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
            self.Reg_data_Label.setText("CALIBRATION")
            self.Reg_data_Label.setStyleSheet("font-size: 18px; font-weight: bold; color: black")
            self.Reg_data_Label.setAlignment(Qt.AlignCenter)

            self.calib_layout = QHBoxLayout()
            self.baseline_btn = QPushButton("BASELINE")
            self.baseline_btn.clicked.connect(self._baseline_collect)
            self.baseline_btn.setStyleSheet("background-color: black; color: white")
            
            self.MVC_btn = QPushButton("MVC")
            self.MVC_btn.clicked.connect(self._MVC_collect)
            self.MVC_btn.setStyleSheet("background-color: black; color: white")
    
            self.calib_layout.addWidget(self.baseline_btn)
            self.calib_layout.addWidget(self.MVC_btn)
            self.left_layout.addLayout(self.calib_layout)
    
            self.button_layout = QHBoxLayout()
            self.start_btn = QPushButton("Start Uplink")
            self.start_btn.clicked.connect(self._start_streaming)
            self.start_btn.setStyleSheet("background-color: grey; color: black")
            self.start_btn.setEnabled(False)
            self.button_layout.addWidget(self.start_btn)
    
            self.stop_btn = QPushButton("Stop Uplink")
            self.stop_btn.clicked.connect(self._stop_streaming)
            self.stop_btn.setStyleSheet("background-color: grey; color: black")
            self.stop_btn.setEnabled(False) 
            self.button_layout.addWidget(self.stop_btn)
    
            self.left_layout.addLayout(self.button_layout)
    
            self.Goodtogo_label = QLabel("Ready to use the device !!!")
            self.Goodtogo_label.setStyleSheet("font-size: 14px; font-weight: bold; color: Green")
            self.Goodtogo_label.setAlignment(Qt.AlignCenter)
            self.Goodtogo_label.setVisible(False)
            self.left_layout.addWidget(self.Goodtogo_label)
    
            self.save_layout = QHBoxLayout()
            self.save_emg_btn = QPushButton("SAVE EMG")
            self.save_emg_btn.clicked.connect(self._save_emg_data)
            self.save_emg_btn.setStyleSheet("background-color: black; color: white")
            self.save_layout.addWidget(self.save_emg_btn)
    
            self.left_layout.addLayout(self.save_layout)
    

            
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
        self._baseline_was_streaming = False
        self._mvc_was_streaming = False
        self.running = False

        for ch in range(self.num_channels):
            gw = pqtg.PlotWidget()
            gw.setFrameStyle(0)
            gw.setBackground('k')
            gw.setYRange(y_min_range, y_max_range)
            gw.setXRange(0, BUFFER_SIZE)
            gw.setFixedSize(GRAPH_W, GRAPH_H)
            pen  = pqtg.mkPen(color=CHANNEL_COLORS[ch % len(CHANNEL_COLORS)], width=2)
            line = gw.plot(pen=pen)
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

        return self.emg_view

    # Calibration (baseline)>>>
    def _baseline_collect(self):
        self.baseline_btn.setEnabled(False)
        self.baseline_btn.setStyleSheet("background-color: #4DB848; color: white")
        self.baseline_btn.setText("BASELINE…")

        self._baseline_was_streaming = self.running
        self.stream._running_baseline = True
        if not self.running:
            self.running = True
            self.stream.start()
            self._plot_timer.start()
        self._baseline_timer.start()

        QTimer.singleShot(500, self._begin_baseline)

    def _on_baseline_timer_poll(self):
        """Stop baseline collection once enough samples have been accumulated."""
        n_samples = (
                len(self.stream.myo.calib_baseline)
                if self.stream.myo.calib_baseline
                else 0
            )
        elapsed_pct = int(n_samples / BASELINE_SAMPLE_LIMIT * 100)
        self.baseline_btn.setText(f"BASELINE… {min(elapsed_pct, 100)}%")
        if n_samples >= BASELINE_SAMPLE_LIMIT:
            self._baseline_timer.stop()
            self._finish_baseline()

    def _begin_baseline(self):
        QTimer.singleShot(BASELINE_DURATION_MS, self._finish_baseline)

    def _finish_baseline(self):
        self.stream._running_baseline = False
        self._baseline_timer.stop()
        array = self._build_emg_array("baseline")
        if array is not None:
            self.baseline_calculation(array)
        else:
            self.status_box.append("[Baseline] No data collected.")

        if not self._baseline_was_streaming:
            self.running = False
            self._plot_timer.stop()
            QTimer.singleShot(200, self.stream.stop)

        self.baseline_btn.setEnabled(False)
        self.baseline_btn.setStyleSheet("background-color: grey; color: black;")
        self.baseline_btn.setText("BASELINE [DONE]")
        self._maybe_enable_start()

    # Calibration (MVC)>>>

    def get_emg_data(self):
        if not self.post_processed_buffers:
            return None
        result = []
        for i in range(len(self.post_processed_buffers)):
            chunk = self.post_processed_buffers[i][-WIN_SAMP:]
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
        self.MVC_btn.setEnabled(False)
        self.MVC_btn.setStyleSheet("background-color: #4DB848; color: white")
        self.MVC_btn.setText(f"MVC…")

        self._mvc_was_streaming = self.running
        self.stream._running_mvc = True
        if not self.running:
            self.running = True
            self.stream.start()
            self._plot_timer.start()
        self._mvc_timer.start()
        
        QTimer.singleShot(500, self._begin_mvc)

    def _begin_mvc(self):
        QTimer.singleShot(MVC_DURATION_MS, self._finish_mvc)  

    def _on_mvc_timer_poll(self):
        """Stop MVC collection once enough samples have been accumulated."""
        n_samples = (
                len(self.stream.myo.calib_mvc)
                if self.stream.myo.calib_mvc
                else 0
            )
        elapsed_pct = int(n_samples / MVC_SAMPLE_LIMIT * 100)
        self.MVC_btn.setText(f"MVC… {min(elapsed_pct, 100)}%")
        if n_samples >= MVC_SAMPLE_LIMIT:
            self._mvc_timer.stop()
            self._finish_mvc()

    def _finish_mvc(self):
        self.stream._running_mvc = False
        self._mvc_timer.stop()
        array = self._build_emg_array("mvc")
        if array is not None:
            self.mvc_calculation(array)
        else:
            self.status_box.append("[MVC] No data collected.")

        if not self._mvc_was_streaming:
            self.running = False
            self._plot_timer.stop()
            QTimer.singleShot(200, self.stream.stop)

        self.MVC_btn.setEnabled(False)
        self.MVC_btn.setStyleSheet("background-color: grey; color: black;")
        self.MVC_btn.setText("MVC [DONE]")
        self._maybe_enable_start()

    def _maybe_enable_start(self):
        if len(self.stream.myo.calib_baseline) > 0 and len(self.stream.myo.calib_mvc) > 0:
            self.start_btn.setEnabled(True)
            self.start_btn.setStyleSheet("background-color: black; color: white")
            self.stop_btn.setEnabled(True)
            self.stop_btn.setStyleSheet("background-color: black; color: white")

            self.calib_done = True

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

            for gw in self.graph_widgets:
                gw.setYRange(-0.2, 1.2)

    def baseline_calculation(self, baseline_array):
        data = baseline_array
        n_ch = self.num_channels

        self.baseline_mean_data = np.zeros(n_ch)
        self.baseline_std_data  = np.zeros(n_ch)

        for ch in range(n_ch):
            raw            = data[:, ch + 2]
            filtered       = self.signal_processor.preprocess_filters_offline(raw, ch)
            preprocessed   = self.signal_processor.rectify_emg(filtered)
            smoothed       = self.signal_processor.moving_window_rms(preprocessed, window_size=WINDOW)
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

    # def mvc_calculation(self, mvc_array, gesture):
    def mvc_calculation(self, mvc_array):
        self.full_mvc_values = mvc_array
        n_ch = self.full_mvc_values.shape[1] - 2
        self.action_mvc = np.zeros(n_ch)

        for ch in range(n_ch):
            raw            = self.full_mvc_values[:, ch + 2]
            filtered       = self.signal_processor.preprocess_filters_offline(raw, ch)
            rectified      = self.signal_processor.rectify_emg(filtered)
            smoothed       = self.signal_processor.moving_window_rms(rectified, window_size=WINDOW)
            post_processed = self.signal_processor.postprocess_filter_offline(smoothed, ch)

            if len(post_processed) > 0:
                peaks, _ = find_peaks(post_processed, height=0)
                self.action_mvc[ch] = (float(np.max(post_processed[peaks]))
                                if len(peaks) > 0 else float(np.max(post_processed)))

        # self.option_mvc_values[gesture] = action_mvc.tolist()
        # mvc_text = np.array2string(self.action_mvc, separator=", ", max_line_width=np.inf)[1:-1]
        # if hasattr(self, "mvc_display"):
        #     self.mvc_display.setText(f"MVC:\n{mvc_text}")
        self.status_box.append(f"50 samp MVC:{post_processed[:50]}")
        self.status_box.append(f"[MVC] Peak amplitude : {self.action_mvc}")

    def _start_streaming(self):
        self.running = True
        self.emg_control = True
        self.signal_processor.reset_filter_states()
        self.stream.start()
        self._plot_timer.start()
        self.start_btn.setStyleSheet("background-color: #4DB848; color: white")
        self.stop_btn.setStyleSheet("background-color: black; color: white")
        self.Goodtogo_label.setVisible(True)

    def _stop_streaming(self):
        self.running = False
        self.emg_control = False
        self._plot_timer.stop() 
        self.stream.stop() 
        
        self.stop_btn.setStyleSheet("background-color: red; color: white")
        self.start_btn.setStyleSheet("background-color: black; color: white")
        self.Goodtogo_label.setVisible(False)
        
    # SAVING DATA>>>>
    def _build_emg_array(self, mode: str):
        """Build (N, n_ch+2) array from baseline, mvc, or full-session logs."""
        source = {
            "baseline": self.stream.myo.calib_baseline,
            "mvc":      self.stream.myo.calib_mvc,
            "data":     self.stream.myo.Entire_Signal,
        }.get(mode)

        if not source:
            return None

        time         = np.array([t[0] for t in source])
        timestamp_us = np.array([t[1] for t in source])
        emg_data     = np.array([t[2] for t in source])
        return np.column_stack([time, timestamp_us, emg_data])
        
    def _resolve_save_root(self):
        """
        Looks for the MYOWARE_USB drive and saves there if found; otherwise
        falls back to a local "Data" folder (mirrors the fallback behavior
        in MyoWare_USBFinder_SUPPORT.py's __main__ block).
        """
        self.usb_path = self.finder.find_usb_drive()
        if self.usb_path:
            root = os.path.join(self.usb_path, "Data")
            self.status_box.append(f"[Save] USB drive found ({self.finder.vol_name}) -> {root}")
        else:
            root = os.path.join(os.getcwd(), "Data")
            self.status_box.append(f"[Save] MYOWARE_USB not found. Saving locally -> {root}")
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

        # full-session raw stream, baseline, and MVC
        for mode, label in (("data", "EMG"), ("baseline", "baseline"), ("mvc", "mvc")):
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

        if not saved_any:
            self.save_emg_btn.setStyleSheet("background-color: red; color: white")

        

    # Buffer Processing >>>
    def rt_buffer_processing(self):
        snap, ts_last = self.stream.myo.snapshot_buffers()
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

            filtered       = self.signal_processor.preprocess_filters(raw, channel)
            rectified      = self.signal_processor.rectify_emg(filtered)
            smoothed       = self.signal_processor.moving_window_rms(rectified, window_size=WINDOW)
            post_processed = self.signal_processor.postprocess_filter(smoothed, channel)
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
        # print(f"timestamp : {self.stream.myo.timestamp_buffers_emg}")
        
        if self.calib_done:
            # Defensive empty-chunk handling (from origin/main) combined with the
            # thread-safe snapshot timestamp (ts_last) from snapshot_buffers().
            emg_window_val = []
            for i in range(n):
                chunk = self.normalized_buffers[i][-WIN_SAMP:]
                if len(chunk) > 0:
                    emg_window_val.append(float(np.mean(chunk)))
                else:
                    emg_window_val.append(0.0)
            timestamp_us_val = ts_last

            # Continuous proportional %MVC per channel (0-100) for the bar game:
            # each bar's height tracks that channel's normalized activation
            # DIRECTLY and ungated, so it doesn't collapse to 0 during the
            # cocontraction / no-activation branches of control_signal_calc_v1.
            # chan_send only selects which bar is the target.
            self._latest_norm_pct = [float(np.clip(v, 0.0, 1.0) * 100.0)
                                     for v in emg_window_val]

            win_arrays = [self.normalized_buffers[i][-WIN_SAMP:] for i in range(n)]
            emg_time_comb_val = [emg_window_val, timestamp_us_val]

            # print(f"windowed: {emg_window_val}, Timstamp: {timestamp_us_val}")
                # print(f"[DEBUG] queue size before put: {self.emg_queue.qsize()}")

            if self.num_channels == 2:
                control_signal = self.signal_processor.control_signal_calc_v1(emg_time_comb=emg_time_comb_val, emg_window_array=win_arrays)
            
            if self.num_channels == 3:
                pass
            
            if self.num_channels == 4:
                pass

            if self.num_channels == 5:
                pass

            if self.num_channels == 6:
                pass

            # Publish for the games to consume (see _emg_source_bar/_box).
            self._latest_control_signal = control_signal
            self.win_metric.append(control_signal)
            self.emg_queue.put_nowait(control_signal)
            # print(f"[queue] size={self.emg_queue.qsize()}  signal={control_signal}")



    def _update_plots(self):
        if not self.running or not self.stream.myo.buffers_emg:
            return

        # buffers = self.post_processed_buffers if self.post_processed_buffers else None 
        if self.calib_done:
            buffers = [np.array(self.normalized_buffers[ch], dtype=float) for ch in range(len(self.normalized_buffers))] # Used for plotting normalized EMG signals
        else:
            buffers = [np.array(self.post_processed_buffers[ch], dtype=float) for ch in range(len(self.post_processed_buffers))] # USed for plotting post-processed EMG signals

        # print([float(np.mean(np.abs(self.post_processed_buffers[ch]))) for ch in range(self.num_channels)])
        if buffers is None:
            return

        for i, line in enumerate(self.data_lines):
            if i >= len(buffers):
                break
            if self.calib_done:
                data = np.array(buffers[i], dtype=np.float64) # For nomalized plotting
            else:
                data = np.array(buffers[i], dtype=np.float64) * 1000 # For plotting in mV of post-processed EMG signals
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
        self.stream.stop()
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
    app.setApplicationName("Delsys EMG Plotter")
    num_chans, ok = QInputDialog.getInt(None, "Setup", "Number of EMG channels to view:",
                                         value=2, min=1, max=8)  # cap at firmware max
    if not ok:
        sys.exit(0)
    active_channels = list(range(num_chans))   # e.g. [0, 1] for first two
    window = RippleGUI(active_channels)
    window.show()
    sys.exit(app.exec_())