"""Propose song sections (bar -> name) from per-bar features of the exported tracks.

Features per bar: each track's level (audio RMS in dB, MIDI note count) and the chroma of the audio
mix. Boundaries are the peaks of a checkerboard novelty curve over the bar self-similarity matrix;
segments are then labelled A, B, C... by similarity, so repeated parts get the same letter. Meant as
a starting point to edit (gui.py), not a final answer.

usage: sections.py <project> <track idx> [...] [--tempo BPM]
"""
import os, sys
import numpy as np

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import project, transcribe, build_gp

KERNEL = 4        # bars on each side of a candidate boundary
MIN_LEN = 4       # bars
SAME = 0.3        # cosine similarity (standardized features) above which two segments share a letter
PCT = 80          # novelty percentile a boundary must reach


def export_info(info, tempo=None):
    """The measure layout the export will use: a tempo override drops the project's tempo map
    (time-signature changes included), exactly as build_gp.run does."""
    info = dict(info)
    if tempo:
        info["tempo"], info["tempo_points"] = float(tempo), []
    return info


def bar_times(info, end_s):
    bpm = info["tempo"]
    ms = build_gp.build_measures(info, end_s * bpm / 60.0)
    return [m["qn"] * 60.0 / bpm for m in ms] + [(ms[-1]["qn"] + ms[-1]["len"]) * 60.0 / bpm]


def features(proj_path, idxs, tempo=None):
    import librosa
    P = project.load(proj_path)
    info = export_info(P.info, tempo)
    bpm = info["tempo"]
    trs = [t for t in build_gp.expand_selection(P.tracks, idxs)]
    end = max((i["position"] + i["length"] for t in trs for i in t["items"] if not i["mute"]), default=0)
    if end <= 0:
        raise SystemExit("nothing to analyse")
    edges = bar_times(info, end)
    nb = len(edges) - 1
    sr = transcribe.SR
    rows, mix = [], np.zeros(int((end + 1) * sr), np.float32)
    for t in trs:
        its = [i for i in t["items"] if not i["mute"]]
        if any(i.get("src_type") == "MIDI" for i in its):
            notes = build_gp.midi_notes(its, bpm)
            row = np.zeros(nb)
            for n in notes:
                b = np.searchsorted(edges, n["start"] * 60.0 / bpm, side="right") - 1
                if 0 <= b < nb:
                    row[b] += 1
            rows.append(np.log1p(row))
            continue
        buf, t0 = transcribe.render(None, its)
        if buf is None:
            continue
        o = int(round(t0 * sr))
        n = min(len(buf), len(mix) - o)
        mix[o:o + n] += buf[:n]
        row = np.zeros(nb)
        for b in range(nb):
            a, z = int(edges[b] * sr) - o, int(edges[b + 1] * sr) - o
            seg = buf[max(a, 0):max(z, 0)]
            row[b] = 10 * np.log10(np.mean(seg ** 2) + 1e-10) if len(seg) else -100
        rows.append(np.clip((row + 60) / 60, 0, 1))  # -60..0 dB -> 0..1
    hop = 512
    chroma = librosa.feature.chroma_cqt(y=mix, sr=sr, hop_length=hop) if mix.any() else np.zeros((12, 1))
    ct = librosa.frames_to_time(np.arange(chroma.shape[1]), sr=sr, hop_length=hop)
    cb = np.zeros((12, nb))
    for b in range(nb):
        sel = (ct >= edges[b]) & (ct < edges[b + 1])
        if sel.any():
            cb[:, b] = chroma[:, sel].mean(1)
    cb /= np.linalg.norm(cb, axis=0, keepdims=True) + 1e-9
    lv = np.array(rows) if rows else np.zeros((0, nb))
    return np.vstack([lv * 1.5, cb]), lv


def propose(proj_path, idxs, tempo=None):
    """-> {bar number (1-based): label}. tempo: the export's tempo override (None = project tempo map)."""
    F, lv = features(proj_path, idxs, tempo)
    nb = F.shape[1]
    active = lv.max(0) > 0.25 if len(lv) else np.ones(nb, bool)
    if not active.any():
        return {}
    first, last = int(np.argmax(active)), nb - 1 - int(np.argmax(active[::-1]))
    Z = F - F.mean(1, keepdims=True)
    Z /= np.linalg.norm(Z, axis=0, keepdims=True) + 1e-9
    S = Z.T @ Z
    K = KERNEL
    ker = np.kron(np.array([[-1, 1], [1, -1]]), np.ones((K, K)))
    ker *= np.outer(np.hanning(2 * K + 2)[1:-1], np.hanning(2 * K + 2)[1:-1])
    nov = np.zeros(nb)
    for i in range(K, nb - K + 1):
        nov[i] = -(S[i - K:i + K, i - K:i + K] * ker).sum()
    cands = [i for i in range(first + MIN_LEN, last - MIN_LEN + 2)
             if nov[i] >= nov[max(0, i - 2):i + 3].max() and nov[i] > 0]
    thr = np.percentile(nov[first:last + 1], PCT)
    bounds = [first]
    for i in sorted(cands, key=lambda i: -nov[i]):
        if nov[i] < thr:
            break
        if all(abs(i - b) >= MIN_LEN for b in bounds):
            bounds.append(i)
    bounds = sorted(bounds) + [last + 1]
    # label segments by similarity of their mean features
    Zs = (F - F.mean(1, keepdims=True)) / (F.std(1, keepdims=True) + 1e-9)  # each feature counts the same
    means = [Zs[:, a:z].mean(1) for a, z in zip(bounds, bounds[1:])]
    labels, protos = [], []
    for m in means:
        best, best_c = None, SAME
        for k, p in enumerate(protos):
            c = float(np.dot(m, p) / (np.linalg.norm(m) * np.linalg.norm(p) + 1e-9))
            if c > best_c:
                best, best_c = k, c
        if best is None:
            protos.append(m)
            best = len(protos) - 1
        labels.append(chr(ord("A") + best) if best < 26 else f"P{best + 1}")
    return {a + 1: lab for a, lab in zip(bounds, labels)}


def main():
    args = sys.argv[1:]
    bpm = None
    if "--tempo" in args:
        k = args.index("--tempo")
        bpm = float(args[k + 1])
        del args[k:k + 2]
    print(propose(args[0], [int(a) for a in args[1:]], bpm))


if __name__ == "__main__":
    main()
