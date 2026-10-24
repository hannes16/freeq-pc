"""Data-driven implementation of FREEQ's original Unity story logic."""

from __future__ import annotations

import json
from copy import deepcopy
from pathlib import Path
from typing import Any


OPERATIONS = (
    lambda a, b: a == b,
    lambda a, b: a >= b,
    lambda a, b: a > b,
    lambda a, b: a <= b,
    lambda a, b: a < b,
    lambda a, b: a != b,
)


class StoryEngine:
    """Faithful translation of TagComparison and ASASpawnManager.

    Unity's Aether grid only permits four simultaneous signals because taking
    a slot removes its row and column from the 5x4 placement grid.  The port
    preserves that effective cap and the serialized signal order.
    """

    ACTIVE_LIMIT = 4

    def __init__(self, data: dict[str, Any]) -> None:
        self.data = data
        self.reset()

    def reset(self) -> None:
        self.mask = int(self.data.get("manager", {}).get("initial_mask", 0))
        self.tags = deepcopy(self.data["initial_tags"])
        self.consumed: set[int] = set()
        self.active: list[dict[str, Any]] = []
        self.notes: list[str] = []
        self.achievements: list[int] = []
        self.act_index = 0
        self.game_over = False
        self.queued_hijack: dict[str, Any] | None = None
        # Unity's ASASpawnManager retains m_ConnectionSignal. When a hijack
        # without connections calls GenerateSignals, that prior connection's
        # tag changes are applied again before the hijack tags.
        self.last_connection: dict[str, Any] | None = None
        self.refresh()

    def compare(self, rules: list[dict[str, Any]]) -> bool:
        for rule in rules:
            origin_name = rule.get("origin")
            if not origin_name:
                continue
            origin = int(self.tags.get(origin_name, 0))
            target_name = rule.get("target_tag")
            target = int(self.tags.get(target_name, 0)) if target_name else int(rule.get("target_value", 0))
            operation = int(rule.get("operation", 0))
            if operation < 0 or operation >= len(OPERATIONS) or not OPERATIONS[operation](origin, target):
                return False
        return True

    def is_signal_available(self, signal: dict[str, Any]) -> bool:
        required = int(signal.get("asa_mask", 0))
        if (required & self.mask) != required:
            return False

        # Some authored choices identify a specific follow-up hijack even
        # though the shipped comparison list only considers relationship
        # totals.  Keep the original comparisons as the fallback, but honor
        # an explicit selector when one of those choices has been made.
        signal_name = signal.get("name", "")
        for group in self.data.get("signal_selector_overrides", []):
            if signal_name not in group.get("signals", []):
                continue
            if not self.compare(group.get("comparisons", [])):
                return self.compare(signal.get("comparisons", []))

            # Preserve any explicitly prioritized relationship route before
            # applying a direct story-choice selector.  The waterfront group
            # uses this for Luigi's hidden strict-highest-affinity rescue.
            selected_priority = next(
                (
                    priority_name
                    for priority_name in group.get("priority_signals", [])
                    for priority_signal in self.data["signals"]
                    if priority_signal.get("name") == priority_name
                    and self.compare(priority_signal.get("comparisons", []))
                ),
                None,
            )
            if selected_priority:
                return signal_name == selected_priority

            selected_name = next(
                (
                    selector.get("signal")
                    for selector in group.get("selectors", [])
                    if int(self.tags.get(selector.get("tag", ""), 0)) > 0
                ),
                None,
            )
            if selected_name:
                return signal_name == selected_name

        return self.compare(signal.get("comparisons", []))

    def eligible_connections(self, signal: dict[str, Any]) -> list[dict[str, Any]]:
        result = []
        for connection in signal.get("connections", []):
            required = int(connection.get("required_mask", 0))
            if (required & self.mask) == required and self.compare(connection.get("comparisons", [])):
                copy = deepcopy(connection)
                if signal.get("hijack"):
                    copy["mask"] = int(copy.get("mask", 0)) | int(signal.get("generated_mask", 0))
                result.append(copy)
        return result

    def _apply_tag_changes(self, item: dict[str, Any], multiplier: int = 1) -> None:
        for name, amount in item.get("tag_changes", {}).items():
            self.tags[name] = int(self.tags.get(name, 0)) + int(amount) * multiplier

    def _record_rewards(self, item: dict[str, Any]) -> None:
        note = item.get("note", "")
        if note and note not in self.notes:
            self.notes.append(note)
        for achievement in item.get("achievements", []):
            value = int(achievement)
            if value not in self.achievements:
                self.achievements.append(value)

    def _advance_act(self) -> None:
        act_tags = self.data.get("act_tags", [])
        if self.act_index >= len(act_tags):
            return
        threshold = int(act_tags[self.act_index])
        if (self.mask & threshold) != threshold:
            return
        self.act_index += 1
        if self.act_index >= len(act_tags):
            self.game_over = True
            self.active.clear()
            return
        # The Unity implementation clears the old act's spawned objects, but
        # deliberately preserves signal id 64 during the transition.
        for signal in list(self.active):
            if int(signal.get("id", -1)) != 64:
                self.consumed.add(int(signal["path_id"]))
                self.active.remove(signal)

    def refresh(self) -> None:
        self._advance_act()
        if self.game_over or self.queued_hijack is not None:
            return
        active_ids = {int(signal["path_id"]) for signal in self.active}
        for signal in self.data["signals"]:
            path_id = int(signal["path_id"])
            if path_id in self.consumed or path_id in active_ids or not self.is_signal_available(signal):
                continue
            if signal.get("hijack"):
                self.queued_hijack = signal
                return
            if len(self.active) < self.ACTIVE_LIMIT:
                self.active.append(signal)
                active_ids.add(path_id)

    def begin_normal_signal(self, signal: dict[str, Any]) -> list[dict[str, Any]]:
        self._apply_tag_changes(signal)
        return self.eligible_connections(signal)

    def cancel_normal_signal(self, signal: dict[str, Any]) -> None:
        self._apply_tag_changes(signal, -1)

    def begin_hijack(self, signal: dict[str, Any]) -> None:
        self._record_rewards(signal)

    def finish_hijack_without_connection(self, signal: dict[str, Any]) -> None:
        if signal.get("connections"):
            raise ValueError("hijack has serialized connections but none are currently eligible")
        if self.last_connection is not None:
            self._apply_tag_changes(self.last_connection)
        self._apply_tag_changes(signal)
        self.mask |= int(signal.get("generated_mask", 0))
        self._consume(signal)

    def finish_connection(
        self,
        signal: dict[str, Any],
        connection: dict[str, Any],
        *,
        hijack: bool,
    ) -> None:
        self._record_rewards(connection)
        self.last_connection = deepcopy(connection)
        self._apply_tag_changes(connection)
        if hijack:
            self._apply_tag_changes(signal)
        self.mask |= int(connection.get("mask", 0))
        self._consume(signal)

    def record_connection_rewards(self, connection: dict[str, Any]) -> None:
        """Record notes at playback start, matching ConnectMenu.CloseConnectionMenu."""
        self._record_rewards(connection)

    def _consume(self, signal: dict[str, Any]) -> None:
        path_id = int(signal["path_id"])
        self.consumed.add(path_id)
        self.active = [item for item in self.active if int(item["path_id"]) != path_id]
        if self.queued_hijack and int(self.queued_hijack["path_id"]) == path_id:
            self.queued_hijack = None
        self.refresh()

    def to_save(self) -> dict[str, Any]:
        return {
            "mask": self.mask,
            "tags": self.tags,
            "consumed": sorted(self.consumed),
            "notes": self.notes,
            "achievements": self.achievements,
            "act_index": self.act_index,
            "game_over": self.game_over,
        }

    def load_save(self, payload: dict[str, Any]) -> None:
        self.mask = int(payload.get("mask", 0))
        self.tags = {**self.data["initial_tags"], **payload.get("tags", {})}
        self.consumed = {int(value) for value in payload.get("consumed", [])}
        self.notes = list(payload.get("notes", []))
        self.achievements = [int(value) for value in payload.get("achievements", [])]
        self.act_index = int(payload.get("act_index", 0))
        self.game_over = bool(payload.get("game_over", False))
        self.active = []
        self.queued_hijack = None
        # Scene reloads do not serialize ASASpawnManager.m_ConnectionSignal.
        self.last_connection = None
        self.refresh()


def load_game_data(path: Path, *, restored_content: bool = True) -> dict[str, Any]:
    data = json.loads(path.read_text(encoding="utf-8"))
    if not restored_content:
        return data
    overlay_path = path.with_name("restored_content.json")
    if not overlay_path.exists():
        return data
    overlay = json.loads(overlay_path.read_text(encoding="utf-8"))
    data["signal_selector_overrides"] = deepcopy(
        overlay.get("signal_selector_overrides", [])
    )
    overrides = overlay.get("connection_overrides", {})
    for signal in data["signals"]:
        for connection in signal.get("connections", []):
            override = overrides.get(str(connection["id"]))
            if not override:
                continue
            if "comparisons" in override:
                connection["original_comparisons"] = deepcopy(connection.get("comparisons", []))
                connection["comparisons"] = deepcopy(override["comparisons"])
            if "tag_changes" in override:
                connection["original_tag_changes"] = deepcopy(connection.get("tag_changes", {}))
                connection["tag_changes"] = deepcopy(override["tag_changes"])
            connection["restored"] = bool(override.get("mark_restored", True))
            connection["restoration_companion"] = bool(
                override.get("restoration_companion", not connection["restored"])
            )
            connection["restoration_reason"] = override.get("reason", "")
    return data

