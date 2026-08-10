import re
import struct
import xipppy as xp
from time import sleep
import collections as c
from Ripple_Settings_SUPPORT import *
from PyQt5.QtCore import QMutex


class RippleController:
    def __init__(self, active_channels=None, status_update=None):
        
        self.hw_channels = NUM_CHANNELS
        self.packet_format  = '<BI' + 'h' * self.hw_channels    # little-endian: uint8, uint32, N x int16 == 17bytes
        self.packet_size  = struct.calcsize(self.packet_format)
        self.active_channels = list(active_channels) if active_channels is not None \
                                else list(range(self.hw_channels))

        self.num_channels = len(self.active_channels) # what buffers/GUI actually use
        self.Entire_Signal = [] # full-session log: (t, timestamp_us, [ch0, ch1, ...])
        self.calib_baseline = [] # baseline calibration log: (t, timestamp_us, [ch0, ch1, ...])
        self.calib_mvc = []      # MVC calibration log: (t, timestamp_us, [ch0, ch1, ...])
        self.buffers_emg = [
            c.deque([0.0] * BUFFER_SIZE, maxlen=BUFFER_SIZE)
            for _ in range(self.num_channels)
        ]
        self.timestamp_buffers_emg = c.deque([(0.0, 0.0)] * BUFFER_SIZE, maxlen=BUFFER_SIZE)
        self.status_update = status_update

        self.packets_ok = 0
        self.resync_count = 0
        self._rx = bytearray()
        self._buf_lock = QMutex()

    def _emit(self,msg):
        # status_update may be a Qt signal (thread-safe, queued to the GUI thread)
        # or a plain callable. Guard against it being missing (e.g. the __main__
        # test harness) so the packaged app can never crash just because it tried
        # to log a status line.
        if self.status_update is None:
            print(msg)
        elif hasattr(self.status_update, "emit"):
            self.status_update.emit(msg)
        else:
            self.status_update(msg)

    def connect_to_processor(self):
        """
        Connects to the Neural Interface Processor. If UDP connection fails,
        attempts TCP connection, and adds Trellis operator ID 129 for recording.
        """
        xp._close()
        sleep(0.001)

        try:
            xp._open()
            self._emit("Connected over UDP")
        except:
            try:
                xp._open(use_tcp=True)
                xp.add_operator(129)
                self._emit("Connected over TCP")
            except:
                self._emit("Failed to connect to processor.")

        sleep(0.001)

    def flush_input(self):
        """Drop any partial/stale bytes sitting in the OS serial buffer AND in
        our own carry-over buffer, so a fresh stream re-locks cleanly."""
        self.ser.reset_input_buffer()
        self._rx.clear()

    def _unpack(self, pkt):
        """Decode one aligned 17-byte packet into (timestamp_us, [voltages...])."""
        _, timestamp_us, *raw_channels = struct.unpack(self.packet_format, pkt)
        # Full 6-channel packet is always parsed; keep only the requested channels.
        selected_raw = [raw_channels[i] for i in self.active_channels]
        voltages = [raw * (self.ADC_VREF / self.ADC_MAX) for raw in selected_raw]
        return timestamp_us, voltages

    def read_sample(self, resync_limit=4096):
        """
        Read one fixed-size binary packet matching the .ino Packet struct:
            uint8_t sync; uint32_t timestamp_us; int16_t channels[6];

        Alignment is CONFIRMED, not assumed: a real packet head is a SYNC_BYTE
        whose byte exactly one packet-length later is ALSO a SYNC_BYTE (packets
        are contiguous, so every packet is immediately followed by the next one's
        sync). This rejects data bytes that merely happen to equal 0xAA -- the
        false-locks a single-byte check turns into gibberish.

        Leftover bytes live in self._rx between calls so we never lose alignment.
        Returns (timestamp_us, [voltage_ch0, ...]) or None if it couldn't sync.
        """
        ps = self.packet_size
        buf = self._rx          # persistent bytearray, mutated in place
        did_resync = False
        scanned = 0

        while scanned < resync_limit:
            # Need a full packet + 1 trailing byte to confirm alignment.
            if len(buf) < ps + 1:
                chunk = self.ser.read(ps + 1 - len(buf))
                if not chunk:
                    return None          # stream idle; leftover kept for next call
                buf += chunk
                continue

            # Aligned & confirmed: consume one packet, keep the remainder.
            if buf[0] == self.SYNC_BYTE and buf[ps] == self.SYNC_BYTE:
                pkt = bytes(buf[:ps])
                del buf[:ps]
                self.packets_ok += 1
                if did_resync:
                    self.resync_count += 1
                try:
                    return self._unpack(pkt)
                except struct.error:
                    del buf[0]           # corrupt despite framing; nudge and rehunt
                    did_resync = True
                    scanned += 1
                    continue

            # Misaligned: drop bytes up to the next candidate sync and retry.
            did_resync = True
            idx = buf.find(self.SYNC_BYTE, 1)
            if idx == -1:
                scanned += len(buf)
                buf.clear()
            else:
                scanned += idx
                del buf[:idx]

        return None  # gave up resyncing

    def acquire(self, duration_s=None, stop_flag=None, calib_mode = None):
        """
        - duration_s: stop after this many seconds (None = run forever)
        - stop_flag: optional callable; loop exits when it returns True
        - calib_mode: if ["baseline"] or ["mvc"], collect data for calibration purposes
        """
        start_time = time.time()
        self._buf_lock.lock()
        try:
            self.buffers_emg = [
                c.deque([0.0] * BUFFER_SIZE, maxlen=BUFFER_SIZE)
                for _ in range(self.num_channels)
            ]
            self.timestamp_buffers_emg = c.deque([(0.0, 0.0)] * BUFFER_SIZE, maxlen=BUFFER_SIZE)
        finally:
            self._buf_lock.unlock()
        # Throughput reporting: snapshot counters so we can print pkt/s live.
        last_stat_time = start_time
        last_pkts = self.packets_ok
        last_resyncs = self.resync_count

        try:
            while True:
                if duration_s is not None and (time.time() - start_time) >= duration_s:
                    break
                if stop_flag is not None and stop_flag():   # <-- call it
                    break

                # Emit a health line every ~2s: rate should be ~1000 pkt/s and
                # resyncs should stop climbing once the stream is locked.
                now = time.time()
                if now - last_stat_time >= 2.0:
                    dt = now - last_stat_time
                    rate = (self.packets_ok - last_pkts) / dt
                    d_resync = self.resync_count - last_resyncs
                    self._emit(f"[Acq] {rate:.0f} pkt/s | resyncs +{d_resync} "
                               f"(total {self.resync_count})")

                    # Per-channel RAW voltage range straight off the ADC (before
                    # any filtering). This is the definitive hardware check:
                    # peak-to-peak should be small at rest and jump HARD when you
                    # contract. If pp barely moves when you flex, the problem is
                    # analog -- electrodes, the reference electrode, power, or a
                    # missing common ground -- not the software.
                    # The ADC rails sit at +/-(2048 * VREF/ADC_MAX) ~= +/-1.65V
                    # (analogRead 0 or 4095). Landing on a rail means the analog
                    # signal is being CLIPPED before we ever digitize it -- no
                    # filter can recover clipped data, so flag it loudly.
                    rail = 2048 * (self.ADC_VREF / self.ADC_MAX)
                    parts = []
                    for ch in range(self.num_channels):
                        arr = list(self.buffers_emg[ch])
                        if arr:
                            lo, hi = min(arr), max(arr)
                            label = self.active_channels[ch] + 1
                            clip = " CLIP!" if (lo <= -rail + 0.05 or hi >= rail - 0.05) else ""
                            parts.append(f"CH{label} pp={hi - lo:.3f}V ({lo:+.2f}..{hi:+.2f}){clip}")
                    if parts:
                        self._emit("[Raw] " + " | ".join(parts))

                    last_stat_time = now
                    last_pkts = self.packets_ok
                    last_resyncs = self.resync_count

                result = self.read_sample()
                if result is None:
                    continue  # couldn't resync this cycle, try again
                timestamp_us, voltages = result
                t = time.time() - start_time

                 # rolling buffers — written under lock so the GUI never reads a
                # half-updated frame (snapshot_buffers takes the same lock).
                self._buf_lock.lock()
                try:
                    self.timestamp_buffers_emg.append((t, timestamp_us))
                    for ch_idx, v in enumerate(voltages):
                        self.buffers_emg[ch_idx].append(v)
                finally:
                    self._buf_lock.unlock()
                
                if calib_mode == "baseline":
                    self.calib_baseline.append((t, timestamp_us, voltages))
                    # print(f"[ArduinoController] Baseline sample: t={t:.3f}s, timestamp_us={timestamp_us}, voltages={voltages}")
                elif calib_mode == "mvc":
                    self.calib_mvc.append((t, timestamp_us, voltages))
                    # print(f"[ArduinoController] MVC sample: t={t:.3f}s, timestamp_us={timestamp_us}, voltages={voltages}")
                else: # full-stream log (unbounded, for saving)
                    self.Entire_Signal.append((t, timestamp_us, voltages))
                    # print(f"[ArduinoController] Continuous sample: t={t:.3f}s, timestamp_us={timestamp_us}, voltages={voltages}")

        except KeyboardInterrupt:
            pass
        return self.buffers_emg
    
    def snapshot_buffers(self):
        """Thread-safe copy of the rolling buffers for the GUI thread.

        Returns (per_channel_lists, last_timestamp_tuple), taken under the same
        mutex the acquisition loop appends with, so the GUI can never observe a
        partially-written frame.
        """
        self._buf_lock.lock()
        try:
            bufs = [list(b) for b in self.buffers_emg]
            ts_last = self.timestamp_buffers_emg[-1]
        finally:
            self._buf_lock.unlock()
        return bufs, ts_last

    def start_streaming(self):
        """Send the 'p' command to start data collection."""
        if self.ser and self.ser.is_open:
            self.ser.write(b'p')
            self.flush_input() # Clear out any old bytes sitting in the buffer
            self._emit("Starting EMG Streaming")

    def stop_streaming(self):
        """Send the 'q' command to stop data collection."""
        if self.ser and self.ser.is_open:
            self.ser.write(b'q')
            self._emit("Stopping EMG Streaming")

    def close(self):
        if self.ser and self.ser.is_open:
            self.ser.close()

    
if __name__ == "__main__":
    controller = ArduinoController()  # raises if no MKR ZERO found

    print("Acquiring 5s of EMG data...")
    data = controller.acquire(duration_s=5.0)
    controller.close()

    print(f"Collected {len(data)} samples")
    if data:
        actual_rate = len(data) / (data[-1][0] - data[0][0])
        print(f"Effective sample rate: {actual_rate:.1f} Hz")
        print(f"First 5 samples (t, V): {data[:5]}")