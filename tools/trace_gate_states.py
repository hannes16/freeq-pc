"""Collect reachable tag combinations when one original signal is available."""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "freeq_port"))
sys.path.insert(0, str(ROOT / "tools"))

from engine import StoryEngine, load_game_data  # noqa: E402
from audit_story_paths import state_key  # noqa: E402
from find_story_branch import successors  # noqa: E402


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("parent_id", type=int)
    parser.add_argument("--max-states", type=int, default=1_000_000)
    parser.add_argument("--extra-tags", nargs="*", default=[])
    args = parser.parse_args()

    data = load_game_data(
        ROOT / "freeq_port" / "data" / "game_data.json",
        restored_content=False,
    )
    parent = next(signal for signal in data["signals"] if int(signal["path_id"]) == args.parent_id)
    tag_names = sorted({
        name
        for connection in parent.get("connections", [])
        for rule in connection.get("comparisons", [])
        for name in (rule.get("origin"), rule.get("target_tag"))
        if name
    } | set(args.extra_tags))

    pending = [(StoryEngine(data), ())]
    seen = set()
    combinations: dict[tuple[int, ...], tuple[tuple[int, int | None], ...]] = {}
    while pending and len(seen) < args.max_states:
        engine, route = pending.pop()
        key = state_key(engine)
        if key in seen:
            continue
        seen.add(key)
        candidates = [engine.queued_hijack] if engine.queued_hijack else engine.active
        if any(signal and int(signal["path_id"]) == args.parent_id for signal in candidates):
            values = tuple(int(engine.tags.get(name, 0)) for name in tag_names)
            combinations.setdefault(values, route)
        # Once this signal has been answered or removed at an act transition,
        # later choices can no longer change which of its connections appeared.
        if args.parent_id in engine.consumed:
            continue
        for branch, action in successors(engine):
            pending.append((branch, route + (action,)))

    print(json.dumps({
        "parent": {"id": args.parent_id, "name": parent["name"]},
        "tag_names": tag_names,
        "states_examined": len(seen),
        "exhaustive": not pending,
        "combinations": [
            {"values": dict(zip(tag_names, values)), "witness": route}
            for values, route in sorted(combinations.items())
        ],
    }, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
