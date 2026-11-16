"""REAPER project -> Guitar Pro 5, in one command.

usage: export_gp.py <project.rpp> <out.gp5> <track> [<track> ...] [--cache DIR] [--force] [--drum-map JSON]

Each <track> is a track name as shown in REAPER (case-insensitive, must be unique) or a 0-based
track index (as returned by the reaper MCP get_selected_tracks). Folder tracks are expanded to
their children. MIDI tracks are read from the .rpp; audio tracks are transcribed with basic-pitch
(results cached per track index in --cache, default <project dir>/gp_export_cache; delete a
<idx>.json there to force re-transcription).
"""
import argparse, os, sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import rpp, transcribe, build_gp


def resolve_tracks(trs, specs):
    """Track names or 0-based indices -> indices."""
    out = []
    for s in specs:
        if s.isdigit():
            i = int(s)
            if i >= len(trs):
                sys.exit(f"track index {i} out of range (project has {len(trs)} tracks)")
            out.append(i)
            continue
        hits = [t["index"] for t in trs if t["name"].strip().lower() == s.strip().lower()]
        if not hits:
            sys.exit(f"no track named {s!r}. Tracks: " + ", ".join(f'{t["index"]}={t["name"]!r}' for t in trs))
        if len(hits) > 1:
            sys.exit(f"several tracks are named {s!r} (indices {hits}); pass the index instead")
        out.append(hits[0])
    return out


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("project")
    ap.add_argument("out")
    ap.add_argument("tracks", nargs="+", help="track names or 0-based indices")
    ap.add_argument("--cache")
    ap.add_argument("--force", action="store_true", help="overwrite the output file")
    ap.add_argument("--drum-map", help="drum note map JSON (default gp_export/drum_maps/ezdrummer3.json)")
    a = ap.parse_args()

    if os.path.exists(a.out) and not a.force:
        sys.exit(f"{a.out} already exists (use --force to overwrite)")
    cache = a.cache or os.path.join(os.path.dirname(os.path.abspath(a.project)), "gp_export_cache")

    proj = rpp.parse(a.project)
    trs = rpp.tracks(proj)
    sel = resolve_tracks(trs, a.tracks)
    audio = []
    for t in build_gp.expand_selection(trs, sel):
        its = rpp.items(t["node"])
        if not any(i.get("src_type") == "MIDI" and not i["mute"] for i in its) and any(i.get("file") for i in its):
            audio.append(t["index"])
    if audio:
        print("transcribing audio tracks:", audio, flush=True)
        transcribe.run(a.project, cache, audio)
    build_gp.run(a.project, cache, a.out, sel, drum_map=a.drum_map)


if __name__ == "__main__":
    main()
