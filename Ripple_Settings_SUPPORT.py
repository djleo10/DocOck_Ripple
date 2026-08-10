GRAPH_W      = 1000
GRAPH_H      = 100
ROW_SPACING  = 2
LABEL_W      = 50
LEFT_MARGIN  = LABEL_W


BUFFER_SIZE    = 2000       
TIMER_MS       = 10           # 100 fps refresh
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

BASELINE_DURATION_MS = 3000
MVC_DURATION_MS      = 3000

MVC_SAMPLE_LIMIT = int(MVC_DURATION_MS * EMG_SAMPLE_RATE / 1000)
BASELINE_SAMPLE_LIMIT = int(BASELINE_DURATION_MS * EMG_SAMPLE_RATE / 1000)

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
