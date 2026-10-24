"""Accessibility and positional audio translated from FREEQ's Unity systems."""

from __future__ import annotations

from collections import deque
from pathlib import Path
from typing import Callable, Iterable

import pygame


NAME_CLIPS = {
    "amy": "amy",
    "vincent": "vincent",
    "james": "james",
    "max": "max",
    "luigi": "luigi",
    "jen": "jen",
    "1955": "y1955",
    "1985": "y1985",
    "2015": "y2015",
    "percy": "percy",
    "louise": "louise",
    "percy (past)": "percy-p",
    "louise (past)": "louise-p",
    "island radio": "islandradio",
    "james (past)": "james-p",
    "pat": "pat",
    "pat (past)": "pat-p",
    "jen (past)": "jen-p",
    "layla": "layla",
    "lars": "lars",
    "radio hijack": "radiohijack",
    "radio tuner": "radiotuner",
    "vincent's broadcast": "vincent-broadcast",
    "island times": "island-times",
    "mayor's office": "mayorsoffice",
    "radio broadcast": "radio-braodcast",
    "pie in the sky": "pieinthesky",
    "james frost": "james-frost",
    "open mic": "openmic",
    "the device": "device",
    "tower": "tower",
    "invention": "invention",
    "radio station": "radiostation",
    "amy's phone": "amysphone",
    "nothing": "nothing",
    "amy (past)": "amy-p",
    "radio theater of wonders": "radiotheater",
    "vincent (past)": "vincent-p",
    "luigi (past)": "luigi-p",
}


class AccessAudio:
    """Owns voice, SFX, and the two original alignment-guide channels."""

    GUIDE_RANGE = 280.0
    AXIS_LOCK_DISTANCE = 20.0
    NODE_LOCK_DISTANCE = 90.0
    LOCK_REPEAT_MS = 4000

    def __init__(self, resolver: Callable[[str], Path | None]) -> None:
        self.resolver = resolver
        self.enabled = True
        self.cache: dict[str, pygame.mixer.Sound] = {}
        self.voice_queue: deque[str] = deque()
        self.voice = pygame.mixer.Channel(2) if pygame.mixer.get_init() else None
        self.sfx = pygame.mixer.Channel(3) if pygame.mixer.get_init() else None
        self.horizontal = pygame.mixer.Channel(4) if pygame.mixer.get_init() else None
        self.vertical = pygame.mixer.Channel(5) if pygame.mixer.get_init() else None
        self.ambient = pygame.mixer.Channel(6) if pygame.mixer.get_init() else None
        self.proximity = pygame.mixer.Channel(7) if pygame.mixer.get_init() else None
        self.x_locked = False
        self.y_locked = False
        self.locked_signal: int | None = None
        self.last_lock_ms = 0

    def sound(self, reference: str) -> pygame.mixer.Sound | None:
        key = reference.lower()
        if key in self.cache:
            return self.cache[key]
        path = self.resolver(reference)
        if not path:
            return None
        try:
            result = pygame.mixer.Sound(str(path))
        except pygame.error:
            return None
        self.cache[key] = result
        return result

    def set_enabled(self, enabled: bool, *, announce: bool = True) -> None:
        self.enabled = enabled
        self.stop_guides()
        if not enabled:
            self.voice_queue.clear()
            if self.voice:
                self.voice.stop()
        if announce:
            # The toggle itself must remain audible when turning guidance off.
            self.play_sfx("access-on" if enabled else "access-off", volume=1.0)

    def play_sfx(self, reference: str, *, volume: float = 0.7) -> None:
        if not self.sfx:
            return
        sound = self.sound(reference)
        if sound:
            self.sfx.set_volume(volume)
            self.sfx.play(sound)

    def speak(self, references: Iterable[str], *, replace: bool = True) -> None:
        if not self.enabled or not self.voice:
            return
        if replace:
            self.voice.stop()
            self.voice_queue.clear()
        self.voice_queue.extend(reference for reference in references if self.resolver(reference))
        self.update_voice()

    def speak_name(self, name: str, *, replace: bool = True) -> None:
        clip = NAME_CLIPS.get(name.strip().lower())
        if clip:
            self.speak([clip], replace=replace)

    def update_voice(self) -> None:
        if not self.enabled or not self.voice or self.voice.get_busy() or not self.voice_queue:
            return
        sound = self.sound(self.voice_queue.popleft())
        if sound:
            self.voice.set_volume(1.0)
            self.voice.play(sound)

    def stop_voice(self) -> None:
        self.voice_queue.clear()
        if self.voice:
            self.voice.stop()

    def voice_idle(self) -> bool:
        return not self.voice_queue and (not self.voice or not self.voice.get_busy())

    def stop_guides(self) -> None:
        for channel in (self.horizontal, self.vertical):
            if channel:
                channel.stop()
        self.x_locked = False
        self.y_locked = False
        self.locked_signal = None

    def stop_environment(self) -> None:
        for channel in (self.ambient, self.proximity):
            if channel:
                channel.stop()

    def update_environment(
        self,
        player: pygame.Vector2,
        nodes: list[tuple[int, tuple[int, int]]],
        *,
        active: bool,
    ) -> None:
        """Recreate BackgroundSound and Resource_SoundComponent_Noise."""
        if not active:
            self.stop_environment()
            return
        self._ensure_loop(self.ambient, "aether")
        if self.ambient:
            self.ambient.set_volume(0.32, 0.32)
        if not nodes:
            if self.proximity:
                self.proximity.stop()
            return

        _, position = min(nodes, key=lambda item: player.distance_squared_to(item[1]))
        distance = player.distance_to(position)
        # Unity used spatial rolloff. This curve retains a quiet outer edge and
        # becomes substantially louder in the final approach.
        closeness = max(0.0, 1.0 - distance / 330.0)
        volume = (closeness**1.6) * 0.62
        self._ensure_loop(self.proximity, "brown_noise")
        if self.proximity:
            dx = float(position[0] - player.x)
            pan = min(1.0, abs(dx) / 330.0)
            if dx < 0:
                self.proximity.set_volume(volume, volume * (1.0 - 0.75 * pan))
            else:
                self.proximity.set_volume(volume * (1.0 - 0.75 * pan), volume)

    def _ensure_loop(self, channel: pygame.mixer.Channel | None, reference: str) -> None:
        if channel and not channel.get_busy():
            sound = self.sound(reference)
            if sound:
                channel.play(sound, loops=-1)

    def update_guides(
        self,
        player: pygame.Vector2,
        nodes: list[tuple[int, tuple[int, int]]],
        *,
        active: bool,
    ) -> None:
        if not active or not self.enabled or not nodes:
            self.stop_guides()
            return
        signal_id, position = min(nodes, key=lambda item: player.distance_squared_to(item[1]))
        dx = float(position[0] - player.x)
        dy = float(position[1] - player.y)
        x_volume = max(0.0, 1.0 - abs(dx) / self.GUIDE_RANGE) * 0.55
        y_volume = max(0.0, 1.0 - abs(dy) / self.GUIDE_RANGE) * 0.55

        self._ensure_loop(self.horizontal, "horizlock")
        self._ensure_loop(self.vertical, "vertical")
        if self.horizontal:
            # Pan the horizontal guide toward the target while preserving a
            # small amount in the opposite ear.
            pan = min(1.0, abs(dx) / self.GUIDE_RANGE)
            if dx < 0:
                self.horizontal.set_volume(x_volume, x_volume * (1.0 - 0.8 * pan))
            else:
                self.horizontal.set_volume(x_volume * (1.0 - 0.8 * pan), x_volume)
        if self.vertical:
            self.vertical.set_volume(y_volume, y_volume)

        same_signal = self.locked_signal == signal_id
        new_x_lock = abs(dx) <= self.AXIS_LOCK_DISTANCE
        new_y_lock = abs(dy) <= self.AXIS_LOCK_DISTANCE
        now = pygame.time.get_ticks()
        newly_aligned = (new_x_lock and (not self.x_locked or not same_signal)) or (
            new_y_lock and (not self.y_locked or not same_signal)
        )
        node_locked = player.distance_to(position) <= self.NODE_LOCK_DISTANCE
        repeat_due = node_locked and now - self.last_lock_ms >= self.LOCK_REPEAT_MS
        if newly_aligned or repeat_due:
            self.play_sfx("lockon", volume=0.55)
            self.last_lock_ms = now
        self.x_locked = new_x_lock
        self.y_locked = new_y_lock
        self.locked_signal = signal_id

