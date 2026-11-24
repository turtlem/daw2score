"""Transcribe a multitrack drum recording (one folder of close mics + overheads) into GM drum notes.

usage: drums_audio.py <project.rpp> <out_dir> <folder_track>

Each child track of the folder gets a role from its name (kick / snare / tom hi|mid|lo / hh / oh /
cowbell); rooms, shakers and unknown names are ignored. Hits are found per mic with onset detection
on a band-limited signal, then filtered against bleed from the other mics. Writes
<out_dir>/<folder idx>.json in the same format as transcribe.py (times in seconds) with profile kind
"drums", which build_gp.py writes as a percussion track.

Reliable: kick, snare, toms (close mics). Approximate: hi-hat open/closed (from decay length),
crashes (long high-frequency decays in the overheads). Not detected: ride, hi-hat pedal, flams.
"""
import json, os, re, sys
import numpy as np
import librosa
from scipy.signal import butter, sosfiltfilt

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import rpp, transcribe

SR = transcribe.SR
HOP = 64                      # 2.9 ms analysis frames
GM = {"kick": 36, "snare": 38, "tom_hi": 50, "tom_mid": 47, "tom_lo": 43,
      "hh_closed": 42, "hh_open": 46, "crash": 49, "cowbell": 56}


def role(name):
    n = name.lower()
    if re.search(r"room|amb|shaker|tamb|clap|talk", n):
        return None
    if re.search(r"kick|\bbd\b|grosse", n):
        return "kick"
    if re.search(r"snare|caisse|\bsn\b", n):
        return "snare_bot" if re.search(r"bot|under|dessous", n) else "snare"
    if "tom" in n:
        if re.search(r"hi|high|\b1\b|rack", n):
            return "tom_hi"
        if re.search(r"mid|\b2\b", n):
            return "tom_mid"
        return "tom_lo"
    if re.search(r"\bhh|hat|charley|charleston", n):
        return "hh"
    if re.search(r"\boh|overhead", n):
        return "oh"
    if re.search(r"cloche|cowbell", n):
        return "cowbell"
    return None


def band(x, lo=None, hi=None):
    if lo and hi:
        sos = butter(4, [lo, hi], btype="band", fs=SR, output="sos")
    elif lo:
        sos = butter(4, lo, btype="high", fs=SR, output="sos")
    else:
        sos = butter(4, hi, btype="low", fs=SR, output="sos")
    return sosfiltfilt(sos, x).astype(np.float32)


def envelope(x):
    """Peak envelope on HOP frames."""
    n = len(x) // HOP
    return np.abs(x[:n * HOP]).reshape(n, HOP).max(axis=1)


def onsets(x, delta=0.07, wait_s=0.06):
    env = librosa.onset.onset_strength(y=x, sr=SR, hop_length=HOP, n_mels=32, fmax=SR / 2, lag=2, max_size=3)
    fr = librosa.onset.onset_detect(onset_envelope=env, sr=SR, hop_length=HOP, backtrack=False,
                                    delta=delta, wait=int(wait_s * SR / HOP))
    return fr


def peaks_at(env, frames, win_s=0.03):
    w = int(win_s * SR / HOP)
    return np.array([env[f:f + w].max() if f < len(env) else 0.0 for f in frames])


def decay_len(env, f, peak, until, frac=0.3):
    """Seconds the envelope stays above frac*peak after frame f (stopping at frame `until`)."""
    seg = env[f:min(until, len(env))]
    below = np.nonzero(seg < frac * peak)[0]
    n = below[0] if len(below) else len(seg)
    return n * HOP / SR


def smooth(env, s=0.02):
    k = max(1, int(s * SR / HOP))
    return np.convolve(env, np.ones(k) / k, mode="same")


def track_audio(pdir, t, length):
    buf, t0 = transcribe.render(pdir, rpp.items(t["node"]))
    out = np.zeros(length, np.float32)
    if buf is None:
        return out
    o = int(round(t0 * SR))
    n = min(len(buf), length - o)
    out[o:o + n] = buf[:n] * 1.0
    return out


def hits(sig, ref_sigs=(), thr=0.2, ratio_k=3.0, delta=0.07):
    """Onsets in `sig`, kept if loud enough (vs. its own 95th-percentile hit) and, for each reference
    mic, louder relative to it than bleed usually is (ratio > ratio_k * median ratio)."""
    env = envelope(sig)
    fr = onsets(sig, delta=delta)
    if not len(fr):
        return fr, np.array([]), env
    pk = peaks_at(env, fr)
    norm = pk / (np.percentile(pk, 95) + 1e-9)
    keep = norm >= thr
    for ref in ref_sigs:
        renv = envelope(ref)
        r = pk / (peaks_at(renv, fr) + 1e-9)
        keep &= r > ratio_k * np.median(r)
    return fr[keep], np.clip(norm[keep], 0, 1.2), env


def transcribe_folder(proj_path, folder_idx):
    proj = rpp.parse(proj_path)
    trs = rpp.tracks(proj)
    pdir = os.path.dirname(os.path.abspath(proj_path))
    folder = trs[folder_idx]
    kids = []
    for c in trs[folder_idx + 1:]:
        if c["depth"] <= folder["depth"]:
            break
        if not c["is_folder"]:
            kids.append(c)
    ends = [i["position"] + i["length"] for c in kids for i in rpp.items(c["node"])]
    length = int((max(ends) + 1) * SR)
    mics = {}
    for c in kids:
        r = role(c["name"])
        if r is None:
            print(f"  ignore {c['name']!r}")
            continue
        x = track_audio(pdir, c, length)
        x /= np.abs(x).max() + 1e-9
        mics[r] = mics.get(r, 0) + x
        print(f"  {c['name']!r} -> {r}")
    notes = []

    def add(frames, norms, gm, dur=0.1):
        for f, a in zip(frames, norms):
            t = f * HOP / SR
            notes.append({"start": round(t, 4), "end": round(t + dur, 4), "pitch": gm, "amp": round(float(min(a, 1.0)) * 0.7, 3)})

    if "kick" in mics:
        k = band(mics["kick"], hi=110)
        refs = [band(mics[t], hi=110) for t in ("tom_lo",) if t in mics]
        fr, nm, _ = hits(k, refs, thr=0.25, ratio_k=0.3)
        add(fr, nm, GM["kick"])
    snare_fr = np.array([], int)
    if "snare" in mics:
        s = band(mics["snare"], 300, 5000)
        refs = [band(mics["hh"], 300, 5000)] if "hh" in mics else []
        snare_fr, nm, _ = hits(s, refs, thr=0.18, ratio_k=0.3)
        add(snare_fr, nm, GM["snare"])
    toms = [t for t in ("tom_hi", "tom_mid", "tom_lo") if t in mics]
    for t in toms:
        x = band(mics[t], 60, 1000)
        refs = [band(mics["snare"], 60, 1000)] if "snare" in mics else []
        refs += [band(mics[o], 60, 1000) for o in toms if o != t]
        fr, nm, _ = hits(x, refs, thr=0.3, ratio_k=3.0)
        add(fr, nm, GM[t], dur=0.2)
    if "hh" in mics:
        h = band(mics["hh"], lo=6000)
        refs = [band(mics["snare"], lo=6000)] if "snare" in mics else []
        fr, nm, env = hits(h, refs, thr=0.08, ratio_k=0.4, delta=0.05)
        snare_t = snare_fr * HOP / SR
        sm = smooth(env)
        for i, (f, a) in enumerate(zip(fr, nm)):
            nxt = fr[i + 1] if i + 1 < len(fr) else len(sm)
            pk = sm[f:f + int(0.03 * SR / HOP)].max()
            d = decay_len(sm, f, pk, nxt)
            # a simultaneous snare hit rings in the hi-hat mic too: ask for a longer decay then
            with_snare = len(snare_t) and np.abs(snare_t - f * HOP / SR).min() < 0.03
            is_open = d > (0.3 if with_snare else 0.16)
            add([f], [a], GM["hh_open" if is_open else "hh_closed"])
    if "oh" in mics:
        o = band(mics["oh"], lo=5000)
        refs = [band(mics["hh"], lo=5000)] if "hh" in mics else []
        fr, nm, env = hits(o, refs, thr=0.35, ratio_k=1.5, delta=0.1)
        sm = smooth(env, 0.05)
        for f, a in zip(fr, nm):
            pk = sm[f:f + int(0.05 * SR / HOP)].max()
            if decay_len(sm, f, pk, len(sm), frac=0.3) > 0.5:
                add([f], [a], GM["crash"], dur=0.5)
    if "cowbell" in mics:
        fr, nm, _ = hits(band(mics["cowbell"], 500, 8000), thr=0.3, ratio_k=0)
        add(fr, nm, GM["cowbell"])
    notes.sort(key=lambda n: (n["start"], n["pitch"]))
    return notes


def run(proj_path, out_dir, folder_idx):
    os.makedirs(out_dir, exist_ok=True)
    out = os.path.join(out_dir, f"{folder_idx}.json")
    if os.path.exists(out):
        print(f"cached {out}")
        return out
    print(f"drum transcription of folder [{folder_idx}]")
    notes = transcribe_folder(proj_path, folder_idx)
    import collections
    print("  hits:", dict(collections.Counter(n["pitch"] for n in notes)))
    with open(out, "w", encoding="utf-8") as f:
        json.dump({"profile": {"kind": "drums"}, "notes": notes}, f)
    return out


if __name__ == "__main__":
    run(sys.argv[1], sys.argv[2], int(sys.argv[3]))
