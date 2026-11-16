"""Read/rewrite a single-voice stringed track inside a Guitar Pro 7/8 .gp file (zip + Content/score.gpif).

GP8 de-duplicates identical Beat/Note elements (one element referenced from many places), so never
edit a Beat/Note in place: rewrite_track creates fresh elements and prunes unreferenced ones.
Slots are 16th notes from the start of the score.
"""
import io, zipfile
from lxml import etree

GPIF = "Content/score.gpif"
VALUE_SLOTS = {"Whole": 16, "Half": 8, "Quarter": 4, "Eighth": 2, "16th": 1}
STEPS = ["C", "C", "D", "D", "E", "F", "F", "G", "G", "A", "A", "B"]
SHARP = [False, True, False, True, False, False, True, False, True, False, True, False]
DUR_PIECES = [(16, "Whole", 0), (12, "Half", 1), (8, "Half", 0), (6, "Quarter", 1),
              (4, "Quarter", 0), (3, "Eighth", 1), (2, "Eighth", 0), (1, "16th", 0)]


class Score:
    def __init__(self, path):
        self.path = path
        with zipfile.ZipFile(path) as z:
            self.entries = [(i, z.read(i.filename)) for i in z.infolist()]
        raw = dict((i.filename, d) for i, d in self.entries)[GPIF]
        parser = etree.XMLParser(strip_cdata=False, remove_blank_text=False, huge_tree=True)
        self.root = etree.fromstring(raw, parser)
        r = self.root
        # findall(tag): the containers also hold XML comments ("order is important here")
        self.masterbars = r.find("MasterBars").findall("MasterBar")
        self.bars = {e.get("id"): e for e in r.find("Bars").findall("Bar")}
        self.voices = {e.get("id"): e for e in r.find("Voices").findall("Voice")}
        self.beats = {e.get("id"): e for e in r.find("Beats").findall("Beat")}
        self.notes = {e.get("id"): e for e in r.find("Notes").findall("Note")}
        self.rhythms = {e.get("id"): e for e in r.find("Rhythms").findall("Rhythm")}
        self.tracks = r.find("Tracks").findall("Track")
        self.bar_slots, s = [], 0
        for mb in self.masterbars:
            num, den = (int(x) for x in mb.findtext("Time").split("/"))
            n = num * 16 // den
            self.bar_slots.append((s, s + n))
            s += n

    # ------------------------------------------------------------------ read
    def track_index(self, name):
        for i, t in enumerate(self.tracks):
            if t.findtext("Name").strip() == name:
                return i
        raise KeyError(f"track {name!r} not found: {[t.findtext('Name') for t in self.tracks]}")

    def tuning(self, ti):
        p = self.tracks[ti].find(".//Property[@name='Tuning']/Pitches")
        return [int(x) for x in p.text.split()]  # index 0 = lowest string (GPIF String number)

    def _rslots(self, rid):
        rh = self.rhythms[rid]
        if rh.find("PrimaryTuplet") is not None:
            raise ValueError("tuplets are not supported")
        n = VALUE_SLOTS[rh.findtext("NoteValue")]
        dot = rh.find("AugmentationDot")
        c = int(dot.get("count")) if dot is not None else 0
        return n + (n // 2 if c >= 1 else 0) + (n // 4 if c >= 2 else 0)

    def read_track(self, ti):
        """Returns (notes, warnings). notes: dict(s, e, pitch, dynamic). Ties are merged; voice 1 only."""
        out, warn = [], []
        for mi, mb in enumerate(self.masterbars):
            bar = self.bars[mb.findtext("Bars").split()[ti]]
            vids = [v for v in bar.findtext("Voices").split() if v != "-1"]
            if len(vids) > 1:
                warn.append(f"bar {mi + 1}: extra voices ignored")
            if not vids:
                continue
            cur = self.bar_slots[mi][0]
            for bid in (self.voices[vids[0]].findtext("Beats") or "").split():
                beat = self.beats[bid]
                d = self._rslots(beat.find("Rhythm").get("ref"))
                nids = (beat.findtext("Notes") or "").split()
                if nids:
                    ns = [self.notes[n] for n in nids]
                    if len(ns) > 1:
                        warn.append(f"bar {mi + 1}: chord reduced to lowest note")
                    n = min(ns, key=lambda x: int(x.findtext(".//Property[@name='Midi']/Number")))
                    pitch = int(n.findtext(".//Property[@name='Midi']/Number"))
                    tie = n.find("Tie")
                    if tie is not None and tie.get("destination") == "true" and out and out[-1]["e"] == cur and out[-1]["pitch"] == pitch:
                        out[-1]["e"] = cur + d
                    else:
                        out.append({"s": cur, "e": cur + d, "pitch": pitch,
                                    "dynamic": beat.findtext("Dynamic") or "MF"})
                cur += d
            if cur != self.bar_slots[mi][1]:
                warn.append(f"bar {mi + 1}: voice length {cur - self.bar_slots[mi][0]} != {self.bar_slots[mi][1] - self.bar_slots[mi][0]}")
        return out, warn

    # ------------------------------------------------------------------ write
    def _new_id(self, table):
        self._ids[table] += 1
        return str(self._ids[table])

    def _rhythm_id(self, value, dots):
        for rid, rh in self.rhythms.items():
            dot = rh.find("AugmentationDot")
            c = int(dot.get("count")) if dot is not None else 0
            if rh.findtext("NoteValue") == value and c == dots and rh.find("PrimaryTuplet") is None and len(rh) == (2 if c else 1):
                return rid
        rid = self._new_id("Rhythms")
        rh = etree.SubElement(self.root.find("Rhythms"), "Rhythm", id=rid)
        etree.SubElement(rh, "NoteValue").text = value
        if dots:
            etree.SubElement(rh, "AugmentationDot", count=str(dots))
        self.rhythms[rid] = rh
        return rid

    @staticmethod
    def _pitch_el(parent, name, midi):
        prop = etree.SubElement(parent, "Property", name=name)
        p = etree.SubElement(prop, "Pitch")
        etree.SubElement(p, "Step").text = STEPS[midi % 12]
        acc = etree.SubElement(p, "Accidental")
        if SHARP[midi % 12]:
            acc.text = "#"
        etree.SubElement(p, "Octave").text = str(midi // 12)

    def _make_beat(self, template, value, dots, dynamic, note=None):
        """note: (string, fret, midi, tie_origin, tie_dest, transpose_octaves) or None for a rest."""
        bid = self._new_id("Beats")
        b = etree.SubElement(self.root.find("Beats"), "Beat", id=bid)
        etree.SubElement(b, "Dynamic").text = dynamic
        etree.SubElement(b, "Rhythm", ref=self._rhythm_id(value, dots))
        for tag in ("TransposedPitchStemOrientation", "ConcertPitchStemOrientation"):
            t = template.find(tag)
            if t is not None:
                b.append(etree.fromstring(etree.tostring(t)))
        if note is not None:
            string, fret, midi, t_or, t_de, tr_oct = note
            nid = self._new_id("Notes")
            n = etree.SubElement(self.root.find("Notes"), "Note", id=nid)
            if t_or or t_de:
                etree.SubElement(n, "Tie", origin=str(t_or).lower(), destination=str(t_de).lower())
            etree.SubElement(n, "InstrumentArticulation").text = "0"
            props = etree.SubElement(n, "Properties")
            self._pitch_el(props, "ConcertPitch", midi)
            fp = etree.SubElement(props, "Property", name="Fret"); etree.SubElement(fp, "Fret").text = str(fret)
            mp = etree.SubElement(props, "Property", name="Midi"); etree.SubElement(mp, "Number").text = str(midi)
            sp = etree.SubElement(props, "Property", name="String"); etree.SubElement(sp, "String").text = str(string)
            self._pitch_el(props, "TransposedPitch", midi - 12 * tr_oct)
            self.notes[nid] = n
            etree.SubElement(b, "Notes").text = nid
        tp = template.find("Properties")
        if tp is not None:
            b.append(etree.fromstring(etree.tostring(tp)))
        self.beats[bid] = b
        return bid

    @staticmethod
    def _decompose(n):
        out = []
        while n > 0:
            for size, val, dots in DUR_PIECES:
                if size <= n:
                    out.append((size, val, dots)); n -= size; break
        return out

    def rewrite_track(self, ti, notes):
        """notes: sorted, non-overlapping dict(s, e, string, fret, pitch, dynamic)."""
        self._ids = {k: max([int(i) for i in getattr(self, k.lower())] + [-1])
                     for k in ("Beats", "Notes", "Rhythms")}
        tr = self.tracks[ti].find("Transpose")
        tr_oct = -int(tr.findtext("Octave") or 0) if tr is not None else 0
        # template = first beat of this track (keeps stem/pickup properties)
        first_voice = self.voices[self.bars[self.masterbars[0].findtext("Bars").split()[ti]].findtext("Voices").split()[0]]
        template = self.beats[first_voice.findtext("Beats").split()[0]]
        k = 0
        for mi, mb in enumerate(self.masterbars):
            b0, b1 = self.bar_slots[mi]
            bar = self.bars[mb.findtext("Bars").split()[ti]]
            vids = bar.findtext("Voices").split()
            voice = self.voices[vids[0]]
            while k < len(notes) and notes[k]["e"] <= b0:
                k += 1
            j, cur, new = k, b0, []
            while j < len(notes) and notes[j]["s"] < b1:
                n = notes[j]
                s, e = max(n["s"], b0), min(n["e"], b1)
                if s > cur:
                    new += [self._make_beat(template, v, d, "MF") for _, v, d in self._decompose(s - cur)]
                pieces = self._decompose(e - s)
                for pi, (_, v, d) in enumerate(pieces):
                    dest = pi > 0 or n["s"] < b0
                    orig = pi < len(pieces) - 1 or n["e"] > b1
                    new.append(self._make_beat(template, v, d, n["dynamic"],
                                               (n["string"], n["fret"], n["pitch"], orig, dest, tr_oct)))
                cur = e
                j += 1
            if cur < b1:
                new += [self._make_beat(template, v, d, "MF") for _, v, d in self._decompose(b1 - cur)]
            voice.find("Beats").text = " ".join(new)
            bar.find("Voices").text = " ".join([vids[0]] + ["-1"] * (len(vids) - 1))
        self._prune()

    def _prune(self):
        used_beats = set()
        for v in self.voices.values():
            used_beats.update((v.findtext("Beats") or "").split())
        for bid in list(self.beats):
            if bid not in used_beats:
                el = self.beats.pop(bid)
                el.getparent().remove(el)
        used_notes, used_rh = set(), set()
        for b in self.beats.values():
            used_notes.update((b.findtext("Notes") or "").split())
            used_rh.add(b.find("Rhythm").get("ref"))
        for nid in list(self.notes):
            if nid not in used_notes:
                self.root.find("Notes").remove(self.notes.pop(nid))
        for rid in list(self.rhythms):
            if rid not in used_rh:
                self.root.find("Rhythms").remove(self.rhythms.pop(rid))

    def save(self, path):
        data = etree.tostring(self.root, xml_declaration=True, encoding="utf-8")
        buf = io.BytesIO()
        with zipfile.ZipFile(buf, "w") as z:
            for info, d in self.entries:
                z.writestr(info, data if info.filename == GPIF else d)
        with open(path, "wb") as f:
            f.write(buf.getvalue())
