from __future__ import annotations

import os
import sys
import unittest
from pathlib import Path


os.environ["SDL_VIDEODRIVER"] = "dummy"
os.environ["SDL_AUDIODRIVER"] = "dummy"
os.environ["PYGAME_HIDE_SUPPORT_PROMPT"] = "1"

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "freeq_port"))

import pygame  # noqa: E402
from freeq import CREDITS_SPEECH, HELP_SPEECH, FreeqGame  # noqa: E402


class UiBehaviorTests(unittest.TestCase):
    def tearDown(self) -> None:
        pygame.mixer.music.stop()

    def test_yes_no_prompt_is_keyboard_menu(self) -> None:
        game = FreeqGame()
        signal = game.engine.active[0]
        game.begin_intercept(signal)
        self.assertEqual(game.confirm_index, 0)
        game.handle_event(pygame.event.Event(pygame.KEYDOWN, key=pygame.K_RIGHT, mod=0))
        self.assertEqual(game.confirm_index, 1)
        game.handle_event(pygame.event.Event(pygame.KEYDOWN, key=pygame.K_RETURN, mod=0))
        self.assertEqual(game.state, "aether")

    def test_restored_connections_use_normal_labels(self) -> None:
        game = FreeqGame()
        restored = next(
            connection
            for signal in game.data["signals"]
            for connection in signal["connections"]
            if connection.get("restored")
        )
        self.assertEqual(game.connection_label(restored), restored["name"])

    def test_restored_selection_has_no_extra_tts_announcement(self) -> None:
        game = FreeqGame()
        signal = next(
            signal
            for signal in game.data["signals"]
            if any(connection.get("restored") for connection in signal["connections"])
        )
        restored = next(
            connection for connection in signal["connections"] if connection.get("restored")
        )

        announcements = []

        class FakeScreenReader:
            def speak(self, text, *, interrupt=True):
                announcements.append((text, interrupt))
                return True

        game.screen_reader = FakeScreenReader()
        game.connections = [restored]
        game.connection_index = 0
        game.announce_connection_selection()
        self.assertEqual(game.pending_screen_reader_announcement, "")
        self.assertEqual(announcements, [])

        game.access.stop_voice()
        game.flush_screen_reader_announcement()
        self.assertEqual(announcements, [])
        self.assertEqual(game.pending_screen_reader_announcement, "")

    def test_new_signals_do_not_reuse_the_completed_aligned_position(self) -> None:
        game = FreeqGame()
        game.sync_node_positions()
        first = game.engine.active[0]
        old_position = game.signal_position(first)
        game.player.update(old_position)

        connection = game.engine.begin_normal_signal(first)[0]
        game.engine.finish_connection(first, connection, hijack=False)
        hijack = game.engine.queued_hijack
        game.engine.finish_hijack_without_connection(hijack)
        game.sync_node_positions()

        self.assertTrue(game.engine.active)
        self.assertNotIn(old_position, game.node_positions.values())
        nearest = min(game.player.distance_to(position) for position in game.node_positions.values())
        self.assertGreater(nearest, game.access.NODE_LOCK_DISTANCE)

    def test_restored_feedback_boundary_closes_original_final_choice_gap(self) -> None:
        game = FreeqGame()
        signal = next(item for item in game.data["signals"] if int(item["path_id"]) == 1240)
        game.engine.tags.update({
            "TowerFIXED": 2,
            "TowerIsSecret": 1,
            "TimeTravelLisa": 3,
            "Musical": 1,
            "JamesSaved": 1,
            "loveJ": 3,
            "loveV": 2,
            "loveL": 2,
            "JenVillain": 2,
            "VincentMayor": 1,
        })
        self.assertTrue(signal["connections"])
        connections = game.engine.eligible_connections(signal)
        self.assertEqual([int(connection["id"]) for connection in connections], [1123])
        self.assertEqual(connections[0]["name"], "Nothing")
        self.assertFalse(connections[0].get("restored"))

    def test_end_credits_are_spoken_and_can_be_repeated(self) -> None:
        game = FreeqGame()
        announcements = []

        class FakeScreenReader:
            def speak(self, text, *, interrupt=True):
                announcements.append((text, interrupt))
                return True

        game.screen_reader = FakeScreenReader()
        game.enter_credits()
        self.assertEqual(game.state, "credits")
        self.assertEqual(announcements, [(CREDITS_SPEECH, True)])

        game.handle_event(pygame.event.Event(pygame.KEYDOWN, key=pygame.K_r, mod=0))
        self.assertEqual(announcements, [(CREDITS_SPEECH, True), (CREDITS_SPEECH, True)])

    def test_help_controls_are_spoken_after_recorded_help_and_can_be_repeated(self) -> None:
        game = FreeqGame()
        announcements = []

        class FakeScreenReader:
            def speak(self, text, *, interrupt=True):
                announcements.append((text, interrupt))
                return True

        game.screen_reader = FakeScreenReader()
        game.open_help()
        self.assertEqual(game.state, "help")
        self.assertEqual(game.pending_screen_reader_announcement, HELP_SPEECH)
        self.assertEqual(announcements, [])

        game.access.stop_voice()
        game.flush_screen_reader_announcement()
        self.assertEqual(announcements, [(HELP_SPEECH, True)])

        game.handle_event(pygame.event.Event(pygame.KEYDOWN, key=pygame.K_r, mod=0))
        self.assertEqual(announcements, [(HELP_SPEECH, True), (HELP_SPEECH, True)])

    def test_achievement_screen_speaks_count_navigation_and_repeat(self) -> None:
        game = FreeqGame()
        announcements = []

        class FakeScreenReader:
            def speak(self, text, *, interrupt=True):
                announcements.append((text, interrupt))
                return True

        game.screen_reader = FakeScreenReader()
        game.engine.achievements = [0, 7]
        game.open_achievements()
        self.assertEqual(game.state, "achievements")
        self.assertIn("2 unlocked", announcements[0][0])
        self.assertIn("First Freeq", announcements[0][0])

        game.handle_event(pygame.event.Event(pygame.KEYDOWN, key=pygame.K_DOWN, mod=0))
        game.handle_event(pygame.event.Event(pygame.KEYDOWN, key=pygame.K_r, mod=0))
        self.assertEqual(announcements[-2:], [("The Pizza Guy", True), ("The Pizza Guy", True)])

    def test_empty_achievement_screen_is_spoken(self) -> None:
        game = FreeqGame()
        announcements = []

        class FakeScreenReader:
            def speak(self, text, *, interrupt=True):
                announcements.append(text)
                return True

        game.screen_reader = FakeScreenReader()
        game.engine.achievements = []
        game.open_achievements()
        self.assertIn("No achievements unlocked yet", announcements[0])


if __name__ == "__main__":
    unittest.main()
