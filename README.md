# FREEQ — Python desktop port

## Original content is not included

This public source repository intentionally excludes the original FREEQ audio,
images, extracted Unity data, decompiled assemblies, IPA contents, packaged
executables, and other proprietary artifacts. Those files remain local and are
ignored by Git. FREEQ is no longer commercially available; reconstructing a
playable build requires separately supplying the original game files. This
repository does not provide or authorize redistribution of those files.

See `attribution.txt` for the preservation notice and rights attribution.

This project ports the supplied iOS Unity build of **FREEQ** to Python and
pygame. The original serialized story graph is preserved: 73 transmissions,
143 referenced connection choices (from 168 scene records), 67 state tags,
bit-mask gates, comparisons, notes, achievements, act transitions, and the
original referenced voice audio.

## Run on Windows

The included project-local virtual environment already contains pygame. Start
the game with:

```powershell
.\run_freeq.bat
```

Or run it directly:

```powershell
.\.venv\Scripts\python.exe .\freeq_port\freeq.py
```

For a fresh checkout, create the requested local virtual environment first:

```powershell
py -3 -m venv .venv
.\.venv\Scripts\python.exe -m pip install -r requirements.txt
```

## Keyboard controls

- `WASD` or arrow keys: move through the Aether
- `Tab` / `Shift+Tab`: jump between active signals
- `Enter` or `E`: intercept, select, or confirm
- On Yes/No prompts, arrows or `Tab` choose an option and `Enter` activates it
- `Esc`: cancel or go back
- `N`: notes
- `L`: achievements
- `Space`: pause/resume transmission audio
- `R`: replay transmission audio
- `S`: skip transmission audio
- `F1`: controls screen
- `F2`: toggle accessibility audio (enabled by default)
- `F11`: fullscreen

Progress is saved automatically to `freeq_port/savegame.json` after every
completed transmission.

## Accessibility audio

The original accessibility layer is enabled by default. In Aether mode,
`horizlock` and `vertical` play on separate channels and grow louder as the
receiver aligns with a signal's horizontal and vertical axes. `lockon` sounds
when either axis aligns and repeats while the signal is fully acquired.

The original movement soundscape is also restored: `aether` loops as the
ambient background, while positional `brown_noise` grows louder and pans toward
the nearest signal as the receiver moves around.

Menus and the switchboard use the original spoken clips for mode changes,
caller/callee names, available connections, confirmation, help, notes, pause,
replay, and skip. Press `F2` at any time to turn this layer off or back on.

Active Aether signals retain stable positions. When a transmission is removed,
replacement signals are placed away from the receiver so the horizontal and
vertical guides begin unaligned instead of immediately locking to a new call.

## Porting notes

Story parity can be checked with:

```powershell
.\.venv\Scripts\python.exe tools\audit_story_paths.py --coverage-runs 200 --json
```

The original asset graph contains 73 signal records and 143 connection records.
Restored-content mode is enabled by default and makes all 143 finished
connection recordings selectable. Restored choices use the same switchboard
labels as original choices. Eight unlabelled boundary/writer adjustments keep the repaired
variants partitioned and close the original final-choice condition gap. The
three `a2-vtest-*` developer signals remain dormant.

The extracted original conditions remain unchanged in `game_data.json`; the
eleven recovered recordings and eight boundary/writer adjustments are isolated
in `restored_content.json`. Their source trace and rationale are recorded in
`original_unity_reference/alternate_branch_trace.md`. To run with the exact
shipped gates instead, set `$env:FREEQ_RESTORED_CONTENT='0'` before launching
from PowerShell. Restored mode routes the original Act 3 zero-connection gap to
its existing `Nothing` / feedback recording; original-data mode preserves the
shipped conditions exactly.

The core logic in `freeq_port/engine.py` is a direct translation of the
original `TagComparison`, `ASASpawnManager`, `ActTransitionManager`, and
connection flow. Touch/tilt input was replaced with keyboard movement and
selection while retaining the original masks, tag mutations, conditions,
signal ordering, automatic hijacks, audio, notes, and endings.

When an ending reaches the credits, Prism reads the complete credits screen
through the best available screen-reader or Windows speech backend.
Press `R` on that screen to read it again.
Opening Help / Controls also reads every keyboard command through Prism after
the original help recording finishes. Press `R` on the help screen to repeat
the controls.
The Achievements screen announces the unlocked count and current achievement
through Prism. Use Up/Down to browse and `R` to repeat the selected name.

## Distribution build

Run `build_freeq.bat` to install the build dependency into the project virtual
environment and create the single-file Windows application at `dist\FREEQ.exe`.
Packaged saves are stored under `%LOCALAPPDATA%\FREEQ Python Port` so they
survive the temporary extraction directory used by the executable.
The package-aware `freeq_main.py` entry point also supports `--smoke-test` for
an automated packaged-resource startup check.

`tools/extract_game_data.py` documents the repeatable extraction process. It
requires UnityPy only for development; the game itself depends only on pygame.
