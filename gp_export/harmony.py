"""Chord detection from audio and chord-track writing (strummed voicings + chord names).

Chords: beat-synchronous chroma of the harmony tracks (guitars weighted by loudness) plus the bass
chroma for the root, matched against maj / m / 5 / sus2 / sus4 templates and smoothed with a Viterbi
pass. Rhythm: onsets of the chord track's own audio on the 16th grid; where that track is silent or
too quiet the chord is held for its whole duration, so every bar with harmony gets a chord.
Voicings: open shapes when they exist, else E- or A-shape barre chords (standard tuning).
"""
import os, sys
import numpy as np
import librosa

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import project, transcribe

SR = transcribe.SR
HOP = 512
NOTES = ["C", "C#", "D", "Eb", "E", "F", "F#", "G", "Ab", "A", "Bb", "B"]
QUAL = {"": [0, 4, 7], "m": [0, 3, 7], "5": [0, 7], "sus2": [0, 2, 7], "sus4": [0, 5, 7]}
QUAL_BIAS = {"": 0.0, "m": 0.0, "5": -0.02, "sus2": -0.04, "sus4": -0.04}

# frets low E -> high e, -1 = not played
OPEN = {
    "C": [-1, 3, 2, 0, 1, 0], "D": [-1, -1, 0, 2, 3, 2], "Dm": [-1, -1, 0, 2, 3, 1],
    "Dsus2": [-1, -1, 0, 2, 3, 0], "Dsus4": [-1, -1, 0, 2, 3, 3], "E": [0, 2, 2, 1, 0, 0],
    "Em": [0, 2, 2, 0, 0, 0], "Esus4": [0, 2, 2, 2, 0, 0], "E5": [0, 2, 2, -1, -1, -1],
    "G": [3, 2, 0, 0, 0, 3], "Gsus2": [3, 0, 0, 2, 3, 3], "A": [-1, 0, 2, 2, 2, 0],
    "Am": [-1, 0, 2, 2, 1, 0], "Asus2": [-1, 0, 2, 2, 0, 0], "Asus4": [-1, 0, 2, 2, 3, 0],
    "A5": [-1, 0, 2, 2, -1, -1], "Csus2": [-1, 3, 0, 0, 1, 3],
}
E_SHAPE = {"": [0, 2, 2, 1, 0, 0], "m": [0, 2, 2, 0, 0, 0], "5": [0, 2, 2, -1, -1, -1],
           "sus4": [0, 2, 2, 2, 0, 0], "sus2": [0, 2, 4, 4, 0, 0]}
A_SHAPE = {"": [-1, 0, 2, 2, 2, 0], "m": [-1, 0, 2, 2, 1, 0], "5": [-1, 0, 2, 2, -1, -1],
           "sus2": [-1, 0, 2, 2, 0, 0], "sus4": [-1, 0, 2, 2, 3, 0]}
STD = [40, 45, 50, 55, 59, 64]


def voicing(name):
    """Chord name -> frets low E -> high e (standard tuning)."""
    if name in OPEN:
        return OPEN[name]
    root = next(r for r in sorted(NOTES, key=len, reverse=True) if name.startswith(r))
    q = name[len(root):]
    pc = NOTES.index(root)
    fe, fa = (pc - 4) % 12, (pc - 9) % 12          # root fret on the E and A strings
    fe, fa = fe or 12, fa or 12
    base, shape = (fe, E_SHAPE[q]) if fe <= fa else (fa, A_SHAPE[q])
    return [-1 if s < 0 else s + base for s in shape]


def _audio(proj_path, trs, idxs, length):
    pdir = None
    out = np.zeros(length, np.float32)
    for i in idxs:
        buf, t0 = transcribe.render(pdir, trs[i]["items"])
        if buf is None:
            continue
        o = int(round(t0 * SR))
        n = min(len(buf), length - o)
        out[o:o + n] += buf[:n]
    return out


def detect(proj_path, harmony_idxs, bass_idxs, bpm, chord_idxs=()):
    """Returns (labels per beat ('N' = no chord), seconds per beat). Each harmony track is normalized
    and weighted by its loudness per beat; the chord track itself counts 1.5x."""
    trs = project.load(proj_path).tracks
    ends = [i["position"] + i["length"] for k in list(harmony_idxs) + list(bass_idxs) for i in trs[k]["items"]]
    length = int((max(ends) + 1) * SR)
    spb = 60.0 / bpm
    nb = int(max(ends) / spb)
    bt = librosa.time_to_frames(np.arange(nb + 1) * spb, sr=SR, hop_length=HOP)

    def bchroma(x, **kw):
        c = librosa.feature.chroma_cqt(y=x, sr=SR, hop_length=HOP, **kw)
        r = librosa.feature.rms(y=x, hop_length=HOP)
        c = librosa.util.sync(c, bt, aggregate=np.mean)[:, :nb]
        r = librosa.util.sync(r, bt)[0, :nb]
        c = c / (c.max(axis=0, keepdims=True) + 1e-9)
        return c * (r / (np.percentile(r, 90) + 1e-9)).clip(0, 1)[None], r

    G = np.zeros((12, nb))
    for i in harmony_idxs:
        c, _ = bchroma(_audio(proj_path, trs, [i], length))
        G += c * (1.5 if i in chord_idxs else 1.0)
    B = np.zeros((12, nb)); bass_on = np.zeros(nb)
    if bass_idxs:
        B, rb = bchroma(_audio(proj_path, trs, bass_idxs, length), fmin=librosa.note_to_hz("E1"), n_octaves=3)
        bass_on = (rb / (np.percentile(rb, 90) + 1e-9)).clip(0, 1)
        B = B / (B.max(axis=0, keepdims=True) + 1e-9)
    labels, S = [], []
    Gn = G / (np.linalg.norm(G, axis=0, keepdims=True) + 1e-9)
    for r in range(12):
        for q, iv in QUAL.items():
            t = np.zeros(12); t[[(r + i) % 12 for i in iv]] = 1
            labels.append(NOTES[r] + q)
            S.append((t / np.linalg.norm(t)) @ Gn + 0.35 * B[r] * bass_on + QUAL_BIAS[q])
    S = np.array(S)
    P = np.exp(S * 12); P /= P.sum(axis=0, keepdims=True)
    path = librosa.sequence.viterbi(P, librosa.sequence.transition_loop(len(labels), 0.93))
    energy = G.sum(axis=0)
    return [labels[p] if energy[k] > 0.3 else "N" for k, p in enumerate(path)], spb


def strums(proj_path, idxs, bpm, slots_per_qn, thr=0.15):
    """Onset slots (16th grid) and strengths (0-1) of the chord track's audio."""
    import drums_audio as D
    trs = project.load(proj_path).tracks
    ends = [i["position"] + i["length"] for k in idxs for i in trs[k]["items"]]
    x = _audio(proj_path, trs, idxs, int((max(ends) + 1) * SR))
    env = D.envelope(x)
    fr = D.onsets(x, delta=0.04)
    pk = D.peaks_at(env, fr)
    norm = pk / (np.percentile(pk, 95) + 1e-9)
    slot_s = 60.0 / bpm / slots_per_qn
    out = {}
    for f, a in zip(fr, norm):
        if a >= thr:
            s = int(round(f * D.HOP / D.SR / slot_s))
            out[s] = max(out.get(s, 0), float(min(a, 1.0)))
    return out


def chord_events(labels, spb_slots, onsets, min_beats=2):
    """Per-beat labels + onset slots -> [{s, e, name, frets, vel, first}] on the slot grid.
    Chords shorter than min_beats are merged into the previous one. A strum lasts until the next strum
    or chord change; a chord segment without any strum is held whole."""
    segs = []  # [label, beat0, beat1]
    for k, l in enumerate(labels):
        if segs and segs[-1][0] == l:
            segs[-1][2] = k + 1
        else:
            segs.append([l, k, k + 1])
    merged = []
    for s in segs:
        if merged and (s[2] - s[1] < min_beats or s[0] == merged[-1][0]):
            merged[-1][2] = s[2]
        else:
            merged.append(s)
    ev = []
    for name, b0, b1 in merged:
        if name == "N":
            continue
        s0, s1 = b0 * spb_slots, b1 * spb_slots
        hits = sorted(s for s in onsets if s0 <= s < s1)
        if not hits or hits[0] - s0 >= spb_slots:   # chord starts without its own strum: add one
            hits = [s0] + hits
        frets = voicing(name)
        for j, s in enumerate(hits):
            e = hits[j + 1] if j + 1 < len(hits) else s1
            vel = int(50 + 70 * onsets.get(s, 0.5))
            ev.append({"s": s, "e": e, "name": name, "frets": frets, "vel": vel, "first": j == 0})
    return ev
