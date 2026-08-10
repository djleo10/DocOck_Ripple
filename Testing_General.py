"""
Basic EMG stream test - Ripple Trellis / Grapevine NIP via xipppy.

Hardware assumed:
    Grapevine NIP  ->  EMG front end  ->  Macro Touchproof Adapter  ->  electrodes

What this does:
    1. Connects to the processor (UDP, falls back to TCP).
    2. Prints processor info (serial, versions, NIP clock).
    3. Discovers the connected front ends and their electrodes.
    4. Prints which data streams each electrode actually offers.
    5. Enables the streams we care about and prints live samples.

Nothing here stimulates. Read-only.

Run Trellis first (or at least have the NIP powered and on the network)
before running this script.
"""

import xipppy as xp
from time import sleep

# --- config ---------------------------------------------------------------

N_CHANNELS_TO_PRINT = 2      # how many electrodes to actually stream from
N_SAMPLES = 100              # datapoints to pull per read
N_ITERATIONS = 10            # how many times to loop
LOOP_DELAY_S = 0.5           # pause between reads

# Stream readers available in xipppy, with their nominal sample rates.
# We probe each electrode for which of these it supports.
STREAM_READERS = {
    'raw':     (xp.cont_raw,    30000),   # 30 kHz broadband
    'hi-res':  (xp.cont_hires,   2000),   # 2 kHz
    'hifreq':  (xp.cont_hifreq,  7500),   # 7.5 kHz
    'lfp':     (xp.cont_lfp,     1000),   # 1 kHz
    'emg':     (xp.cont_emg,     2000),   # EMG stream
}


# --- connection -----------------------------------------------------------

def connect():
    """Open a connection to the NIP. Tries UDP, falls back to TCP."""
    xp._close()
    sleep(0.001)
    try:
        xp._open()
        print("Connected over UDP")
    except Exception:
        xp._open(use_tcp=True)
        print("Connected over TCP")
    sleep(0.001)


def print_processor_info():
    print("\n--- Processor ---")
    try:
        print("NIP serial      :", xp.get_nip_serial())
    except Exception as e:
        print("NIP serial      : <unavailable>", e)
    try:
        print("xipppy version  :", xp.get_version())
    except Exception as e:
        print("xipppy version  : <unavailable>", e)
    print("NIP clock       :", xp.time(), "(30 kHz ticks)")


# --- discovery ------------------------------------------------------------

def find_electrodes():
    """
    Find recording electrodes. Tries the EMG front end first, then falls
    back to whatever is plugged in.
    """
    print("\n--- Front ends ---")

    for fe_type in ('EMG', 'macro', 'surf'):
        try:
            elecs = list(xp.list_elec(fe_type))
        except Exception:
            elecs = []
        if elecs:
            print("Found {} '{}' electrodes: {}".format(
                len(elecs), fe_type, elecs))
            return elecs
        print("No electrodes reported for fe_type='{}'".format(fe_type))

    # Nothing matched by type - list everything.
    all_elecs = list(xp.list_elec(''))
    if not all_elecs:
        raise RuntimeError(
            "No electrodes detected at all. Check that the front end is "
            "seated in the NIP and that Trellis sees it."
        )
    print("Falling back to all detected electrodes: {}".format(all_elecs))
    return all_elecs


def report_streams(elecs):
    """
    Print the stream types each electrode supports, and return a dict of
    {elec: [stream names]}.
    """
    print("\n--- Available streams per electrode ---")
    streams_by_elec = {}
    for elec in elecs:
        try:
            streams = xp.get_fe_streams(elec)
        except Exception as e:
            print("  elec {:>3}: <error> {}".format(elec, e))
            continue
        streams_by_elec[elec] = streams
        try:
            fe = xp.get_fe(elec)
        except Exception:
            fe = '?'
        print("  elec {:>3} (FE {}): {}".format(elec, fe, streams))
    return streams_by_elec


def enable_streams(elecs, streams_by_elec):
    """
    Turn on every stream we know how to read, for the given electrodes.
    Returns {elec: [stream names actually enabled]}.
    """
    print("\n--- Enabling streams ---")
    enabled = {}
    for elec in elecs:
        available = streams_by_elec.get(elec, [])
        on = []
        for stream in available:
            if stream not in STREAM_READERS:
                continue  # no reader for this one (spk, stim, etc.)
            try:
                xp.signal_set(elec, stream, True)
                sleep(0.005)
                if xp.signal(elec, stream):
                    on.append(stream)
                else:
                    print("  elec {}: '{}' did not turn on".format(elec, stream))
            except Exception as e:
                print("  elec {}: '{}' failed - {}".format(elec, stream, e))
        enabled[elec] = on
        print("  elec {:>3}: enabled {}".format(elec, on))

    # Give the NIP a moment to start filling its buffers.
    sleep(0.5)
    return enabled


# --- streaming ------------------------------------------------------------

def summarize(data):
    """Return a short 'n / min / max / mean' string for a block of samples."""
    if not data:
        return "no data returned"
    lo = min(data)
    hi = max(data)
    mean = sum(data) / len(data)
    return "n={:<5} min={:>10.2f}  max={:>10.2f}  mean={:>10.2f}".format(
        len(data), lo, hi, mean)


def print_streams(enabled):
    """Read and print samples from every enabled stream."""
    elecs = [e for e in enabled if enabled[e]][:N_CHANNELS_TO_PRINT]
    if not elecs:
        raise RuntimeError("No streams were enabled on any electrode.")

    print("\n--- Streaming (electrodes {}) ---".format(elecs))

    for i in range(N_ITERATIONS):
        print("\n[read {}/{}]  NIP time = {}".format(
            i + 1, N_ITERATIONS, xp.time()))

        for elec in elecs:
            for stream in enabled[elec]:
                reader, fs = STREAM_READERS[stream]
                try:
                    data, _ts = reader(N_SAMPLES, [elec])
                except Exception as e:
                    print("  elec {:>3} {:<7}: read error - {}".format(
                        elec, stream, e))
                    continue

                data = list(data)
                print("  elec {:>3} {:<7} ({:>5} Hz): {}".format(
                    elec, stream, fs, summarize(data)))
                if data:
                    head = ", ".join("{:.1f}".format(v) for v in data[:5])
                    print("  {:>25}first 5: [{}]".format("", head))

        sleep(LOOP_DELAY_S)


# --- main -----------------------------------------------------------------

if __name__ == '__main__':
    try:
        connect()
        print_processor_info()

        elecs = find_electrodes()
        streams_by_elec = report_streams(elecs[:N_CHANNELS_TO_PRINT])
        enabled = enable_streams(elecs[:N_CHANNELS_TO_PRINT], streams_by_elec)
        print_streams(enabled)

    except Exception as e:
        print("\nERROR: {}: {}".format(type(e).__name__, e))

    finally:
        print("\nClosing connection.")
        xp._close()
