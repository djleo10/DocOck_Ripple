import os 
import pygame
import random

WIDTH, HEIGHT = 800, 800
FPS = 30
TEXTSIZE = 30
TEXTCOLOR = (255, 255, 255)
BACKGROUND_COLOR = (0, 0, 0) # Black
BAR_WIDTH = 50 
BAR_MAX_HEIGHT = HEIGHT - 100
MINI_BAR_HEIGHT = 20
BTW_BAR_DISTANCE = 20

GRID_PCTS_X = (0, 50, 100)
GRID_PCTS_Y = (0, 50, 100)
GRID_NODES = [(x, y) for x in GRID_PCTS_X for y in GRID_PCTS_Y]

LEVELS = list(range(1, 14))
REST_DURATION   = 3
RAMPUP_DURATION = 2
HOLD_DURATION   = 3
STOP_DURATION   = 1
TARGET_HOLD_DURATION = 2.0    
MISS_DISPLAY_TIME    = 1.0   
TARGET_HIT_RADIUS = 4.0
RAMPUP_AT = REST_DURATION                           # 2
HOLD_AT   = REST_DURATION + RAMPUP_DURATION         # 4
STOP_AT   = HOLD_AT   + HOLD_DURATION               # 7
TRIAL_END = STOP_AT   + STOP_DURATION               # 8

LEVEL_TIMEOUT = {
    1: 15,  2: 13,  3: 11,  4:  9,  5:  7,
    8: 15,  9: 13, 10: 11, 11:  9, 12:  7,
}

DEFAULT_TIMEOUT = 15

FLASH_HZ_REST   = 2.0   # 2 blinks/s during REST
FLASH_HZ_RAMPUP = 3.0   # 3 blinks/s during RAMP-UP
FLASH_HZ_HOLD   = 1.5   # 1.5 blinks/s during HOLD (silent)
FLASH_HZ_STOP   = 4.0   # 4 blinks/s during STOP

TRIAL_TIME = 11 # sec
TOTAL_TRIALS = 9 # Each Level
HOLD_START = 10 # After elpased time =  15 sec
