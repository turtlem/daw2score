# Third-party components

daw2score itself is MIT-licensed (see `LICENSE`). The Windows installer and the macOS app bundle the components
below, unmodified. Their full license texts are installed with the app, in a `licenses` folder linked from the *?*
dialog (`_internal\licenses` on Windows, `daw2score.app/Contents/Resources/licenses` on macOS): one folder per
Python package, plus `alphaTab`, `Node.js`, `LGPL-3.0.txt` and `GPL-3.0.txt`.

| Component | Use | License |
|---|---|---|
| Python 3.11 | runtime | PSF-2.0 |
| Qt 6 / PySide6-Essentials, shiboken6 | window | LGPL-3.0 (dynamically linked, the DLLs can be replaced) |
| alphaTab (`@coderline/alphatab`) | GP5 → Guitar Pro 7/8 conversion | MPL-2.0 |
| Node.js | runs alphaTab | MIT (+ bundled components, see its LICENSE) |
| basic-pitch (Spotify) | audio → notes transcription | Apache-2.0 |
| ONNX Runtime | runs the basic-pitch model | MIT |
| librosa, resampy | audio analysis | ISC |
| NumPy, SciPy, scikit-learn, numba, llvmlite | numerics | BSD-3-Clause / BSD-2-Clause |
| PyGuitarPro | Guitar Pro 5 writing | LGPL-3.0 |
| lxml (libxml2, libxslt) | XML | BSD-3-Clause / MIT |
| soundfile (libsndfile, LAME, mpg123) | audio files, MP3 | BSD-3-Clause / LGPL-2.1 |
| soxr (libsoxr) | resampling | LGPL-2.1 |
| mido, pretty_midi, mir_eval | MIDI | MIT |

The LGPL libraries are used as separate, replaceable shared libraries / Python packages; their sources are
available from their upstream projects (qt.io, pypi.org/project/PySide6-Essentials, github.com/Perlence/PyGuitarPro,
github.com/libsndfile/libsndfile, github.com/chirlu/soxr).
