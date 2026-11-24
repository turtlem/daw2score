"""End-to-end check of an installation: builds a tiny stems folder (MIDI drums + a synthetic bass
recording) and exports it to .gp and .musicxml, which exercises basic-pitch, librosa, alphaTab and Node.

    daw2score.exe --selftest REPORT.txt        (installed build; the exit code is 0 when everything works)
    uv run python gp_export/selftest.py
"""
import os, sys, tempfile, time, traceback

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

MODULES = ("project", "exporter", "transcribe", "build_gp", "musicxml", "sections", "tempo", "harmony",
           "drums_audio", "add_backing", "clean_bass", "bass_fix", "gpif", "dawproject")


def make_stems(d, bpm=120):
    import numpy as np, soundfile as sf, mido
    mid = mido.MidiFile(ticks_per_beat=480)
    tr = mido.MidiTrack()
    mid.tracks.append(tr)
    tr += [mido.MetaMessage("track_name", name="Drums"), mido.MetaMessage("set_tempo", tempo=mido.bpm2tempo(bpm)),
           mido.MetaMessage("time_signature", numerator=4, denominator=4)]
    for beat in range(16):  # 4 bars: kick on 1/3, snare on 2/4, hats on 8ths
        tr.append(mido.Message("note_on", channel=9, note=36 if beat % 2 == 0 else 38, velocity=100, time=0))
        tr.append(mido.Message("note_on", channel=9, note=42, velocity=80, time=0))
        tr.append(mido.Message("note_off", channel=9, note=36 if beat % 2 == 0 else 38, velocity=0, time=240))
        tr.append(mido.Message("note_off", channel=9, note=42, velocity=0, time=0))
        tr.append(mido.Message("note_on", channel=9, note=42, velocity=70, time=0))
        tr.append(mido.Message("note_off", channel=9, note=42, velocity=0, time=240))
    mid.save(os.path.join(d, "Drums.mid"))
    sr, spb = 44100, 60.0 / bpm
    out = np.zeros(int(sr * spb * 16) + sr, np.float32)
    for k, f in enumerate([55.0, 55.0, 73.42, 82.41] * 4):  # A1 A1 D2 E2, one note per beat
        t = np.arange(int(sr * spb * 0.9)) / sr
        note = sum(np.sin(2 * np.pi * f * h * t) / h for h in (1, 2, 3)) * np.exp(-3 * t)
        a = int(k * spb * sr)
        out[a:a + len(note)] += 0.3 * note.astype(np.float32)
    sf.write(os.path.join(d, "Bass.wav"), out, sr)


def run(report=None):
    lines, ok = [], True

    def say(s):
        lines.append(s)
        print(s, flush=True)
    from version import __version__
    say(f"daw2score {__version__} self-test, python {sys.version.split()[0]}, frozen={getattr(sys, 'frozen', False)}")
    for m in MODULES:
        try:
            __import__(m)
            say(f"ok   import {m}")
        except Exception:  # noqa: BLE001
            ok = False
            say(f"FAIL import {m}\n{traceback.format_exc()}")
    if ok:
        try:
            import exporter, project
            with tempfile.TemporaryDirectory() as d:
                stems = os.path.join(d, "Song")
                os.makedirs(stems)
                make_stems(stems)
                P = project.load(stems)
                idx = {t["name"]: t["index"] for t in P.tracks}
                outs = [os.path.join(d, "Song.gp"), os.path.join(d, "Song.musicxml")]
                t0 = time.time()
                exporter.export(stems, outs, groups=[("Drums", [idx["Drums"]]), ("Bass", [idx["Bass"]])],
                                roles={idx["Bass"]: "bass"}, backing=[idx["Bass"]])  # + MP3 audio track
                for o in outs:
                    if not os.path.getsize(o):
                        raise RuntimeError(f"{o} is empty")
                say(f"ok   export .gp (with audio track) + .musicxml ({time.time() - t0:.1f}s)")
        except BaseException:  # noqa: BLE001 - SystemExit included
            ok = False
            say(f"FAIL export\n{traceback.format_exc()}")
    say("SELFTEST OK" if ok else "SELFTEST FAILED")
    if report:
        with open(report, "w", encoding="utf-8") as f:
            f.write("\n".join(lines) + "\n")
    return ok


if __name__ == "__main__":
    sys.exit(0 if run(sys.argv[1] if len(sys.argv) > 1 else None) else 1)
