"""
Pyns_Plot is a simple command line plotting tool (making use of matplotlib)
to index through plots of Neuroshare entities. This tool is provided mostly
to give a usage example of pyns, the Python Neuroshare API. The user may
browse through Neuroshare entities by using the keys: n - next entity,
p - previous entity, t - go forawrd in time, b - go back in time, 
and q - to quit the program.

Created on May 27, 2012

author: Elliott L. Barcikowski
"""

import argparse
import sys
import tkinter
import tkinter.messagebox
import tkinter.filedialog
import numpy as np
from matplotlib import pyplot as plt
from pyns.nsfile import NSFile
from pyns.nsentity import EntityType


class PlotManager:
    """
    Class to draw entities and handle events from user. The pyplot
    canvas held by this class is controlled by the key-strokes (q, p, and n)
    q causes the application to quit, n advances to the next entity,
    and p goes back to the previous entity.
    """

    def __init__(self, entities, skip=0, max_segment=100, max_analog=90000):
        self.entities = entities
        self.current_entity = skip

        if skip >= len(self.entities):
            return

        self.fig = plt.figure()
        self.ax = self.fig.add_subplot(111)
        self.fig.canvas.mpl_connect('key_press_event', self.onpress)

        self.current_segment = 0
        self.current_analog = 0

        self.max_segment = max_segment
        self.max_analog = max_analog

        # Draw the first entity. If it has zero items, or is not
        # a segment or analog, go on to the next
        if not self.draw_entity():
            next(self)

    def onpress(self, event):
        if event.key not in ('n', 'p', 'q', 't', 'b'):
            return
        if event.key == 'n':
            next(self)
        if event.key == 'p':
            self.previous()
        if event.key == 't':
            self.forward()
        if event.key == 'b':
            self.back()
        if event.key == 'q':
            if tkinter.messagebox.askokcancel('pyns_plot', 'Quit pyns_plot?'):
                sys.exit(0)

    def previous(self):
        if self.current_entity != 0:
            self.current_entity -= 1
            # If we fail to draw an entity (basically if the
            # entity has zero items, keep iterating back)
            if not self.draw_entity():
                self.previous()

    def __next__(self):
        self.current_analog = 0
        self.current_segment = 0

        if self.current_entity < len(self.entities) - 1:
            self.current_entity += 1
            # If we fail to draw an entity (basically if the
            # entity has zero items, keep iterating forward)
            if not self.draw_entity():
                next(self)
        else:
            sys.exit(0)

    def draw_event_entity(self):
        """
        Handles drawing digital events. This will draw a plot for all events in each
        different EventEntity.

        NOTE: This function assumes that all events within the same entity are from the same
        source (either Parallel Input, SMA 1, SMA 2, SMA 3, or SMA 4). However, data packets
        may contain digital events from multiple sources if they occur at the same timestamp.
        This function does not handle this case. For simplicity, digital events from only one
        source are plotted per entity. To handle multiple sources in data packets: 'entity.mode'
        is a bit mask indicating which ports were triggered, see NEVspec manual for more details.
        """
        entity = self.entities[self.current_entity]

        # Check if event entity is being plotted
        if entity.entity_type != EntityType.event:
            sys.stderr.write("must specify event entity\n")
            return False

        # Calculate number of events to plot within entity (can't be more than maximum)
        item_count = min(entity.item_count, self.max_analog)

        # Possible trigger sources for digital events
        reason = [
            'Parallel Input', 'SMA 1', 'SMA 2', 'SMA 3', 'SMA 4', 'Output Echo'
        ]

        # Convert entity.mode bit mask into index identifying which source
        title = f'{reason[entity.mode.bit_length() - 1]} digital events'

        # If there's no data in entity, skip plotting
        if item_count == 0:
            return False

        self.ax.cla()

        self.ax.set_title(title)
        self.ax.set_xlabel('[s]')
        self.ax.set_ylabel('')

        timestamps = np.zeros(item_count, dtype=np.double)
        values = np.zeros(item_count, dtype=np.uint16)

        # Collect all event data from a single source
        for item in range(0, item_count):
            data_rt = entity.get_event_data(item)
            timestamps[item] = data_rt[0]

            # Only gather data from largest bit in bitmask entity.mode
            values[item] = data_rt[1][entity.mode.bit_length() - 1]

        self.ax.scatter(timestamps, values)

        self.fig.canvas.draw()
        return True

    def draw_entity(self):
        """
        This function is called each time an entity is called to draw.
        It looks at the entity and calls the appropriate function.
        """
        entity = self.entities[self.current_entity]
        if entity.entity_type == EntityType.segment:
            return self.draw_segment_entity()
        if entity.entity_type == EntityType.analog:
            return self.draw_analog_entity()
        if entity.entity_type == EntityType.event:
            return self.draw_event_entity()
        # Return false if we don't have an analog or segment entity
        return False

    def draw_segment_entity(self):
        """
        A utility function to overlay all the segment waveforms for a
        a specified segment entity.
        """
        entity = self.entities[self.current_entity]

        # Check if segment entity is being plotted
        if entity.entity_type != EntityType.segment:
            sys.stderr.write("must specify segment entity\n")
            return False

        # Calculate number of segment waveforms to plot in entity (can't be more than max)
        item_count = min(entity.item_count - self.current_segment, self.max_segment)

        title = "Overlay of {0:d} segment waveforms for {1:s}".format(
            item_count, entity.label
        )

        # If there's no data in entity, skip plotting
        if item_count <= 0:
            return False

        self.ax.cla()

        # Get the time resolution (though it should always be 1/30kHz)
        segment_info = entity.get_segment_info()

        self.ax.set_title(title)

        self.ax.set_xlabel('[ms]')
        self.ax.set_ylabel('[uV]')

        # Collect all segment data
        for item in range(self.current_segment, self.current_segment + item_count):
            # Get the segment info for the time resolution,
            # though it should always be 30000
            segment_info = entity.get_segment_info()
            timestamp, waveform, _ = entity.get_segment_data(item)
            # Create physical time dimensions in milliseconds
            time = np.arange(0, len(waveform), dtype=np.double)
            time *= 1.0 / segment_info.sample_rate
            time *= 1000.0
            self.ax.plot(time, waveform)

        self.fig.canvas.draw()
        return True

    def forward(self):
        """
        Helper function to move plot forward in time.

        If the amount of analog data/segment data surpasses the max allowable within a plot,
        calculate the next data index to move to in order to plot the next window of data.
        """
        self.current_analog = min(
            self.current_analog + self.max_analog,
            self.entities[self.current_entity].item_count
        )
        self.current_segment = min(
            self.current_segment + self.max_segment,
            self.entities[self.current_entity].item_count
        )
        self.draw_entity()

    def back(self):
        """
        Helper function to move plot window backward in time.
        """
        self.current_analog = max(self.current_analog - self.max_analog, 0)
        self.current_segment = max(self.current_segment - self.max_segment, 0)

        self.draw_entity()

    def draw_analog_entity(self):
        """
        A utility function to draw any analog entity.
        """
        entity = self.entities[self.current_entity]

        # Check if analog entity is being plotted
        if entity.entity_type != EntityType.analog:
            sys.stderr.write("must specify analog entity\n")
            return False

        self.ax.cla()

        # Calculate the amount of analog data to be plotted (can't be more than max)
        item_count = min(self.max_analog, entity.item_count - self.current_analog)

        # If there's no data in entity, skip plotting
        if item_count <= 0:
            return False

        # The analog info will be useful to get time axis
        # resolution (i.e., ns2 or ns5 files)
        analog_info = entity.get_analog_info()
        entity_info = entity.get_entity_info()
        title = "Analog data for {0:s}".format(entity_info.label)

        # Notify user how much data is being plotted
        if item_count < entity.item_count:
            title += " (max {0:d} bins)".format(item_count)

        self.ax.set_title(title)
        self.ax.set_xlabel('[s]')
        self.ax.set_ylabel('[uV]')

        waveform = entity.get_analog_data(self.current_analog, item_count)
        # Create physical time dimensions in seconds
        time = np.arange(
            self.current_analog, self.current_analog + len(waveform),
            dtype=np.double
        )
        time *= 1.0 / analog_info.sample_rate
        self.ax.plot(time, waveform)

        self.fig.canvas.draw()

        return True


if __name__ == '__main__':
    description = """pyns_plot is a simple command line plotting tool
    (making use of matplotlib) to index through plots of Neuroshare entities.
    This tool is provided mostly to give a usage example of pyns, the Python
    Neuroshare API. The user may browse through Neuroshare entities by using
    the keys: n - next entity, p - previous entity, and q - to quit the program.
    """
    parser = argparse.ArgumentParser(description=description)

    parser.add_argument(
        "-k", "--skip", dest="skip",
        help="skip the first SKIP entities", default=0, type=int
    )
    parser.add_argument(
        "-a", "--analog-only", dest="analog_only", default=False,
        action="store_true", help="Only show waveforms for analog entities"
    )
    parser.add_argument(
        "-s", "--segment-only", dest="segment_only", default=False,
        action="store_true", help="Only show waveforms for segment entities"
    )
    parser.add_argument(
        "-e", "--event-only", dest="event_only", default=False,
        action="store_true", help="Only show digital event data"
    )
    parser.add_argument(
        "-m", "--max-segments", dest="max_segments", default=100,
        type=int, help="Only overlay MAX_SEGMENTS spikes"
    )
    parser.add_argument(
        "-n", "--max-analog", dest="max_analog", default=90000,
        type=int, help="Only overlay MAX_ANALOG time bins"
    )
    parser.add_argument(
        'filename', nargs="?", type=str, metavar="NEV_FILE",
        help="use NEV_FILE as input (optional)", default=None
    )

    args = parser.parse_args()
    # Check options conflicts
    if args.segment_only and args.analog_only:
        parser.error("can't specify both analog-only and segment-only options")

    root = tkinter.Tk()
    root.withdraw()

    message = """pyns_plot shows the power and ease of using Python for quick analysis applications.
    Browse Neuroshare entities using the following keys:
        'n' - next entities,
        'p' - previous entity,
        't' - forward in time,
        'b' - back in time,
        'q' - quit pyns_plot.
        """
    tkinter.messagebox.showinfo('pyns_plot Help', message)

    # Check that we have an input file and that it opens successfully
    if not args.filename:
        # If no file is specified, we'll open a simple tk file dialog and
        # have the user specify a file

        nev_formats = [("NEV", "*.nev"), ("NSx", "*.ns?"), ("NFx", "*.nf3")]
        filename = tkinter.filedialog.askopenfilename(
            title="Choose a file", filetypes=nev_formats
        )
        if len(filename) == 0:
            parser.error('selected invalid NEV or NSx file.')
    else:
        filename = args.filename
    nsfile = NSFile(filename)
    if nsfile is None:
        parser.error(f"failed to open file: {args.filename}")

    if args.analog_only:
        wanted_entities = [e for e in nsfile.get_entities(EntityType.analog)]
    elif args.segment_only:
        wanted_entities = [e for e in nsfile.get_entities(EntityType.segment)]
    elif args.event_only:
        wanted_entities = [e for e in nsfile.get_entities(EntityType.event)]
    else:
        wanted_entities = [e for e in nsfile.get_entities()]

    manager = PlotManager(
        wanted_entities, args.skip, args.max_segments, args.max_analog
    )

    plt.show()