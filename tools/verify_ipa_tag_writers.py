"""List every serialized story-tag writer in an extracted FREEQ IPA."""

from __future__ import annotations

import argparse
from pathlib import Path

import UnityPy
from UnityPy.helpers.TypeTreeGenerator import TypeTreeGenerator


WRITER_CLASSES = {"SignalInfo", "ConnectionInformation", "RecordingButtonEffect"}


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("data", type=Path)
    args = parser.parse_args()
    data = args.data.resolve()
    candidates = [path for path in data.iterdir() if path.is_file()]

    class_counts = {class_name: 0 for class_name in WRITER_CLASSES}
    for asset_path in candidates:
        try:
            env = UnityPy.load(str(asset_path))
            generator = TypeTreeGenerator(env.file.unity_version)
            generator.load_local_dll_folder(str(data / "Managed"))
            env.typetree_generator = generator
        except Exception:
            continue

        found = []
        for obj in env.objects:
            if obj.type.name != "MonoBehaviour":
                continue
            try:
                head = obj.parse_monobehaviour_head()
                script = head.m_Script.deref_parse_as_object()
                class_name = script.m_ClassName
                if class_name not in WRITER_CLASSES:
                    continue
                class_counts[class_name] += 1
                tree = obj.read_typetree()
            except Exception:
                continue
            deltas = [int(value) for value in tree.get("m_TagsToIncrease", [])]
            nonzero = [(index, value) for index, value in enumerate(deltas) if value]
            if nonzero or class_name == "RecordingButtonEffect":
                found.append(
                    (
                        class_name,
                        obj.path_id,
                        tree.get("m_strName", ""),
                        int(tree.get("m_CreationIdx", -1)),
                        nonzero,
                    )
                )
        if found:
            print(asset_path.name)
            for row in found:
                print(row)
    print("class counts", class_counts)


if __name__ == "__main__":
    main()
