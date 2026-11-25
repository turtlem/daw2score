"""Build the installer for the current platform:
    Windows -> dist/daw2score-<version>-setup.exe      (Inno Setup: winget install JRSoftware.InnoSetup)
    macOS   -> dist/daw2score-<version>-macos-<arm64|x86_64>.dmg

    uv sync --extra gui            (PyInstaller is in the dev group, installed by default)
    uv run python packaging/build.py [--skip-installer] [--skip-selftest]

Steps: check the version numbers agree, npm ci for alphaTab, a pinned Node.js (downloaded once into build/,
SHA-256 checked), the third-party license files, PyInstaller (packaging/daw2score.spec), the self-test on the
built app, then the installer / disk image. Macs are built on GitHub Actions (.github/workflows/build.yml).
"""
import hashlib, importlib.metadata as md, os, platform, re, shutil, subprocess, sys, tarfile, time, urllib.request, zipfile

ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
SRC = os.path.join(ROOT, "gp_export")
BUILD = os.path.join(ROOT, "build")
DIST = os.path.join(ROOT, "dist")
MAC = sys.platform == "darwin"
WIN = os.name == "nt"
NODE_VERSION = "24.20.0"
NODE_URL = f"https://nodejs.org/dist/v{NODE_VERSION}/"
GNU = ("LGPL-3.0.txt", "GPL-3.0.txt")  # kept in packaging/licenses (gnu.org downloads time out in CI)
DEV_ONLY = {"pyinstaller", "pyinstaller-hooks-contrib", "altgraph", "pefile", "pywin32-ctypes", "macholib"}


def arch():
    m = platform.machine().lower()
    return "arm64" if m in ("arm64", "aarch64") else "x86_64"


def version():
    sys.path.insert(0, SRC)
    from version import __version__
    py = re.search(r'^version = "(.+)"', open(os.path.join(ROOT, "pyproject.toml"), encoding="utf-8").read(), re.M)
    if not py or py.group(1) != __version__:
        sys.exit(f"pyproject.toml version {py and py.group(1)!r} != gp_export/version.py {__version__!r}")
    if not re.fullmatch(r"\d+\.\d+\.\d+", __version__):
        sys.exit(f"version {__version__!r} is not X.Y.Z")
    return __version__


def download(url, dst, tries=4):
    if not os.path.exists(dst):
        for k in range(tries):
            print("downloading", url, flush=True)
            try:
                req = urllib.request.Request(url, headers={"User-Agent": "daw2score-build"})
                with urllib.request.urlopen(req, timeout=120) as r, open(dst + ".part", "wb") as f:
                    shutil.copyfileobj(r, f)
                break
            except OSError as e:  # timeouts, resets: CI networks are flaky
                if k == tries - 1:
                    raise
                print(f"  failed ({e}), retrying", flush=True)
                time.sleep(10 * (k + 1))
        os.replace(dst + ".part", dst)
    return dst


def node():
    """-> (path of the node binary for this platform, its LICENSE bytes), from the official archive
    checked against SHASUMS256.txt."""
    d = os.path.join(BUILD, "node")
    os.makedirs(d, exist_ok=True)
    if WIN:
        name, exe = f"node-v{NODE_VERSION}-win-x64.zip", "node.exe"
    elif MAC:
        name, exe = f"node-v{NODE_VERSION}-darwin-{'arm64' if arch() == 'arm64' else 'x64'}.tar.gz", "node"
    else:
        sys.exit("only Windows and macOS builds are supported")
    a = download(NODE_URL + name, os.path.join(d, name))
    sums = download(NODE_URL + "SHASUMS256.txt", os.path.join(d, f"SHASUMS256-{NODE_VERSION}.txt"))
    want = next(l.split()[0] for l in open(sums) if l.strip().endswith(" " + name))
    got = hashlib.sha256(open(a, "rb").read()).hexdigest()
    if got != want:
        os.remove(a)
        sys.exit(f"{name}: bad SHA-256 {got}, expected {want}")
    top = name.replace(".zip", "").replace(".tar.gz", "") + "/"
    if WIN:
        with zipfile.ZipFile(a) as zf:
            binary, lic = zf.read(top + exe), zf.read(top + "LICENSE")
    else:
        with tarfile.open(a) as tf:
            binary, lic = tf.extractfile(top + "bin/node").read(), tf.extractfile(top + "LICENSE").read()
    out = os.path.join(d, arch(), exe)
    os.makedirs(os.path.dirname(out), exist_ok=True)
    open(out, "wb").write(binary)
    os.chmod(out, 0o755)
    return out, lic


def version_info(v):
    t = tuple(int(x) for x in v.split(".")) + (0,)
    s = f"""VSVersionInfo(
  ffi=FixedFileInfo(filevers={t}, prodvers={t}, mask=0x3f, flags=0x0, OS=0x40004, fileType=0x1, subtype=0x0, date=(0, 0)),
  kids=[StringFileInfo([StringTable('040904B0', [
    StringStruct('CompanyName', 'daw2score'),
    StringStruct('FileDescription', 'daw2score - DAW projects to Guitar Pro / MusicXML'),
    StringStruct('FileVersion', '{v}'),
    StringStruct('InternalName', 'daw2score'),
    StringStruct('LegalCopyright', 'MIT License, (c) turtlem'),
    StringStruct('OriginalFilename', 'daw2score.exe'),
    StringStruct('ProductName', 'daw2score'),
    StringStruct('ProductVersion', '{v}')])]),
  VarFileInfo([VarStruct('Translation', [1033, 1200])])]
)
"""
    open(os.path.join(BUILD, "version_info.txt"), "w", encoding="utf-8").write(s)


def licenses(node_license):
    """build/licenses: bundled into the app (gui.notices_path)."""
    out = os.path.join(BUILD, "licenses")
    shutil.rmtree(out, ignore_errors=True)
    os.makedirs(out)
    shutil.copy(os.path.join(ROOT, "LICENSE"), os.path.join(out, "daw2score-LICENSE.txt"))
    shutil.copy(os.path.join(ROOT, "THIRD_PARTY_NOTICES.md"), out)
    for dist in md.distributions():
        name = dist.metadata["Name"]
        if name.lower() in DEV_ONLY:
            continue
        files = [f for f in (dist.files or []) if re.search(r"LICEN[CS]E|COPYING|NOTICE", f.name, re.I)
                 and not f.name.endswith((".py", ".pyc"))]
        dst = os.path.join(out, f"{name}-{dist.version}")
        os.makedirs(dst, exist_ok=True)
        with open(os.path.join(dst, "METADATA.txt"), "w", encoding="utf-8") as f:
            f.write(f"{name} {dist.version}\nLicense: {dist.metadata.get('License-Expression') or dist.metadata.get('License') or '?'}\n"
                    f"Home: {dist.metadata.get('Home-page') or ''}\n")
        for k, fp in enumerate(files):
            src = dist.locate_file(fp)
            if os.path.isfile(src):
                shutil.copy(src, os.path.join(dst, f"{k}-{fp.name}"))
    for fn in GNU:  # Qt / PySide6 (LGPL-3.0), PyGuitarPro (LGPL-3.0)
        shutil.copy(os.path.join(ROOT, "packaging", "licenses", fn), os.path.join(out, fn))
    at = os.path.join(SRC, "gp7", "node_modules", "@coderline", "alphatab")
    os.makedirs(os.path.join(out, "alphaTab"), exist_ok=True)
    for fn in os.listdir(at):
        if re.search(r"LICEN[CS]E|NOTICE", fn, re.I):
            shutil.copy(os.path.join(at, fn), os.path.join(out, "alphaTab", fn))
    os.makedirs(os.path.join(out, "Node.js"), exist_ok=True)
    open(os.path.join(out, "Node.js", "LICENSE"), "wb").write(node_license)


def selftest(exe):
    report = os.path.join(BUILD, "selftest.txt")
    if os.path.exists(report):
        os.remove(report)
    r = subprocess.run([exe, "--selftest", report], timeout=1200)
    print(open(report, encoding="utf-8").read() if os.path.exists(report) else "(no self-test report)", flush=True)
    if r.returncode:
        sys.exit("self-test failed: no installer built")


def windows_installer(v, app):
    iscc = shutil.which("iscc") or next((p for p in (
        os.path.expandvars(r"%LOCALAPPDATA%\Programs\Inno Setup 6\ISCC.exe"),
        r"C:\Program Files (x86)\Inno Setup 6\ISCC.exe", r"C:\Program Files\Inno Setup 6\ISCC.exe")
        if os.path.exists(p)), None)
    if not iscc:
        sys.exit("Inno Setup not found: winget install JRSoftware.InnoSetup")
    subprocess.run([iscc, f"/DAppVersion={v}", f"/DSourceDir={app}", f"/DOutputDir={DIST}",
                    os.path.join(ROOT, "packaging", "daw2score.iss")], check=True)
    return os.path.join(DIST, f"daw2score-{v}-setup.exe")


MAC_README = """daw2score {v}

1. Drag daw2score.app onto the Applications folder.
2. First launch: the app is not notarized by Apple yet. Open it once, then go to
   System Settings > Privacy & Security and click "Open Anyway" (macOS 15+),
   or right-click the app > Open (macOS 14 and earlier).
3. REAPER action (optional): in REAPER, Actions > Show action list > New action >
   Load ReaScript..., pick "daw2score_export.lua" from this disk image (copy it to
   REAPER's Scripts folder first if you like). It opens the window on the current project.

Log: ~/Library/Application Support/daw2score/daw2score.log
https://github.com/turtlem/daw2score
"""


def mac_dmg(v, app):
    stage = os.path.join(BUILD, "dmg")
    shutil.rmtree(stage, ignore_errors=True)
    os.makedirs(stage)
    subprocess.run(["ditto", app, os.path.join(stage, "daw2score.app")], check=True)  # keeps symlinks/signature
    os.symlink("/Applications", os.path.join(stage, "Applications"))
    shutil.copy(os.path.join(ROOT, "packaging", "daw2score_export.lua"), stage)
    open(os.path.join(stage, "Read me.txt"), "w").write(MAC_README.format(v=v))
    dmg = os.path.join(DIST, f"daw2score-{v}-macos-{arch()}.dmg")
    if os.path.exists(dmg):
        os.remove(dmg)
    subprocess.run(["hdiutil", "create", "-volname", f"daw2score {v}", "-srcfolder", stage, "-ov",
                    "-format", "UDZO", dmg], check=True)
    return dmg


def main():
    args = sys.argv[1:]
    v = version()
    print(f"== daw2score {v} ({sys.platform}, {arch()})", flush=True)
    os.makedirs(BUILD, exist_ok=True)
    gp7 = os.path.join(SRC, "gp7")
    if not os.path.isdir(os.path.join(gp7, "node_modules", "@coderline", "alphatab")):
        subprocess.run([shutil.which("npm") or "npm", "ci", "--no-audit", "--no-fund"], cwd=gp7, check=True)
    node_bin, node_license = node()
    licenses(node_license)
    if WIN:
        version_info(v)
    env = dict(os.environ, DAW2SCORE_NODE=node_bin, DAW2SCORE_VERSION=v)
    for old in ("daw2score", "daw2score.app"):
        shutil.rmtree(os.path.join(DIST, old), ignore_errors=True)
    subprocess.run([sys.executable, "-m", "PyInstaller", "--noconfirm", "--clean", "--distpath", DIST,
                    "--workpath", os.path.join(BUILD, "pyinstaller"), os.path.join(ROOT, "packaging", "daw2score.spec")],
                   check=True, env=env)
    if MAC:
        app = os.path.join(DIST, "daw2score.app")
        exe = os.path.join(app, "Contents", "MacOS", "daw2score")
    else:
        app = os.path.join(DIST, "daw2score")
        exe = os.path.join(app, "daw2score.exe")
        os.makedirs(os.path.join(app, "reaper"), exist_ok=True)
        shutil.copy(os.path.join(ROOT, "packaging", "daw2score_export.lua"), os.path.join(app, "reaper"))
    size = sum(os.path.getsize(os.path.join(r, f)) for r, _, fs in os.walk(app) for f in fs
               if not os.path.islink(os.path.join(r, f)))
    print(f"app: {app} ({size / 1e6:.0f} MB)", flush=True)
    if "--skip-selftest" not in args:
        selftest(exe)
    if "--skip-installer" not in args:
        out = mac_dmg(v, app) if MAC else windows_installer(v, app)
        print(f"installer: {out} ({os.path.getsize(out) / 1e6:.0f} MB)", flush=True)


if __name__ == "__main__":
    main()
