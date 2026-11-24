# daw2score

[![Ko-fi](https://img.shields.io/badge/Ko--fi-support-FF5E5B?logo=ko-fi&logoColor=white)](https://ko-fi.com/vincentmouge)

Turn a [REAPER](https://www.reaper.fm/) project, a [DAWproject](https://github.com/bitwig/dawproject) file (Bitwig Studio, Studio One, Cubase 14+) — or stems and MIDI files exported from any DAW — into a Guitar Pro score (or MusicXML for Finale, MuseScore, Dorico, Sibelius): MIDI tracks become notation, audio tracks are transcribed (pitched instruments with basic-pitch, multitrack drums from the close mics, rhythm guitars as named chords), and the result can be paired with an embedded, synced audio track in Guitar Pro 8.

Built and tested on Windows with REAPER 7, Guitar Pro 8.1 and Toontrack EZdrummer 3 / EZkeys 2. macOS builds (Apple Silicon and Intel) are produced and self-tested on GitHub Actions.

## What it does

| Script | Purpose |
|---|---|
| `gp_export/export_gp.py` | Selected REAPER tracks → Guitar Pro 7/8 `.gp`, `.gp5` or MusicXML (`.musicxml`, `.mxl`). Folder tracks are expanded. MIDI is read from the `.rpp`; audio is transcribed with Spotify's [basic-pitch](https://github.com/spotify/basic-pitch). Keeps time-signature changes and markers (as sections). Options for recordings: tempo override, sections by bar, merged tracks, audio drums, chord tracks, bass cleanup (see below). |
| `gp_export/gui.py` | Export window (Qt): tracks, roles, merged tracks, tempo, sections, formats, audio track; settings remembered per project. |
| `gp_export/sections.py` | Proposes song sections from the tracks (novelty of per-bar levels and harmony), labelled A, B, C… by similarity. |
| `gp_export/musicxml.py` | MusicXML 4.0 writer used for `.musicxml`/`.mxl` outputs: bass and guitars on a standard staff + TAB staff, keys and vocals on real notation staves, drums on a percussion staff, chord names with diagrams, sections as rehearsal marks. |
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

Download the installer from the [Releases](https://github.com/turtlem/daw2score/releases) page. Everything is bundled: Python, the transcription models and Node.js.

### Windows 10/11 (64-bit)

Run `daw2score-<version>-setup.exe`. It needs no administrator rights (installs for the current user; choose "all users" in the first dialog if you prefer).

The installer is not code-signed yet: Windows SmartScreen may show "Windows protected your PC" — click *More info* → *Run anyway*.

- **Start:** daw2score in the Start menu (or drop a project on the window).
- **From REAPER:** *Actions → Show action list → New action → Load ReaScript…* and pick `reaper\daw2score_export.lua` in the install folder (default `%LOCALAPPDATA%\Programs\daw2score`). The action saves the project if needed and opens the window on it; give it a shortcut or a toolbar button.
- **Updates:** *?* (top right) → *Check for updates*. Installing a new version over the old one keeps your settings.
- **Problems:** the log is `%LOCALAPPDATA%\daw2score\daw2score.log` (link in the *?* dialog); attach it to a [GitHub issue](https://github.com/turtlem/daw2score/issues). `daw2score.exe --selftest report.txt` checks an installation end to end.
- **Uninstall:** Windows *Settings → Apps*. Settings and the log in `%LOCALAPPDATA%\daw2score` are kept.

### macOS 12+ (Apple Silicon or Intel)

Open `daw2score-<version>-macos-arm64.dmg` (M1/M2/M3/M4… Macs) or `-macos-x86_64.dmg` (Intel Macs) and drag `daw2score.app` onto *Applications*.

The app is not notarized by Apple yet. On the first launch macOS refuses to open it: go to *System Settings → Privacy & Security* and click *Open Anyway* (macOS 15+), or right-click the app → *Open* (macOS 14 and earlier). Only once.

- **From REAPER:** *Actions → Show action list → New action → Load ReaScript…* and pick `daw2score_export.lua` from the disk image (copy it somewhere first, e.g. REAPER's `Scripts` folder). It finds the app in `/Applications` or `~/Applications`.
- You can also drop a `.rpp`, a `.dawproject` or a stems folder on the app's Dock icon.
- **Log:** `~/Library/Application Support/daw2score/daw2score.log`. **Uninstall:** move the app to the Bin.

## Install from source (development)

Requires [uv](https://docs.astral.sh/uv/) (`winget install astral-sh.uv`), which provides Python 3.11 itself, and [Node.js](https://nodejs.org/) to write `.gp` files (the GP5 → GP7/8 conversion uses [alphaTab](https://github.com/CoderLine/alphaTab); `npm ci` runs in `gp_export/gp7` on first use).

```powershell
git clone <this repo> && cd daw2score
uv sync
uv sync --extra gui      # optional: the export window (PySide6)
uv run python gp_export/selftest.py   # end-to-end check (synthetic song -> .gp + .musicxml)
```

### Building the installer

```powershell
winget install JRSoftware.InnoSetup      # once
uv sync --extra gui
uv run python packaging/build.py         # -> dist/daw2score-<version>-setup.exe
```

`build.py` builds for the platform it runs on: it checks that `gp_export/version.py` and `pyproject.toml` agree, adds a pinned Node.js (downloaded once, SHA-256 checked) and the third-party licenses, freezes the window with PyInstaller (`packaging/daw2score.spec`: a folder on Windows, `daw2score.app` on macOS), runs the self-test on the built app, then compiles `packaging/daw2score.iss` (Windows) or makes a `.dmg` (macOS, `hdiutil`).

The GitHub Actions workflow `.github/workflows/build.yml` runs it on Windows, macOS arm64 and macOS Intel (manually from the *Actions* tab, or on a tag). To release: bump the version in both files, add a `CHANGELOG.md` entry, commit, then `git tag vX.Y.Z && git push --tags`: the workflow builds the three installers and attaches them to a **draft** release with the changelog section as notes; check it and publish it (the window's update check reads the latest published release).

## Export window

```powershell
uv run python gp_export/gui.py ["D:\Music\Song\Song.rpp"]
```

Drop a REAPER project, a `.dawproject` or a stems folder on the window, then:

- **Pistes (tracks):** tick the tracks to export and pick their role (drums, bass, distorted / clean / lead guitar, guitar as chords, vocals, keys; *Auto* guesses it from the name). Tracks given the same score name are merged into one score track (e.g. a lead vocal split over several tracks). A folder of drum mics exports as one drum track. *Audio .gp* = mixed into the Guitar Pro 8 audio track; *Accords* = listened to when detecting the chords.
- **Tempo et sections:** project tempo, a typed one, or detection from the drums; sections from the project markers, typed by bar, or proposed automatically from the tracks (changes in levels and harmony; repeated parts get the same letter) and then renamed.
- **Sortie (output):** folder, file name, formats (`.gp`, MusicXML, `.gp5`), bass cleanup, MIDI drum map, audio track name.

The settings are remembered per project (`gp_export_cache/gui_<project>.json` next to the project). The window runs the same export as `export_gp.py` (`exporter.py`). It is in English or French (system language by default, switch in the top-right corner).

## Command line

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

### Other notation programs: MusicXML

Use a `.musicxml` (or compressed `.mxl`) output, or add one to a Guitar Pro export with `--also`:

```powershell
uv run python gp_export/export_gp.py Song.rpp Song.gp Drums Bass --also Song.musicxml
```

MusicXML opens in Finale, MuseScore, Dorico, Sibelius and Guitar Pro. The file is checked against the measure lengths on export and validates against the MusicXML 4.0 schema. The Guitar Pro audio track (`add_backing.py`) has no MusicXML equivalent.

### MIDI inside plugins

Patterns written inside EZdrummer/EZkeys (their own song track) are not visible to REAPER. Drag them from the plugin onto the REAPER timeline as MIDI items before exporting.

## Limitations

- **Audio transcription is approximate.** Bass is usable after cleanup; distorted guitars, clean/solo guitars and vocals are rough drafts at best. MIDI tracks are the reliable part.
- **Audio drums:** kick, snare and toms (close mics) are reliable; hi-hat open/closed and crashes are approximate; ride and hi-hat pedal are not detected.
- **Chords:** major, minor, power (5), sus2 and sus4 only, at most one change per 2 beats; check them by ear. Voicings assume standard tuning.
- **Everything is quantized to 16th notes** (triplets and flams are simplified).
- **Constant tempo only.** Time-signature changes are supported, tempo changes are not (recordings must be played to a click).
- **Drum note map.** EZdrummer uses non-GM notes for articulations (hi-hat variants 12–26 and 60–64, ride edge on 52…). `gp_export/drum_maps/ezdrummer3.json` folds them into the GM notes Guitar Pro understands; it was inferred from EZdrummer 3's own groove database and articulation names, and each entry says where it comes from. Toontrack maps can differ per kit (e.g. 52 is China in the generic map but Ride Edge in some kits): copy the file, adjust it and pass `--drum-map my_kit.json`.
- **The Guitar Pro score is built as GP5 first**, which has no notation-only staff: keys and vocals are written on 7-"string" pseudo-instruments; switch them to standard notation in Guitar Pro 8. The MusicXML output writes them as normal staves.
- **MusicXML:** no key signature is written (accidentals are spelled with sharps or flats from the estimated key); each instrument is a single voice. Validated against the schema and re-imported with alphaTab, not yet opened in Finale or Dorico.
- **Guitar Pro 8 audio track:** the format is undocumented; the layout follows [alphaTab](https://github.com/CoderLine/alphaTab)'s GPIF writer and was verified in Guitar Pro 8.1.4.

## Optional: drive REAPER from Claude Code

The repo is set up to work with [Claude Code](https://claude.com/claude-code) and the [TwelveTake REAPER MCP server](https://github.com/TwelveTake-Studios/reaper-mcp), which lets the assistant read the current selection and project:

```powershell
uvx twelvetake-reaper-mcp --install-bridge --autostart
copy .mcp.json.example .mcp.json
```

Then run the bridge script in REAPER (it starts automatically on the next launch with `--autostart`). `CLAUDE.md` holds the notes for the assistant.

## License

MIT, see [LICENSE](LICENSE). Dependencies keep their own licenses (basic-pitch: Apache-2.0, PyGuitarPro: LGPL-3.0, alphaTab: MPL-2.0, Qt/PySide6: LGPL-3.0); see [THIRD_PARTY_NOTICES.md](THIRD_PARTY_NOTICES.md) for what the installer bundles.
