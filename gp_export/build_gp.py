"""Build a Guitar Pro 5 file from selected REAPER tracks (MIDI from the .rpp + basic-pitch transcriptions).

usage: build_gp.py <project.rpp> <transcriptions_dir> <out.gp5> <selected_idx> [...]
"""
import collections, json, os, sys
import guitarpro as gp

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import rpp, transcribe

SLOTS_PER_QN = 4  # 16th-note grid
MAX_DRUM_SLOTS = 8

DEFAULT_DRUM_MAP = os.path.join(os.path.dirname(os.path.abspath(__file__)), "drum_maps", "ezdrummer3.json")


def load_drum_map(path=None):
    """Drum-plugin note -> GM note, from a drum_maps/*.json file (see ezdrummer3.json)."""
    with open(path or DEFAULT_DRUM_MAP, encoding="utf-8") as f:
        return {int(k): int(v["gm"]) for k, v in json.load(f)["map"].items()}

TUNINGS = {
    "bass4": [43, 38, 33, 28], "bass5": [43, 38, 33, 28, 23],
    "gtr": [64, 59, 55, 50, 45, 40], "gtr_dropd": [64, 59, 55, 50, 45, 38],
    "gtr7": [64, 59, 55, 50, 45, 40, 35],
    "keys_rh": [80, 75, 70, 65, 60, 55, 50], "keys_lh": [50, 45, 40, 35, 30, 25, 20],
    "voice": [76, 71, 66, 61, 56, 51, 46],
}
GM_PROGRAM = {"bass": 33, "gtr_heavy": 30, "gtr_solo": 29, "gtr_clean": 27, "vocal": 53,
              "keys": 0, "other": 0}

DUR_PIECES = [(16, 1, False), (12, 2, True), (8, 2, False), (6, 4, True),
              (4, 4, False), (3, 8, True), (2, 8, False), (1, 16, False)]


# ---------------------------------------------------------------- timeline
def build_measures(info, end_qn):
    bpm = info["tempo"]
    changes = []  # (qn, num, den)
    for pt in info["tempo_points"]:
        flags = int(pt[3]) if len(pt) > 3 and pt[3].lstrip("-").isdigit() else 0
        if abs(float(pt[1]) - bpm) > 1e-6:
            print("WARNING: tempo changes are not supported, using", bpm)
        if flags:
            changes.append((float(pt[0]) * bpm / 60.0, flags & 0xFFFF, flags >> 16))
    if not changes or changes[0][0] > 1e-6:
        changes.insert(0, (0.0, info["ts_num"], info["ts_den"]))
    measures, qn, ci = [], 0.0, 0
    while qn < end_qn - 1e-6:
        while ci + 1 < len(changes) and changes[ci + 1][0] <= qn + 1e-6:
            ci += 1
        num, den = changes[ci][1], changes[ci][2]
        length = num * 4.0 / den
        measures.append({"qn": qn, "len": length, "num": num, "den": den,
                         "s0": round(qn * SLOTS_PER_QN), "s1": round((qn + length) * SLOTS_PER_QN)})
        qn += length
    return measures


# ---------------------------------------------------------------- note sources
def midi_notes(its, bpm):
    out = []
    q = bpm / 60.0
    for it in its:
        if it["mute"] or it.get("src_type") != "MIDI":
            continue
        base = it["position"] * q - it["soffs"] * q
        lo, hi = it["position"] * q, (it["position"] + it["length"]) * q
        tick, on = 0, {}
        for ev in it["events"]:
            tick += int(ev[1])
            st = int(ev[2], 16)
            kind, ch = st & 0xF0, st & 0x0F
            if kind not in (0x80, 0x90) or len(ev) < 5:
                continue
            pitch, vel = int(ev[3], 16), int(ev[4], 16)
            t = base + tick / it["ppq"]
            if kind == 0x90 and vel > 0:
                on.setdefault((ch, pitch), []).append((t, vel))
            elif on.get((ch, pitch)):
                t0, v = on[(ch, pitch)].pop(0)
                if t0 < hi and t > lo:
                    out.append({"start": max(t0, lo), "end": min(t, hi), "pitch": pitch, "vel": v})
    out.sort(key=lambda n: (n["start"], n["pitch"]))
    return out


def audio_notes(tdir, idx, bpm):
    p = os.path.join(tdir, f"{idx}.json")
    if not os.path.exists(p):
        return None, None
    d = json.load(open(p, encoding="utf-8"))
    q = bpm / 60.0
    notes = [{"start": n["start"] * q, "end": n["end"] * q, "pitch": n["pitch"],
              "vel": max(30, min(127, int(40 + n["amp"] * 120)))} for n in d["notes"]]
    return notes, d["profile"]


# ---------------------------------------------------------------- reduction to chords on the grid
def to_chords(notes, max_poly, drum=False):
    by_slot = collections.defaultdict(list)
    for n in notes:
        s = round(n["start"] * SLOTS_PER_QN)
        e = max(s + 1, round(n["end"] * SLOTS_PER_QN))
        by_slot[s].append({**n, "e": e})
    starts = sorted(by_slot)
    chords = []
    for k, s in enumerate(starts):
        ns = {}
        for n in sorted(by_slot[s], key=lambda n: -n["vel"]):
            ns.setdefault(n["pitch"], n)  # dedupe pitch
        ns = sorted(ns.values(), key=lambda n: -n["vel"])[:max_poly]
        nxt = starts[k + 1] if k + 1 < len(starts) else None
        if drum:
            e = s + MAX_DRUM_SLOTS if nxt is None else min(nxt, s + MAX_DRUM_SLOTS)
        else:
            e = max(n["e"] for n in ns)
            if nxt is not None:
                e = min(e, nxt)
        chords.append({"s": s, "e": e, "notes": ns})
    return chords


# ---------------------------------------------------------------- tunings / fretting
def pick_tuning(kind, pitches):
    if not pitches:
        return {"bass": "bass4", "keys_rh": "keys_rh", "keys_lh": "keys_lh", "vocal": "voice"}.get(kind, "gtr")
    srt = sorted(pitches)
    low = srt[int(len(srt) * 0.03)]
    if kind == "bass":
        return "bass4" if low >= 28 else "bass5"
    if kind.startswith("gtr"):
        return "gtr" if low >= 40 else ("gtr_dropd" if low >= 38 else "gtr7")
    return {"keys_rh": "keys_rh", "keys_lh": "keys_lh", "vocal": "voice"}.get(kind, "gtr")


class Fretter:
    def __init__(self, tuning, frets=24, max_span=5):
        self.t, self.frets, self.pos, self.dropped, self.transposed = tuning, frets, 5.0, 0, 0
        self.max_span = max_span

    def fit(self, p):
        lo, hi = min(self.t), max(self.t) + self.frets
        while p < lo:
            p += 12; self.transposed += 1
        while p > hi:
            p -= 12; self.transposed += 1
        return p

    def assign(self, notes):
        """notes: list of dict(pitch, vel). Returns list of (string_no, fret, vel)."""
        ps = []
        for n in notes:
            p = self.fit(n["pitch"])
            if all(p != q for q, _ in ps):
                ps.append((p, n["vel"]))
        ps.sort(key=lambda x: -x[0])
        while ps:
            best = self._search(ps)
            if best is not None:
                fretted = [f for _, f, _ in best if f > 0]
                if fretted:
                    self.pos = 0.7 * self.pos + 0.3 * (sum(fretted) / len(fretted))
                return best
            ps.remove(min(ps, key=lambda x: x[1]))  # drop quietest
            self.dropped += 1
        return []

    def _search(self, ps):
        best, best_cost = None, None
        n_str = len(self.t)

        def rec(i, used, acc):
            nonlocal best, best_cost
            if i == len(ps):
                fr = [f for _, f, _ in acc if f > 0]
                span = (max(fr) - min(fr)) if fr else 0
                if self.max_span is not None and span > self.max_span and len(acc) > 1:
                    return
                mean = sum(fr) / len(fr) if fr else self.pos
                cost = span * 2 + abs(mean - self.pos) * 0.6 + sum(f for _, f, _ in acc) * 0.05
                if best_cost is None or cost < best_cost:
                    best, best_cost = list(acc), cost
                return
            p, v = ps[i]
            for s in range(n_str):
                if s in used:
                    continue
                f = p - self.t[s]
                if 0 <= f <= self.frets:
                    used.add(s); acc.append((s + 1, f, v))
                    rec(i + 1, used, acc)
                    acc.pop(); used.discard(s)

        rec(0, set(), [])
        return best


# ---------------------------------------------------------------- GP writing
def decompose(n):
    out = []
    while n > 0:
        for size, val, dot in DUR_PIECES:
            if size <= n:
                out.append((size, val, dot)); n -= size; break
    return out


def chord_diagram(name, nts):
    """gp.Chord (name + diagram) from [(string_no, fret, vel)], string 1 = high e."""
    frets = [-1] * 7
    for st, fr, _ in nts:
        frets[st - 1] = fr
    played = [f for f in frets if f > 0]
    first = max(1, min(played)) if played and max(played) > 4 else 1
    return gp.Chord(length=6, name=name, strings=frets, firstFret=first, sharp=False, add=False,
                    show=True, newFormat=True)


def fill_track(track, measures, chords, assign):
    """chords: list of {s,e,notes}; assign(chord)->[(string,fret,vel)]"""
    assigned = [(c["s"], c["e"], assign(c), c.get("label")) for c in chords]
    assigned = [a for a in assigned if a[2]]
    ai = 0
    for m, gm in zip(measures, track.measures):
        voice = gm.voices[0]
        cursor = m["s0"]
        while ai < len(assigned) and assigned[ai][1] <= m["s0"]:
            ai += 1
        k = ai
        pieces = []
        while k < len(assigned) and assigned[k][0] < m["s1"]:
            s, e, nts, label = assigned[k]
            pieces.append((max(s, m["s0"]), min(e, m["s1"]), nts, s < m["s0"], label))
            k += 1
        for s, e, nts, tied, label in pieces:
            if s > cursor:
                for _, val, dot in decompose(s - cursor):
                    voice.beats.append(gp.Beat(voice, duration=gp.Duration(val, dot), status=gp.BeatStatus.rest))
            first = True
            for _, val, dot in decompose(e - s):
                b = gp.Beat(voice, duration=gp.Duration(val, dot), status=gp.BeatStatus.normal)
                is_tie = tied or not first
                for st, fr, vel in nts:
                    b.notes.append(gp.Note(b, value=fr, velocity=vel, string=st,
                                           type=gp.NoteType.tie if is_tie else gp.NoteType.normal))
                if label and first and not tied:
                    b.effect.chord = chord_diagram(label, nts)
                voice.beats.append(b)
                first = False
            cursor = e
        if cursor < m["s1"]:
            for _, val, dot in decompose(m["s1"] - cursor):
                voice.beats.append(gp.Beat(voice, duration=gp.Duration(val, dot), status=gp.BeatStatus.rest))


def expand_selection(trs, sel):
    out = []
    for t in trs:
        if t["index"] in sel:
            out.append(t)
            if t["is_folder"]:
                for c in trs[t["index"] + 1:]:
                    if c["depth"] <= t["depth"]:
                        break
                    out.append(c)
    seen, res = set(), []
    for t in out:
        if t["index"] not in seen and not t["is_folder"]:
            seen.add(t["index"]); res.append(t)
    return res


def main():
    run(sys.argv[1], sys.argv[2], sys.argv[3], [int(a) for a in sys.argv[4:]])


def run(proj_path, tdir, out_path, sel, drum_map=None, tempo=None, sections=None, groups=None,
        chord_tracks=None, chord_labels=None, clean_bass=False):
    """sel: track indices (folders expanded). groups: [(name, [indices])] each written as ONE track from
    the cached transcriptions of its tracks (a drum folder transcribed by drums_audio.py is a group of
    one: its folder index). tempo: BPM overriding the project's (for audio recorded to a click while
    the project kept REAPER's default tempo). sections: {bar number (1-based): name}, replacing the
    project markers. chord_tracks: [(name, events from harmony.chord_events)] written as strummed
    chords with chord names. clean_bass: run bass_fix.fix on bass tracks (chord_labels = per-beat chord
    names from harmony.detect, used to judge passing notes)."""
    drum_to_gm = load_drum_map(drum_map)
    proj = rpp.parse(proj_path)
    info = rpp.project_info(proj)
    if tempo:
        if info["tempo_points"]:
            print("WARNING: --tempo ignores the project's tempo map")
        info["tempo"], info["tempo_points"] = float(tempo), []
    bpm = info["tempo"]
    all_trs = rpp.tracks(proj)
    trs = expand_selection(all_trs, sel)

    specs = []  # (name, kind, notes, is_drum)
    spec_idxs = {}
    for name, idxs in groups or []:
        spec_idxs[name] = idxs
        notes, kind = [], None
        for i in idxs:
            ns, prof = audio_notes(tdir, i, bpm)
            if ns:
                notes += ns
                kind = kind or prof["kind"]
        if not notes:
            print(f"skip group {name!r}: no notes")
            continue
        notes.sort(key=lambda n: (n["start"], n["pitch"]))
        # "drums_audio" = already GM (from drums_audio.py), so no plugin note map
        specs.append((name, "drums_audio" if kind == "drums" else kind, notes, kind == "drums"))
    for t in trs:
        its = rpp.items(t["node"])
        has_midi = any(i.get("src_type") == "MIDI" and not i["mute"] for i in its)
        fx = " ".join(" ".join(c.args) for c in t["node"].find("FXCHAIN")[0].children) if t["node"].find("FXCHAIN") else ""
        if has_midi:
            notes = midi_notes(its, bpm)
            if "drum" in t["name"].lower() or "EZdrummer" in fx:
                specs.append((t["name"], "drums", notes, True))
            else:
                rh = [n for n in notes if n["pitch"] >= 60]
                lh = [n for n in notes if n["pitch"] < 60]
                if rh: specs.append((t["name"] + " (MD)", "keys_rh", rh, False))
                if lh: specs.append((t["name"] + " (MG)", "keys_lh", lh, False))
        else:
            notes, prof = audio_notes(tdir, t["index"], bpm)
            if notes:
                specs.append((t["name"], prof["kind"], notes, False))
            else:
                print(f'skip [{t["index"]}] {t["name"]}: no notes')
            spec_idxs[t["name"]] = [t["index"]]

    if clean_bass:
        import bass_fix
        kicks = {round(n["start"] * SLOTS_PER_QN) for _, _, ns, d in specs if d for n in ns if n["pitch"] in (35, 36)}
        pdir = os.path.dirname(os.path.abspath(proj_path))
        for k, (name, kind, notes, is_drum) in enumerate(specs):
            if kind != "bass":
                continue
            its = [i for ix in spec_idxs.get(name, []) for i in rpp.items(all_trs[ix]["node"])]
            buf, t0 = transcribe.render(pdir, its) if its else (None, 0.0)
            fixed, st = bass_fix.fix(notes, buf, t0, bpm, SLOTS_PER_QN, kicks, chord_labels)
            print(f"bass cleanup {name!r}: {len(notes)} -> {len(fixed)} notes {st}")
            specs[k] = (name, kind, fixed, is_drum)
    for name, events in chord_tracks or []:
        specs.append((name, "chords", events, False))

    end_qn = max((n["end"] if "end" in n else n["e"] / SLOTS_PER_QN) for _, _, ns, _ in specs for n in ns) + 0.01
    measures = build_measures(info, end_qn)

    song = gp.Song(title=os.path.splitext(os.path.basename(proj_path))[0], tempo=int(round(bpm)))
    song.measureHeaders = []
    song.tracks = []
    marker_qn = {round(t * bpm / 60.0 * SLOTS_PER_QN): name for t, name in info["markers"]}
    if sections:
        marker_qn = {measures[b - 1]["s0"]: name for b, name in sections.items() if 0 < b <= len(measures)}
    tick = 960
    for i, m in enumerate(measures):
        h = gp.MeasureHeader(number=i + 1, start=tick,
                             timeSignature=gp.TimeSignature(numerator=m["num"], denominator=gp.Duration(value=m["den"])))
        if m["s0"] in marker_qn:
            h.marker = gp.Marker(title=marker_qn[m["s0"]], color=gp.Color(255, 0, 0))
        song.measureHeaders.append(h)
        tick += int(round(m["len"] * 960))

    names = collections.Counter()
    chan_pool = [(port, c) for port in (1, 2, 3, 4) for c in range(16) if c != 9]
    report = []
    for n_t, (name, kind, notes, is_drum) in enumerate(specs):
        names[name] += 1
        tname = name if names[name] == 1 else f"{name} ({names[name]})"
        if is_drum:
            if kind != "drums_audio":
                for n in notes:
                    n["pitch"] = drum_to_gm.get(n["pitch"], n["pitch"])
            track = gp.Track(song, number=n_t + 1, name=tname, isPercussionTrack=True,
                             strings=[gp.GuitarString(i + 1, 0) for i in range(6)],
                             port=1, channel=gp.MidiChannel(channel=9, effectChannel=9, instrument=0))
            chords = to_chords(notes, 6, drum=True)

            def assign(c):
                return [(i + 1, n["pitch"], n["vel"]) for i, n in enumerate(sorted(c["notes"], key=lambda n: n["pitch"])[:6])]
            tun = "percussion"
            fretter = None
        elif kind == "chords":
            tun = "gtr"
            fretter = None
            port, ch = chan_pool.pop(0)
            track = gp.Track(song, number=n_t + 1, name=tname,
                             strings=[gp.GuitarString(i + 1, v) for i, v in enumerate(TUNINGS["gtr"])],
                             port=port, channel=gp.MidiChannel(channel=ch, effectChannel=ch, instrument=GM_PROGRAM["gtr_clean"]))
            chords = [{"s": ev["s"], "e": ev["e"], "notes": [], "ev": ev,
                       "label": ev["name"] if ev["first"] else None} for ev in notes]

            def assign(c):
                fr = c["ev"]["frets"]  # low E -> high e; GP string 1 = high e
                return [(6 - i, f, c["ev"]["vel"]) for i, f in enumerate(fr) if f >= 0]
        else:
            max_poly = {"bass": 1, "gtr_solo": 1, "vocal": 1, "gtr_heavy": 3, "gtr_clean": 6}.get(kind, 7)
            tun = pick_tuning(kind, [n["pitch"] for n in notes])
            tuning = TUNINGS[tun]
            fretter = Fretter(tuning, max_span=5 if kind in ("bass",) or kind.startswith("gtr") else None)
            port, ch = chan_pool.pop(0)
            prog = GM_PROGRAM.get("keys" if kind.startswith("keys") else kind, 0)
            track = gp.Track(song, number=n_t + 1, name=tname,
                             strings=[gp.GuitarString(i + 1, v) for i, v in enumerate(tuning)],
                             port=port, channel=gp.MidiChannel(channel=ch, effectChannel=ch, instrument=prog))
            chords = to_chords(notes, max_poly)
            assign = lambda c, f=fretter: f.assign(c["notes"])
        track.measures = [gp.Measure(track, h) for h in song.measureHeaders]
        fill_track(track, measures, chords, assign)
        song.tracks.append(track)
        report.append((tname, kind, tun, len(notes), len(chords),
                       fretter.dropped if fretter else 0, fretter.transposed if fretter else 0))

    with open(out_path, "wb") as f:
        gp.write(song, f, version=(5, 1, 0))
    back = gp.parse(out_path)
    print(f"written {out_path}: {len(back.tracks)} tracks, {len(back.measureHeaders)} measures, tempo {back.tempo}")
    # validation: every measure of every track must sum to its time signature length
    bad = 0
    for tr in back.tracks:
        for meas in tr.measures:
            want = meas.header.timeSignature.numerator * 16 // meas.header.timeSignature.denominator.value
            got = sum((16 // b.duration.value) * (1.5 if b.duration.isDotted else 1) for b in meas.voices[0].beats)
            if abs(got - want) > 1e-9:
                bad += 1
                if bad <= 5:
                    print(f"  BAD measure {meas.header.number} in {tr.name}: {got} vs {want} sixteenths")
    print("measure length check:", "OK" if bad == 0 else f"{bad} bad measures")
    print("track | kind | tuning | src notes | beats w/ notes | dropped | octave-shifted")
    for r in report:
        print(" | ".join(str(x) for x in r))
    ts = collections.Counter((m["num"], m["den"]) for m in measures)
    print("time signatures:", dict(ts))
    print("markers:", [(h.number, h.marker.title) for h in back.measureHeaders if h.marker])


if __name__ == "__main__":
    main()
