import os
import sys
import time
import random
import glob
import pygame
from pygame.locals import *
from math import fabs

try:
    from ..BaseGame import BaseGame
except ImportError:
    from games.BaseGame import BaseGame

STATE_FIRST_SCREEN = "first_screen"
STATE_MAIN_MENU    = "main_menu"
STATE_PLAYING      = "playing"
STATE_PAUSED       = "paused"
STATE_DEAD_ANIM    = "dead_anim"
STATE_SPIN         = "spin"
STATE_DONE         = "done"

EMG_THRESHOLD = 30   # % MVC above which jetpack fires

class _Zapper:
    _NAMES = ["zap2.png", "zap3.png", "zap.png", "zap1.png"]

    def __init__(self, game):
        self.game       = game
        self.x          = 0.0
        self.y          = 0.0
        self.spinamount = 0
        self.addx = self.addy = 0.0
        self._rand_pic()
        self.rect = self.Object.get_rect()

    def _p(self, name):
        return os.path.join(self.game.basepath, "Img1", name)

    def _rand_pic(self):
        name = random.choice(self._NAMES)
        self.rotate  = (name == "zap4.png")
        self.image   = self._p(name)
        self.Object  = pygame.image.load(self.image)
        self.spinObj = pygame.image.load(self._p("zap4.png"))

    def setx(self, x): self.x = x; self.rect.x = int(x)
    def sety(self, y): self.y = y; self.rect.y = int(y)

    def blit(self):
        if self.rotate:
            self.game.screen.blit(self.Object, (self.x + self.addx, self.y + self.addy))
        else:
            self.game.screen.blit(self.Object, (int(self.x), int(self.y)))

    def intersecting(self, steverect):
        g = self.game
        if g.invincible:
            return
        obj  = pygame.transform.rotate(self.spinObj, self.spinamount) if self.rotate else self.Object
        ox   = self.x + self.addx if self.rotate else self.x
        oy   = self.y + self.addy if self.rotate else self.y
        r    = obj.get_rect()
        r.x  = int(ox); r.y = int(oy)
        if not r.colliderect(steverect):
            return
        sw, sh = g.steve.get_width(), g.steve.get_height()
        for cx, cy in [(g.stevex, g.stevey), (g.stevex + sw, g.stevey),
                       (g.stevex, g.stevey + sh), (g.stevex + sw, g.stevey + sh)]:
            if r.collidepoint(cx, cy):
                px = max(0, min(int(fabs(cx - ox)), obj.get_width()  - 1))
                py = max(0, min(int(fabs(cy - oy)), obj.get_height() - 1))
                rgb = obj.get_at((px, py))
                if rgb not in [(255, 255, 255, 0), (0, 0, 0, 255)]:
                    g.die = True
                    return

    def update(self):
        g = self.game
        self.x -= g.speed
        if self.x <= -550 and g.Type == "zapper":
            if random.randint(0, 20) == 0:
                tok = _SpinToken(g)
                tok.setx(1024 * 1.5)
                g.spintokensl.append(tok)
            self.x  = 1024.0
            self._rand_pic()
            self.y  = float(random.choice([
                100,
                (100 + (768 - 120 - self.Object.get_height())) / 2,
                768 - 120 - self.Object.get_height()
            ]))
        if self.rotate:
            self.spinamount += 1
            rotated    = pygame.transform.rotate(self.spinObj, self.spinamount)
            self.addx  = (self.spinObj.get_width()  - rotated.get_width())  / 2
            self.addy  = (self.spinObj.get_height() - rotated.get_height()) / 2
            self.Object = rotated
        self.rect.x = int(self.x)
        self.rect.y = int(self.y)

class _Coin:
    _cache = None

    def __init__(self, game):
        self.game   = game
        self.floor  = game.screen.get_height() - 190
        self.x      = float(random.randint(0, 1024))
        self.y      = float(random.randint(125, self.floor))
        self.touch  = self.point = self.spintoken = False
        self.imgnum = 0
        self._ensure_cache()
        self.imgs       = _Coin._cache
        self.CoinObject = self.imgs[self.imgnum]
        self.rect   = self.CoinObject.get_rect()
        self.rect.x = int(self.x)    # ← FIX: sync on creation
        self.rect.y = int(self.y)    # ← FIX
        self.tokenrandom = [1] + [0] * 40

    def _ensure_cache(self):
        if _Coin._cache is None:
            _Coin._cache = [
                pygame.image.load(
                    os.path.join(self.game.basepath, "Img1", f"Coin{i}1.png"))
                for i in range(6)
            ]

    def changeimage(self):
        self.imgnum     = (self.imgnum + 1) % 6
        self.CoinObject = self.imgs[self.imgnum]

    def update(self):
      pass

    def intersecting(self, steverect):
        self.rect.x = int(self.x)    
        self.rect.y = int(self.y)
        if self.rect.colliderect(steverect):
            if self.spintoken:
                self.game.spintokens += 1
            elif not self.point:
                self.game.score += 1
                self.point = True
            if self.game.respawncoins:
                self.x      = 1024.0
                self.y      = float(random.randint(100, self.floor))
                self.rect.x = int(self.x)    # ← FIX: sync after teleport
                self.rect.y = int(self.y)
                self.touch  = self.point = False
                self.spintoken = bool(random.choice(self.tokenrandom))
            else:
                self.x      = -self.CoinObject.get_width() * 2
                self.rect.x = int(self.x)    # ← FIX: sync after removal
        return self.touch

    def blit(self):
        self.game.screen.blit(self.CoinObject, (int(self.x), int(self.y)))
    
class _SpinToken:
    def __init__(self, game):
        self.game  = game
        self.image = pygame.image.load(
            os.path.join(game.basepath, "Img1", "spin", "spin token.png"))
        self.x = 0.0
        self.y = float(random.randint(125, 638))
        self.rect = self.image.get_rect()

    def setx(self, x): self.x = x; self.rect.x = int(x)

    def update(self):
        g = self.game
        self.rect.x = int(self.x); self.rect.y = int(self.y)
        self.y += ((g.stevey - self.y) / 80) * (1 if self.y < g.stevey else -1)
        if self.rect.colliderect(g.steverect):
            g.spintokens += 1
            self.x = -self.image.get_width()
        else:
            self.x -= g.speed

    def blit(self):
        self.game.screen.blit(self.image, (int(self.x), int(self.y)))

class JetpackGame(BaseGame):

    def __init__(self, basepath=None, num_channels=1, **kwargs):
        if basepath is None:
            basepath = os.path.dirname(os.path.abspath(__file__))
        super().__init__(basepath=basepath, num_channels=num_channels, **kwargs)
        self._session_data = []
        self._last_distance = 0
        self._last_score    = 0 
        self._bestscreen    = None
        self._run_number = 0
        self.state         = STATE_FIRST_SCREEN
        self._prev_stevey  = 0.0
        self._vel_y        = 0.0
        self._prev_vel_y   = 0.0
        self._emg_strength = 0.0 
        self._timer_start  = None 

    def game_name(self) -> str:
        return "jetpack_joyride"

    def _p(self, *parts):
        return os.path.join(self.basepath, "Img1", *parts)

    def _load(self, *parts):
        return pygame.image.load(self._p(*parts))

    def _blited_costume(self, fname):
        body = self._load("clothing1", "body", self.costume,     fname)
        face = self._load("clothing1", "face", self.costumeface, fname)
        w    = max(body.get_width(),  face.get_width())
        h    = max(body.get_height(), face.get_height())
        surf = pygame.Surface((w, h), pygame.SRCALPHA, 32).convert_alpha()
        surf.blit(face, (0, h - face.get_height()))
        surf.blit(body, (0, h - body.get_height()))
        return surf

    def setup(self):
        pygame.init()
        self.screen = pygame.display.set_mode((1024, 768))
        pygame.display.set_caption("Jetpack Joyride")
        self.clock  = pygame.time.Clock()

        fp = self._p("New Athletic M54.ttf")
        self.font          = pygame.font.Font(fp, 50)
        self.smallfont     = pygame.font.Font(fp, 40)
        self.verysmallfont = pygame.font.Font(fp, 30)
        self.extremefont   = pygame.font.Font(fp, 130)

        # Costume
        try:
            with open(self._p("clothing1", "costume.txt")) as f:
                lines = f.readlines()
            self.costume, self.costumeface = lines[0].rstrip(), lines[1].rstrip()
        except:
            self.costume, self.costumeface = "Original body", "Original face"

        # High scores
        self._hs_path = self._p("Highscore.txt")
        try:
            rows = [l.strip() for l in open(self._hs_path) if l.strip()]
            self.distf, self.dists, self.distt = \
                int(float(rows[0])), int(float(rows[1])), int(float(rows[2]))
        except:
            self.distf = self.dists = self.distt = 0

        # Money
        self._money_path = self._p("money.txt")
        try:
            self.money = int(open(self._money_path).readlines()[0])
        except:
            self.money = 0

        # Static images
        self.bg               = self._load("bg6.jpg")
        self.pause_img        = self._load("pause.png")
        self.pause_img.set_colorkey(pygame.Color(0, 0, 0))
        self.paused_img       = self._load("paused.png")
        self.darker           = self._load("darker screen.png")
        self.first_screen_img = self._load("first screen.png")
        self.mainmenu_img     = self._load("newmain.png")

        # Steve sprites
        self.steveimages = [self._blited_costume(n) for n in
                            ["walk1.png", "walk2.png", "flying1.png", "beggining.png"]]

        # Music
        self.mute = False
        for name in ["Jetpack Joyride Music.wav", "Jetpack Joyride Music smaller.wav"]:
            try:
                pygame.mixer.music.load(self._p(name))
                break
            except:
                pass

        try:
            pygame.display.set_icon(self._load("icon.png"))
        except:
            pass

        self.bar_values = [0] * self.num_channels
        self._bestscreen    = None
        self._last_distance = 0     
        self._last_score    = 0
        self._load_progress()
        self.state = STATE_FIRST_SCREEN

        self._open_csv([
            "run", "t", "x", "y",
            "vel_y", "accel_y",
            "keydown", "emg_strength",
            "score", "distance"
        ])

    def _init_run(self):
        self._run_number += 1
        self.floor           = self.bg.get_height() - 190
        self.stevex          = 100.0
        self.stevey          = float(self.floor)
        self.mstevey         = 0.0
        self.keydown         = False
        self.change          = 0.0
        self.die             = False
        self.score           = 0
        self.distance        = 0.0
        self.speed           = 7
        self.walkcount       = 0
        self.count           = 0
        self.invincible      = False
        self.invincibleframesl = 100
        self.spintokens      = 0
        self.spintokensl     = []
        self.respawncoins    = False

        self.bg1x = float(self.bg.get_width())
        self.bg2x = 0.0
        self.bg1y = self.bg2y = 0.0

        self.steve      = self.steveimages[0]
        self.steverect  = self.steve.get_rect()
        self.stevewidth  = self.steve.get_width()
        self.steveheight = self.steve.get_height()

        self.Type         = "zapper"
        self.typechange   = -1
        self._tc_t        = time.time()

        self.coins    = []
        self.zapper_a = _Zapper(self)
        self.zapper_b = _Zapper(self)
        self.zapper_a.setx(-self.zapper_a.Object.get_width())
        self.zapper_b.setx(-self.zapper_b.Object.get_width())

        self._dead_img       = None
        self._dead_ss        = None
        self._dead_direction = random.choice([-1, 1])
        self._dead_rotation  = 0.0

        self.bar_values   = [0] * self.num_channels
        self._timer_start = time.time()

        self._prev_stevey  = float(self.floor)
        self._vel_y        = 0.0
        self._prev_vel_y   = 0.0
        self._emg_strength = 0.0

    def tick(self):
        if   self.state == STATE_FIRST_SCREEN: self._tick_first_screen()
        elif self.state == STATE_MAIN_MENU:    self._tick_main_menu()
        elif self.state == STATE_PLAYING:      self._tick_playing()
        elif self.state == STATE_PAUSED:       self._tick_paused()
        elif self.state == STATE_DEAD_ANIM:    self._tick_dead_anim()
        elif self.state == STATE_SPIN:         self._tick_spin()
        elif self.state == STATE_DONE:
            self.stop_game()
            return
        pygame.display.flip()
        self.clock.tick(60)

    def get_current_sample(self) -> dict:
        elapsed = round(time.time() - self._timer_start, 3) if self._timer_start else 0.0
        return {
            "run":          self._run_number,
            "t":            elapsed,
            "x":            round(float(self.stevex), 1),
            "y":            round(float(self.stevey), 1),
            "vel_y":        round(float(self._vel_y), 1),
            "accel_y":      round(float(self._vel_y - self._prev_vel_y), 1),
            "keydown":      self.keydown,
            "emg_strength": self._emg_strength,
            "score":        self.score,
            "distance":     round(self.distance, 1),
        }

    def get_save_data(self) -> dict:
        return {
            "high_scores": {"first": self.distf, "second": self.dists, "third": self.distt},
            "money":       self.money,
            "last_run":    {"distance": self._last_distance, "score": self._last_score},
            "data_samples": [
                {
                    "run":      entry["run"],
                    "distance": entry["distance"],
                    "score":    entry["score"],
                    "samples":  entry["samples"],   # ← nested, matches other games
                }
                for entry in self._session_data
            ],
        }
    
    def _load_progress(self):
        import json
        path = os.path.join(
            os.path.dirname(os.path.abspath(__file__)),
            "..", "..", "data", f"{self.game_name()}.json" 
        )

        try:
            rows = [l.strip() for l in open(self._hs_path) if l.strip()]
            self.distf, self.dists, self.distt = \
                int(float(rows[0])), int(float(rows[1])), int(float(rows[2]))
        except:
            self.distf = self.dists = self.distt = 0

        if not os.path.exists(path):
            print(f"[JetpackGame] No save file — starting fresh")
            return
        try:
            with open(path, "r") as f:
                data = json.load(f)
            hs             = data.get("high_scores", {})
            self.distf     = int(hs.get("first",  0))
            self.dists     = int(hs.get("second", 0))
            self.distt     = int(hs.get("third",  0))
            self.money     = int(data.get("money", 0))
            lr             = data.get("last_run", {})
            self._last_distance = float(lr.get("distance", 0))
            self._last_score    = int(lr.get("score",    0))
            print(f"[JetpackGame] Loaded — best={self.distf}m  money={self.money}")
        except Exception as e:
            print(f"[JetpackGame] Load failed: {e}")

    def on_game_over(self):
        self._last_distance = float(getattr(self, "distance", 0.0))
        self._last_score    = int(getattr(self, "score", 0))
        self.money         += self._last_score
        self._save_high_score()
        self._save_money()

        if self._recording:
            samples = self.stop_recording()
            flat    = samples.get("gameplay", [])
            if flat:
                self._session_data.append({
                    "run":      self._run_number,
                    "distance": round(self.distance, 1),
                    "score":    self.score,
                    "samples":  flat,
                })
        self.save_session_data()

    def apply_keyboard_control(self):
        pass   # jetpack handled via pygame events in _tick_playing

    def apply_emg_values(self, values):
        if not values:
            return
        self.bar_values    = [max(0, min(100, int(v))) for v in values[:self.num_channels]]
        self._emg_strength = float(self.bar_values[0])   # ← ADD: capture strength
        active = self.bar_values[0] >= EMG_THRESHOLD
        if active and self.keydown is not True:
            self.keydown = True;  self.change = 0.0; self.mstevey = 0.0
        elif not active and self.keydown is True:
            self.keydown = "falling"; self.mstevey = 0.0; self.change = 0.0

    def _tick_first_screen(self):
        for event in pygame.event.get():
            if event.type == QUIT:
                self.state = STATE_DONE; return
            if event.type == pygame.MOUSEBUTTONDOWN:
                self.state = STATE_MAIN_MENU; return

        surf = self.first_screen_img.copy()
        hs   = self.font.render("{:,}".format(self.distf), True, (86, 113, 149))

        # Scale to fit the score box on the first screen image
        if hs.get_width() / 90 > hs.get_height() / 28:
            hs = pygame.transform.scale(
                hs, (90, int((90 / hs.get_width()) * hs.get_height())))
        else:
            hs = pygame.transform.scale(
                hs, (int((28 / hs.get_height()) * hs.get_width()), 28))

        surf.blit(hs, (860 - hs.get_width() // 2, 530 - hs.get_height() // 2))
        self.screen.blit(surf, (0, 0))

    def _tick_main_menu(self):
        for event in pygame.event.get():
            if event.type == QUIT:
                self.state = STATE_DONE; return
            if event.type == pygame.MOUSEBUTTONDOWN:
                pos = pygame.mouse.get_pos()
                if 525 < pos[0] < 974 and 528 < pos[1] < 685:
                    self._start_new_run(); return
        
        ss_path = self._p("screenshot.bmp")
        if os.path.exists(ss_path):
            self.screen.blit(pygame.image.load(ss_path), (0, 0))
        else:
            self.screen.fill((0, 0, 0))

        self.screen.blit(self.darker, (0, 0))

        menu = self.mainmenu_img.copy()
        if self._bestscreen is not None:
            menu.blit(pygame.transform.rotate(self._bestscreen, 5), (85, 325))
        self.screen.blit(menu, (0, 0))

        ms = self.smallfont.render(str(int(self.money)), True, (255, 255, 255))
        self.screen.blit(ms, (745 - ms.get_width(), 445 - ms.get_height() // 2))

        dist_surf = pygame.transform.rotate(
            self.extremefont.render(
                str(int(self._last_distance)) + "m", True, (246, 142, 1)), 5.5)
        self.screen.blit(dist_surf, (86, 120))

        score_surf = pygame.transform.rotate(
            self.verysmallfont.render(
                str(int(self._last_score)), True, (213, 199, 96)), 5.5)
        self.screen.blit(score_surf, (307, 264))

        for i, val in enumerate([self.distf, self.dists, self.distt]):
            s = self.verysmallfont.render(str(int(val)), True, (124, 137, 160))
            self.screen.blit(s, (968 - s.get_width(), 132 + i * 46))

    def _start_new_run(self):
        self._init_run()
        if not self.mute:
            pygame.mixer.music.play(-1)
        self.start_recording(["gameplay"])
        self.state = STATE_PLAYING

    def _tick_playing(self):
        # Events
        for event in pygame.event.get():
            if event.type == QUIT:
                self.state = STATE_DONE; return

            if event.type == KEYDOWN and event.key == K_SPACE:
                self.keydown = True;  self.change = 0.0; self.mstevey = 0.0

            if event.type == KEYUP and event.key == K_SPACE:
                self.keydown = "falling"; self.mstevey = 0.0; self.change = 0.0

            if event.type == pygame.MOUSEBUTTONDOWN:
                pos = pygame.mouse.get_pos()
                pw, ph = self.pause_img.get_size()
                if not (pos[0] >= 1024 - pw and pos[1] <= ph):
                    self.keydown = True; self.change = 0.0; self.mstevey = 0.0

            if event.type == pygame.MOUSEBUTTONUP:
                pos = pygame.mouse.get_pos()
                pw, ph = self.pause_img.get_size()
                if pos[0] >= 1024 - pw and pos[1] <= ph:
                    self._enter_pause(); return
                else:
                    self.keydown = "falling"; self.mstevey = 0.0; self.change = 0.0

        # Control (EMG or keyboard)
        self.apply_control()

        # Game logic
        self._physics_step()
        self._type_step()
        self._objects_step()

        # Record x/y every frame
        self.record_sample()

        if self.die:
            self._enter_dead_anim()
            return

        self._draw_playing()

    def _physics_step(self):
        self._prev_vel_y  = self._vel_y
        self._vel_y       = self.stevey - self._prev_stevey
        self._prev_stevey = self.stevey

        # Floor snap
        if self.stevey >= self.floor and self.keydown == "falling":
            self.keydown = False; self.mstevey = 0.0
            self.change  = 0.0;   self.stevey  = float(self.floor)

        # Vertical velocity
        if self.keydown is True and self.stevey >= 0:
            self.change  -= 0.01
            self.mstevey += self.change
        if self.keydown == "falling":
            self.change  += 0.02
            self.mstevey += self.change
        if self.stevey >= 100 or self.keydown == "falling":
            self.stevey  += self.mstevey

        # Walk animation
        self.walkcount += 1
        if self.walkcount % 10 == 0 and self.stevey >= self.floor and self.keydown != "falling":
            self.steve = self.steveimages[0]
        elif self.walkcount % 5 == 0:
            self.steve = self.steveimages[1]
        if self.keydown is True and self.stevey <= self.floor - self.steveheight:
            self.steve = self.steveimages[2]
        elif self.keydown is True:
            self.steve = self.steveimages[3]
        if self.keydown == "falling":
            self.steve = self.steveimages[3]

        # Background scroll
        self.bg1x -= self.speed;  self.bg2x -= self.speed
        if self.bg1x <= -1024: self.bg1x = 1024.0
        if self.bg2x <= -1024: self.bg2x = 1024.0

        # Distance + coin animation tick
        self.count = (self.count + 1) % 5
        if self.count == 0:
            self.distance += 0.5
            for c in self.coins:
                c.changeimage()

        # Invincibility countdown
        if self.invincible:
            self.invincibleframesl -= 1
            if self.invincibleframesl <= 0:
                self.invincible = False; self.invincibleframesl = 200

        self.steverect.x = int(self.stevex)
        self.steverect.y = int(self.stevey)

        if random.randint(0, 200) == 50:
            sw = self.steve.get_width()
            sh = self.steve.get_height()
            cx, cy = int(self.stevex + sw / 2), int(self.stevey + sh / 2)
            rx, ry = 180, 145
            surf = pygame.Surface((rx * 2, ry * 2), pygame.SRCALPHA, 32).convert_alpha()
            surf.blit(self.screen, (0, 0),
                    (cx - rx, cy - ry, rx * 2, ry * 2))
            self._bestscreen = surf



    def _type_step(self):
        now = time.time()
        self.typechange -= (now - self._tc_t)
        self._tc_t = now

        # If all coins have scrolled off, force switch back
        if self.Type == "coin" and self.coins:
            if all(c.x < 0 for c in self.coins):
                self.typechange = -1

        if self.typechange <= 0:
            self.typechange = 0
            self.Type = "coin" if self.Type == "zapper" else "zapper"
            if self.Type == "zapper":
                self.typechange  = 4.0  
                self.zapper_a    = _Zapper(self)
                self.zapper_b    = _Zapper(self)
                self.zapper_a.setx(1024)
                self.zapper_b.setx(1024 * 1.5 +
                                self.zapper_b.Object.get_width() // 2 +
                                self.zapper_a.Object.get_width() // 2)
                self.zapper_a.sety(random.randint(125, self.floor - self.zapper_a.Object.get_height()))
                self.zapper_b.sety(random.randint(125, self.floor - self.zapper_a.Object.get_height()))
                self.respawncoins = False
                self.coins        = []   # ← clear old off-screen coins

            else:
                self.typechange = 6.0  
                coors = self._rcform()
                self.coins = []
                if not coors:            # ← guard: if no formation files found, make a simple line
                    coors = [[i, 3] for i in range(8)]   # fallback row of coins
                x = 0
                for pos in coors:
                    x += 1 / 8
                    if round(x) > 6: x = 0
                    c           = _Coin(self)
                    c.x         = float(pos[0])
                    c.y         = float(pos[1])
                    c.rect.x    = int(c.x)   # ← sync rect immediately
                    c.rect.y    = int(c.y)
                    c.spintoken = False
                    c.imgnum    = round(x)
                    self.coins.append(c)

    def _objects_step(self):
        for tok in self.spintokensl[:]:
            tok.update()
            if tok.x < -tok.image.get_width():
                self.spintokensl.remove(tok)

        for c in self.coins:
            # ← scroll directly here using self.speed — no indirection through c.game.speed
            c.x     -= self.speed
            c.rect.x = int(c.x)
            c.rect.y = int(c.y)

            # collision check
            c.intersecting(self.steverect)

            # respawn if scrolled off left edge
            if c.x <= -c.CoinObject.get_width() * 2:
                if self.respawncoins:
                    c.x      = float(1024)
                    c.y      = float(random.randint(100, self.floor))
                    c.rect.x = int(c.x)
                    c.rect.y = int(c.y)
                    c.touch  = c.point = False

        try:
            self.zapper_a.intersecting(self.steverect)
            self.zapper_b.intersecting(self.steverect)
            self.zapper_a.update()
            self.zapper_b.update()
        except Exception as e:
            print(f"[Zapper] {e}")

    def _draw_playing(self):
        self.screen.blit(self.bg, (self.bg1x, self.bg1y))
        self.screen.blit(self.bg, (self.bg2x, self.bg2y))
        try:
            self.zapper_a.blit(); self.zapper_b.blit()
        except: pass
        for tok in self.spintokensl: tok.blit()
        for c   in self.coins:       c.blit()
        if self.invincibleframesl % 16 == self.invincibleframesl % 8:
            self.screen.blit(self.steve, (int(self.stevex), int(self.stevey)))
        self.screen.blit(self.pause_img, (1024 - self.pause_img.get_width(), 0))
        self._outline(0, 50, 2, str(self.score).zfill(3),
                      self.smallfont, (255, 140, 0), 23)
        self._outline(0,  0, 2, str(int(self.distance)).zfill(4) + " m",
                      self.font, (160, 160, 160), 27)

    def _enter_pause(self):
        if not self.mute:
            pygame.mixer.music.pause()
        pygame.image.save(self.screen, self._p("screenshot.bmp"))
        self.screen.blit(self.darker, (0, 0))
        pygame.display.flip()
        self.state = STATE_PAUSED

    def _tick_paused(self):
        mute_obj = self._load("mute.png" if self.mute else "unmute.png")
        mx, my   = 876, 12
        for event in pygame.event.get():
            if event.type == QUIT:
                self.state = STATE_DONE; return
            if event.type == pygame.MOUSEBUTTONUP:
                pos = pygame.mouse.get_pos()
                if mx < pos[0] < mx + mute_obj.get_width() and my < pos[1] < my + mute_obj.get_height():
                    self.mute = not self.mute
                    if not self.mute:
                        pygame.mixer.music.play(-1); pygame.mixer.music.pause()
                elif 643 < pos[0] < 872 and 614 < pos[1] < 692:   # Resume
                    if not self.mute: pygame.mixer.music.unpause()
                    self._tc_t = time.time()
                    self.state = STATE_PLAYING
                elif (391 < pos[0] < 618 and 614 < pos[1] < 690) or \
                     (150 < pos[0] < 369 and 614 < pos[1] < 692):  # Quit
                    self.on_game_over()
                    self.state = STATE_MAIN_MENU
        self.screen.blit(self.paused_img, (0, 0))
        self.screen.blit(mute_obj, (mx, my))

    def _enter_dead_anim(self):
        elapsed = round(time.time() - self._timer_start, 3)
        self.on_game_over()
        pygame.image.save(self.screen, self._p("screenshot.bmp"))
        self._dead_ss  = self._load("screenshot.bmp")
        self._dead_img = self._load("dead.png")
        self.state = STATE_DEAD_ANIM

    def _tick_dead_anim(self):
        for event in pygame.event.get():
            if event.type == QUIT:
                self.state = STATE_DONE; return

        self.stevey         += random.randint(100, 200) / 100
        self.stevex         += 0.1 * self._dead_direction
        self._dead_rotation += 0.25

        self.screen.blit(self._dead_ss, (0, 0))
        rotated = pygame.transform.rotate(self._dead_img, self._dead_rotation)
        self.screen.blit(rotated, (int(self.stevex), int(self.stevey)))

        if self.stevey >= self.floor:
            end = self._blited_costume("end.png")
            self.screen.blit(end, (int(self.stevex), self.floor + end.get_height() + 20))
            pygame.display.flip()
            pygame.time.wait(1000)
            self.state = STATE_SPIN if self.spintokens > 0 else STATE_MAIN_MENU

    def _tick_spin(self):
        self.spintokens = 0
        self.state = STATE_MAIN_MENU

    def _update_high_score(self):
        s = int(self.distance)
        if   s > self.distf: self.distf, self.dists, self.distt = s, self.distf, self.dists
        elif s > self.dists: self.dists, self.distt = s, self.dists
        elif s > self.distt: self.distt = s

    def _save_high_score(self):
        self._update_high_score()
        try:
            with open(self._hs_path, 'w') as f:
                f.write(f"{self.distf}\n{self.dists}\n{self.distt}")
        except Exception as e:
            print(f"[HS] {e}")

    def _save_money(self):
        try:
            with open(self._money_path, 'w') as f:
                f.write(str(int(self.money)))
        except Exception as e:
            print(f"[Money] {e}")

    def _rcform(self):
        # ← exact port of original rcform() — uses coinh as spacing, no normalization
        files = glob.glob(self._p("formations", "*.txt"))
        if not files:
            return []
        text  = open(random.choice(files)).readlines()
        coinh = self._load("Coin01.png").get_height()
        height = len(text[0].strip())
        coors = []
        for y in range(len(text)):
            text[y] = text[y].strip()[::-1]
            for x in range(len(text[y].strip())):
                if text[y][x] == '1':
                    coors.append([y, x])
        cbuffer  = (768 - (coinh * height)) / 2
        realcoors = []
        for i in coors:
            realcoors.append([i[0] * coinh + 1024, (i[1] * coinh) + cbuffer])
        return realcoors

    def _outline(self, x, y, thickness, string, font, color, step):
        for ch in string:
            if ch != " ":
                inner = font.render(ch, True, color)
                outer = font.render(ch, True, (0, 0, 0))
                for dx, dy in [(-1,-1),(-1,0),(-1,1),(0,-1),(0,1),(1,-1),(1,0),(1,1)]:
                    self.screen.blit(outer, (x + dx * thickness, y + dy * thickness))
                self.screen.blit(inner, (x, y))
            x += step


if __name__ == "__main__":
    from PyQt5.QtWidgets import QApplication
    app  = QApplication(sys.argv)
    game = JetpackGame(num_channels=1)
    game.start_game()
    sys.exit(app.exec_())