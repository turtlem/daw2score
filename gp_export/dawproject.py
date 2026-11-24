"""Read a DAWproject file (open format by Bitwig and PreSonus: Bitwig Studio, Studio One, Cubase 14+)
into the project model of project.py. https://github.com/bitwig/dawproject

A .dawproject is a zip holding project.xml (+ metadata.xml and, usually, the audio files). Read:
- Structure: tracks, nested group tracks (contentType "tracks") as folders, channel mute.
- Arrangement lanes: clips (nested clips, playStart, loops, enable), note clips, audio clips with or
  without Warps (time-stretch: one item per warp segment, as a play rate), markers, time-signature
  automation. Time units "beats" / "seconds" are inherited down the timeline as in the spec.
- Transport tempo. Tempo automation is only checked: build_gp supports one constant tempo.
Embedded audio is extracted to <project dir>/gp_export_cache/dawproject_media/<name>/ (once);
external files are resolved relative to the .dawproject file.

Not read: clip launcher scenes, automation other than tempo/time signature, video, plugin states.
"""
import os, zipfile
from lxml import etree

import project

INF = float("inf")


def _f(el, attr, default=None):
    v = el.get(attr)
    return float(v) if v not in (None, "") else default


class _Ctx:
    """Maps a content position (in `unit`) to timeline seconds: A + R * seconds(x, unit), visible in
    window [w0, w1) (timeline seconds). R is the stretch factor from Warps (1 = no stretch)."""
    def __init__(self, bpm, A=0.0, R=1.0, w0=-INF, w1=INF, unit="beats", track=None, mute=False):
        self.bpm, self.A, self.R, self.w0, self.w1 = bpm, A, R, w0, w1
        self.unit, self.track, self.mute = unit, track, mute

    def sec(self, x, unit=None):
        return x * 60.0 / self.bpm if (unit or self.unit) == "beats" else x

    def at(self, x, unit=None):
        return self.A + self.R * self.sec(x, unit)

    def child(self, **kw):
        c = _Ctx(self.bpm, self.A, self.R, self.w0, self.w1, self.unit, self.track, self.mute)
        for k, v in kw.items():
            setattr(c, k, v)
        return c


class _Reader:
    def __init__(self, path, zf, root, bpm, media_dir):
        self.path, self.zf, self.root, self.bpm, self.media_dir = path, zf, root, bpm, media_dir
        self.content = {}       # track id -> {"audio": [items], "notes": [(s, e, key, vel, ch)]}
        self.warnings = set()
        self.ids = {el.get("id"): el for el in root.iter() if el.get("id")}

    def media(self, file_el):
        p = file_el.get("path")
        if file_el.get("external") == "true":
            full = p if os.path.isabs(p) or (len(p) > 1 and p[1] == ":") else \
                os.path.join(os.path.dirname(self.path), p)
            return os.path.normpath(full)
        out = os.path.join(self.media_dir, *p.replace("\\", "/").split("/"))
        if not os.path.exists(out):
            os.makedirs(os.path.dirname(out), exist_ok=True)
            with self.zf.open(p.replace("\\", "/")) as src, open(out, "wb") as dst:
                dst.write(src.read())
        return out

    def bucket(self, ctx):
        return self.content.setdefault(ctx.track, {"audio": [], "notes": []})

    # ---- timeline walk
    def walk(self, el, ctx):
        tag = etree.QName(el).localname
        if tag in ("Lanes", "Clips", "Notes", "Warps", "Audio", "Markers", "Points", "Timeline", "Video", "ClipSlot"):
            ctx = ctx.child(unit=el.get("timeUnit") or ctx.unit, track=el.get("track") or ctx.track)
        if tag in ("Lanes", "Clips", "Timeline"):
            for c in el:
                if isinstance(c.tag, str):
                    self.walk(c, ctx)
        elif tag == "Clip":
            self.clip(el, ctx)
        elif tag == "Notes":
            self.notes(el, ctx)
        elif tag == "Warps":
            self.warps(el, ctx)
        elif tag == "Audio":
            self.audio(el, ctx)
        elif tag in ("Video", "Points", "ClipSlot", "Markers"):
            pass
        else:
            self.warnings.add(f"ignored <{tag}>")

    def clip(self, el, ctx):
        if el.get("enable") == "false":
            return
        pu = ctx.unit
        cu = el.get("contentTimeUnit") or pu
        start = ctx.at(_f(el, "time", 0.0), pu)
        play0 = _f(el, "playStart", 0.0)
        dur = _f(el, "duration")
        if dur is None:
            stop = _f(el, "playStop")
            dur_s = ctx.R * ctx.sec(stop - play0, cu) if stop is not None else INF
        else:
            dur_s = ctx.R * ctx.sec(dur, pu)
        w0, w1 = max(ctx.w0, start), min(ctx.w1, start + dur_s)
        if w1 <= w0:
            return
        content = [c for c in el if isinstance(c.tag, str)]
        if not content and el.get("reference") in self.ids:
            content = [self.ids[el.get("reference")]]
        l0, l1 = _f(el, "loopStart"), _f(el, "loopEnd")
        passes = []  # (content start, content end, timeline start)
        if l0 is not None and l1 is not None and l1 > l0:
            t, c0 = start, play0
            while t < w1 and len(passes) < 10000:
                c1 = l1 if c0 < l1 else c0 + (l1 - l0)
                passes.append((c0, c1, t))
                t += ctx.R * ctx.sec(c1 - c0, cu)
                c0 = l0
        else:
            passes.append((play0, INF, start))
        for c0, c1, t in passes:
            seg_end = t + ctx.R * ctx.sec(c1 - c0, cu) if c1 < INF else INF
            sub = ctx.child(A=t - ctx.R * ctx.sec(c0, cu), unit=cu,
                            w0=max(w0, t), w1=min(w1, seg_end))
            for c in content:
                self.walk(c, sub)

    def notes(self, el, ctx):
        b = self.bucket(ctx)
        for n in el:
            if not isinstance(n.tag, str) or etree.QName(n).localname != "Note":
                continue
            s, e = ctx.at(_f(n, "time")), ctx.at(_f(n, "time") + _f(n, "duration"))
            if not (ctx.w0 - 1e-6 <= s < ctx.w1):
                continue
            vel = _f(n, "vel", 0.8)
            b["notes"].append((s, min(e, ctx.w1), int(n.get("key")), max(1, round(vel * 127)),
                               int(n.get("channel") or 0)))

    def warps(self, el, ctx):
        cu = el.get("contentTimeUnit") or "seconds"
        wu = el.get("timeUnit") or ctx.unit
        pts = sorted(((_f(w, "time"), _f(w, "contentTime")) for w in el
                      if isinstance(w.tag, str) and etree.QName(w).localname == "Warp"))
        content = [c for c in el if isinstance(c.tag, str) and etree.QName(c).localname != "Warp"]
        if len(pts) < 2:
            self.warnings.add("Warps with fewer than 2 points: content placed unstretched")
            for c in content:
                self.walk(c, ctx.child(unit=cu))
            return
        for k in range(len(pts) - 1):
            (t0, c0), (t1, c1) = pts[k], pts[k + 1]
            o0, o1 = ctx.at(t0, wu), ctx.at(t1, wu)
            s0, s1 = ctx.sec(c0, cu), ctx.sec(c1, cu)
            if s1 <= s0 or o1 <= o0:
                continue
            ratio = (o1 - o0) / (s1 - s0)             # timeline seconds per content second
            sub = ctx.child(A=o0 - ratio * s0, R=ratio, unit=cu,
                            w0=max(ctx.w0, o0 if k else -INF), w1=min(ctx.w1, o1 if k < len(pts) - 2 else INF))
            for c in content:
                self.walk(c, sub)

    def audio(self, el, ctx):
        f = el.find("{*}File") if el.find("{*}File") is not None else el.find("File")
        if f is None:
            return
        dur = _f(el, "duration", 0.0)                 # seconds of audio
        a0 = ctx.A                                    # timeline seconds of audio position 0
        pos, end = max(ctx.w0, a0), min(ctx.w1, a0 + ctx.R * dur)
        if end - pos < 1e-4:
            return
        self.bucket(ctx)["audio"].append({
            "position": pos, "length": end - pos, "soffs": (pos - a0) / ctx.R, "playrate": 1.0 / ctx.R,
            "loop": False, "mute": False, "src_type": "WAVE", "file": self.media(f)})


def _points(el, tag):
    return [p for p in el if isinstance(p.tag, str) and etree.QName(p).localname == tag]


def load(path):
    zf = zipfile.ZipFile(path)
    names = {n.lower(): n for n in zf.namelist()}
    if "project.xml" not in names:
        raise SystemExit(f"{path}: no project.xml inside (not a DAWproject file?)")
    root = etree.fromstring(zf.read(names["project.xml"]))
    q = lambda el, tag: el.find(f"{{*}}{tag}") if el.find(f"{{*}}{tag}") is not None else el.find(tag)

    tr = q(root, "Transport")
    tempo_el = q(tr, "Tempo") if tr is not None else None
    bpm = _f(tempo_el, "value", 120.0) if tempo_el is not None else 120.0
    ts_el = q(tr, "TimeSignature") if tr is not None else None
    ts_num = int(ts_el.get("numerator")) if ts_el is not None else 4
    ts_den = int(ts_el.get("denominator")) if ts_el is not None else 4

    name = os.path.splitext(os.path.basename(path))[0]
    media = os.path.join(os.path.dirname(path), "gp_export_cache", "dawproject_media", name)
    rd = _Reader(path, zf, root, bpm, media)

    # structure -> track list (folders first, then children)
    tracks, by_id = [], {}

    def add_track(el, depth):
        types = (el.get("contentType") or "").replace(",", " ").split()
        kids = [c for c in el if isinstance(c.tag, str) and etree.QName(c).localname == "Track"]
        ch = q(el, "Channel")
        mute_el = q(ch, "Mute") if ch is not None else None
        t = {"index": len(tracks), "name": el.get("name") or f"Track {len(tracks) + 1}", "depth": depth,
             "is_folder": bool(kids) or "tracks" in types, "items": [], "fx": "", "drums": None,
             "mute": mute_el is not None and mute_el.get("value") == "true", "types": types}
        if ch is not None and q(ch, "Devices") is not None:
            t["fx"] = " ".join(d.get("deviceName") or d.get("name") or "" for d in q(ch, "Devices")
                               if isinstance(d.tag, str))
        tracks.append(t)
        by_id[el.get("id")] = t
        for k in kids:
            add_track(k, depth + 1)

    st = q(root, "Structure")
    for el in (st if st is not None else []):
        if isinstance(el.tag, str) and etree.QName(el).localname == "Track":
            add_track(el, 0)

    arr = q(root, "Arrangement")
    markers, ts_points, tempo_vals = [], [], []
    if arr is not None:
        lanes = q(arr, "Lanes")
        if lanes is not None:
            rd.walk(lanes, _Ctx(bpm))
        ctx = _Ctx(bpm)
        mk = q(arr, "Markers")
        if mk is not None:
            u = mk.get("timeUnit") or "beats"
            markers = [(ctx.sec(_f(m, "time"), u), m.get("name") or "") for m in _points(mk, "Marker")]
        ta = q(arr, "TempoAutomation")
        if ta is not None:
            tempo_vals = [_f(p, "value") for p in _points(ta, "RealPoint")]
        tsa = q(arr, "TimeSignatureAutomation")
        if tsa is not None:
            u = tsa.get("timeUnit") or "beats"
            for p in _points(tsa, "TimeSignaturePoint"):
                t = ctx.sec(_f(p, "time"), u)
                num, den = int(p.get("numerator")), int(p.get("denominator"))
                if t <= 1e-6:
                    ts_num, ts_den = num, den
                else:
                    ts_points.append([f"{t}", f"{bpm}", "0", str((den << 16) | num)])
    if tempo_vals and (max(tempo_vals) - min(tempo_vals) > 1e-3 or abs(tempo_vals[0] - bpm) > 1e-3):
        print(f"WARNING: DAWproject tempo automation ({min(tempo_vals):g}-{max(tempo_vals):g} BPM) is not "
              f"supported; using {bpm:g} BPM")

    for tid, c in rd.content.items():
        t = by_id.get(tid)
        if t is None:
            continue
        for it in c["audio"]:
            it["mute"] = t["mute"]
        t["items"].extend(sorted(c["audio"], key=lambda i: i["position"]))
        if c["notes"]:
            drums = all(n[4] == 9 for n in c["notes"])
            t["items"].append(project.midi_item([n[:4] for n in c["notes"]], bpm, drums, t["mute"]))
            t["drums"] = drums or None
    for w in sorted(rd.warnings):
        print(f"note (dawproject): {w}")
    info = {"tempo": bpm, "ts_num": ts_num, "ts_den": ts_den, "tempo_points": ts_points,
            "markers": sorted(markers), "tempo_source": "dawproject"}
    return project.Project(path, name, tracks, info)
