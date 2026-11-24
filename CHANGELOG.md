# Changelog

Versions follow `MAJOR.MINOR.PATCH` (semantic versioning; 0.x while the project is young).

## 0.2.0 — 2026-11-25

First release with installers: Windows (setup.exe) and macOS (Apple Silicon and Intel .dmg).

- Export window (English / French): tracks and roles, merged tracks, tempo (project, typed, detected), sections
  (markers, typed, proposed automatically), output formats, Guitar Pro 8 audio track; settings remembered per project.
- Windows installer (no administrator rights needed) and macOS app, bundling Python, the transcription models
  and Node.js; built and self-tested on GitHub Actions.
- REAPER action script that opens the window on the current project.
- About dialog with the version, licenses, log file and an update check against the GitHub releases.
- Log file and error dialog; `--selftest` installation check.
- Automatic section proposal (`sections.py`).
- Track roles override the name guessing (transcription profile and score instrument).

## 0.1.0

Command-line tools: REAPER, DAWproject and stems + MIDI folders to Guitar Pro 7/8 `.gp`, `.gp5` and MusicXML;
audio transcription (basic-pitch), multitrack drums, chord detection, bass cleanup, embedded audio track.
