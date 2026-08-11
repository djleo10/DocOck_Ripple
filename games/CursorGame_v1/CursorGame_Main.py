import os
import sys
import json
import time
import numpy as np
from datetime import datetime
import pygame as pg
from PyQt5.QtWidgets import QApplication

try:
    from .CursorGame_Settings import *
except ImportError:
    from CursorGame_Settings import *

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

class CursorGame_v1(BaseGame):

    def __init__(self, basepath=None, num_channels=2, **kwargs):
        if basepath is None:
            basepath = os.path.dirname(os.path.abspath(__file__))
        super().__init__(basepath=basepath, num_channels=num_channels, **kwargs)

        self._session_results   = []
        self.completion_counts = {lvl: 0 for lvl in LEVELS}
        self.attempt_counters  = {str(lvl): 0 for lvl in LEVELS}
        self.level_labels      = {}

        self.state = STATE_WELCOME

        self._button_rects   = []
        self._pre_trial_end  = None
        self._timer_start    = None
        self._mvc_pct        = 0
        self._muscle         = ""
        self._cycle_attempt  = 0
        self._selected_level = None
        self._run_count      = 0

        self._prev_sample_t = None
        self._prev_cursor_x = 0
        self._prev_cursor_y = 0
        self._prev_vel_x    = 0.0
        self._prev_vel_y    = 0.0
        self._emg_strengths = [0.0] * num_channels 

        self._freemode_session = 0
        self._freemode_start   = None

        self._test_level     = None
        self._test_run_count = 0
        self._test_btn_rects = []

        self._target_node      = None
        self._last_target_node = None
        self._node_queue = []

        self._target_node_start  = None
        self._on_target_since    = None
        self._hold_elapsed       = 0.0
        self._target_missed      = False
        self._miss_display_until = None
        self._hits_count         = 0
        self._misses_count       = 0

    def game_name(self) -> str:
        return "cursor_game_v1"

    def setup(self):
        pg.init()
        self.screen = pg.display.set_mode((WIDTH, HEIGHT))
        pg.display.set_caption("Cursor Game v1")
        self.clock  = pg.time.Clock()
        self.font   = pg.font.SysFont(None, TEXTSIZE)
        self.small_font = pg.font.SysFont(None, 20)

        self.bar_values = [0] * self.num_channels

        self.cursor_color = (80, 220, 255)
        self.rect_color   = (255, 255, 255)

        # control field
        field_margin_top    = 130
        field_margin_bottom = 70
        field_size = min(WIDTH, HEIGHT - field_margin_top - field_margin_bottom)
        self.field_left   = (WIDTH - field_size) // 2
        self.field_top    = field_margin_top
        self.field_right  = self.field_left + field_size
        self.field_bottom = self.field_top + field_size
        self.field_w = self.field_h = field_size

        emg_cols = [f"emg_ch{i+1}" for i in range(self.num_channels)]

        self._open_csv([
            "level", "muscle", "mvc_pct", "attempt",
            "target_x", "target_y", "result",
            "phase", "t",
            "cursor_x", "cursor_y",
            "vel_x", "vel_y",
            "acc_x", "acc_y",
            *emg_cols,                   
        ])

        self._build_level_labels()
        self._load_progress()

    def tick(self):
        if   self.state == STATE_WELCOME:       self.welcome_screen()
        elif self.state == STATE_HOME:          self.home_screen()
        elif self.state == STATE_FREEMODE:      self._tick_freemode()
        elif self.state == STATE_TEST_MENU:     self._tick_test_menu()
        elif self.state == STATE_TEST_PRE:      self._tick_test_pre()
        elif self.state == STATE_TEST_RUNNING:  self._tick_test_running()
        elif self.state == STATE_LEVEL_PRE:     self._tick_level_pre()
        elif self.state == STATE_LEVEL_RUNNING: self._tick_level_running()
        elif self.state == STATE_DONE:
            self.stop_game()
            return
        pg.display.flip()
        self.clock.tick(FPS)

    def get_current_sample(self) -> dict:
        elapsed = round(time.time() - self._timer_start, 3) \
                if self._timer_start else 0.0

        dt = elapsed - self._prev_sample_t if self._prev_sample_t is not None else 0.0

        if dt > 0:
            vel_x = (self.bar_values[0] - self._prev_cursor_x) / dt
            vel_y = (self.bar_values[1] - self._prev_cursor_y) / dt
        else:
            vel_x = vel_y = 0.0

        if dt > 0:
            acc_x = (vel_x - self._prev_vel_x) / dt
            acc_y = (vel_y - self._prev_vel_y) / dt
        else:
            acc_x = acc_y = 0.0

        self._prev_sample_t = elapsed
        self._prev_cursor_x = self.bar_values[0]
        self._prev_cursor_y = self.bar_values[1]
        self._prev_vel_x    = vel_x
        self._prev_vel_y    = vel_y

        emg_fields = {
            f"emg_ch{i+1}": round(self._emg_strengths[i], 2)
            for i in range(self.num_channels)
        }

        return {
            "t":        elapsed,
            "cursor_x": self.bar_values[0],
            "cursor_y": self.bar_values[1] if len(self.bar_values) > 1 else 0,
            "vel_x":    round(vel_x, 3),
            "vel_y":    round(vel_y, 3),
            "acc_x":    round(acc_x, 3),
            "acc_y":    round(acc_y, 3),
            **emg_fields,             
        }

    def get_save_data(self) -> dict:
        return {
            "completion_counts": {str(k): v for k, v in self.completion_counts.items()},
            "attempt_counters":  self.attempt_counters,
            "data_samples":      self._session_results
        }

    def on_game_over(self):
        if self._recording:
            samples = self.stop_recording()
            if any(samples.values()):
                metrics = self._calculate_trial_metrics(samples)
                self._session_results.append(metrics)
                self.save_session_data()

    def apply_keyboard_control(self):
        # arrow keys - cursor stays where it is when no key pressed
        # unlike BarGame bars which decay
        keys = pg.key.get_pressed()
        step = 2
        if keys[pg.K_LEFT]:
            self.bar_values[0] = max(0,   self.bar_values[0] - step)
        elif keys[pg.K_RIGHT]:
            self.bar_values[0] = min(100, self.bar_values[0] + step)
        if keys[pg.K_DOWN]:
            self.bar_values[1] = max(0,   self.bar_values[1] - step)
        elif keys[pg.K_UP]:
            self.bar_values[1] = min(100, self.bar_values[1] + step)

    def apply_emg_values(self, values):
        for i, v in enumerate(values[:self.num_channels]):
            self._emg_strengths[i] = float(v)
            self.bar_values[i]     = max(0, min(100, int(v)))

    def welcome_screen(self):
        for event in pg.event.get():
            if event.type == pg.QUIT:
                self.state = STATE_DONE
                return
            elif event.type == pg.KEYDOWN and event.key == pg.K_p:
                self.state = STATE_HOME
                return
        self.screen.fill(BACKGROUND_COLOR)
        self._draw_text_centered("CURSOR GAME (V1)", -100)
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

    def _tick_freemode(self):
        for event in pg.event.get():
            if event.type == pg.QUIT:
                self._exit_freemode()
                return
            elif event.type == pg.KEYDOWN and event.key == pg.K_q:
                self._exit_freemode()
                return

        self.apply_control()

        elapsed = round(time.time() - self._freemode_start, 1)
        self.screen.fill(BACKGROUND_COLOR)
        self._draw_text_top(
            f"FREEMODE — Session {self._freemode_session}   "
            f"Time: {elapsed}s   [Q to stop]"
        )
        self.draw_cursor(self.bar_values)

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

    def _tick_test_menu(self):
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
        self._muscle         = "M1" if level in [1, 2, 3, 4, 5] else "M2"
        self._test_run_count = 0
        self._hits_count     = 0
        self._misses_count   = 0
        self._pre_trial_end  = time.time() + 5
        self._node_queue    = [] 
        self.state = STATE_TEST_PRE

    def _tick_test_pre(self):
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
        lines = [f"Get ready!  {self._muscle}", f"Starts in  {remaining + 1}s"]
        y = HEIGHT // 2 + 60
        for line in lines:
            surf = self.font.render(line, True, (230, 200, 0))
            self.screen.blit(surf, surf.get_rect(center=(WIDTH//2, y)))
            y += surf.get_height() + 8

    def _enter_test_running(self):
        self._test_run_count    += 1
        self._pick_target_node()
        self._timer_start        = time.time()
        self._target_node_start  = time.time()
        self._on_target_since    = None
        self._hold_elapsed       = 0.0
        self._target_missed      = False
        self._miss_display_until = None
        self.state = STATE_TEST_RUNNING

    def _tick_test_running(self):
        for event in pg.event.get():
            if event.type == pg.QUIT:
                self.state = STATE_DONE
                return
            elif event.type == pg.KEYDOWN and event.key == pg.K_q:
                self.state = STATE_HOME
                return

        self.apply_control()
        now = time.time()

        # ---- Miss display window ----
        if self._miss_display_until is not None:
            if now >= self._miss_display_until:
                self._miss_display_until = None
                self._target_missed      = False
                self._enter_test_running()
                return
            self.screen.fill(BACKGROUND_COLOR)
            self._draw_text_top(
                f"TEST MODE — {self._muscle}  {self._mvc_pct}% MVC"
                f"MISSED — moving to next target"
                f"Hits: {self._hits_count}          Missed: {self._misses_count}",
                f"[Q to exit]",
                color=(230, 200, 0)
            )
            self.draw_cursor(self.bar_values)
            return

        # ---- Distance to target ----
        tx_pct, ty_pct = self._target_node
        dist      = ((self.bar_values[0] - tx_pct) ** 2 +
                     (self.bar_values[1] - ty_pct) ** 2) ** 0.5
        on_target = dist <= TARGET_HIT_RADIUS

        if on_target:
            if self._on_target_since is None:
                self._on_target_since = now
            self._hold_elapsed = now - self._on_target_since
        else:
            self._on_target_since = None
            self._hold_elapsed    = 0.0

        # ---- Success ----
        if self._hold_elapsed >= TARGET_HOLD_DURATION:
            self._hits_count += 1
            self._enter_test_running()
            return

        # ---- Miss ----
        time_on_trial = now - self._target_node_start
        if time_on_trial >= self._current_timeout():
            self._misses_count      += 1
            self._target_missed      = True
            self._miss_display_until = now + MISS_DISPLAY_TIME
            return

        # ---- Draw ----
        time_left = self._current_timeout() - time_on_trial
        self.screen.fill(BACKGROUND_COLOR)
        self._draw_text_top(
            f"TEST — {self._muscle} {self._mvc_pct}%MVC — "
            f"rep {self._test_run_count}   "
            f"Target: ({tx_pct}%,{ty_pct}%)  "
            f"Time left: {time_left:.1f}s  "
            f"Hits: {self._hits_count}  Missed: {self._misses_count}  [Q exit]",
            color=(230, 200, 0)
        )
        self.draw_cursor(self.bar_values)

    def _current_timeout(self):
        if self._selected_level in LEVEL_TIMEOUT:
            return LEVEL_TIMEOUT[self._selected_level]
        return DEFAULT_TIMEOUT 

    def _enter_level_pre(self, level):
        self._selected_level = level
        self._mvc_pct        = MVC_PCT_MAP.get(level, 0)
        self._muscle         = "M1" if level in [1, 2, 3, 4, 5] else "M2"
        level_key = str(level)
        self.attempt_counters[level_key] += 1
        self._cycle_attempt = ((self.attempt_counters[level_key] - 1) % 3) + 1
        self._run_count     = 0
        self._pre_trial_end = time.time() + 5
        self._hits_count    = 0      # reset for this level session
        self._misses_count  = 0
        self._node_queue    = [] 
        self.state = STATE_LEVEL_PRE

    def _tick_level_pre(self):
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
        lines = [f"Get ready!  {self._muscle}", f"Starts in  {remaining + 1}s"]
        y = HEIGHT // 2 + 60
        for line in lines:
            surf = self.font.render(line, True, (0, 255, 0))
            self.screen.blit(surf, surf.get_rect(center=(WIDTH//2, y)))
            y += surf.get_height() + 8

    def _enter_level_running(self):
        self._run_count += 1
        if self._run_count > TOTAL_TRIALS:
            self.state = STATE_HOME
            return

        self._pick_target_node()
        self._timer_start        = time.time()
        self._target_node_start  = time.time()
        self._on_target_since    = None
        self._hold_elapsed       = 0.0
        self._target_missed      = False
        self._miss_display_until = None

        self._prev_sample_t = None   # ← ADD: reset vel/acc tracking
        self._prev_cursor_x = 0
        self._prev_cursor_y = 0
        self._prev_vel_x    = 0.0
        self._prev_vel_y    = 0.0

        self.start_recording(["approach", "hold"])
        self.state = STATE_LEVEL_RUNNING

    def _tick_level_running(self):
        level = self._selected_level

        for event in pg.event.get():
            if event.type == pg.QUIT:
                self.state = STATE_DONE
                return

        self.apply_control()          # always update cursor position

        now       = time.time()
        elapsed   = round(now - self._timer_start, 3)
        trial_num = self.completion_counts[level]

        # ---- Miss display window (showing X) ----
        if self._miss_display_until is not None:
            if now >= self._miss_display_until:
                self._miss_display_until = None
                self._target_missed      = False
                samples = self.stop_recording()
                metrics = self._calculate_trial_metrics(samples, result="miss")
                self._session_results.append(metrics)
                self.save_session_data()
                self._enter_level_running()
                return
            # Still showing X — just draw
            self.screen.fill(BACKGROUND_COLOR)
            self._draw_text_top(
                f"{self.level_labels[level][:22]}  "
                f"MISSED   "
                f"Hits: {self._hits_count}  Misses: {self._misses_count}"
            )
            self.draw_cursor(self.bar_values)
            return

        # ---- Active trial ----
        self.record_sample()

        tx_pct, ty_pct = self._target_node
        dist      = ((self.bar_values[0] - tx_pct) ** 2 +
                     (self.bar_values[1] - ty_pct) ** 2) ** 0.5
        on_target = dist <= TARGET_HIT_RADIUS

        if on_target:
            if self._on_target_since is None:
                self._on_target_since = now
            self._hold_elapsed = now - self._on_target_since
            self.set_phase("hold")
        else:
            if self._on_target_since is not None:
                self._on_target_since = None
            self._hold_elapsed = 0.0
            self.set_phase("approach")

        # ---- SUCCESS — held long enough ----
        if self._hold_elapsed >= TARGET_HOLD_DURATION:
            self._hits_count += 1
            self.completion_counts[level] += 1
            samples = self.stop_recording()
            metrics = self._calculate_trial_metrics(samples, result="hit")
            self._session_results.append(metrics)
            self.save_session_data()
            self._enter_level_running()
            return

        # ---- MISS — timeout ----
        time_on_trial = now - self._target_node_start
        if time_on_trial >= self._current_timeout():
            self._misses_count      += 1
            self._target_missed      = True
            self._miss_display_until = now + MISS_DISPLAY_TIME
            return

        # ---- Draw ----
        time_left = self._current_timeout() - time_on_trial
        self.screen.fill(BACKGROUND_COLOR)
        self._draw_text_top(
            f"{self.level_labels[level][:22]} — Trial {trial_num + 1}  "
            f"Att {self._cycle_attempt}  "
            f"Time left: {time_left:.1f}s  "
            f"Hits: {self._hits_count}  Missed: {self._misses_count}"
        )
        self.draw_cursor(self.bar_values)

    def _calculate_trial_metrics(self, samples, result="hit"):
        level      = self._selected_level
        target_x   = float(self._target_node[0]) if self._target_node else 0.0
        target_y   = float(self._target_node[1]) if self._target_node else 0.0

        ctx = {
            "level":    level,
            "muscle":   self._muscle,
            "mvc_pct":  self._mvc_pct,
            "attempt":  self.attempt_counters[str(level)],
            "target_x": target_x,
            "target_y": target_y,
            "result":   result,
        }

        flat_samples = []
        for phase_name, phase_samples in samples.items():
            for s in phase_samples:
                emg_fields = {
                    f"emg_ch{i+1}": s.get(f"emg_ch{i+1}", "")
                    for i in range(self.num_channels)
                }
                flat_samples.append({
                    "phase":    phase_name,
                    "t":        round(s["t"], 3),
                    "cursor_x": s["cursor_x"],
                    "cursor_y": s["cursor_y"],
                    "vel_x":    s.get("vel_x", ""),
                    "vel_y":    s.get("vel_y", ""),
                    "acc_x":    s.get("acc_x", ""),
                    "acc_y":    s.get("acc_y", ""),
                    **emg_fields,
                })

        metrics = {}
        for phase_name, phase_samples in samples.items():
            if not phase_samples:
                continue
            times     = [s["t"]        for s in phase_samples]
            xs        = np.array([s["cursor_x"] for s in phase_samples])
            ys        = np.array([s["cursor_y"] for s in phase_samples])
            times_arr = np.array(times)
            err_x     = xs - target_x
            err_y     = ys - target_y
            dist      = np.sqrt(err_x ** 2 + err_y ** 2)

            metrics[f"{phase_name}_n_samples"]        = len(phase_samples)
            metrics[f"{phase_name}_duration_s"]        = round(times[-1] - times[0], 3) if len(times) > 1 else 0
            metrics[f"{phase_name}_mean_dist_error"]   = round(float(np.mean(dist)), 2)
            metrics[f"{phase_name}_pct_time_on_target"]= round(float(np.mean(dist <= TARGET_HIT_RADIUS)) * 100, 1)

            if phase_name == "approach":
                within = np.where(dist <= TARGET_HIT_RADIUS)[0]
                metrics["approach_time_to_target_s"] = (
                    round(float(times_arr[within[0]] - times_arr[0]), 3)
                    if len(within) > 0 else None)

            if phase_name == "hold":
                metrics["hold_std_dist_error"] = round(float(np.std(dist)), 2)

        return {
            **ctx,
            **metrics,
            "samples": flat_samples,
        }

    def _load_progress(self):
        path = os.path.join(
            os.path.dirname(os.path.abspath(__file__)),
            "..", "..", "data", f"{self.game_name()}.json"
        )
        if not os.path.exists(path):
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
            print(f"[CursorGame] Progress loaded")
        except Exception as e:
            print(f"[CursorGame] Failed to load progress: {e}")

    def draw_cursor(self, cursor_pos):
        # Border
        field_rect = pg.Rect(self.field_left, self.field_top, self.field_w, self.field_h)
        pg.draw.rect(self.screen, (90, 90, 90), field_rect, 2)

        label_col = (140, 140, 140)

        xs = [self.field_left   + int(self.field_w * p / 100) for p in GRID_PCTS_X]
        ys = [self.field_bottom - int(self.field_h * p / 100) for p in GRID_PCTS_Y]

        for gx in xs:
            pg.draw.line(self.screen, (45, 45, 45),
                         (gx, self.field_top), (gx, self.field_bottom), 1)
        for gy in ys:
            pg.draw.line(self.screen, (45, 45, 45),
                         (self.field_left, gy), (self.field_right, gy), 1)

        # ---- target node ----
        if self._target_node is not None:
            tx_pct, ty_pct = self._target_node
            tx = self.field_left   + int(self.field_w * tx_pct / 100)
            ty = self.field_bottom - int(self.field_h * ty_pct / 100)

            if self._target_missed:
                # Dark red circle + white X
                pg.draw.circle(self.screen, (80, 0, 0),   (tx, ty), 14)
                pg.draw.circle(self.screen, (200, 0, 0),  (tx, ty), 14, 2)
                s = 9
                pg.draw.line(self.screen, (255, 60, 60),
                             (tx - s, ty - s), (tx + s, ty + s), 3)
                pg.draw.line(self.screen, (255, 60, 60),
                             (tx + s, ty - s), (tx - s, ty + s), 3)
            else:
                dist = ((cursor_pos[0] - tx_pct) ** 2 +
                        (cursor_pos[1] - ty_pct) ** 2) ** 0.5
                on_target = dist <= TARGET_HIT_RADIUS

                dot_col  = (255, 200, 230) if on_target else (255, 105, 180)
                ring_col = (255, 255, 255) if on_target else (200, 80, 140)
                pg.draw.circle(self.screen, dot_col,  (tx, ty), 14)
                pg.draw.circle(self.screen, ring_col, (tx, ty), 14, 2)

                # Hold progress bar below the dot
                if on_target and self._hold_elapsed > 0:
                    progress = min(1.0, self._hold_elapsed / TARGET_HOLD_DURATION)
                    bar_w = 44
                    bar_h = 6
                    bx    = tx - bar_w // 2
                    by    = ty + 20
                    pg.draw.rect(self.screen, (50, 50, 50),
                                 (bx - 1, by - 1, bar_w + 2, bar_h + 2))
                    pg.draw.rect(self.screen, (0, 255, 80),
                                 (bx, by, int(bar_w * progress), bar_h))
                    # Seconds remaining label
                    secs_left = TARGET_HOLD_DURATION - self._hold_elapsed
                    lbl = self.small_font.render(f"{secs_left:.1f}s", True, (0, 255, 80))
                    self.screen.blit(lbl, (tx - lbl.get_width() // 2, by + bar_h + 3))

        # Tick labels: 0, 50, 100 along each axis
        for pct, gx in zip(GRID_PCTS_X, xs):
            lbl = self.small_font.render(str(pct), True, label_col)
            self.screen.blit(lbl, (gx - lbl.get_width() // 2, self.field_bottom + 6))
        for pct, gy in zip(GRID_PCTS_Y, ys):
            lbl = self.small_font.render(str(pct), True, label_col)
            self.screen.blit(lbl, (self.field_left - lbl.get_width() - 6,
                                    gy - lbl.get_height() // 2))

        # Axis labels — shifted outward to clear the tick numbers
        x_lbl = self.font.render("M_1 (X)", True, TEXTCOLOR)
        self.screen.blit(x_lbl, (
            self.field_left + self.field_w // 2 - x_lbl.get_width() // 2,
            self.field_bottom + 38))       

        y_lbl_rot = pg.transform.rotate(
            self.font.render("M_2 (Y)", True, TEXTCOLOR), 90)
        self.screen.blit(y_lbl_rot, (
            self.field_left - y_lbl_rot.get_width() - 30,   # -30 to clear tick labels
            self.field_top + self.field_h // 2 - y_lbl_rot.get_height() // 2))

        # Cursor dot
        px = self.field_left   + int(self.field_w * (cursor_pos[0] / 100))
        py = self.field_bottom - int(self.field_h * (cursor_pos[1] / 100))
        px = max(self.field_left,  min(self.field_right,  px))
        py = max(self.field_top,   min(self.field_bottom, py))

        pg.draw.circle(self.screen, self.cursor_color, (px, py), 10)
        pg.draw.circle(self.screen, (255, 255, 255),   (px, py), 10, 2)

        val_lbl = self.font.render(
            f"({cursor_pos[0]}%, {cursor_pos[1]}%)", True, TEXTCOLOR)
        self.screen.blit(val_lbl, (px - val_lbl.get_width() // 2, py - 30))
    
    def _build_node_queue(self):
        """Shuffle all 9 nodes into a fresh queue."""
        nodes = list(GRID_NODES)
        random.shuffle(nodes)
        if len(nodes) > 1 and nodes[0] == self._last_target_node:
            nodes.append(nodes.pop(0))
        self._node_queue = nodes
        print(f"[CursorGame] New node queue: {self._node_queue}")

    def _pick_target_node(self):
        if not self._node_queue:
            self._build_node_queue()
        node = self._node_queue.pop(0)
        self._target_node      = node
        self._last_target_node = node
        print(f"[CursorGame] Target: {node}  |  "
              f"Remaining this round: {len(self._node_queue)}")

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
    game = CursorGame_v1(num_channels=2)
    game.start_game()
    sys.exit(app.exec_())