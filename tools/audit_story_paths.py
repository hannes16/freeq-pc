"""Exhaustively explore every reachable FREEQ story decision.

This follows every ordering of concurrently active signals and every eligible
switchboard connection.  Prompt cancellations are omitted because they return
to the identical story state without changing tags, masks, or consumed signals.
"""

from __future__ import annotations

import argparse
import json
import random
import sys
from collections import deque
from dataclasses import dataclass
from pathlib import Path
from typing import Any


ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "freeq_port"))

from engine import StoryEngine, load_game_data  # noqa: E402


@dataclass(frozen=True)
class AuditResult:
    states: int
    completed_states: int
    stalled_states: int
    reachable_signals: frozenset[int]
    reachable_connections: frozenset[int]
    transitions: int
    exhaustive: bool


@dataclass(frozen=True)
class CoverageResult:
    runs: int
    completed_runs: int
    stalled_runs: int
    reachable_signals: frozenset[int]
    reachable_connections: frozenset[int]
    first_stall: dict[str, Any] | None
    terminal_signal_ids: frozenset[int]
    restored_connections_on_completed_runs: frozenset[int]


def state_key(engine: StoryEngine) -> tuple[Any, ...]:
    """Return all state that can affect subsequent story availability."""
    return (
        engine.mask,
        tuple(sorted((name, int(value)) for name, value in engine.tags.items())),
        tuple(sorted(engine.consumed)),
        tuple(int(signal["path_id"]) for signal in engine.active),
        int(engine.queued_hijack["path_id"]) if engine.queued_hijack else None,
        connection_id(engine.last_connection) if engine.last_connection else None,
        engine.act_index,
        engine.game_over,
    )


def connection_id(connection: dict[str, Any]) -> int:
    return int(connection["id"])


def clone_engine(engine: StoryEngine) -> StoryEngine:
    """Copy mutable runtime state while sharing the immutable story database."""
    branch = StoryEngine.__new__(StoryEngine)
    branch.data = engine.data
    branch.mask = engine.mask
    branch.tags = engine.tags.copy()
    branch.consumed = engine.consumed.copy()
    branch.active = engine.active.copy()
    branch.notes = engine.notes.copy()
    branch.achievements = engine.achievements.copy()
    branch.act_index = engine.act_index
    branch.game_over = engine.game_over
    branch.queued_hijack = engine.queued_hijack
    branch.last_connection = engine.last_connection
    return branch


def audit(
    data: dict[str, Any],
    *,
    max_states: int | None = None,
    progress_every: int | None = None,
) -> AuditResult:
    pending = deque([StoryEngine(data)])
    seen: set[tuple[Any, ...]] = set()
    reachable_signals: set[int] = set()
    reachable_connections: set[int] = set()
    completed_states = 0
    stalled_states = 0
    transitions = 0

    while pending:
        # Depth-first traversal keeps the pending frontier small. The `seen`
        # key still guarantees that every distinct resulting state is visited.
        engine = pending.pop()
        key = state_key(engine)
        if key in seen:
            continue
        seen.add(key)
        if progress_every and len(seen) % progress_every == 0:
            print(
                f"audited {len(seen):,} states; "
                f"signals={len(reachable_signals)}, connections={len(reachable_connections)}, "
                f"pending={len(pending):,}",
                file=sys.stderr,
                flush=True,
            )
        if max_states is not None and len(seen) >= max_states:
            break

        if engine.game_over:
            completed_states += 1
            continue

        if engine.queued_hijack:
            signal = engine.queued_hijack
            reachable_signals.add(int(signal["path_id"]))
            connections = engine.eligible_connections(signal)
            if connections:
                for connection in connections:
                    reachable_connections.add(connection_id(connection))
                    branch = clone_engine(engine)
                    branch_signal = branch.queued_hijack
                    branch_connection = next(
                        item
                        for item in branch.eligible_connections(branch_signal)
                        if connection_id(item) == connection_id(connection)
                    )
                    branch.finish_connection(branch_signal, branch_connection, hijack=True)
                    pending.append(branch)
                    transitions += 1
            elif not signal.get("connections"):
                branch = clone_engine(engine)
                branch.finish_hijack_without_connection(branch.queued_hijack)
                pending.append(branch)
                transitions += 1
            else:
                stalled_states += 1
            continue

        progressed = False
        for signal in engine.active:
            reachable_signals.add(int(signal["path_id"]))
            started = clone_engine(engine)
            branch_signal = next(
                item for item in started.active if int(item["path_id"]) == int(signal["path_id"])
            )
            connections = started.begin_normal_signal(branch_signal)
            if not connections:
                # Accepting this call rolls its temporary tag changes back and
                # returns to the same Aether state. Another active call may
                # still make it available later.
                continue
            progressed = True
            for connection in connections:
                reachable_connections.add(connection_id(connection))
                branch = clone_engine(started)
                branch_signal = next(
                    item for item in branch.active if int(item["path_id"]) == int(signal["path_id"])
                )
                branch_connection = next(
                    item
                    for item in branch.eligible_connections(branch_signal)
                    if connection_id(item) == connection_id(connection)
                )
                branch.finish_connection(branch_signal, branch_connection, hijack=False)
                pending.append(branch)
                transitions += 1

        if not progressed:
            stalled_states += 1

    return AuditResult(
        states=len(seen),
        completed_states=completed_states,
        stalled_states=stalled_states,
        reachable_signals=frozenset(reachable_signals),
        reachable_connections=frozenset(reachable_connections),
        transitions=transitions,
        exhaustive=not pending,
    )


def cover_branches(data: dict[str, Any], *, runs: int, seed: int = 20261023) -> CoverageResult:
    """Seek a playable witness route for every serialized story branch.

    Selection is deterministic for a given seed and favors actions used least
    often across prior runs, which reaches rare conditional endings much more
    efficiently than uniform random play.
    """
    rng = random.Random(seed)
    action_visits: dict[tuple[int, int | None], int] = {}
    reachable_signals: set[int] = set()
    reachable_connections: set[int] = set()
    completed_runs = 0
    stalled_runs = 0
    first_stall: dict[str, Any] | None = None
    terminal_signal_ids: set[int] = set()
    restored_connections_on_completed_runs: set[int] = set()

    for _ in range(runs):
        engine = StoryEngine(data)
        route: list[tuple[int, int | None]] = []
        restored_in_run: set[int] = set()
        while not engine.game_over:
            if engine.queued_hijack:
                signal = engine.queued_hijack
                signal_id = int(signal["path_id"])
                reachable_signals.add(signal_id)
                connections = engine.eligible_connections(signal)
                if not connections and not signal.get("connections"):
                    action_visits[(signal_id, None)] = action_visits.get((signal_id, None), 0) + 1
                    route.append((signal_id, None))
                    engine.finish_hijack_without_connection(signal)
                    continue
                if not connections:
                    stalled_runs += 1
                    if first_stall is None:
                        first_stall = {
                            "mask": engine.mask,
                            "act_index": engine.act_index,
                            "active_signal_ids": [signal_id],
                            "nonzero_tags": {
                                name: value for name, value in engine.tags.items() if int(value) != 0
                            },
                            "route": route.copy(),
                        }
                    break
                minimum = min(action_visits.get((signal_id, connection_id(item)), 0) for item in connections)
                choices = [
                    item
                    for item in connections
                    if action_visits.get((signal_id, connection_id(item)), 0) == minimum
                ]
                connection = rng.choice(choices)
                edge = (signal_id, connection_id(connection))
                action_visits[edge] = action_visits.get(edge, 0) + 1
                route.append(edge)
                reachable_connections.add(connection_id(connection))
                if connection.get("restored"):
                    restored_in_run.add(connection_id(connection))
                engine.finish_connection(signal, connection, hijack=True)
                continue

            candidates: list[tuple[dict[str, Any], dict[str, Any]]] = []
            for signal in engine.active:
                signal_id = int(signal["path_id"])
                reachable_signals.add(signal_id)
                # Normal signal tag changes occur before the switchboard opens.
                # Apply and immediately roll them back while enumerating the
                # choices, then apply them permanently only to the selected call.
                engine._apply_tag_changes(signal)
                for connection in engine.eligible_connections(signal):
                    candidates.append((signal, connection))
                engine._apply_tag_changes(signal, -1)
            if not candidates:
                stalled_runs += 1
                if first_stall is None:
                    first_stall = {
                        "mask": engine.mask,
                        "act_index": engine.act_index,
                        "active_signal_ids": [int(item["path_id"]) for item in engine.active],
                        "nonzero_tags": {
                            name: value for name, value in engine.tags.items() if int(value) != 0
                        },
                        "route": route.copy(),
                    }
                break

            minimum = min(
                action_visits.get((int(signal["path_id"]), connection_id(connection)), 0)
                for signal, connection in candidates
            )
            least_used = [
                candidate
                for candidate in candidates
                if action_visits.get(
                    (int(candidate[0]["path_id"]), connection_id(candidate[1])), 0
                )
                == minimum
            ]
            signal, connection = rng.choice(least_used)
            selected_id = connection_id(connection)
            connection = next(
                item
                for item in engine.begin_normal_signal(signal)
                if connection_id(item) == selected_id
            )
            edge = (int(signal["path_id"]), connection_id(connection))
            action_visits[edge] = action_visits.get(edge, 0) + 1
            route.append(edge)
            reachable_connections.add(connection_id(connection))
            if connection.get("restored"):
                restored_in_run.add(connection_id(connection))
            engine.finish_connection(signal, connection, hijack=False)
        else:
            completed_runs += 1
            if route:
                terminal_signal_ids.add(route[-1][0])
            restored_connections_on_completed_runs.update(restored_in_run)

    return CoverageResult(
        runs=runs,
        completed_runs=completed_runs,
        stalled_runs=stalled_runs,
        reachable_signals=frozenset(reachable_signals),
        reachable_connections=frozenset(reachable_connections),
        first_stall=first_stall,
        terminal_signal_ids=frozenset(terminal_signal_ids),
        restored_connections_on_completed_runs=frozenset(restored_connections_on_completed_runs),
    )


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--json",
        action="store_true",
        help="print the audit summary as JSON",
    )
    parser.add_argument(
        "--coverage-runs",
        type=int,
        default=0,
        help="seek branch witnesses over this many complete playthroughs",
    )
    parser.add_argument(
        "--original",
        action="store_true",
        help="audit the shipped gates without the restored-content overlay",
    )
    parser.add_argument(
        "--progress-every",
        type=int,
        help="report progress after this many new states",
    )
    parser.add_argument(
        "--max-states",
        type=int,
        help="stop after this many distinct states (diagnostic only)",
    )
    args = parser.parse_args()
    data = load_game_data(
        ROOT / "freeq_port" / "data" / "game_data.json",
        restored_content=not args.original,
    )
    all_signals = {int(signal["path_id"]) for signal in data["signals"]}
    all_connections = {
        int(connection["id"])
        for signal in data["signals"]
        for connection in signal.get("connections", [])
    }
    if args.coverage_runs:
        result = cover_branches(data, runs=args.coverage_runs)
        summary = {
            "runs": result.runs,
            "completed_runs": result.completed_runs,
            "stalled_runs": result.stalled_runs,
            "reachable_signals": len(result.reachable_signals),
            "total_signals": len(all_signals),
            "reachable_connections": len(result.reachable_connections),
            "total_connections": len(all_connections),
            "unreached_signal_ids": sorted(all_signals - result.reachable_signals),
            "unreached_connection_ids": sorted(all_connections - result.reachable_connections),
            "first_stall": result.first_stall,
            "terminal_signal_ids": sorted(result.terminal_signal_ids),
            "restored_connections_on_completed_runs": sorted(
                result.restored_connections_on_completed_runs
            ),
        }
        # Unreached records remain visible in the report; some are deliberately
        # dormant in the shipped Unity data. A coverage run fails only if a
        # sampled playthrough cannot reach a terminal state.
        failed = bool(result.stalled_runs or result.completed_runs != result.runs)
    else:
        result = audit(
            data,
            max_states=args.max_states,
            progress_every=args.progress_every,
        )
        summary = {
            "states": result.states,
            "exhaustive": result.exhaustive,
            "transitions": result.transitions,
            "completed_states": result.completed_states,
            "stalled_states": result.stalled_states,
            "reachable_signals": len(result.reachable_signals),
            "total_signals": len(all_signals),
            "reachable_connections": len(result.reachable_connections),
            "total_connections": len(all_connections),
            "unreached_signal_ids": sorted(all_signals - result.reachable_signals),
            "unreached_connection_ids": sorted(all_connections - result.reachable_connections),
        }
        failed = bool(result.stalled_states or result.completed_states == 0)
    if args.json:
        print(json.dumps(summary, indent=2))
    else:
        for name, value in summary.items():
            print(f"{name}: {value}")
    return 1 if failed else 0


if __name__ == "__main__":
    raise SystemExit(main())
