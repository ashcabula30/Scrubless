<p align="center">
  <img src="footage_finder/icon.png" alt="Scrubless" width="150" />
</p>

# Scrubless

[![Runs](https://img.shields.io/badge/RUNS-100%25%20LOCAL-2D9D78?style=for-the-badge&labelColor=555555)](#-privacy) [![GPU](https://img.shields.io/badge/GPU-NVIDIA%20CUDA-76B900?style=for-the-badge&logo=nvidia&logoColor=white&labelColor=555555)](#-system-requirements) [![Editor](https://img.shields.io/badge/EDITOR-PREMIERE%20PRO-9999FF?style=for-the-badge&logo=adobepremierepro&logoColor=white&labelColor=555555)](#-brief--rough-cut) [![Platform](https://img.shields.io/badge/PLATFORM-WINDOWS-0078D6?style=for-the-badge&logo=windows11&logoColor=white&labelColor=555555)](#-getting-started) [![Version](https://img.shields.io/badge/VERSION-0.8.0-1473E6?style=for-the-badge&labelColor=555555)](#-roadmap)

> Stop scrubbing through footage. Scrubless listens to and watches every clip once, on your own GPU, then finds the exact take where a line is said or a shot appears, in under a second. Paste a brief, pick your takes, and get a Premiere rough cut.

---

## ✨ Features Highlight

- 🗣️ **Find any spoken line:** Type a line from the script and get every take of it, with clip and timecode,
  even when the creator paraphrased it ("can't stop drinking it" finds "I literally cannot stop drinking this"). Repeated takes inside one clip come
  back as separate takes.
- 👁️ **Find any shot by description:** "Dog running on the beach", "hand pouring tea, close-up". An image
  model looks at every shot, so b-roll is searchable by what's on screen.
- 📋 **Brief → Rough cut:** Import the brief from a **ClickUp** task in one click, paste the table, or paste
  a **screenshot** of it (Script, Visual and On-screen text columns). Every line gets its best takes and b-roll; click to swap picks, then build a Premiere sequence with takes on
  V1/A1, b-roll on V2 and a marker on every line listing the backup takes.
- ⚡ **Instant search:** Models stay loaded in the background, so searches take ~0.1–0.5 s. Previews of
  iPhone HEVC clips are cut to small H.264 clips on the GPU and play right in the app.
- 🎞️ **Premiere panel:** Search from inside Premiere (*Window › Extensions › Scrubless*). **Source** opens
  a take in the Source Monitor with in/out set; **Place** drops it at the playhead on an empty track.
- 📚 **Library & background indexing:** Add a folder (or drag it onto the window) and it indexes with a
  progress bar. Stop any time; Update only processes new files. Exports, finals, renders and Premiere
  preview folders are skipped, so finished edits don't show up as takes.
- ☁️ **Backblaze B2 and Iconik sources:** Index a shoot straight from a B2 bucket or an Iconik collection.
  Clips (Iconik: small proxies) stream down one at a time, get indexed and deleted; only the clips you pick
  are downloaded for keeps, at full quality.
- 🔒 **Private by design:** Everything runs on your PC. No subscription, no cloud AI, footage never leaves
  the machine.

---

## 🛠️ The Technology Stack

Built from proven open-source models and libraries, tuned to run fast on a consumer NVIDIA GPU.

- **Desktop Shell:** [pywebview](https://pywebview.flowrl.com/) (Edge WebView2) + a native C# launcher
  (`Scrubless.exe`)
- **Interface:** [React](https://react.dev/) + [TypeScript](https://www.typescriptlang.org/), bundled with
  [Vite](https://vite.dev/)
- **Local API:** [FastAPI](https://fastapi.tiangolo.com/) + [Uvicorn](https://www.uvicorn.org/) on
  `127.0.0.1` (reachable only from this PC)
- **Speech-to-Text:** [Whisper large-v3](https://github.com/openai/whisper) via
  [faster-whisper](https://github.com/SYSTRAN/faster-whisper) (CTranslate2, word-level timestamps)
- **Meaning Search:** [BGE](https://huggingface.co/BAAI/bge-large-en-v1.5) embeddings via
  [sentence-transformers](https://www.sbert.net/) + [RapidFuzz](https://github.com/rapidfuzz/RapidFuzz)
- **Visual Search:** [SigLIP 2](https://huggingface.co/google/siglip2-so400m-patch14-384) via
  [Transformers](https://huggingface.co/docs/transformers) + [PyTorch](https://pytorch.org/) (CUDA 12.8)
- **Brief Screenshots:** [RapidOCR](https://github.com/RapidAI/RapidOCR) (ONNX Runtime) +
  [OpenCV](https://opencv.org/) table detection
- **Video Pipeline:** [FFmpeg](https://ffmpeg.org/) (NVDEC keyframe decoding + GPU scaling, NVENC previews)
- **Storage:** [SQLite](https://sqlite.org/) index per footage folder
- **Cloud Sources:** [b2sdk](https://github.com/Backblaze/b2-sdk-python) (Backblaze B2) · Iconik REST API
- **Briefs:** ClickUp REST API (personal token; reads the task's brief table)
- **Premiere Panel:** CEP extension (HTML + ExtendScript) calling the same local API
- **Rough Cuts:** Final Cut Pro 7 XML, imported natively by Premiere Pro
- **Packaging:** [uv](https://docs.astral.sh/uv/) (Python 3.12 environment) +
  [Inno Setup](https://jrsoftware.org/isinfo.php) installer

---

## 🖥️ System Requirements

| Preset | Speech | Meaning search | Visual | For |
|---|---|---|---|---|
| **High** | Whisper large-v3 | bge-large | SigLIP 2 so400m, up to 2 frames/s | NVIDIA GPU with 12 GB+ (e.g. RTX 5070 Ti) |
| **Mid** | Whisper large-v3-turbo | bge-base | SigLIP 2 base, 1 frame/s | NVIDIA GPU with 6–8 GB |
| **Low** | Whisper small (CPU) | bge-small | SigLIP 2 base, 0.5 frames/s | Any PC with 8 GB RAM |

`Automatic` picks the preset from your GPU. Also needed: Windows 10/11, [FFmpeg](https://ffmpeg.org/) on PATH,
~15 GB of disk for Python, libraries and models.

**Speed (High, RTX 5070 Ti):** 6 min of 4K iPhone footage (27 clips) indexed in **29 s** (was 69 s before
0.8). Frames are sampled at keyframes (iPhone: about one a second) so the GPU decodes only those, image
preprocessing runs on the GPU, and the speech and visual passes of each clip run at the same time.

---

## 🚀 Getting Started

1. Run **`Scrubless Setup <version>.exe`** (per user, no admin). Pick a data folder on an internal drive.
2. Open **Scrubless**. The first launch on a new PC offers a one-time setup (Python + AI libraries, ~4 GB).
3. **Library →** add a footage folder (Browse, paste a path, or drag it onto the window).
4. **Search →** type a line or describe a shot. Click a result to preview it; **Show in Explorer** or
   **Copy path + time** to use it.
5. **Premiere →** restart Premiere once after installing, then open *Window › Extensions › Scrubless*. Keep
   the Scrubless app open: the panel searches through it.

Uninstall from Windows *Installed apps*. The data folder (models + search data) is kept so a reinstall is quick.

---

## 🎬 Brief → Rough Cut

1. **From ClickUp** (paste the task link, or pick one of your tasks in an editing status; a Video Editing
   subtask reads the brief from its parent). Or copy the brief table (**Section | Script | Visual | On-screen
   text**) and press <kbd>Ctrl</kbd>+<kbd>V</kbd> on the Brief page, or paste / drop a screenshot of it.
   You can also type in the table.
2. **Find takes →**. Script cells are split into sentences, each script paragraph is paired with the visual
   paragraph beside it, `{placeholders}` are ignored, and On-screen text becomes a note in the marker (it is
   not searched).
3. Click the take and b-roll you want for each line (green = in the cut).
4. Choose size (9:16, 4:5, 1:1, 16:9) and folder, then **Build rough cut**. In Premiere: *File › Import* the `.xml`.

Lines nobody said become a gap with a `MISSING` marker (needs VO, new footage, or a manual pick).

---

## 🧑‍💻 Development

```powershell
winget install astral-sh.uv
$env:UV_PROJECT_ENVIRONMENT = "D:\footage-finder-data\venv"   # keep the big environment off C:
uv sync --python 3.12                                         # Python 3.12 + CUDA 12.8 PyTorch
cd ui; npm install; npm run build; cd ..                      # UI -> footage_finder/static
.\footage.cmd app                                             # run the app from source
```

**Command line** (`footage.cmd <command>`):

```text
footage index "<folder or b2://bucket/folder/>"   # index; re-run adds new files
footage find "I can't stop drinking this tea"    # where is this line said?
footage scene "hand pouring tea" --sheet x.jpg   # where is this shot? (+ contact sheet)
footage brief brief.txt                          # every line and visual in a brief
footage roughcut brief.txt --out cut.xml         # Premiere sequence from a brief
footage serve                                    # API + UI on 127.0.0.1:7792
footage doctor                                   # GPU, preset, Backblaze key
```

**Release:** bump `AppVersion` in `installer/Scrubless.iss`, then run `installer/build-installer.ps1`
(builds the UI, the launcher and `installer/build/Scrubless Setup <version>.exe`).

**Connections** (all in Settings, stored in the data folder): ClickUp personal token (`clickup.json`),
Iconik App ID + Auth Token (`iconik.json`), Backblaze key (`backblaze.json`).

**Premiere panel:** lives in `footage_finder/panel/`; the installer copies it to
`%APPDATA%\Adobe\CEP\extensions\com.goodostudios.scrubless`. It is unsigned, so Premiere must allow
unsigned panels (`PlayerDebugMode` = `1` under `HKCU\Software\Adobe\CSXS.11` and `CSXS.12`). Open
`http://127.0.0.1:7792/panel/` in a browser to test its search without Premiere.

**Backblaze:** put a **read-only** application key in `<data folder>\backblaze.json`
(`{"key_id": "...", "application_key": "..."}`) or the Settings page. Set `FF_B2_FAKE_ROOT` to a local
folder to test without a bucket.

<details>
<summary><b>Gotchas found while building</b></summary>

- Python 3.14 is too new for the AI libraries; the project pins 3.12.
- RTX 50-series (Blackwell) needs PyTorch built for CUDA 12.8 (`pytorch-cu128` index in `pyproject.toml`).
- PyAV 19 broke faster-whisper's file reader, so audio is decoded with FFmpeg instead.
- transformers 5 returns an output object from `get_image_features`; handled in `visual.py`.
- Never run the uv setup from inside the installer: Windows restricts processes an installer starts and uv's
  Python junction fails ("untrusted mount point", os error 448). The launcher starts setup through Explorer.
- Rough cuts count the timeline in whole frames; rounding start and length separately caused 1-frame overlaps.
- ffmpeg's `-skip_frame nokey` is ignored with plain `-hwaccel cuda` output and duplicates frames unless
  `-fps_mode passthrough` is set; keyframe sampling needs `-hwaccel_output_format cuda` + `scale_cuda`.
- Whisper's batched mode was barely faster on short phone clips and dropped repeated words, so it's off.
- Synology Drive "online-only" placeholders download in full when read; don't index them wholesale on a small C:.
- Called *Footage Finder* up to v0.3.1; internal names (`footage_finder`, `footage`, `footage-finder-data`) kept it.

</details>

---

## 📁 Project Structure

```text
footage_finder/      Python engine, API server and app window
  indexer.py         transcription + frame sampling per file
  search.py          spoken-line search, brief parsing
  visual.py          SigLIP shot search, contact sheets
  roughcut.py        Premiere XML rough cuts
  ocr.py             brief table from a screenshot
  clickup.py         brief import from ClickUp tasks
  iconik.py · sources.py  Iconik, Backblaze and local sources
  panel/             Premiere Pro panel (CEP)
  server.py · app.py local API · desktop window
ui/                  React + TypeScript interface (built into footage_finder/static)
installer/           C# launcher, setup script, Inno Setup installer
```

---

## 🗺️ Roadmap

- [x] Spoken-line search · visual shot search · Premiere rough cuts
- [x] Desktop app with installer · ClickUp brief table + screenshot reading
- [x] Backblaze B2 source (tested against a simulated bucket; live test pending)
- [x] Iconik source · ClickUp brief import · On-screen text column
- [x] Skip exports/output folders when indexing
- [x] Scrubless panel inside Premiere Pro (same local API)
- [x] 2.4× faster indexing (keyframe sampling, GPU preprocessing, parallel passes)
- [ ] Synology Drive: index online-only folders one file at a time
- [ ] Mac build

---

## 🔒 Privacy

Scrubless never uploads footage, audio or briefs. Models run on your GPU/CPU; the internet is only used to
download the libraries and models once, and to fetch clips and briefs from services you connect (Backblaze, Iconik, ClickUp).
