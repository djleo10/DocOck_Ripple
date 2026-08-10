"""
This script is designed to stimulate an AC waveform through the
EEG+tES front end for a defined duration.
There are six user-defined variables to run the script: source_chan,
sink_chan, stim_ampl, stim_freq, stim_duration, and show_plot.
There are no default values, but the values will stay the same from the
previous time the script had run. source_chan and sink_chan are given as
a number from the array of channels available. If the sink_chan is set to
-1, the sink is ground. stim_ampl is given in uA, with 5 being the
lowest codable value and 5000 being the maximum. stim_freq is given in
Hz. stim_duration is given in seconds. show_plot can be set to True to show
the plot and False to not show plot. The section to edit these variables is
in the get_user_settings function of the ACStimulator class.

Created by: caleb
Edited on: Nov 2024 by richard
"""

import xipppy as xp
import numpy as np
from time import sleep
import matplotlib.pyplot as plt
import math
import copy
import matplotlib

# Explicitly set the backend to TkAgg, avoid conflict with PyQT6
matplotlib.use('TkAgg')


class ACStimulator:
    def __init__(self, source_chan, sink_chan, stim_ampl, stim_freq, stim_duration, show_plot):
        self.source_chan = source_chan
        self.sink_chan = sink_chan
        self.stim_ampl = stim_ampl
        self.stim_freq = stim_freq
        self.stim_duration = stim_duration
        self.show_plot = show_plot

        # Neural Interface Processor clock rate
        self.fs_clock = 30000  # Hz

    @staticmethod
    def connect_to_processor():
        """
        Connect to the Neural Interface Processor. If UDP connection fails,
        attempt TCP connection.
        """
        # Close Connection
        xp._close()
        sleep(0.001)

        # Connect to processor (Try UDP then TCP).
        try:
            xp._open()
        except Exception as e_udp:
            try:
                xp._open(use_tcp=True)
            except Exception as e_tcp:
                print(f"Failed to connect to processor over UDP and TCP: {e_udp}, {e_tcp}")
            else:
                print("Connected over TCP")
        else:
            print("Connected over UDP")
        sleep(0.001)

    @staticmethod
    def get_user_settings(chan_list):
        """
        Fetches user settings for stimulation parameters.
        """
        # Channel on which to stimulate, zero-indexed 0:N-1
        source_chan = chan_list[0]

        # Channel for stimulation return, zero-indexed. Set to -1 for ground channel only.
        sink_chan = chan_list[31]

        # Stimulation Amplitude
        stim_ampl = 2000  # uA

        # Stimulation Frequency
        stim_freq = 10  # Hz

        # Total Stimulation Duration
        stim_duration = 100  # s

        # Flag to show plot of stimulation waveform
        show_plot = True

        return [source_chan, sink_chan, stim_ampl, stim_freq, stim_duration, show_plot]

    def build_waveform(self):
        """
        Builds the stimulation waveform.
        """
        # List of stimulation step sizes for EEG+tES front end
        stim_res = np.array([5, 10, 20, 50])  # uA/step

        # Determine index of stimulation resolution to use, chooses the smallest
        # step size for selected amplitude.
        stim_res_ind = np.where(abs(self.stim_ampl) <= 100 * stim_res)[0][0]

        # Determine stimulation amplitude step (1-100 at the current resolution)
        stim_step = math.floor(abs(self.stim_ampl) / stim_res[stim_res_ind])

        # Disable global stimulation to set stimulation resolution
        xp.stim_enable_set(False)

        # Set stimulation resolution
        xp.stim_set_res(self.source_chan, int(stim_res_ind))
        if self.sink_chan >= 0:
            xp.stim_set_res(self.sink_chan, int(stim_res_ind))

        # Enable global stimulation
        xp.stim_enable_set(True)

        # Stimulation Period (in # of clock cycles)
        stim_period = math.floor(self.fs_clock / self.stim_freq)

        # Resulting Stimulation Frequency (in Hz)
        result_freq = self.fs_clock / stim_period
        print(f'Resulting stimulation frequency: {result_freq} Hz')

        # Calculate # of stimulation repeats
        stim_repeats = math.floor(self.fs_clock * self.stim_duration / stim_period)

        # Calculate time sequence for stim waveform plot and desired sinusoidal waveform
        t = [i for i in range(stim_period)]
        y = [stim_step * math.sin(2 * math.pi * result_freq * i / self.fs_clock) for i in range(stim_period)]
        if self.stim_ampl < 0:
            y = [-yi for yi in y]

        # Integer version of sinusoidal waveform
        z = np.round(y)

        # Calculate differential of integer waveform to identify points of amplitude change
        # in discrete version of sinusoidal waveform
        dz = np.diff(z)
        dz = np.append(dz, 1)
        end_pts = np.asarray(np.nonzero(abs(dz)))
        n_vc = end_pts.size
        stim_command = []

        # If the number of voltage changes is within the maximum number of voltage sequences allowed
        # on the Neural Interface Processor, use Integer waveform to build optimized waveform.
        # Otherwise, use uniform voltage segment lengths to build the stimulation waveform.
        if n_vc <= 244:
            self._build_optimized_waveform(n_vc, end_pts, z, stim_command, stim_period)
        else:
            self._build_even_segments_waveform(stim_period, y, stim_command)

        if self.show_plot:
            self.plot_waveform(stim_command, t, y)
        return stim_command, stim_repeats

    def _build_optimized_waveform(self, n_vc, end_pts, z, stim_command, stim_period):
        """
        Build optimized waveform using the available voltage changes within stimulation period.
        """
        print(f'Building optimized waveform using {n_vc} uneven segments')

        zero_end = np.append(-1, end_pts)
        temp_seg = []

        # Create segments based on given parameters
        for j in range(n_vc):
            seg_len = int(zero_end[j + 1] - zero_end[j])
            seg_amp = int(abs(z[end_pts[0][j]]))
            seg_pol = 1 if z[end_pts[0][j]] >= 0 else -1
            temp_seg.append(xp.StimSegment(seg_len, seg_amp, seg_pol))

        # Construct segment string for the eval function
        seg_str = ''.join(f'temp_seg[{k}], ' for k in range(len(temp_seg)))
        # Append the newly created StimSeq object to stim_command
        stim_command.append(eval(f'xp.StimSeq(self.source_chan, stim_period, 1, {seg_str}action=2)'))

    def _build_even_segments_waveform(self, stim_period, y, stim_command):
        """
        Build waveform using even segments covering the stimulation period.
        """
        # Maximum number of stimulation sequences allowed
        max_sequence = 244

        even_seg_length = math.ceil(stim_period / max_sequence)
        num_segs = math.floor(stim_period / even_seg_length)
        remaining_seg_length = stim_period - num_segs * even_seg_length

        print(f'Building waveform using {num_segs} segments, each {even_seg_length} clock-cycles long')

        temp_seg = []

        # Create segments based on even segment length
        for k in range(num_segs):
            a = k * even_seg_length
            b = (k + 1) * even_seg_length
            amp = np.round(np.mean(y[a:b]))
            pol = 1 if amp >= 0 else -1
            temp_seg.append(xp.StimSegment(even_seg_length, int(abs(amp)), pol))

        # Handle remaining segment length if present
        if remaining_seg_length > 0:
            a = num_segs * even_seg_length
            amp = np.round(np.mean(y[a:len(y)]))
            pol = 1 if amp >= 0 else -1
            temp_seg.append(xp.StimSegment(remaining_seg_length, int(abs(amp)), pol))

        # Construct segment string for the eval function
        seg_str = ''.join(f'temp_seg[{k}], ' for k in range(len(temp_seg)))
        # Append the newly created StimSeq object to stim_command
        stim_command.append(eval(f'xp.StimSeq(self.source_chan, stim_period, 1, {seg_str}action=2)'))

    def plot_waveform(self, stim_command, t, y):
        """
        Plots the waveform.
        """
        temp = stim_command[0]
        wf = np.zeros(len(t))
        a = 0

        for seg in temp.segments:
            b = a + seg.length
            wf[a:b] = seg.amplitude * seg.polarity
            a = b

        plt.ion()
        fig, ax = plt.subplots()
        ax.plot(t, y, '-r')
        ax.plot(t, wf, '-b')
        plt.title('AC Stimulation Waveform')
        plt.xlabel('Clock Cycles')
        plt.ylabel('Stimulation Amplitude (Steps)')
        ax.legend(['Ideal Waveform', 'Actual Waveform'])
        y2 = ax.secondary_yaxis('right')
        y2.set_ylabel('Stim Amplitude (\u03BCA)')
        plt.show(block=False)
        plt.pause(0.001)  # Allow the plot to update

    def send_stim_waveforms(self, stim_command, stim_repeats):
        """
        Sends the stimulation waveforms.
        """
        # Maximum number of repeats allowed (2^12 - 1) on Neural Interface Processor
        max_repeats = 4095

        # Source channel stimulation sequence
        x_source = stim_command[0]

        # Clear buffer of stimulation data on source channel
        _, _ = xp.stim_data(self.source_chan)

        # Send AC stimulation, broken into different queued sequences if exceeds maximum number of repeats
        if stim_repeats < 8 * max_repeats:
            repeats_left = stim_repeats
            while repeats_left > 0:
                use_repeats = min([repeats_left, max_repeats])
                x_source.repeats = use_repeats
                print(f'Sending stimulation for {use_repeats}/{repeats_left} remaining repeats')

                if self.sink_chan >= 0:
                    # If there's a designated sink channel, reverse the polarities in its stimulation sequence
                    x_sink = copy.deepcopy(x_source)
                    x_sink.electrode = self.sink_chan
                    for seg in x_sink.segments:
                        seg.polarity = -seg.polarity
                    xp.StimSeq.send_stim_seqs([x_source, x_sink])
                else:
                    xp.StimSeq.send(x_source)

                repeats_left -= use_repeats

            total_time = self._wait_for_stimulation_end(x_source)
            print(f'Stimulation duration {total_time} seconds')
        else:
            raise Exception(f'Error: Duration is too long for Xipppy. {stim_repeats} repeats requested, maximum = {8 * max_repeats}')

        return total_time

    def _wait_for_stimulation_end(self, x_source):
        """
        Wait until the stimulation ends and calculate total duration.
        """
        # Get initial timestamp (start of stimulation) from first successfully retrieved stim data
        count, ts = xp.stim_data(self.source_chan)
        while count < 1:
            count, ts = xp.stim_data(self.source_chan)
        time_start = ts[0].timestamp

        # Continuously sleep until stimulation has stopped
        while count > 0:
            last_stim = ts[-1].timestamp
            sleep(1)
            count, ts = xp.stim_data(self.source_chan)

        # Calculate total duration of stimulation
        total_time = (last_stim - time_start) / self.fs_clock
        return total_time


if __name__ == '__main__':
    ACStimulator.connect_to_processor()

    tES_chans = xp.list_elec(fe_type='EEG')
    if len(tES_chans) == 0:
        raise Exception('ERROR: EEG+tES Front End not detected')

    settings = ACStimulator.get_user_settings(tES_chans)
    stimulator = ACStimulator(*settings)

    if stimulator.stim_ampl < 15:
        xp._close()
        raise Exception('Stimulation amplitude too low. Must be at least 15 \u03BCA')

    AC_Command, repeats = stimulator.build_waveform()
    stim_dur = stimulator.send_stim_waveforms(AC_Command, repeats)
    xp._close()
    print('Xipppy connection closed')