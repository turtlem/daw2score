"""Dump tempo/time-signature map, markers, folder tree and item summary of a .rpp. usage: inspect_rpp.py <project.rpp>"""
import os, sys, collections
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import rpp

proj = rpp.parse(sys.argv[1])
info = rpp.project_info(proj)
print("tempo", info["tempo"], "ts", info["ts_num"], "/", info["ts_den"])
print("tempo env points:", info["tempo_points"][:20], "count", len(info["tempo_points"]))
print("markers:", info["markers"])
print("track header lane keys:")
for t in rpp.tracks(proj):
    its = rpp.items(t["node"])
    lanes = collections.Counter(i["lane"] for i in its)
    types = collections.Counter(i.get("src_type") for i in its)
    lanekeys = [l for l in t["node"].lines if l and l[0].startswith("LANE") or (l and l[0] == "FIXEDLANES")]
    print(f'{t["index"]:2d} {"  "*t["depth"]}{t["name"]!r} folder={t["is_folder"]} items={len(its)} '
          f'types={dict(types)} lanes={dict(lanes)} muted_items={sum(i["mute"] for i in its)} {lanekeys}')
allkeys = collections.Counter()
for t in rpp.tracks(proj):
    for i in rpp.items(t["node"]):
        allkeys.update(i["keys"])
print("item keys:", dict(allkeys))
