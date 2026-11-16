"""Clean a transcribed bass track inside a Guitar Pro 7/8 .gp file, using the REAPER project as reference.

usage: clean_bass.py <score.gp> <project.rpp> [--track Bass] [--rpp-bass Bass] [--rpp-drums Drums]
                     [--cache DIR] [--out OUT.gp]

1. Octave errors: for each note, checks the bass audio (rebuilt from the .rpp) for energy at the odd
   harmonics (f0, 3f0) of the octave below. basic-pitch often reports the 2nd harmonic; if the lower
   octave is really sounding, the note is moved down (up to twice, never below the lowest string).
2. Fragments: contiguous notes of the same pitch are merged unless the second one falls on a kick
   (re-attack) or is louder than the first.
3. Parasites: 16th notes off the kick with low basic-pitch amplitude are removed (the previous note
   is extended over them when contiguous).
4. Re-fretting for the track's tuning, preferring open/low positions and avoiding the low B string.

Without --out, the input file is overwritten after a backup <name>.before-bass-cleanup.gp is written.
"""
import argparse, json, os, shutil, sys
import numpy as np

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import gpif, rpp, transcribe, build_gp

OCT_RATIO = 0.5       # odd(low)/even energy above which the lower octave is considered real
PARASITE_AMP = 0.45   # basic-pitch amplitude (~ lower quartile on a test song) below which a lone 16th is noise


def hz(p):
    return 440.0 * 2 ** ((p - 69) / 12)


class Spectra:
    def __init__(self, buf, t0, sec_per_slot):
        self.buf, self.t0, self.sps = buf, t0, sec_per_slot

    def ratio(self, n, pitch):
        sr = transcribe.SR
        a = int((n["s"] * self.sps - self.t0) * sr) + int(0.02 * sr)
        b = max(int((n["e"] * self.sps - self.t0) * sr), a + int(0.08 * sr))
        seg = self.buf[max(a, 0):b]
        if len(seg) < 256:
            return 0.0
        spec = np.abs(np.fft.rfft(seg * np.hanning(len(seg)), 1 << 16))
        df = sr / (1 << 16)

        def e(f):
            lo, hi = int(f * 0.97 / df), int(f * 1.03 / df) + 1
            return float(spec[lo:hi].max()) if hi < len(spec) else 0.0
        fl, fh = hz(pitch - 12), hz(pitch)
        return (e(fl) + e(3 * fl)) / (e(fh) + e(2 * fh) + 1e-9)


def fret_bass(notes, tuning):
    """tuning: GPIF order (index 0 = lowest string). Sets n['string'], n['fret']."""
    pos, low_b = 3.0, len(tuning) >= 5
    for n in notes:
        best = None
        for s, open_p in enumerate(tuning):
            f = n["pitch"] - open_p
            if not 0 <= f <= 24:
                continue
            cost = abs(f - pos) * 0.5 + f * 0.1 - (0.5 if f == 0 else 0)
            if low_b and s == 0 and n["pitch"] >= tuning[1]:
                cost += 3  # only use the low B string when needed
            if best is None or cost < best[0]:
                best = (cost, s, f)
        if best is None:  # out of range: fold into range
            p = n["pitch"]
            while p < tuning[0]:
                p += 12
            while p > tuning[-1] + 24:
                p -= 12
            n["pitch"] = p
            return fret_bass(notes, tuning)
        _, n["string"], n["fret"] = best
        if n["fret"] > 0:
            pos = 0.7 * pos + 0.3 * n["fret"]


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("score")
    ap.add_argument("project")
    ap.add_argument("--track", default="Bass", help="track name in the .gp")
    ap.add_argument("--rpp-bass", default="Bass", help="bass track name in the .rpp")
    ap.add_argument("--rpp-drums", default="Drums", help="drum MIDI track name in the .rpp")
    ap.add_argument("--cache", help="transcription cache (default <project dir>/gp_export_cache)")
    ap.add_argument("--out")
    a = ap.parse_args()

    sc = gpif.Score(a.score)
    ti = sc.track_index(a.track)
    tuning = sc.tuning(ti)
    notes, warn = sc.read_track(ti)
    if warn:
        print("read warnings:", *warn[:10], sep="\n  ")
    n_in = len(notes)

    proj = rpp.parse(a.project)
    info = rpp.project_info(proj)
    bpm = info["tempo"]
    sps = 60.0 / bpm / build_gp.SLOTS_PER_QN
    trs = {t["name"]: t for t in rpp.tracks(proj)}
    bass_t, drum_t = trs[a.rpp_bass], trs[a.rpp_drums]
    kick = {round(n["start"] * build_gp.SLOTS_PER_QN)
            for n in build_gp.midi_notes(rpp.items(drum_t["node"]), bpm) if n["pitch"] in (35, 36)}
    cache = a.cache or os.path.join(os.path.dirname(os.path.abspath(a.project)), "gp_export_cache")
    amp = {}
    jp = os.path.join(cache, f'{bass_t["index"]}.json')
    if os.path.exists(jp):
        for t in json.load(open(jp, encoding="utf-8"))["notes"]:
            k = (round(t["start"] / sps), t["pitch"])
            amp[k] = max(amp.get(k, 0.0), t["amp"])
    else:
        print(f"no amplitude cache at {jp}: parasite removal disabled")
    for n in notes:
        n["amp"] = amp.get((n["s"], n["pitch"]))

    # 1. octave
    buf, t0 = transcribe.render(os.path.dirname(os.path.abspath(a.project)), rpp.items(bass_t["node"]))
    spectra = Spectra(buf, t0, sps)
    moved = 0
    for n in notes:
        for _ in range(2):
            if n["pitch"] - 12 >= tuning[0] and spectra.ratio(n, n["pitch"]) > OCT_RATIO:
                n["pitch"] -= 12
                moved += 1
            else:
                break

    def merge(ns):
        out, c = [], 0
        for n in ns:
            p = out[-1] if out else None
            if (p and p["e"] == n["s"] and p["pitch"] == n["pitch"] and n["s"] not in kick
                    and (n["amp"] is None or p["amp"] is None or n["amp"] <= p["amp"])):
                p["e"] = n["e"]; c += 1
            else:
                out.append(n)
        return out, c

    # 2. fragments
    notes, merged = merge(notes)
    # 3. parasites
    kept, removed = [], 0
    for n in notes:
        if (n["e"] - n["s"] == 1 and n["s"] not in kick and n["amp"] is not None and n["amp"] < PARASITE_AMP):
            removed += 1
            if kept and kept[-1]["e"] == n["s"]:
                kept[-1]["e"] = n["e"]
            continue
        kept.append(n)
    notes, merged2 = merge(kept)
    # 4. frets
    fret_bass(notes, tuning)

    out = a.out or a.score
    if not a.out:
        base, ext = os.path.splitext(a.score)
        backup = base + ".before-bass-cleanup" + ext
        if os.path.exists(backup):
            sys.exit(f"backup {backup} already exists; move it away or pass --out")
        shutil.copy2(a.score, backup)
        print("backup:", backup)
    sc.rewrite_track(ti, notes)
    sc.save(out)

    chk = gpif.Score(out)
    back, w2 = chk.read_track(chk.track_index(a.track))
    print(f"{n_in} notes -> {len(notes)} | octave fixes {moved} | merged {merged + merged2} | parasites removed {removed}")
    print("verify:", "OK" if not w2 and len(back) == len(notes) else f"MISMATCH {len(back)} notes, {w2[:5]}")
    print("written:", out)


if __name__ == "__main__":
    main()
