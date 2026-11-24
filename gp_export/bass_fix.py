"""Clean a transcribed bass line before it is written (export_gp.py --clean-bass).

Same ideas as clean_bass.py (which works on a saved .gp), applied to the note list, plus harmony:
1. One note per 16th: among simultaneous candidates, prefer the chord root, then chord tones, then
   the loudest; octave chosen by checking the bass audio for the lower octave (clean_bass.Spectra).
2. Incoherent leaps: a note more than LEAP semitones away from the median of its neighbours is moved
   by octaves towards it (pitch class kept).
3. Parasites: 16th notes off the kick that are not chord tones, or quiet, are removed.
4. Fragments of the same pitch are merged unless the next one is re-attacked on a kick.
"""
import os, sys
import numpy as np

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import clean_bass

LEAP = 9
WINDOW = 4          # neighbours on each side for the median
LOW, HIGH = 28, 28 + 26   # E1 .. ~F#3: comfortable range on a 4-string


def chord_tones(name):
    import harmony
    if not name or name == "N":
        return None, set()
    root = next(r for r in sorted(harmony.NOTES, key=len, reverse=True) if name.startswith(r))
    pc = harmony.NOTES.index(root)
    return pc, {(pc + i) % 12 for i in harmony.QUAL[name[len(root):]]}


def fix(notes, buf, t0, bpm, slots_per_qn, kicks=(), chord_labels=None, slots_per_beat=None):
    """notes: [{start, end, pitch, vel}] in quarter notes. Returns (notes, stats)."""
    kicks = set(kicks)
    sps = 60.0 / bpm / slots_per_qn
    spec = clean_bass.Spectra(buf, t0, sps) if buf is not None else None
    stats = dict(octave=0, leaps=0, parasites=0, merged=0)

    def chord_at(s):
        if not chord_labels:
            return None, set()
        b = s // (slots_per_beat or slots_per_qn)
        return chord_tones(chord_labels[b] if b < len(chord_labels) else "N")

    groups = {}
    for n in notes:
        s = round(n["start"] * slots_per_qn)
        groups.setdefault(s, []).append({**n, "s": s, "e": max(s + 1, round(n["end"] * slots_per_qn))})
    out = []
    for s in sorted(groups):
        cands = groups[s]
        root, tones = chord_at(s)

        def score(n):
            pc = n["pitch"] % 12
            return (pc == root, pc in tones, n["vel"])
        best = max(cands, key=score)
        same_pc = [c for c in cands if c["pitch"] % 12 == best["pitch"] % 12]
        n = dict(max(same_pc, key=lambda c: c["pitch"]))
        n["e"] = max(c["e"] for c in same_pc)
        if spec is not None:
            for _ in range(2):
                if n["pitch"] - 12 >= LOW and spec.ratio(n, n["pitch"]) > clean_bass.OCT_RATIO:
                    n["pitch"] -= 12; stats["octave"] += 1
                else:
                    break
        while n["pitch"] < LOW:
            n["pitch"] += 12
        while n["pitch"] > HIGH:
            n["pitch"] -= 12
        out.append(n)
    for a, b in zip(out, out[1:]):
        a["e"] = min(a["e"], b["s"])

    # 2. leaps
    for _ in range(2):
        ps = np.array([n["pitch"] for n in out])
        for i, n in enumerate(out):
            nb = np.concatenate([ps[max(0, i - WINDOW):i], ps[i + 1:i + 1 + WINDOW]])
            if not len(nb):
                continue
            m = np.median(nb)
            while n["pitch"] - m > LEAP and n["pitch"] - 12 >= LOW:
                n["pitch"] -= 12; stats["leaps"] += 1
            while m - n["pitch"] > LEAP and n["pitch"] + 12 <= HIGH:
                n["pitch"] += 12; stats["leaps"] += 1
            ps[i] = n["pitch"]

    # 3. parasites
    vels = np.array([n["vel"] for n in out]) if out else np.array([0])
    quiet = np.percentile(vels, 25)
    kept = []
    for n in out:
        _, tones = chord_at(n["s"])
        short = n["e"] - n["s"] <= 1
        off_chord = bool(tones) and n["pitch"] % 12 not in tones
        if short and n["s"] not in kicks and (off_chord or n["vel"] <= quiet):
            stats["parasites"] += 1
            if kept and kept[-1]["e"] == n["s"]:
                kept[-1]["e"] = n["e"]
            continue
        kept.append(n)

    # 4. fragments
    res = []
    for n in kept:
        p = res[-1] if res else None
        if p and p["e"] == n["s"] and p["pitch"] == n["pitch"] and n["s"] not in kicks:
            p["e"] = n["e"]; stats["merged"] += 1
        else:
            res.append(n)
    return [{"start": n["s"] / slots_per_qn, "end": n["e"] / slots_per_qn, "pitch": n["pitch"], "vel": n["vel"]}
            for n in res], stats
