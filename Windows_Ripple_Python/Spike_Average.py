"""
This script is an example of how to get and process spike data using xipppy.
"""

import time
from time import sleep
import matplotlib.pyplot as plt
import numpy as np
import xipppy as xp

SPK_SAMPLES = 52
FS_CLK = 30000
SPK_BUFFER_SIZE = 100


def connect_to_processor():
    """
    Connects to the Neural Interface Processor. If UDP connection fails,
    attempts TCP connection.
    """
    xp._close()
    sleep(0.001)

    try:
        xp._open()
        print("Connected over UDP")
    except:
        try:
            xp._open(use_tcp=True)
            print("Connected over TCP")
        except:
            print("Failed to connect to processor.")

    sleep(0.001)


def unit_color(class_id):
    """
    Maps class IDs to specific colors for plotting.

    Parameters:
        class_id: Class identifier for the spike

    Returns:
        str: Color corresponding to the class ID
    """
    return {
        0: 'b',
        1: 'm',
        2: 'y',
        3: 'g',
        4: 'r'
    }[class_id]


def plot_spike_average(elec):
    """
    Plots the last 100 spikes received by the front end, calculates the
    average, and plots it.

    Parameters:
        elec: Electrode number to plot the spike data from
    """
    plt.figure(1)
    plt.xlabel('Time (ms)')
    plt.ylabel('uV')
    spk_count = 0  # Initialization for how many spikes have occurred
    spk_avg = np.empty([0, SPK_SAMPLES])  # Initialization for average 52 sample spike waveform
    spk_buffer = np.empty([SPK_BUFFER_SIZE, SPK_SAMPLES])  # Initialization for holding waveform data of Spike samples
    spk_t = np.arange(0, 52000 / FS_CLK, 1000 / FS_CLK, dtype=np.float32)  # Time series (in milliseconds) for spike waveform
    spk_buffer[:] = np.nan

    # Note: data starts collecting in a buffer *after* xipppy is instantiated.
    # Wait for 1 sec = 1000 samples/1000 Hz.
    # The data is concatenated into one array, which is the reason for time.sleep(1)
    # below.
    time.sleep(1)

    while plt.fignum_exists(1):
        count, seg_data = xp.spk_data(elec)  # Collect spike data
        for spike in seg_data:
            if spk_count < SPK_BUFFER_SIZE:
                plt.title(f'Spike count: {spk_count + 1}')
                plt.plot(spk_t, spike.wf, color=unit_color(spike.class_id), linewidth=0.3)
                spk_buffer[spk_count] = spike.wf
                spk_avg = np.nanmean(spk_buffer, axis=0)
                plt.pause(0.05)
                spk_count += 1
            else:
                plt.title(f'Electrode {elec} - Last {SPK_BUFFER_SIZE} spikes average')
                plt.plot(spk_t, spk_avg, color='k', linewidth=4.0)
                plt.pause(0.1)
                plt.show()
                return


if __name__ == '__main__':
    connect_to_processor()
    plot_spike_average(0)
    xp._close()