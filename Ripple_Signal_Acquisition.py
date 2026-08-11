import xipppy as xp
from time import time, sleep
import collections as c
from Ripple_Settings_SUPPORT import *
from PyQt5.QtCore import QMutex, QThread, pyqtSignal


class RippleController:
    """
    Talks to the Grapevine NIP through xipppy.

    Unlike the MyoWare serial controller this replaces, xipppy hands back
    *blocks* of samples rather than one packet per sample: cont_hires(n, elecs)
    returns n*len(elecs) floats laid out channel-major (all of elec[0]'s n
    samples, then all of elec[1]'s, ...). The acquisition loop below reads one
    block per poll and de-interleaves it into the per-channel deques.
    """

    def __init__(self, active_channels=None, status_update=None):
        # Electrodes actually streamed from. Populated by select_channels()
        # once the hardware has been discovered; active_channels is only the
        # requested count/ordering until then.
        self.active_channels = list(active_channels) if active_channels is not None \
                                else list(range(NUM_CHANNELS))
        self.elecs = []
        self.num_channels = len(self.active_channels)

        self.connected = False
        self.stream_name = None      # canonical stream currently enabled
        self.sample_rate = None      # Hz, for the enabled stream
        self.buffer_len = BUFFER_SIZE

        self.Entire_Signal = []  # full-session log: (t, timestamp_ticks, [ch0, ch1, ...])
        self.calib_baseline = []  # baseline calibration log
        self.calib_mvc = []       # MVC calibration log

        # Read live by the acquisition loop so the GUI can start/stop a
        # calibration capture without restarting the stream. None -> the
        # samples go to Entire_Signal.
        self.calib_mode = None

        self.buffers_emg = [
            c.deque([0.0] * self.buffer_len, maxlen=self.buffer_len)
            for _ in range(self.num_channels)
        ]
        self.timestamp_buffers_emg = c.deque([(0.0, 0.0)] * self.buffer_len,
                                             maxlen=self.buffer_len)
        self.status_update = status_update

        # Health counters, surfaced in the status box every ~2 s.
        self.blocks_ok = 0
        self.samples_ok = 0
        self.resync_count = 0

        self._buf_lock = QMutex()
        self._next_ts = 0            # NIP tick we expect the next sample at

    def _emit(self, msg):
        if self.status_update is None:
            print(msg)
        elif hasattr(self.status_update, "emit"):
            self.status_update.emit(msg)
        else:
            self.status_update(msg)

    # --- connection -------------------------------------------------------
    def connect_to_processor(self):
        """
        Connects to the Neural Interface Processor. If UDP connection fails,
        attempts TCP connection, and adds Trellis operator ID 129 for recording.
        Returns True when a connection was established.
        """
        try:
            xp._close()
        except Exception:
            pass
        sleep(0.001)

        self.connected = False
        try:
            xp._open()
            self._emit("Connected over UDP")
            self.connected = True
        except Exception:
            try:
                xp._open(use_tcp=True)
                xp.add_operator(129)
                self._emit("RippleNeuro connected over TCP")
                self.connected = True
            except Exception as e:
                self._emit(f"Failed to connect to processor: {e}")

        sleep(0.001)
        return self.connected

    def get_processor_info(self):
        info = {}
        try:
            info["NIP serial"] = xp.get_nip_serial()
        except Exception as e:
            info["NIP serial"] = f"<unavailable> {e}"
        try:
            info["xipppy version"] = xp.get_version()
        except Exception as e:
            info["xipppy version"] = f"<unavailable> {e}"
        try:
            info["NIP clock"] = xp.time()
        except Exception as e:
            info["NIP clock"] = f"<unavailable> {e}"
        return info

    # --- discovery --------------------------------------------------------
    def find_electrodes(self):
        self._emit("\n--- Front ends ---")

        for fe_type in ('EMG', 'macro', 'surf', 'micro', 'nano',
                        'ecog', 'eeg', 'analog', 'stim'):
            try:
                elecs = list(xp.list_elec(fe_type))
            except Exception:
                elecs = []
            if elecs:
                self._emit("Found {} '{}' electrodes: {}".format(
                    len(elecs), fe_type, elecs))
                return elecs
            self._emit("No electrodes reported for fe_type='{}'".format(fe_type))

        # Nothing matched by type - list everything.
        all_elecs = list(xp.list_elec(''))
        if not all_elecs:
            raise RuntimeError(
                "No electrodes detected at all. Check that the front end is "
                "seated in the NIP and that Trellis sees it."
            )
        self._emit("Falling back to all detected electrodes: {}".format(all_elecs))
        return all_elecs

    def report_streams(self, elecs):
        """
        Print the stream types each electrode supports, and return a dict of
        {elec: [stream names]}.
        """
        self._emit("\n--- Available streams per electrode ---")
        streams_by_elec = {}
        for elec in elecs:
            try:
                streams = xp.get_fe_streams(elec)
            except Exception as e:
                self._emit("  elec {:>3}: <error> {}".format(elec, e))
                continue
            streams_by_elec[elec] = streams
            try:
                fe = xp.get_fe(elec)
            except Exception:
                fe = '?'
            self._emit("elec {:>3} (FE {}): {}".format(elec, fe, streams))
        return streams_by_elec

    def select_channels(self, n_channels):
        """
        Take the first n_channels detected electrodes as CH 1..N and resize the
        rolling buffers to match. Returns the electrode list actually selected.
        """
        found = self.find_electrodes()
        self.elecs = list(found)[:n_channels]
        if not self.elecs:
            raise RuntimeError("No electrodes available to stream from.")

        self.num_channels = len(self.elecs)
        self.active_channels = list(self.elecs)
        if self.num_channels < n_channels:
            self._emit(f"[WARN] Asked for {n_channels} channels but only "
                       f"{self.num_channels} electrode(s) detected.")

        self._emit(f"Streaming electrodes {self.elecs} as CH 1..{self.num_channels}")
        self._reset_buffers()
        return self.elecs

    def available_streams(self, elecs=None):
        """
        Canonical stream names supported by *every* selected electrode and
        readable by us, ordered by STREAM_PREFERENCE. Discovering these rather
        than hardcoding avoids the 'hi-res' vs 'hires' naming mismatch.
        """
        elecs = self.elecs if elecs is None else list(elecs)
        if not elecs:
            return []

        streams_by_elec = self.report_streams(elecs)
        common = None
        for elec in elecs:
            canon = set()
            for raw_name in streams_by_elec.get(elec, []):
                name = normalize_stream(raw_name)
                if name in STREAM_READERS:
                    canon.add(name)
            common = canon if common is None else (common & canon)

        common = common or set()
        ordered = [s for s in STREAM_PREFERENCE if s in common]
        ordered += sorted(common - set(ordered))
        self._emit(f"Streams available on all selected electrodes: {ordered}")
        return ordered

    def enable_stream(self, stream_name, elecs=None):
        """
        Turn on one stream type across the selected electrodes and remember its
        sample rate. Returns True if it came up on at least one electrode.
        """
        elecs = self.elecs if elecs is None else list(elecs)
        canon = normalize_stream(stream_name)
        reader, fs = stream_reader(stream_name)
        if reader is None:
            self._emit(f"[Stream] No reader for '{stream_name}'.")
            return False

        on = []
        for elec in elecs:
            try:
                xp.signal_set(elec, canon, True)
                sleep(0.005)
                if xp.signal(elec, canon):
                    on.append(elec)
                else:
                    self._emit(f"  elec {elec}: '{canon}' did not turn on")
            except Exception as e:
                self._emit(f"  elec {elec}: '{canon}' failed - {e}")

        if not on:
            self._emit(f"[Stream] '{canon}' could not be enabled on any electrode.")
            return False

        self.stream_name = canon
        self.sample_rate = fs
        # Size the rolling window in seconds so 30 kHz raw and 1 kHz lfp both
        # show a comparable slice of time.
        self.buffer_len = min(int(fs * DISPLAY_SECONDS), MAX_BUFFER_PTS)
        self._reset_buffers()

        self._emit(f"[Stream] '{canon}' enabled on {on} @ {fs} Hz "
                   f"(buffer {self.buffer_len} samples)")
        # Let the NIP start filling its buffers before the first read.
        sleep(0.2)
        return True

    def disable_stream(self, stream_name=None, elecs=None):
        """Deselect a stream so it stops consuming NIP bandwidth."""
        elecs = self.elecs if elecs is None else list(elecs)
        canon = normalize_stream(stream_name or self.stream_name or '')
        if canon is None:
            return
        for elec in elecs:
            try:
                xp.signal_set(elec, canon, False)
            except Exception:
                pass

    def _reset_buffers(self):
        self._buf_lock.lock()
        try:
            self.buffers_emg = [
                c.deque([0.0] * self.buffer_len, maxlen=self.buffer_len)
                for _ in range(self.num_channels)
            ]
            self.timestamp_buffers_emg = c.deque([(0.0, 0.0)] * self.buffer_len,
                                                 maxlen=self.buffer_len)
        finally:
            self._buf_lock.unlock()

    def snapshot_buffers(self):
        """
        Thread-safe copy of the rolling buffers for the GUI.

        Returns (list_of_lists, (time_elapsed_s, nip_ticks)). The timestamp is
        the PAIR, not a bare tick - control_signal_calc_v1 indexes it as
        emg_time_comb[1][0] / [1][1].
        """
        self._buf_lock.lock()
        try:
            snap = [list(buf) for buf in self.buffers_emg]
            ts_last = (self.timestamp_buffers_emg[-1]
                       if self.timestamp_buffers_emg else (0.0, 0.0))
        finally:
            self._buf_lock.unlock()
        return snap, ts_last

    # --- streaming --------------------------------------------------------
    def read_block(self, npoints):
        """
        Read one gapless block from the enabled stream.

        Returns (n_samples, per_channel_lists, first_timestamp_ticks), or None
        if nothing was available this cycle.
        """
        reader, fs = stream_reader(self.stream_name)
        if reader is None:
            return None

        tps = ticks_per_sample(fs)

        # Passing a non-zero start_timestamp is what makes reads gapless AND
        # what makes xipppy return a real timestamp - with start_timestamp=0 it
        # returns the newest samples and a timestamp of 0.
        try:
            data, ts = reader(npoints, self.elecs, self._next_ts)
        except Exception as e:
            self._emit(f"[Stream] read error: {e}")
            return None

        n_ch = len(self.elecs)
        n = len(data) // n_ch if n_ch else 0
        if n == 0:
            return None

        # channel-major: elec i occupies data[i*n : (i+1)*n]
        per_ch = [list(data[i * n:(i + 1) * n]) for i in range(n_ch)]

        self._next_ts = ts + n * tps
        self.blocks_ok += 1
        self.samples_ok += n
        return n, per_ch, ts

    def _resync(self):
        """Jump the read cursor to the newest data after falling behind."""
        try:
            self._next_ts = xp.time()
        except Exception:
            self._next_ts = 0
        self.resync_count += 1

    def acquire(self, duration_s=None, stop_flag=None, calib_mode=None):
        """
        - duration_s: stop after this many seconds (None = run forever)
        - stop_flag: optional callable; loop exits when it returns True
        - calib_mode: initial value for self.calib_mode. The loop re-reads
          self.calib_mode every block, so the GUI can flip it to "baseline"/
          "mvc"/None mid-stream without restarting acquisition.
        """
        self.calib_mode = calib_mode
        if not self.elecs:
            raise RuntimeError("No electrodes selected - call select_channels() first.")
        if self.stream_name is None:
            raise RuntimeError("No stream enabled - call enable_stream() first.")

        fs = self.sample_rate
        tps = ticks_per_sample(fs)
        npoints = max(1, int(fs * ACQ_POLL_MS / 1000.0))
        max_lag_ticks = int(ACQ_MAX_LAG_S * NIP_CLOCK_HZ)

        self._emit("--- Streaming '{}' on electrodes {} @ {} Hz "
                   "({} samples/read) ---".format(
                       self.stream_name, self.elecs, fs, npoints))

        self._reset_buffers()
        self.blocks_ok = 0
        self.samples_ok = 0
        self.resync_count = 0

        start_time = time()
        last_stat_time = start_time
        last_samples = 0
        try:
            self._next_ts = xp.time()
        except Exception as e:
            self._emit(f"[Stream] could not read NIP clock: {e}")
            return self.buffers_emg

        try:
            while True:
                if duration_s is not None and (time() - start_time) >= duration_s:
                    break
                if stop_flag is not None and stop_flag():
                    break

                # If the NIP has moved far past our cursor the old samples are
                # gone from its buffer; skip forward instead of stalling.
                try:
                    if xp.time() - self._next_ts > max_lag_ticks:
                        self._resync()
                        self._emit(f"[Stream] fell behind, resynced "
                                   f"(#{self.resync_count})")
                except Exception:
                    pass

                block = self.read_block(npoints)
                if block is None:
                    sleep(ACQ_POLL_MS / 1000.0)
                    continue
                n, per_ch, ts0 = block

                t_block = time() - start_time
                # Per-sample host time, back-dated across the block so the log
                # isn't a staircase of identical timestamps.
                dt = 1.0 / fs

                self._buf_lock.lock()
                try:
                    for ch_idx in range(self.num_channels):
                        self.buffers_emg[ch_idx].extend(per_ch[ch_idx])
                    for i in range(n):
                        self.timestamp_buffers_emg.append(
                            (t_block - (n - 1 - i) * dt, ts0 + i * tps))
                finally:
                    self._buf_lock.unlock()

                # Re-read every block so calibration can be armed mid-stream.
                sink = {"baseline": self.calib_baseline,
                        "mvc": self.calib_mvc}.get(self.calib_mode, self.Entire_Signal)
                for i in range(n):
                    sink.append((t_block - (n - 1 - i) * dt,
                                 ts0 + i * tps,
                                 [per_ch[ch][i] for ch in range(self.num_channels)]))

                # Health line every ~2 s: sample rate should track the stream's
                # nominal fs and resyncs should stop climbing once locked.
                now = time()
                if now - last_stat_time >= 2.0:
                    elapsed = now - last_stat_time
                    rate = (self.samples_ok - last_samples) / elapsed
                    ranges = []
                    self._buf_lock.lock()
                    try:
                        for ch in range(self.num_channels):
                            arr = list(self.buffers_emg[ch])
                            if arr:
                                ranges.append("CH{} [{:.0f}, {:.0f}]".format(
                                    ch + 1, min(arr), max(arr)))
                    finally:
                        self._buf_lock.unlock()
                    self._emit("[Stream] {:.0f} samp/s (nominal {}) | resyncs {} | {}".format(
                        rate, fs, self.resync_count, "  ".join(ranges)))
                    last_stat_time = now
                    last_samples = self.samples_ok

                sleep(ACQ_POLL_MS / 1000.0)

        except KeyboardInterrupt:
            pass
        return self.buffers_emg

    def close(self):
        try:
            if self.stream_name:
                self.disable_stream()
        except Exception:
            pass
        try:
            xp._close()
        except Exception:
            pass
        self.connected = False


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
