"""
Diagnose why a stream refuses to enable (e.g. 'hires' failing while 'hifreq'
works on the same electrodes).

xipppy's exception.check() throws away the driver's negative return code and
replaces it with the generic "Xipplib call failed". This script calls the C
entry point directly, keeps the code, and decodes it via xp.error_string() so
the real reason is visible.

Run with the NIP powered and Trellis in whatever state you normally use.
"""

import xipppy as xp
import xipppy_capi as _c
from time import sleep

from Ripple_Settings_SUPPORT import STREAM_READERS, normalize_stream


def connect():
    try:
        xp._close()
    except Exception:
        pass
    sleep(0.001)
    try:
        xp._open()
        print("Connected over UDP")
    except Exception:
        xp._open(use_tcp=True)
        xp.add_operator(129)
        print("Connected over TCP (operator 129 added)")
    sleep(0.001)


def raw_signal_set(elec, stream, on):
    """signal_set WITHOUT check() - returns the driver's own code."""
    return _c.xl_signal_set(elec, stream, int(on))


def decode(code):
    try:
        return xp.error_string(code)
    except Exception as e:
        return f"<error_string failed: {e}>"


def main():
    connect()

    try:
        print("NIP serial :", xp.get_nip_serial())
        print("versions   :", xp.get_version())
    except Exception as e:
        print("processor info unavailable:", e)

    elecs = list(xp.list_elec('EMG')) or list(xp.list_elec(''))
    print("\nElectrodes:", elecs)
    if not elecs:
        print("No electrodes - nothing to test.")
        return

    targets = elecs[:2]

    for elec in targets:
        try:
            fe = xp.get_fe(elec)
        except Exception:
            fe = '?'
        try:
            reported = xp.get_fe_streams(elec)
        except Exception as e:
            reported = f"<error {e}>"
        print(f"\n=== elec {elec} (FE {fe}) ===")
        print(f"  get_fe_streams reports : {reported}")

        # What is already selected, before we touch anything? A stream Trellis
        # has claimed can refuse to be re-selected from here.
        for s in (reported if isinstance(reported, list) else []):
            canon = normalize_stream(s)
            try:
                state = xp.signal(elec, s)
            except Exception as e:
                state = f"<error {e}>"
            readable = "yes" if canon in STREAM_READERS else "no reader"
            print(f"    {s:<10} currently_on={str(state):<7} readable={readable}")

        # Now try to turn each one on and keep the real return code.
        print("  --- enable attempts (raw return codes) ---")
        for s in (reported if isinstance(reported, list) else []):
            code = raw_signal_set(elec, s, True)
            if code < 0:
                print(f"    {s:<10} FAILED  code={code}  -> {decode(code)}")
            else:
                sleep(0.01)
                try:
                    now_on = xp.signal(elec, s)
                except Exception:
                    now_on = '?'
                print(f"    {s:<10} ok      code={code}  verified_on={now_on}")
                # Try an actual read - selection succeeding doesn't guarantee data.
                canon = normalize_stream(s)
                if canon in STREAM_READERS:
                    reader, fs = STREAM_READERS[canon]
                    try:
                        data, ts = reader(100, [elec], xp.time())
                        print(f"    {'':<10} read {len(data)} pts @ {fs} Hz")
                    except Exception as e:
                        print(f"    {'':<10} read FAILED: {e}")
                # leave it as we found it
                raw_signal_set(elec, s, False)

    # Enabling on both electrodes at once can hit per-stream channel limits
    # that a single-electrode test would not.
    print(f"\n=== both electrodes {targets} at once ===")
    for s in ('hires', 'hifreq', 'raw', 'lfp', 'emg'):
        codes = [raw_signal_set(e, s, True) for e in targets]
        ok = all(c >= 0 for c in codes)
        sleep(0.01)
        verified = []
        for e in targets:
            try:
                verified.append(xp.signal(e, s))
            except Exception:
                verified.append('?')
        print(f"  {s:<8} codes={codes} verified={verified}"
              + ("" if ok else f"  -> {decode(min(codes))}"))
        for e in targets:
            raw_signal_set(e, s, False)

    xp._close()
    print("\nClosed.")


if __name__ == '__main__':
    main()
