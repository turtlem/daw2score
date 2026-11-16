"""REAPER project -> Guitar Pro 5, in one command.

usage: export_gp.py <project.rpp> <out.gp5> <track_index> [<track_index> ...] [--cache DIR] [--force]

Track indices are 0-based (as returned by the reaper MCP get_selected_tracks). Folder tracks are
expanded to their children. MIDI tracks are read from the .rpp; audio tracks are transcribed with
basic-pitch (results cached per track index in --cache, default <project dir>/gp_export_cache;
delete a <idx>.json there to force re-transcription).
"""
import argparse, os, sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import rpp, transcribe, build_gp


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("project")
    ap.add_argument("out")
    ap.add_argument("tracks", nargs="+", type=int)
    ap.add_argument("--cache")
    ap.add_argument("--force", action="store_true", help="overwrite the output file")
    ap.add_argument("--drum-map", help="drum note map JSON (default gp_export/drum_maps/ezdrummer3.json)")
    a = ap.parse_args()

    if os.path.exists(a.out) and not a.force:
        sys.exit(f"{a.out} already exists (use --force to overwrite)")
    cache = a.cache or os.path.join(os.path.dirname(os.path.abspath(a.project)), "gp_export_cache")

    proj = rpp.parse(a.project)
    audio = []
    for t in build_gp.expand_selection(rpp.tracks(proj), a.tracks):
        its = rpp.items(t["node"])
        if not any(i.get("src_type") == "MIDI" and not i["mute"] for i in its) and any(i.get("file") for i in its):
            audio.append(t["index"])
    if audio:
        print("transcribing audio tracks:", audio, flush=True)
        transcribe.run(a.project, cache, audio)
    build_gp.run(a.project, cache, a.out, a.tracks, drum_map=a.drum_map)


if __name__ == "__main__":
    main()
