"""REAPER project -> Guitar Pro 7/8 (.gp), Guitar Pro 5 (.gp5) or MusicXML, in one command.

usage: export_gp.py <project.rpp | .dawproject | stems folder> <out.gp|.gp5|.musicxml|.mxl> <track> [<track> ...]
                    [--also OUT ...] [--cache DIR] [--force] [--drum-map JSON] [--tempo BPM|auto] [--section BAR=NAME ...]
                    [--chords NAME=trackA+trackB] [--harmony trackA+trackB] [--clean-bass]

Each <track> is a track name as shown in REAPER (case-insensitive, must be unique) or a 0-based
track index (as returned by the reaper MCP get_selected_tracks). Folder tracks are expanded to
their children. MIDI tracks are read from the .rpp; audio tracks are transcribed with basic-pitch
(results cached per track index in --cache, default <project dir>/gp_export_cache; delete a
<idx>.json there to force re-transcription).

"NAME=trackA+trackB" writes several audio tracks as ONE Guitar Pro track (e.g. a lead vocal split
over several tracks by section). A drum folder made of audio mics (name contains "drum"/"batterie",
no MIDI inside) is transcribed by drums_audio.py into one percussion track.

The project is a REAPER .rpp or, for any other DAW, a folder of stems + MIDI files (see
project.py: one track per audio file, sub-folders are folder tracks, MIDI files give the tempo).

--tempo overrides the project tempo (audio recorded to a click while the project kept REAPER's
default 120 BPM, or stems without MIDI); "auto" detects it from the drums (tempo.py). --section 20="Couplet 1" sets section markers by bar number
instead of the project markers.

--chords writes a rhythm guitar as strummed chords with chord names instead of transcribed notes:
the chords are detected from the --harmony tracks (default: the --chords tracks) plus the bass
tracks, the rhythm comes from the --chords tracks' attacks (see harmony.py). --clean-bass cleans
transcribed bass lines (octaves, leaps, passing-note parasites; see bass_fix.py).

A .gp output is built as GP5 and converted with alphaTab (Node.js, gp_export/gp7; npm ci runs on
first use). Only .gp files can then get an audio track (add_backing.py) or clean_bass.py.

A .musicxml (or compressed .mxl) output opens in Finale, MuseScore, Dorico, Sibelius... (musicxml.py:
standard + TAB staves for bass/guitars, chord names with diagrams, sections). --also writes the same
score to more files in one run, e.g. song.gp --also song.musicxml.
"""
import argparse, os, re, sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import project, exporter


def resolve_tracks(trs, specs):
    """Track names or 0-based indices -> indices."""
    out = []
    for s in specs:
        if s.isdigit():
            i = int(s)
            if i >= len(trs):
                sys.exit(f"track index {i} out of range (project has {len(trs)} tracks)")
            out.append(i)
            continue
        hits = [t["index"] for t in trs if t["name"].strip().lower() == s.strip().lower()]
        if not hits:
            sys.exit(f"no track named {s!r}. Tracks: " + ", ".join(f'{t["index"]}={t["name"]!r}' for t in trs))
        if len(hits) > 1:
            sys.exit(f"several tracks are named {s!r} (indices {hits}); pass the index instead")
        out.append(hits[0])
    return out


def parse_sections(items):
    out = {}
    for it in items or []:
        bar, _, name = it.partition("=")
        if not bar.strip().isdigit() or not name.strip():
            sys.exit(f"--section expects BAR=NAME, got {it!r}")
        out[int(bar)] = name.strip()
    return out


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("project")
    ap.add_argument("out")
    ap.add_argument("tracks", nargs="+", help='track names or 0-based indices, or "NAME=trackA+trackB"')
    ap.add_argument("--also", action="append", default=[], metavar="OUT",
                    help="also write the score to this file (.gp, .gp5, .musicxml, .mxl; repeatable)")
    ap.add_argument("--cache")
    ap.add_argument("--force", action="store_true", help="overwrite the output file")
    ap.add_argument("--drum-map", help="drum note map JSON (default gp_export/drum_maps/ezdrummer3.json)")
    ap.add_argument("--tempo", help='BPM overriding the project tempo, or "auto" to detect it')
    ap.add_argument("--section", action="append", metavar="BAR=NAME", help="section marker at a bar (repeatable)")
    ap.add_argument("--chords", action="append", metavar="NAME=trackA+trackB", help="chord track (repeatable)")
    ap.add_argument("--harmony", metavar="trackA+trackB", help="tracks used to detect the chords")
    ap.add_argument("--clean-bass", action="store_true", help="clean transcribed bass tracks")
    a = ap.parse_args()

    P = project.load(a.project)
    trs = P.tracks
    sel, groups = [], []
    for spec in a.tracks:
        if "+" in spec or "=" in spec:
            name, _, members = spec.rpartition("=") if "=" in spec else ("", "", spec)
            idxs = resolve_tracks(trs, [m for m in members.split("+") if m])
            groups.append((name or trs[idxs[0]]["name"], idxs))
        else:
            sel.append(resolve_tracks(trs, [spec])[0])
    chord_specs = []
    for spec in a.chords or []:
        name, _, members = spec.rpartition("=")
        chord_specs.append((name or members, resolve_tracks(trs, [m for m in members.split("+") if m])))
    harm = resolve_tracks(trs, [m for m in a.harmony.split("+") if m]) if a.harmony else None
    tempo = a.tempo
    if tempo not in (None, "auto"):
        try:
            tempo = float(tempo)
        except ValueError:
            sys.exit(f"--tempo expects a number or 'auto', got {tempo!r}")
    exporter.export(a.project, [a.out] + a.also, sel=sel, groups=groups, chord_specs=chord_specs,
                    harmony_idxs=harm, tempo=tempo, sections=parse_sections(a.section),
                    clean_bass=a.clean_bass, drum_map=a.drum_map, cache=a.cache, force=a.force)


if __name__ == "__main__":
    main()
