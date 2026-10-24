"""Extract FREEQ's data-driven story graph and reusable media from the IPA.

This is a development helper.  The shipped Python game reads the generated
``game_data.json`` and ``assets`` directory and does not need UnityPy.
"""

from __future__ import annotations

import json
import re
import sys
from pathlib import Path
from typing import Any

import UnityPy
from UnityPy.helpers.TypeTreeGenerator import TypeTreeGenerator


ROOT = Path(__file__).resolve().parents[1]
UNITY_DATA = ROOT / "extracted" / "Payload" / "freeq.app" / "Data"
MANAGED = UNITY_DATA / "Managed"
OUT_DATA = ROOT / "freeq_port" / "data"
OUT_AUDIO = ROOT / "freeq_port" / "assets" / "audio"
OUT_IMAGES = ROOT / "freeq_port" / "assets" / "images"

ACHIEVEMENT_NAMES = [
    "First Freeq", "Moon Hits Eye", "Betrayed", "You Dirty Rat",
    "I'm Gonna Win", "Coming Clean", "Messin' with the Hof", "The Pizza Guy",
    "Love No Matter What", "Like You Like That", "Evil Scientist, Heart of Gold",
    "Broken Tower", "It Is Secret, It Is Safe", "The Dream Is Dead", "Interview",
    "Red Sky at Morn", "Are You From the Future?", "Groundhog Day", "Tower of Power",
    "Redemption", "Your Cheatin' Heart", "Tragedy", "Freeq Like Me", "Backer Love",
]


def safe_name(value: str) -> str:
    value = value.replace("\\", "_").replace("/", "_")
    return re.sub(r"[^A-Za-z0-9_.()& -]", "_", value).strip() or "unnamed"


def pptr_id(value: Any) -> int | None:
    if not isinstance(value, dict):
        return None
    path_id = value.get("m_PathID")
    return int(path_id) if path_id else None


def build_scene_index() -> tuple[dict[int, dict[str, Any]], dict[int, str], dict[str, Any]]:
    env = UnityPy.load(str(UNITY_DATA / "level0"))
    generator = TypeTreeGenerator(env.file.unity_version)
    generator.load_local_dll_folder(str(MANAGED))
    env.typetree_generator = generator

    behaviours: dict[int, dict[str, Any]] = {}
    classes: dict[int, str] = {}
    game_objects: dict[int, str] = {}

    for obj in env.objects:
        if obj.type.name == "GameObject":
            try:
                game_objects[obj.path_id] = obj.read().m_Name
            except Exception:
                pass

    wanted_classes = {
        "ConnectionInformation",
        "SignalInfo",
        "IncrementalTag",
        "IncrementalTagManager",
        "ASASpawnManager",
        "ActTransitionManager",
    }
    for obj in env.objects:
        if obj.type.name != "MonoBehaviour":
            continue
        head = obj.parse_monobehaviour_head()
        script = head.m_Script.deref_parse_as_object()
        if script.m_ClassName not in wanted_classes:
            continue
        tree = obj.read_typetree()
        go_id = pptr_id(tree.get("m_GameObject"))
        tree["_path_id"] = obj.path_id
        tree["_game_object"] = game_objects.get(go_id or 0, "")
        behaviours[obj.path_id] = tree
        classes[obj.path_id] = script.m_ClassName

    return behaviours, classes, {"unity_version": env.file.unity_version}


def serialize_story() -> dict[str, Any]:
    behaviours, classes, metadata = build_scene_index()

    tag_names: dict[int, str] = {}
    initial_tags: dict[str, int] = {}
    for path_id, tree in behaviours.items():
        if classes[path_id] == "IncrementalTag":
            name = tree.get("m_name", tree.get("_game_object", str(path_id)))
            tag_names[path_id] = name
            initial_tags[name] = int(tree.get("m_value", 0))

    def tag_ref(value: Any) -> str | None:
        path_id = pptr_id(value)
        return tag_names.get(path_id) if path_id else None

    def base_rules(tree: dict[str, Any]) -> dict[str, Any]:
        origins = tree.get("m_OrigenTags", [])
        targets = tree.get("m_TargetTags", [])
        values = tree.get("m_TargetValues", [])
        operations = tree.get("m_Operation", [])
        comparisons = []
        for idx, origin in enumerate(origins):
            comparisons.append(
                {
                    "origin": tag_ref(origin),
                    "target_tag": tag_ref(targets[idx]) if idx < len(targets) else None,
                    "target_value": int(values[idx]) if idx < len(values) else 0,
                    "operation": int(operations[idx]) if idx < len(operations) else 0,
                }
            )
        increases = {}
        raw_increases = tree.get("m_TagsToIncrease", [])
        # Unity stores tag deltas by IncrementalTagManager list order.  That
        # list is resolved below and injected into this closure.
        for idx, amount in enumerate(raw_increases):
            if idx < len(tag_order) and amount:
                increases[tag_order[idx]] = int(amount)
        return {
            "comparisons": comparisons,
            "tag_changes": increases,
            "achievements": [int(v) for v in tree.get("m_AchievementList", [])],
            "note": tree.get("m_Note", ""),
        }

    tag_order: list[str] = []
    for path_id, tree in behaviours.items():
        if classes[path_id] == "IncrementalTagManager":
            tag_order = [tag_ref(ref) or f"tag_{idx}" for idx, ref in enumerate(tree.get("m_currentTags", []))]
            break
    if not tag_order:
        tag_order = list(initial_tags)

    connections: dict[int, dict[str, Any]] = {}
    for path_id, tree in behaviours.items():
        if classes[path_id] != "ConnectionInformation":
            continue
        connection = {
            "id": path_id,
            "name": tree.get("m_strName", "Unknown"),
            "mask": int(tree.get("m_mask", 0)),
            "required_mask": int(tree.get("m_requiredMask", 0)),
            "sound": tree.get("m_Sound", ""),
            "circle_level": int(tree.get("m_circleLevel", 0)),
        }
        connection.update(base_rules(tree))
        connections[path_id] = connection

    signals: dict[int, dict[str, Any]] = {}
    for path_id, tree in behaviours.items():
        if classes[path_id] != "SignalInfo":
            continue
        signal_connections = []
        for ref in tree.get("m_Connections", []):
            connection_id = pptr_id(ref)
            if connection_id in connections:
                signal_connections.append(connections[connection_id])
        signal = {
            "path_id": path_id,
            "id": int(tree.get("m_ID", -1)),
            "name": tree.get("m_strName", ""),
            "user_name": tree.get("m_strUserName", "Unknown"),
            "soundtrack": tree.get("m_strSoundTrak", ""),
            "asa_mask": int(tree.get("m_ASAMask", 0)),
            "generated_mask": int(tree.get("m_generatedMask", 0)),
            "size_mask": int(tree.get("m_sizeMask", 0)),
            "hijack": bool(tree.get("m_bHijack", False)),
            "texture": tree.get("m_TextureName", ""),
            "preferred_connection": tree.get("m_preferredConnectionName", ""),
            "connections": signal_connections,
        }
        signal.update(base_rules(tree))
        signals[path_id] = signal

    ordered_signal_ids: list[int] = []
    manager_data: dict[str, Any] = {}
    act_tags: list[int] = []
    for path_id, tree in behaviours.items():
        if classes[path_id] == "ASASpawnManager":
            ordered_signal_ids = [
                signal_id
                for ref in tree.get("m_lpSignals", [])
                if (signal_id := pptr_id(ref)) in signals
            ]
            manager_data = {
                "reset_mask_on_start": bool(tree.get("m_bResetMaskOnStart", False)),
                "initial_mask": int(tree.get("m_currentMaskStatus", 0)),
            }
            break

    for path_id, tree in behaviours.items():
        if classes[path_id] == "ActTransitionManager":
            act_tags = [int(value) for value in tree.get("m_ActTags", [])]
            break


    # Preserve the exact list order used by ASASpawnManager.GenerateSignals.
    ordered_signals = [signals[path_id] for path_id in ordered_signal_ids]

    notes: dict[str, str] = {}
    notes_source = ROOT / "decompiled" / "csharp" / "NotesDescriptionManager.cs"
    if notes_source.exists():
        source = notes_source.read_text(encoding="utf-8")
        keys_block = source.split("m_EnumOfNotes = new List<string>", 1)[1].split(
            "private List<string> m_NotesDescription", 1
        )[0]
        descriptions_block = source.split("m_NotesDescription = new List<string>", 1)[1].split(
            "private List<int> m_IndexofShowingNotes", 1
        )[0]
        literal_pattern = re.compile(r'"(?:\\.|[^"\\])*"')
        keys = [json.loads(value) for value in literal_pattern.findall(keys_block)]
        descriptions = [json.loads(value) for value in literal_pattern.findall(descriptions_block)]
        notes = dict(zip(keys, descriptions))

    return {
        "metadata": metadata,
        "tag_order": tag_order,
        "initial_tags": {name: initial_tags.get(name, 0) for name in tag_order},
        "manager": manager_data,
        "act_tags": act_tags,
        "signals": ordered_signals,
        "notes": notes,
        "achievement_names": ACHIEVEMENT_NAMES,
    }


def extract_media() -> dict[str, dict[str, str]]:
    OUT_AUDIO.mkdir(parents=True, exist_ok=True)
    OUT_IMAGES.mkdir(parents=True, exist_ok=True)
    manifest: dict[str, dict[str, str]] = {"audio": {}, "images": {}}
    asset_files = [
        "resources.assets",
        "sharedassets0.assets",
        "sharedassets1.assets",
        "sharedassets2.assets",
        "sharedassets3.assets",
    ]
    for asset_file in asset_files:
        env = UnityPy.load(str(UNITY_DATA / asset_file))
        for obj in env.objects:
            if obj.type.name == "AudioClip":
                try:
                    clip = obj.read()
                except Exception as exc:
                    print(f"warning: could not read audio object {obj.path_id} in {asset_file}: {exc}", file=sys.stderr)
                    continue
                samples = clip.samples
                if not samples:
                    tree = obj.read_typetree()
                    raw = bytes(tree.get("m_AudioData", []))
                    if raw:
                        suffix = ".mp3" if raw[:2] in (b"\xff\xfb", b"\xff\xf3", b"\xff\xf2") or raw[:3] == b"ID3" else ".audio"
                        samples = {f"{tree.get('m_Name', clip.m_Name)}{suffix}": raw}
                for sample_name, sample_data in samples.items():
                    suffix = Path(sample_name).suffix or ".wav"
                    file_name = f"{safe_name(clip.m_Name)}{suffix.lower()}"
                    target = OUT_AUDIO / file_name
                    if not target.exists():
                        target.write_bytes(sample_data)
                    manifest["audio"].setdefault(clip.m_Name.lower(), f"assets/audio/{file_name}")
            elif obj.type.name == "Texture2D":
                texture = obj.read()
                try:
                    file_name = f"{safe_name(texture.m_Name)}.png"
                    target = OUT_IMAGES / file_name
                    texture.image.save(target)
                    manifest["images"].setdefault(texture.m_Name.lower(), f"assets/images/{file_name}")
                except Exception as exc:
                    print(f"warning: could not export texture {texture.m_Name}: {exc}", file=sys.stderr)
    return manifest


def main() -> None:
    OUT_DATA.mkdir(parents=True, exist_ok=True)
    story = serialize_story()
    manifest = extract_media()
    (OUT_DATA / "game_data.json").write_text(json.dumps(story, indent=2), encoding="utf-8")
    (OUT_DATA / "media_manifest.json").write_text(json.dumps(manifest, indent=2), encoding="utf-8")
    print(f"Extracted {len(story['signals'])} signals")
    print(f"Extracted {len(manifest['audio'])} audio clips and {len(manifest['images'])} textures")


if __name__ == "__main__":
    main()
