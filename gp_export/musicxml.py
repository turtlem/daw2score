"""Write the score built by build_gp (a PyGuitarPro Song) as MusicXML 4.0, for Finale, MuseScore,
Dorico, Sibelius, or any notation program.

    musicxml.write(song, "out.musicxml", kinds, bpm)    # .musicxml / .xml = plain XML, .mxl = compressed

kinds: one build_gp kind per track ("bass", "gtr_*", "chords", "keys_rh", "keys_lh", "vocal", "drums",
"drums_audio", ...). Bass and guitars get a standard staff (written an octave up, as usual) plus a
TAB staff carrying string/fret; keys and vocals a standard staff (the pseudo-tunings build_gp uses
for GP5 are turned back into pitches); drums a percussion staff with the usual drum-kit positions.
Chord names become <harmony> with a fret diagram, section markers <rehearsal> marks.
"""
import zipfile

from lxml import etree

DIV = 4  # divisions per quarter note = build_gp's 16th grid
TYPE = {1: "whole", 2: "half", 4: "quarter", 8: "eighth", 16: "16th", 32: "32nd"}
SHARP = ["C", "C#", "D", "D#", "E", "F", "F#", "G", "G#", "A", "A#", "B"]
FLAT = ["C", "Db", "D", "Eb", "E", "F", "Gb", "G", "Ab", "A", "Bb", "B"]
# GM drum note -> (display step, octave, notehead or None, name)
DRUMS = {
    35: ("E", 4, None, "Acoustic Bass Drum"), 36: ("F", 4, None, "Bass Drum"),
    37: ("C", 5, "x", "Side Stick"), 38: ("C", 5, None, "Snare"), 39: ("C", 5, "x", "Hand Clap"),
    40: ("C", 5, None, "Electric Snare"), 41: ("G", 4, None, "Low Floor Tom"),
    42: ("G", 5, "x", "Closed Hi-Hat"), 43: ("A", 4, None, "High Floor Tom"),
    44: ("D", 4, "x", "Pedal Hi-Hat"), 45: ("B", 4, None, "Low Tom"),
    46: ("G", 5, "circle-x", "Open Hi-Hat"), 47: ("D", 5, None, "Low-Mid Tom"),
    48: ("E", 5, None, "Hi-Mid Tom"), 49: ("A", 5, "x", "Crash Cymbal 1"),
    50: ("E", 5, None, "High Tom"), 51: ("F", 5, "x", "Ride Cymbal 1"),
    52: ("B", 5, "x", "Chinese Cymbal"), 53: ("F", 5, "diamond", "Ride Bell"),
    54: ("D", 5, "x", "Tambourine"), 55: ("B", 5, "x", "Splash Cymbal"),
    56: ("E", 5, "triangle", "Cowbell"), 57: ("A", 5, "x", "Crash Cymbal 2"),
    59: ("F", 5, "x", "Ride Cymbal 2"),
}
CHORD_KIND = {"": "major", "m": "minor", "5": "power", "sus2": "suspended-second",
              "sus4": "suspended-fourth", "7": "dominant", "m7": "minor-seventh",
              "maj7": "major-seventh", "dim": "diminished", "aug": "augmented"}
# Krumhansl-Kessler key profiles, used only to choose sharps or flats
MAJ = [6.35, 2.23, 3.48, 2.33, 4.38, 4.09, 2.52, 5.19, 2.39, 3.66, 2.29, 2.88]
MIN = [6.33, 2.68, 3.52, 5.38, 2.60, 3.53, 2.54, 4.75, 3.98, 2.69, 3.34, 3.17]
FIFTHS_MAJ = [0, -5, 2, -3, 4, -1, 6, 1, -4, 3, -2, 5]  # tonic pitch class -> key signature


def sub(parent, tag, _text=None, **attrs):
    e = etree.SubElement(parent, tag, {k.replace("_", "-"): str(v) for k, v in attrs.items()})
    if _text is not None:
        e.text = str(_text)
    return e


def is_drum(kind):
    return kind in ("drums", "drums_audio")


def staff_layout(kind, pitches):
    """-> (clefs [(sign, line, octave_change)], written-pitch shift in semitones, tab staff?)"""
    if is_drum(kind):
        return [("percussion", None, 0)], 0, False
    if kind == "bass":
        return [("F", 4, 0)], 12, True
    if kind.startswith("gtr") or kind == "chords":
        return [("G", 2, 0)], 12, True
    if kind == "keys_lh":
        return [("F", 4, 0)], 0, False
    if kind == "vocal":
        mid = sorted(pitches)[len(pitches) // 2] if pitches else 67
        return [("G", 2, -1 if mid < 60 else 0)], 0, False  # tenor clef (G8vb) for a low voice
    return [("G", 2, 0)], 0, False


def note_pitch(track, note):
    return track.strings[note.string - 1].value + note.value


def key_sharps(song, kinds):
    """+1 to spell with sharps, -1 with flats, from the pitch-class histogram (best major/minor key)."""
    hist = [0.0] * 12
    for tr, kind in zip(song.tracks, kinds):
        if is_drum(kind):
            continue
        for m in tr.measures:
            for b in m.voices[0].beats:
                for n in b.notes:
                    hist[note_pitch(tr, n) % 12] += 16 / b.duration.value
    if not any(hist):
        return 1

    def corr(prof, t):
        p = [prof[(i - t) % 12] for i in range(12)]
        mh, mp = sum(hist) / 12, sum(p) / 12
        return sum((h - mh) * (q - mp) for h, q in zip(hist, p))
    best = max(((corr(MAJ, t), FIFTHS_MAJ[t]) for t in range(12)),
               key=lambda x: x[0])
    best_min = max(((corr(MIN, t), FIFTHS_MAJ[(t + 3) % 12]) for t in range(12)), key=lambda x: x[0])
    fifths = max(best, best_min)[1]
    return 1 if fifths >= 0 else -1


def spell(midi, sharps):
    name = (SHARP if sharps > 0 else FLAT)[midi % 12]
    alter = {"#": 1, "b": -1}.get(name[1:], 0)
    return name[0], alter, midi // 12 - 1


def harmony(parent, chord):
    name = chord.name or ""
    h = sub(parent, "harmony", print_frame="yes" if chord.strings else "no")
    if not name or name[0] not in "ABCDEFG":
        sub(sub(h, "root"), "root-step", "C")
        sub(h, "kind", "none", text=name)
    else:
        acc = name[1:2] if name[1:2] in ("#", "b") else ""
        rest = name[1 + len(acc):]
        root = sub(h, "root")
        sub(root, "root-step", name[0])
        if acc:
            sub(root, "root-alter", 1 if acc == "#" else -1)
        kind = CHORD_KIND.get(rest)
        sub(h, "kind", kind or "other", text=rest if kind is None or kind == "power" else "")
    frets = [(i + 1, f) for i, f in enumerate(chord.strings[:6]) if f is not None and f >= 0]
    if frets:
        played = [f for _, f in frets if f > 0]
        first = chord.firstFret or 1
        fr = sub(h, "frame")
        sub(fr, "frame-strings", 6)
        sub(fr, "frame-frets", max(4, (max(played) - first + 1) if played else 4))
        if first > 1:
            sub(fr, "first-fret", first)
        for s, f in sorted(frets, reverse=True):  # low string first
            fn = sub(fr, "frame-note")
            sub(fn, "string", s)
            sub(fn, "fret", f)


def write(song, path, kinds, bpm):
    sharps = key_sharps(song, kinds)
    root = etree.Element("score-partwise", version="4.0")
    sub(sub(root, "work"), "work-title", song.title)
    ident = sub(root, "identification")
    enc = sub(ident, "encoding")
    sub(enc, "software", "reaper_to_gp")
    plist = sub(root, "part-list")

    parts = []
    for k, (tr, kind) in enumerate(zip(song.tracks, kinds)):
        pid = f"P{k + 1}"
        sp = sub(plist, "score-part", id=pid)
        sub(sp, "part-name", tr.name)
        drum_notes = sorted({n.value for m in tr.measures for b in m.voices[0].beats for n in b.notes}) \
            if is_drum(kind) else []
        if is_drum(kind):
            for gm in drum_notes:
                si = sub(sp, "score-instrument", id=f"{pid}-I{gm}")
                sub(si, "instrument-name", DRUMS.get(gm, (0, 0, 0, f"Drum {gm}"))[3])
            for gm in drum_notes:
                mi = sub(sp, "midi-instrument", id=f"{pid}-I{gm}")
                sub(mi, "midi-channel", 10)
                sub(mi, "midi-unpitched", gm + 1)
        else:
            si = sub(sp, "score-instrument", id=f"{pid}-I1")
            sub(si, "instrument-name", tr.name)
            mi = sub(sp, "midi-instrument", id=f"{pid}-I1")
            sub(mi, "midi-channel", [c for c in range(1, 17) if c != 10][k % 15])
            sub(mi, "midi-program", tr.channel.instrument + 1)
        parts.append((sub(root, "part", id=pid), tr, kind))

    for pi, (part, tr, kind) in enumerate(parts):
        tuning = [s.value for s in tr.strings]  # string 1 (highest) first
        pitches = [] if is_drum(kind) else [note_pitch(tr, n) for m in tr.measures
                                            for b in m.voices[0].beats for n in b.notes]
        clefs, shift, tab = staff_layout(kind, pitches)
        flat = [(mi, b) for mi, m in enumerate(tr.measures) for b in m.voices[0].beats]
        next_beat = {id(b): flat[j + 1][1] for j, (_, b) in enumerate(flat[:-1])}
        prev_ts = None
        for mi, meas in enumerate(tr.measures):
            hd = meas.header
            m = sub(part, "measure", number=mi + 1)
            ts = (hd.timeSignature.numerator, hd.timeSignature.denominator.value)
            mlen = ts[0] * 4 * DIV // ts[1]
            if mi == 0 or ts != prev_ts:
                at = sub(m, "attributes")
                if mi == 0:
                    sub(at, "divisions", DIV)
                    sub(sub(at, "key"), "fifths", 0)
                t = sub(at, "time")
                sub(t, "beats", ts[0])
                sub(t, "beat-type", ts[1])
                if mi == 0:
                    if tab:
                        sub(at, "staves", 2)
                    for si, (sign, line, octch) in enumerate(clefs):
                        c = sub(at, "clef", number=si + 1)
                        sub(c, "sign", sign)
                        if line:
                            sub(c, "line", line)
                        if octch:
                            sub(c, "clef-octave-change", octch)
                    if tab:
                        c = sub(at, "clef", number=2)
                        sub(c, "sign", "TAB")
                        sub(c, "line", 5)
                        sd = sub(at, "staff-details", number=2)
                        sub(sd, "staff-lines", len(tuning))
                        for line_no, p in enumerate(reversed(tuning), 1):
                            st = sub(sd, "staff-tuning", line=line_no)
                            step, alter, octave = spell(p, sharps)
                            sub(st, "tuning-step", step)
                            if alter:
                                sub(st, "tuning-alter", alter)
                            sub(st, "tuning-octave", octave)
                    if shift:
                        tp = sub(at, "transpose")
                        sub(tp, "diatonic", 0)
                        sub(tp, "chromatic", 0)
                        sub(tp, "octave-change", -shift // 12)
            prev_ts = ts
            if pi == 0:
                if mi == 0:
                    d = sub(m, "direction", placement="above")
                    mt = sub(sub(d, "direction-type"), "metronome")
                    sub(mt, "beat-unit", "quarter")
                    sub(mt, "per-minute", f"{bpm:g}")
                    sub(d, "sound", tempo=f"{bpm:g}")
                if hd.marker:
                    d = sub(m, "direction", placement="above")
                    sub(sub(d, "direction-type"), "rehearsal", hd.marker.title)
            staves = [1, 2] if tab else [1]
            for staff in staves:
                if staff == 2:
                    sub(sub(m, "backup"), "duration", mlen)
                for b in meas.voices[0].beats:
                    dur = int(4 * DIV / b.duration.value * (1.5 if b.duration.isDotted else 1))
                    if staff == 1 and b.effect.chord is not None:
                        harmony(m, b.effect.chord)
                    notes = list(b.notes) if b.status.name != "rest" else []
                    nxt = next_beat.get(id(b))
                    nxt_tied = {n.string for n in nxt.notes if n.type.name == "tie"} if nxt is not None else set()
                    if not notes:
                        n = sub(m, "note")
                        sub(n, "rest")
                        sub(n, "duration", dur)
                        sub(n, "voice", 1 if staff == 1 else 5)
                        sub(n, "type", TYPE[b.duration.value])
                        if b.duration.isDotted:
                            sub(n, "dot")
                        if tab:
                            sub(n, "staff", staff)
                        continue
                    for j, gn in enumerate(sorted(notes, key=lambda x: -x.string)):  # low to high
                        n = sub(m, "note")
                        if j:
                            sub(n, "chord")
                        if is_drum(kind):
                            step, octave, head, _ = DRUMS.get(gn.value, ("C", 5, "x", ""))
                            up = sub(n, "unpitched")
                            sub(up, "display-step", step)
                            sub(up, "display-octave", octave)
                        else:
                            step, alter, octave = spell(note_pitch(tr, gn) + shift, sharps)
                            p = sub(n, "pitch")
                            sub(p, "step", step)
                            if alter:
                                sub(p, "alter", alter)
                            sub(p, "octave", octave)
                            head = None
                        sub(n, "duration", dur)
                        tie_stop = gn.type.name == "tie"
                        tie_start = gn.string in nxt_tied
                        if tie_stop:
                            sub(n, "tie", type="stop")
                        if tie_start:
                            sub(n, "tie", type="start")
                        if is_drum(kind):
                            sub(n, "instrument", id=f"P{pi + 1}-I{gn.value}")
                        sub(n, "voice", 1 if staff == 1 else 5)
                        sub(n, "type", TYPE[b.duration.value])
                        if b.duration.isDotted:
                            sub(n, "dot")
                        if is_drum(kind):
                            sub(n, "stem", "up")
                        elif staff == 2:
                            sub(n, "stem", "none")
                        if head:
                            sub(n, "notehead", head)
                        if tab:
                            sub(n, "staff", staff)
                        if tie_stop or tie_start or tab:
                            nt = sub(n, "notations")
                            if tie_stop:
                                sub(nt, "tied", type="stop")
                            if tie_start:
                                sub(nt, "tied", type="start")
                            if tab:
                                tech = sub(nt, "technical")
                                sub(tech, "string", gn.string)
                                sub(tech, "fret", gn.value)

    xml = etree.tostring(root, xml_declaration=True, encoding="UTF-8", pretty_print=True,
                         doctype='<!DOCTYPE score-partwise PUBLIC "-//Recordare//DTD MusicXML 4.0 Partwise//EN" '
                                 '"http://www.musicxml.org/dtds/partwise.dtd">')
    if path.lower().endswith(".mxl"):
        with zipfile.ZipFile(path, "w") as z:
            z.writestr(zipfile.ZipInfo("mimetype"), "application/vnd.recordare.musicxml")
            z.writestr("META-INF/container.xml",
                       '<?xml version="1.0" encoding="UTF-8"?>\n<container><rootfiles>'
                       '<rootfile full-path="score.musicxml" media-type="application/vnd.recordare.musicxml+xml"/>'
                       '</rootfiles></container>\n')
            z.writestr("score.musicxml", xml, compress_type=zipfile.ZIP_DEFLATED)
    else:
        with open(path, "wb") as f:
            f.write(xml)
    check(xml, path)


def check(xml, path):
    """Re-parse and check that every staff of every measure adds up to its time signature."""
    root = etree.fromstring(xml)
    bad, n_notes = 0, 0
    for part in root.findall("part"):
        ts = None
        for m in part.findall("measure"):
            t = m.find("attributes/time")
            if t is not None:
                ts = (int(t.findtext("beats")), int(t.findtext("beat-type")))
            want = ts[0] * 4 * DIV // ts[1]
            per_staff = {}
            for n in m.findall("note"):
                if n.find("chord") is not None:
                    continue
                st = n.findtext("staff") or "1"
                per_staff[st] = per_staff.get(st, 0) + int(n.findtext("duration"))
                n_notes += n.find("rest") is None
            for st, got in per_staff.items():
                if got != want:
                    bad += 1
                    if bad <= 5:
                        print(f"  BAD measure {m.get('number')} part {part.get('id')} staff {st}: {got} vs {want}")
    print(f"written {path} (MusicXML 4.0): {len(root.findall('part'))} parts, "
          f"{len(root.find('part').findall('measure'))} measures; measure length check:",
          "OK" if bad == 0 else f"{bad} bad measures")
