"""Dump tempo/time-signature map, markers, folder tree and items of a project.

usage: inspect_rpp.py <project.rpp | stems folder>
"""
import os, sys, collections
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import project

p = project.load(sys.argv[1])
info = p.info
print(f"{p.name}: tempo {info['tempo']:g}, ts {info['ts_num']}/{info['ts_den']}"
      + (f" (from {info['tempo_source']})" if info.get("tempo_source") else ""))
print("tempo/time-signature points:", info["tempo_points"][:20], "count", len(info["tempo_points"]))
print("markers:", info["markers"])
for t in p.tracks:
    its = t["items"]
    types = collections.Counter(i.get("src_type") for i in its)
    extra = ""
    if "node" in t:  # REAPER: lanes and lane keys help with comping / fixed lanes
        lanes = collections.Counter(i["lane"] for i in its)
        lanekeys = [l for l in t["node"].lines if l and (l[0].startswith("LANE") or l[0] == "FIXEDLANES")]
        extra = f" lanes={dict(lanes)} {lanekeys}"
    span = f" {min(i['position'] for i in its):.2f}-{max(i['position'] + i['length'] for i in its):.2f}s" if its else ""
    print(f'{t["index"]:2d} {"  " * t["depth"]}{t["name"]!r}{" [folder]" if t["is_folder"] else ""} '
          f'items={len(its)} types={dict(types)}{span} muted={sum(i["mute"] for i in its)}'
          f'{" drums" if t.get("drums") else ""}{extra}')
