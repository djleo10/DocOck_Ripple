import os
import sys
import json
import time
import random
import numpy as np
from datetime import datetime
import pygame as pg
from PyQt5.QtWidgets import QApplication

try:
    from .BarGame_settings import *
except ImportError:
    from BarGame_settings import *

try:
    from ..BaseGame import BaseGame
except ImportError:
    from games.BaseGame import BaseGame

STATE_WELCOME       = "welcome"
STATE_HOME          = "home"
STATE_FREEMODE      = "freemode"
STATE_TEST_MENU     = "test_menu"
STATE_TEST_PRE      = "test_pre"
STATE_TEST_RUNNING  = "test_running"
STATE_LEVEL_PRE     = "level_pre"
STATE_LEVEL_RUNNING = "level_running"
STATE_DONE          = "done"

MVC_PCT_MAP = {1:20, 2:40, 3:60, 4:80, 5:100,
               8:20, 9:40, 10:60, 11:80, 12:100}


class BarGame_v2(BaseGame):

    def __init__(self, basepath=None, num_channels=2, **kwargs):
        if basepath is None:
            basepath = os.path.dirname(os.path.abspath(__file__))
        super().__init__(basepath=basepath, num_channels=num_channels, **kwargs)

        self.completion_counts = {lvl: 0 for lvl in LEVELS}
        self.attempt_counters  = {str(lvl): 0 for lvl in LEVELS}
        self.level_labels      = {}
        self._session_results = []

        # state machine
        self.state = STATE_WELCOME

        # shared across states
        self._button_rects    = []
        self._pre_trial_end   = None
        self._timer_start     = None
        self._mvc_pct         = 0
        self._muscle          = ""
        self._cycle_attempt   = 0
        self._selected_level  = None
        self._run_count       = 0
        self.bar_values       = [0] * num_channels

        # freemode
        self._freemode_session = 0
        self._freemode_start   = None

        # test mode
        self._test_level     = None
        self._test_run_count = 0
        self._test_btn_rects = []

    def game_name(self) -> str:
        return "bar_game_v2"

    def setup(self):
        pg.init()
        pg.mixer.init()
        self.screen = pg.display.set_mode((WIDTH, HEIGHT))
        pg.display.set_caption("Bar Game v2")
        self.clock  = pg.time.Clock()
        self.font   = pg.font.SysFont(None, TEXTSIZE)

        # layout
        self.center_ground_x = WIDTH  // 2 - 50
        self.center_ground_y = HEIGHT - 50
        self.mid_ground_y    = HEIGHT // 2
        self.mid_ground_x    = WIDTH  // 2 + WIDTH // 4 + 100
        self.bar_colours     = [
            (random.randint(50,255), random.randint(50,255), random.randint(50,255))
            for _ in range(self.num_channels)
        ]
        self.rect_color = (255, 255, 255)

        # audio
        self.dingsound_1     = pg.mixer.Sound(os.path.join(self.basepath, "Audio_Files", "1_audio.wav"))
        self.dingsound_2     = pg.mixer.Sound(os.path.join(self.basepath, "Audio_Files", "2_audio.wav"))
        self.ding_holdsound  = pg.mixer.Sound(os.path.join(self.basepath, "Audio_Files", "hold_audio.wav"))
        self.ding_holdxsound = pg.mixer.Sound(os.path.join(self.basepath, "Audio_Files", "holdx_audio.wav"))

        self._flash_sound_rest   = self.dingsound_1
        self._flash_sound_rampup = self.ding_holdsound
        self._trans_to_rampup    = self.dingsound_2
        self._trans_to_hold      = self.ding_holdxsound
        self._trans_to_rest      = self.dingsound_2
        self._trans_to_stop      = self.dingsound_2

        # flash state
        self._current_phase        = "rest"
        self._flash_visible        = True
        self._flash_last_toggle    = 0.0
        self._last_triggered_phase = None

        self._open_csv([
            "level", "muscle", "mvc_pct", "attempt",
            "phase", "t", "bar_0", "bar_1"
        ])

        self._load_progress()
        self._build_level_labels()

    def tick(self):
        if   self.state == STATE_WELCOME:       self.welcome_screen()
        elif self.state == STATE_HOME:          self.home_screen()
        elif self.state == STATE_FREEMODE:      self.freemode_screen()
        elif self.state == STATE_TEST_MENU:     self.test_menu_screen()
        elif self.state == STATE_TEST_PRE:      self.test_pre_screen()
        elif self.state == STATE_TEST_RUNNING:  self.test_running_screen()
        elif self.state == STATE_LEVEL_PRE:     self.level_pre_screen()
        elif self.state == STATE_LEVEL_RUNNING: self.level_running_screen()
        elif self.state == STATE_DONE:
            self.stop_game()
            return
        pg.display.flip()
        self.clock.tick(FPS)

    def get_current_sample(self) -> dict:
        elapsed = round(time.time() - self._timer_start, 3) \
                  if self._timer_start else 0.0
        return {
            "t":    elapsed,
            "bars": self.bar_values[:]
        }

    def get_save_data(self) -> dict:
        return {
            "completion_counts": {str(k): v for k, v in self.completion_counts.items()},
            "attempt_counters":  self.attempt_counters,
            "data_samples":      self._session_results,
        }

    def _load_progress(self):
        path = os.path.join(
            os.path.dirname(os.path.abspath(__file__)),
            "..", "..", "data", f"{self.game_name()}.json"
        )
        if not os.path.exists(path):
            print(f"[BarGame] No progress file found, starting fresh")
            return
        try:
            with open(path, "r") as f:
                data = json.load(f)
            for k, v in data.get("completion_counts", {}).items():
                key = int(k) if k.isdigit() else k
                if key in self.completion_counts:
                    self.completion_counts[key] = v
            for k, v in data.get("attempt_counters", {}).items():
                if k in self.attempt_counters:
                    self.attempt_counters[k] = v
            self._trial_metrics = data.get("trial_metrics", [])
            print(f"[BarGame] Progress loaded")
        except Exception as e:
            print(f"[BarGame] Failed to load progress: {e}")
                
    def on_game_over(self):
        if self._recording:
            samples = self.stop_recording()
            if any(samples.values()):
                result = self._calculate_trial_metrics(samples)
                self._session_results.append(result)
                self.save_session_data()

    def apply_keyboard_control(self):
        keys = pg.key.get_pressed()
        for i in range(self.num_channels):
            key = getattr(pg, f'K_{i+1}', None)
            if key:
                if keys[key]:
                    self.bar_values[i] = min(100, self.bar_values[i] + 2)
                else:
                    self.bar_values[i] = max(0, self.bar_values[i] - 1)

    def apply_emg_values(self, values):
        for i in range(self.num_channels):
            if i < len(values):
                self.bar_values[i] = min(100, int(values[i]))

    def welcome_screen(self):
        for event in pg.event.get():
            if event.type == pg.QUIT:
                self.state = STATE_DONE
                return
            elif event.type == pg.KEYDOWN and event.key == pg.K_p:
                self.state = STATE_HOME
                return
        self.screen.fill(BACKGROUND_COLOR)
        self._draw_text_centered("BAR GAME (V2)", -100)
        self._draw_text_centered("Press 'P' to Play.", 20)

    def _build_home_buttons(self):
        self._build_level_labels()
        menu_items = [
            (self.level_labels[1],   1),  (self.level_labels[2],  2),
            (self.level_labels[3],   3),  (self.level_labels[4],  4),
            (self.level_labels[5],   5),
            (self.level_labels[8],   8),  (self.level_labels[9],  9),
            (self.level_labels[10], 10),  (self.level_labels[11], 11),
            (self.level_labels[12], 12),
            (self.level_labels[13], 13),
            (self.level_labels[14], 14),
        ]
        self._button_rects = []
        spacing = 50
        top = HEIGHT // 2 - (len(menu_items) * spacing) // 2
        for i, (label, idx) in enumerate(menu_items):
            extra  = 50  if idx in [8,9,10,11,12] else 0
            extra += 100 if idx == 13 else 0
            extra += 10  if idx == 14 else 0
            rect = pg.Rect(WIDTH//2 - 200, top + i*spacing + extra, 400, 42)
            self._button_rects.append((rect, idx, label))

    def home_screen(self):
        if not self._button_rects:
            self._build_home_buttons()
        for event in pg.event.get():
            if event.type == pg.QUIT:
                self.state = STATE_DONE
                return
            elif event.type == pg.MOUSEBUTTONDOWN:
                for rect, idx, label in self._button_rects:
                    if rect.collidepoint(pg.mouse.get_pos()):
                        self._button_rects = []
                        if   idx == 13:     self._enter_freemode()
                        elif idx == 14:     self.state = STATE_TEST_MENU
                        elif idx in LEVELS: self._enter_level_pre(idx)
                        return
        self.screen.fill(BACKGROUND_COLOR)
        self._draw_text_centered("Select a Level", -380)
        for rect, idx, label in self._button_rects:
            color = (230, 200, 0) if idx == 14 else self.rect_color
            pg.draw.rect(self.screen, color, rect)
            surf = self.font.render(label, True, (0, 0, 0))
            self.screen.blit(surf, surf.get_rect(center=rect.center))

    def _enter_freemode(self):
        self.completion_counts[13] += 1
        self._freemode_session = self.completion_counts[13]
        self._freemode_start   = time.time()
        self.state = STATE_FREEMODE

    def freemode_screen(self):
        for event in pg.event.get():
            if event.type == pg.QUIT:
                self._exit_freemode(); return
            elif event.type == pg.KEYDOWN and event.key == pg.K_q: 
                self._exit_freemode(); return

        self.apply_control()  

        elapsed = round(time.time() - self._freemode_start, 1)
        self.screen.fill(BACKGROUND_COLOR)
        self._draw_text_top(
            f"FREEMODE — Session {self._freemode_session}   "
            f"Time: {elapsed}s   [Q to stop]"
        )
        pg.draw.line(self.screen, (255,255,255),
                     (0, self.center_ground_y), (WIDTH, self.center_ground_y), 2)
        self.draw_bars(self.bar_values)

    def _exit_freemode(self):
        self.state = STATE_HOME

    def _build_test_buttons(self):
        test_menu = [
            ("Test — 20% MVC  (M1)",  1), ("Test — 40% MVC  (M1)",  2),
            ("Test — 60% MVC  (M1)",  3), ("Test — 80% MVC  (M1)",  4),
            ("Test — 100% MVC (M1)",  5),
            ("Test — 20% MVC  (M2)",  8), ("Test — 40% MVC  (M2)",  9),
            ("Test — 60% MVC  (M2)", 10), ("Test — 80% MVC  (M2)", 11),
            ("Test — 100% MVC (M2)", 12),
        ]
        self._test_btn_rects = []
        spacing = 46
        top = HEIGHT // 2 - (len(test_menu) * spacing) // 2
        for i, (label, idx) in enumerate(test_menu):
            rect = pg.Rect(WIDTH//2 - 210, top + i*spacing, 420, 38)
            self._test_btn_rects.append((rect, idx, label))

    def test_menu_screen(self):
        if not self._test_btn_rects:
            self._build_test_buttons()
        for event in pg.event.get():
            if event.type == pg.QUIT:
                self.state = STATE_DONE
                return
            elif event.type == pg.MOUSEBUTTONDOWN:
                for rect, idx, label in self._test_btn_rects:
                    if rect.collidepoint(pg.mouse.get_pos()):
                        self._test_btn_rects = []
                        self._enter_test_pre(idx)
                        return
        self.screen.fill(BACKGROUND_COLOR)
        self._draw_text_centered(
            "TEST MODE — select level to practice", -380, color=(230, 200, 0))
        for rect, idx, label in self._test_btn_rects:
            pg.draw.rect(self.screen, (230, 200, 0), rect)
            surf = self.font.render(label, True, (0, 0, 0))
            self.screen.blit(surf, surf.get_rect(center=rect.center))

    def _enter_test_pre(self, level):
        self._test_level     = level
        self._mvc_pct        = MVC_PCT_MAP.get(level, 0)
        self._muscle         = "M1" if level in [1,2,3,4,5] else "M2"
        self._test_run_count = 0
        self._pre_trial_end  = time.time() + 5
        self.state = STATE_TEST_PRE

    def test_pre_screen(self):
        for event in pg.event.get():
            if event.type == pg.QUIT:
                self.state = STATE_DONE
                return
        if time.time() >= self._pre_trial_end:
            self._enter_test_running()
            return
        remaining = int(self._pre_trial_end - time.time())
        self.screen.fill(BACKGROUND_COLOR)
        self._draw_text_top(
            f"TEST MODE\nMuscle: {self._muscle}  {self._mvc_pct}% MVC\n[GET READY]",
            starter_text=True, color=(230, 200, 0)
        )
        self._update_phase_flash(None)
        self.draw_stimulus()
        lines = [f"Get ready!  {self._muscle}", f"Starts in  {remaining + 1}s"]
        y = HEIGHT // 2
        for line in lines:
            surf = self.font.render(line, True, (230, 200, 0))
            self.screen.blit(surf, surf.get_rect(
                center=(WIDTH//2 - WIDTH//4, y)))
            y += surf.get_height() + 8

    def _enter_test_running(self):
        self._test_run_count += 1
        self._reset_flash_state()
        self._timer_start = time.time()
        self.state = STATE_TEST_RUNNING

    def test_running_screen(self):
        for event in pg.event.get():
            if event.type == pg.QUIT:
                self.state = STATE_DONE
                return

        self.apply_control()

        elapsed = round(time.time() - self._timer_start, 3)
        self._update_phase_flash(elapsed)
        if elapsed >= TRIAL_END:
            self._enter_test_running()
            return
        self.screen.fill(BACKGROUND_COLOR)
        self._draw_text_top(
            f"TEST MODE — {self._muscle} {self._mvc_pct}%MVC — "
            f"rep {self._test_run_count}   Time: {elapsed:.1f}s   [Q to exit]",
            color=(230, 200, 0)
        )
        pg.draw.line(self.screen, (255,255,255),
                     (0, self.center_ground_y), (WIDTH, self.center_ground_y), 2)
        if self._mvc_pct != 0:
            line_y = int(50 + 70 * (10 - self._mvc_pct / 10))
            pg.draw.line(self.screen, (255,0,0), (0, line_y), (WIDTH, line_y), 2)
        self.draw_stimulus()
        self.draw_bars(self.bar_values)

    def _enter_level_pre(self, level):
        self._selected_level = level
        self._mvc_pct        = MVC_PCT_MAP.get(level, 0)
        self._muscle         = "M1" if level in [1,2,3,4,5] else "M2"
        level_key = str(level)
        self.attempt_counters[level_key] += 1
        self._cycle_attempt = ((self.attempt_counters[level_key] - 1) % 3) + 1
        self._run_count     = 0
        self.bar_values = [0] * self.num_channels
        self._pre_trial_end = time.time() + 5
        self.state = STATE_LEVEL_PRE

    def level_pre_screen(self):
        for event in pg.event.get():
            if event.type == pg.QUIT:
                self.state = STATE_DONE
                return
        if time.time() >= self._pre_trial_end:
            self._enter_level_running()
            return
        remaining = int(self._pre_trial_end - time.time())
        level = self._selected_level
        self.screen.fill(BACKGROUND_COLOR)
        self._draw_text_top(
            f"{self.level_labels[level][:22]}\nMuscle: {self._muscle}\n[GET READY]",
            starter_text=True
        )
        self._update_phase_flash(None)
        self.draw_stimulus()
        lines = [f"Get ready!  {self._muscle}", f"Starts in  {remaining + 1}s"]
        y = HEIGHT // 2
        for line in lines:
            surf = self.font.render(line, True, (0, 255, 0))
            self.screen.blit(surf, surf.get_rect(
                center=(WIDTH//2 - WIDTH//4, y)))
            y += surf.get_height() + 8

    def _enter_level_running(self):
        self._run_count += 1
        if self._run_count > TOTAL_TRIALS:
            self.state = STATE_HOME
            return
        
        level     = self._selected_level
        trial_num = self.completion_counts[level]

        self._reset_flash_state()
        self._timer_start = time.time()

        self.start_recording(["rampup", "hold", "stop"]) 

        self.state = STATE_LEVEL_RUNNING

    def level_running_screen(self):
        level = self._selected_level
        for event in pg.event.get():
            if event.type == pg.QUIT:
                self.state = STATE_DONE
                return

        self.apply_control() 

        elapsed   = round(time.time() - self._timer_start, 3)
        trial_num = self.completion_counts[level]
        self._update_phase_flash(elapsed)

        self.set_phase(self._current_phase)  # ← BaseGame
        self.record_sample()                 # ← BaseGame

        if elapsed >= TRIAL_END:
            self.completion_counts[level] += 1
            print(f"Trial {self.completion_counts[level]} complete — "
                f"attempt {self._cycle_attempt} — elapsed: {elapsed}s")
            samples = self.stop_recording()
            result  = self._calculate_trial_metrics(samples)
            self._session_results.append(result)
            self.save_session_data()
            self._enter_level_running()
            return

        self.screen.fill(BACKGROUND_COLOR)
        self._draw_text_top(
            f"{self.level_labels[level][:22]} — Trial {trial_num + 1}  "
            f"Attempt {self._cycle_attempt}  Time: {elapsed:.1f}s"
        )
        pg.draw.line(self.screen, (255,255,255),
                     (0, self.center_ground_y), (WIDTH, self.center_ground_y), 2)
        if self._mvc_pct != 0:
            line_y = int(50 + 70 * (10 - self._mvc_pct / 10))
            pg.draw.line(self.screen, (255,0,0), (0, line_y), (WIDTH, line_y), 2)
        self.draw_stimulus()
        self.draw_bars(self.bar_values)

    def _calculate_trial_metrics(self, samples):
        level      = self._selected_level
        target     = float(self._mvc_pct)
        target_bar = 0 if self._muscle == "M1" else 1

        ctx = {
            "level":   level,
            "muscle":  self._muscle,
            "mvc_pct": self._mvc_pct,
            "attempt": self.attempt_counters[str(level)],
        }

        flat_samples = []
        for phase_name, phase_samples in samples.items():
            for s in phase_samples:
                flat_samples.append({
                    "phase": phase_name,
                    "t":     round(s["t"], 3),
                    "bar_0": s["bars"][0] if len(s["bars"]) > 0 else "",
                    "bar_1": s["bars"][1] if len(s["bars"]) > 1 else "",
                })

        metrics = {}
        for phase_name, phase_samples in samples.items():
            if not phase_samples:
                continue
            times      = [s["t"] for s in phase_samples]
            bar_arrays = [[] for _ in range(self.num_channels)]
            for s in phase_samples:
                for i, v in enumerate(s["bars"]):
                    bar_arrays[i].append(v)

            if phase_name == "hold" and bar_arrays[target_bar]:
                arr   = np.array(bar_arrays[target_bar])
                error = arr - target
                metrics["hold_target"]             = target
                metrics["hold_mean_error"]         = round(float(np.mean(error)), 2)
                metrics["hold_mean_abs_error"]     = round(float(np.mean(np.abs(error))), 2)
                metrics["hold_std_error"]          = round(float(np.std(error)), 2)
                metrics["hold_pct_time_on_target"] = round(
                    float(np.mean(np.abs(error) <= target * 0.1)) * 100, 1)

            if phase_name == "rampup" and bar_arrays[target_bar]:
                arr       = np.array(bar_arrays[target_bar])
                times_arr = np.array(times)
                above     = np.where(arr >= target)[0]
                metrics["rampup_time_to_target_s"] = (
                    round(float(times_arr[above[0]] - times_arr[0]), 3)
                    if len(above) > 0 else None)

        result = {
            **ctx,
            **metrics,          # ← metrics at top level alongside ctx
            "samples": flat_samples   # ← samples nested same as BoxDropGame
        }
        return result

    def set_volume(self, audio, vol):
        audio.set_volume(max(0.0, min(1.0, vol)))

    def _draw_text_centered(self, text, y_offset=0, color=TEXTCOLOR):
        surf = self.font.render(text, True, color)
        self.screen.blit(surf, surf.get_rect(
            center=(WIDTH//2, HEIGHT//2 + y_offset)))

    def _draw_text_right(self, text, y_offset=0, color=TEXTCOLOR):
        surf = self.font.render(text, True, color)
        self.screen.blit(surf, surf.get_rect(
            center=(WIDTH//2 + WIDTH//4, HEIGHT//2 + y_offset)))

    def _draw_text_top(self, text, starter_text=False, color=TEXTCOLOR):
        if starter_text:
            y = HEIGHT // 2 - 100
            for line in text.split("\n"):
                surf = self.font.render(line, True, color)
                self.screen.blit(surf, (WIDTH//2 - surf.get_width()//2, y))
                y += surf.get_height() + 10
        else:
            surf = self.font.render(text, True, color)
            self.screen.blit(surf, (WIDTH//2 - surf.get_width()//2, 10))

    def _get_phase(self, elapsed: float) -> str:
        if   elapsed < RAMPUP_AT: return "rest"
        elif elapsed < HOLD_AT:   return "rampup"
        elif elapsed < STOP_AT:   return "hold"
        elif elapsed < TRIAL_END: return "stop"
        else:                     return "rest"

    def _reset_flash_state(self):
        self._last_triggered_phase = None
        self._flash_visible        = True
        self._flash_last_toggle    = time.time()
        self._current_phase        = "rest"

    def _update_phase_flash(self, elapsed):
        if elapsed is None:
            self._current_phase = "rest"
            self._flash_visible = True
            return
        new_phase = self._get_phase(elapsed)
        if new_phase != self._last_triggered_phase:
            if new_phase == "rampup":
                self.set_volume(self._trans_to_rampup, 1.0)
                self._trans_to_rampup.play()
            elif new_phase == "hold":
                self.set_volume(self._trans_to_hold, 1.0)
                self._trans_to_hold.play()
            elif new_phase == "stop":
                self.set_volume(self._trans_to_stop, 1.0)
                self._trans_to_stop.play()
            self._last_triggered_phase = new_phase
            self._flash_last_toggle    = time.time()
            self._flash_visible        = True
        self._current_phase = new_phase
        hz_map = {"rest": FLASH_HZ_REST, "rampup": FLASH_HZ_RAMPUP,
                  "hold": FLASH_HZ_HOLD, "stop":   FLASH_HZ_STOP}
        hz = hz_map.get(new_phase)
        if hz is None:
            self._flash_visible = True
            return
        half_period = 1.0 / (2 * hz)
        now = time.time()
        if now - self._flash_last_toggle >= half_period:
            self._flash_last_toggle = now
            self._flash_visible = not self._flash_visible
            if self._flash_visible:
                if new_phase == "rest":
                    self.set_volume(self._flash_sound_rest, 0.4)
                    self._flash_sound_rest.play()
                elif new_phase == "rampup":
                    self.set_volume(self._flash_sound_rampup, 0.45)
                    self._flash_sound_rampup.play()

    def draw_stimulus(self, Rest_color=(0,255,0), Ramp_up_color=(255,255,0),
                      Ramp_down_color=(60,60,60), Hold_color=(255,0,0)):
        phase = self._current_phase
        vis   = self._flash_visible
        DIM   = (60, 60, 60)

        def seg_color(seg_phase, base):
            return (base if vis else DIM) if seg_phase == phase else base

        peak_height = 60
        ramp_w      = 30
        hold_w      = 50
        p0 = (self.mid_ground_x - 50,             self.mid_ground_y + 20)
        p1 = (self.mid_ground_x,                   self.mid_ground_y + 20)
        p2 = (self.mid_ground_x + ramp_w,          self.mid_ground_y + 20 - peak_height)
        p3 = (self.mid_ground_x + ramp_w + hold_w, self.mid_ground_y + 20 - peak_height)
        p4 = (self.mid_ground_x + ramp_w + hold_w, self.mid_ground_y + 20)
        pg.draw.lines(self.screen, (255,255,255), False, [p0,p1,p2,p3,p4], 2)
        if phase == "rest" and vis:
            pg.draw.lines(self.screen, seg_color("rest", Rest_color), False, [p0,p1], 3)
            s = self.font.render("RELAX", True, Rest_color)
            self.screen.blit(s, ((p0[0]+p1[0])//2 - s.get_width()//2,
                                  self.mid_ground_y + 30))
        if phase == "rampup" and vis:
            pg.draw.lines(self.screen, seg_color("rampup", Ramp_up_color), False, [p1,p2], 3)
            s = self.font.render("RAMP UP", True, Ramp_up_color)
            self.screen.blit(s, (p2[0] - s.get_width() - 20, self.mid_ground_y - 30))
        if phase == "hold" and vis:
            pg.draw.lines(self.screen, seg_color("hold", Hold_color), False, [p2,p3], 3)
            s = self.font.render("HOLD", True, Hold_color)
            self.screen.blit(s, ((p2[0]+p3[0])//2 - s.get_width()//2,
                                  p2[1] - s.get_height() - 4))
        if phase == "stop" and vis:
            pg.draw.lines(self.screen, seg_color("stop", Ramp_down_color), False, [p3,p4], 3)

    def draw_bars(self, bar_values):
        for i in range(self.num_channels):
            label      = self.font.render(f"M_{i+1}", True, TEXTCOLOR)
            bar_value  = self.font.render(f"{bar_values[i]}%", True, TEXTCOLOR)
            bar_height = int((bar_values[i] / 100) * BAR_MAX_HEIGHT)
            if i % 2 == 0:
                x_pos = self.center_ground_x - (BTW_BAR_DISTANCE + BAR_WIDTH) * (i//2 + 1)
            else:
                x_pos = self.center_ground_x + (BTW_BAR_DISTANCE + BAR_WIDTH) * (i//2)
            x_lbl = x_pos + BAR_WIDTH//2 - label.get_width()//2
            y_pos = self.center_ground_y
            pg.draw.rect(self.screen, self.bar_colours[i],
                         (x_pos, y_pos - bar_height, BAR_WIDTH, bar_height))
            self.screen.blit(label,     (x_lbl, y_pos + 10))
            self.screen.blit(bar_value, (x_lbl, y_pos - bar_height
                                         - bar_value.get_height() - 4))

    def _build_level_labels(self):
        self.level_labels = {
            1:  f"Level 1 (20%-MVC-M1)       ({self.completion_counts.get(1,0)})",
            2:  f"Level 2 (40%-MVC-M1)       ({self.completion_counts.get(2,0)})",
            3:  f"Level 3 (60%-MVC-M1)       ({self.completion_counts.get(3,0)})",
            4:  f"Level 4 (80%-MVC-M1)       ({self.completion_counts.get(4,0)})",
            5:  f"Level 5 (100%-MVC-M1)      ({self.completion_counts.get(5,0)})",
            8:  f"Level 1 (20%-MVC-M2)       ({self.completion_counts.get(8,0)})",
            9:  f"Level 2 (40%-MVC-M2)       ({self.completion_counts.get(9,0)})",
            10: f"Level 3 (60%-MVC-M2)      ({self.completion_counts.get(10,0)})",
            11: f"Level 4 (80%-MVC-M2)      ({self.completion_counts.get(11,0)})",
            12: f"Level 5 (100%-MVC-M2)     ({self.completion_counts.get(12,0)})",
            13: f"PRACTICE (FREEMODE)        ({self.completion_counts.get(13,0)})",
            14: f"TEST MODE  (no data recorded)",
        }


if __name__ == "__main__":
    app = QApplication(sys.argv)
    game = BarGame_v2(num_channels=2)
    game.start_game()
    sys.exit(app.exec_())