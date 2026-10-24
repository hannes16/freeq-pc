"""FREEQ desktop port using pygame and keyboard controls."""

from __future__ import annotations

import json
import math
import os
import sys
from pathlib import Path
from typing import Any

os.environ.setdefault("PYGAME_HIDE_SUPPORT_PROMPT", "1")

import pygame

try:
    from .engine import StoryEngine, load_game_data
    from .access_audio import AccessAudio, NAME_CLIPS
    from .screen_reader import ScreenReader
except ImportError:  # Direct script launch: python freeq_port/freeq.py
    from engine import StoryEngine, load_game_data
    from access_audio import AccessAudio, NAME_CLIPS
    from screen_reader import ScreenReader


if getattr(sys, "frozen", False):
    ROOT = Path(getattr(sys, "_MEIPASS")) / "freeq_port"
    SAVE_FILE = Path(os.environ.get("LOCALAPPDATA", Path.home())) / "FREEQ Python Port" / "savegame.json"
else:
    ROOT = Path(__file__).resolve().parent
    SAVE_FILE = ROOT / "savegame.json"
DATA_DIR = ROOT / "data"
WIDTH, HEIGHT = 1024, 576
CYAN = (47, 235, 225)
PALE = (216, 245, 241)
DARK = (3, 18, 22)
RED = (244, 76, 91)
NODE_POSITIONS = [
    (165, 155), (395, 150), (625, 155), (855, 150),
    (170, 300), (400, 295), (630, 300), (850, 295),
    (175, 435), (405, 430), (635, 435), (845, 430),
]
CREDITS_SPEECH = (
    "Transmission complete. You reached the end of FREEQ. "
    "Original game copyright 2013 Psychic Bunny, Incorporated. "
    "Python port generated from the supplied iOS build. "
    "Press Enter or Escape to return to the main menu. "
    "Press R to read the credits again."
)
HELP_SPEECH = (
    "Keyboard controls. "
    "W A S D or arrow keys: move the receiver through the Aether. "
    "Tab or Shift plus Tab: jump to the next or previous signal. "
    "Enter or E: intercept, select, or confirm. "
    "Escape: cancel or go back. "
    "N opens notes. L opens achievements. "
    "Space: pause or resume transmission audio. "
    "R replays transmission audio. S skips transmission audio. "
    "F2 toggles voice and positional accessibility audio. "
    "F11 toggles full screen. "
    "Press F1, Enter, or Escape to close help. "
    "While this help screen is open, press R to read these controls again."
)


class FreeqGame:
    def __init__(self) -> None:
        pygame.init()
        try:
            pygame.mixer.init(frequency=44100)
        except pygame.error:
            pass
        self.screen = pygame.display.set_mode((WIDTH, HEIGHT), pygame.RESIZABLE)
        self.canvas = pygame.Surface((WIDTH, HEIGHT))
        pygame.display.set_caption("FREEQ — Python Port")
        self.clock = pygame.time.Clock()
        self.font = pygame.font.SysFont("segoeui", 24)
        self.small = pygame.font.SysFont("segoeui", 18)
        self.tiny = pygame.font.SysFont("consolas", 14)
        self.title_font = pygame.font.SysFont("segoeui", 64, bold=True)
        self.heading = pygame.font.SysFont("segoeui", 34, bold=True)

        self.restored_content = os.environ.get("FREEQ_RESTORED_CONTENT", "1") != "0"
        self.data = load_game_data(
            DATA_DIR / "game_data.json",
            restored_content=self.restored_content,
        )
        self.engine = StoryEngine(self.data)
        self.media = json.loads((DATA_DIR / "media_manifest.json").read_text(encoding="utf-8"))
        self.images = self._load_images()
        self.state = "menu"
        self.help_return_state = "menu"
        self.menu_index = 0
        self.running = True
        self.fullscreen = False
        self.player = pygame.Vector2(WIDTH / 2, HEIGHT / 2)
        self.focus_index = 0
        self.current_signal: dict[str, Any] | None = None
        self.connections: list[dict[str, Any]] = []
        self.connection_index = 0
        self.confirm_index = 0
        self.node_positions: dict[int, tuple[int, int]] = {}
        self.playback_kind = ""
        self.playback_ref = ""
        self.playback_started = 0
        self.playback_paused = False
        self.scroll = 0
        self.status = ""
        self.status_until = 0
        self.beacon_key = ""
        self.beacon_channel = pygame.mixer.Channel(1) if pygame.mixer.get_init() else None
        self.sound_cache: dict[str, pygame.mixer.Sound] = {}
        self.access = AccessAudio(self.audio_path)
        self.screen_reader = ScreenReader()
        self.pending_screen_reader_announcement = ""
        self.announced_signal_id: int | None = None
        self.access.speak(["mainmenu", "newgame"])

    def _load_images(self) -> dict[str, pygame.Surface]:
        result = {}
        for name in ("Freeq_UI_MainMenu_BG", "Freeq_UI_BG_blue", "Freeq_UI_BG_log", "Freeq_UI_BG_red"):
            path = ROOT / "assets" / "images" / f"{name}.png"
            if path.exists():
                image = pygame.image.load(path).convert()
                result[name] = pygame.transform.smoothscale(image, (WIDTH, HEIGHT))
        return result

    def audio_path(self, reference: str) -> Path | None:
        key = reference.replace("\\", "/").split("/")[-1].lower()
        relative = self.media.get("audio", {}).get(key)
        return ROOT / relative if relative else None

    def play_music(self, reference: str) -> bool:
        path = self.audio_path(reference)
        if not path or not path.exists() or not pygame.mixer.get_init():
            self.status_message(f"Audio unavailable: {reference}")
            return False
        try:
            if self.beacon_channel:
                self.beacon_channel.stop()
            pygame.mixer.music.load(str(path))
            pygame.mixer.music.play()
            self.playback_ref = reference
            self.playback_started = pygame.time.get_ticks()
            self.playback_paused = False
            return True
        except pygame.error as exc:
            self.status_message(f"Could not play audio: {exc}")
            return False

    def play_beacon(self, signal: dict[str, Any] | None) -> None:
        # The original access mode suppresses the caller soundtrack used as a
        # beacon. Spoken caller names, axis guides, and brown-noise proximity
        # supply the accessible locator instead.
        if self.access.enabled or not signal or not self.beacon_channel or self.state != "aether":
            if self.beacon_channel:
                self.beacon_channel.stop()
            self.beacon_key = ""
            return
        reference = signal.get("soundtrack", "")
        key = reference.lower()
        if key == self.beacon_key:
            return
        self.beacon_channel.stop()
        path = self.audio_path(reference)
        if not path:
            return
        try:
            sound = self.sound_cache.get(key)
            if sound is None:
                sound = pygame.mixer.Sound(str(path))
                self.sound_cache[key] = sound
            self.beacon_channel.play(sound, loops=-1)
            self.beacon_channel.set_volume(0.4)
            self.beacon_key = key
        except pygame.error:
            self.beacon_key = ""

    def status_message(self, message: str, duration: int = 3000) -> None:
        self.status = message
        self.status_until = pygame.time.get_ticks() + duration

    def new_game(self) -> None:
        self.engine.reset()
        self.player.update(WIDTH / 2, HEIGHT / 2)
        self.focus_index = 0
        self.node_positions.clear()
        self.sync_node_positions()
        self.state = "aether"
        self.save()
        self.access.speak(["aethermode"])
        self.check_hijack()

    def continue_game(self) -> None:
        if not SAVE_FILE.exists():
            self.status_message("No saved game found.")
            return
        try:
            self.engine.load_save(json.loads(SAVE_FILE.read_text(encoding="utf-8")))
            self.node_positions.clear()
            self.sync_node_positions()
            if self.engine.game_over:
                self.enter_credits()
            else:
                self.state = "aether"
                self.access.speak(["aethermode"])
            self.check_hijack()
        except (OSError, ValueError, TypeError) as exc:
            self.status_message(f"Could not load save: {exc}")

    def save(self) -> None:
        try:
            SAVE_FILE.parent.mkdir(parents=True, exist_ok=True)
            SAVE_FILE.write_text(json.dumps(self.engine.to_save(), indent=2), encoding="utf-8")
        except OSError as exc:
            self.status_message(f"Could not save: {exc}")

    def check_hijack(self) -> None:
        if self.state == "aether" and self.engine.queued_hijack:
            self.access.stop_guides()
            self.access.stop_voice()
            self.access.play_sfx("bwee")
            self.current_signal = self.engine.queued_hijack
            self.engine.begin_hijack(self.current_signal)
            self.playback_kind = "hijack"
            self.state = "playback"
            if not self.play_music(self.current_signal.get("soundtrack", "")):
                self.finish_playback()

    def finish_playback(self) -> None:
        pygame.mixer.music.stop()
        signal = self.current_signal
        if not signal:
            self.state = "aether"
            return
        if self.playback_kind == "hijack":
            self.connections = self.engine.eligible_connections(signal)
            if self.connections:
                self.connection_index = self._preferred_index(signal)
                self.state = "connections"
                self.announce_switchboard()
            elif signal.get("connections"):
                # Unity opens a switchboard with zero nodes for this rare
                # conditional softlock. Preserve the blocked story state but
                # display it safely instead of indexing an empty list.
                self.state = "blocked"
                self.access.stop_voice()
            else:
                self.engine.finish_hijack_without_connection(signal)
                self.current_signal = None
                self.save()
                if self.engine.game_over:
                    self.enter_credits()
                else:
                    self.state = "aether"
                    self.access.speak(["aethermode"])
                self.check_hijack()
        elif self.playback_kind == "connection":
            connection = self.connections[self.connection_index]
            self.engine.finish_connection(signal, connection, hijack=bool(signal.get("hijack")))
            self.current_signal = None
            self.connections = []
            self.save()
            if self.engine.game_over:
                self.enter_credits()
            else:
                self.state = "aether"
                self.access.speak(["aethermode"])
            self.check_hijack()

    def enter_credits(self) -> None:
        """Enter the credits and read all visible text through Prism once."""
        self.state = "credits"
        self.access.stop_voice()
        self.access.stop_guides()
        self.access.stop_environment()
        self.pending_screen_reader_announcement = ""
        self.screen_reader.speak(CREDITS_SPEECH)

    def _preferred_index(self, signal: dict[str, Any]) -> int:
        preferred = signal.get("preferred_connection", "")
        for index, item in enumerate(self.connections):
            if item.get("name") == preferred:
                return index
        return 0

    def begin_intercept(self, signal: dict[str, Any]) -> None:
        self.play_beacon(None)
        self.access.stop_guides()
        caller = signal.get("user_name", "")
        self.access.play_sfx("bwee")
        clips = ["intercepted-id"]
        name_clip = self.name_clip(caller)
        if name_clip:
            clips.append(name_clip)
        self.confirm_index = 0
        clips.append("yes")
        self.access.speak(clips)
        self.current_signal = signal
        self.state = "intercept_confirm"

    def accept_intercept(self) -> None:
        if not self.current_signal:
            return
        self.connections = self.engine.begin_normal_signal(self.current_signal)
        if not self.connections:
            self.engine.cancel_normal_signal(self.current_signal)
            self.status_message("No valid connections are available yet.")
            self.current_signal = None
            self.state = "aether"
            return
        self.connection_index = self._preferred_index(self.current_signal)
        self.state = "connections"
        self.announce_switchboard()

    def announce_switchboard(self) -> None:
        if not self.connections:
            return
        selected = self.connections[self.connection_index]
        clips = ["switchboardmode", "possible connections"]
        name_clip = self.name_clip(selected.get("name", ""))
        if name_clip:
            clips.append(name_clip)
        self.access.speak(clips)
        self.pending_screen_reader_announcement = ""

    def announce_connection_selection(self) -> None:
        if not self.connections:
            return
        selected = self.connections[self.connection_index]
        self.access.speak_name(selected.get("name", ""))
        self.pending_screen_reader_announcement = ""

    def flush_screen_reader_announcement(self) -> None:
        if not self.pending_screen_reader_announcement or not self.access.voice_idle():
            return
        announcement = self.pending_screen_reader_announcement
        self.pending_screen_reader_announcement = ""
        self.screen_reader.speak(announcement)

    def announce_connection_confirmation(self) -> None:
        if not self.current_signal or not self.connections:
            return
        connection = self.connections[self.connection_index]
        clips = ["confirmconnect"]
        caller = self.name_clip(self.current_signal.get("user_name", ""))
        callee = self.name_clip(connection.get("name", ""))
        if caller:
            clips.append(caller)
        if callee:
            clips.append(callee)
        clips.append("yes" if self.confirm_index == 0 else "no")
        self.access.speak(clips)

    def start_connection_audio(self) -> None:
        connection = self.connections[self.connection_index]
        self.access.stop_voice()
        self.access.play_sfx("bleep1")
        self.engine.record_connection_rewards(connection)
        self.playback_kind = "connection"
        self.state = "playback"
        if not self.play_music(connection.get("sound", "")):
            self.finish_playback()

    def cancel_connections(self) -> None:
        if self.current_signal and not self.current_signal.get("hijack"):
            self.engine.cancel_normal_signal(self.current_signal)
        self.current_signal = None
        self.connections = []
        self.state = "aether"
        self.access.speak(["aethermode"])
        self.check_hijack()

    def name_clip(self, name: str) -> str | None:
        return NAME_CLIPS.get(name.strip().lower())

    @staticmethod
    def connection_label(connection: dict[str, Any]) -> str:
        return connection.get("name", "Unknown")

    def announce_menu_selection(self) -> None:
        label = self.menu_options()[self.menu_index][0]
        clip = {
            "NEW GAME": "newgame",
            "CONTINUE": "continue",
            "HELP / CONTROLS": "help-controls",
            "QUIT": "exitmenu",
        }.get(label)
        if clip:
            self.access.speak([clip])

    def speak_current_note(self) -> None:
        if not self.engine.notes:
            return
        index = min(self.scroll, len(self.engine.notes) - 1)
        self.access.speak([f"l-{self.engine.notes[index]}"])

    def unlocked_achievement_names(self) -> list[str]:
        names = self.data.get("achievement_names", [])
        return [
            names[index] if 0 <= index < len(names) else f"Achievement {index}"
            for index in self.engine.achievements
        ]

    def open_achievements(self) -> None:
        self.scroll = 0
        self.state = "achievements"
        self.access.stop_voice()
        self.pending_screen_reader_announcement = ""
        names = self.unlocked_achievement_names()
        if names:
            self.screen_reader.speak(
                f"Achievements. {len(names)} unlocked. {names[0]}. "
                "Use Up and Down to move through achievements. "
                "Press R to repeat the current achievement."
            )
        else:
            self.screen_reader.speak(
                "Achievements. No achievements unlocked yet. Press L or Escape to close."
            )

    def speak_current_achievement(self) -> None:
        names = self.unlocked_achievement_names()
        if not names:
            self.screen_reader.speak("No achievements unlocked yet.")
            return
        self.scroll = min(self.scroll, len(names) - 1)
        self.screen_reader.speak(names[self.scroll])

    def sync_node_positions(self) -> None:
        """Keep existing nodes fixed and place new signals away from the tuner."""
        active_ids = {int(signal["path_id"]) for signal in self.engine.active}
        self.node_positions = {
            signal_id: position
            for signal_id, position in self.node_positions.items()
            if signal_id in active_ids
        }
        used = set(self.node_positions.values())
        for signal in self.engine.active:
            signal_id = int(signal["path_id"])
            if signal_id in self.node_positions:
                continue
            free_positions = [position for position in NODE_POSITIONS if position not in used]
            if not free_positions:
                break
            position = max(free_positions, key=self.player.distance_squared_to)
            self.node_positions[signal_id] = position
            used.add(position)

    def signal_position(self, signal: dict[str, Any]) -> tuple[int, int]:
        self.sync_node_positions()
        return self.node_positions[int(signal["path_id"])]

    def handle_event(self, event: pygame.event.Event) -> None:
        if event.type == pygame.QUIT:
            self.running = False
            return
        if event.type != pygame.KEYDOWN:
            return
        if event.key == pygame.K_F11:
            self.fullscreen = not self.fullscreen
            flags = pygame.FULLSCREEN if self.fullscreen else pygame.RESIZABLE
            self.screen = pygame.display.set_mode((WIDTH, HEIGHT), flags)
            return
        if event.key == pygame.K_F2:
            self.access.set_enabled(not self.access.enabled)
            self.status_message(f"Accessibility audio {'on' if self.access.enabled else 'off'}")
            return
        if event.key == pygame.K_F1:
            self.help_return_state = self.state
            self.state = "help"
            help_clip = {
                "aether": "aetherhelp",
                "connections": "switchboardhelp",
                "connection_confirm": "switchboardhelp",
                "playback": "playbackhelp",
            }.get(self.help_return_state, "help-controls")
            self.access.speak([help_clip])
            self.pending_screen_reader_announcement = HELP_SPEECH
            return

        if self.state == "menu":
            options = self.menu_options()
            if event.key in (pygame.K_UP, pygame.K_w):
                self.menu_index = (self.menu_index - 1) % len(options)
                self.access.play_sfx("bwomp1")
                self.announce_menu_selection()
            elif event.key in (pygame.K_DOWN, pygame.K_s):
                self.menu_index = (self.menu_index + 1) % len(options)
                self.access.play_sfx("bwomp1")
                self.announce_menu_selection()
            elif event.key in (pygame.K_RETURN, pygame.K_SPACE):
                options[self.menu_index][1]()
            elif event.key == pygame.K_ESCAPE:
                self.running = False
        elif self.state == "aether":
            if event.key == pygame.K_TAB and self.engine.active:
                self.focus_index = (self.focus_index + (-1 if event.mod & pygame.KMOD_SHIFT else 1)) % len(self.engine.active)
                signal = self.engine.active[self.focus_index]
                self.player.update(self.signal_position(signal))
                self.access.speak_name(signal.get("user_name", ""))
            elif event.key in (pygame.K_RETURN, pygame.K_e):
                signal = self.near_signal()
                if signal:
                    self.begin_intercept(signal)
            elif event.key == pygame.K_n:
                self.scroll = 0
                self.state = "notes"
                self.access.speak(["logmode"])
            elif event.key == pygame.K_l:
                self.open_achievements()
            elif event.key == pygame.K_ESCAPE:
                self.play_beacon(None)
                self.state = "menu"
                self.access.speak(["mainmenu"])
        elif self.state == "intercept_confirm":
            if event.key in (pygame.K_LEFT, pygame.K_RIGHT, pygame.K_UP, pygame.K_DOWN, pygame.K_TAB):
                self.confirm_index = 1 - self.confirm_index
                self.access.play_sfx("bwomp1")
                self.access.speak(["yes" if self.confirm_index == 0 else "no"])
            elif event.key == pygame.K_RETURN:
                if self.confirm_index == 0:
                    self.accept_intercept()
                else:
                    self.current_signal = None
                    self.state = "aether"
                    self.access.speak(["aethermode"])
            elif event.key == pygame.K_y:
                self.accept_intercept()
            elif event.key in (pygame.K_ESCAPE, pygame.K_n):
                self.current_signal = None
                self.state = "aether"
                self.access.speak(["aethermode"])
        elif self.state == "connections":
            if event.key in (pygame.K_LEFT, pygame.K_a, pygame.K_UP, pygame.K_w):
                self.connection_index = (self.connection_index - 1) % len(self.connections)
                self.access.play_sfx("bwomp1")
                self.announce_connection_selection()
            elif event.key in (pygame.K_RIGHT, pygame.K_d, pygame.K_DOWN, pygame.K_s, pygame.K_TAB):
                self.connection_index = (self.connection_index + 1) % len(self.connections)
                self.access.play_sfx("bwomp1")
                self.announce_connection_selection()
            elif event.key in (pygame.K_RETURN, pygame.K_e):
                self.confirm_index = 0
                self.state = "connection_confirm"
                self.announce_connection_confirmation()
            elif event.key == pygame.K_ESCAPE:
                self.cancel_connections()
        elif self.state == "connection_confirm":
            if event.key in (pygame.K_LEFT, pygame.K_RIGHT, pygame.K_UP, pygame.K_DOWN, pygame.K_TAB):
                self.confirm_index = 1 - self.confirm_index
                self.access.play_sfx("bwomp1")
                self.access.speak(["yes" if self.confirm_index == 0 else "no"])
            elif event.key == pygame.K_RETURN:
                if self.confirm_index == 0:
                    self.start_connection_audio()
                else:
                    self.state = "connections"
                    self.announce_connection_selection()
            elif event.key == pygame.K_y:
                self.start_connection_audio()
            elif event.key in (pygame.K_ESCAPE, pygame.K_n):
                self.state = "connections"
                self.announce_connection_selection()
        elif self.state == "playback":
            if event.key == pygame.K_s:
                self.access.speak(["skip"])
                self.finish_playback()
            elif event.key == pygame.K_r:
                self.access.speak(["repeat"])
                self.play_music(self.playback_ref)
            elif event.key == pygame.K_SPACE:
                if self.playback_paused:
                    pygame.mixer.music.unpause()
                else:
                    pygame.mixer.music.pause()
                    self.access.speak(["paused"])
                self.playback_paused = not self.playback_paused
        elif self.state in ("notes", "achievements"):
            if event.key in (pygame.K_ESCAPE, pygame.K_n, pygame.K_l):
                self.state = "aether"
            elif event.key in (pygame.K_DOWN, pygame.K_s, pygame.K_PAGEDOWN):
                if self.state == "notes":
                    self.scroll += 1
                    self.speak_current_note()
                else:
                    names = self.unlocked_achievement_names()
                    if names:
                        self.scroll = min(self.scroll + 1, len(names) - 1)
                    self.speak_current_achievement()
            elif event.key in (pygame.K_UP, pygame.K_w, pygame.K_PAGEUP):
                self.scroll = max(0, self.scroll - 1)
                if self.state == "notes":
                    self.speak_current_note()
                else:
                    self.speak_current_achievement()
            elif event.key == pygame.K_r and self.state == "achievements":
                self.speak_current_achievement()
        elif self.state == "help":
            if event.key in (pygame.K_ESCAPE, pygame.K_F1, pygame.K_RETURN):
                self.pending_screen_reader_announcement = ""
                self.state = self.help_return_state
                mode_clip = {
                    "aether": "aethermode",
                    "connections": "switchboardmode",
                    "playback": "playbackcontrols",
                    "menu": "mainmenu",
                }.get(self.state)
                if mode_clip:
                    self.access.speak([mode_clip])
            elif event.key == pygame.K_r:
                self.screen_reader.speak(HELP_SPEECH)
        elif self.state == "credits":
            if event.key in (pygame.K_ESCAPE, pygame.K_RETURN):
                self.state = "menu"
                self.access.speak(["mainmenu"])
            elif event.key == pygame.K_r:
                self.screen_reader.speak(CREDITS_SPEECH)
        elif self.state == "blocked":
            if event.key == pygame.K_ESCAPE:
                self.state = "menu"
                self.access.speak(["mainmenu"])

    def menu_options(self) -> list[tuple[str, Any]]:
        options = [("NEW GAME", self.new_game)]
        if SAVE_FILE.exists():
            options.append(("CONTINUE", self.continue_game))
        options.extend((("HELP / CONTROLS", self.open_help), ("QUIT", lambda: setattr(self, "running", False))))
        self.menu_index %= len(options)
        return options

    def open_help(self) -> None:
        self.help_return_state = self.state
        self.state = "help"
        self.access.speak(["help-controls"])
        self.pending_screen_reader_announcement = HELP_SPEECH

    def near_signal(self) -> dict[str, Any] | None:
        self.sync_node_positions()
        best = None
        best_distance = 90.0
        for index, signal in enumerate(self.engine.active):
            distance = self.player.distance_to(self.signal_position(signal))
            if distance < best_distance:
                best = signal
                best_distance = distance
                self.focus_index = index
        return best

    def update(self, dt: float) -> None:
        if self.state == "aether":
            self.sync_node_positions()
            keys = pygame.key.get_pressed()
            direction = pygame.Vector2(
                keys[pygame.K_d] + keys[pygame.K_RIGHT] - keys[pygame.K_a] - keys[pygame.K_LEFT],
                keys[pygame.K_s] + keys[pygame.K_DOWN] - keys[pygame.K_w] - keys[pygame.K_UP],
            )
            if direction.length_squared():
                self.player += direction.normalize() * 260 * dt
                self.player.x = min(970, max(54, self.player.x))
                self.player.y = min(515, max(95, self.player.y))
            near = self.near_signal()
            self.play_beacon(near)
            near_id = int(near["path_id"]) if near else None
            if near_id is not None and near_id != self.announced_signal_id:
                self.access.speak_name(near.get("user_name", ""))
            self.announced_signal_id = near_id
        guide_nodes = [
            (int(signal["path_id"]), self.signal_position(signal))
            for signal in self.engine.active
        ]
        self.access.update_guides(self.player, guide_nodes, active=self.state == "aether")
        self.access.update_environment(self.player, guide_nodes, active=self.state == "aether")
        self.access.update_voice()
        self.flush_screen_reader_announcement()
        if self.state == "playback" and not self.playback_paused:
            if pygame.time.get_ticks() - self.playback_started > 500 and not pygame.mixer.music.get_busy():
                self.finish_playback()
        if self.status and pygame.time.get_ticks() > self.status_until:
            self.status = ""

    def background(self, name: str = "Freeq_UI_BG_blue") -> None:
        image = self.images.get(name)
        self.canvas.blit(image, (0, 0)) if image else self.canvas.fill(DARK)

    def text(self, value: str, pos: tuple[int, int], *, font=None, color=PALE, center=False) -> pygame.Rect:
        surface = (font or self.font).render(value, True, color)
        rect = surface.get_rect(center=pos) if center else surface.get_rect(topleft=pos)
        self.canvas.blit(surface, rect)
        return rect

    def wrapped(self, value: str, rect: pygame.Rect, *, font=None, color=PALE, line_gap=5) -> int:
        font = font or self.font
        words = value.split()
        lines, line = [], ""
        for word in words:
            test = f"{line} {word}".strip()
            if font.size(test)[0] <= rect.width:
                line = test
            else:
                if line:
                    lines.append(line)
                line = word
        if line:
            lines.append(line)
        y = rect.y
        for item in lines:
            self.text(item, (rect.x, y), font=font, color=color)
            y += font.get_linesize() + line_gap
        return y

    def draw_header(self, title: str, subtitle: str = "") -> None:
        self.text(title, (40, 24), font=self.heading, color=CYAN)
        if subtitle:
            self.text(subtitle, (42, 67), font=self.small, color=PALE)
        pygame.draw.line(self.canvas, (*CYAN, 100), (40, 91), (984, 91), 1)

    def draw_yes_no_menu(self, y: int) -> None:
        for index, label in enumerate(("YES", "NO")):
            rect = pygame.Rect(330 + index * 200, y, 165, 54)
            selected = index == self.confirm_index
            color = CYAN if selected else (76, 135, 142)
            pygame.draw.rect(self.canvas, (3, 31, 36), rect, border_radius=7)
            pygame.draw.rect(self.canvas, color, rect, 3 if selected else 1, border_radius=7)
            prefix = "> " if selected else ""
            self.text(prefix + label, rect.center, color=color, center=True)

    def draw_menu(self) -> None:
        self.background("Freeq_UI_MainMenu_BG")
        self.text("FREEQ", (WIDTH // 2, 155), font=self.title_font, color=CYAN, center=True)
        self.text("PYTHON DESKTOP PORT", (WIDTH // 2, 205), font=self.small, center=True)
        for index, (label, _) in enumerate(self.menu_options()):
            color = CYAN if index == self.menu_index else PALE
            prefix = ">  " if index == self.menu_index else "   "
            self.text(prefix + label, (WIDTH // 2, 295 + index * 48), color=color, center=True)
        access = "ON" if self.access.enabled else "OFF"
        self.text(f"↑/↓ select  •  Enter confirm  •  F2 access audio {access}  •  F11 fullscreen", (WIDTH // 2, 535), font=self.tiny, center=True)

    def draw_aether(self) -> None:
        self.background()
        act = min(self.engine.act_index + 1, 3)
        self.draw_header("AETHER", f"ACT {act}   •   MASK {self.engine.mask:#010x}")
        t = pygame.time.get_ticks() / 1000
        for index, signal in enumerate(self.engine.active):
            x, y = self.signal_position(signal)
            radius = 28 + int(math.sin(t * 2.2 + index) * 4)
            near = self.player.distance_to((x, y)) < 90
            color = CYAN if near else (60, 135, 145)
            pygame.draw.circle(self.canvas, color, (x, y), radius, 2)
            pygame.draw.circle(self.canvas, (*color[:3],), (x, y), 5)
            self.text(signal.get("user_name") or "UNKNOWN", (x, y + 47), font=self.small, color=color, center=True)
        pygame.draw.circle(self.canvas, PALE, self.player, 10, 2)
        pygame.draw.line(self.canvas, PALE, self.player + (-16, 0), self.player + (16, 0), 1)
        pygame.draw.line(self.canvas, PALE, self.player + (0, -16), self.player + (0, 16), 1)
        signal = self.near_signal()
        if signal:
            self.text(f"ENTER: INTERCEPT {signal.get('user_name') or signal.get('name')}", (WIDTH // 2, 505), color=CYAN, center=True)
        else:
            self.text("WASD / ARROWS move   •   TAB jump between signals", (WIDTH // 2, 505), font=self.small, center=True)
        access = "ON" if self.access.enabled else "OFF"
        self.text(f"N notes   •   L achievements   •   F1 help   •   F2 access audio {access}   •   Esc menu", (WIDTH // 2, 545), font=self.tiny, center=True)

    def draw_intercept_confirm(self) -> None:
        self.background("Freeq_UI_BG_red")
        self.draw_header("INTERCEPT TRANSMISSION")
        signal = self.current_signal or {}
        self.text(signal.get("user_name") or "UNKNOWN CALLER", (WIDTH // 2, 225), font=self.heading, color=CYAN, center=True)
        self.text(signal.get("name", ""), (WIDTH // 2, 272), center=True)
        self.text("Intercept this transmission?", (WIDTH // 2, 360), center=True)
        self.draw_yes_no_menu(400)
        self.text("Arrows / Tab select   •   Enter confirm   •   Y/N shortcuts", (WIDTH // 2, 492), font=self.small, center=True)

    def draw_connections(self) -> None:
        self.background()
        caller = (self.current_signal or {}).get("user_name", "UNKNOWN")
        self.draw_header("SWITCHBOARD", f"Choose a connection for {caller}")
        count = len(self.connections)
        for index, connection in enumerate(self.connections):
            angle = -math.pi / 2 + math.tau * index / max(1, count)
            x = WIDTH // 2 + int(math.cos(angle) * 265)
            y = 320 + int(math.sin(angle) * 150)
            selected = index == self.connection_index
            color = CYAN if selected else (82, 145, 151)
            pygame.draw.circle(self.canvas, color, (x, y), 40 if selected else 30, 2)
            self.text(self.connection_label(connection), (x, y), font=self.small, color=color, center=True)
        selected = self.connections[self.connection_index]
        self.text(f"CONNECT WITH {self.connection_label(selected)}", (WIDTH // 2, 520), color=CYAN, center=True)
        self.text("←/→ choose   •   Enter connect   •   Esc return to Aether", (WIDTH // 2, 552), font=self.tiny, center=True)

    def draw_connection_confirm(self) -> None:
        self.background("Freeq_UI_BG_red")
        caller = (self.current_signal or {}).get("user_name", "Unknown")
        target = self.connection_label(self.connections[self.connection_index])
        self.draw_header("CONFIRM CONNECTION")
        self.text("Did you want to connect", (WIDTH // 2, 215), center=True)
        self.text(caller, (WIDTH // 2, 270), font=self.heading, color=CYAN, center=True)
        self.text("with", (WIDTH // 2, 318), center=True)
        self.text(target + "?", (WIDTH // 2, 370), font=self.heading, color=CYAN, center=True)
        self.draw_yes_no_menu(410)
        self.text("Arrows / Tab select   •   Enter confirm   •   Y/N shortcuts", (WIDTH // 2, 500), font=self.small, center=True)

    def draw_playback(self) -> None:
        self.background("Freeq_UI_BG_red" if self.playback_kind == "hijack" else "Freeq_UI_BG_blue")
        heading = "RADIO HIJACK" if self.playback_kind == "hijack" else "INTERCEPTED TRANSMISSION"
        self.draw_header(heading)
        caller = (self.current_signal or {}).get("user_name") or "UNKNOWN"
        self.text(caller, (WIDTH // 2, 190), font=self.heading, color=RED if self.playback_kind == "hijack" else CYAN, center=True)
        center = (WIDTH // 2, 325)
        t = pygame.time.get_ticks() / 1000
        for ring in range(5):
            radius = 34 + ring * 25 + int(math.sin(t * 3 + ring) * 7)
            color = RED if self.playback_kind == "hijack" else CYAN
            pygame.draw.circle(self.canvas, color, center, radius, 2)
        paused = "PAUSED" if self.playback_paused else "PLAYING"
        self.text(paused, (WIDTH // 2, 470), color=CYAN, center=True)
        self.text("SPACE pause   •   R replay   •   S skip", (WIDTH // 2, 535), font=self.small, center=True)

    def draw_notes(self) -> None:
        self.background("Freeq_UI_BG_log")
        self.draw_header("LOG", "Recovered notes from intercepted transmissions")
        note_map = self.data.get("notes", {})
        entries = [(key, note_map.get(key, key)) for key in self.engine.notes]
        if not entries:
            self.text("No new notes.", (60, 135))
        y = 120
        for index, (key, description) in enumerate(entries[self.scroll : self.scroll + 5], start=self.scroll + 1):
            self.text(f"{index:02d}", (55, y), font=self.small, color=CYAN)
            y = self.wrapped(description, pygame.Rect(100, y, 840, 80), font=self.small)
            y += 22
        self.text("↑/↓ scroll   •   N or Esc close", (WIDTH // 2, 548), font=self.tiny, center=True)

    def draw_achievements(self) -> None:
        self.background("Freeq_UI_BG_log")
        self.draw_header("ACHIEVEMENTS", f"Unlocked {len(self.engine.achievements)}")
        unlocked = self.unlocked_achievement_names()
        if not unlocked:
            self.text("No achievements unlocked yet.", (60, 135))
        for row, name in enumerate(unlocked[self.scroll : self.scroll + 10]):
            self.text("◆", (70, 125 + row * 39), color=CYAN)
            self.text(name, (105, 120 + row * 39), font=self.small)
        self.text("↑/↓ select   •   R repeat   •   L or Esc close", (WIDTH // 2, 548), font=self.tiny, center=True)

    def draw_help(self) -> None:
        self.background()
        self.draw_header("KEYBOARD CONTROLS")
        controls = [
            ("WASD / ARROWS", "Move the receiver through the Aether"),
            ("TAB / SHIFT+TAB", "Jump to next / previous signal"),
            ("ENTER or E", "Intercept, select, or confirm"),
            ("ESC", "Cancel or go back"),
            ("N / L", "Open notes / achievements"),
            ("SPACE", "Pause or resume transmission audio"),
            ("R / S", "Replay / skip transmission audio"),
            ("F2", "Toggle voice and positional accessibility audio"),
            ("F11", "Toggle fullscreen"),
        ]
        for row, (key, action) in enumerate(controls):
            y = 112 + row * 43
            self.text(key, (90, y), font=self.small, color=CYAN)
            self.text(action, (330, y), font=self.small)
        self.text("F1 / Enter / Esc to close", (WIDTH // 2, 535), font=self.small, center=True)

    def draw_credits(self) -> None:
        self.background("Freeq_UI_MainMenu_BG")
        self.text("TRANSMISSION COMPLETE", (WIDTH // 2, 145), font=self.heading, color=CYAN, center=True)
        self.text("You reached the end of FREEQ.", (WIDTH // 2, 235), center=True)
        self.text("Original game © 2013 Psychic Bunny, Inc.", (WIDTH // 2, 330), font=self.small, center=True)
        self.text("Python port generated from the supplied iOS build.", (WIDTH // 2, 365), font=self.small, center=True)
        self.text("Enter / Esc return to menu", (WIDTH // 2, 495), font=self.small, center=True)

    def draw_blocked(self) -> None:
        self.background("Freeq_UI_BG_red")
        self.draw_header("NO VALID CONNECTION")
        self.text("This rare decision history reaches an original FREEQ", (WIDTH // 2, 235), center=True)
        self.text("switchboard state with no eligible destination.", (WIDTH // 2, 272), center=True)
        self.text("The story cannot advance from this state.", (WIDTH // 2, 340), color=RED, center=True)
        self.text("Esc returns to the main menu", (WIDTH // 2, 490), font=self.small, center=True)

    def draw(self) -> None:
        draw_method = getattr(self, f"draw_{self.state}")
        draw_method()
        if self.status:
            surface = self.small.render(self.status, True, PALE)
            rect = surface.get_rect(center=(WIDTH // 2, HEIGHT - 28))
            panel = rect.inflate(28, 16)
            pygame.draw.rect(self.canvas, (5, 15, 18), panel, border_radius=5)
            pygame.draw.rect(self.canvas, CYAN, panel, 1, border_radius=5)
            self.canvas.blit(surface, rect)
        target_size = self.screen.get_size()
        if target_size == (WIDTH, HEIGHT):
            self.screen.blit(self.canvas, (0, 0))
        else:
            scale = min(target_size[0] / WIDTH, target_size[1] / HEIGHT)
            size = (int(WIDTH * scale), int(HEIGHT * scale))
            scaled = pygame.transform.smoothscale(self.canvas, size)
            self.screen.fill((0, 0, 0))
            self.screen.blit(scaled, ((target_size[0] - size[0]) // 2, (target_size[1] - size[1]) // 2))
        pygame.display.flip()

    def run(self) -> None:
        while self.running:
            dt = min(self.clock.tick(60) / 1000.0, 0.05)
            for event in pygame.event.get():
                self.handle_event(event)
            self.update(dt)
            self.draw()
        pygame.quit()


if __name__ == "__main__":
    FreeqGame().run()

