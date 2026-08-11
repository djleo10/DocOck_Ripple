import os
import sys
import json
import time
import random
import pygame as pg
from PyQt5.QtWidgets import QApplication

try:
    from ..BaseGame import BaseGame
except ImportError:
    from games.BaseGame import BaseGame

STATE_PLAYING   = "playing"
STATE_GAME_OVER = "game_over"
STATE_DONE      = "done"


class SpaceGame(BaseGame):

    def game_name(self) -> str:
        return "space_game"

    def setup(self):
        pg.init()
        pg.mixer.init()

        screen_info        = pg.display.Info()
        self.screen_width  = 600
        self.screen_height = round(screen_info.current_h * 0.80)
        self.base_size     = round(self.screen_height * 0.1111)

        self.screen = pg.display.set_mode((self.screen_width, self.screen_height))
        pg.display.set_caption("Space Game")
        self.clock  = pg.time.Clock()
        self.font   = pg.font.Font(None, 36)

        self._load_images()

        # audio
        pg.mixer.music.load(os.path.join(self.basepath, "assets", "space.mp3"))
        pg.mixer.music.play(-1)
        pg.mixer.music.set_volume(0.25)
        self.sfx_explode = pg.mixer.Sound(
            os.path.join(self.basepath, "assets", "explosion.mp3"))
        self.sfx_explode.set_volume(0.5)

        self._ship_direction = "default"

        emg_cols = [f"emg_ch{i+1}" for i in range(self.num_channels)]

        self._open_csv([
            "play_number", "cause", "final_score", "final_level",
            "t", "score", "level", "ship_x", "ship_y", "direction", "num_obs",
            *emg_cols,
        ])

        self._load_progress()
        self._reset_game()

    def __init__(self, basepath=None, num_channels=2, **kwargs):
        if basepath is None:
            basepath = os.path.dirname(os.path.abspath(__file__))
        super().__init__(basepath=basepath, num_channels=num_channels, **kwargs)
        self._session_plays = []
        self._level_events  = []
        self.hi_score       = 0
        self.hi_level       = 0
        self.state          = STATE_PLAYING
        self._emg_strengths = [0.0] * num_channels 

    def tick(self):
        if   self.state == STATE_PLAYING:   self.play_screen()
        elif self.state == STATE_GAME_OVER: self.game_over_screen()
        elif self.state == STATE_DONE:
            self.stop_game()
            return
        pg.display.flip()
        self.clock.tick(60)

    def get_current_sample(self) -> dict:
        emg_fields = {
            f"emg_ch{i+1}": round(self._emg_strengths[i], 2)
            for i in range(self.num_channels)
        }
        return {
            "t":         round(time.time() - self._trial_start_time, 2)
                        if self._trial_start_time else 0.0,
            "score":     self.score,
            "level":     self.level,
            "ship_x":    self.ship.rect.x,
            "ship_y":    self.ship.rect.y,
            "direction": self._ship_direction, 
            "num_obs":   len(self.obs),
            **emg_fields, 
        }

    def on_game_over(self):
        if self._recording:
            self._store_play_result(cause="quit")
        self.save_session_data()

    def apply_keyboard_control(self):
        keys = pg.key.get_pressed()
        if   keys[pg.K_LEFT]:  self._ship_direction = "left"
        elif keys[pg.K_RIGHT]: self._ship_direction = "right"
        elif keys[pg.K_UP]:    self._ship_direction = "up"
        elif keys[pg.K_DOWN]:  self._ship_direction = "down"
        else:                  self._ship_direction = "default"

    def apply_emg_values(self, values):
        for i, v in enumerate(values[:self.num_channels]):
            self._emg_strengths[i] = float(v)
        if len(values) >= 2:
            h = values[0]
            v = values[1]
            if   h > 60:  self._ship_direction = "right"
            elif h < 40:  self._ship_direction = "left"
            elif v > 60:  self._ship_direction = "up"
            elif v < 40:  self._ship_direction = "down"
            else:         self._ship_direction = "default"
        elif len(values) == 1:
            h = values[0]
            if   h > 60:  self._ship_direction = "right"
            elif h < 40:  self._ship_direction = "left"
            else:         self._ship_direction = "default"

    def _reset_game(self):
        self.score                 = 0
        self.level                 = 0
        self.asteroid_added_scores = set()
        self._ship_direction       = "default"
        self._level_events         = []

        self.starfield = Stars(
            self.screen_width, self.screen_height, 100, 1, 4)
        self.ship = Ship(
            self.screen_width, self.screen_height, self.ship_images)
        self.obs  = [
            Obstacle(self.screen_width, self.screen_height, self.obstacle_images)
            for _ in range(3)
        ]
        pg.mixer.music.unpause()
        self.start_recording(["playing"])
        self.state = STATE_PLAYING

    def play_screen(self):
        for event in pg.event.get():
            if event.type == pg.QUIT:
                self.state = STATE_DONE
                return

        self.apply_control()
        self.ship.move(self._ship_direction)

        self.starfield.moveStars()
        for ob in self.obs:
            if ob.move():
                self.score += 1

        # level progression
        threshold = 10 if 0 < self.level < 6 else 20
        if (self.score > 0
                and self.score % threshold == 0
                and self.score not in self.asteroid_added_scores):
            self.obs.append(
                Obstacle(self.screen_width, self.screen_height,
                         self.obstacle_images))
            self.level += 1
            self.asteroid_added_scores.add(self.score)
            # stamp level up event
            self._level_events.append({
                "level": self.level,
                "score": self.score,
                "t":     round(time.time() - self._trial_start_time, 2)
                         if self._trial_start_time else 0.0
            })

        # collision
        hit = any(
            self.ship.mask.overlap(
                ob.mask,
                (ob.rect.x - self.ship.rect.x,
                 ob.rect.y - self.ship.rect.y)
            )
            for ob in self.obs
        )
        if hit:
            self.sfx_explode.play()
            pg.mixer.music.pause()
            self.hi_score = max(self.hi_score, self.score)
            self.hi_level = max(self.hi_level, self.level)
            self._store_play_result(cause="collision")
            self.state = STATE_GAME_OVER
            return

        # sample every interval
        self.set_phase("playing")
        self.record_sample()

        # draw
        self.screen.fill((0, 0, 0))
        self.starfield.drawStars(self.screen)
        for ob in self.obs:
            ob.draw(self.screen)
        self.ship.draw(self.screen)

        for text, pos in [
            (f"Score: {self.score}",         (10, 10)),
            (f"High Score: {self.hi_score}", (10, 30)),
            (f"Level: {self.level}",         (10, 50)),
            (f"High Level: {self.hi_level}", (10, 70)),
        ]:
            self.screen.blit(
                self.font.render(text, True, (255, 255, 255)), pos)

    def game_over_screen(self):
        for event in pg.event.get():
            if event.type == pg.QUIT:
                self.state = STATE_DONE
                return

        keys = pg.key.get_pressed()
        if keys[pg.K_y]:
            self._reset_game()
            return
        elif keys[pg.K_n]:
            self.state = STATE_DONE
            return

        self.screen.fill((0, 0, 0))
        for text, offset in [
            ("GAME OVER",                         -100),
            (f"Final Score: {self.score}",         -50),
            (f"Final Level: {self.level}",           0),
            (f"Hi Score: {self.hi_score}",          50),
            (f"Hi Level: {self.hi_level}",         100),
            ("Play again? (Y / N)",                150),
        ]:
            surf = self.font.render(text, True, (255, 255, 255))
            self.screen.blit(surf, surf.get_rect(
                center=(self.screen_width  // 2,
                        self.screen_height // 2 + offset)))

    def _store_play_result(self, cause="collision"):
        samples = self.stop_recording() if self._recording else {}
        play = {
            "play_number":  len(self._session_plays) + 1,
            "cause":        cause,
            "final_score":  self.score,
            "final_level":  self.level,
            "hi_score":     self.hi_score,
            "hi_level":     self.hi_level,
            "level_events": self._level_events,
            "samples":      samples.get("playing", [])
        }
        self._session_plays.append(play)
        self.save_session_data()
        print(f"[SpaceGame] Play {play['play_number']} stored — "
            f"score={self.score} level={self.level} "
            f"cause={cause} samples={len(play['samples'])}")

    def _load_images(self):
        s = self.base_size

        def load(name, w, h):
            return pg.transform.scale(
                pg.image.load(
                    os.path.join(self.basepath, "assets", name)
                ).convert_alpha(), (w, h))

        self.ship_images = {
            "default": load("shipcenter.png",   s,      s),
            "left1":   load("shipleft1.png",    s,      s),
            "left2":   load("shipleft2.png",    s,      s),
            "right1":  load("shipright1.png",   s,      s),
            "right2":  load("shipright2.png",   s,      s),
            "up1":     load("shipforward1.png", s,      s),
            "up2":     load("shipforward2.png", s,      s),
        }
        self.obstacle_images = [
            load("astronaut.png", s-50, s-50),
            load("astronaut.png", s-50, s-50),
            load("sat.png",       s,    s-20),
            load("alien.png",     s-10, s-10),
            load("asteroid.png",  s+50, s+50),
            load("asteroid.png",  s+50, s+50),
        ]

    def get_save_data(self) -> dict:
        return {
            "hi_score":    self.hi_score,
            "hi_level":    self.hi_level,
            "total_plays": len(self._session_plays),
            "data_samples": [
                {
                    "play_number": p["play_number"],
                    "cause":       p["cause"],
                    "final_score": p["final_score"],
                    "final_level": p["final_level"],
                    "samples":     p["samples"],    # ← nested list of sample dicts
                }
                for p in self._session_plays
            ],
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
            self.hi_score = data.get("hi_score", 0)
            self.hi_level = data.get("hi_level", 0)
            print(f"[SpaceGame] Progress loaded")
        except Exception as e:
            print(f"[SpaceGame] Failed to load progress: {e}")


class Stars:
    def __init__(self, screen_width, screen_height, num_stars, min_speed, max_speed):
        self.screen_width  = screen_width
        self.screen_height = screen_height
        self.min_speed     = min_speed
        self.max_speed     = max_speed
        self.stars         = [
            [random.randint(0, screen_width),
             random.randint(0, screen_height),
             random.uniform(min_speed, max_speed)]
            for _ in range(num_stars)
        ]

    def moveStars(self):
        for star in self.stars:
            star[1] += star[2]
            if star[1] > self.screen_height:
                star[1] = 0
                star[0] = random.randint(0, self.screen_width)
                star[2] = random.uniform(self.min_speed, self.max_speed)

    def drawStars(self, screen):
        for star in self.stars:
            pg.draw.circle(screen, (255, 255, 255),
                           (int(star[0]), int(star[1])), int(star[2]))


class Ship:
    def __init__(self, screen_width, screen_height, images):
        self.images        = images
        self.image         = images["default"]
        self.rect          = self.image.get_rect()
        self.mask          = pg.mask.from_surface(self.image)
        self.screen_width  = screen_width
        self.screen_height = screen_height
        self.rect.centerx  = screen_width // 2
        self.rect.bottom   = screen_height - 10
        self.speed         = 5

    def move(self, direction):
        if direction == "left" and self.rect.left > 0:
            self.rect.x -= self.speed
            self.image   = random.choice(
                [self.images["left1"], self.images["left2"]])
        elif direction == "right" and self.rect.right < self.screen_width:
            self.rect.x += self.speed
            self.image   = random.choice(
                [self.images["right1"], self.images["right2"]])
        elif direction == "up" and self.rect.top > self.screen_height - 350:
            self.rect.y -= self.speed
            self.image   = random.choice(
                [self.images["up1"], self.images["up2"]])
        elif direction == "down" and self.rect.bottom < self.screen_height - 10:
            self.rect.y += self.speed
            self.image   = self.images["default"]
        else:
            self.image = random.choice(
                [self.images["up1"], self.images["up2"]])
        self.mask = pg.mask.from_surface(self.image)

    def draw(self, screen):
        screen.blit(self.image, self.rect)


class Obstacle:
    def __init__(self, screen_width, screen_height, images):
        self.image         = random.choice(images)
        self.rect          = self.image.get_rect()
        self.mask          = pg.mask.from_surface(self.image)
        self.screen_width  = screen_width
        self.screen_height = screen_height
        self.rect.x        = random.randint(0, screen_width - self.rect.width)
        self.rect.y        = -self.rect.height
        self.speed         = random.uniform(4, 6)

    def move(self):
        self.rect.y += self.speed
        if self.rect.top > self.screen_height:
            self.rect.y = -self.rect.height
            self.rect.x = random.randint(0, self.screen_width - self.rect.width)
            self.speed  = random.uniform(4, 6)
            return True
        return False

    def draw(self, screen):
        screen.blit(self.image, self.rect)


if __name__ == "__main__":
    app  = QApplication(sys.argv)
    game = SpaceGame(num_channels=2)
    game.start_game()
    sys.exit(app.exec_())