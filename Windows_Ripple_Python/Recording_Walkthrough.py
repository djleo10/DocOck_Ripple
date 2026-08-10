"""
This is an example script for starting a neural recording trial from the Neural Interface Processor and Trellis.

In order to initiate recording from this script, Trellis is required to be open on the same computer, with
the "Enable Remote Control" option checked in Trellis File Save. Selected signals and channels for recording
should be set in Trellis before running the script.

This script will start a recording for 5 seconds, pause the recording for 2 seconds, resume for 2 seconds, then stop.

Created on Tue Nov 26 2024

@author: richard
"""

import xipppy as xp
from time import sleep


def connect_to_processor():
    """
    Connects to the Neural Interface Processor. If UDP connection fails,
    attempts TCP connection, and adds Trellis operator ID 129 for recording.
    """
    xp._close()
    sleep(0.001)

    try:
        xp._open()
        print("Connected over UDP")
    except:
        try:
            xp._open(use_tcp=True)
            xp.add_operator(129)
            print("Connected over TCP")
        except:
            print("Failed to connect to processor.")

    sleep(0.001)


def start_recording(file_name_base=None, auto_stop_time=None, auto_incr=None, incr_num=None):
    """
    Starts a recording trial with user-defined properties.

    Parameters:
        file_name_base (str): Optional. Full path of base file name for recording. Recorded files 
                              will be named file_name_base.nev, file_name_base.ns2, etc. If not 
                              specified, this parameter will not be changed.
        auto_stop_time (int): Optional. Time to automatically stop recording(s) in seconds. If not 
                              specified, this parameter will not be changed. If set to 0, auto stop 
                              will be disabled.
        auto_incr (bool): Optional. If set to True, output file name will be appended 
                          by a recording index. The appended string will always be four digits 
                          long, padded to the left with zeroes. If set to False, auto increment 
                          will be disabled. If not specified, this parameter will not be changed.
        incr_num (int): Optional. Current value of increment number. If not specified, this 
                        parameter will not be changed.
    """
    print('Current Recording Status:')
    status = xp.trial(
        129,
        status='recording',
        file_name_base=file_name_base,
        auto_stop_time=auto_stop_time,
        auto_incr=auto_incr,
        incr_num=incr_num
    )
    print(status)
    print('\n')


def toggle_pause_recording():
    """
    Pauses an ongoing recording trial or resumes a paused recording trial.
    """
    print('Current Recording Status:')
    status = xp.trial(129, status='paused')
    print(status)
    print('\n')


def stop_recording():
    """
    Stops an ongoing recording trial.
    """
    print('Current Recording Status:')
    status = xp.trial(129, status='stopped')
    print(status)
    print('\n')


if __name__ == '__main__':
    # Connect to the Neural Interface Processor and add a Trellis operator if TCP connected
    connect_to_processor()

    # Start a recording with default options set in Trellis
    start_recording()

    sleep(5)

    # Pause the recording
    toggle_pause_recording()

    sleep(2)

    # Resume the recording
    toggle_pause_recording()

    sleep(2)

    # Stop the recording
    stop_recording()

    xp._close()