import xipppy as xp

# --- Ripple continuous streams -------------------------------------------
# Canonical stream name -> (reader fn, nominal sample rate in Hz).
# The canonical names are the strings xipppy's C API expects for
# signal_set()/signal()/filter_set(). get_fe_streams() reports these same
# names, so we normalize whatever it returns through STREAM_ALIASES below
# before looking anything up here.
STREAM_READERS = {
    'raw':     (xp.cont_raw,    30000),   # 30 kHz broadband
    'hires':   (xp.cont_hires,   2000),   # 2 kHz
    'hifreq':  (xp.cont_hifreq,  7500),   # 7.5 kHz
    'lfp':     (xp.cont_lfp,     1000),   # 1 kHz
    'emg':     (xp.cont_emg,     2000),   # EMG stream
}

# The front end / older scripts spell some of these differently. Map every
# spelling we've seen onto the canonical key used in STREAM_READERS.
STREAM_ALIASES = {
    'raw': 'raw',
    'hires': 'hires',
    'hi-res': 'hires',
    'hi_res': 'hires',
    'hifreq': 'hifreq',
    'hi-freq': 'hifreq',
    'hf': 'hifreq',
    'lfp': 'lfp',
    'emg': 'emg',
}

# Human-readable dropdown text. The QComboBox stores the canonical name as
# the item's userData, so the GUI never has to parse this back.
STREAM_LABELS = {
    'raw':    'raw (30 kHz)',
    'hires':  'hi-res (2 kHz)',
    'hifreq': 'hifreq (7.5 kHz)',
    'lfp':    'lfp (1 kHz)',
    'emg':    'emg (2 kHz)',
}

# Order streams are offered in when several are available.
STREAM_PREFERENCE = ['hires', 'emg', 'raw', 'hifreq', 'lfp']

# The NIP clock runs at 30 kHz; every stream's sample period is an integer
# number of these ticks (raw=1, hifreq=4, hires/emg=15, lfp=30).
NIP_CLOCK_HZ = 30000


def normalize_stream(name):
    """Map a stream name from any source onto its canonical xipppy key."""
    return STREAM_ALIASES.get(str(name).strip().lower())


def stream_reader(name):
    """Return (reader_fn, sample_rate_hz) for a stream name, or (None, None)."""
    canon = normalize_stream(name)
    if canon is None:
        return None, None
    return STREAM_READERS.get(canon, (None, None))


def ticks_per_sample(fs):
    """NIP clock ticks between consecutive samples of an fs Hz stream."""
    return max(1, int(round(NIP_CLOCK_HZ / float(fs))))


# --- acquisition ----------------------------------------------------------
ACQ_POLL_MS      = 20     # worker sleeps this long between block reads
DISPLAY_SECONDS  = 2.0    # rolling window kept per channel for plotting
MAX_BUFFER_PTS   = 30000  # hard cap so 30 kHz raw doesn't eat memory
ACQ_MAX_LAG_S    = 0.5    # if we fall this far behind, resync to newest data

N_CHANNELS_TO_PRINT = 2      # how many electrodes to actually stream from

# --- plot geometry --------------------------------------------------------
GRAPH_W      = 1000
GRAPH_H      = 100
ROW_SPACING  = 2
LABEL_W      = 90
LEFT_MARGIN  = LABEL_W

BUFFER_SIZE    = 2000
TIMER_MS       = 10           # legacy; kept for compatibility
PLOT_TIMER_MS  = 33           # ~30 fps redraw
EMG_SAMPLE_RATE  = 1000        # EMG Raw (1000 Hz)


# Filters:
HPF = 10
HPF_O = 4
NOTCH = 60
NOTCH_Q = 30
LPF_HC = 6
LPF_O = 4
WINDOW = 50

# Window for segmenting (last 50 samples)
WIN_SAMP = 300

# Ripple streams at 2 k / 7.5 k / 30 kHz
WINDOW_MS   = 1000.0 * WINDOW   / EMG_SAMPLE_RATE   # 50 ms  RMS smoothing
WIN_SAMP_MS = 1000.0 * WIN_SAMP / EMG_SAMPLE_RATE   # 300 ms control window


def samples_for_ms(ms, fs):
    """Convert a duration in ms to a sample count at fs Hz (minimum 1)."""
    return max(1, int(round(ms * fs / 1000.0)))


BASELINE_DURATION_MS = 3000
MVC_DURATION_MS      = 3000
# Dead time after arming a capture, before collection starts. Lets the stream
# settle (and the subject reach effort) without that transient landing in the
# calibration data. Not counted toward the 3 s.
CALIB_SETTLE_MS      = 500
# The offline filter chain is primed from each array's first sample, so the
# envelope still rings for a while at the start. Measured at 7500 Hz on a
# stationary input: discarding this much cuts the baseline std from 60.8 to
# 26.5 (the rest of the record is unaffected). Dropped before mean/std/peak.
CALIB_DISCARD_MS     = 100
# A resting envelope this variable means contact/montage trouble: a 3 s peak of
# a signal with this coefficient of variation lands 3-4 sigma up on its own,
# which is indistinguishable from a real contraction.
BASELINE_CV_WARN     = 0.25

MVC_SAMPLE_LIMIT = int(MVC_DURATION_MS * EMG_SAMPLE_RATE / 1000)
BASELINE_SAMPLE_LIMIT = int(BASELINE_DURATION_MS * EMG_SAMPLE_RATE / 1000)

# MVC is captured one muscle at a time. M<i> is the muscle on electrode <i>, so
# M1's capture supplies channel 0's MVC, M2's supplies channel 1's, and so on -
# you can't maximally contract every muscle at once, so each channel gets its
# value from its own trial.
MUSCLE_PREFIX = "M"


def muscle_names(n_channels):
    """['M1', 'M2', ...] - one entry per streamed channel."""
    return [f"{MUSCLE_PREFIX}{i + 1}" for i in range(max(0, int(n_channels)))]

# Y-axis once normalization is live (0-1 with headroom)
NORM_Y_MIN = -0.2
NORM_Y_MAX = 1.2


# --- stimulation ----------------------------------------------------------
# Hardware limits, taken from xipppy/stim.py's own property setters. Times in
# the stim API are in NIP clocks, not microseconds - a very easy way to be off
# by 33x, so conversions always go through STIM_CLOCK_US.
STIM_CLOCK_US          = 1e6 / NIP_CLOCK_HZ   # 33.333 us per clock
STIM_MAX_AMP_STEPS     = 127                  # StimSegment.amplitude
STIM_MAX_SEG_CLOCKS    = 0xFFFF               # StimSegment.length
STIM_MAX_PERIOD_CLOCKS = 0xFFFF               # StimSeq.period
STIM_MAX_REPEATS       = 0xFFF                # StimSeq.repeats (4095)
STIM_MAX_SEGMENTS      = 249                  # StimSeq.GVSTIM_CMD_MAXLEN

# Charge per phase above which the GUI asks for confirmation. Not a hardware
# limit - a review prompt, since safe charge density depends on electrode area.
STIM_CHARGE_WARN_NC    = 400.0

# Defaults mirror Bipolar_Stim_Example.py so the GUI starts from known-good
# numbers: 80 steps at 20 uA/step = 1600 uA, 200 clocks = 6.67 ms per phase.
# Shown until the real table is read from the FE via stim_get_res_options().
# These are the nano/stim front-end steps quoted in Bipolar_Stim_Example.py.
STIM_FALLBACK_RES_UA = [1.0, 2.0, 5.0, 10.0, 20.0]

STIM_DEFAULTS = dict(
    cathode_elec=0,
    anode_elec=1,
    res_index=4,
    amp_steps=80,
    phase_clocks=200,
    interphase_clocks=100,
    frequency_hz=1.0,
    n_pulses=20,
)

# The main window sets "background-color: black", and Qt cascades that into any
# dialog parented to it. A dialog that only sets QLabel colour therefore ends up
# black-on-black. Every dialog gets this instead, which sets its own background
# as well as the text, inputs and buttons.
DIALOG_STYLE = """
QMessageBox, QInputDialog, QDialog {
    background-color: #1e1e1e;
}
QMessageBox QLabel, QInputDialog QLabel, QDialog QLabel {
    color: #FFFFFF;
    background-color: transparent;
    font-size: 13px;
}
QLineEdit, QSpinBox, QDoubleSpinBox, QComboBox, QTextEdit {
    background-color: #2b2b2b;
    color: #FFFFFF;
    border: 1px solid #777;
    padding: 4px;
}
QPushButton {
    background-color: #3a3a3a;
    color: #FFFFFF;
    border: 1px solid #8a8a8a;
    padding: 6px 18px;
    min-width: 76px;
}
QPushButton:hover    { background-color: #555; }
QPushButton:pressed  { background-color: #222; }
QPushButton:default  { border: 2px solid #4DB848; }
"""

# Data Plotting
EMG_TYPES = {"EMG"}
NUM_CHANNELS = 6
CHANNEL_COLORS = [
    "#00E5FF",
    "#376E00",
    "#FF4081",
    "#FFEA00",
    "#E040FB",
    "#FF6D00",
    "#1DE9B6",
    "#F50057",
]
