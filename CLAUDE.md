# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

reaper_to_gp: tools that turn REAPER (DAW) projects, DAWproject files (Bitwig/Studio One/Cubase 14+), or stems + MIDI folders from any DAW, into Guitar Pro files, on Windows. See README.md for the user-facing overview.

## REAPER MCP

`.mcp.json` (local, git-ignored; template in `.mcp.json.example`) registers the TwelveTake `reaper` MCP server (`uvx twelvetake-reaper-mcp`; use the full path to `uvx.exe` if the WinGet PATH entry is not loaded). It talks to REAPER through a Lua bridge (`%APPDATA%\REAPER\Scripts\reaper_mcp_bridge.lua`, optionally autostarted from `__startup.lua`) by exchanging JSON files in `%APPDATA%\REAPER\Scripts\mcp_bridge_data`.

- A tool timeout means REAPER is closed or the bridge is not running.
- Start with `get_project_summary`. Track indices are 0-based and **shift whenever the user adds/removes tracks** — re-query (`get_all_tracks`) instead of reusing indices from earlier in the conversation.
- `get_midi_notes` on a full drum item exceeds the tool output limit: pass `fields=[...]` and expect the result to be saved to a file you then process with a script.
- `get_item_info` does not expose the source file path, source offset or takes. For anything that needs the audio itself, parse the saved `.rpp` instead (ask the user to save first; check the file mtime).
- MIDI that lives inside an instrument plugin (EZdrummer/EZkeys song tracks) is invisible to REAPER and the MCP until the user drags it onto the timeline.

## Environment & commands

Python is managed by `uv`; `pyproject.toml` pins Python 3.11 for basic-pitch. Writing `.gp` needs Node.js: `gp_export/gp7` holds a pinned alphaTab (`npm ci` on first use, `node_modules` git-ignored). The user wants `.gp` output only, never leftover `.gp5`.

```powershell
uv sync                                                # create .venv
uv run python gp_export/export_gp.py <project.rpp|.dawproject|stems dir> <out.gp> <track name|idx|NAME=a+b>... [--cache DIR] [--force] [--drum-map JSON]
        [--tempo BPM|auto] [--section BAR=NAME]... [--chords NAME=a+b] [--harmony a+b+c] [--clean-bass]
uv run python gp_export/clean_bass.py <score.gp> <project.rpp> [--track Bass] [--out OUT.gp]
uv run python gp_export/add_backing.py <score.gp> <project.rpp> "<rpp track name>"... [--name NAME] [--out OUT.gp]
uv run python gp_export/inspect_rpp.py <project.rpp|stems dir>   # tempo/TS map, markers, folder tree, items
uv run python gp_export/tempo.py <project.rpp|stems dir>         # detect a click tempo from the drums
uv run python gp_export/build_gp.py <project.rpp> <transcriptions_dir> <out.gp5> <track_idx>...   # skip transcription
```

Dependency constraints in `pyproject.toml` are load-bearing: TensorFlow is excluded via `override-dependencies` (TF 2.14 crashes with the numpy it would get; basic-pitch falls back to its ONNX model), `numpy<2` and `setuptools<81` (resampy imports `pkg_resources`). The basic-pitch "tflite/Tensorflow is not installed" warnings are expected.

There are no tests. Each writer validates its own output: `build_gp.py` re-parses the `.gp5` and checks every measure sums to its time signature; `clean_bass.py` and `add_backing.py` re-read the written `.gp`. Keep those checks passing.

## gp_export architecture

Pipeline: REAPER track selection → notes in quarter-note time → 16th-note grid chords → Guitar Pro 5 via PyGuitarPro → (for a `.gp` output) GP7/8 through alphaTab's `Gp7Exporter` (`gp7/gp5togp.mjs`, temp `.tmp.gp5` deleted); then optional in-place post-processing of the `.gp`.

- `project.py` — the only entry point for reading a project: `project.load(path)` (cached per path+mtime) returns `.tracks` (dicts with `items`, `fx`, `drums`, `depth`, `is_folder`), `.info` (rpp.project_info shape) and `.dir`/`.name`, from a `.rpp`, a `.dawproject` (`dawproject.py`) or a stems folder (audio files = tracks, sub-folders = folder tracks, MIDI files → tracks with REAPER-style `E` events at the file's first tempo + tempo/TS/markers). Item `file` paths are absolute. Modules must not call `rpp` directly; copy `info` before mutating it (it is cached).
- `dawproject.py` — zip + `project.xml` (spec: github.com/bitwig/dawproject `Project.xsd`). Walks the arrangement timeline with a context mapping content time to timeline seconds (`A + R * seconds(x, unit)`, visible window `[w0, w1)`): `timeUnit` beats/seconds inherited downwards; `Clip` = time/duration in the parent unit, `playStart`/loops in `contentTimeUnit`, nested clips; `Warps` = one linear segment per warp pair (R = stretch, item `playrate = 1/R`); notes → `project.midi_item`. Group tracks (nested `Track`, contentType `tracks`) are folders; `Channel/Mute` mutes items. Embedded audio extracted to `gp_export_cache/dawproject_media/<name>/`. Only tested on synthetic files built from the spec (Bitwig-style two-level warped clips): validate on a real DAW export when one is available.
- `tempo.py` — `--tempo auto`: librosa beat tracking on the drum tracks, linear fit; rounds to an integer BPM when within 0.15.
- `rpp.py` — minimal `.rpp` parser (used by `project.py`). Child chunks are also recorded inline in `Node.lines` as `["<CHILD>", node]` so multi-take items can be split on `TAKE` lines; the active take is the one whose `TAKE` line has `SEL` (else take 0). Folder depth comes from `ISBUS <flag> <delta>`. Time signatures live in `TEMPOENVEX` `PT` lines, field 3 = `(den << 16) | num`.
- `transcribe.py` — rebuilds each audio track from its items (source file, `SOFFS`, playrate, loop) into one mono 22.05 kHz buffer, runs basic-pitch with a per-instrument profile chosen from the track name (`profile()`), and caches `<idx>.json` (times in seconds). Delete a cached json to re-transcribe.
- `build_gp.py` — MIDI notes come straight from the `E` events (MIDI tracks named like bass/guitar/vocal per `transcribe.profile` are fretted, other MIDI = keys); audio notes from the cache. `build_measures` reproduces time-signature changes (tempo changes are not supported, only warned). `to_chords` quantizes and limits polyphony; `Fretter` assigns string/fret by DFS (fret-span limit only for bass/guitar); `fill_track` splits chords at barlines and into note values, writing ties and rests. GP5 has no notation-only piano, so keys/vocals use 7-"string" pseudo-tunings (`TUNINGS`), keys split into MD/MG tracks at middle C. Drums go on a percussion track with fret = GM note; the plugin→GM map is loaded from `drum_maps/*.json` (`--drum-map`, default `ezdrummer3.json`). That map was derived from EZdrummer's SQLite groove DB (`%APPDATA%\Toontrack\EZdrummer 3\MidiDB`: `MIDI_INFO` blobs are 5-byte records whose byte 4 is the note, `REL_ENT_KITS`/`KITPIECES` list the pieces each groove uses) plus `LeadKey`/`From "<articulation>"` pairs in `C:\ProgramData\Toontrack\EZdrummer 3\*.midtrackinfo` (written when MIDI is dragged out of the plugin; kit-specific, so it wins over the generic DB — e.g. 52 = Ride Edge, not China). Read a copy of `MidiDB`, never the live file.
- In practice only drums (MIDI) and bass (transcribed, then `clean_bass.py`) came out usable; transcribed distorted/clean/solo guitars, vocals and the keys split were judged barely usable. Don't oversell audio transcription beyond bass; default to MIDI + bass unless asked.
- `gpif.py` — read/rewrite one single-voice stringed track in a GP7/8 `.gp` (zip + `Content/score.gpif`, via lxml to keep CDATA). GP8 shares identical Beat/Note elements between positions, so `rewrite_track` always creates fresh elements and prunes orphans; containers contain XML comments, so use `findall(tag)`. GPIF `String` is 0-based from the lowest string, `Midi` is the real pitch.
- `clean_bass.py` — post-processes a transcribed bass in a `.gp`: octave fix by checking odd-harmonic energy of the lower octave in the bass audio rebuilt from the `.rpp` (threshold `OCT_RATIO`), fragment merge unless re-attack on a kick, removal of quiet off-kick 16ths (`PARASITE_AMP`, needs the transcription cache), re-fretting. Writes `<name>.before-bass-cleanup.gp` before overwriting. Typical effect: ~20% fewer notes, octave fixes on most notes reported an octave too high.
- `add_backing.py` — uses the score's tempo automation (not the project's) for the sync points; embeds a mix of named `.rpp` tracks as the GP8 audio track (GP8 allows only one): stereo 44.1 kHz MP3 from project time 0 at `Content/Assets/backing-track.mp3`, `BackingTrack` after `MasterTrack`, `Assets` after `MasterBars`, SyncPoints (frames @ 44.1 kHz) at first/last bar. Element layout copied from alphaTab's `GpifWriter.ts` (no official spec); verified to open and play in Guitar Pro 8.1.4. Backup `<name>.before-backing.gp`.
- `export_gp.py` — orchestrator: expands selected folders, transcribes audio tracks (cache default `<project dir>/gp_export_cache`), then builds. Refuses to overwrite without `--force`. `NAME=a+b` = groups (several tracks → one GP track, e.g. a lead vocal split by section); an audio-only folder named drum/batterie goes to `drums_audio.py`.
- Multitrack recordings imported into REAPER usually keep the default 120 BPM with no markers. Detect the real tempo before exporting (librosa beat tracking on the kick/snare/hh mics, then a linear fit: a residual of ~20 ms means it was recorded to a click from time 0) and pass `--tempo`; propose sections from per-bar instrument activity and pass `--section`.
- `drums_audio.py` — onset detection per close mic on a band-limited signal; bleed rejected by comparing each hit's level ratio to a reference mic against the median ratio (`ratio_k`). Hi-hat open = long high-band decay (longer when a snare hit coincides); crash = long decay in the overheads. Output = cache json with profile kind `drums` (already GM, the plugin drum map is skipped).
- `harmony.py` — beat-synchronous chroma of the harmony tracks (loudness-weighted, chord track 1.5x) + bass chroma for the root, maj/m/5/sus2/sus4 templates, Viterbi smoothing, min 2 beats per chord. Strums from the chord track's onsets; a chord with no strum is held. Voicings: open shapes table, else E/A-shape barres (standard tuning). `build_gp.chord_diagram` attaches names/diagrams.
- `bass_fix.py` — note-list bass cleanup at export (`--clean-bass`): picks one note per 16th (chord root > chord tone > loudest), `clean_bass.Spectra` octave check, leaps > 9 semitones from the neighbours' median moved by octaves, range E1–F#3, removes short off-kick non-chord/quiet notes, merges fragments. Kicks come from the exported drum track.
