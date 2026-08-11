import json
import os
import sys
import time
import random
import numpy as np
import pygame as pg
from datetime import datetime
from PyQt5.QtWidgets import QApplication
from PyQt5.QtCore import QTimer

try:
    from .BoxDropGame_settings import *
except ImportError:
    from BoxDropGame_settings import *

try:
    from ..BaseGame import BaseGame
except ImportError:
    from games.BaseGame import BaseGame

STATE_WELCOME      = "welcome"
STATE_HOME         = "home"
STATE_INSTRUCTIONS = "instructions"
STATE_ACHIEVEMENTS = "achievements"
STATE_LEVEL_PRE    = "level_pre"
STATE_LEVEL        = "level"
STATE_FREE         = "free"
STATE_DONE         = "done"


class BoxDropGame_v1(BaseGame):
    def game_name(self) -> str:
        return "box_drop_game"

    def setup(self):
        pg.init()
        self.screen = pg.display.set_mode((WIDTH, HEIGHT))
        pg.display.set_caption("Box Drop Game v1")
        self.clock = pg.time.Clock()
        self.font  = pg.font.SysFont(None, TEXTSIZE)

        self.state = STATE_WELCOME

        # tracking
        self.completion_counts = {lvl: 0 for lvl in LEVELS}
        self.fastest_times     = {lvl: float("inf") for lvl in LEVELS}
        self.attempt_counters  = {str(lvl): 0 for lvl in LEVELS}
        self.attempt_counters["Free"] = 0

        # movement
        self._velocity      = 0.0
        self._prev_velocity = 0.0
        self._accel     = 0.5
        self._max_speed = 10.0
        self._friction  = 0.8
        self._last_keypress = "None"

        # level state
        self._selected_level = None
        self._player         = None
        self._target         = None
        self._start_marker   = None
        self._obstacles      = []
        self._obs_speed      = 0
        self._hold_start     = None
        self._hold_duration  = 0
        self._level_start    = None
        self._timer_start    = None
        self._pre_end        = None

        # free mode state
        self._lives      = 3
        self._score      = 0
        self._has_coin   = False
        self._coin       = None
        self._free_start = None

        # home buttons
        self._button_rects   = []

        # results
        self._session_results = []

        self._emg_strength = 0.0 
        self._emg_chan_send = None

        self._open_csv(fieldnames=[
        "level", "attempt", "success", "duration_s",
        "t", "keypress", "velocity", "acceleration",
        "emg_strength", "emg_chan",   
        ])

        self._load_progress()

    def get_current_sample(self) -> dict:
        elapsed = round(time.time() - self._level_start, 2) \
                  if self._level_start else 0.0
        return {
            "t":            elapsed,
            "keypress":     self._last_keypress,
            "velocity":     round(self._velocity, 3),
            "acceleration": round(self._velocity - self._prev_velocity, 3),
            "emg_strength": self._emg_strength,  
            "emg_chan":     self._emg_chan_send,
        }

    def get_save_data(self) -> dict:
        return {
            "completion_counts": {str(k): v for k, v in self.completion_counts.items()},
            "fastest_times":     {str(k): round(v, 2) for k, v in self.fastest_times.items() if v != float("inf")},
            "attempt_counters":  self.attempt_counters,
            "data_samples":   self._session_results
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
            for k, v in data.get("fastest_times", {}).items():
                key = int(k) if k.isdigit() else k
                if key in self.fastest_times:
                    self.fastest_times[key] = v
            for k, v in data.get("attempt_counters", {}).items():
                if k in self.attempt_counters:
                    self.attempt_counters[k] = v
            print(f"[BoxDrop] Progress loaded")
        except Exception as e:
            print(f"[BoxDrop] Failed to load progress: {e}")

    def on_game_over(self):
        if self._recording:
            samples = self.stop_recording()
            self._store_result(
                str(self._selected_level) if self._selected_level else "Free",
                samples, success=False)
                        
    def tick(self):
        if   self.state == STATE_WELCOME:      self.welcome_screen()
        elif self.state == STATE_HOME:         self.home_screen()
        elif self.state == STATE_INSTRUCTIONS: self.instructions_screen()
        elif self.state == STATE_ACHIEVEMENTS: self.achievement_screen()
        elif self.state == STATE_LEVEL_PRE:    self._tick_level_pre()
        elif self.state == STATE_LEVEL:        self._tick_level()
        elif self.state == STATE_FREE:         self._tick_free()
        elif self.state == STATE_DONE:
            self.stop_game()
            return

        pg.display.flip()
        self.clock.tick(FPS)

    def welcome_screen(self):
        for event in pg.event.get():
            if event.type == pg.QUIT:
                self.state = STATE_DONE
                return
            elif event.type == pg.KEYDOWN and event.key == pg.K_p:
                self.state = STATE_HOME
                return

        self.screen.fill(BLACK)
        self._draw_text_centered("BLOCK GAME", -100)
        self._draw_text_centered("Press 'P' to Play.", 20)

    def _build_home_buttons(self):
        level_labels = {
            lvl: f"Level {lvl}       ({self.completion_counts[lvl]})"
            for lvl in LEVELS
        }
        menu_items = [
            (level_labels[1], 1), (level_labels[2], 2),
            (level_labels[3], 3), (level_labels[4], 4),
            (level_labels[5], 5), (level_labels[6], 6),
            ("Free Mode",     7),
            ("Instructions",  8),
            ("Achievements",  9),
        ]
        self._button_rects = []
        spacing = 50
        top = HEIGHT // 2 - (len(menu_items) * spacing) // 2
        for i, (label, idx) in enumerate(menu_items):
            rect = pg.Rect(WIDTH // 2 - 110, top + i * spacing, 220, 42)
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
                        if   idx == 7:      self._enter_free()
                        elif idx == 8:      self.state = STATE_INSTRUCTIONS
                        elif idx == 9:      self.state = STATE_ACHIEVEMENTS
                        elif idx in LEVELS: self._enter_level_pre(idx)
                        return

        self.screen.fill(BLACK)
        self._draw_text_centered("Select a Level", -260)
        for rect, idx, label in self._button_rects:
            pg.draw.rect(self.screen, WHITE, rect)
            surf = self.font.render(label, True, BLACK)
            self.screen.blit(surf, surf.get_rect(center=rect.center))

    def instructions_screen(self):
        for event in pg.event.get():
            if event.type == pg.QUIT:
                self.state = STATE_DONE
                return
            elif event.type == pg.KEYDOWN:
                self.state = STATE_HOME
                return

        lines = [
            "Instructions:",
            "- Use LEFT and RIGHT arrows to move.",
            "- Level 1: Go right to the target.",
            "- Level 2: Go left to the target.",
            "- Level 3: Hold on target for 5 seconds.",
            "- Levels 4-6: Avoid falling red blocks.",
            "- Free Mode: Collect coins, dodge blocks.",
            "Press any key to return.",
        ]
        self.screen.fill(BLACK)
        for i, line in enumerate(lines):
            self._draw_text_centered(line, -180 + i * 40)

    def achievement_screen(self):
        for event in pg.event.get():
            if event.type == pg.QUIT:
                self.state = STATE_DONE
                return
            elif event.type == pg.MOUSEBUTTONDOWN:
                self.state = STATE_HOME
                return

        self.screen.fill(BLACK)
        self._draw_text_centered("Achievements", -240)
        for i in LEVELS:
            fastest = (
                f"{self.fastest_times[i]}s"
                if self.fastest_times[i] != float("inf")
                else "N/A"
            )
            self._draw_text_centered(
                f"Level {i}: {self.completion_counts[i]} completions "
                f"| Fastest: {fastest}",
                -200 + i * 50,
            )
        self._draw_text_centered("Click anywhere to return", 220)

    def _enter_level_pre(self, level):
        self._selected_level = level
        self._pre_end        = time.time() + 3
        self.state = STATE_LEVEL_PRE

    def _tick_level_pre(self):
        for event in pg.event.get():
            if event.type == pg.QUIT:
                self.state = STATE_DONE
                return

        if time.time() >= self._pre_end:
            self._enter_level()
            return

        remaining = int(self._pre_end - time.time())
        self.screen.fill(BLACK)
        self._draw_text_centered(f"Level {self._selected_level}", -50)
        self._draw_text_centered(f"Get ready... {remaining + 1}", 20)

    def _enter_level(self):
        level     = self._selected_level
        level_key = str(level)

        self.attempt_counters[level_key] += 1
        self._velocity      = 0.0
        self._prev_velocity = 0.0

        player_x = WIDTH - 100 if level == 2 else 100
        target_x = 100        if level == 2 else WIDTH - 100
        if level == 3:
            target_x = WIDTH // 2 + 60

        self._player = pg.Rect(
            player_x, HEIGHT // 2 - PLAYER_SIZE // 2,
            PLAYER_SIZE, PLAYER_SIZE)
        self._target = pg.Rect(
            target_x, HEIGHT // 2 - TARGET_HEIGHT // 2,
            TARGET_WIDTH, TARGET_HEIGHT)
        self._start_marker = pg.Rect(
            player_x, HEIGHT // 2 - PLAYER_SIZE // 2,
            PLAYER_SIZE, PLAYER_SIZE)

        n_obs = level - 3 if level in (4, 5, 6) else 0
        self._obstacles = [
            pg.Rect(random.randint(200, WIDTH - 50), -100 * i, 50, 50)
            for i in range(n_obs)
        ]
        self._obs_speed     = 5 + 2 * (level - 4) if level in (4, 5, 6) else 0
        self._hold_duration = 5 if level == 3 else 0
        self._hold_start    = None
        self._level_start   = time.time()
        self._timer_start   = None if level == 3 else time.time()

        self.start_recording(["active"])
        self.state = STATE_LEVEL

    def _tick_level(self):
        level     = self._selected_level
        level_key = str(level)

        for event in pg.event.get():
            if event.type == pg.QUIT:
                self.state = STATE_DONE
                return

        self._prev_velocity = self._velocity
        self.apply_control()
        self._apply_movement(self._player)

        self.set_phase("active")
        self.record_sample()

        # obstacles
        hit = False
        for obs in self._obstacles:
            obs.y += self._obs_speed
            if obs.y > HEIGHT:
                obs.y = -100
                obs.x = random.randint(200, WIDTH - 50)
            if self._player.colliderect(obs):
                hit = True

        if hit:
            samples = self.stop_recording()
            self._store_result(level_key, samples, success=False)
            self._button_rects = []
            self.state = STATE_HOME
            return

        # target / hold
        level_complete = False
        if self._player.colliderect(self._target):
            if level == 3:
                if self._hold_start is None:
                    self._hold_start  = time.time()
                    self._timer_start = time.time()
                elif time.time() - self._hold_start >= self._hold_duration:
                    level_complete = True
            else:
                level_complete = True
        else:
            self._hold_start = None

        if level_complete:
            total_time = round(time.time() - self._timer_start, 2) \
                         if self._timer_start else 0.0
            self.completion_counts[level] += 1
            self.fastest_times[level] = min(
                self.fastest_times[level], total_time)
            samples = self.stop_recording()
            self._store_result(
                level_key, samples,
                success=True, duration_time=total_time)
            self._button_rects = []
            self.state = STATE_HOME
            return

        # draw
        elapsed = 0.0 if self._timer_start is None \
                  else round(time.time() - self._timer_start, 1)
        self.screen.fill(BLACK)
        self._draw_text_top(
            f"Level {level} — Attempt {self.attempt_counters[level_key]}  "
            f"Time: {elapsed}s"
        )
        pg.draw.rect(self.screen, GREEN, self._start_marker)
        pg.draw.rect(self.screen, BLUE,  self._target)
        pg.draw.rect(self.screen, WHITE, self._player)
        for obs in self._obstacles:
            pg.draw.rect(self.screen, RED, obs)

    def _enter_free(self):
        self.attempt_counters["Free"] += 1
        self._velocity      = 0.0
        self._prev_velocity = 0.0
        self._lives         = 3
        self._score         = 0
        self._has_coin      = False
        self._player        = pg.Rect(
            100, HEIGHT // 2 - PLAYER_SIZE // 2,
            PLAYER_SIZE, PLAYER_SIZE)
        self._start_marker  = pg.Rect(
            100, HEIGHT // 2 - PLAYER_SIZE // 2,
            PLAYER_SIZE, PLAYER_SIZE)
        self._coin          = pg.Rect(WIDTH - 100, HEIGHT // 2 - 25, 30, 30)
        self._obstacles     = [
            pg.Rect(random.randint(200, WIDTH - 50), -100 * i, 50, 50)
            for i in range(3)
        ]
        self._free_start  = time.time()
        self._level_start = time.time()

        self.start_recording(["active"])
        self.state = STATE_FREE

    def _tick_free(self):
        for event in pg.event.get():
            if event.type == pg.QUIT:
                self.state = STATE_DONE
                return
            elif event.type == pg.KEYDOWN and event.key == pg.K_ESCAPE:
                samples = self.stop_recording()
                self._store_result(
                    "Free", samples,
                    success=False, score=self._score)
                self._button_rects = []
                self.state = STATE_HOME
                return

        if self._lives <= 0:
            samples = self.stop_recording()
            self._store_result(
                "Free", samples,
                success=True, score=self._score)
            self._button_rects = []
            self.state = STATE_HOME
            return

        self._prev_velocity = self._velocity
        self.apply_control()
        self._apply_movement(self._player)
        self.set_phase("active")
        self.record_sample()

        for obs in self._obstacles:
            obs.y += 7
            if obs.y > HEIGHT:
                obs.y = -100
                obs.x = random.randint(200, WIDTH - 50)
            if self._player.colliderect(obs):
                self._lives    -= 1
                self._player.x  = 100
                self._has_coin  = False

        if not self._has_coin and self._player.colliderect(self._coin):
            self._has_coin = True
        if self._has_coin and self._player.colliderect(self._start_marker):
            self._score   += 1
            self._has_coin = False

        elapsed = round(time.time() - self._free_start, 1)
        self.screen.fill(BLACK)
        self._draw_text_top(
            f"Free Mode — Attempt {self.attempt_counters['Free']}  "
            f"Score: {self._score}  Lives: {self._lives}  Time: {elapsed}s"
        )
        pg.draw.rect(self.screen, GREEN, self._start_marker)
        pg.draw.rect(self.screen, WHITE, self._player)
        if not self._has_coin:
            pg.draw.rect(self.screen, YELLOW, self._coin)
        for obs in self._obstacles:
            pg.draw.rect(self.screen, RED, obs)

    def apply_keyboard_control(self):
        keys = pg.key.get_pressed()
        if keys[pg.K_LEFT]:
            self._velocity      = max(self._velocity - self._accel, -self._max_speed)
            self._last_keypress = "left"
        elif keys[pg.K_RIGHT]:
            self._velocity      = min(self._velocity + self._accel, self._max_speed)
            self._last_keypress = "right"
        else:
            self._apply_friction()
            self._last_keypress = "None"

    def apply_emg_values(self, values):
        data_packet = values[0] if isinstance(
            values[0], (list, tuple, np.ndarray)) else values
        chan_send   = values[1] if len(values) > 1 else None
        strength    = (max(data_packet) / 10.0) if len(data_packet) else 0.0

        self._emg_strength = round(float(strength), 3)
        self._emg_chan_send = chan_send

        # chan_send from control_signal_calc_v1: 0 -> ch0 dominant (move LEFT),
        # 1 -> ch1 dominant (move RIGHT). Legacy string labels also accepted.
        if chan_send == 0 or chan_send == "medial":
            self._velocity      = max(
                self._velocity - self._accel * strength, -self._max_speed)
            self._last_keypress = "left"
        elif chan_send == 1 or chan_send == "lateral":
            self._velocity      = min(
                self._velocity + self._accel * strength, self._max_speed)
            self._last_keypress = "right"
        else:
            self._apply_friction()
            self._last_keypress = "None"

    def _apply_friction(self):
        self._velocity *= self._friction
        if abs(self._velocity) < 0.1:
            self._velocity = 0.0

    def _apply_movement(self, player_rect):
        # physics - clamp to boundaries
        new_x = player_rect.x + self._velocity
        if new_x < 0:
            new_x = 0
            self._velocity = 0.0
        elif new_x > WIDTH - PLAYER_SIZE:
            new_x = WIDTH - PLAYER_SIZE
            self._velocity = 0.0
        player_rect.x = int(new_x)

    def _store_result(self, level_key, samples,
                    success, duration_time=None, score=None):

        result = {
            "level":   level_key,
            "attempt": self.attempt_counters[level_key],
            "success": success,
            "samples": samples.get("active", [])
        }
        if duration_time is not None:
            result["duration_s"] = duration_time
        else:
            result["duration_s"] = round(time.time() - (self._free_start if level_key == "Free" else self._level_start), 2) if (self._free_start or self._level_start) else None

        if score is not None:
            result["score"] = score

        self._session_results.append(result)
        self.save_session_data() 
        print(f"[BoxDrop] level={level_key} success={success} "
            f"samples={len(result['samples'])}")
    
    def _draw_text_centered(self, text, y_offset=0, color=WHITE):
        surf = self.font.render(text, True, color)
        self.screen.blit(surf, surf.get_rect(
            center=(WIDTH // 2, HEIGHT // 2 + y_offset)))

    def _draw_text_top(self, text):
        surf = self.font.render(text, True, WHITE)
        self.screen.blit(surf, (WIDTH // 2 - surf.get_width() // 2, 10))


if __name__ == "__main__":
    app = QApplication(sys.argv)
    game = BoxDropGame_v1(num_channels=1)
    game.start_game()
    sys.exit(app.exec_())