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
import project, transcribe, build_gp, drums_audio, harmony


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


def is_audio_drum_folder(trs, t):
    if not t["is_folder"] or not re.search(r"drum|batterie", t["name"], re.I):
        return False
    kids = build_gp.expand_selection(trs, [t["index"]])
    return not any(i.get("src_type") == "MIDI" for k in kids for i in k["items"])


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

    outs = [a.out] + a.also
    for o in outs:
        if not o.lower().endswith((".gp", ".gp5") + build_gp.XML_EXT):
            sys.exit(f"unknown output format {o!r}: use .gp, .gp5, .musicxml or .mxl")
        if os.path.exists(o) and not a.force:
            sys.exit(f"{o} already exists (use --force to overwrite)")
    P = project.load(a.project)
    cache = a.cache or os.path.join(P.dir, "gp_export_cache")
    sections = parse_sections(a.section)
    if a.tempo == "auto":
        import tempo
        d = tempo.detect(a.project)
        tempo.report(d)
        b = d["bpm"]
        a.tempo = float(round(b)) if abs(b - round(b)) < 0.15 else round(b, 1)
        print(f"using --tempo {a.tempo:g}")
    elif a.tempo is not None:
        try:
            a.tempo = float(a.tempo)
        except ValueError:
            sys.exit(f"--tempo expects a number or 'auto', got {a.tempo!r}")
    elif os.path.isdir(a.project) and not P.info.get("tempo_source"):
        print("WARNING: stems folder without a MIDI file: tempo 120 assumed (use --tempo BPM or --tempo auto)")

    trs = P.tracks
    sel, groups, drum_folders = [], [], []
    for spec in a.tracks:
        if "+" in spec or "=" in spec:
            name, _, members = spec.rpartition("=") if "=" in spec else ("", "", spec)
            idxs = resolve_tracks(trs, [m for m in members.split("+") if m])
            groups.append((name or trs[idxs[0]]["name"], idxs))
            continue
        i = resolve_tracks(trs, [spec])[0]
        if is_audio_drum_folder(trs, trs[i]):
            drum_folders.append(i)
            groups.append((trs[i]["name"], [i]))
        else:
            sel.append(i)

    audio = []
    group_tracks = [trs[i] for _, idxs in groups for i in idxs if i not in drum_folders]
    for t in build_gp.expand_selection(trs, sel) + group_tracks:
        its = t["items"]
        if not any(i.get("src_type") == "MIDI" and not i["mute"] for i in its) and any(i.get("file") for i in its):
            audio.append(t["index"])
    if audio:
        print("transcribing audio tracks:", audio, flush=True)
        transcribe.run(a.project, cache, audio)
    for i in drum_folders:
        drums_audio.run(a.project, cache, i)

    bpm = a.tempo or P.info["tempo"]
    chord_specs = []
    for spec in a.chords or []:
        name, _, members = spec.rpartition("=")
        chord_specs.append((name or members, resolve_tracks(trs, [m for m in members.split("+") if m])))
    chord_tracks, labels = [], None
    if chord_specs or a.clean_bass:
        exported = [t["index"] for t in build_gp.expand_selection(trs, sel)] + [i for _, ix in groups for i in ix]
        bass = [i for i in exported if re.search(r"bass|basse", trs[i]["name"], re.I)]
        chord_idxs = [i for _, ix in chord_specs for i in ix]
        harm = resolve_tracks(trs, [m for m in a.harmony.split("+") if m]) if a.harmony else chord_idxs
        if harm:
            print("detecting chords from", [trs[i]["name"] for i in harm], "+ bass", [trs[i]["name"] for i in bass], flush=True)
            labels, _ = harmony.detect(a.project, harm, bass, bpm, chord_idxs)
            prog = []
            for k in range(0, len(labels), 4):
                bar = " ".join(dict.fromkeys(labels[k:k + 4]))
                prog.append(f"{k // 4 + 1}:{bar}")
            print("chords per bar:", " | ".join(prog))
        for name, ix in chord_specs:
            ons = harmony.strums(a.project, ix, bpm, build_gp.SLOTS_PER_QN)
            chord_tracks.append((name, harmony.chord_events(labels, build_gp.SLOTS_PER_QN, ons)))
    gp7 = [o for o in outs if o.lower().endswith(".gp")]
    tmp = {o: os.path.splitext(o)[0] + ".tmp.gp5" for o in gp7}
    build_gp.run(a.project, cache, [tmp.get(o, o) for o in outs], sel, drum_map=a.drum_map, tempo=a.tempo,
                 sections=sections, groups=groups, chord_tracks=chord_tracks, chord_labels=labels,
                 clean_bass=a.clean_bass)
    try:
        for o in gp7:
            to_gp7(tmp[o], o)
    finally:
        for t in tmp.values():
            if os.path.exists(t):
                os.remove(t)


def to_gp7(src, dst):
    """GP5 -> Guitar Pro 7/8 .gp through alphaTab (Node.js, gp_export/gp7)."""
    import shutil, subprocess
    here = os.path.join(os.path.dirname(os.path.abspath(__file__)), "gp7")
    node = shutil.which("node")
    if not node:
        sys.exit("writing .gp needs Node.js (https://nodejs.org); or write a .gp5")
    if not os.path.isdir(os.path.join(here, "node_modules", "@coderline", "alphatab")):
        subprocess.run([shutil.which("npm") or "npm", "ci", "--no-audit", "--no-fund"], cwd=here, check=True)
    subprocess.run([node, os.path.join(here, "gp5togp.mjs"), os.path.abspath(src), os.path.abspath(dst)],
                   cwd=here, check=True)
    import gpif
    sc = gpif.Score(dst)  # re-read to make sure the file is well-formed
    print(f"written {dst} (Guitar Pro 7/8): {len(sc.root.find('Tracks').findall('Track'))} tracks")


if __name__ == "__main__":
    main()
