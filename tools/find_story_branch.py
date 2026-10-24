"""Find a playable route to one serialized FREEQ connection."""

from __future__ import annotations

import argparse
import heapq
import json
import sys
from itertools import count
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "freeq_port"))
sys.path.insert(0, str(ROOT / "tools"))

from engine import StoryEngine, load_game_data  # noqa: E402
from audit_story_paths import clone_engine, connection_id, state_key  # noqa: E402


def successors(engine: StoryEngine):
    if engine.queued_hijack:
        signal = engine.queued_hijack
        connections = engine.eligible_connections(signal)
        if connections:
            for connection in connections:
                branch = clone_engine(engine)
                branch.finish_connection(branch.queued_hijack, connection, hijack=True)
                yield branch, (int(signal["path_id"]), connection_id(connection))
        elif not signal.get("connections"):
            branch = clone_engine(engine)
            branch.finish_hijack_without_connection(branch.queued_hijack)
            yield branch, (int(signal["path_id"]), None)
        return
    for signal in engine.active:
        started = clone_engine(engine)
        branch_signal = next(item for item in started.active if item["path_id"] == signal["path_id"])
        for connection in started.begin_normal_signal(branch_signal):
            branch = clone_engine(started)
            branch_signal = next(item for item in branch.active if item["path_id"] == signal["path_id"])
            branch.finish_connection(branch_signal, connection, hijack=False)
            yield branch, (int(signal["path_id"]), connection_id(connection))


def rule_distance(engine: StoryEngine, rule: dict[str, Any]) -> int:
    origin = int(engine.tags.get(rule["origin"], 0))
    target = int(engine.tags.get(rule.get("target_tag"), 0)) if rule.get("target_tag") else int(rule["target_value"])
    operation = int(rule["operation"])
    if operation == 0:
        return abs(origin - target)
    if operation == 1:
        return max(0, target - origin)
    if operation == 2:
        return max(0, target + 1 - origin)
    if operation == 3:
        return max(0, origin - target)
    if operation == 4:
        return max(0, origin - target + 1)
    return 0 if origin != target else 1


def find_route(data: dict[str, Any], target_id: int, limit: int):
    parent = next(
        signal
        for signal in data["signals"]
        if any(int(connection["id"]) == target_id for connection in signal["connections"])
    )
    target = next(connection for connection in parent["connections"] if int(connection["id"]) == target_id)
    serial = count()

    def score(engine: StoryEngine) -> int:
        parent_visible = any(int(item["path_id"]) == int(parent["path_id"]) for item in engine.active)
        distance = sum(rule_distance(engine, rule) for rule in target.get("comparisons", []))
        return (
            engine.act_index * 100_000
            + (1_000_000 if parent_visible else 0)
            + len(engine.consumed) * 100
            + engine.mask.bit_count()
            - distance * 10_000
        )

    initial = StoryEngine(data)
    heap = [(-score(initial), next(serial), initial, ())]
    seen: set[tuple[Any, ...]] = set()
    relevant_tags = {rule["origin"] for rule in target.get("comparisons", []) if rule.get("origin")}
    relevant_tags.update(
        rule["target_tag"]
        for rule in target.get("comparisons", [])
        if rule.get("target_tag")
    )
    observed_parent_states = 0
    observed_ranges: dict[str, list[int]] = {}
    while heap and len(seen) < limit:
        _, _, engine, route = heapq.heappop(heap)
        key = state_key(engine)
        if key in seen:
            continue
        seen.add(key)
        candidates = [engine.queued_hijack] if engine.queued_hijack else engine.active
        for signal in candidates:
            if signal and int(signal["path_id"]) == int(parent["path_id"]):
                observed_parent_states += 1
                for name in relevant_tags:
                    value = int(engine.tags.get(name, 0))
                    bounds = observed_ranges.setdefault(name, [value, value])
                    bounds[0] = min(bounds[0], value)
                    bounds[1] = max(bounds[1], value)
                probe = clone_engine(engine)
                probe_signal = probe.queued_hijack or next(
                    item for item in probe.active if int(item["path_id"]) == int(parent["path_id"])
                )
                if not probe_signal.get("hijack"):
                    connections = probe.begin_normal_signal(probe_signal)
                else:
                    connections = probe.eligible_connections(probe_signal)
                if any(connection_id(item) == target_id for item in connections):
                    return (
                        route + ((int(parent["path_id"]), target_id),),
                        len(seen),
                        probe.tags,
                        {"parent_states": observed_parent_states, "tag_ranges": observed_ranges},
                    )
        for branch, action in successors(engine):
            heapq.heappush(heap, (-score(branch), next(serial), branch, route + (action,)))
    return (
        None,
        len(seen),
        None,
        {"parent_states": observed_parent_states, "tag_ranges": observed_ranges},
    )


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("connection_id", type=int)
    parser.add_argument("--limit", type=int, default=500_000)
    parser.add_argument(
        "--original",
        action="store_true",
        help="search the shipped gates without the restored-content overlay",
    )
    args = parser.parse_args()
    data = load_game_data(
        ROOT / "freeq_port" / "data" / "game_data.json",
        restored_content=not args.original,
    )
    route, states, tags, observations = find_route(data, args.connection_id, args.limit)
    print(
        json.dumps(
            {
                "found": route is not None,
                "states": states,
                "route": route,
                "tags": tags,
                "observations": observations,
            },
            indent=2,
        )
    )
    return 0 if route else 1


if __name__ == "__main__":
    raise SystemExit(main())
