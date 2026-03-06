import pygame
import pygame.gfxdraw
import serial
import serial.tools.list_ports
import threading
import time
from collections import deque
import random
import math

BAUD_RATE  = 38400
BOARD_SIZE = 8
CELL_SIZE  = 60

WIDTH, HEIGHT = 600, 820
OFFSET_X = (WIDTH - BOARD_SIZE * CELL_SIZE) // 2
OFFSET_Y = 160

BG_COLOR    = (6, 8, 18)
TEXT_COLOR  = (210, 225, 255)
ACCENT      = (0, 200, 255)
PANEL_COLOR = (10, 12, 28)

# Neon gem colors
COLORS = {
    0: (0, 0, 0),
    1: (255, 45,  80),
    2: (0,  160, 255),
    3: (0,  240, 120),
    4: (255, 210,  0),
    5: (180,  0, 255),
    6: (255, 120,  0),
}
GLOW = {
    0: (0, 0, 0),
    1: (255, 80, 110),
    2: (60, 200, 255),
    3: (80, 255, 160),
    4: (255, 230, 80),
    5: (210, 80, 255),
    6: (255, 170, 60),
}
MEDAL = [(255, 215, 0), (192, 192, 192), (205, 127, 50), (150, 160, 180), (130, 140, 160)]


def get_ports():
    result = []
    for p in serial.tools.list_ports.comports():
        desc = str(p.description).lower()
        manu = str(p.manufacturer).lower()
        is_board = any(x in desc for x in ["stm", "stlink", "st-link", "ch340", "cp210", "ftdi", "uart"]) or \
                   any(x in manu for x in ["stmicroelectronics", "wch", "silicon labs", "ftdi"])
        result.append({"device": p.device, "is_board": is_board})
    return result


# ─────────────────────────────────────────────────────────────────────────────
class Star:
    """Background ambient star for the starfield."""
    def __init__(self, w, h):
        self.x    = random.randint(0, w)
        self.y    = random.randint(0, h)
        self.r    = random.uniform(0.5, 2.0)
        self.base = random.randint(60, 160)
        self.phase = random.uniform(0, math.pi * 2)
        self.speed = random.uniform(0.5, 2.0)

    def brightness(self):
        return int(self.base + 40 * math.sin(time.time() * self.speed + self.phase))

    def draw(self, surface):
        b = self.brightness()
        pygame.gfxdraw.filled_circle(surface, int(self.x), int(self.y), int(self.r), (b, b, b+30, 180))


class Particle:
    def __init__(self, x, y, color):
        angle = random.uniform(0, 2 * math.pi)
        speed = random.uniform(1.5, 7)
        self.x, self.y = float(x), float(y)
        self.vx = math.cos(angle) * speed
        self.vy = math.sin(angle) * speed
        self.life  = random.randint(25, 45)
        self.max_life = self.life
        self.color = color
        self.r     = random.uniform(1.5, 4.0)

    def update(self):
        self.x  += self.vx
        self.y  += self.vy
        self.vy += 0.18
        self.vx *= 0.97
        self.life -= 1

    def draw(self, surface):
        if self.life <= 0:
            return
        t     = self.life / self.max_life
        alpha = int(255 * t)
        r     = max(1, int(self.r * t))
        # glow halo
        glow_surf = pygame.Surface((r * 6 + 2, r * 6 + 2), pygame.SRCALPHA)
        gc = (*self.color, int(alpha * 0.35))
        pygame.gfxdraw.filled_circle(glow_surf, r * 3 + 1, r * 3 + 1, r * 3, gc)
        surface.blit(glow_surf, (int(self.x) - r * 3 - 1, int(self.y) - r * 3 - 1))
        # core
        pygame.gfxdraw.filled_circle(surface, int(self.x), int(self.y), r, (*self.color, alpha))


class FloatingText:
    def __init__(self, x, y, text, color, font):
        self.x, self.y = float(x), float(y)
        self.text  = text
        self.color = color
        self.font  = font
        self.life  = 255
        self.vx    = random.uniform(-0.5, 0.5)
        self.vy    = random.uniform(-3.0, -1.8)
        self.scale = 1.4  # starts big, shrinks

    def update(self):
        self.x    += self.vx
        self.y    += self.vy
        self.vy   *= 0.94
        self.life -= 5
        self.scale = max(1.0, self.scale - 0.02)

    def draw(self, surface):
        if self.life <= 0:
            return
        alpha = max(0, int(self.life))
        ts = self.font.render(self.text, True, self.color).convert_alpha()
        ss = self.font.render(self.text, True, (0, 0, 0)).convert_alpha()
        ts.set_alpha(alpha)
        ss.set_alpha(int(alpha * 0.6))
        rect = ts.get_rect(center=(int(self.x), int(self.y)))
        surface.blit(ss, (rect.x + 2, rect.y + 2))
        surface.blit(ts, rect)


class AnimCell:
    def __init__(self, r, c):
        self.r, self.c = r, c
        self.color    = 0
        self.x        = OFFSET_X + c * CELL_SIZE + CELL_SIZE // 2
        self.y        = OFFSET_Y + r * CELL_SIZE + CELL_SIZE // 2
        self.target_y = self.y
        self.scale    = 1.0
        # Die animation
        self.dying      = False
        self.die_scale  = 1.0   # shrinks from 1.0 → 0
        self.die_alpha  = 255   # fades from 255 → 0
        self.die_color  = 0     # color id captured at death moment

    def sync(self, new_color):
        """Returns old color if color changed, else None."""
        if self.color != new_color:
            old = self.color
            self.color = new_color
            if old != 0 and new_color == 0:
                # Start die animation instead of instant disappear
                self.dying     = True
                self.die_scale = 1.0
                self.die_alpha = 255
                self.die_color = old
            elif old == 0 and new_color != 0:
                self.y = self.target_y - CELL_SIZE
                self.dying = False
            return old
        return None

    def update_position(self, new_r):
        self.r        = new_r
        self.target_y = OFFSET_Y + new_r * CELL_SIZE + CELL_SIZE // 2

    def update(self):
        self.y += (self.target_y - self.y) * 0.45
        if self.scale < 1.0:
            self.scale = min(1.0, self.scale + 0.1)
        # Advance die animation
        if self.dying:
            self.die_scale = max(0.0, self.die_scale - 0.085)
            self.die_alpha = max(0,   self.die_alpha - 22)
            if self.die_scale <= 0 or self.die_alpha <= 0:
                self.dying = False

    def draw(self, surface):
        # Draw die animation on top (fading remnant of dead gem)
        if self.dying and self.die_color != 0:
            self._draw_gem(surface, self.die_color, self.die_scale, self.die_alpha)

        if self.color == 0:
            return
        self._draw_gem(surface, self.color, self.scale, 255)

    def _draw_gem(self, surface, color_id, scale, alpha):
        base  = COLORS[color_id]
        glow  = GLOW[color_id]
        R     = int((CELL_SIZE // 2 - 5) * scale)
        if R < 3:
            return
        cx, cy = int(self.x), int(self.y)
        t      = alpha / 255.0
        pulse  = 0.5 + 0.5 * math.sin(time.time() * 2.8 + self.c * 0.9 + self.r * 1.3)

        # ── 1. Outer soft glow ──────────────────────────────────────────────
        for i in range(5, 0, -1):
            gr = R + i * 3
            ga = int(20 * pulse * (6 - i) * t)
            if ga < 2:
                continue
            gs = pygame.Surface((gr * 2 + 2, gr * 2 + 2), pygame.SRCALPHA)
            pygame.gfxdraw.filled_circle(gs, gr + 1, gr + 1, gr, (*glow, ga))
            surface.blit(gs, (cx - gr - 1, cy - gr - 1))

        # ── 2. Hexagon gem shape ─────────────────────────────────────────────
        # Flat-top hexagon: 6 vertices
        def hex_pt(angle_deg, r):
            a = math.radians(angle_deg)
            return (cx + r * math.cos(a), cy + r * math.sin(a))

        outer  = [hex_pt(30 + 60 * i, R)       for i in range(6)]
        inner  = [hex_pt(30 + 60 * i, R * 0.55) for i in range(6)]
        center_pt = (cx, cy)

        # Draw 6 trapezoid facets with different brightness
        # Top facets: lighter, bottom: darker
        brightness_mult = [1.3, 1.1, 0.8, 0.6, 0.8, 1.1]  # top=light, bottom=dark
        for i in range(6):
            bm   = brightness_mult[i]
            fc   = tuple(min(255, int(v * bm)) for v in base)
            poly = [outer[i], outer[(i+1) % 6], inner[(i+1) % 6], inner[i]]
            pts  = [(int(x), int(y)) for x, y in poly]
            fsurf = pygame.Surface((R * 2 + 4, R * 2 + 4), pygame.SRCALPHA)
            shifted = [(x - (cx - R - 2), y - (cy - R - 2)) for x, y in pts]
            pygame.gfxdraw.filled_polygon(fsurf, shifted, (*fc, int(235 * t)))
            pygame.gfxdraw.aapolygon(fsurf,     shifted, (*fc, int(255 * t)))
            surface.blit(fsurf, (cx - R - 2, cy - R - 2))

        # Center hex fill (brighter core)
        inner_pts  = [(int(x), int(y)) for x, y in inner]
        core_color = tuple(min(255, int(v * 1.4)) for v in base)
        csurf = pygame.Surface((R * 2 + 4, R * 2 + 4), pygame.SRCALPHA)
        shifted_inner = [(x - (cx - R - 2), y - (cy - R - 2)) for x, y in inner_pts]
        pygame.gfxdraw.filled_polygon(csurf, shifted_inner, (*core_color, int(220 * t)))
        surface.blit(csurf, (cx - R - 2, cy - R - 2))

        # ── 3. Outer edge outline ───────────────────────────────────────────
        outer_pts = [(int(x), int(y)) for x, y in outer]
        esurf = pygame.Surface((R * 2 + 4, R * 2 + 4), pygame.SRCALPHA)
        shifted_outer = [(x - (cx - R - 2), y - (cy - R - 2)) for x, y in outer_pts]
        edge_col = tuple(min(255, int(v * 1.6)) for v in glow)
        pygame.gfxdraw.aapolygon(esurf, shifted_outer, (*edge_col, int(200 * t)))
        surface.blit(esurf, (cx - R - 2, cy - R - 2))

        # ── 4. Inner spoke lines (facet detail) ────────────────────────────
        spoke_surf = pygame.Surface((R * 2 + 4, R * 2 + 4), pygame.SRCALPHA)
        sc = (*glow, int(55 * t))
        ox, oy = cx - R - 2, cy - R - 2
        for i in range(6):
            ix, iy = int(inner[i][0]) - ox, int(inner[i][1]) - oy
            pygame.draw.line(spoke_surf, sc,
                             (int(center_pt[0]) - ox, int(center_pt[1]) - oy),
                             (ix, iy), 1)
        surface.blit(spoke_surf, (ox, oy))

        # ── 5. Specular highlight (top-left glint) ──────────────────────────
        hR = max(2, R // 3)
        hx = cx - R // 3
        hy = cy - R // 3
        # Primary bright spot
        hsurf = pygame.Surface((hR * 4, hR * 4), pygame.SRCALPHA)
        pygame.gfxdraw.filled_circle(hsurf, hR * 2, hR * 2, hR,
                                     (255, 255, 255, int(160 * t)))
        surface.blit(hsurf, (hx - hR * 2, hy - hR * 2))
        # Tiny sharp glint
        gr2 = max(1, R // 6)
        g2surf = pygame.Surface((gr2 * 4, gr2 * 4), pygame.SRCALPHA)
        pygame.gfxdraw.filled_circle(g2surf, gr2 * 2, gr2 * 2, gr2,
                                     (255, 255, 255, int(220 * t)))
        surface.blit(g2surf, (hx - gr2 * 2 - 2, hy - gr2 * 2 - 2))

        # ── 6. Bottom shadow reflection ─────────────────────────────────────
        sr = max(1, R // 4)
        ssurf = pygame.Surface((sr * 4, sr * 4), pygame.SRCALPHA)
        dark_glow = tuple(min(255, int(v * 0.6)) for v in glow)
        pygame.gfxdraw.filled_circle(ssurf, sr * 2, sr * 2, sr,
                                     (*dark_glow, int(60 * t)))
        surface.blit(ssurf, (cx + R // 4 - sr * 2, cy + R // 3 - sr * 2))


# ─────────────────────────────────────────────────────────────────────────────
class Match3Game:
    def __init__(self):
        pygame.init()

        self.windowed_w    = 600
        self.windowed_h    = 820
        self.is_fullscreen = False

        self.screen = pygame.display.set_mode((WIDTH, HEIGHT), pygame.RESIZABLE)
        pygame.display.set_caption("STM32 3 IN A ROW")
        self.clock = pygame.time.Clock()

        self.font_title = pygame.font.SysFont("Consolas",    52, bold=True)
        self.font_big   = pygame.font.SysFont("Consolas",    32, bold=True)
        self.font_small = pygame.font.SysFont("Consolas",    17, bold=True)
        self.font_hint  = pygame.font.SysFont("Consolas",    13)
        self.font_score = pygame.font.SysFont("Consolas",    38, bold=True)

        # Starfield
        self.stars = [Star(WIDTH, HEIGHT) for _ in range(110)]
        self._star_surf_time = -1

        self.board          = [[AnimCell(r, c) for c in range(BOARD_SIZE)] for r in range(BOARD_SIZE)]
        self.particles      = []
        self.floating_texts = []

        self.state               = "MENU"
        self.menu_action_target  = ""
        self.pause_origin        = "PLAYING"   # where to return on CANCEL
        self.player_name         = ""
        self.score               = 0
        self.score_per_ball      = 10
        self.selected            = None
        self.busy                = False
        self.busy_start_time     = 0.0
        self.running             = True
        self.exiting_game        = False

        self.current_slot              = None
        self._slot_already_saved       = False
        self.last_action_time          = time.time()
        self.hint_cells                = None
        self.pending_explosions        = set()
        self.pending_swap              = None
        self.matches_detected_for_swap = False
        self.received_0x16_during_busy = False
        self._cleared_this_turn        = 0

        # BUG FIX #7: msg_lock protects info_msg from cross-thread writes
        self.msg_lock   = threading.Lock()
        self.info_msg   = ""
        self.info_timer = 0
        self.info_color = (255, 255, 0)

        # Leaderboard — single source of truth: MCU Flash
        self.best_scores            = {}
        self._lb_loaded             = False
        self._lb_temp_scores        = {}
        self._lb_session            = 0
        self.temp_leaderboard_names = {}
        # BUG FIX #5: use an Event instead of a plain counter to avoid stale state
        self._lb_done    = threading.Event()
        self._lb_lock    = threading.Lock()  # BUG FIX #8: protect leaderboard temp dict
        self._lb_received = 0

        self.slot_names = ["EMPTY", "EMPTY", "EMPTY"]
        self.temp_slots = {i: ['\x00'] * 12 for i in range(3)}

        self.update_layout()

        self.available_ports     = get_ports()
        self.selected_port_index = 0
        self.connected           = False
        self.ser                 = None
        # BUG FIX #1: separate lock for queue vs serial to avoid deadlock
        self.queue      = deque()
        self.queue_lock = threading.Lock()
        self.ser_lock   = threading.Lock()
        self.last_rx_time = 0

        self.reader_thread = threading.Thread(target=self.reader_loop, daemon=True)
        self.reader_thread.start()

        # BUG FIX #10: ping timer fires every second but we only send in PLAYING state
        pygame.time.set_timer(pygame.USEREVENT + 1, 1000)

    # ── Utilities ─────────────────────────────────────────────────────────────

    @staticmethod
    def _bytes_to_ascii(raw_bytes):
        """Convert MCU bytes to ASCII string.
        Accepts only bytes 32-126 (printable ASCII).
        Stops at first null (0x00) or garbage byte (>126) — Flash uninitialized = 0xFF."""
        result = []
        for b in raw_bytes:
            if b == 0:
                break
            if 32 <= b <= 126:
                result.append(chr(b))
        return "".join(result)

    def clean_text(self, text):
        """Keep only printable ASCII chars (32–126). Filters MCU garbage bytes like 0xFF."""
        return "".join(c for c in str(text) if 32 <= ord(c) <= 126).strip()

    def show_msg(self, text, duration=120, color=(255, 255, 0)):
        # BUG FIX #7: thread-safe message update
        with self.msg_lock:
            self.info_msg   = text
            self.info_timer = duration
            self.info_color = color

    def update_layout(self):
        global OFFSET_X, OFFSET_Y
        OFFSET_X = (WIDTH - BOARD_SIZE * CELL_SIZE) // 2
        OFFSET_Y = (HEIGHT - BOARD_SIZE * CELL_SIZE) // 2 - 30

        for r in range(BOARD_SIZE):
            for c in range(BOARD_SIZE):
                cell = self.board[r][c]
                cell.x        = OFFSET_X + c * CELL_SIZE + CELL_SIZE // 2
                cell.target_y = OFFSET_Y + r * CELL_SIZE + CELL_SIZE // 2
                if abs(cell.y - cell.target_y) < 2 or cell.color == 0:
                    cell.y = cell.target_y

        self.stars = [Star(WIDTH, HEIGHT) for _ in range(110)]

        panel_y = HEIGHT - 70
        self.rect_left  = pygame.Rect(WIDTH // 2 - 250, panel_y + 20, 40, 35)
        self.rect_right = pygame.Rect(WIDTH // 2 - 10,  panel_y + 20, 40, 35)
        self.rect_conn  = pygame.Rect(WIDTH // 2 + 50,  panel_y + 15, 150, 40)

    def toggle_fullscreen(self):
        global WIDTH, HEIGHT
        self.is_fullscreen = not self.is_fullscreen
        if self.is_fullscreen:
            info = pygame.display.Info()
            WIDTH, HEIGHT = info.current_w, info.current_h
            self.screen = pygame.display.set_mode((WIDTH, HEIGHT), pygame.FULLSCREEN)
        else:
            WIDTH, HEIGHT = self.windowed_w, self.windowed_h
            self.screen = pygame.display.set_mode((WIDTH, HEIGHT), pygame.RESIZABLE)
        self.update_layout()

    # ── UART ──────────────────────────────────────────────────────────────────

    def crc8(self, data):
        crc = 0
        for b in data:
            crc ^= b
            for _ in range(8):
                crc = (crc << 1) ^ 0x07 if crc & 0x80 else crc << 1
                crc &= 0xFF
        return crc

    def send(self, cmd, b1=0, b2=0, b3=0, b4=0):
        if not self.connected:
            return
        try:
            p = bytearray([cmd, b1, b2, b3, b4])
            p.append(self.crc8(p))
            with self.ser_lock:  # BUG FIX #1: protect serial write
                self.ser.write(p)
        except Exception:
            self.show_msg("ERROR: DATA SEND FAILED!", 120, (255, 60, 60))
            # Schedule disconnect on main thread to avoid ser_lock deadlock
            self._pending_disconnect = True

    def send_player_name(self):
        """Sends name in 6 chunks of 3 bytes = 18 bytes (15 chars + nulls)."""
        if not self.player_name:
            return
        padded = self.player_name[:15].ljust(18, '\x00')
        for i in range(6):
            chunk = padded[i * 3: i * 3 + 3]
            self.send(0x20, i, ord(chunk[0]), ord(chunk[1]), ord(chunk[2]))
            time.sleep(0.015)   # 15ms — enough at 38400 baud, was 50ms

    def reader_loop(self):
        """Background thread: reads serial and pushes validated packets to queue.
        Reads only complete 6-byte aligned chunks — no byte-slip or resync needed.
        Drains ALL pending packets per poll for fast board fill (64 × 0x16)."""
        while self.running:
            if self.connected and self.ser and self.ser.is_open:
                try:
                    with self.ser_lock:
                        waiting = self.ser.in_waiting
                    n = waiting // 6   # only read whole packets
                    if n > 0:
                        with self.ser_lock:
                            raw = self.ser.read(n * 6)
                        packets = []
                        for i in range(n):
                            p = raw[i * 6:(i + 1) * 6]
                            if self.crc8(p[:5]) == p[5]:
                                packets.append(bytes(p))
                        if packets:
                            with self.queue_lock:
                                self.queue.extend(packets)
                except Exception:
                    if self.connected:
                        self.show_msg("ERROR: MCU CABLE DISCONNECTED!", 180, (255, 60, 60))
                        self._pending_disconnect = True
            time.sleep(0.002)

    def _load_leaderboard_from_flash(self):
        if not self.connected:
            return
        self._lb_session += 1
        current_session = self._lb_session

        with self._lb_lock:
            self.temp_leaderboard_names.clear()
            self._lb_received    = 0
            self._lb_temp_scores = {}

        self._lb_loaded = False
        self._lb_done.clear()
        self.send(0x40)
        self._lb_done.wait(timeout=3.0)

        if self._lb_session == current_session:
            with self._lb_lock:
                tmp = dict(self._lb_temp_scores)
            if tmp:
                self.best_scores = tmp
        self._lb_loaded = True

    def sync_board_data(self, delay=0.0):
        """Requests slot nicknames + leaderboard from MCU Flash."""
        if delay > 0:
            time.sleep(delay)
        if not self.connected:
            return

        self.temp_slots = {i: ['\x00'] * 12 for i in range(3)}
        for i in range(3):
            self.send(0x32, i)
            time.sleep(0.1)

        self._load_leaderboard_from_flash()

    # ── Game tasks (background threads) ───────────────────────────────────────

    def task_save_slot(self, slot_idx):
        """Save current game state to a slot WITHOUT ending the game.
        Sets _slot_already_saved so safe_exit_to_menu won't send 0x30 again."""
        self.exiting_game = True
        self.send_player_name()
        time.sleep(0.3)
        self.send(0x30, slot_idx)
        time.sleep(0.8)          # give MCU enough time to write Flash
        self._slot_already_saved = True
        self.current_slot = slot_idx
        self.temp_slots = {i: ['\x00'] * 12 for i in range(3)}
        for i in range(3):
            self.send(0x32, i)
            time.sleep(0.12)
        self.show_msg(f"SAVED TO SLOT {slot_idx + 1}!", 150, (0, 255, 160))
        self.exiting_game = False

    def task_save_and_exit(self, slot_idx):
        """Save to slot + update leaderboard + exit to MENU."""
        self.exiting_game = True
        self.send_player_name()
        time.sleep(0.3)
        self.send(0x30, slot_idx)   # save slot BEFORE finish
        self.show_msg(f"SAVING SLOT {slot_idx + 1}...", 200, (100, 255, 255))
        time.sleep(0.8)             # Flash write margin
        self.current_slot        = slot_idx
        self._slot_already_saved = True
        self.send(0x12, 0xFF)       # FINISH → MCU writes leaderboard
        time.sleep(1.6)
        self._load_leaderboard_from_flash()
        self.current_slot        = None
        self._slot_already_saved = False
        self.exiting_game = False
        self.state = "MENU"

    def task_load_slot(self, slot_idx):
        self.exiting_game = True
        self.send_player_name()
        time.sleep(0.2)
        self.send(0x31, slot_idx)
        time.sleep(0.3)
        self.send(0x15)
        self.exiting_game = False

    def safe_exit_to_menu(self):
        self.exiting_game = True
        self.send_player_name()
        time.sleep(0.3)

        self.send(0x15)
        time.sleep(0.5)

        if self.current_slot is not None and not self._slot_already_saved:
            self.send(0x30, self.current_slot)
            self.show_msg(f"SAVING SLOT {self.current_slot + 1}...", 180, (100, 255, 255))
            time.sleep(0.8)

        self.current_slot        = None
        self._slot_already_saved = False

        self.send(0x12, 0xFF)
        time.sleep(1.8)

        self._load_leaderboard_from_flash()

        self.exiting_game = False
        self.state = "MENU"

    def _game_over_exit(self):
        """Called from background thread when MCU sends 0x12 (GAME OVER).
        Player sees the message for 2s, then we clean up and go to MENU."""
        self.exiting_game = True
        self.busy = False
        time.sleep(2.0)          # let player read GAME OVER message

        # Request final score before MCU clears it
        self.send(0x15)
        time.sleep(0.4)

        # Save slot if one was assigned
        if self.current_slot is not None:
            self.send(0x30, self.current_slot)
            time.sleep(0.6)
            self.current_slot = None

        # MCU already called Update_Leaderboard on 0x12 — just wait for Flash write
        time.sleep(0.8)
        self._load_leaderboard_from_flash()

        self.exiting_game = False
        self.state = "MENU"

    # ── Connection ────────────────────────────────────────────────────────────

    def connect(self):
        if self.connected or not self.available_ports:
            return
        try:
            port = self.available_ports[self.selected_port_index]["device"]
            self.ser          = serial.Serial(port, BAUD_RATE, timeout=0.1)
            self.connected    = True
            self.last_rx_time = time.time()
            self._pending_disconnect = False
            self.show_msg("CONNECTED TO " + port, 120, (100, 255, 100))

            for r in range(BOARD_SIZE):
                for c in range(BOARD_SIZE):
                    self.board[r][c].color = 0

            self.best_scores = {}
            self._lb_loaded  = False
            threading.Thread(target=self.sync_board_data, args=(2.0,), daemon=True).start()
        except Exception:
            self.connected = False
            self.show_msg("CONNECTION FAILED!", 120, (255, 60, 60))

    def disconnect(self):
        self.connected = False
        self.busy      = False
        try:
            with self.ser_lock:
                if self.ser:
                    self.ser.close()
        except Exception:
            pass
        self.best_scores = {}
        self._lb_loaded  = False
        self.state       = "MENU"

    # ── Game logic ────────────────────────────────────────────────────────────

    def start_new_game(self):
        self.score        = 0
        self.busy         = False
        self.selected     = None
        self.current_slot = None
        self._slot_already_saved = False
        self.pending_explosions.clear()
        self.pending_swap              = None
        self.matches_detected_for_swap = False
        self.last_action_time          = time.time()
        self.hint_cells                = None
        self.floating_texts.clear()
        self.particles.clear()

        for r in range(BOARD_SIZE):
            for c in range(BOARD_SIZE):
                self.board[r][c].color = 0
                self.board[r][c].dying = False

        # Send name + start command in background so UI doesn't freeze
        def _start():
            self.send_player_name()   # 6 packets × 50ms = ~300ms
            self.send(0x10)           # MCU starts filling board via 0x16 packets
        threading.Thread(target=_start, daemon=True).start()
        self.state = "PLAYING"

    def create_explosion(self, x, y, color_id):
        glow = GLOW.get(color_id, COLORS.get(color_id, (255, 255, 255)))
        for _ in range(22):
            self.particles.append(Particle(x, y, glow))

    def check_any_match(self):
        for r in range(BOARD_SIZE):
            for c in range(BOARD_SIZE - 2):
                v = self.board[r][c].color
                if v != 0 and v == self.board[r][c + 1].color == self.board[r][c + 2].color:
                    return True
        for c in range(BOARD_SIZE):
            for r in range(BOARD_SIZE - 2):
                v = self.board[r][c].color
                if v != 0 and v == self.board[r + 1][c].color == self.board[r + 2][c].color:
                    return True
        return False

    def find_possible_move(self):
        for r in range(BOARD_SIZE):
            for c in range(BOARD_SIZE):
                if c < BOARD_SIZE - 1:
                    self.board[r][c].color, self.board[r][c + 1].color = \
                        self.board[r][c + 1].color, self.board[r][c].color
                    found = self.check_any_match()
                    self.board[r][c].color, self.board[r][c + 1].color = \
                        self.board[r][c + 1].color, self.board[r][c].color
                    if found:
                        return ((r, c), (r, c + 1))
                if r < BOARD_SIZE - 1:
                    self.board[r][c].color, self.board[r + 1][c].color = \
                        self.board[r + 1][c].color, self.board[r][c].color
                    found = self.check_any_match()
                    self.board[r][c].color, self.board[r + 1][c].color = \
                        self.board[r + 1][c].color, self.board[r][c].color
                    if found:
                        return ((r, c), (r + 1, c))
        return None

    def detect_and_save_matches(self):
        """Scan current board for matches; update score multiplier.
        BUG FIX #3: called exactly once per swap, not per-cell."""
        for r in range(BOARD_SIZE):
            for c in range(BOARD_SIZE - 2):
                color = self.board[r][c].color
                if color != 0 and self.board[r][c + 1].color == color and self.board[r][c + 2].color == color:
                    self.pending_explosions.update([(r, c), (r, c + 1), (r, c + 2)])
        for c in range(BOARD_SIZE):
            for r in range(BOARD_SIZE - 2):
                color = self.board[r][c].color
                if color != 0 and self.board[r + 1][c].color == color and self.board[r + 2][c].color == color:
                    self.pending_explosions.update([(r, c), (r + 1, c), (r + 2, c)])

        count = len(self.pending_explosions)
        if   count == 3: self.score_per_ball = 10
        elif count == 4: self.score_per_ball = 15
        elif count >= 5: self.score_per_ball = 20
        else:            self.score_per_ball = 10

    # BUG FIX #6: is_board_stable no longer requires all cells to be non-zero.
    # It only checks that all non-zero cells have finished their drop animation.
    def is_board_stable(self):
        for r in range(BOARD_SIZE):
            for c in range(BOARD_SIZE):
                cell = self.board[r][c]
                if cell.dying:                                   # burn animation in progress
                    return False
                if cell.color != 0 and abs(cell.y - cell.target_y) > 1.0:
                    return False
        return True

    # ── UART processing (main thread) ─────────────────────────────────────────

    def process_uart(self):
        # BUG FIX #1: drain pending_disconnect flag set by reader_loop
        if getattr(self, '_pending_disconnect', False):
            self._pending_disconnect = False
            self.disconnect()
            return

        # Watchdog: якщо MCU не відповів на swap за 5 секунд — скидаємо busy
        if self.busy and (time.time() - self.busy_start_time) > 5.0:
            if self.pending_swap:
                (r1, c1), (r2, c2), col1, col2 = self.pending_swap
                self.board[r1][c1].color = col1
                self.board[r2][c2].color = col2
            self.pending_swap  = None
            self.busy          = False
            self.pending_explosions.clear()
            self.show_msg("TIMEOUT — RETRYING...", 90, (255, 160, 0))

        with self.queue_lock:  # BUG FIX #1: use separate queue lock
            packets = list(self.queue)
            self.queue.clear()

        for p in packets:
            cmd = p[0]

            if cmd == 0x16:
                self.received_0x16_during_busy = True
                r, c, color = p[1], p[2], p[3]
                if 0 <= r < BOARD_SIZE and 0 <= c < BOARD_SIZE:
                    cell      = self.board[r][c]
                    old_color = cell.sync(color)
                    if color == 0 and old_color and old_color != 0:
                        # Count cleared cells to set score_per_ball bonus tier
                        self._cleared_this_turn += 1
                        count = self._cleared_this_turn
                        if   count <= 3: self.score_per_ball = 10
                        elif count == 4: self.score_per_ball = 15
                        else:            self.score_per_ball = 20
                        # MCU cleared this cell — fire explosion + score popup
                        self.create_explosion(cell.x, cell.y, old_color)
                        self.floating_texts.append(FloatingText(
                            cell.x, cell.y - 15,
                            f"+{self.score_per_ball}",
                            GLOW[old_color], self.font_small,
                        ))
                    cell.update_position(r)

            elif cmd == 0x11:
                # MCU finished processing the swap.
                # If no 0x16 packets arrived → swap was invalid → revert visual swap.
                if self.pending_swap and not self.received_0x16_during_busy:
                    (r1, c1), (r2, c2), col1, col2 = self.pending_swap
                    self.board[r1][c1].color = col1
                    self.board[r2][c2].color = col2
                self.pending_swap              = None
                self.pending_explosions.clear()
                self.matches_detected_for_swap = False
                self.busy = False

            elif cmd == 0x12:
                if p[4] == 0xAA:
                    self.show_msg("GAME OVER! YOU'RE IN TOP 5!", 240, (255, 215, 0))
                else:
                    self.show_msg("GAME OVER!", 240, (255, 120, 60))
                # Auto-exit to MENU: fetch final score → update leaderboard → switch state
                threading.Thread(target=self._game_over_exit, daemon=True).start()

            elif cmd == 0x15:
                self.score = (p[1] << 24) | (p[2] << 16) | (p[3] << 8) | p[4]

            elif cmd == 0x30:
                pass  # Save ACK — no action needed

            elif cmd == 0x31:
                if p[4] == 0xEE:
                    self.show_msg("ERROR: SLOT IS EMPTY!", 120, (255, 60, 60))
                    self.current_slot = None
                else:
                    self.show_msg("GAME LOADED!", 120, (100, 255, 100))
                    self.last_action_time = time.time()
                    self.hint_cells       = None
                    self.floating_texts.clear()
                    self.state = "PLAYING"

            elif cmd in [0x33, 0x34, 0x35, 0x36]:
                slot = p[1]
                if slot < 3:
                    chunk = self._bytes_to_ascii(p[2:5])
                    # Pad chunk to exactly 3 chars with null sentinel
                    chars = list(chunk.ljust(3, '\x00'))[:3]
                    if   cmd == 0x33: self.temp_slots[slot][0:3]  = chars
                    elif cmd == 0x34: self.temp_slots[slot][3:6]  = chars
                    elif cmd == 0x35: self.temp_slots[slot][6:9]  = chars
                    elif cmd == 0x36: self.temp_slots[slot][9:12] = chars

            elif cmd == 0x32:
                slot = p[1]
                if slot < 3:
                    if p[4] == 0xAA:
                        # Stop at first null terminator
                        raw_chars = self.temp_slots[slot]
                        name_raw = ""
                        for ch in raw_chars:
                            if ch == '\x00':
                                break
                            name_raw += ch
                        clean = self.clean_text(name_raw)
                        self.slot_names[slot] = clean if clean else "EMPTY"
                    else:
                        self.slot_names[slot] = "EMPTY"

            # Leaderboard name chunks
            elif cmd in [0x41, 0x43, 0x44, 0x45, 0x46]:
                idx = p[1]
                with self._lb_lock:
                    if idx not in self.temp_leaderboard_names:
                        self.temp_leaderboard_names[idx] = ['\x00'] * 15
                    chunk = self._bytes_to_ascii(p[2:5])
                    chars = list(chunk.ljust(3, '\x00'))[:3]
                    if   cmd == 0x41: self.temp_leaderboard_names[idx][0:3]   = chars
                    elif cmd == 0x43: self.temp_leaderboard_names[idx][3:6]   = chars
                    elif cmd == 0x44: self.temp_leaderboard_names[idx][6:9]   = chars
                    elif cmd == 0x45: self.temp_leaderboard_names[idx][9:12]  = chars
                    elif cmd == 0x46: self.temp_leaderboard_names[idx][12:15] = chars

            # Leaderboard score packet
            elif cmd == 0x42:
                idx = p[1]
                if idx < 5:
                    score = (p[2] << 16) | (p[3] << 8) | p[4]
                    with self._lb_lock:
                        raw_chars = self.temp_leaderboard_names.get(idx, ['\x00'] * 15)
                        name_raw = ""
                        for ch in raw_chars:
                            if ch == '\x00':
                                break
                            name_raw += ch
                        self._lb_received += 1
                        received_now = self._lb_received
                        clean = self.clean_text(name_raw)
                        if clean and score > 0:
                            prev = self._lb_temp_scores.get(clean, 0)
                            if score > prev:
                                self._lb_temp_scores[clean] = score
                    if received_now >= 5:
                        self._lb_done.set()

        # Connection timeout check intentionally disabled — MCU timing is handled
        # by the physical USB/serial layer; false positives cause unwanted disconnects.

    # ── Input ─────────────────────────────────────────────────────────────────

    def handle_keydown(self, key, unicode):
        if self.state == "INPUT_NAME":
            if key == pygame.K_BACKSPACE:
                self.player_name = self.player_name[:-1]
            elif key == pygame.K_RETURN:
                if self.player_name.strip() and self.menu_action_target == "NEW":
                    self.start_new_game()
            elif unicode and len(self.player_name) < 15:
                # Accept only printable ASCII (32-126), no leading space
                code = ord(unicode)
                if 32 <= code <= 126:
                    # Disallow leading space
                    if code == 32 and not self.player_name:
                        return
                    self.player_name += unicode

    def click(self, pos):
        if self.exiting_game:
            return
        self.last_action_time = time.time()
        self.hint_cells = None

        if self.rect_left.collidepoint(pos):
            self.available_ports = get_ports()
            if self.available_ports:
                self.selected_port_index = (self.selected_port_index - 1) % len(self.available_ports)
            return
        elif self.rect_right.collidepoint(pos):
            self.available_ports = get_ports()
            if self.available_ports:
                self.selected_port_index = (self.selected_port_index + 1) % len(self.available_ports)
            return
        elif self.rect_conn.collidepoint(pos):
            if self.connected:
                self.disconnect()
            else:
                self.connect()
            return

        if not self.connected:
            self.show_msg("ERROR: MCU NOT CONNECTED!", 120, (255, 60, 60))
            return

        if self.state == "MENU":
            cy = HEIGHT // 2 - 76
            if pygame.Rect(WIDTH // 2 - 110, cy, 220, 52).collidepoint(pos):
                self.menu_action_target = "NEW"
                self.state = "INPUT_NAME"

            elif pygame.Rect(WIDTH // 2 - 110, cy + 70, 220, 52).collidepoint(pos):
                self.menu_action_target = "LOAD"
                threading.Thread(target=self.sync_board_data, daemon=True).start()
                self.state = "SLOTS"

            elif pygame.Rect(WIDTH // 2 - 110, cy + 140, 220, 52).collidepoint(pos):
                # Don't clear best_scores — show existing data while refresh loads
                threading.Thread(target=self._load_leaderboard_from_flash, daemon=True).start()
                self.state = "LEADERBOARD"

        elif self.state == "INPUT_NAME":
            if pygame.Rect(WIDTH // 2 - 100, HEIGHT // 2 + 80, 200, 50).collidepoint(pos):
                if self.player_name.strip() and self.menu_action_target == "NEW":
                    self.start_new_game()
            elif pygame.Rect(WIDTH // 2 - 100, HEIGHT // 2 + 150, 200, 50).collidepoint(pos):
                self.state = "MENU"

        elif self.state == "SLOTS":
            cy = HEIGHT // 2 - 80
            for i in range(3):
                if pygame.Rect(WIDTH // 2 - 150, cy + i * 70, 300, 50).collidepoint(pos):
                    if self.menu_action_target == "SAVE_AND_EXIT":
                        threading.Thread(target=self.task_save_and_exit, args=(i,), daemon=True).start()
                    elif self.menu_action_target == "SAVE":
                        self.current_slot = i
                        threading.Thread(target=self.task_save_slot, args=(i,), daemon=True).start()
                        self.state = "PLAYING"
                    elif self.menu_action_target == "LOAD":
                        if self.slot_names[i] != "EMPTY":
                            self.player_name     = self.slot_names[i]
                            self.current_slot    = i
                            self._slot_already_saved = True  # slot exists on MCU — don't 0x30 on exit
                            for r in range(BOARD_SIZE):
                                for c in range(BOARD_SIZE):
                                    self.board[r][c].color = 0
                            self.score = 0
                            threading.Thread(target=self.task_load_slot, args=(i,), daemon=True).start()
                            self.state = "PLAYING"

            if pygame.Rect(WIDTH // 2 - 100, cy + 210, 200, 50).collidepoint(pos):
                # Back — return to PAUSE if we came from there, else MENU
                if self.menu_action_target == "SAVE_AND_EXIT":
                    self.state = "PAUSE"
                else:
                    self.state = "MENU"

        elif self.state == "LEADERBOARD":
            if pygame.Rect(WIDTH // 2 - 100, HEIGHT - 180, 200, 50).collidepoint(pos):
                self.state = "MENU"

        elif self.state == "PAUSE":
            bw, bh = 280, 52
            bx = WIDTH // 2 - bw // 2
            panel_h = 240
            panel_y = HEIGHT // 2 - panel_h // 2
            exit_rect   = pygame.Rect(bx, panel_y + 110, bw, bh)
            cancel_rect = pygame.Rect(bx, panel_y + 174, bw, bh)

            if exit_rect.collidepoint(pos):
                threading.Thread(target=self.safe_exit_to_menu, daemon=True).start()
            elif cancel_rect.collidepoint(pos):
                self.state = "PLAYING"

        elif self.state == "PLAYING":
            menu_rect = pygame.Rect(WIDTH - 110, 8, 96, 38)
            save_rect = pygame.Rect(WIDTH - 216, 8, 96, 38)

            if menu_rect.collidepoint(pos):
                # Open pause dialog instead of direct exit
                self.state = "PAUSE"
                return

            if save_rect.collidepoint(pos) and not self.exiting_game:
                self.menu_action_target = "SAVE"
                threading.Thread(target=self.sync_board_data, daemon=True).start()
                self.state = "SLOTS"
                return

            if self.busy or not self.connected or not self.is_board_stable():
                self.selected = None
                return

            c = (pos[0] - OFFSET_X) // CELL_SIZE
            r = (pos[1] - OFFSET_Y) // CELL_SIZE
            if not (0 <= r < BOARD_SIZE and 0 <= c < BOARD_SIZE):
                return

            if self.selected is None:
                self.selected = (r, c)
            else:
                r1, c1 = self.selected
                if abs(r1 - r) + abs(c1 - c) == 1:
                    self.busy  = True
                    self.busy_start_time = time.time()
                    self.received_0x16_during_busy = False
                    self._cleared_this_turn = 0  # reset per-turn cleared counter

                    # Optimistic visual swap — MCU will confirm via 0x16 packets.
                    # We do NOT run detect_and_save_matches() here anymore:
                    # MCU is the single source of truth for what cells get cleared.
                    # pending_explosions is now filled only from MCU 0x16 (color==0) packets.
                    c1_color = self.board[r1][c1].color
                    c2_color = self.board[r][c].color
                    self.board[r1][c1].color = c2_color
                    self.board[r][c].color   = c1_color

                    # Store swap info so we can REVERT if MCU sends 0x11 with no 0x16
                    self.pending_swap = ((r1, c1), (r, c), c1_color, c2_color)
                    self.pending_explosions.clear()

                    self.send(0x11, r1, c1, r, c)

                self.selected = None

    # ── Drawing helpers ───────────────────────────────────────────────────────

    def _draw_bg(self):
        """Deep space background with starfield and scanline grid."""
        self.screen.fill(BG_COLOR)
        # Scanline grid (very subtle)
        grid_surf = pygame.Surface((WIDTH, HEIGHT), pygame.SRCALPHA)
        for y in range(0, HEIGHT, 28):
            pygame.draw.line(grid_surf, (0, 180, 255, 6), (0, y), (WIDTH, y), 1)
        for x in range(0, WIDTH, 28):
            pygame.draw.line(grid_surf, (0, 180, 255, 4), (x, 0), (x, HEIGHT), 1)
        self.screen.blit(grid_surf, (0, 0))
        # Stars
        for s in self.stars:
            s.draw(self.screen)

    def _glow_text(self, text, font, color, glow_color, surface, pos, center=True):
        """Render text with neon glow halo."""
        tx = font.render(text, True, color)
        gx = font.render(text, True, glow_color)
        if center:
            rect = tx.get_rect(center=pos)
        else:
            rect = tx.get_rect(topleft=pos)
        for dx, dy in [(-2,0),(2,0),(0,-2),(0,2),(-1,-1),(1,-1),(-1,1),(1,1)]:
            g = gx.copy(); g.set_alpha(55)
            surface.blit(g, (rect.x + dx, rect.y + dy))
        surface.blit(tx, rect)
        return rect

    def _draw_panel_bg(self, rect, alpha=200, border_color=None, corner=12):
        """Glassmorphic dark panel with neon border."""
        s = pygame.Surface((rect.w, rect.h), pygame.SRCALPHA)
        pygame.draw.rect(s, (8, 14, 35, alpha), s.get_rect(), border_radius=corner)
        self.screen.blit(s, rect.topleft)
        bc = border_color or ACCENT
        pygame.draw.rect(self.screen, bc, rect, 1, border_radius=corner)

    def draw_button(self, surface, rect, label, base_color, font, hover=False):
        # Glow halo on hover
        if hover:
            hs = pygame.Surface((rect.w + 20, rect.h + 20), pygame.SRCALPHA)
            pygame.draw.rect(hs, (*base_color, 55), hs.get_rect(), border_radius=14)
            surface.blit(hs, (rect.x - 10, rect.y - 10))

        # Background
        bg_alpha = 230 if hover else 180
        bg = pygame.Surface((rect.w, rect.h), pygame.SRCALPHA)
        bc = tuple(min(255, v + 40) for v in base_color) if hover else base_color
        dark_bg = tuple(max(0, v // 5) for v in bc)
        pygame.draw.rect(bg, (*dark_bg, bg_alpha), bg.get_rect(), border_radius=10)
        surface.blit(bg, rect.topleft)

        # Bright top edge highlight
        top_rect = pygame.Rect(rect.x + 2, rect.y + 1, rect.w - 4, 2)
        hl_surf = pygame.Surface((top_rect.w, top_rect.h), pygame.SRCALPHA)
        hl_surf.fill((*bc, 80))
        surface.blit(hl_surf, top_rect.topleft)

        # Border
        border_a = 255 if hover else 160
        pygame.draw.rect(surface, (*bc, border_a), rect, 2, border_radius=10)

        # Label with shadow
        safe = self.clean_text(label)
        ts = font.render(safe, True, (255, 255, 255))
        ss = font.render(safe, True, (0, 0, 0))
        tr = ts.get_rect(center=rect.center)
        ss.set_alpha(120)
        surface.blit(ss, (tr.x + 1, tr.y + 2))
        surface.blit(ts, tr)

        # Hover shimmer line
        if hover:
            shimmer = pygame.Surface((rect.w - 8, 1), pygame.SRCALPHA)
            shimmer.fill((255, 255, 255, 60))
            surface.blit(shimmer, (rect.x + 4, rect.centery - 1))

    def draw_centered_btn(self, y, text, color, hover_pos, w=220, h=48):
        rect = pygame.Rect(WIDTH // 2 - w // 2, y, w, h)
        self.draw_button(self.screen, rect, text, color, self.font_small, rect.collidepoint(hover_pos))

    def _draw_title_bar(self, text, y=70):
        """Neon title with side decorative lines."""
        tx = self.font_title.render(text, True, ACCENT)
        rx = tx.get_rect(center=(WIDTH // 2, y))
        # glow
        for dx, dy in [(-3,0),(3,0),(0,-3),(0,3)]:
            g = self.font_title.render(text, True, (0, 100, 200))
            g.set_alpha(60)
            self.screen.blit(g, (rx.x + dx, rx.y + dy))
        self.screen.blit(tx, rx)
        # side lines
        lw = (WIDTH - rx.w) // 2 - 30
        cy = rx.centery
        pygame.draw.line(self.screen, (*ACCENT, 120), (20, cy), (20 + lw, cy), 1)
        pygame.draw.line(self.screen, (*ACCENT, 120), (WIDTH - 20 - lw, cy), (WIDTH - 20, cy), 1)

    def draw(self):
        mx, my = pygame.mouse.get_pos()
        self._draw_bg()

        # Toast message
        with self.msg_lock:
            msg_text  = self.info_msg
            msg_timer = self.info_timer
            msg_color = self.info_color
            if self.info_timer > 0:
                self.info_timer -= 1

        if msg_timer > 0:
            alpha = min(255, msg_timer * 4)
            msg_bg = pygame.Surface((WIDTH - 40, 36), pygame.SRCALPHA)
            msg_bg.fill((0, 0, 0, min(200, alpha)))
            self.screen.blit(msg_bg, (20, 14))
            pygame.draw.rect(self.screen, (*msg_color, min(255, alpha)),
                             pygame.Rect(20, 14, WIDTH - 40, 36), 1, border_radius=6)
            self._glow_text(self.clean_text(msg_text), self.font_small,
                            msg_color, msg_color, self.screen, (WIDTH // 2, 32))

        # ── MENU ──────────────────────────────────────────────────────────────
        if self.state == "MENU":
            # Hero title
            pulse = 0.5 + 0.5 * math.sin(time.time() * 1.8)
            col = (int(0 + 60 * pulse), int(180 + 20 * pulse), int(240 + 15 * pulse))
            self._glow_text("STM32", self.font_title, col, (0, 80, 160), self.screen,
                            (WIDTH // 2, HEIGHT // 2 - 195))
            self._glow_text("MATCH-3", self.font_title, (255, 255, 255), (0, 120, 200),
                            self.screen, (WIDTH // 2, HEIGHT // 2 - 148))

            # Decorative diamond separator
            ds = pygame.Surface((160, 2), pygame.SRCALPHA)
            for i in range(160):
                a = int(255 * math.sin(math.pi * i / 160))
                ds.set_at((i, 0), (*ACCENT, a))
            self.screen.blit(ds, (WIDTH // 2 - 80, HEIGHT // 2 - 118))

            cy = HEIGHT // 2 - 76
            self.draw_centered_btn(cy,       "NEW GAME",    (20, 160, 70),  (mx, my), w=220, h=52)
            self.draw_centered_btn(cy + 70,  "CONTINUE",   (160, 100, 10), (mx, my), w=220, h=52)
            self.draw_centered_btn(cy + 140, "LEADERBOARD", (110, 40, 180), (mx, my), w=220, h=52)

            # Version tag
            vt = self.font_hint.render("STM32 UART  //  38400 BAUD", True, (50, 60, 90))
            self.screen.blit(vt, (WIDTH // 2 - vt.get_width() // 2, HEIGHT - 90))

        # ── INPUT NAME ────────────────────────────────────────────────────────
        elif self.state == "INPUT_NAME":
            self._draw_title_bar("ENTER CALLSIGN")

            # Input panel
            panel = pygame.Rect(WIDTH // 2 - 170, HEIGHT // 2 - 40, 340, 60)
            blink = time.time() % 1 > 0.5
            border_col = ACCENT if blink else (0, 80, 140)
            self._draw_panel_bg(panel, alpha=220, border_color=border_col, corner=8)
            cursor = "|" if blink else " "
            display = self.clean_text(self.player_name) + cursor
            nt = self.font_big.render(display, True, (255, 255, 255))
            self.screen.blit(nt, nt.get_rect(center=panel.center))

            # Char counter
            cc = self.font_hint.render(f"{len(self.player_name)}/15", True, (60, 80, 120))
            self.screen.blit(cc, (panel.right - cc.get_width() - 6, panel.bottom + 4))

            self.draw_centered_btn(HEIGHT // 2 + 60,  "CONFIRM", (20, 160, 70),  (mx, my))
            self.draw_centered_btn(HEIGHT // 2 + 120, "< BACK",    (160, 40, 40),  (mx, my))

        # ── SLOTS ─────────────────────────────────────────────────────────────
        elif self.state == "SLOTS":
            action_word = "SAVE TO" if self.menu_action_target == "SAVE" else "LOAD FROM"
            self._draw_title_bar(f"{action_word} SLOT")

            cy = HEIGHT // 2 - 95
            slot_icons = ["[1]", "[2]", "[3]"]
            for i in range(3):
                rect  = pygame.Rect(WIDTH // 2 - 160, cy + i * 72, 320, 54)
                cname = self.clean_text(self.slot_names[i])
                empty = cname == "EMPTY"
                col   = (50, 55, 90) if empty else (30, 110, 160)
                text  = f"{slot_icons[i]}  {cname}" if not empty else f"{slot_icons[i]}  — EMPTY SLOT —"
                self.draw_button(self.screen, rect, text, col, self.font_small,
                                 rect.collidepoint(mx, my))
                if not empty:
                    dot = pygame.Surface((8, 8), pygame.SRCALPHA)
                    pygame.gfxdraw.filled_circle(dot, 4, 4, 4, (0, 255, 150, 200))
                    self.screen.blit(dot, (rect.right - 18, rect.centery - 4))

            self.draw_centered_btn(cy + 225, "< BACK", (140, 35, 35), (mx, my))

        # ── LEADERBOARD ───────────────────────────────────────────────────────
        elif self.state == "LEADERBOARD":
            self._draw_title_bar("LEADERBOARD")

            panel = pygame.Rect(WIDTH // 2 - 200, 105, 400, 295)
            self._draw_panel_bg(panel, alpha=190, border_color=(180, 150, 0), corner=14)

            if not self._lb_loaded:
                # Still loading
                dots = "." * (int(time.time() * 2) % 4)
                lt = self.font_small.render(f"LOADING{dots}", True, (100, 130, 200))
                self.screen.blit(lt, lt.get_rect(center=(WIDTH // 2, panel.centery)))
            elif not self.best_scores:
                # Loaded but empty
                lt = self.font_small.render("NO RECORDS YET", True, (80, 90, 120))
                self.screen.blit(lt, lt.get_rect(center=(WIDTH // 2, panel.centery)))
            else:
                display_lb = sorted(
                    [{"name": k, "score": v} for k, v in self.best_scores.items()],
                    key=lambda x: x["score"], reverse=True
                )[:5]
                while len(display_lb) < 5:
                    display_lb.append({"name": None, "score": 0})

                row_h = 52
                sy    = panel.y + 14
                for idx, entry in enumerate(display_lb[:5]):
                    row_rect = pygame.Rect(panel.x + 8, sy, panel.w - 16, row_h - 4)
                    # Row bg for top 3
                    if idx < 3 and entry["name"]:
                        rb = pygame.Surface((row_rect.w, row_rect.h), pygame.SRCALPHA)
                        mc = MEDAL[idx]
                        pygame.draw.rect(rb, (*mc, 22), rb.get_rect(), border_radius=8)
                        self.screen.blit(rb, row_rect.topleft)
                        pygame.draw.rect(self.screen, (*mc, 80), row_rect, 1, border_radius=8)

                    mc   = MEDAL[idx]
                    rank_labels = ["#1", "#2", "#3", "#4", "#5"]
                    rt = self.font_small.render(rank_labels[idx], True, mc)
                    self.screen.blit(rt, (row_rect.x + 8, row_rect.centery - rt.get_height() // 2))

                    if entry["name"]:
                        nt = self.font_small.render(self.clean_text(entry["name"]), True, TEXT_COLOR)
                        st = self.font_small.render(f"{entry['score']:,}", True, mc)
                        self.screen.blit(nt, (row_rect.x + 40, row_rect.centery - nt.get_height() // 2))
                        self.screen.blit(st, (row_rect.right - st.get_width() - 8,
                                              row_rect.centery - st.get_height() // 2))
                    else:
                        empty_t = self.font_small.render("---", True, (60, 70, 100))
                        self.screen.blit(empty_t, (row_rect.x + 40, row_rect.centery - empty_t.get_height() // 2))
                    sy += row_h

            self.draw_centered_btn(HEIGHT - 170, "< BACK", (140, 35, 35), (mx, my))

            # Debug: show how many packets received from MCU
            with self._lb_lock:
                rcv = self._lb_received
            dbg = self.font_hint.render(
                f"MCU packets: {rcv}/5  |  entries: {len(self.best_scores)}",
                True, (40, 55, 80))
            self.screen.blit(dbg, dbg.get_rect(centerx=WIDTH // 2, y=HEIGHT - 140))

        # ── PAUSE ─────────────────────────────────────────────────────────────
        elif self.state == "PAUSE":
            dim = pygame.Surface((WIDTH, HEIGHT), pygame.SRCALPHA)
            dim.fill((0, 0, 0, 160))
            self.screen.blit(dim, (0, 0))

            bw, bh = 280, 52
            bx = WIDTH // 2 - bw // 2
            panel_h = 240
            panel = pygame.Rect(WIDTH // 2 - bw // 2 - 30, HEIGHT // 2 - panel_h // 2,
                                bw + 60, panel_h)
            self._draw_panel_bg(panel, alpha=230, border_color=ACCENT, corner=16)

            self._glow_text("PAUSED", self.font_big, ACCENT, (0, 80, 160),
                            self.screen, (WIDTH // 2, panel.y + 36))

            sc_t = self.font_hint.render(f"score:  {self.score:,}", True, (80, 150, 220))
            self.screen.blit(sc_t, sc_t.get_rect(centerx=WIDTH // 2, y=panel.y + 70))

            sep = pygame.Surface((bw, 1), pygame.SRCALPHA)
            for xi in range(bw):
                a = int(180 * math.sin(math.pi * xi / bw))
                sep.set_at((xi, 0), (*ACCENT, a))
            self.screen.blit(sep, (bx, panel.y + 94))

            exit_rect   = pygame.Rect(bx, panel.y + 110, bw, bh)
            cancel_rect = pygame.Rect(bx, panel.y + 174, bw, bh)
            self.draw_button(self.screen, exit_rect,   "EXIT TO MENU",
                             (140, 80, 10), self.font_small, exit_rect.collidepoint(mx, my))
            self.draw_button(self.screen, cancel_rect, "CONTINUE",
                             (20, 100, 160), self.font_small, cancel_rect.collidepoint(mx, my))

        # ── PLAYING ───────────────────────────────────────────────────────────
        elif self.state == "PLAYING":
            # Top HUD bar
            hud_s = pygame.Surface((WIDTH, 56), pygame.SRCALPHA)
            hud_s.fill((4, 6, 18, 215))
            self.screen.blit(hud_s, (0, 0))
            pygame.draw.line(self.screen, (*ACCENT, 80), (0, 56), (WIDTH, 56), 1)

            # Player name (left)
            pn = self.font_hint.render(
                f">> {self.clean_text(self.player_name)}",
                True, (80, 160, 240))
            self.screen.blit(pn, (12, 20))

            # Score — center
            score_label = self.font_hint.render("SCORE", True, (60, 90, 140))
            score_val   = self.font_score.render(f"{self.score:,}", True, ACCENT)
            self.screen.blit(score_label,
                             score_label.get_rect(centerx=WIDTH // 2, bottom=20))
            self.screen.blit(score_val,
                             score_val.get_rect(centerx=WIDTH // 2, top=18))

            # SAVE button (right side, second from right)
            save_rect = pygame.Rect(WIDTH - 216, 8, 96, 38)
            self.draw_button(self.screen, save_rect, "[ SAVE ]", (20, 100, 60),
                             self.font_small, save_rect.collidepoint(mx, my))

            # MENU button (rightmost)
            menu_rect = pygame.Rect(WIDTH - 110, 8, 96, 38)
            self.draw_button(self.screen, menu_rect, "< MENU", (20, 60, 140),
                             self.font_small, menu_rect.collidepoint(mx, my))

            # Board shadow frame
            board_rect = pygame.Rect(OFFSET_X - 6, OFFSET_Y - 6,
                                     BOARD_SIZE * CELL_SIZE + 12, BOARD_SIZE * CELL_SIZE + 12)
            self._draw_panel_bg(board_rect, alpha=160,
                                border_color=(0, 120, 200), corner=14)

            # Hint logic
            if not self.busy and not self.exiting_game and self.connected and self.is_board_stable():
                if time.time() - self.last_action_time > 10:
                    if not self.hint_cells:
                        self.hint_cells = self.find_possible_move()
                else:
                    self.hint_cells = None
            else:
                self.last_action_time = time.time()
                self.hint_cells = None

            # Grid cells
            for r in range(BOARD_SIZE):
                for c in range(BOARD_SIZE):
                    x = OFFSET_X + c * CELL_SIZE
                    y = OFFSET_Y + r * CELL_SIZE
                    # Cell bg
                    cell_bg = pygame.Surface((CELL_SIZE, CELL_SIZE), pygame.SRCALPHA)
                    pygame.draw.rect(cell_bg, (12, 18, 45, 200),
                                     cell_bg.get_rect(), border_radius=10)
                    self.screen.blit(cell_bg, (x, y))

                    cell = self.board[r][c]
                    cell.update()
                    cell.draw(self.screen)

                    if self.selected == (r, c):
                        sel_surf = pygame.Surface((CELL_SIZE, CELL_SIZE), pygame.SRCALPHA)
                        pygame.draw.rect(sel_surf, (0, 220, 255, 55),
                                         sel_surf.get_rect(), border_radius=10)
                        pygame.draw.rect(sel_surf, (0, 220, 255, 220),
                                         sel_surf.get_rect(), 2, border_radius=10)
                        self.screen.blit(sel_surf, (x, y))

            # Hint highlight
            if self.hint_cells:
                t = time.time()
                pulse = 0.4 + 0.6 * abs(math.sin(t * 2.5))
                for (hr, hc) in self.hint_cells:
                    hx = OFFSET_X + hc * CELL_SIZE
                    hy = OFFSET_Y + hr * CELL_SIZE
                    hs = pygame.Surface((CELL_SIZE, CELL_SIZE), pygame.SRCALPHA)
                    pygame.draw.rect(hs, (255, 220, 0, int(60 * pulse)),
                                     hs.get_rect(), border_radius=10)
                    pygame.draw.rect(hs, (255, 220, 0, int(220 * pulse)),
                                     hs.get_rect(), 2, border_radius=10)
                    self.screen.blit(hs, (hx, hy))

            # Particles & floating texts
            for pt in self.particles[:]:
                pt.update(); pt.draw(self.screen)
                if pt.life <= 0: self.particles.remove(pt)
            for ft in self.floating_texts[:]:
                ft.update(); ft.draw(self.screen)
                if ft.life <= 0: self.floating_texts.remove(ft)

            # Busy indicator
            if self.busy:
                bt = self.font_hint.render("...", True,
                                           (0, int(180 + 75 * abs(math.sin(time.time() * 5))), 255))
                self.screen.blit(bt, bt.get_rect(centerx=WIDTH // 2,
                                                  y=OFFSET_Y + BOARD_SIZE * CELL_SIZE + 10))

        # ── Bottom connection panel ────────────────────────────────────────────
        panel_y = HEIGHT - 70
        pb = pygame.Surface((WIDTH, 70), pygame.SRCALPHA)
        pb.fill((4, 6, 18, 230))
        self.screen.blit(pb, (0, panel_y))
        pygame.draw.line(self.screen, (*ACCENT, 60), (0, panel_y), (WIDTH, panel_y), 1)

        port_name = "NO PORT DETECTED"
        text_col  = (60, 70, 110)
        if self.available_ports:
            self.selected_port_index = self.selected_port_index % len(self.available_ports)
            info   = self.available_ports[self.selected_port_index]
            device = info["device"]
            if self.connected and self.ser and hasattr(self.ser, "port") and self.ser.port == device:
                port_name = f"{device}  [ACTIVE]"
                text_col  = (0, 255, 150)
            elif info["is_board"]:
                port_name = f"{device}  [STM32 DETECTED]"
                text_col  = (0, 200, 255)
            else:
                port_name = device
                text_col  = (130, 140, 170)

        port_txt = self.font_hint.render(port_name, True, text_col)
        txt_cx   = (self.rect_left.right + self.rect_right.left) // 2
        self.screen.blit(port_txt, port_txt.get_rect(centerx=txt_cx, centery=panel_y + 35))

        # Status dot
        dot_col = (0, 255, 150) if self.connected else (255, 60, 60)
        pulse_r = int(4 + 2 * abs(math.sin(time.time() * 2)))
        pygame.gfxdraw.filled_circle(self.screen,
                                     self.rect_right.right + 14, panel_y + 35,
                                     pulse_r, (*dot_col, 200))
        pygame.gfxdraw.aacircle(self.screen,
                                 self.rect_right.right + 14, panel_y + 35,
                                 pulse_r, dot_col)

        self.draw_button(self.screen, self.rect_left,  "<", (20, 60, 120), self.font_small,
                         self.rect_left.collidepoint(mx, my))
        self.draw_button(self.screen, self.rect_right, ">", (20, 60, 120), self.font_small,
                         self.rect_right.collidepoint(mx, my))

        btn_color = (10, 150, 80) if not self.connected else (180, 30, 30)
        btn_text  = "CONNECT"     if not self.connected else "DISCONNECT"
        self.draw_button(self.screen, self.rect_conn, btn_text, btn_color,
                         self.font_small, self.rect_conn.collidepoint(mx, my))

        pygame.display.flip()

    # ── Main loop ─────────────────────────────────────────────────────────────

    def run(self):
        global WIDTH, HEIGHT
        self._pending_disconnect = False

        while self.running:
            self.process_uart()
            self.draw()

            for e in pygame.event.get():
                if e.type == pygame.QUIT:
                    self.running = False

                elif e.type == pygame.VIDEORESIZE:
                    if not self.is_fullscreen:
                        WIDTH, HEIGHT = e.w, e.h
                        self.screen = pygame.display.set_mode((WIDTH, HEIGHT), pygame.RESIZABLE)
                        self.update_layout()

                elif e.type == pygame.KEYDOWN:
                    self.last_action_time = time.time()
                    self.hint_cells = None
                    self.handle_keydown(e.key, e.unicode)
                    if e.key == pygame.K_F11:
                        self.toggle_fullscreen()
                    elif e.key == pygame.K_ESCAPE:
                        if self.is_fullscreen and self.state == "PLAYING":
                            self.toggle_fullscreen()
                        elif self.state == "PLAYING" and not self.exiting_game:
                            self.state = "PAUSE"
                        elif self.state == "PAUSE":
                            self.state = "PLAYING"

                elif e.type == pygame.MOUSEBUTTONDOWN and e.button == 1:
                    self.click(e.pos)

                elif e.type == pygame.USEREVENT + 1:
                    # BUG FIX #10: only ping MCU while actively playing
                    if self.connected and self.state == "PLAYING" and not self.exiting_game:
                        self.send(0x15)

            self.clock.tick(60)

        pygame.quit()


if __name__ == "__main__":
    Match3Game().run()