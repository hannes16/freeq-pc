from __future__ import annotations

import json
import sys
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "freeq_port"))
sys.path.insert(0, str(ROOT / "tools"))

from engine import StoryEngine, load_game_data  # noqa: E402
from audit_story_paths import cover_branches  # noqa: E402


class StoryEngineTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.data = load_game_data(ROOT / "freeq_port" / "data" / "game_data.json")

    def test_original_graph_dimensions(self) -> None:
        self.assertEqual(len(self.data["signals"]), 73)
        self.assertEqual(sum(len(signal["connections"]) for signal in self.data["signals"]), 143)
        self.assertEqual(len(self.data["tag_order"]), 67)
        self.assertEqual(self.data["act_tags"], [524288, 1073741824, 268435456])

    def test_first_transmission_and_hijack_order(self) -> None:
        engine = StoryEngine(self.data)
        self.assertEqual([signal["name"] for signal in engine.active], ["a1-sp1"])
        signal = engine.active[0]
        connections = engine.begin_normal_signal(signal)
        self.assertEqual([connection["name"] for connection in connections], ["James"])
        engine.finish_connection(signal, connections[0], hijack=False)
        self.assertEqual(engine.mask, 1)
        self.assertEqual(engine.tags["no warp"], 1)
        self.assertEqual(engine.queued_hijack["name"], "a1-hijack")
        engine.finish_hijack_without_connection(engine.queued_hijack)
        self.assertEqual(engine.tags["no warp"], 2)

    def test_every_referenced_gameplay_clip_was_extracted(self) -> None:
        manifest = json.loads((ROOT / "freeq_port" / "data" / "media_manifest.json").read_text(encoding="utf-8"))
        audio = manifest["audio"]
        refs = []
        for signal in self.data["signals"]:
            refs.append(signal["soundtrack"])
            refs.extend(connection["sound"] for connection in signal["connections"])
        missing = []
        for reference in refs:
            key = reference.replace("\\", "/").split("/")[-1].lower()
            if key and (key not in audio or not (ROOT / "freeq_port" / audio[key]).exists()):
                missing.append(reference)
        self.assertEqual(missing, [])

    def test_accessibility_audio_clips_are_present(self) -> None:
        manifest = json.loads((ROOT / "freeq_port" / "data" / "media_manifest.json").read_text(encoding="utf-8"))
        audio = manifest["audio"]
        required = {
            "vertical",
            "horizlock",
            "lockon",
            "switchboardmode",
            "switchboardhelp",
            "possible connections",
            "confirmconnect",
            "aethermode",
            "aetherhelp",
            "intercepted-id",
            "aether",
            "brown_noise",
        }
        self.assertEqual(required - audio.keys(), set())

    def test_at_least_one_complete_story_path_is_reachable(self) -> None:
        """Follow the serialized preferred/first choices through all three acts."""
        engine = StoryEngine(self.data)
        transmissions = 0
        while not engine.game_over and transmissions < 100:
            signal = engine.queued_hijack or (engine.active[0] if engine.active else None)
            self.assertIsNotNone(signal, f"Story stalled at mask {engine.mask:#x}")
            hijack = bool(signal.get("hijack"))
            connections = engine.eligible_connections(signal)
            if not connections:
                self.assertTrue(hijack, f"Normal signal {signal['name']} has no connection")
                engine.finish_hijack_without_connection(signal)
            else:
                if not hijack:
                    connections = engine.begin_normal_signal(signal)
                preferred = signal.get("preferred_connection", "")
                connection = next((item for item in connections if item["name"] == preferred), connections[0])
                engine.finish_connection(signal, connection, hijack=hijack)
            transmissions += 1
        self.assertTrue(engine.game_over)
        self.assertEqual(transmissions, 46)

    def test_every_reachable_branch_has_a_complete_witness_run(self) -> None:
        result = cover_branches(self.data, runs=200)
        all_signal_ids = {int(signal["path_id"]) for signal in self.data["signals"]}
        all_connection_ids = {
            int(connection["id"])
            for signal in self.data["signals"]
            for connection in signal["connections"]
        }
        dormant_signals = {1155, 1186, 1410}
        self.assertEqual(result.completed_runs, 200)
        self.assertEqual(result.stalled_runs, 0)
        self.assertEqual(all_signal_ids - result.reachable_signals, dormant_signals)
        # The Amy/James-villain variant is exceptionally rare and has a
        # dedicated targeted witness below rather than relying on sampling.
        self.assertEqual(all_connection_ids - result.reachable_connections, {1382})
        self.assertEqual(result.restored_connections_on_completed_runs, {
            1196, 1218, 1270, 1275, 1402,
            1438, 1504, 1542, 1544, 1558,
        })

    def test_rare_restored_james_villain_route_can_finish(self) -> None:
        route = [
            (1369, 1227), (1482, None), (1128, 1513), (1519, 1275),
            (1257, 1446), (1289, 1131), (1414, 1545), (1462, 1309),
            (1118, 1312), (1456, 1406), (1321, 1426), (1326, 1205),
            (1500, None), (1153, None), (1360, 1379), (1399, 1476),
            (1182, 1152), (1164, 1112), (1397, 1411), (1235, 1404),
            (1419, 1190), (1417, 1377), (1420, 1208), (1319, 1563),
            (1145, 1433), (1497, 1229), (1561, None), (1211, 1187),
            (1201, None), (1294, None), (1480, 1361), (1468, None),
            (1219, None), (1484, None), (1303, 1382),
        ]
        engine = StoryEngine(self.data)
        for signal_id, connection_id in route:
            signal = engine.queued_hijack or next(
                item for item in engine.active if int(item["path_id"]) == signal_id
            )
            connections = engine.eligible_connections(signal)
            if not signal.get("hijack"):
                connections = engine.begin_normal_signal(signal)
            if connection_id is None:
                engine.finish_hijack_without_connection(signal)
            else:
                connection = next(item for item in connections if int(item["id"]) == connection_id)
                engine.finish_connection(signal, connection, hijack=bool(signal.get("hijack")))
        self.assertIn(1382, {
            int(connection["id"])
            for signal in self.data["signals"]
            for connection in signal["connections"]
            if connection.get("restored")
        })
        self.assertEqual(engine.tags["JamesVillain"], 3)

        steps = 0
        while not engine.game_over and steps < 50:
            signal = engine.queued_hijack or engine.active[0]
            connections = engine.eligible_connections(signal)
            if not signal.get("hijack"):
                connections = engine.begin_normal_signal(signal)
            if connections:
                engine.finish_connection(signal, connections[0], hijack=bool(signal.get("hijack")))
            else:
                engine.finish_hijack_without_connection(signal)
            steps += 1
        self.assertTrue(engine.game_over)

    def test_restored_overlay_preserves_original_conditions(self) -> None:
        original = load_game_data(
            ROOT / "freeq_port" / "data" / "game_data.json",
            restored_content=False,
        )
        restored_ids = {
            int(connection["id"])
            for signal in self.data["signals"]
            for connection in signal["connections"]
            if connection.get("restored")
        }
        self.assertEqual(restored_ids, {
            1196, 1218, 1270, 1275, 1382, 1402,
            1438, 1504, 1542, 1544, 1558,
        })
        self.assertFalse(any(
            connection.get("restored")
            for signal in original["signals"]
            for connection in signal["connections"]
        ))

    def test_restoration_companions_preserve_exclusive_boundaries(self) -> None:
        by_id = {
            int(connection["id"]): connection
            for signal in self.data["signals"]
            for connection in signal["connections"]
        }
        companion_ids = {1123, 1131, 1190, 1252, 1267, 1313, 1356, 1492}
        self.assertEqual(
            {connection_id for connection_id, connection in by_id.items()
             if connection.get("restoration_companion")},
            companion_ids,
        )
        self.assertTrue(all(not by_id[connection_id].get("restored") for connection_id in companion_ids))
        expected_first_comparison = {
            1123: ("JenVillain", 3, 3),
            1131: ("loveJ", 2, 4),
            1252: ("JamesVillain", 3, 4),
            1267: ("JamesVillain", 3, 4),
            1313: ("jFollow", 1, 4),
            1356: ("JamesVillain", 3, 4),
            1492: ("jFollow", 2, 1),
        }
        for connection_id, expected in expected_first_comparison.items():
            comparison = by_id[connection_id]["comparisons"][0]
            self.assertEqual(
                (comparison["origin"], comparison["target_value"], comparison["operation"]),
                expected,
            )

    def test_tower2_information_handoff_unlocks_original_gates(self) -> None:
        by_signal_id = {int(signal["path_id"]): signal for signal in self.data["signals"]}
        by_connection_id = {
            int(connection["id"]): connection
            for signal in self.data["signals"]
            for connection in signal["connections"]
        }
        handoff = by_connection_id[1190]
        self.assertEqual(handoff["original_tag_changes"], {})
        self.assertEqual(handoff["tag_changes"], {"Tower2Info": 1})
        self.assertFalse(handoff["restored"])

        for connection_id in (1402, 1504):
            connection = by_connection_id[connection_id]
            self.assertEqual(connection["comparisons"], connection["original_comparisons"])
            self.assertEqual(connection["comparisons"][0]["origin"], "Tower2Info")

        engine = StoryEngine(self.data)
        special_signal = by_signal_id[1319]
        initial_eligible = {int(item["id"]) for item in engine.eligible_connections(special_signal)}
        self.assertNotIn(1402, initial_eligible)
        self.assertNotIn(1504, initial_eligible)
        engine._apply_tag_changes(handoff)
        eligible = {int(item["id"]) for item in engine.eligible_connections(special_signal)}
        self.assertIn(1402, eligible)
        self.assertIn(1504, eligible)

    def test_restored_connections_use_traced_narrow_conditions(self) -> None:
        by_id = {
            int(connection["id"]): connection
            for signal in self.data["signals"]
            for connection in signal["connections"]
        }
        self.assertEqual(by_id[1270]["comparisons"][0], {
            "origin": "jFollow", "target_tag": None, "target_value": 2, "operation": 4,
        })
        self.assertEqual(by_id[1438]["comparisons"], by_id[1438]["original_comparisons"])
        self.assertEqual(by_id[1544]["comparisons"][1], {
            "origin": "jLoyal", "target_tag": None, "target_value": 1, "operation": 4,
        })


if __name__ == "__main__":
    unittest.main()
