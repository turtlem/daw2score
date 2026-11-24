"""DAW-independent project model: a REAPER .rpp, a DAWproject file (Bitwig, Studio One, Cubase 14+;
see dawproject.py), or a folder of stems + MIDI files from any DAW.

    p = project.load(path)
    p.tracks  -> [{index, name, depth, is_folder, items, fx, drums}]   (folder tracks first, then children)
    p.info    -> {tempo, ts_num, ts_den, tempo_points, markers}         (same shape as rpp.project_info)
    p.name    -> project name (file or folder name)
    p.dir     -> folder holding the project (default place for gp_export_cache)

Items: {position, length, soffs, playrate, loop, mute, src_type ("MIDI" or "WAVE"), file (absolute)}
and, for MIDI, REAPER-style "E" events + ppq, so build_gp.midi_notes reads both sources.

Stems folder layout (export from your DAW, every file starting at the song start / 0 s):

    Song/
      Bass.wav
      Guitar front.wav
      drums/            <- a sub-folder is a folder track (e.g. drum mics -> drums_audio.py)
        Kick.wav
        Snare top.wav
      song.mid          <- optional: each MIDI track becomes a track; gives tempo, time signatures, markers

Audio: wav, flac, aif/aiff, ogg, mp3. Track names are the file names without extension.
"""
import functools, os

import rpp

AUDIO_EXT = (".wav", ".flac", ".aif", ".aiff", ".ogg", ".mp3")
MIDI_EXT = (".mid", ".midi")
PPQ = 960


class Project:
    def __init__(self, path, name, tracks, info):
        self.path, self.name, self.tracks, self.info = path, name, tracks, info
        self.dir = path if os.path.isdir(path) else os.path.dirname(path)


@functools.lru_cache(maxsize=4)
def _load(path, mtime):
    if os.path.isdir(path):
        return _load_stems(path)
    if path.lower().endswith(".dawproject"):
        import dawproject
        return dawproject.load(path)
    return _load_rpp(path)


def load(path):
    path = os.path.abspath(path)
    if not os.path.exists(path):
        raise FileNotFoundError(path)
    return _load(path, os.path.getmtime(path))


# ---------------------------------------------------------------- REAPER
def _load_rpp(path):
    proj = rpp.parse(path)
    pdir = os.path.dirname(path)
    trs = rpp.tracks(proj)
    for t in trs:
        its = rpp.items(t["node"])
        for i in its:
            if i.get("file") and not os.path.isabs(i["file"]):
                i["file"] = os.path.join(pdir, i["file"])
        t["items"] = its
        fx = t["node"].find("FXCHAIN")
        t["fx"] = " ".join(" ".join(c.args) for c in fx[0].children) if fx else ""
        t["drums"] = None
    return Project(path, os.path.splitext(os.path.basename(path))[0], trs, rpp.project_info(proj))


# ---------------------------------------------------------------- stems + MIDI folder
def _audio_item(f):
    import soundfile as sf
    try:
        length = sf.info(f).duration
    except RuntimeError as e:
        raise SystemExit(f"cannot read {f}: {e}")
    return {"position": 0.0, "length": length, "soffs": 0.0, "playrate": 1.0, "loop": False,
            "mute": False, "src_type": "WAVE", "file": f}


def midi_item(notes, bpm, drums=False, mute=False):
    """[(start_s, end_s, pitch, velocity 1-127)] -> a MIDI item with REAPER-style "E" events (quarter
    notes at a constant tempo, which is all build_gp supports), starting at 0 s."""
    evs = []
    for start, end, p, v in notes:
        evs.append((round(start * bpm / 60.0 * PPQ), 0x90, p, max(1, min(127, int(v)))))
        evs.append((round(end * bpm / 60.0 * PPQ), 0x80, p, 0))
    evs.sort(key=lambda e: (e[0], e[1] == 0x90))
    events, last = [], 0
    ch = 9 if drums else 0
    for tick, st, p, v in evs:
        events.append(["E", str(tick - last), f"{st | ch:02x}", f"{p:02x}", f"{v:02x}"])
        last = tick
    end = max((n[1] for n in notes), default=0.0)
    return {"position": 0.0, "length": end + 0.01, "soffs": 0.0, "playrate": 1.0, "loop": False,
            "mute": mute, "src_type": "MIDI", "ppq": PPQ, "events": events, "file": None}


def _midi_tracks(f):
    """-> (tracks [(name, item, is_drum)], tempo_bpm, tempo_changes, [(time_s, num, den)], markers)"""
    import mido
    import pretty_midi
    pm = pretty_midi.PrettyMIDI(f)
    times, tempi = pm.get_tempo_changes()
    # MIDI stores microseconds per quarter: round away the conversion noise (134.00005 -> 134)
    bpm = round(float(tempi[0]), 3) if len(tempi) else 120.0
    changes = [(float(t), round(float(b), 3)) for t, b in zip(times, tempi)]
    ts = [(float(x.time), x.numerator, x.denominator) for x in pm.time_signature_changes]
    markers = []
    mf = mido.MidiFile(f)
    for tr in mf.tracks:
        tick = 0
        for msg in tr:
            tick += msg.time
            if msg.type in ("marker", "cue_marker"):
                markers.append((float(pm.tick_to_time(tick)), msg.text))
    base = os.path.splitext(os.path.basename(f))[0]
    out = []
    for k, inst in enumerate(pm.instruments):
        if not inst.notes:
            continue
        item = midi_item([(n.start, n.end, n.pitch, n.velocity) for n in inst.notes], bpm, inst.is_drum)
        name = inst.name.strip() or (f"{base} {k + 1}" if len(pm.instruments) > 1 else base)
        out.append((name, item, inst.is_drum))
    return out, bpm, changes, ts, markers


def _load_stems(path):
    tracks, midi_info = [], None

    def add(name, depth, is_folder, items, drums=None):
        tracks.append({"index": len(tracks), "name": name, "depth": depth, "is_folder": is_folder,
                       "items": items, "fx": "", "drums": drums})

    def walk(d, depth):
        nonlocal midi_info
        entries = sorted(os.listdir(d), key=str.lower)
        for e in entries:
            f = os.path.join(d, e)
            low = e.lower()
            if os.path.isfile(f) and low.endswith(AUDIO_EXT):
                add(os.path.splitext(e)[0], depth, False, [_audio_item(f)])
            elif os.path.isfile(f) and low.endswith(MIDI_EXT):
                trs, bpm, changes, ts, markers = _midi_tracks(f)
                if midi_info is None:
                    midi_info = (bpm, changes, ts, markers, e)
                for name, item, is_drum in trs:
                    add(name, depth, False, [item], drums=is_drum)
        for e in entries:
            f = os.path.join(d, e)
            if os.path.isdir(f) and not e.startswith((".", "gp_export_cache")):
                add(e, depth, True, [])
                walk(f, depth + 1)

    walk(path, 0)
    if not tracks:
        raise SystemExit(f"no audio ({', '.join(AUDIO_EXT)}) or MIDI files in {path}")
    info = {"tempo": 120.0, "ts_num": 4, "ts_den": 4, "tempo_points": [], "markers": [], "tempo_source": None}
    if midi_info:
        bpm, changes, ts, markers, fname = midi_info
        info.update(tempo=bpm, markers=markers, tempo_source=fname)
        if ts:
            info["ts_num"], info["ts_den"] = ts[0][1], ts[0][2]
        pts = {t: [f"{t}", f"{bpm}", "0", "0"] for t, _ in changes if t > 1e-6}
        for t, b in changes:
            if t > 1e-6:
                pts[t][1] = f"{b}"
        for t, num, den in ts:
            pts.setdefault(t, [f"{t}", f"{bpm}", "0", "0"])[3] = str((den << 16) | num)
        info["tempo_points"] = [pts[t] for t in sorted(pts)]
    return Project(path, os.path.basename(os.path.normpath(path)), tracks, info)
