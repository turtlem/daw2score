# PyInstaller spec for the daw2score window: one folder (Windows) or daw2score.app (macOS), no console.
# Built by packaging/build.py, which first prepares build/node/<node binary> (DAW2SCORE_NODE) and
# build/licenses, then wraps the result in an installer (.exe) or a disk image (.dmg).
import glob, os, sys
from PyInstaller.utils.hooks import collect_data_files, collect_submodules

ROOT = os.path.abspath(os.path.join(SPECPATH, ".."))
SRC = os.path.join(ROOT, "gp_export")
MAC = sys.platform == "darwin"
VERSION = os.environ["DAW2SCORE_VERSION"]

# every module of gp_export: many are imported lazily (tempo, sections, add_backing...)
own = [os.path.splitext(os.path.basename(p))[0] for p in glob.glob(os.path.join(SRC, "*.py"))]
own = [m for m in own if m != "gui"]

gp7 = os.path.join(SRC, "gp7")
datas = [
    (os.path.join(SRC, "drum_maps"), "drum_maps"),
    (os.path.join(SRC, "assets"), "assets"),
    (os.path.join(gp7, "gp5togp.mjs"), "gp7"),
    (os.path.join(gp7, "package.json"), "gp7"),
    (os.path.join(gp7, "node_modules"), os.path.join("gp7", "node_modules")),
    (os.path.join(ROOT, "build", "licenses"), "licenses"),
]
datas += collect_data_files("basic_pitch")  # ONNX model
datas += collect_data_files("librosa")      # lazy_loader .pyi stubs, example data index
datas += collect_data_files("resampy")      # filters
datas += collect_data_files("mir_eval")
binaries = [(os.environ["DAW2SCORE_NODE"], "gp7")]  # Node.js for alphaTab (exporter.to_gp7)

hidden = own + collect_submodules("basic_pitch", filter=lambda n: "train" not in n and "visualize" not in n)
hidden += ["sklearn.utils._typedefs", "scipy.special.cython_special"]

a = Analysis(
    [os.path.join(SRC, "gui.py")],
    pathex=[SRC],
    binaries=binaries,
    datas=datas,
    hiddenimports=hidden,
    excludes=["tensorflow", "tflite_runtime", "coremltools", "torch", "matplotlib", "IPython", "tkinter",
              "PyInstaller", "pytest"],
    noarchive=False,
)
pyz = PYZ(a.pure)
exe = EXE(
    pyz, a.scripts, [],
    exclude_binaries=True,
    name="daw2score",
    console=False,
    icon=os.path.join(SRC, "assets", "daw2score.icns" if MAC else "daw2score.ico"),
    version=None if MAC else os.path.join(ROOT, "build", "version_info.txt"),
)
coll = COLLECT(exe, a.binaries, a.datas, name="daw2score")
if MAC:
    app = BUNDLE(
        coll,
        name="daw2score.app",
        icon=os.path.join(SRC, "assets", "daw2score.icns"),
        bundle_identifier="io.github.turtlem.daw2score",
        version=VERSION,
        info_plist={
            "CFBundleName": "daw2score",
            "CFBundleDisplayName": "daw2score",
            "CFBundleShortVersionString": VERSION,
            "CFBundleVersion": VERSION,
            "NSHumanReadableCopyright": "MIT License, (c) turtlem",
            "NSHighResolutionCapable": True,
            "LSMinimumSystemVersion": "12.0",
            # projects can be dropped on the Dock icon / opened with the app
            "CFBundleDocumentTypes": [
                {"CFBundleTypeName": "REAPER project", "CFBundleTypeExtensions": ["rpp"], "CFBundleTypeRole": "Viewer",
                 "LSHandlerRank": "Alternate"},
                {"CFBundleTypeName": "DAWproject", "CFBundleTypeExtensions": ["dawproject"], "CFBundleTypeRole": "Viewer",
                 "LSHandlerRank": "Alternate"},
                {"CFBundleTypeName": "Folder", "LSItemContentTypes": ["public.folder"], "CFBundleTypeRole": "Viewer",
                 "LSHandlerRank": "None"},
            ],
        },
    )
