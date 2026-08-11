from scipy.signal import butter, lfilter, lfilter_zi, iirnotch
import numpy as np
from Ripple_Settings_SUPPORT import *

class SignalProcessor:
    def __init__(self, num_channels = 2, fs = EMG_SAMPLE_RATE, highpass_cutoff=HPF, notch_freq=NOTCH, notch_q=NOTCH_Q, highpass_order=HPF_O, highcut=LPF_HC, order=LPF_O):
        self.num_channels = num_channels
        self.fs = fs
        self.highpass_cutoff = highpass_cutoff
        self.notch_freq = notch_freq
        self.notch_q = notch_q
        self.highpass_order = highpass_order
        self.highcut_lpf = highcut
        self.bpf_order = order

        # Design filters
        self.b_high, self.a_high = self._design_highpass_filter()
        self.b_low, self.a_low = self._design_lowpass_filter()
        self.b_notch, self.a_notch = self._design_notch_filter()

        self._init_filter_states()

    def _init_filter_states(self):
        n = self.num_channels
        # Unit-step steady-state templates. lfilter_zi assumes an input amplitude
        # of 1.0, so these must be scaled by the FIRST sample of each stage's
        # input before use (done lazily on the first filter call per channel).
        # Otherwise the filter "rings down" from 1.0 and injects a large startup
        # transient that contaminates the signal (and calibration).
        self._ziu_high  = lfilter_zi(self.b_high,  self.a_high)
        self._ziu_low   = lfilter_zi(self.b_low,   self.a_low)
        self._ziu_notch = lfilter_zi(self.b_notch, self.a_notch)

        # None == "not primed yet"; the first sample seen primes the state.
        self.zi_high  = [None] * n
        self.zi_low   = [None] * n
        self.zi_notch = [None] * n

    def _design_notch_filter(self):
        b, a = iirnotch(self.notch_freq, self.notch_q, self.fs)
        return b, a

    def _design_highpass_filter(self):
        nyquist = 0.5 * self.fs
        normal_cutoff = self.highpass_cutoff / nyquist
        b, a = butter(self.highpass_order, normal_cutoff, btype='high', analog=False)
        return b, a

    def _design_lowpass_filter(self):
        nyq = 0.5 * self.fs
        low_pass = self.highcut_lpf / nyq
        b, a = butter(self.bpf_order, low_pass, btype='low')
        return b, a

    def rectify_emg(self, data):
        return np.abs(data)

    def moving_window_rms(self, signal, window_size):
        signal = np.asarray(signal, dtype=np.float64)
        return np.sqrt(np.convolve(signal ** 2, np.ones(window_size) / window_size, mode='same'))

    def non_ovlp_calculate_rms(self, data, window_size):
        n_channels, n_samples = data.shape
        n_windows = n_samples // window_size
        rms_features = np.zeros((n_channels, n_windows))
        for ch in range(n_channels):
            for i in range(n_windows):
                window = data[ch, i * window_size:(i + 1) * window_size]
                rms_features[ch, i] = np.sqrt(np.mean(window ** 2))
        return rms_features

    def calculate_rms(self, window):
        return np.sqrt(np.mean(np.array(window) ** 2))

    def preprocess_filters(self, data, channel):
        """Real-time causal filtering — updates zi state for this channel."""
        data = np.array(data, dtype=float)
        # Prime each stage from the first sample of ITS OWN input the first time.
        if self.zi_high[channel] is None:
            self.zi_high[channel] = self._ziu_high * data[0]
        data, self.zi_high[channel] = lfilter(self.b_high, self.a_high, data, zi=self.zi_high[channel])
        if self.zi_notch[channel] is None:
            self.zi_notch[channel] = self._ziu_notch * data[0]  # data is now the HPF output
        data, self.zi_notch[channel] = lfilter(self.b_notch, self.a_notch, data, zi=self.zi_notch[channel])
        return data

    def postprocess_filter(self, data, channel):
        data = np.array(data, dtype=float)
        if self.zi_low[channel] is None:
            self.zi_low[channel] = self._ziu_low * data[0]
        data, self.zi_low[channel]  = lfilter(self.b_low,  self.a_low,  data, zi=self.zi_low[channel])
        return data

    def reset_filter_states(self):
        """Reset all filter zi states to initial conditions."""
        self._init_filter_states()

    def reinitialise_filters(self, fs=None, num_channels=None):
        """Rebuild filter coefficients with new or existing fs, reset all states."""
        if fs is not None:
            self.fs = fs
        if num_channels is not None:
            self.num_channels = num_channels
        self.b_high,  self.a_high  = self._design_highpass_filter()
        self.b_low,   self.a_low   = self._design_lowpass_filter()
        self.b_notch, self.a_notch = self._design_notch_filter()
        self._init_filter_states()
        # print(f"[SignalProcessor] Filters reinitialised at fs={self.fs} Hz")

    def preprocess_filters_offline(self, data, channel):
        """
        Same causal lfilter as real-time but with fresh zi state.
        Use for calibration processing so streaming state doesn't contaminate.
        """
        data = np.array(data, dtype=float)
        zi_high  = lfilter_zi(self.b_high,  self.a_high) * data[0]
        data, _ = lfilter(self.b_high,  self.a_high,  data, zi=zi_high)
        zi_notch = lfilter_zi(self.b_notch, self.a_notch) * data[0]  # data is now HPF output
        data, _ = lfilter(self.b_notch, self.a_notch, data, zi=zi_notch)
        return data

    def postprocess_filter_offline(self, data, channel):
        """Same as postprocess_filter but with fresh zi state."""
        data = np.array(data, dtype=float)
        zi_low = lfilter_zi(self.b_low, self.a_low) * data[0]
        data, _ = lfilter(self.b_low, self.a_low, data, zi=zi_low)
        return data

    # Proportional control inference function
    def max_chan_controller(self, emg_win_val):
        max_chan = np.argmax(emg_win_val)
        return max_chan

    def normalize_signal(self, signal, baseline_mean, baseline_std, mvc_value):
        """
        Normalize the signal based on baseline and MVC values.
        """
        # Ensure inputs are numpy arrays for element-wise operations
        signal = np.array(signal)
        baseline_mean = np.array(baseline_mean)
        baseline_std = np.array(baseline_std)
        mvc_value = np.array(mvc_value)

        # Avoid division by zero by adding a small epsilon to the denominator
        epsilon = 1e-9
        normalized_signal = (signal - (baseline_mean + baseline_std)) / (mvc_value - (baseline_mean + baseline_std) + epsilon)
        return normalized_signal

    def percentage_mvc_calc_v1(self, emg_window_val, mvc_dict, baseline_mean_values, baseline_std_values, chan):
        data_packet = [0]*self.num_channels
        chan_send = None
        baseline_mean_val = baseline_mean_values[chan]
        baseline_std_val = baseline_std_values[chan]
        baseline_val = float(baseline_mean_val + baseline_std_val)

        mvc_signal_1 = mvc_dict["medial"]
        sig_chan_1 = self.max_chan_controller(mvc_signal_1)

        mvc_signal_2 = mvc_dict["lateral"]
        sig_chan_2 = self.max_chan_controller(mvc_signal_2)

        clean_sig = max(baseline_val, emg_window_val[chan])
        if chan == sig_chan_1:
            percen = (clean_sig - baseline_val) / (float(mvc_signal_1[sig_chan_1]) - baseline_val)
            chan_send = "lateral"
        elif chan == sig_chan_2:
            percen = (clean_sig - baseline_val) / (float(mvc_signal_2[sig_chan_2]) - baseline_val)
            chan_send = "medial"
        else:
            percen = 0

        if percen < 0 or percen is None:
            percen = 0

        data_packet[chan] = percen *100
        return (data_packet, chan_send)

    def percentage_mvc_calc_v2(self, emg_window_val, mvc_dict, baseline_mean_values, baseline_std_values, alpha = 1e-9, thresh = 0.4, emg_control=False):
        """
        Difference over sum logic, to tackle concontraction.
        """
        data_packet = [0]*self.num_channels
        chan_send = None

        if emg_control == False:
            return (data_packet, chan_send, None, None, None, None, None, None)

        mvc_signal_1 = np.array(mvc_dict["lateral"])
        mvc_signal_2 = np.array(mvc_dict["medial"])
        sig_chan_1 = self.max_chan_controller(mvc_signal_1)
        sig_chan_2 = self.max_chan_controller(mvc_signal_2)

        baseline_val = np.array(baseline_mean_values) + np.array(baseline_std_values)

        # Scale emg_window_val to match units (assuming baseline/MVC in uV, window in V)
        emg_window_val_scaled = np.array(emg_window_val) * 1000
        clean_sig = np.array([max(float(baseline_val[i]), float(emg_window_val_scaled[i])) for i in range(self.num_channels)])

        percen_lateral = (clean_sig - baseline_val) / (mvc_signal_1 - baseline_val + alpha) # Normalized percentage for each channel
        percen_medial = (clean_sig - baseline_val) / (mvc_signal_2 - baseline_val + alpha) # Normalized percentage for each channel

        # medial is positive, lateral is negative
        percen_diffsum_medial = (percen_medial[sig_chan_2] - percen_lateral[sig_chan_1]) / (percen_lateral[sig_chan_1] + percen_medial[sig_chan_2] + alpha)
        percen_diffsum_lateral = (percen_lateral[sig_chan_1] - percen_medial[sig_chan_2]) / (percen_lateral[sig_chan_1] + percen_medial[sig_chan_2] + alpha)
        percen_lateral_activation = percen_lateral[sig_chan_1] / (percen_lateral[sig_chan_1] + percen_medial[sig_chan_2] + alpha)
        percen_medial_activation = percen_medial[sig_chan_2] / (percen_lateral[sig_chan_1] + percen_medial[sig_chan_2] + alpha)
        co_contraction_index = 2 * min(percen_lateral[sig_chan_1], percen_medial[sig_chan_2]) / (percen_lateral[sig_chan_1] + percen_medial[sig_chan_2] + alpha)

        if percen_diffsum_medial > thresh and percen_diffsum_lateral < -thresh: # If this channel is the dominant lateralor channel
            percen = percen_medial[sig_chan_2] # Only consider as lateralor activation if the difference is positive
            chan_send = "medial"
            chan = sig_chan_2
            data_packet[chan] = percen * 100
            data_packet[sig_chan_1] = percen_lateral[sig_chan_1] * 100

        elif percen_diffsum_lateral > thresh and percen_diffsum_medial < -thresh: # If this channel is the dominant medialsor channel
            percen = percen_lateral[sig_chan_1] # Only consider as medialsor activation if the difference is negative
            chan_send = "lateral"
            chan = sig_chan_1
            data_packet[chan] = percen * 100
            data_packet[sig_chan_2] = percen_medial[sig_chan_2] * 100

        elif co_contraction_index > thresh: # If both channels are active and co-contraction index is above threshold, consider it as cocontraction and set to 0
            percen = 0
            chan_send = "cocontraction"
            chan = None
            data_packet = [0]*self.num_channels

        elif percen_diffsum_medial < -thresh and percen_diffsum_lateral < -thresh: # If both channels are active but neither is dominant, consider it as cocontraction and set to 0
            percen = 0
            chan_send = "cocontraction"
            chan = None
            data_packet = [0]*self.num_channels

        elif percen_diffsum_medial > thresh and percen_diffsum_lateral > thresh: # If both channels are active and both are above the threshold, consider it as cocontraction and set to 0
            percen = 0
            chan_send = "cocontraction"
            chan = None
            data_packet = [0]*self.num_channels

        elif max(percen_diffsum_medial, percen_diffsum_lateral) <= thresh: # If both channels are below the threshold, consider it as no activation and set to 0
            percen = 0
            chan_send = "no_activation"
            chan = None
            data_packet = [0]*self.num_channels

        else:
            percen = 0
            chan_send = None
            chan = None
            data_packet = [0]*self.num_channels

        return (data_packet, chan_send, percen_lateral, percen_medial, percen_diffsum_lateral, percen_diffsum_medial, percen_lateral_activation, percen_medial_activation, sig_chan_1, sig_chan_2, co_contraction_index, )


    def percentage_mvc_calc_v3(self, emg_window_val, mvc_dict, baseline_mean_values, baseline_std_values, alpha = 1e-9, thresh = 0.4, emg_control=False):
        """
        Using Same MVC values for both channels. More useful for Game control
        """
        data_packet = [0]*self.num_channels
        chan_send = None

        if emg_control == False:
            return (data_packet, chan_send, None, None, None, None, None, None)

        mvc_signal_1 = np.array(mvc_dict["lateral"])
        mvc_signal_2 = np.array(mvc_dict["medial"])
        sig_chan_1 = 1
        sig_chan_2 = 0

        baseline_val = np.array(baseline_mean_values) + np.array(baseline_std_values)

        # Scale emg_window_val to match units (assuming baseline/MVC in uV, window in V)
        emg_window_val_scaled = np.array(emg_window_val) * 1000
        clean_sig = np.array([max(float(baseline_val[i]), float(emg_window_val_scaled[i])) for i in range(self.num_channels)])

        percen_lateral = (clean_sig - baseline_val) / (mvc_signal_1 - baseline_val + alpha) # Normalized percentage for each channel
        percen_medial = (clean_sig - baseline_val) / (mvc_signal_2 - baseline_val + alpha) # Normalized percentage for each channel

        # medial is positive, lateral is negative
        percen_diffsum_medial = (percen_medial[sig_chan_2] - percen_lateral[sig_chan_1]) / (percen_lateral[sig_chan_1] + percen_medial[sig_chan_2] + alpha)
        percen_diffsum_lateral = (percen_lateral[sig_chan_1] - percen_medial[sig_chan_2]) / (percen_lateral[sig_chan_1] + percen_medial[sig_chan_2] + alpha)
        percen_lateral_activation = percen_lateral[sig_chan_1] / (percen_lateral[sig_chan_1] + percen_medial[sig_chan_2] + alpha)
        percen_medial_activation = percen_medial[sig_chan_2] / (percen_lateral[sig_chan_1] + percen_medial[sig_chan_2] + alpha)
        co_contraction_index = 2 * min(percen_lateral[sig_chan_1], percen_medial[sig_chan_2]) / (percen_lateral[sig_chan_1] + percen_medial[sig_chan_2] + alpha)

        if percen_diffsum_medial > thresh and percen_diffsum_lateral < -thresh: # If this channel is the dominant lateralor channel
            percen = percen_medial[sig_chan_2] # Only consider as lateralor activation if the difference is positive
            chan_send = "medial"
            chan = sig_chan_2
            data_packet[chan] = percen * 100
            data_packet[sig_chan_1] = percen_lateral[sig_chan_1] * 100

        elif percen_diffsum_lateral > thresh and percen_diffsum_medial < -thresh: # If this channel is the dominant medialsor channel
            percen = percen_lateral[sig_chan_1] # Only consider as medialsor activation if the difference is negative
            chan_send = "lateral"
            chan = sig_chan_1
            data_packet[chan] = percen * 100
            data_packet[sig_chan_2] = percen_medial[sig_chan_2] * 100

        elif co_contraction_index > thresh: # If both channels are active and co-contraction index is above threshold, consider it as cocontraction and set to 0
            percen = 0
            chan_send = "cocontraction"
            chan = None
            data_packet = [0]*self.num_channels

        elif percen_diffsum_medial < -thresh and percen_diffsum_lateral < -thresh: # If both channels are active but neither is dominant, consider it as cocontraction and set to 0
            percen = 0
            chan_send = "cocontraction"
            chan = None
            data_packet = [0]*self.num_channels

        elif percen_diffsum_medial > thresh and percen_diffsum_lateral > thresh: # If both channels are active and both are above the threshold, consider it as cocontraction and set to 0
            percen = 0
            chan_send = "cocontraction"
            chan = None
            data_packet = [0]*self.num_channels

        elif max(percen_diffsum_medial, percen_diffsum_lateral) <= thresh: # If both channels are below the threshold, consider it as no activation and set to 0
            percen = 0
            chan_send = "no_activation"
            chan = None
            data_packet = [0]*self.num_channels

        else:
            percen = 0
            chan_send = None
            chan = None
            data_packet = [0]*self.num_channels

        return (data_packet, chan_send, percen_lateral, percen_medial, percen_diffsum_lateral, percen_diffsum_medial, percen_lateral_activation, percen_medial_activation, sig_chan_1, sig_chan_2, co_contraction_index)

    def percentage_mvc_calc_v4(self, emg_window_val, mvc_dict, baseline_mean_values, baseline_std_values, alpha = 1e-9, thresh = 0.0, emg_control=False):
        """
        Just simpler version of V3, Only for Bar Game training
        """
        data_packet = [0]*self.num_channels
        chan_send = None

        if emg_control == False:
            return (data_packet, chan_send, None, None, None, None, None, None)

        mvc_signal_1 = np.array(mvc_dict["lateral"])
        mvc_signal_2 = np.array(mvc_dict["medial"])
        sig_chan_1 = 1
        sig_chan_2 = 0

        baseline_val = np.array(baseline_mean_values) + np.array(baseline_std_values)

        # Scale emg_window_val to match units (assuming baseline/MVC in uV, window in V)
        emg_window_val_scaled = np.array(emg_window_val) * 1000
        clean_sig = np.array([max(float(baseline_val[i]), float(emg_window_val_scaled[i])) for i in range(self.num_channels)])

        percen_lateral = (clean_sig - baseline_val) / (mvc_signal_1 - baseline_val + alpha) # Normalized percentage for each channel
        percen_medial = (clean_sig - baseline_val) / (mvc_signal_2 - baseline_val + alpha) # Normalized percentage for each channel

        # medial is positive, lateral is negative
        percen_diffsum_medial = (percen_medial[sig_chan_2] - percen_lateral[sig_chan_1]) / (percen_lateral[sig_chan_1] + percen_medial[sig_chan_2] + alpha)
        percen_diffsum_lateral = (percen_lateral[sig_chan_1] - percen_medial[sig_chan_2]) / (percen_lateral[sig_chan_1] + percen_medial[sig_chan_2] + alpha)
        percen_lateral_activation = percen_lateral[sig_chan_1] / (percen_lateral[sig_chan_1] + percen_medial[sig_chan_2] + alpha)
        percen_medial_activation = percen_medial[sig_chan_2] / (percen_lateral[sig_chan_1] + percen_medial[sig_chan_2] + alpha)
        co_contraction_index = 2 * min(percen_lateral[sig_chan_1], percen_medial[sig_chan_2]) / (percen_lateral[sig_chan_1] + percen_medial[sig_chan_2] + alpha)

        if percen_diffsum_medial > thresh and percen_diffsum_lateral < -thresh: # If this channel is the dominant lateralor channel
            percen = percen_medial[sig_chan_2] # Only consider as lateralor activation if the difference is positive
            chan_send = "medial"
            chan = sig_chan_2
            data_packet[chan] = percen * 100
            data_packet[sig_chan_1] = percen_lateral[sig_chan_1] * 100

        elif percen_diffsum_lateral > thresh and percen_diffsum_medial < -thresh: # If this channel is the dominant medialsor channel
            percen = percen_lateral[sig_chan_1] # Only consider as medialsor activation if the difference is negative
            chan_send = "lateral"
            chan = sig_chan_1
            data_packet[chan] = percen * 100
            data_packet[sig_chan_2] = percen_medial[sig_chan_2] * 100

        return (data_packet, chan_send, percen_lateral, percen_medial, percen_diffsum_lateral, percen_diffsum_medial, percen_lateral_activation, percen_medial_activation, sig_chan_1, sig_chan_2, co_contraction_index)


    def percentage_mvc_calc_v5(self, emg_window_val, mvc_dict, baseline_mean_values, baseline_std_values, alpha = 1e-9, thresh = 0.0, emg_control=False):
        """
        For 3 channel version metrics
        """
        data_packet = [0]*self.num_channels
        chan_send = None

        if emg_control == False:
            return (data_packet, chan_send, None, None, None, None, None, None)

        mvc_signal_1 = np.array(mvc_dict["lateral"])
        mvc_signal_2 = np.array(mvc_dict["medial"])
        mvc_signal_3 = np.array(mvc_dict["soleus"])
        sig_chan_1 = 1
        sig_chan_2 = 0
        sig_chan_3 = 2

        baseline_val = np.array(baseline_mean_values) + np.array(baseline_std_values)

        # Scale emg_window_val to match units (assuming baseline/MVC in uV, window in V)
        emg_window_val_scaled = np.array(emg_window_val) * 1000
        clean_sig = np.array([max(float(baseline_val[i]), float(emg_window_val_scaled[i])) for i in range(self.num_channels)])

        percen_lateral = (clean_sig - baseline_val) / (mvc_signal_1 - baseline_val + alpha) # Normalized percentage for each channel
        percen_medial = (clean_sig - baseline_val) / (mvc_signal_2 - baseline_val + alpha) # Normalized percentage for each channel
        percen_soleus = (clean_sig - baseline_val) / (mvc_signal_3 - baseline_val + alpha) # Normalized percentage for each channel

        # medial is positive, lateral is negative
        total = percen_lateral[sig_chan_1] + percen_medial[sig_chan_2] + percen_soleus[sig_chan_3] + alpha

        percen_diffsum_medial = (percen_medial[sig_chan_2] - (percen_lateral[sig_chan_1] + percen_soleus[sig_chan_3]) / 2) / total
        percen_diffsum_lateral = (percen_lateral[sig_chan_1] - (percen_medial[sig_chan_2] + percen_soleus[sig_chan_3]) / 2) / total
        percen_diffsum_soleus   = (percen_soleus[sig_chan_3]   - (percen_lateral[sig_chan_1] + percen_medial[sig_chan_2]) / 2) / total

        percen_lateral_activation = percen_lateral[sig_chan_1] / total
        percen_medial_activation = percen_medial[sig_chan_2] / total
        percen_soleus_activation   = percen_soleus[sig_chan_3]   / total

        min_activation = min(percen_lateral[sig_chan_1], percen_medial[sig_chan_2], percen_soleus[sig_chan_3])
        co_contraction_index = (3 * min_activation) / total

        if percen_diffsum_medial > thresh:
            percen = percen_medial[sig_chan_2] # Only consider as lateralor activation if the difference is positive
            chan_send = "medial"
            chan = sig_chan_2
            data_packet[chan] = percen * 100
            data_packet[sig_chan_1] = percen_lateral[sig_chan_1] * 100
            data_packet[sig_chan_3] = percen_soleus[sig_chan_3] * 100

        elif percen_diffsum_lateral > thresh :
            percen = percen_lateral[sig_chan_1] # Only consider as medialsor activation if the difference is negative
            chan_send = "lateral"
            chan = sig_chan_1
            data_packet[chan] = percen * 100
            data_packet[sig_chan_2] = percen_medial[sig_chan_2] * 100
            data_packet[sig_chan_3] = percen_soleus[sig_chan_3] * 100

        elif percen_diffsum_soleus > thresh:
            percen = percen_soleus[sig_chan_3] # Only consider as soleus activation if the difference is positive
            chan_send = "soleus"
            chan = sig_chan_3
            data_packet[chan] = percen * 100
            data_packet[sig_chan_1] = percen_lateral[sig_chan_1] * 100
            data_packet[sig_chan_2] = percen_medial[sig_chan_2] * 100

        return (data_packet, chan_send, percen_lateral, percen_medial, percen_soleus, percen_diffsum_lateral, percen_diffsum_medial, percen_diffsum_soleus, percen_lateral_activation, percen_medial_activation, percen_soleus_activation, sig_chan_1, sig_chan_2, sig_chan_3, co_contraction_index)

    def v6_support_func(self, percen_lateral, percen_medial, sig_chan_1, sig_chan_2,
                    win_arrays, mvc_signal_1, mvc_signal_2, baseline_val,
                    target_activation):
        # Activation error uses the channel-indexed percentages
        act_errorlateral = abs(percen_lateral[sig_chan_1] - target_activation)
        act_errormedial = abs(percen_medial[sig_chan_2] - target_activation)

        # Normalize win_arrays by MVC before computing std
        mvc_range_lg = mvc_signal_1[sig_chan_1] - baseline_val[sig_chan_1]
        mvc_range_mg = mvc_signal_2[sig_chan_2] - baseline_val[sig_chan_2]

        norm_win_lg = (win_arrays[sig_chan_1] - baseline_val[sig_chan_1]) / (mvc_range_lg + 1e-9)
        norm_win_mg = (win_arrays[sig_chan_2] - baseline_val[sig_chan_2]) / (mvc_range_mg + 1e-9)

        act_stdlateral = np.std(norm_win_lg)
        act_stdmedial = np.std(norm_win_mg)

        ratio2target_lateral = (percen_lateral[sig_chan_1] / target_activation)
        ratio2target_medial = (percen_medial[sig_chan_2] / target_activation)

        return (act_errorlateral, act_errormedial,
                act_stdlateral, act_stdmedial,
                ratio2target_lateral, ratio2target_medial)


    def percentage_mvc_calc_v6(self, emg_window_val, mvc_dict, baseline_mean_values,
                                baseline_std_values, alpha=1e-9, thresh=0.0,
                                emg_control=False, win_arrays=None):
        """
        Calculates MVC percentages with Activation Error and Standard deviation for 30% target.
        """
        data_packet = [0] * self.num_channels
        chan_send = None

        if emg_control == False:
            return (data_packet, chan_send, None, None, None, None, None, None), None

        mvc_signal_1 = np.array(mvc_dict)
        mvc_signal_2 = np.array(mvc_dict)
        sig_chan_1 = 1  # lateral channel index
        sig_chan_2 = 0  # medial channel index


        baseline_val = np.array(baseline_mean_values) + np.array(baseline_std_values)

        emg_window_val_scaled = np.array(emg_window_val) * 1000
        clean_sig = np.array([max(float(baseline_val[i]), float(emg_window_val_scaled[i]))
                            for i in range(self.num_channels)])

        percen_lateral = (clean_sig - baseline_val) / (mvc_signal_1 - baseline_val + alpha)
        percen_medial = (clean_sig - baseline_val) / (mvc_signal_2 - baseline_val + alpha)

        percen_diffsum_medial = (percen_medial[sig_chan_2] - percen_lateral[sig_chan_1]) / \
                                (percen_lateral[sig_chan_1] + percen_medial[sig_chan_2] + alpha)
        percen_diffsum_lateral = (percen_lateral[sig_chan_1] - percen_medial[sig_chan_2]) / \
                                (percen_lateral[sig_chan_1] + percen_medial[sig_chan_2] + alpha)
        percen_lateral_activation = percen_lateral[sig_chan_1] / \
                                    (percen_lateral[sig_chan_1] + percen_medial[sig_chan_2] + alpha)
        percen_medial_activation = percen_medial[sig_chan_2] / \
                                    (percen_lateral[sig_chan_1] + percen_medial[sig_chan_2] + alpha)
        co_contraction_index = 2 * min(percen_lateral[sig_chan_1], percen_medial[sig_chan_2]) / \
                            (percen_lateral[sig_chan_1] + percen_medial[sig_chan_2] + alpha)

        support_kwargs = dict(
            percen_lateral=percen_lateral,
            percen_medial=percen_medial,
            sig_chan_1=sig_chan_1,
            sig_chan_2=sig_chan_2,
            win_arrays=win_arrays,
            mvc_signal_1=mvc_signal_1,
            mvc_signal_2=mvc_signal_2,
            baseline_val=baseline_val,
        )

        # --- ONLY CALCULATE 30% MVC METRICS ---
        metrics_30 = self.v6_support_func(**support_kwargs, target_activation=0.3)

        if percen_diffsum_medial > thresh and percen_diffsum_lateral < -thresh:
            chan_send = "medial"
            chan = sig_chan_2
            data_packet[chan]       = percen_medial[sig_chan_2] * 100
            data_packet[sig_chan_1] = percen_lateral[sig_chan_1] * 100

        elif percen_diffsum_lateral > thresh and percen_diffsum_medial < -thresh:
            chan_send = "lateral"
            chan = sig_chan_1
            data_packet[chan]       = percen_lateral[sig_chan_1] * 100
            data_packet[sig_chan_2] = percen_medial[sig_chan_2] * 100

        control_signal = (data_packet, chan_send, percen_lateral, percen_medial,
                        percen_diffsum_lateral, percen_diffsum_medial,
                        percen_lateral_activation, percen_medial_activation,
                        sig_chan_1, sig_chan_2, co_contraction_index)

        return control_signal, metrics_30



    def control_sig_support_func(self, clean_sig, win_arrays, target_activation = 0.2, alpha = 1e-3):
        # Activation error uses the channel-indexed percentages
        percen_diffsum_1 = (clean_sig[0] - clean_sig[1]) / (clean_sig[0] + clean_sig[1] + alpha)
        percen_diffsum_2 = (clean_sig[1] - clean_sig[0]) / (clean_sig[0] + clean_sig[1] + alpha)

        percen_act_1 = clean_sig[0] / (clean_sig[0] + clean_sig[1] + alpha)
        percen_act_2 = clean_sig[1] / (clean_sig[0] + clean_sig[1] + alpha)

        co_contraction_index = 2 * min(clean_sig[0], clean_sig[1]) / (clean_sig[0] + clean_sig[1] + alpha)

        act_error1 = abs(clean_sig[0] - target_activation)
        act_error2 = abs(clean_sig[1] - target_activation)

        act_std1 = np.std(np.clip(win_arrays[0],0,1))
        act_std2 = np.std(np.clip(win_arrays[1],0,1))

        ratio2target_1 = (clean_sig[0] / target_activation)
        ratio2target_2 = (clean_sig[1] / target_activation)

        return percen_diffsum_1, percen_diffsum_2, percen_act_1, percen_act_2, co_contraction_index, act_error1, act_error2, act_std1, act_std2, ratio2target_1, ratio2target_2

    def control_signal_calc_v1(self, emg_time_comb, emg_window_array, alpha = 1e-3, thresh = 0.4):
        """Uses the normalized signal"""

        data_packet = [0]*self.num_channels
        clean_sig = np.clip(np.array(emg_time_comb[0]),0,1)
        time_elapsed = np.array(emg_time_comb[1][0])
        timestamp_us = np.array(emg_time_comb[1][1])

        percen_diffsum_1, percen_diffsum_2, percen_act_1, percen_act_2, co_contraction_index, act_error1, act_error2, act_std1, act_std2, ratio2target_1, ratio2target_2 = self.control_sig_support_func(clean_sig, emg_window_array)

        if percen_diffsum_1 > thresh and percen_diffsum_2 < -thresh:
            chan_send = 0
            data_packet[chan_send] = clean_sig[chan_send] * 100
            data_packet[1] = clean_sig[1] * 100

        elif percen_diffsum_2 > thresh and percen_diffsum_1 < -thresh:
            chan_send = 1
            data_packet[chan_send] = clean_sig[chan_send] * 100
            data_packet[0] = clean_sig[0] * 100

        elif co_contraction_index > thresh: # If both channels are active and co-contraction index is above threshold, consider it as cocontraction and set to 0
            chan_send = "cocontraction"
            data_packet = [0]*self.num_channels

        elif percen_diffsum_1 < -thresh and percen_diffsum_2 < -thresh: # If both channels are active but neither is dominant, consider it as cocontraction and set to 0
            chan_send = "cocontraction"
            data_packet = [0]*self.num_channels

        elif percen_diffsum_1 > thresh and percen_diffsum_2 > thresh: # If both channels are active and both are above the threshold, consider it as cocontraction and set to 0
            chan_send = "cocontraction"
            data_packet = [0]*self.num_channels

        elif max(percen_diffsum_1, percen_diffsum_2) <= thresh: # If both channels are below the threshold, consider it as no activation and set to 0
            chan_send = "no_activation"
            data_packet = [0]*self.num_channels

        else:
            chan_send = "alt_condition"
            data_packet = [0]*self.num_channels

        return (time_elapsed, timestamp_us, data_packet, emg_window_array, chan_send, percen_act_1, percen_act_2, percen_diffsum_1, percen_diffsum_2, co_contraction_index, act_error1, act_error2, act_std1, act_std2, ratio2target_1, ratio2target_2)
