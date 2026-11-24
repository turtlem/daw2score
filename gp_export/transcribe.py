"""Render selected REAPER audio tracks from the .rpp (active takes, offsets) and transcribe with basic-pitch.

usage: transcribe.py <project.rpp> <out_dir> <track_index> [<track_index> ...]
Writes <out_dir>/<idx>_<name>.wav and <out_dir>/<idx>.json (cached: skipped if json exists).
"""
import json, os, re, sys, warnings
import numpy as np
import soundfile as sf

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import rpp

warnings.filterwarnings("ignore")
SR = 22050


def profile(name):
    n = name.lower()
    if "bass" in n:
        return dict(kind="bass", fmin=30, fmax=400, onset=0.5, frame=0.3, min_len=90, max_poly=1)
    if "solo" in n:
        return dict(kind="gtr_solo", fmin=75, fmax=1700, onset=0.5, frame=0.3, min_len=70, max_poly=1)
    if "clean" in n:
        return dict(kind="gtr_clean", fmin=75, fmax=1400, onset=0.5, frame=0.3, min_len=90, max_poly=6)
    if "gtr" in n or "guit" in n or re.search(r"\bgt\b", n):
        return dict(kind="gtr_heavy", fmin=70, fmax=1000, onset=0.6, frame=0.35, min_len=90, max_poly=3)
    if "chant" in n or "vocal" in n or "voix" in n or re.search(r"\bvx\b", n):
        return dict(kind="vocal", fmin=70, fmax=1100, onset=0.5, frame=0.3, min_len=110, max_poly=1)
    return dict(kind="other", fmin=30, fmax=2000, onset=0.5, frame=0.3, min_len=90, max_poly=6)


def resample(x, sr_in, sr_out):
    if sr_in == sr_out:
        return x
    import soxr
    return soxr.resample(x, sr_in, sr_out)


def render(proj_dir, its):
    its = [i for i in its if not i["mute"] and i.get("file")]
    if not its:
        return None, 0.0
    t0 = min(i["position"] for i in its)
    t1 = max(i["position"] + i["length"] for i in its)
    buf = np.zeros(int((t1 - t0) * SR) + SR, dtype=np.float32)
    cache = {}
    for i in its:
        path = i["file"] if os.path.isabs(i["file"]) else os.path.join(proj_dir, i["file"])
        if path not in cache:
            x, sr = sf.read(path, dtype="float32", always_2d=True)
            cache[path] = resample(x.mean(axis=1), sr, SR).astype(np.float32)
        src = cache[path]
        rate = i["playrate"] or 1.0
        n_out = int(i["length"] * SR)
        start = int(i["soffs"] * SR)
        idx = start + (np.arange(n_out) * rate).astype(np.int64)
        if i["loop"] and len(src):
            idx %= len(src)
        valid = idx < len(src)
        seg = np.zeros(n_out, dtype=np.float32)
        seg[valid] = src[idx[valid]]
        o = int((i["position"] - t0) * SR)
        buf[o:o + n_out] += seg[: len(buf) - o]
    peak = np.abs(buf).max()
    if peak > 0:
        buf /= peak
    return buf, t0


def main():
    run(sys.argv[1], sys.argv[2], [int(a) for a in sys.argv[3:]])


def run(proj_path, out_dir, wanted):
    os.makedirs(out_dir, exist_ok=True)
    proj = rpp.parse(proj_path)
    trs = rpp.tracks(proj)
    from basic_pitch.inference import predict, Model
    from basic_pitch import ICASSP_2022_MODEL_PATH
    model = Model(ICASSP_2022_MODEL_PATH)
    for t in trs:
        if t["index"] not in wanted:
            continue
        jpath = os.path.join(out_dir, f'{t["index"]}.json')
        if os.path.exists(jpath):
            print(f'[{t["index"]}] {t["name"]}: cached', flush=True)
            continue
        its = rpp.items(t["node"])
        buf, t0 = render(os.path.dirname(proj_path), its)
        if buf is None:
            print(f'[{t["index"]}] {t["name"]}: no audio', flush=True)
            continue
        p = profile(t["name"])
        safe = re.sub(r"[^\w-]+", "_", t["name"])
        wav = os.path.join(out_dir, f'{t["index"]}_{safe}.wav')
        sf.write(wav, buf, SR, subtype="PCM_16")
        _, _, events = predict(wav, model, onset_threshold=p["onset"], frame_threshold=p["frame"],
                               minimum_note_length=p["min_len"], minimum_frequency=p["fmin"],
                               maximum_frequency=p["fmax"], melodia_trick=True)
        notes = [{"start": float(s) + t0, "end": float(e) + t0, "pitch": int(pi), "amp": float(a)}
                 for s, e, pi, a, *_ in events]
        notes.sort(key=lambda n: (n["start"], n["pitch"]))
        json.dump({"index": t["index"], "name": t["name"], "profile": p, "notes": notes},
                  open(jpath, "w", encoding="utf-8"))
        print(f'[{t["index"]}] {t["name"]}: {len(notes)} notes ({p["kind"]}), '
              f'{sum(1 for i in its if i.get("n_takes", 1) > 1)} multi-take items', flush=True)


if __name__ == "__main__":
    main()
