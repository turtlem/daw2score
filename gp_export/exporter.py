"""The whole export as one function, shared by export_gp.py (command line) and gui.py (window).

    exporter.export(project_path, ["Song.gp", "Song.musicxml"], sel=[3, 7], groups=[("Chant", [12, 13])],
                    roles={7: "bass"}, tempo="auto", sections={3: "Intro"}, backing=[20, 21])

Tracks are 0-based indices of project.load(project_path).tracks. Errors raise SystemExit with a
message (as the command line always did).
"""
import os, re, shutil, subprocess, sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import project, transcribe, build_gp, drums_audio, harmony

OUT_EXT = (".gp", ".gp5") + build_gp.XML_EXT
ROLES = ("drums", "bass", "gtr_heavy", "gtr_clean", "gtr_solo", "chords", "vocal", "keys")


def is_audio_drum_folder(trs, t, roles=None):
    """A folder track of drum mics (audio only), named drum/batterie or given the drums role."""
    if not t["is_folder"]:
        return False
    if (roles or {}).get(t["index"]) != "drums" and not re.search(r"drum|batterie", t["name"], re.I):
        return False
    kids = build_gp.expand_selection(trs, [t["index"]])
    return not any(i.get("src_type") == "MIDI" for k in kids for i in k["items"])


def detect_tempo(proj_path):
    import tempo
    d = tempo.detect(proj_path)
    tempo.report(d)
    b = d["bpm"]
    return float(round(b)) if abs(b - round(b)) < 0.15 else round(b, 1)


def export(proj_path, outs, sel=(), groups=(), chord_specs=(), harmony_idxs=None, tempo=None,
           sections=None, clean_bass=False, drum_map=None, cache=None, roles=None, backing=None,
           backing_name=None, force=False):
    """outs: output paths (.gp, .gp5, .musicxml, .mxl). sel: track indices (folders expanded; an
    audio drum folder goes to drums_audio). groups: [(name, [indices])] written as one track.
    chord_specs: [(name, [indices])] written as strummed chords; the chords are detected from
    harmony_idxs (default: the chord tracks) + the bass tracks. tempo: None (project), BPM or "auto".
    sections: {bar: name} replacing the project markers. roles: {index: kind} (see ROLES).
    backing: track indices mixed into the Guitar Pro 8 audio track of each .gp output."""
    outs = list(outs)
    roles = dict(roles or {})
    if not outs:
        sys.exit("no output file")
    for o in outs:
        if not o.lower().endswith(OUT_EXT):
            sys.exit(f"unknown output format {o!r}: use .gp, .gp5, .musicxml or .mxl")
        if os.path.exists(o) and not force:
            sys.exit(f"{o} already exists (use --force to overwrite)")
    P = project.load(proj_path)
    trs = P.tracks
    cache = cache or os.path.join(P.dir, "gp_export_cache")
    if tempo == "auto":
        tempo = detect_tempo(proj_path)
        print(f"using --tempo {tempo:g}")
    elif tempo is not None:
        tempo = float(tempo)
    elif os.path.isdir(proj_path) and not P.info.get("tempo_source"):
        print("WARNING: stems folder without a MIDI file: tempo 120 assumed (use --tempo BPM or --tempo auto)")

    for i, k in roles.items():
        if k == "drums" and not trs[i]["is_folder"] and not any(it.get("src_type") == "MIDI" for it in trs[i]["items"]):
            print(f"WARNING: role drums ignored for the audio track {trs[i]['name']!r}: only MIDI tracks and "
                  "folders of drum mics can be written as drums")
    sel_tracks, drum_groups, drum_folders = [], [], []
    for i in sel:
        if is_audio_drum_folder(trs, trs[i], roles):
            drum_groups.append((trs[i]["name"], [i]))
        else:
            sel_tracks.append(i)
    groups = drum_groups + list(groups)  # drums first, as in the command-line order
    for _, idxs in groups:
        drum_folders += [i for i in idxs if is_audio_drum_folder(trs, trs[i], roles)]

    audio = []
    group_tracks = [trs[i] for _, idxs in groups for i in idxs if i not in drum_folders]
    for t in build_gp.expand_selection(trs, sel_tracks) + group_tracks:
        its = t["items"]
        if not any(i.get("src_type") == "MIDI" and not i["mute"] for i in its) and any(i.get("file") for i in its):
            audio.append(t["index"])
    if audio:
        print("transcribing audio tracks:", audio, flush=True)
        transcribe.run(proj_path, cache, audio, roles={i: k for i, k in roles.items() if k != "drums"})
    for i in drum_folders:
        drums_audio.run(proj_path, cache, i)

    bpm = tempo or P.info["tempo"]
    chord_tracks, labels = [], None
    if chord_specs or clean_bass:
        exported = [t["index"] for t in build_gp.expand_selection(trs, sel_tracks)] + [i for _, ix in groups for i in ix]
        bass = [i for i in exported if roles.get(i) == "bass"
                or (i not in roles and re.search(r"bass|basse", trs[i]["name"], re.I))]
        chord_idxs = [i for _, ix in chord_specs for i in ix]
        harm = list(harmony_idxs) if harmony_idxs else chord_idxs
        if harm:
            print("detecting chords from", [trs[i]["name"] for i in harm], "+ bass", [trs[i]["name"] for i in bass], flush=True)
            labels, _ = harmony.detect(proj_path, harm, bass, bpm, chord_idxs)
            prog = []
            for k in range(0, len(labels), 4):
                bar = " ".join(dict.fromkeys(labels[k:k + 4]))
                prog.append(f"{k // 4 + 1}:{bar}")
            print("chords per bar:", " | ".join(prog))
        for name, ix in chord_specs:
            ons = harmony.strums(proj_path, ix, bpm, build_gp.SLOTS_PER_QN)
            chord_tracks.append((name, harmony.chord_events(labels, build_gp.SLOTS_PER_QN, ons)))

    gp7 = [o for o in outs if o.lower().endswith(".gp")]
    tmp = {o: os.path.splitext(o)[0] + ".tmp.gp5" for o in gp7}
    build_gp.run(proj_path, cache, [tmp.get(o, o) for o in outs], sel_tracks, drum_map=drum_map, tempo=tempo,
                 sections=sections, groups=groups, chord_tracks=chord_tracks, chord_labels=labels,
                 clean_bass=clean_bass, roles={i: k for i, k in roles.items() if k != "chords"})
    try:
        for o in gp7:
            to_gp7(tmp[o], o)
    finally:
        for t in tmp.values():
            if os.path.exists(t):
                os.remove(t)
    if backing and gp7:
        import add_backing
        for o in gp7:
            add_backing.add(o, proj_path, list(backing), name=backing_name, out=o, replace=True)
    return {"outputs": outs, "bpm": bpm}


def to_gp7(src, dst):
    """GP5 -> Guitar Pro 7/8 .gp through alphaTab (Node.js, gp_export/gp7)."""
    here = os.path.join(os.path.dirname(os.path.abspath(__file__)), "gp7")
    bundled = os.path.join(here, "node.exe" if os.name == "nt" else "node")  # shipped by the installer / .app
    node = bundled if os.path.exists(bundled) else shutil.which("node")
    if not node:
        sys.exit("writing .gp needs Node.js (https://nodejs.org); or write a .gp5")

    def run(cmd):
        r = subprocess.run(cmd, cwd=here, capture_output=True, text=True, encoding="utf-8", errors="replace",
                           creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0))
        if r.stdout.strip():
            print(r.stdout.strip())
        if r.returncode:
            sys.exit(f"{os.path.basename(cmd[0])} failed:\n{r.stderr.strip()}")
    if not os.path.isdir(os.path.join(here, "node_modules", "@coderline", "alphatab")):
        print("installing alphaTab (npm ci, first use only)...", flush=True)
        run([shutil.which("npm") or "npm", "ci", "--no-audit", "--no-fund"])
    run([node, os.path.join(here, "gp5togp.mjs"), os.path.abspath(src), os.path.abspath(dst)])
    import gpif
    sc = gpif.Score(dst)  # re-read to make sure the file is well-formed
    print(f"written {dst} (Guitar Pro 7/8): {len(sc.root.find('Tracks').findall('Track'))} tracks")
