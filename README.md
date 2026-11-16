# reaper_to_gp

Turn a [REAPER](https://www.reaper.fm/) project into a Guitar Pro score: MIDI tracks become notation, audio tracks are transcribed, and the result can be cleaned up and paired with an embedded, synced audio track in Guitar Pro 8.

Built and tested on Windows with REAPER 7, Guitar Pro 8.1 and Toontrack EZdrummer 3 / EZkeys 2.

## What it does

| Script | Purpose |
|---|---|
| `gp_export/export_gp.py` | Selected REAPER tracks → `.gp5` (opens in Guitar Pro 5–8). Folder tracks are expanded. MIDI is read from the `.rpp`; audio is transcribed with Spotify's [basic-pitch](https://github.com/spotify/basic-pitch). Keeps time-signature changes and markers (as sections). |
| `gp_export/clean_bass.py` | Cleans a transcribed bass in a Guitar Pro 7/8 `.gp`: fixes octave errors by checking the bass audio, merges fragmented notes, removes quiet off-kick parasites, re-frets. |
| `gp_export/add_backing.py` | Mixes REAPER tracks (e.g. stems) into one MP3 and embeds it as the Guitar Pro 8 audio track, synced to bar 1. |
| `gp_export/inspect_rpp.py` | Prints a project's tempo/time-signature map, markers, folder tree and items. |

## Install

Requires [uv](https://docs.astral.sh/uv/) (`winget install astral-sh.uv`). It provides Python 3.11 itself.

```powershell
git clone <this repo> && cd reaper_to_gp
uv sync
```

## Usage

Save the REAPER project first: the scripts read the `.rpp` from disk. Tracks are given by their REAPER name (case-insensitive); a folder track exports all its children. When two tracks share a name, pass the 0-based track index instead (`inspect_rpp.py` lists them).

```powershell
# 1. Export the "Drums" and "Bass" tracks to Guitar Pro 5
uv run python gp_export/export_gp.py "D:\Music\Song\Song.rpp" "D:\Music\Song\Song.gp5" Drums Bass

# 2. Open the .gp5 in Guitar Pro 8 and save it as .gp, then clean the bass
uv run python gp_export/clean_bass.py "D:\Music\Song\Song.gp" "D:\Music\Song\Song.rpp" --track Bass

# 3. Embed the guitar stem as the audio track
uv run python gp_export/add_backing.py "D:\Music\Song\Song.gp" "D:\Music\Song\Song.rpp" "Guitars - stem"
```

`clean_bass.py` and `add_backing.py` write a `*.before-*.gp` backup before modifying the file (or use `--out`). Transcriptions are cached in `<project dir>/gp_export_cache/`.

### MIDI inside plugins

Patterns written inside EZdrummer/EZkeys (their own song track) are not visible to REAPER. Drag them from the plugin onto the REAPER timeline as MIDI items before exporting.

## Limitations

- **Audio transcription is approximate.** Bass is usable after `clean_bass.py`; distorted guitars, clean/solo guitars and vocals are rough drafts at best. MIDI tracks are the reliable part.
- **Everything is quantized to 16th notes** (triplets and flams are simplified).
- **Constant tempo only.** Time-signature changes are supported, tempo changes are not.
- **Drum note map.** EZdrummer uses non-GM notes for articulations (hi-hat variants 12–26 and 60–64, ride edge on 52…). `gp_export/drum_maps/ezdrummer3.json` folds them into the GM notes Guitar Pro understands; it was inferred from EZdrummer 3's own groove database and articulation names, and each entry says where it comes from. Toontrack maps can differ per kit (e.g. 52 is China in the generic map but Ride Edge in some kits): copy the file, adjust it and pass `--drum-map my_kit.json`.
- **GP5 has no notation-only staff**, so keys and vocals are written on 7-"string" pseudo-instruments; switch them to standard notation in Guitar Pro 7/8.
- **Guitar Pro 8 audio track:** the format is undocumented; the layout follows [alphaTab](https://github.com/CoderLine/alphaTab)'s GPIF writer and was verified in Guitar Pro 8.1.4.

## Optional: drive REAPER from Claude Code

The repo is set up to work with [Claude Code](https://claude.com/claude-code) and the [TwelveTake REAPER MCP server](https://github.com/TwelveTake-Studios/reaper-mcp), which lets the assistant read the current selection and project:

```powershell
uvx twelvetake-reaper-mcp --install-bridge --autostart
copy .mcp.json.example .mcp.json
```

Then run the bridge script in REAPER (it starts automatically on the next launch with `--autostart`). `CLAUDE.md` holds the notes for the assistant.

## License

MIT, see [LICENSE](LICENSE). Dependencies keep their own licenses (basic-pitch: Apache-2.0, PyGuitarPro: LGPL-3.0).
