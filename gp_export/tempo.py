"""Detect the tempo of a recording played to a click (export_gp.py --tempo auto).

Beat tracking (librosa) on the drum tracks (or every audio track when there are none), then a
straight-line fit beat_time = offset + k * period over the whole song. A small residual (~20 ms)
means a constant tempo; the offset tells whether the beat grid starts at 0 s, which the score needs.

usage: tempo.py <project.rpp | stems folder>
"""
import os, re, sys
import numpy as np

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import project, transcribe

DRUMS = re.compile(r"drum|batterie|kick|snare|caisse|\bhh\b|hat|tom|\boh\b|overhead", re.I)


def detect(proj_path, idxs=None):
    """-> dict(bpm, offset, residual_ms, max_ms, n_beats, tracks)"""
    import librosa
    p = project.load(proj_path)
    audio = [t for t in p.tracks if any(i.get("file") and not i["mute"] for i in t["items"])]
    if idxs:
        use = [t for t in audio if t["index"] in idxs]
    else:
        folders = [t for t in p.tracks if t["is_folder"] and DRUMS.search(t["name"])]
        in_folder = {c["index"] for f in folders for c in p.tracks[f["index"] + 1:]
                     if c["depth"] > f["depth"]} if folders else set()
        use = [t for t in audio if DRUMS.search(t["name"]) or t["index"] in in_folder]
        use = [t for t in use if not re.search(r"room|amb|shaker", t["name"], re.I)] or audio
    if not use:
        raise SystemExit("no audio track to detect the tempo from")
    sr = transcribe.SR
    end = max(i["position"] + i["length"] for t in use for i in t["items"])
    mix = np.zeros(int((end + 1) * sr), np.float32)
    for t in use:
        buf, t0 = transcribe.render(None, t["items"])
        if buf is None:
            continue
        o = int(round(t0 * sr))
        n = min(len(buf), len(mix) - o)
        mix[o:o + n] += buf[:n]
    hop = 256
    env = librosa.onset.onset_strength(y=mix, sr=sr, hop_length=hop)
    _, beats = librosa.beat.beat_track(onset_envelope=env, sr=sr, hop_length=hop, units="time", tightness=400)
    if len(beats) < 16:
        raise SystemExit("not enough beats found to estimate a tempo")
    k = np.arange(len(beats))
    period, offset = np.polyfit(k, beats, 1)
    res = beats - (offset + k * period)
    return {"bpm": 60.0 / period, "offset": float(offset % period), "period": float(period),
            "residual_ms": float(res.std() * 1000), "max_ms": float(np.abs(res).max() * 1000),
            "n_beats": len(beats), "tracks": [t["name"] for t in use]}


def report(d):
    off = min(d["offset"], d["period"] - d["offset"])
    print(f"tempo: {d['bpm']:.2f} BPM from {len(d['tracks'])} track(s), {d['n_beats']} beats, "
          f"grid residual {d['residual_ms']:.0f} ms (max {d['max_ms']:.0f} ms)")
    if d["residual_ms"] > 35:
        print("  WARNING: the tempo drifts (not played to a click?): bars will not line up everywhere")
    if off * 1000 > 40:
        print(f"  WARNING: the beats are {off * 1000:.0f} ms off the grid that starts at 0 s; "
              f"re-export the stems from bar 1 (or trim {d['offset']:.3f} s)")


def main():
    d = detect(sys.argv[1])
    report(d)


if __name__ == "__main__":
    main()
