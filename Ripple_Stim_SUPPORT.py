"""
Biphasic bipolar stimulation for the Ripple Grapevine, via xipppy.

Everything that defines a biphasic pulse train is a parameter on StimParams.
Nothing here assumes a fixed pulse shape.

Two facts from xipppy/stim.py drive the whole design:

  * StimSegment.length is in NIP clocks of 33.333 us (30 kHz), NOT microseconds,
    and amplitude is in resolution STEPS capped at 127. The real current is
    steps * (uA/step), where uA/step comes from stim_get_res_options(elec).
  * StimSeq(electrode, period, repeats, *segments) can play a whole train on the
    NIP clock. A software sleep() loop jitters with the OS; period/repeats does
    not. A sequence may hold up to 249 segments.

So trains are built two ways:
  CONSTANT amplitude -> one pulse in segments, period/repeats does the timing.
                        Up to 4095 pulses.
  RAMPED amplitude   -> every pulse written out explicitly with its own
                        amplitude, separated by disabled gap segments. Still
                        hardware-timed, but the 249-segment cap limits it to
                        ~62 pulses.

The waveform drawn in the GUI is rendered FROM THE SEGMENTS THAT GET SENT, so
the picture cannot drift away from what the hardware actually plays.
"""

import numpy as np
import xipppy as xp
from time import sleep

from Ripple_Settings_SUPPORT import (
    NIP_CLOCK_HZ, STIM_CLOCK_US,
    STIM_MAX_AMP_STEPS, STIM_MAX_SEG_CLOCKS, STIM_MAX_PERIOD_CLOCKS,
    STIM_MAX_REPEATS, STIM_MAX_SEGMENTS,
    STIM_CHARGE_WARN_NC,
)


class StimParamError(ValueError):
    """Raised when a parameter set cannot be realized on the hardware."""


class StimParams:
    """
    Every knob for a biphasic bipolar train. Times are held in NIP clocks
    internally but the *_us / *_hz helpers convert both ways so the GUI can
    work in physical units.
    """

    def __init__(self,
                 cathode_elec=0,
                 anode_elec=1,
                 res_index=4,
                 ua_per_step=20.0,
                 amp_steps=80,
                 phase_clocks=200,
                 interphase_clocks=100,
                 anodic_phase_clocks=None,   # None -> mirror the cathodic phase
                 anodic_amp_steps=None,      # None -> mirror the cathodic amp
                 cathodic_first=True,
                 frequency_hz=1.0,
                 n_pulses=20,
                 ramp_enabled=False,
                 ramp_end_steps=None,
                 fast_settle=False,
                 interpulse_delay=0):
        self.cathode_elec = int(cathode_elec)
        self.anode_elec = int(anode_elec)
        self.res_index = int(res_index)
        self.ua_per_step = float(ua_per_step)

        self.amp_steps = int(amp_steps)
        self.phase_clocks = int(phase_clocks)
        self.interphase_clocks = int(interphase_clocks)
        self.anodic_phase_clocks = anodic_phase_clocks
        self.anodic_amp_steps = anodic_amp_steps
        self.cathodic_first = bool(cathodic_first)

        self.frequency_hz = float(frequency_hz)
        self.n_pulses = int(n_pulses)

        self.ramp_enabled = bool(ramp_enabled)
        self.ramp_end_steps = ramp_end_steps

        self.fast_settle = bool(fast_settle)
        self.interpulse_delay = int(interpulse_delay)

    # --- derived, in physical units ---------------------------------------
    @property
    def anodic_clocks(self):
        return (self.phase_clocks if self.anodic_phase_clocks is None
                else int(self.anodic_phase_clocks))

    @property
    def anodic_steps(self):
        return (self.amp_steps if self.anodic_amp_steps is None
                else int(self.anodic_amp_steps))

    @property
    def phase_us(self):
        return self.phase_clocks * STIM_CLOCK_US

    @property
    def anodic_us(self):
        return self.anodic_clocks * STIM_CLOCK_US

    @property
    def interphase_us(self):
        return self.interphase_clocks * STIM_CLOCK_US

    @property
    def amp_ua(self):
        return self.amp_steps * self.ua_per_step

    @property
    def anodic_ua(self):
        return self.anodic_steps * self.ua_per_step

    @property
    def pulse_clocks(self):
        """Total clocks occupied by one biphasic pulse."""
        return self.phase_clocks + self.interphase_clocks + self.anodic_clocks

    @property
    def pulse_us(self):
        return self.pulse_clocks * STIM_CLOCK_US

    @property
    def period_clocks(self):
        if self.frequency_hz <= 0:
            return 0
        return int(round(NIP_CLOCK_HZ / self.frequency_hz))

    @property
    def actual_frequency_hz(self):
        """Frequency after rounding the period to whole clocks."""
        p = self.period_clocks
        return (NIP_CLOCK_HZ / p) if p else 0.0

    @property
    def train_duration_s(self):
        if self.n_pulses <= 0:
            return 0.0
        return (self.n_pulses - 1) / max(self.actual_frequency_hz, 1e-9) \
            + self.pulse_us * 1e-6

    @property
    def cathodic_charge_nc(self):
        """Charge in the leading phase, nC = uA * us / 1000."""
        return self.amp_ua * self.phase_us / 1000.0

    @property
    def anodic_charge_nc(self):
        return self.anodic_ua * self.anodic_us / 1000.0

    @property
    def charge_imbalance_nc(self):
        return self.cathodic_charge_nc - self.anodic_charge_nc

    @property
    def is_charge_balanced(self):
        ref = max(abs(self.cathodic_charge_nc), 1e-12)
        return abs(self.charge_imbalance_nc) / ref < 1e-6

    @property
    def uses_explicit_segments(self):
        """Ramping needs one segment group per pulse instead of repeats."""
        return self.ramp_enabled and self.n_pulses > 1

    def amplitude_schedule(self):
        """Per-pulse amplitude in steps (length n_pulses)."""
        n = max(self.n_pulses, 0)
        if n == 0:
            return []
        if not self.uses_explicit_segments:
            return [self.amp_steps] * n
        end = self.amp_steps if self.ramp_end_steps is None else int(self.ramp_end_steps)
        return [int(round(v)) for v in np.linspace(self.amp_steps, end, n)]

    # --- validation --------------------------------------------------------
    def validate(self):
        """
        Return a list of human-readable problems. Empty list == safe to send.
        Hardware limits come straight from xipppy's own setters.
        """
        errs = []
        if self.cathode_elec == self.anode_elec:
            errs.append("Cathode and anode must be different electrodes - "
                        "bipolar stim needs current to flow between two contacts.")
        for name, e in (("cathode", self.cathode_elec), ("anode", self.anode_elec)):
            if not 0 <= e <= 511:
                errs.append(f"{name} electrode {e} outside [0, 511]")

        for name, steps in (("amplitude", self.amp_steps),
                            ("anodic amplitude", self.anodic_steps)):
            if not 0 <= steps <= STIM_MAX_AMP_STEPS:
                errs.append(f"{name} {steps} steps outside [0, {STIM_MAX_AMP_STEPS}]")

        for name, clk in (("phase width", self.phase_clocks),
                          ("anodic phase width", self.anodic_clocks)):
            if not 1 <= clk <= STIM_MAX_SEG_CLOCKS:
                errs.append(f"{name} {clk} clocks outside [1, {STIM_MAX_SEG_CLOCKS}]")
        if not 0 <= self.interphase_clocks <= STIM_MAX_SEG_CLOCKS:
            errs.append(f"interphase {self.interphase_clocks} clocks outside "
                        f"[0, {STIM_MAX_SEG_CLOCKS}]")

        if self.n_pulses < 1:
            errs.append("Number of pulses must be at least 1.")

        if self.n_pulses > 1:
            if self.period_clocks <= 0:
                errs.append("Frequency must be > 0 for a multi-pulse train.")
            elif self.period_clocks < self.pulse_clocks:
                errs.append(
                    f"{self.frequency_hz:.3f} Hz gives a period of "
                    f"{self.period_clocks} clocks ({self.period_clocks*STIM_CLOCK_US:.0f} us) "
                    f"but one pulse already takes {self.pulse_clocks} clocks "
                    f"({self.pulse_us:.0f} us). Max frequency here is "
                    f"{NIP_CLOCK_HZ/self.pulse_clocks:.1f} Hz.")
            elif self.period_clocks > STIM_MAX_PERIOD_CLOCKS:
                errs.append(
                    f"{self.frequency_hz:.3f} Hz needs a period of "
                    f"{self.period_clocks} clocks, over the {STIM_MAX_PERIOD_CLOCKS} "
                    f"limit. Minimum frequency is "
                    f"{NIP_CLOCK_HZ/STIM_MAX_PERIOD_CLOCKS:.3f} Hz.")

        if self.uses_explicit_segments:
            n_seg = self.segments_per_pulse() * self.n_pulses
            if n_seg > STIM_MAX_SEGMENTS:
                max_pulses = STIM_MAX_SEGMENTS // self.segments_per_pulse()
                errs.append(
                    f"A ramped train writes every pulse out explicitly "
                    f"({self.segments_per_pulse()} segments each), needing {n_seg} "
                    f"segments - the limit is {STIM_MAX_SEGMENTS}. Reduce to "
                    f"{max_pulses} pulses or turn the ramp off.")
            gap = self.period_clocks - self.pulse_clocks
            if self.n_pulses > 1 and gap > STIM_MAX_SEG_CLOCKS:
                errs.append(
                    f"Ramped trains need an inter-pulse gap segment of {gap} clocks, "
                    f"over the {STIM_MAX_SEG_CLOCKS} limit. Raise the frequency "
                    f"above {NIP_CLOCK_HZ/(STIM_MAX_SEG_CLOCKS+self.pulse_clocks):.2f} Hz.")
            for steps in self.amplitude_schedule():
                if not 0 <= steps <= STIM_MAX_AMP_STEPS:
                    errs.append(f"Ramp reaches {steps} steps, outside "
                                f"[0, {STIM_MAX_AMP_STEPS}]")
                    break
        return errs

    def warnings(self):
        """Non-fatal things worth surfacing before stimulating."""
        warns = []
        if not self.is_charge_balanced:
            warns.append(
                f"Charge is NOT balanced: cathodic {self.cathodic_charge_nc:.1f} nC "
                f"vs anodic {self.anodic_charge_nc:.1f} nC "
                f"(net {self.charge_imbalance_nc:+.1f} nC per pulse). Net DC charge "
                f"drives electrode corrosion and tissue damage - match "
                f"amplitude x width across the two phases unless you intend this.")
        q = abs(self.cathodic_charge_nc)
        if q > STIM_CHARGE_WARN_NC:
            warns.append(
                f"{q:.0f} nC per phase is above the {STIM_CHARGE_WARN_NC:.0f} nC "
                f"review threshold ({self.amp_ua:.0f} uA x {self.phase_us:.0f} us). "
                f"Confirm this is intended for your electrode area.")
        if self.interphase_clocks == 0:
            warns.append(
                "Interphase interval is 0 - the anodic phase starts immediately "
                "and will cancel part of the cathodic response.")
        return warns

    def segments_per_pulse(self):
        """cathodic + optional interphase + anodic, plus a gap when ramping."""
        n = 2 + (1 if self.interphase_clocks > 0 else 0)
        return n + 1   # trailing inter-pulse gap

    def summary(self):
        return (
            f"{self.amp_ua:.0f} uA ({self.amp_steps} steps x {self.ua_per_step:g} uA) | "
            f"{self.phase_us:.0f} us/phase, {self.interphase_us:.0f} us gap | "
            f"{'cathodic' if self.cathodic_first else 'anodic'}-first | "
            f"{self.actual_frequency_hz:.2f} Hz x {self.n_pulses} pulses "
            f"= {self.train_duration_s:.2f} s | "
            f"{self.cathodic_charge_nc:.1f} nC/phase | "
            f"e{self.cathode_elec}(-) <-> e{self.anode_elec}(+)")


class RippleStimulator:
    """Builds, previews and sends biphasic bipolar trains."""

    def __init__(self, status_update=None):
        self.status_update = status_update
        self.last_segments = None      # segments of the cathode-leading channel
        self.last_params = None

    def _emit(self, msg):
        if self.status_update is None:
            print(msg)
        elif hasattr(self.status_update, "emit"):
            self.status_update.emit(msg)
        else:
            self.status_update(msg)

    # --- hardware queries --------------------------------------------------
    def list_stim_electrodes(self):
        try:
            return list(xp.list_elec('stim'))
        except Exception as e:
            self._emit(f"[Stim] could not list stim electrodes: {e}")
            return []

    def resolution_options(self, elec):
        """[uA/step, ...] indexed by resolution level, straight from the FE."""
        try:
            return [float(v) for v in xp.stim_get_res_options(elec)]
        except Exception as e:
            self._emit(f"[Stim] could not read resolution options for e{elec}: {e}")
            return []

    def apply_resolution(self, params):
        """
        Set the stim resolution on both electrodes of the pair. Must happen
        while stim is disabled.
        """
        xp.stim_enable_set(False)
        sleep(0.001)
        for elec in (params.cathode_elec, params.anode_elec):
            xp.stim_set_res(elec, params.res_index)
        sleep(0.001)

    # --- segment construction ---------------------------------------------
    def _pulse_segments(self, params, amp_steps, leading_cathodic):
        """
        One biphasic pulse. leading_cathodic picks which phase comes first;
        the two electrodes of a bipolar pair get opposite leading polarity so
        current flows between them.
        """
        anodic_steps = (amp_steps if params.anodic_amp_steps is None
                        else int(params.anodic_amp_steps))
        first_pol = -1 if leading_cathodic else 1
        second_pol = -first_pol

        segs = [xp.StimSegment(params.phase_clocks, amp_steps, first_pol,
                               fast_settle=params.fast_settle)]
        if params.interphase_clocks > 0:
            segs.append(xp.StimSegment(params.interphase_clocks, 0, 1,
                                       enable=False))
        segs.append(xp.StimSegment(params.anodic_clocks, anodic_steps, second_pol,
                                   fast_settle=params.fast_settle))
        return segs

    def build_sequences(self, params):
        """
        Return [StimSeq_cathode_leading, StimSeq_anode_leading].

        Constant amplitude -> period/repeats carries the train.
        Ramped            -> pulses written out with gap segments between them.
        """
        errs = params.validate()
        if errs:
            raise StimParamError("; ".join(errs))

        seqs = []
        for leading_cathodic, elec in ((True, params.cathode_elec),
                                       (False, params.anode_elec)):
            if not params.uses_explicit_segments:
                segs = self._pulse_segments(params, params.amp_steps, leading_cathodic)
                seq = xp.StimSeq(elec, params.period_clocks, params.n_pulses,
                                 *segs, action=xp.StimSeq.STIM_IMMED)
            else:
                schedule = params.amplitude_schedule()
                gap = max(params.period_clocks - params.pulse_clocks, 1)
                segs = []
                for i, amp in enumerate(schedule):
                    segs.extend(self._pulse_segments(params, amp, leading_cathodic))
                    if i < len(schedule) - 1:
                        segs.append(xp.StimSegment(gap, 0, 1, enable=False))
                seq = xp.StimSeq(elec, params.period_clocks, 1,
                                 *segs, action=xp.StimSeq.STIM_IMMED)
            seqs.append(seq)

        if leading_cathodic is not None:
            self.last_params = params
        return seqs

    # --- preview (no hardware touched) ------------------------------------
    def render_waveform(self, params, channel='cathode', max_points=200000):
        """
        (t_ms, i_uA) for one channel of the pair, built from the same segment
        description that gets sent. Returns the full train.
        """
        leading_cathodic = (channel == 'cathode')
        schedule = params.amplitude_schedule()
        if not schedule:
            return np.zeros(0), np.zeros(0)

        gap_clocks = max(params.period_clocks - params.pulse_clocks, 0)
        anodic_steps = (params.anodic_amp_steps
                        if params.anodic_amp_steps is not None else None)

        # (clocks, uA) runs, in order
        runs = []
        for i, amp in enumerate(schedule):
            a_steps = amp if anodic_steps is None else int(anodic_steps)
            first = -amp if leading_cathodic else amp
            second = a_steps if leading_cathodic else -a_steps
            runs.append((params.phase_clocks, first * params.ua_per_step))
            if params.interphase_clocks > 0:
                runs.append((params.interphase_clocks, 0.0))
            runs.append((params.anodic_clocks, second * params.ua_per_step))
            if i < len(schedule) - 1 and gap_clocks > 0:
                runs.append((gap_clocks, 0.0))

        # Step plot: two points per run so edges stay vertical.
        t_ms, i_ua = [], []
        clk = 0
        for length, amp in runs:
            t0 = clk * STIM_CLOCK_US / 1000.0
            t1 = (clk + length) * STIM_CLOCK_US / 1000.0
            t_ms.extend((t0, t1))
            i_ua.extend((amp, amp))
            clk += length
        # return to zero at the end
        t_ms.append(clk * STIM_CLOCK_US / 1000.0)
        i_ua.append(0.0)

        t = np.asarray(t_ms, dtype=float)
        y = np.asarray(i_ua, dtype=float)
        if t.size > max_points:
            keep = np.linspace(0, t.size - 1, max_points).astype(int)
            t, y = t[keep], y[keep]
        return t, y

    def render_single_pulse(self, params, channel='cathode', pad_frac=0.35):
        """(t_ms, i_uA) for just the first pulse, padded either side."""
        leading_cathodic = (channel == 'cathode')
        amp = params.amplitude_schedule()[0] if params.n_pulses else params.amp_steps
        a_steps = (amp if params.anodic_amp_steps is None
                   else int(params.anodic_amp_steps))
        first = -amp if leading_cathodic else amp
        second = a_steps if leading_cathodic else -a_steps

        pad = max(int(params.pulse_clocks * pad_frac), 1)
        runs = [(pad, 0.0),
                (params.phase_clocks, first * params.ua_per_step)]
        if params.interphase_clocks > 0:
            runs.append((params.interphase_clocks, 0.0))
        runs.append((params.anodic_clocks, second * params.ua_per_step))
        runs.append((pad, 0.0))

        t_ms, i_ua, clk = [], [], 0
        for length, a in runs:
            t0 = (clk - pad) * STIM_CLOCK_US / 1000.0
            t1 = (clk + length - pad) * STIM_CLOCK_US / 1000.0
            t_ms.extend((t0, t1))
            i_ua.extend((a, a))
            clk += length
        return np.asarray(t_ms, float), np.asarray(i_ua, float)

    def pulse_marker_times_ms(self, params):
        """Start time of each pulse, for marking the train plot."""
        if params.n_pulses <= 0:
            return np.zeros(0)
        step = params.period_clocks * STIM_CLOCK_US / 1000.0
        return np.arange(params.n_pulses) * step

    # --- sending -----------------------------------------------------------
    def send_train(self, params):
        """Apply resolution, enable stim, and fire the train. Returns the seqs."""
        seqs = self.build_sequences(params)

        self.apply_resolution(params)
        xp.stim_enable_set(True)
        sleep(0.001)

        xp.StimSeq.send_stim_seqs(seqs)
        self.last_params = params
        self._emit(f"[Stim] sent -> {params.summary()}")
        if params.uses_explicit_segments:
            sched = params.amplitude_schedule()
            self._emit(f"[Stim] ramp {sched[0]}->{sched[-1]} steps "
                       f"({sched[0]*params.ua_per_step:.0f}->"
                       f"{sched[-1]*params.ua_per_step:.0f} uA) over {len(sched)} pulses")
        return seqs

    def stop(self):
        """Global stim disable - the fastest way to stop output."""
        try:
            xp.stim_enable_set(False)
            self._emit("[Stim] output DISABLED")
            return True
        except Exception as e:
            self._emit(f"[Stim] failed to disable: {e}")
            return False

    def is_enabled(self):
        try:
            return bool(xp.stim_enable())
        except Exception:
            return False
