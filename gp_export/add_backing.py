"""Embed a mix of REAPER tracks (e.g. stems) as the Guitar Pro 8 audio track ("backing track") of a .gp file.

usage: add_backing.py <score.gp> <project.rpp> <rpp track name> [...] [--out OUT.gp] [--replace]

GP8 supports a single audio track per file, so the named tracks are summed into one stereo 44.1 kHz
MP3 rendered from project time 0 (= start of bar 1), stored as Content/Assets/backing-track.mp3.
Sync points are written at the first and last bar (constant tempo; the audio is already aligned).
GPIF structure follows alphaTab's GpifWriter (BackingTrack after MasterTrack, Assets after MasterBars).
Without --out the input is overwritten after writing <name>.before-backing.gp.
"""
import argparse, io, os, shutil, sys, tempfile, zipfile
import numpy as np
import soundfile as sf
from lxml import etree

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import gpif, project

SR = 44100  # GP sync frame offsets are always in 44.1 kHz frames
ASSET = "Content/Assets/backing-track.mp3"
CHANNEL_STRIP = "0.500000 0.500000 0.500000 0.500000 0.500000 0.500000 0.500000 0.500000 0.500000 " \
                "0.000000 0.500000 0.500000 0.800000 0.500000 0.500000 0.500000"


def render_stereo(proj_dir, tracks, end_s):
    out = np.zeros((int(end_s * SR) + 1, 2), dtype=np.float32)
    cache = {}
    for t in tracks:
        for it in t["items"]:
            if it["mute"] or not it.get("file"):
                continue
            path = it["file"] if os.path.isabs(it["file"]) else os.path.join(proj_dir, it["file"])
            if path not in cache:
                x, sr = sf.read(path, dtype="float32", always_2d=True)
                if x.shape[1] == 1:
                    x = np.repeat(x, 2, axis=1)
                x = x[:, :2]
                if sr != SR:
                    import soxr
                    x = soxr.resample(x, sr, SR).astype(np.float32)
                cache[path] = x
            src = cache[path]
            n = int(it["length"] * SR)
            idx = int(it["soffs"] * SR) + (np.arange(n) * (it["playrate"] or 1.0)).astype(np.int64)
            if it["loop"]:
                idx %= len(src)
            ok = idx < len(src)
            o = int(it["position"] * SR)
            n_fit = max(0, min(n, len(out) - o))
            seg = np.zeros((n, 2), dtype=np.float32)
            seg[ok] = src[idx[ok]]
            out[o:o + n_fit] += seg[:n_fit]
    peak = float(np.abs(out).max())
    if peak > 0.99:
        out *= 0.99 / peak
    return out, peak


def el(parent, tag, text=None, cdata=False, **attrs):
    e = etree.SubElement(parent, tag, **attrs)
    if text is not None:
        e.text = etree.CDATA(text) if cdata else text
    return e


def sync_point(parent, bar, frame, tempo, visible):
    a = el(parent, "Automation")
    el(a, "Type", "SyncPoint"); el(a, "Linear", "false"); el(a, "Bar", str(bar))
    el(a, "Position", "0"); el(a, "Visible", "true" if visible else "false")
    v = el(a, "Value")
    el(v, "BarIndex", str(bar)); el(v, "BarOccurrence", "0")
    el(v, "ModifiedTempo", f"{tempo:g}"); el(v, "OriginalTempo", f"{tempo:g}")
    el(v, "FrameOffset", str(frame))


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("score"); ap.add_argument("project"); ap.add_argument("tracks", nargs="+")
    ap.add_argument("--name", help="audio track name shown in Guitar Pro")
    ap.add_argument("--out"); ap.add_argument("--replace", action="store_true")
    a = ap.parse_args()
    add(a.score, a.project, a.tracks, name=a.name, out=a.out, replace=a.replace)


def add(score, proj_path, track_refs, name=None, out=None, replace=False):
    """Embed the mix of track_refs (track names or 0-based indices) as the audio track of score."""
    sc = gpif.Score(score)
    r = sc.root
    if r.find("BackingTrack") is not None and not replace:
        sys.exit("this score already has an audio track (use --replace)")

    P = project.load(proj_path)
    info = P.info
    bpm = info["tempo"]
    # the score's own tempo wins (export_gp.py --tempo may differ from the project's)
    for auto in r.iter("Automation"):
        if auto.findtext("Type") == "Tempo" and auto.findtext("Bar") in ("0", None):
            score_bpm = float(auto.findtext("Value").split()[0])
            if abs(score_bpm - bpm) > 1e-6:
                print(f"using the score tempo {score_bpm:g} BPM (project: {bpm:g})")
            bpm = score_bpm
            break
    by_name = {t["name"]: t for t in P.tracks}
    missing = [n for n in track_refs if not isinstance(n, int) and n not in by_name]
    if missing:
        sys.exit(f"tracks not found in project: {missing}")
    tracks = [P.tracks[n] if isinstance(n, int) else by_name[n] for n in track_refs]
    sps = 60.0 / bpm / 4  # seconds per 16th slot
    end_s = max([sc.bar_slots[-1][1] * sps] + [i["position"] + i["length"] for t in tracks
                                                for i in t["items"] if not i["mute"]])
    audio, peak = render_stereo(P.dir, tracks, end_s)

    with tempfile.TemporaryDirectory() as td:
        mp3 = os.path.join(td, "mix.mp3")
        sf.write(mp3, audio, SR, format="MP3", subtype="MPEG_LAYER_III", compression_level=0.2)
        mp3_bytes = open(mp3, "rb").read()

    # --- GPIF edits
    for tag in ("BackingTrack", "Assets"):
        old = r.find(tag)
        if old is not None:
            r.remove(old)
    for auto in r.findall("MasterTrack/Automations/Automation"):
        if auto.findtext("Type") == "SyncPoint":
            auto.getparent().remove(auto)

    name = name or " + ".join(t["name"] for t in tracks)
    bt = etree.Element("BackingTrack")
    el(bt, "IconId", "21"); el(bt, "Color", "0 0 0")
    el(bt, "Name", name, cdata=True); el(bt, "ShortName", name[:12], cdata=True)
    el(bt, "PlaybackState", "Default"); el(bt, "Enabled", "true"); el(bt, "Source", "Local")
    el(bt, "AssetId", "0")
    cs = el(bt, "ChannelStrip")
    el(cs, "Parameters", CHANNEL_STRIP); el(cs, "YouTubeVideoUrl", ""); el(cs, "Filter", "6")
    el(cs, "FramesPerPixel", "400")
    el(bt, "FramePadding", "0"); el(bt, "Semitones", "0"); el(bt, "Cents", "0")
    r.find("MasterTrack").addnext(bt)

    assets = etree.Element("Assets")
    el(el(assets, "Asset", id="0"), "EmbeddedFilePath", ASSET, cdata=True)
    r.find("MasterBars").addnext(assets)

    autos = r.find("MasterTrack/Automations")
    if autos is None:
        autos = el(r.find("MasterTrack"), "Automations")
    last = len(sc.masterbars) - 1
    sync_point(autos, 0, 0, bpm, True)
    sync_point(autos, last, int(round(sc.bar_slots[last][0] * sps * SR)), bpm, False)

    # --- write zip (asset stored uncompressed, other entries untouched)
    if not out:
        out = score
        base, ext = os.path.splitext(score)
        backup = base + ".before-backing" + ext
        if os.path.exists(backup):
            sys.exit(f"backup {backup} already exists; move it away or pass --out")
        shutil.copy2(score, backup)
        print("backup:", backup)
    data = etree.tostring(r, xml_declaration=True, encoding="utf-8")
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w") as z:
        for info_, d in sc.entries:
            if info_.filename == ASSET:
                continue
            z.writestr(info_, data if info_.filename == gpif.GPIF else d)
        z.writestr(zipfile.ZipInfo(ASSET), mp3_bytes)
    open(out, "wb").write(buf.getvalue())

    # --- verify
    chk = gpif.Score(out)
    with zipfile.ZipFile(out) as z:
        dec, dsr = sf.read(io.BytesIO(z.read(ASSET)))
    print(f"audio track {name!r}: {len(audio) / SR:.1f}s rendered (peak {peak:.2f}), mp3 {len(mp3_bytes) / 1e6:.1f} MB, "
          f"decodes to {len(dec) / dsr:.1f}s @ {dsr} Hz")
    print(f"sync points: bar 1 @ 0, bar {last + 1} @ {sc.bar_slots[last][0] * sps:.3f}s | "
          f"score still has {len(chk.masterbars)} bars, {len(chk.tracks)} tracks")
    print("written:", out)


if __name__ == "__main__":
    main()
