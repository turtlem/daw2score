"""daw2score window: pick a project (REAPER .rpp, .dawproject or stems folder), choose tracks and roles,
tempo, sections and output formats, then export (same code as export_gp.py, through exporter.py).

    uv sync --extra gui
    uv run python gp_export/gui.py [project]

Settings are remembered per project in <project dir>/gp_export_cache/gui_<project name>.json.
"""
import contextlib, datetime, glob, json, os, sys, traceback

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from PySide6.QtCore import Qt, QThread, Signal, QObject, QSettings, QUrl
from PySide6.QtCore import QEvent
from PySide6.QtGui import QFont, QIcon, QFontDatabase
from PySide6.QtWidgets import (
    QApplication, QMainWindow, QWidget, QVBoxLayout, QHBoxLayout, QFormLayout, QGridLayout, QLabel,
    QPushButton, QLineEdit, QTreeWidget, QTreeWidgetItem, QComboBox, QTabWidget, QGroupBox, QRadioButton,
    QDoubleSpinBox, QTableWidget, QTableWidgetItem, QCheckBox, QPlainTextEdit, QProgressBar, QFileDialog,
    QMessageBox, QSplitter, QHeaderView, QButtonGroup, QAbstractItemView, QDialog, QDialogButtonBox)

KOFI_URL = "https://ko-fi.com/vincentmouge"
GITHUB_URL = "https://github.com/turtlem/daw2score"
RELEASES_API = "https://api.github.com/repos/turtlem/daw2score/releases/latest"

import project, exporter, transcribe
from version import __version__

HERE = os.path.dirname(os.path.abspath(__file__))
FROZEN = getattr(sys, "frozen", False)  # running from the installed build (PyInstaller)
if sys.platform == "darwin":
    APP_DIR = os.path.expanduser("~/Library/Application Support/daw2score")
else:
    APP_DIR = os.path.join(os.environ.get("LOCALAPPDATA") or os.path.expanduser("~"), "daw2score")
LOG_PATH = os.path.join(APP_DIR, "daw2score.log")
LOG = None  # log file, opened by main(); everything shown in the window's log is also written there
LANG = "en"  # "en" or "fr", set by main() from the saved choice or the system language


def T(fr, en):
    """The label in the current language (French and English are written side by side)."""
    return fr if LANG == "fr" else en


def role_labels():  # (kind or None for automatic, label)
    return [(None, "Auto"), ("drums", T("Batterie", "Drums")), ("bass", T("Basse", "Bass")),
            ("gtr_heavy", T("Guitare saturée", "Distorted guitar")),
            ("gtr_clean", T("Guitare claire", "Clean guitar")), ("gtr_solo", T("Guitare solo", "Lead guitar")),
            ("chords", T("Guitare (accords)", "Guitar (chords)")), ("vocal", T("Chant", "Vocals")),
            ("keys", T("Claviers", "Keys"))]


def kind_label(k):
    labels = {kk: l for kk, l in role_labels() if kk}
    labels |= {"other": T("autre", "other"), "drums_audio": T("batterie, micros", "drums, mics")}
    return labels.get(k, k)


def type_label(typ):
    return {"drum_folder": T("Dossier batterie (audio)", "Drum folder (audio)"), "folder": T("Dossier", "Folder"),
            "midi": "MIDI", "audio": "Audio", "empty": T("Vide", "Empty")}[typ]


COL_TRACK, COL_TYPE, COL_ROLE, COL_NAME, COL_AUDIO, COL_HARM = range(6)


def formats():
    return [(".gp", "Guitar Pro 7/8 (.gp)"), (".musicxml", "MusicXML (Finale, MuseScore, Dorico…)"),
            (".gp5", "Guitar Pro 5 (.gp5)")]


# ---------------------------------------------------------------- background jobs
class _Stream(QObject):
    text = Signal(str)

    def write(self, s):
        if s:
            self.text.emit(s)

    def flush(self):
        pass


class Job(QThread):
    """Runs fn() in a thread; its prints go to the log. done(result) or failed(message)."""
    log = Signal(str)
    done = Signal(object)
    failed = Signal(str)

    def __init__(self, fn):
        super().__init__()
        self.fn = fn

    def run(self):
        stream = _Stream()
        stream.text.connect(self.log.emit)
        try:
            with contextlib.redirect_stdout(stream), contextlib.redirect_stderr(stream):
                res = self.fn()
            self.done.emit(res)
        except SystemExit as e:
            self.failed.emit(str(e.code) if e.code not in (None, 0) else T("arrêt", "stopped"))
        except Exception as e:  # noqa: BLE001 - shown to the user
            self.failed.emit(f"{type(e).__name__}: {e}\n{traceback.format_exc()}")


# ---------------------------------------------------------------- helpers
def track_type(trs, t):
    if t["is_folder"]:
        return "drum_folder" if exporter.is_audio_drum_folder(trs, t) else "folder"
    its = [i for i in t["items"] if not i["mute"]]
    if any(i.get("src_type") == "MIDI" for i in its):
        return "midi"
    return "audio" if any(i.get("file") for i in its) else "empty"


def auto_kind(trs, t):
    """The role build_gp would pick without an override."""
    typ = track_type(trs, t)
    if typ == "drum_folder":
        return "drums_audio"
    if typ == "midi":
        if t.get("drums") or "drum" in t["name"].lower() or "EZdrummer" in t["fx"]:
            return "drums"
        k = transcribe.guess_kind(t["name"])
        return "keys" if k == "other" else k
    return transcribe.guess_kind(t["name"])


def track_keys(trs):
    """Stable keys for remembering settings: name, plus #n when several tracks share it."""
    seen, keys = {}, []
    for t in trs:
        n = seen.get(t["name"], 0)
        seen[t["name"]] = n + 1
        keys.append(t["name"] if n == 0 else f'{t["name"]}#{n + 1}')
    return keys


# ---------------------------------------------------------------- window
class Main(QMainWindow):
    def __init__(self):
        super().__init__()
        self.setWindowTitle(f"daw2score {__version__}")
        self.resize(1100, 760)
        self.setAcceptDrops(True)
        self.P = None
        self.job = None
        self.qs = QSettings("daw2score", "daw2score")

        central = QWidget()
        lay = QVBoxLayout(central)
        top = QHBoxLayout()
        self.path_edit = QLineEdit()
        self.path_edit.setReadOnly(True)
        self.path_edit.setPlaceholderText(T("Glisse ici un projet REAPER (.rpp), un .dawproject ou un dossier de stems",
                                            "Drop a REAPER project (.rpp), a .dawproject or a stems folder here"))
        b_file = QPushButton(T("Ouvrir un projet…", "Open project…"))
        b_file.clicked.connect(self.pick_file)
        b_dir = QPushButton(T("Dossier de stems…", "Stems folder…"))
        b_dir.clicked.connect(self.pick_dir)
        self.lang = QComboBox()
        self.lang.addItem("English", "en")
        self.lang.addItem("Français", "fr")
        self.lang.setCurrentIndex(self.lang.findData(LANG))
        self.lang.currentIndexChanged.connect(self.switch_language)
        top.addWidget(QLabel(T("Projet :", "Project:")))
        top.addWidget(self.path_edit, 1)
        top.addWidget(b_file)
        top.addWidget(b_dir)
        top.addWidget(self.lang)
        b_about = QPushButton("?")
        b_about.setFixedWidth(28)
        b_about.setToolTip(T("À propos de daw2score", "About daw2score"))
        b_about.clicked.connect(lambda: About(self).exec())
        top.addWidget(b_about)
        lay.addLayout(top)
        self.info = QLabel(" ")
        self.info.setStyleSheet("color: palette(mid);")
        lay.addWidget(self.info)

        split = QSplitter(Qt.Vertical)
        self.tabs = QTabWidget()
        self.tabs.addTab(self._tracks_tab(), T("Pistes", "Tracks"))
        self.tabs.addTab(self._tempo_tab(), T("Tempo et sections", "Tempo and sections"))
        self.tabs.addTab(self._output_tab(), T("Sortie", "Output"))
        split.addWidget(self.tabs)
        self.log = QPlainTextEdit()
        self.log.setReadOnly(True)
        mono = QFontDatabase.systemFont(QFontDatabase.FixedFont)
        mono.setPointSize(9 if sys.platform != "darwin" else 11)
        self.log.setFont(mono)
        self.log.setMaximumBlockCount(5000)
        split.addWidget(self.log)
        split.setSizes([560, 160])
        lay.addWidget(split, 1)

        bottom = QHBoxLayout()
        self.progress = QProgressBar()
        self.progress.setRange(0, 1)
        self.progress.setTextVisible(False)
        self.status = QLabel("")
        self.export_btn = QPushButton(T("Exporter", "Export"))
        self.export_btn.setMinimumWidth(140)
        self.export_btn.setDefault(True)
        self.export_btn.clicked.connect(self.do_export)
        kofi = QLabel(f'<a href="{KOFI_URL}">☕ {T("Soutenir le projet", "Support the project")}</a>')
        kofi.setOpenExternalLinks(True)
        kofi.setToolTip(KOFI_URL)
        bottom.addWidget(kofi)
        bottom.addWidget(self.status, 1)
        bottom.addWidget(self.progress)
        bottom.addWidget(self.export_btn)
        lay.addLayout(bottom)
        self.setCentralWidget(central)
        self._set_enabled(False)

    # ------------------------------------------------------------ tabs
    def _tracks_tab(self):
        w = QWidget()
        v = QVBoxLayout(w)
        self.tree = QTreeWidget()
        self.tree.setHeaderLabels([T("Piste", "Track"), "Type", T("Rôle", "Role"),
                                   T("Nom dans la partition", "Name in the score"), "Audio .gp", T("Accords", "Chords")])
        h = self.tree.header()
        h.setSectionResizeMode(COL_TRACK, QHeaderView.Stretch)
        for c, wd in ((COL_TYPE, 150), (COL_ROLE, 170), (COL_NAME, 200), (COL_AUDIO, 75), (COL_HARM, 70)):
            h.setSectionResizeMode(c, QHeaderView.Interactive)
            self.tree.setColumnWidth(c, wd)
        self.tree.headerItem().setToolTip(COL_AUDIO, T("Mixée dans la piste audio du .gp (Guitar Pro 8)",
                                                       "Mixed into the audio track of the .gp (Guitar Pro 8)"))
        self.tree.headerItem().setToolTip(COL_HARM, T("Écoutée pour détecter les accords des pistes « Guitare (accords) »",
                                                      "Listened to when detecting the chords of the Guitar (chords) tracks"))
        self.tree.headerItem().setToolTip(COL_NAME, T("Les pistes qui portent le même nom sont fusionnées en une seule piste",
                                                      "Tracks with the same name are merged into one score track"))
        self.tree.itemChanged.connect(self._item_changed)
        self.tree.setEditTriggers(QAbstractItemView.DoubleClicked | QAbstractItemView.EditKeyPressed
                                  | QAbstractItemView.SelectedClicked)
        v.addWidget(self.tree, 1)
        hint = QLabel(T("Coche les pistes à exporter. Même nom dans la partition = pistes fusionnées "
                        "(ex. un chant réparti sur plusieurs pistes). Un dossier de micros de batterie "
                        "s'exporte en une seule piste de batterie. « Accords » : pistes écoutées pour "
                        "détecter les accords (par défaut, les pistes en rôle Guitare (accords)).",
                        "Tick the tracks to export. Same name in the score = merged tracks (e.g. a lead "
                        "vocal split over several tracks). A folder of drum mics exports as one drum track. "
                        "Chords: tracks listened to when detecting the chords (by default, the tracks "
                        "with the Guitar (chords) role)."))
        hint.setWordWrap(True)
        hint.setStyleSheet("color: palette(mid);")
        v.addWidget(hint)
        return w

    def _tempo_tab(self):
        w = QWidget()
        v = QVBoxLayout(w)
        g = QGroupBox("Tempo")
        gl = QGridLayout(g)
        self.t_group = QButtonGroup(self)
        self.t_project = QRadioButton(T("Tempo du projet", "Project tempo"))
        self.t_manual = QRadioButton(T("Tempo manuel", "Manual tempo"))
        self.t_auto = QRadioButton(T("Détecter à l'export (batterie)", "Detect when exporting (drums)"))
        for k, b in enumerate((self.t_project, self.t_manual, self.t_auto)):
            self.t_group.addButton(b, k)
        self.t_project.setChecked(True)
        self.t_spin = QDoubleSpinBox()
        self.t_spin.setRange(20, 400)
        self.t_spin.setDecimals(2)
        self.t_spin.setSuffix(" BPM")
        self.t_spin.setValue(120)
        self.t_spin.valueChanged.connect(lambda _: self.t_manual.setChecked(True))
        self.t_detect = QPushButton(T("Détecter maintenant", "Detect now"))
        self.t_detect.clicked.connect(self.detect_tempo)
        self.t_note = QLabel(T("Enregistrement fait au clic mais projet resté à 120 BPM : détecte ou saisis le vrai tempo.",
                               "Recorded to a click but the project stayed at 120 BPM? Detect or type the real tempo."))
        self.t_note.setWordWrap(True)
        self.t_note.setStyleSheet("color: palette(mid);")
        gl.addWidget(self.t_project, 0, 0)
        gl.addWidget(self.t_manual, 1, 0)
        gl.addWidget(self.t_spin, 1, 1)
        gl.addWidget(self.t_detect, 1, 2)
        gl.addWidget(self.t_auto, 2, 0)
        gl.addWidget(self.t_note, 3, 0, 1, 4)
        gl.setColumnStretch(3, 1)
        v.addWidget(g)

        g2 = QGroupBox("Sections")
        g2l = QVBoxLayout(g2)
        row = QHBoxLayout()
        self.s_markers = QRadioButton(T("Marqueurs du projet", "Project markers"))
        self.s_custom = QRadioButton(T("Sections ci-dessous", "Sections below"))
        self.s_markers.setChecked(True)
        row.addWidget(self.s_markers)
        row.addWidget(self.s_custom)
        row.addStretch(1)
        g2l.addLayout(row)
        self.s_table = QTableWidget(0, 2)
        self.s_table.setHorizontalHeaderLabels([T("Mesure", "Bar"), T("Nom", "Name")])
        self.s_table.horizontalHeader().setSectionResizeMode(1, QHeaderView.Stretch)
        self.s_table.verticalHeader().setVisible(False)
        self.s_table.itemChanged.connect(lambda _: self.s_custom.setChecked(True))
        g2l.addWidget(self.s_table, 1)
        row = QHBoxLayout()
        for text, fn in ((T("Ajouter", "Add"), self.add_section), (T("Supprimer", "Remove"), self.del_section),
                         (T("Copier les marqueurs", "Copy markers"), self.copy_markers),
                         (T("Proposer automatiquement", "Suggest sections"), self.propose_sections)):
            b = QPushButton(text)
            b.clicked.connect(fn)
            row.addWidget(b)
        row.addStretch(1)
        g2l.addLayout(row)
        note = QLabel(T("« Proposer » analyse les pistes cochées (niveaux, harmonie) et marque les changements "
                        "de partie, à renommer (A, B, C… = parties qui se ressemblent). Le tempo doit être juste.",
                        "Suggest analyses the ticked tracks (levels, harmony) and marks where the song changes, "
                        "for you to rename (A, B, C… = parts that sound alike). The tempo must be right."))
        note.setWordWrap(True)
        note.setStyleSheet("color: palette(mid);")
        g2l.addWidget(note)
        v.addWidget(g2, 1)
        return w

    def _output_tab(self):
        w = QWidget()
        f = QFormLayout(w)
        row = QHBoxLayout()
        self.o_dir = QLineEdit()
        b = QPushButton("…")
        b.setFixedWidth(32)
        b.clicked.connect(self.pick_out_dir)
        row.addWidget(self.o_dir, 1)
        row.addWidget(b)
        f.addRow(T("Dossier :", "Folder:"), row)
        self.o_name = QLineEdit()
        f.addRow(T("Nom du fichier :", "File name:"), self.o_name)
        fmt = QVBoxLayout()
        self.o_formats = {}
        for ext, label in formats():
            c = QCheckBox(label)
            c.setChecked(ext == ".gp")
            self.o_formats[ext] = c
            fmt.addWidget(c)
        f.addRow(T("Formats :", "Formats:"), fmt)
        self.o_clean_bass = QCheckBox(T("Nettoyer les basses transcrites (octaves, sauts, notes parasites)",
                                        "Clean transcribed bass lines (octaves, leaps, stray notes)"))
        self.o_clean_bass.setChecked(True)
        f.addRow(T("Basse :", "Bass:"), self.o_clean_bass)
        self.o_drum_map = QComboBox()
        for p in sorted(glob.glob(os.path.join(HERE, "drum_maps", "*.json"))):
            self.o_drum_map.addItem(os.path.splitext(os.path.basename(p))[0], p)
        self.o_drum_map.addItem(T("Autre fichier…", "Other file…"), None)
        self.o_drum_map.activated.connect(self._drum_map_other)
        f.addRow(T("Table batterie MIDI :", "MIDI drum map:"), self.o_drum_map)
        self.o_backing_name = QLineEdit()
        self.o_backing_name.setPlaceholderText(T("par défaut : noms des pistes cochées « Audio .gp »",
                                                 "default: names of the tracks ticked Audio .gp"))
        f.addRow(T("Piste audio .gp :", "Audio track (.gp):"), self.o_backing_name)
        self.o_force = QCheckBox(T("Écraser les fichiers existants", "Overwrite existing files"))
        f.addRow("", self.o_force)
        return w

    # ------------------------------------------------------------ project loading
    def dragEnterEvent(self, e):
        if e.mimeData().hasUrls():
            e.acceptProposedAction()

    def dropEvent(self, e):
        urls = e.mimeData().urls()
        if urls:
            self.load(urls[0].toLocalFile())

    def pick_file(self):
        p, _ = QFileDialog.getOpenFileName(self, T("Projet", "Project"), self.qs.value("last_dir", ""),
                                           T("Projets (*.rpp *.dawproject);;Tous les fichiers (*)",
                                             "Projects (*.rpp *.dawproject);;All files (*)"))
        if p:
            self.load(p)

    def pick_dir(self):
        p = QFileDialog.getExistingDirectory(self, T("Dossier de stems", "Stems folder"), self.qs.value("last_dir", ""))
        if p:
            self.load(p)

    def pick_out_dir(self):
        p = QFileDialog.getExistingDirectory(self, T("Dossier de sortie", "Output folder"), self.o_dir.text())
        if p:
            self.o_dir.setText(p)

    def _drum_map_other(self, k):
        if self.o_drum_map.itemData(k) is None:
            p, _ = QFileDialog.getOpenFileName(self, T("Table batterie", "Drum map"), HERE, "JSON (*.json)")
            if p:
                self.o_drum_map.insertItem(k, os.path.basename(p), p)
                self.o_drum_map.setCurrentIndex(k)
            else:
                self.o_drum_map.setCurrentIndex(0)

    def load(self, path):
        if self.job:
            return
        self.save_settings()
        try:
            P = project.load(path)
        except (SystemExit, Exception) as e:  # noqa: BLE001
            QMessageBox.warning(self, "daw2score", T(f"Impossible de lire {path} :\n{e}", f"Cannot read {path}:\n{e}"))
            return
        self.P = P
        self.qs.setValue("last_dir", os.path.dirname(os.path.abspath(path)))
        self.path_edit.setText(os.path.abspath(path))
        kind = T("dossier de stems", "stems folder") if os.path.isdir(path) else (
            "DAWproject" if path.lower().endswith(".dawproject") else "REAPER")
        info = P.info
        self.info.setText(f"{kind} · {len(P.tracks)} {T('pistes', 'tracks')} · {info['tempo']:g} BPM · "
                          f"{info['ts_num']}/{info['ts_den']} · {len(info['markers'])} {T('marqueurs', 'markers')}")
        self.t_project.setText(T("Tempo du projet", "Project tempo") + f" ({info['tempo']:g} BPM)")
        self._fill_tree()
        self.s_table.blockSignals(True)
        self.s_table.setRowCount(0)
        self.s_table.blockSignals(False)
        self.s_markers.setChecked(True)
        self.t_project.setChecked(True)
        self.t_spin.blockSignals(True)
        self.t_spin.setValue(info["tempo"])
        self.t_spin.blockSignals(False)
        self.o_dir.setText(P.dir)
        self.o_name.setText(P.name)
        self.load_settings()
        self._set_enabled(True)
        self.note(T("projet chargé : ", "project loaded: ") + os.path.abspath(path))

    def _fill_tree(self):
        self.tree.blockSignals(True)
        self.tree.clear()
        trs = self.P.tracks
        self.items = {}
        stack = []
        for t in trs:
            while stack and stack[-1][0] >= t["depth"]:
                stack.pop()
            parent = stack[-1][1] if stack else self.tree
            it = QTreeWidgetItem(parent)
            it.setData(COL_TRACK, Qt.UserRole, t["index"])
            it.setText(COL_TRACK, t["name"])
            typ = track_type(trs, t)
            it.setText(COL_TYPE, type_label(typ))
            flags = it.flags() | Qt.ItemIsUserCheckable
            it.setCheckState(COL_TRACK, Qt.Unchecked)
            leaf_like = not t["is_folder"] or typ == "drum_folder"
            if leaf_like and typ != "empty":
                flags |= Qt.ItemIsEditable
                it.setText(COL_NAME, t["name"])
                it.setCheckState(COL_AUDIO, Qt.Unchecked)
                if typ == "audio":
                    it.setCheckState(COL_HARM, Qt.Unchecked)
            it.setFlags(flags)
            self.items[t["index"]] = it
            if leaf_like and typ != "empty":
                combo = QComboBox()
                auto = auto_kind(trs, t)
                for k, label in role_labels():
                    if typ == "drum_folder" and k not in (None, "drums"):
                        continue
                    combo.addItem(f"Auto ({kind_label(auto)})" if k is None else label, k)
                combo.setProperty("track", t["index"])
                self.tree.setItemWidget(it, COL_ROLE, combo)
            if t["is_folder"]:
                stack.append((t["depth"], it))
                it.setExpanded(typ != "drum_folder")
        self.tree.blockSignals(False)

    def _item_changed(self, it, col):
        """Folder check -> children; columns other than the name are not editable."""
        if col == COL_TRACK and it.childCount():
            idx = it.data(COL_TRACK, Qt.UserRole)
            drum = track_type(self.P.tracks, self.P.tracks[idx]) == "drum_folder"
            self.tree.blockSignals(True)
            for k in range(it.childCount()):
                c = it.child(k)
                if drum:  # the folder itself is the drum track: its mics are not exported one by one
                    c.setCheckState(COL_TRACK, Qt.Unchecked)
                    c.setDisabled(it.checkState(COL_TRACK) == Qt.Checked)
                else:
                    self._check_recursive(c, it.checkState(COL_TRACK))
            self.tree.blockSignals(False)

    def _check_recursive(self, it, state):
        if it.flags() & Qt.ItemIsUserCheckable and not it.isDisabled():
            it.setCheckState(COL_TRACK, state)
        for k in range(it.childCount()):
            self._check_recursive(it.child(k), state)

    def role_of(self, idx):
        combo = self.tree.itemWidget(self.items[idx], COL_ROLE)
        return combo.currentData() if combo else None

    # ------------------------------------------------------------ settings
    def _settings_path(self):
        if not self.P:
            return None
        return os.path.join(self.P.dir, "gp_export_cache", f"gui_{self.P.name}.json")

    def collect_settings(self):
        keys = track_keys(self.P.tracks)
        tracks = {}
        for t in self.P.tracks:
            it = self.items[t["index"]]
            d = {"checked": it.checkState(COL_TRACK) == Qt.Checked}
            if it.text(COL_NAME):
                d["name"] = it.text(COL_NAME)
                d["audio"] = it.checkState(COL_AUDIO) == Qt.Checked
                d["harmony"] = it.data(COL_HARM, Qt.CheckStateRole) is not None and it.checkState(COL_HARM) == Qt.Checked
                d["role"] = self.role_of(t["index"])
            tracks[keys[t["index"]]] = d
        return {
            "tracks": tracks,
            "tempo_mode": self.t_group.checkedId(), "tempo": self.t_spin.value(),
            "sections_custom": self.s_custom.isChecked(), "sections": self.sections_table(),
            "out_dir": self.o_dir.text(), "out_name": self.o_name.text(),
            "formats": [e for e, c in self.o_formats.items() if c.isChecked()],
            "clean_bass": self.o_clean_bass.isChecked(),
            "drum_map": self.o_drum_map.currentData(), "backing_name": self.o_backing_name.text(),
        }

    def save_settings(self):
        p = self._settings_path() if self.P else None
        if not p:
            return
        try:
            os.makedirs(os.path.dirname(p), exist_ok=True)
            with open(p, "w", encoding="utf-8") as f:
                json.dump(self.collect_settings(), f, ensure_ascii=False, indent=1)
        except OSError:
            pass

    def load_settings(self):
        p = self._settings_path()
        if not p or not os.path.exists(p):
            return
        try:
            s = json.load(open(p, encoding="utf-8"))
        except (OSError, ValueError):
            return
        keys = track_keys(self.P.tracks)
        self.tree.blockSignals(True)
        for t in self.P.tracks:
            d = s.get("tracks", {}).get(keys[t["index"]])
            if not d:
                continue
            it = self.items[t["index"]]
            if it.text(COL_NAME) and "name" in d:
                it.setText(COL_NAME, d["name"])
                it.setCheckState(COL_AUDIO, Qt.Checked if d.get("audio") else Qt.Unchecked)
                if it.data(COL_HARM, Qt.CheckStateRole) is not None:
                    it.setCheckState(COL_HARM, Qt.Checked if d.get("harmony") else Qt.Unchecked)
                combo = self.tree.itemWidget(it, COL_ROLE)
                if combo:
                    k = combo.findData(d.get("role"))
                    combo.setCurrentIndex(max(k, 0))
            it.setCheckState(COL_TRACK, Qt.Checked if d.get("checked") else Qt.Unchecked)
        self.tree.blockSignals(False)
        for t in self.P.tracks:  # re-apply folder rules (drum folder disables its mics)
            it = self.items[t["index"]]
            if it.childCount() and track_type(self.P.tracks, t) == "drum_folder":
                self._item_changed(it, COL_TRACK)
        self.t_spin.blockSignals(True)
        self.t_spin.setValue(s.get("tempo", self.t_spin.value()))
        self.t_spin.blockSignals(False)
        b = self.t_group.button(s.get("tempo_mode", 0))
        if b:
            b.setChecked(True)
        self.set_sections(s.get("sections", {}))
        (self.s_custom if s.get("sections_custom") else self.s_markers).setChecked(True)
        if s.get("out_dir"):
            self.o_dir.setText(s["out_dir"])
        if s.get("out_name"):
            self.o_name.setText(s["out_name"])
        for e, c in self.o_formats.items():
            c.setChecked(e in s.get("formats", [".gp"]))
        self.o_clean_bass.setChecked(s.get("clean_bass", True))
        k = self.o_drum_map.findData(s.get("drum_map"))
        if k >= 0:
            self.o_drum_map.setCurrentIndex(k)
        self.o_backing_name.setText(s.get("backing_name", ""))

    def closeEvent(self, e):
        self.save_settings()
        super().closeEvent(e)

    # ------------------------------------------------------------ sections
    def sections_table(self):
        out = {}
        for r in range(self.s_table.rowCount()):
            b, n = self.s_table.item(r, 0), self.s_table.item(r, 1)
            if b and n and b.text().strip().isdigit() and n.text().strip():
                out[int(b.text())] = n.text().strip()
        return out

    def set_sections(self, secs):
        self.s_table.blockSignals(True)
        self.s_table.setRowCount(0)
        for b, n in sorted(((int(b), n) for b, n in secs.items())):
            r = self.s_table.rowCount()
            self.s_table.insertRow(r)
            self.s_table.setItem(r, 0, QTableWidgetItem(str(b)))
            self.s_table.setItem(r, 1, QTableWidgetItem(n))
        self.s_table.blockSignals(False)

    def add_section(self):
        r = self.s_table.rowCount()
        self.s_table.insertRow(r)
        self.s_table.setItem(r, 0, QTableWidgetItem(""))
        self.s_table.setItem(r, 1, QTableWidgetItem(""))
        self.s_table.editItem(self.s_table.item(r, 0))
        self.s_custom.setChecked(True)

    def del_section(self):
        for r in sorted({i.row() for i in self.s_table.selectedIndexes()}, reverse=True):
            self.s_table.removeRow(r)
        self.s_custom.setChecked(True)

    def bar_of(self, t_s):
        import build_gp
        info = dict(self.P.info)
        bpm = self.current_bpm()
        if self.t_group.checkedId() != 0:
            info["tempo"], info["tempo_points"] = bpm, []
        ms = build_gp.build_measures(info, t_s * bpm / 60.0 + 0.01)
        return len(ms)

    def copy_markers(self):
        if not self.P:
            return
        self.set_sections({self.bar_of(t): n for t, n in self.P.info["markers"]})
        self.s_custom.setChecked(True)

    def current_bpm(self):
        return self.t_spin.value() if self.t_group.checkedId() == 1 else self.P.info["tempo"]

    def propose_sections(self):
        idxs = [i for i, _, _ in self.selection()] or [t["index"] for t in self.P.tracks if not t["is_folder"]]
        if self.t_group.checkedId() == 2:
            QMessageBox.information(self, "daw2score", T("Détecte d'abord le tempo (bouton « Détecter maintenant »).",
                                                         "Detect the tempo first (Detect now button)."))
            return
        bpm, path = self.current_bpm(), self.path_edit.text()

        def run():
            import sections
            print(T(f"analyse des sections ({len(idxs)} pistes, {bpm:g} BPM)...",
                    f"analysing sections ({len(idxs)} tracks, {bpm:g} BPM)..."))
            return sections.propose(path, idxs, bpm)
        self.start(run, self._sections_done, T("Analyse des sections…", "Analysing sections…"))

    def _sections_done(self, secs):
        self.set_sections(secs)
        self.s_custom.setChecked(True)
        self.note(T("sections proposées : ", "suggested sections: ") + str(secs))

    # ------------------------------------------------------------ tempo
    def detect_tempo(self):
        path = self.path_edit.text()

        def run():
            import tempo
            d = tempo.detect(path)
            tempo.report(d)
            return d
        self.start(run, self._tempo_done, T("Détection du tempo…", "Detecting the tempo…"))

    def _tempo_done(self, d):
        b = d["bpm"]
        b = float(round(b)) if abs(b - round(b)) < 0.15 else round(b, 2)
        self.t_spin.setValue(b)
        self.t_manual.setChecked(True)
        self.note(T(f"tempo détecté : {b:g} BPM (écart à la grille {d['residual_ms']:.0f} ms)",
                    f"detected tempo: {b:g} BPM (grid residual {d['residual_ms']:.0f} ms)"))

    # ------------------------------------------------------------ export
    def selection(self):
        """-> [(index, role, score name)] of the checked tracks, in project order."""
        out = []
        for t in self.P.tracks:
            it = self.items[t["index"]]
            if it.checkState(COL_TRACK) != Qt.Checked or it.isDisabled() or not it.text(COL_NAME):
                continue
            out.append((t["index"], self.role_of(t["index"]), it.text(COL_NAME).strip() or t["name"]))
        return out

    def build_args(self):
        """GUI state -> exporter.export keyword arguments (raises ValueError with a message)."""
        sel = self.selection()
        if not sel:
            raise ValueError(T("Coche au moins une piste à exporter (onglet Pistes).",
                               "Tick at least one track to export (Tracks tab)."))
        groups, chords, roles = {}, {}, {}
        for i, role, name in sel:
            if role:
                roles[i] = role
            (chords if role == "chords" else groups).setdefault(name, []).append(i)
        harmony_idxs = [t["index"] for t in self.P.tracks
                        if self.items[t["index"]].data(COL_HARM, Qt.CheckStateRole) is not None
                        and self.items[t["index"]].checkState(COL_HARM) == Qt.Checked]
        backing = []
        for t in self.P.tracks:
            it = self.items[t["index"]]
            if it.text(COL_NAME) and it.checkState(COL_AUDIO) == Qt.Checked:
                if t["is_folder"]:
                    import build_gp
                    backing += [c["index"] for c in build_gp.expand_selection(self.P.tracks, [t["index"]])]
                else:
                    backing.append(t["index"])
        exts = [e for e, c in self.o_formats.items() if c.isChecked()]
        if not exts:
            raise ValueError(T("Choisis au moins un format de sortie (onglet Sortie).",
                               "Choose at least one output format (Output tab)."))
        name = self.o_name.text().strip()
        if not name or not self.o_dir.text().strip():
            raise ValueError(T("Indique un dossier et un nom de fichier (onglet Sortie).",
                               "Enter a folder and a file name (Output tab)."))
        outs = [os.path.join(self.o_dir.text().strip(), name + e) for e in exts]
        mode = self.t_group.checkedId()
        tempo = None if mode == 0 else (self.t_spin.value() if mode == 1 else "auto")
        sections = self.sections_table() if self.s_custom.isChecked() else None
        if self.s_custom.isChecked() and not sections:
            raise ValueError(T("Le tableau des sections est vide : ajoute des sections ou choisis les marqueurs du projet.",
                               "The sections table is empty: add sections or use the project markers."))
        return dict(proj_path=self.path_edit.text(), outs=outs, groups=list(groups.items()),
                    chord_specs=list(chords.items()), harmony_idxs=harmony_idxs or None, tempo=tempo,
                    sections=sections, clean_bass=self.o_clean_bass.isChecked(),
                    drum_map=self.o_drum_map.currentData(), roles=roles, backing=backing or None,
                    backing_name=self.o_backing_name.text().strip() or None,
                    force=self.o_force.isChecked())

    def do_export(self):
        try:
            args = self.build_args()
        except ValueError as e:
            QMessageBox.information(self, "daw2score", str(e))
            return
        existing = [o for o in args["outs"] if os.path.exists(o)]
        if existing and not args["force"]:
            if QMessageBox.question(self, "daw2score", T("Ces fichiers existent déjà :", "These files already exist:")
                                    + "\n" + "\n".join(existing)
                                    + "\n\n" + T("Les remplacer ?", "Replace them?")) != QMessageBox.Yes:
                return
            args["force"] = True
        self.save_settings()
        self.note("\n=== export ===")
        self.start(lambda: exporter.export(**args), self._export_done, T("Export en cours…", "Exporting…"))

    def _export_done(self, res):
        outs = res["outputs"]
        self.note(T("terminé : ", "done: ") + ", ".join(outs))
        self.status.setText(T("Exporté : ", "Exported: ") + ", ".join(os.path.basename(o) for o in outs))

    # ------------------------------------------------------------ job plumbing
    def _set_enabled(self, on):
        for w in (self.tabs, self.export_btn):
            w.setEnabled(on)

    def start(self, fn, on_done, label):
        if self.job:
            return
        self.job = Job(fn)
        self.job.log.connect(self._append_log)
        self.job.done.connect(on_done)
        self.job.failed.connect(self._failed)
        self.job.finished.connect(self._finished)
        self.status.setText(label)
        self.progress.setRange(0, 0)
        self._set_enabled(False)
        self.job.start()

    def switch_language(self):
        """Rebuild the window in the chosen language, keeping the project and its settings."""
        global LANG
        if self.job:
            self.lang.blockSignals(True)
            self.lang.setCurrentIndex(self.lang.findData(LANG))
            self.lang.blockSignals(False)
            return
        LANG = self.lang.currentData()
        self.qs.setValue("lang", LANG)
        self.save_settings()
        w = Main()
        w.setGeometry(self.geometry())
        if self.P:
            w.load(self.path_edit.text())
        w.show()
        QApplication.instance().setProperty("main_window", w)
        self.close()

    def note(self, s):
        """A line of the window's own in the log (on its own line, after any job output)."""
        if self.log.toPlainText() and not self.log.toPlainText().endswith("\n"):
            s = "\n" + s
        self._append_log(s + "\n")

    def _append_log(self, s):
        log_write(s)
        self.log.moveCursor(self.log.textCursor().MoveOperation.End)
        self.log.insertPlainText(s)
        self.log.ensureCursorVisible()

    def _failed(self, msg):
        self.note(T("ERREUR : ", "ERROR: ") + msg)
        self.status.setText(T("Échec", "Failed"))
        QMessageBox.warning(self, "daw2score", msg.splitlines()[0] if msg else T("Échec", "Failed"))

    def _finished(self):
        self.job = None
        self.progress.setRange(0, 1)
        self._set_enabled(True)
        if self.status.text().endswith("…"):
            self.status.setText("")


# ---------------------------------------------------------------- about, updates, log file
def version_tuple(v):
    return tuple(int(x) for x in v.lstrip("vV").split("-")[0].split(".") if x.isdigit())


def latest_release():
    """-> (version, page url) of the latest GitHub release. Sends nothing but the request itself."""
    import urllib.request
    req = urllib.request.Request(RELEASES_API, headers={"User-Agent": f"daw2score/{__version__}",
                                                        "Accept": "application/vnd.github+json"})
    with urllib.request.urlopen(req, timeout=8) as r:
        d = json.load(r)
    return d["tag_name"].lstrip("vV"), d["html_url"]


def notices_path():
    """Third-party licenses: the licenses folder of the installed build, else the notices file."""
    lic = os.path.join(HERE, "licenses")  # bundled next to the modules (packaging/build.py)
    return lic if os.path.isdir(lic) else os.path.join(os.path.dirname(HERE), "THIRD_PARTY_NOTICES.md")


class App(QApplication):
    """macOS sends files opened from the Finder / Dock (or `open -a daw2score file`) as FileOpen events."""
    def event(self, e):
        if e.type() == QEvent.FileOpen and e.file():
            w = self.property("main_window")
            if w is not None:
                w.load(e.file())
            else:
                self.pending = e.file()
            return True
        return super().event(e)


class About(QDialog):
    def __init__(self, parent):
        super().__init__(parent)
        self.setWindowTitle(T("À propos de daw2score", "About daw2score"))
        lay = QVBoxLayout(self)
        text = QLabel(
            f"<h2>daw2score {__version__}</h2>"
            + T("<p>Partitions Guitar Pro et MusicXML à partir de projets REAPER, DAWproject ou de stems + MIDI.</p>",
                "<p>Guitar Pro and MusicXML scores from REAPER projects, DAWproject files or stems + MIDI.</p>")
            + f'<p><a href="{GITHUB_URL}">{GITHUB_URL}</a><br>'
            + f'<a href="{KOFI_URL}">☕ {T("Soutenir le projet sur Ko-fi", "Support the project on Ko-fi")}</a></p>'
            + T("<p>Licence MIT. Composants tiers : ", "<p>MIT license. Third-party components: ")
            + f'<a href="{QUrl.fromLocalFile(notices_path()).toString()}">{T("licences", "licenses")}</a> '
            + "(Qt / PySide6 LGPL-3.0, alphaTab MPL-2.0, basic-pitch Apache-2.0, librosa ISC, Node.js MIT…).</p>"
            + T("<p>Journal : ", "<p>Log: ")
            + f'<a href="{QUrl.fromLocalFile(APP_DIR).toString()}">{LOG_PATH}</a></p>')
        text.setTextFormat(Qt.RichText)
        text.setOpenExternalLinks(True)
        text.setWordWrap(True)
        text.setMinimumWidth(460)
        lay.addWidget(text)
        self.upd = QLabel("")
        self.upd.setOpenExternalLinks(True)
        self.upd.setWordWrap(True)
        lay.addWidget(self.upd)
        bb = QDialogButtonBox(QDialogButtonBox.Close)
        chk = bb.addButton(T("Vérifier les mises à jour", "Check for updates"), QDialogButtonBox.ActionRole)
        chk.clicked.connect(self.check)
        bb.rejected.connect(self.reject)
        lay.addWidget(bb)

    def check(self):
        self.upd.setText(T("Recherche…", "Checking…"))
        QApplication.processEvents()
        try:
            v, url = latest_release()
        except Exception as e:  # noqa: BLE001 - offline, no release yet, rate limit...
            if getattr(e, "code", None) == 404:
                self.upd.setText(T("Aucune version publiée pour l'instant.", "No published release yet."))
                return
            self.upd.setText(T("Impossible de vérifier : ", "Could not check: ") + str(e))
            return
        if version_tuple(v) > version_tuple(__version__):
            self.upd.setText(f'<b>{T("Nouvelle version", "New version")} {v}</b> : '
                             f'<a href="{url}">{T("télécharger", "download")}</a>')
        else:
            self.upd.setText(T(f"daw2score {__version__} est à jour.", f"daw2score {__version__} is up to date."))


def log_write(s):
    if LOG:
        try:
            LOG.write(s)
        except (OSError, ValueError):
            pass


def open_log():
    """Append to APP_DIR/daw2score.log (previous one kept as .old above 2 MB)."""
    global LOG
    try:
        os.makedirs(APP_DIR, exist_ok=True)
        if os.path.exists(LOG_PATH) and os.path.getsize(LOG_PATH) > 2_000_000:
            os.replace(LOG_PATH, LOG_PATH + ".old")
        LOG = open(LOG_PATH, "a", encoding="utf-8", buffering=1)
        LOG.write(f"\n===== daw2score {__version__} {datetime.datetime.now():%Y-%m-%d %H:%M:%S} =====\n")
    except OSError:
        LOG = None
    if sys.stdout is None:  # windowed build: no console
        sys.stdout = LOG or open(os.devnull, "w")
    if sys.stderr is None:
        sys.stderr = LOG or open(os.devnull, "w")


def excepthook(etype, value, tb):
    """An unexpected error in the window itself: logged and shown; the window keeps running."""
    msg = "".join(traceback.format_exception(etype, value, tb))
    log_write(msg)
    try:
        sys.__stderr__.write(msg)
    except (AttributeError, OSError, ValueError):
        pass
    box = QMessageBox(QMessageBox.Critical, "daw2score",
                      T("Erreur inattendue. Détails dans le journal :\n", "Unexpected error. Details in the log:\n")
                      + LOG_PATH + "\n\n" + f"{etype.__name__}: {value}")
    box.setDetailedText(msg)
    box.exec()


def main():
    open_log()
    if FROZEN:  # numba (librosa) cannot cache next to the bundled modules
        os.environ.setdefault("NUMBA_CACHE_DIR", os.path.join(APP_DIR, "numba_cache"))
    if len(sys.argv) > 1 and sys.argv[1] == "--selftest":  # installation check, no window
        import selftest
        sys.exit(0 if selftest.run(sys.argv[2] if len(sys.argv) > 2 else None) else 1)
    sys.excepthook = excepthook
    app = App(sys.argv)
    app.pending = None
    app.setApplicationName("daw2score")
    app.setApplicationVersion(__version__)
    icon = os.path.join(HERE, "assets", "daw2score.ico" if os.name == "nt" else "daw2score.png")
    if os.path.exists(icon):
        app.setWindowIcon(QIcon(icon))
    global LANG
    from PySide6.QtCore import QLocale
    saved = QSettings("daw2score", "daw2score").value("lang")
    LANG = saved if saved in ("en", "fr") else ("fr" if QLocale.system().language() == QLocale.French else "en")
    w = Main()
    app.setProperty("main_window", w)
    w.show()
    start = next((a for a in sys.argv[1:] if not a.startswith("-")), None) or app.pending
    if start:
        w.load(start)
    sys.exit(app.exec())


if __name__ == "__main__":
    import multiprocessing
    multiprocessing.freeze_support()
    main()
