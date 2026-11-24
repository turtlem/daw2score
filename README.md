# reaper_to_gp

Turn a [REAPER](https://www.reaper.fm/) project, a [DAWproject](https://github.com/bitwig/dawproject) file (Bitwig Studio, Studio One, Cubase 14+) — or stems and MIDI files exported from any DAW — into a Guitar Pro score: MIDI tracks become notation, audio tracks are transcribed (pitched instruments with basic-pitch, multitrack drums from the close mics, rhythm guitars as named chords), and the result can be paired with an embedded, synced audio track in Guitar Pro 8.

Built and tested on Windows with REAPER 7, Guitar Pro 8.1 and Toontrack EZdrummer 3 / EZkeys 2.

## What it does

| Script | Purpose |
|---|---|
| `gp_export/export_gp.py` | Selected REAPER tracks → Guitar Pro 7/8 `.gp` (or `.gp5`). Folder tracks are expanded. MIDI is read from the `.rpp`; audio is transcribed with Spotify's [basic-pitch](https://github.com/spotify/basic-pitch). Keeps time-signature changes and markers (as sections). Options for recordings: tempo override, sections by bar, merged tracks, audio drums, chord tracks, bass cleanup (see below). |
| `gp_export/drums_audio.py` | Multitrack drum recording (kick / snare / toms / hi-hat / overheads mics) → GM drum hits. Used automatically by `export_gp.py` for a drum folder without MIDI. |
| `gp_export/harmony.py` | Chord detection from the guitars + bass audio, written as strummed chords with chord names and diagrams, following the guitar's own attacks (`--chords`). |
| `gp_export/bass_fix.py` | Cleans a transcribed bass while exporting (`--clean-bass`): octave errors, incoherent leaps, passing-note parasites, fragments. |
| `gp_export/clean_bass.py` | Same idea on an existing Guitar Pro 7/8 `.gp`, for MIDI-drum projects: fixes octave errors by checking the bass audio, merges fragmented notes, removes quiet off-kick parasites, re-frets. |
| `gp_export/add_backing.py` | Mixes REAPER tracks (e.g. stems) into one MP3 and embeds it as the Guitar Pro 8 audio track, synced to bar 1. |
| `gp_export/tempo.py` | Detects the tempo of a recording played to a click (`--tempo auto`) and warns if the beat grid does not start at 0 s. |
| `gp_export/project.py` | Reads the input: a REAPER `.rpp`, a `.dawproject` or a stems + MIDI folder, into one DAW-independent model. |
| `gp_export/dawproject.py` | DAWproject reader: tracks and group tracks, audio clips (embedded or external, time-stretched), note clips (loops), markers, time signatures. |
| `gp_export/inspect_rpp.py` | Prints a project's (or stems folder's) tempo/time-signature map, markers, folder tree and items. |

## Install

Requires [uv](https://docs.astral.sh/uv/) (`winget install astral-sh.uv`), which provides Python 3.11 itself, and [Node.js](https://nodejs.org/) to write `.gp` files (the GP5 → GP7/8 conversion uses [alphaTab](https://github.com/CoderLine/alphaTab); `npm ci` runs in `gp_export/gp7` on first use).

```powershell
git clone <this repo> && cd reaper_to_gp
uv sync
```

## Usage

Save the REAPER project first: the scripts read the `.rpp` from disk. Tracks are given by their REAPER name (case-insensitive); a folder track exports all its children. When two tracks share a name, pass the 0-based track index instead (`inspect_rpp.py` lists them).

```powershell
# 1. Export the "Drums" and "Bass" tracks to Guitar Pro 8
uv run python gp_export/export_gp.py "D:\Music\Song\Song.rpp" "D:\Music\Song\Song.gp" Drums Bass

# 2. Clean the bass (MIDI drums project; for recordings use --clean-bass at export instead)
uv run python gp_export/clean_bass.py "D:\Music\Song\Song.gp" "D:\Music\Song\Song.rpp" --track Bass

# 3. Embed the guitar stem as the audio track
uv run python gp_export/add_backing.py "D:\Music\Song\Song.gp" "D:\Music\Song\Song.rpp" "Guitars - stem"
```

### Bitwig Studio, Studio One, Cubase 14+: DAWproject

Export the song as `.dawproject` from the DAW (export or save-as menu, depending on the DAW) and pass that file instead of a `.rpp`. Tracks, group tracks (as folders), audio and MIDI clips, tempo, time signatures and markers are read directly; no stems needed. Embedded audio is extracted once to `gp_export_cache/dawproject_media/`.

```powershell
uv run python gp_export/export_gp.py "D:\Music\Song.dawproject" "D:\Music\Song.gp" Drums Bass
```

Instrument tracks are read as their MIDI notes (like REAPER). Tempo automation is not supported (constant tempo only).

### Other DAWs: stems + MIDI folder

For DAWs without DAWproject (Ableton Live, Logic, Pro Tools, FL Studio, older Cubase…), any DAW (Ableton Live, Logic, Cubase, Pro Tools, FL Studio, Bitwig, Studio One…) can export stems and MIDI. Export every track **from the song start** (bar 1, so that all files start together) and pass the folder instead of a `.rpp`:

```
Song/
  Bass.wav                 one track per audio file (wav, flac, aif, ogg, mp3), named after the file
  Guitar front.wav
  Guitar back.wav
  Drums/                   a sub-folder is a folder track (here: drum mics, transcribed hit by hit)
    Kick.wav
    Snare top.wav
    HH.wav
    OH L.wav
  song.mid                 optional: each MIDI track becomes a track (channel 10 = drums);
                           tempo, time-signature changes and markers are read from it
```

```powershell
uv run python gp_export/export_gp.py "D:\Music\Song" "D:\Music\Song.gp" Drums Bass `
    --chords "Rhythm=Guitar front+Guitar back" --clean-bass --tempo auto
```

Without a MIDI file, the tempo is unknown: use `--tempo BPM` or `--tempo auto` (constant tempo, played to a click). `add_backing.py` and `clean_bass.py` accept the folder too. MIDI tracks named like a bass, guitar or vocal line are fretted as such; other MIDI tracks are written as keys.

### Multitrack recordings

For a band recorded to a click and imported into REAPER (project left at the default 120 BPM, drums as separate mics, a part split over several tracks):

```powershell
uv run python gp_export/export_gp.py Song.rpp Song.gp Drums "Bass=Bass DI" `
    "Vocals=Lead verse+Lead chorus" `
    --chords "Rhythm=Gtr front+Gtr back" --harmony "Gtr front+Gtr back+Lead gtr" `
    --clean-bass --tempo auto --section 3=Intro --section "20=Verse 1" --section "58=Chorus"
```

- `--tempo` overrides the project tempo (`--tempo auto` detects it); `--section BAR=NAME` places section markers by bar.
- `NAME=trackA+trackB` writes several audio tracks as one Guitar Pro track.
- A folder named like `drums`/`batterie` with audio mics only is transcribed by `drums_audio.py` (mic roles come from the track names: kick, snare, tom hi/mid/lo, hh, oh, cowbell; rooms and shakers are ignored).
- `--chords` writes the guitar as chords detected from the `--harmony` tracks plus the bass.

`clean_bass.py` and `add_backing.py` write a `*.before-*.gp` backup before modifying the file (or use `--out`). Transcriptions are cached in `<project dir>/gp_export_cache/`.

### MIDI inside plugins

Patterns written inside EZdrummer/EZkeys (their own song track) are not visible to REAPER. Drag them from the plugin onto the REAPER timeline as MIDI items before exporting.

## Limitations

- **Audio transcription is approximate.** Bass is usable after cleanup; distorted guitars, clean/solo guitars and vocals are rough drafts at best. MIDI tracks are the reliable part.
- **Audio drums:** kick, snare and toms (close mics) are reliable; hi-hat open/closed and crashes are approximate; ride and hi-hat pedal are not detected.
- **Chords:** major, minor, power (5), sus2 and sus4 only, at most one change per 2 beats; check them by ear. Voicings assume standard tuning.
- **Everything is quantized to 16th notes** (triplets and flams are simplified).
- **Constant tempo only.** Time-signature changes are supported, tempo changes are not (recordings must be played to a click).
- **Drum note map.** EZdrummer uses non-GM notes for articulations (hi-hat variants 12–26 and 60–64, ride edge on 52…). `gp_export/drum_maps/ezdrummer3.json` folds them into the GM notes Guitar Pro understands; it was inferred from EZdrummer 3's own groove database and articulation names, and each entry says where it comes from. Toontrack maps can differ per kit (e.g. 52 is China in the generic map but Ride Edge in some kits): copy the file, adjust it and pass `--drum-map my_kit.json`.
- **The score is built as GP5 first**, which has no notation-only staff: keys and vocals are written on 7-"string" pseudo-instruments; switch them to standard notation in Guitar Pro 8.
- **Guitar Pro 8 audio track:** the format is undocumented; the layout follows [alphaTab](https://github.com/CoderLine/alphaTab)'s GPIF writer and was verified in Guitar Pro 8.1.4.

## Optional: drive REAPER from Claude Code

The repo is set up to work with [Claude Code](https://claude.com/claude-code) and the [TwelveTake REAPER MCP server](https://github.com/TwelveTake-Studios/reaper-mcp), which lets the assistant read the current selection and project:

```powershell
uvx twelvetake-reaper-mcp --install-bridge --autostart
copy .mcp.json.example .mcp.json
```

Then run the bridge script in REAPER (it starts automatically on the next launch with `--autostart`). `CLAUDE.md` holds the notes for the assistant.

## License

MIT, see [LICENSE](LICENSE). Dependencies keep their own licenses (basic-pitch: Apache-2.0, PyGuitarPro: LGPL-3.0, alphaTab: MPL-2.0).
