"""Minimal REAPER .rpp parser: tracks (with folder depth), items, MIDI events, audio sources."""
import re, shlex


def tokens(line):
    try:
        return shlex.split(line, posix=True)
    except ValueError:
        return line.split()


class Node:
    def __init__(self, tag, args):
        self.tag, self.args, self.lines, self.children = tag, args, [], []

    def get(self, key):
        for l in self.lines:
            if l and l[0] == key:
                return l[1:]
        return None

    def all(self, key):
        return [l[1:] for l in self.lines if l and l[0] == key]

    def find(self, tag):
        return [c for c in self.children if c.tag == tag]


def parse(path):
    root = Node("ROOT", [])
    stack = [root]
    with open(path, encoding="utf-8", errors="replace") as f:
        for raw in f:
            s = raw.strip()
            if not s:
                continue
            if s.startswith("<"):
                t = tokens(s[1:])
                n = Node(t[0] if t else "", t[1:])
                stack[-1].children.append(n)
                stack[-1].lines.append(["<CHILD>", n])  # keeps ordering for multi-take items
                stack.append(n)
            elif s == ">":
                stack.pop()
            else:
                # MIDI event lines and base64 blobs: keep raw split (fast)
                if s[0] in "Ee" and len(s) > 1 and s[1] == " ":
                    stack[-1].lines.append(s.split())
                else:
                    stack[-1].lines.append(tokens(s))
    return root.children[0]  # REAPER_PROJECT


def project_info(proj):
    tempo = proj.get("TEMPO")
    info = {"tempo": float(tempo[0]), "ts_num": int(tempo[1]), "ts_den": int(tempo[2])}
    env = proj.find("TEMPOENVEX")
    info["tempo_points"] = [l[1:] for l in env[0].lines if l and l[0] == "PT"] if env else []
    info["markers"] = [(float(m[1]), m[2]) for m in proj.all("MARKER")]
    return info


def tracks(proj):
    out, depth = [], 0
    for i, t in enumerate(proj.find("TRACK")):
        isbus = t.get("ISBUS") or ["0", "0"]
        out.append({"index": i, "name": (t.get("NAME") or [""])[0], "depth": depth,
                    "is_folder": isbus[0] == "1", "node": t})
        depth += int(isbus[1]) if isbus[0] in ("1", "2") else 0
    return out


def _split_takes(it):
    """Return list of takes: dict(lines=[...], source=Node|None, sel=bool). Take 0 = lines before first TAKE."""
    takes = [{"lines": [], "source": None, "sel": False}]
    for l in it.lines:
        if not l:
            continue
        if l[0] == "TAKE":
            takes.append({"lines": [], "source": None, "sel": "SEL" in l[1:]})
        elif l[0] == "<CHILD>":
            if l[1].tag == "SOURCE" and takes[-1]["source"] is None:
                takes[-1]["source"] = l[1]
        else:
            takes[-1]["lines"].append(l)
    return takes


def _get(lines, key):
    for l in lines:
        if l[0] == key:
            return l[1:]
    return None


def items(track_node):
    res = []
    for it in track_node.find("ITEM"):
        takes = _split_takes(it)
        active = next((t for t in takes[1:] if t["sel"]), takes[0])
        tl = active["lines"]
        d = {"position": float(it.get("POSITION")[0]), "length": float(it.get("LENGTH")[0]),
             "mute": (it.get("MUTE") or ["0"])[0] == "1",
             "loop": (it.get("LOOP") or ["0"])[0] == "1",
             "soffs": float((_get(tl, "SOFFS") or ["0"])[0]),
             "playrate": float((_get(tl, "PLAYRATE") or ["1"])[0]),
             "lane": int(it.get("I_FIXEDLANE")[0]) if it.get("I_FIXEDLANE") else None,
             "n_takes": len(takes),
             "keys": sorted({l[0] for l in it.lines if l and isinstance(l[0], str)}),
             "name": (_get(tl, "NAME") or [""])[0]}
        src = [active["source"]] if active["source"] is not None else []
        if src:
            s = src[0]
            # section / nested sources
            while s.find("SOURCE") and s.args and s.args[0] == "SECTION":
                s = s.find("SOURCE")[0]
            d["src_type"] = s.args[0] if s.args else "?"
            if d["src_type"] == "MIDI":
                hd = s.get("HASDATA")
                d["ppq"] = int(hd[1]) if hd else 960
                d["events"] = [l for l in s.lines if l and l[0] in ("E", "e")]
            else:
                f = s.get("FILE")
                d["file"] = f[0] if f else None
        res.append(d)
    return res
