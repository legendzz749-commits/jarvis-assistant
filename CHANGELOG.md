# Changelog

## 2026-09-25 — Audit fixes, part 2

Every remaining medium- and low-severity finding from the audit, fixed the same
way as part 1: reproduced against the real code first, with a regression test
that fails on the old code and passes on the new (239 tests in total).

### 🔒 Privacy and safety

- The phone mic is no longer streamed while JARVIS is asleep.
- `config/api_keys.json` and the memory file are written owner-only (0600).
- Generated passwords are no longer printed to the log.
- Phone uploads no longer broadcast your local folder path (it names your OS
  user). Linux screenshots go to `~/Pictures` instead of the repository, and
  `.gitignore` also covers `uploads/`, stray screenshots and `.env`.
- Typing and pasting give your clipboard back afterwards.

### 🗣️ Conversation

- Tool calls run off the receive loop, so a slow tool no longer freezes the
  conversation.
- "Goodbye" is spoken in full before JARVIS exits. The session summary is saved
  afterwards, with a time limit.
- A tail of an answer re-sent after a tool call is no longer logged or mouthed
  twice. Repeated phrases inside an answer are no longer dropped.
- A voice change made while connecting is applied. Plugin toggles take effect
  in the running session.
- Quiz results survive sleep and reconnects. A missing microphone no longer
  ends the session.

### 🧠 Memory

- Reads and writes are atomic and locked, so concurrent saves no longer lose
  facts.
- Recall ignores accents ("Ayşe" finds `ayse_sister`). Only the latest session
  recap is replayed.
- Facts saved under any category reach the prompt. The prompt block stays
  within its budget however much you store.

### 🖥️ HUD

- A live recolour reaches every painted part: the CPU bar, the drop zone and
  an open document review. It also never overwrites the fixed status colours.
- Fixes to panels and the activity log:
  - Customise and Plugin Manager no longer leak widgets.
  - The plugin list scrolls, so CLOSE stays on screen.
  - The activity log no longer steals your scroll or selection, and colours
    lines correctly.
- Fixes to the file drop zone:
  - Clearing a file resets its hint.
  - Browse lists files that have no extension.
- The avatar's brows move with a slow asymmetry. Lip-sync is thread-safe, and
  ligatures and fullwidth text now reach the mouth.

### 🧰 Tools

- **Computer control:**
  - Actions that did nothing no longer report "Done".
  - Restart and shutdown wait the promised 10 seconds on every OS.
  - Snap left and right use the real screen size.
- **Desktop:**
  - Wallpaper failures are reported.
  - It uses the current KDE Plasma 6 and XFCE multi-monitor commands.
  - Generated desktop code can use everyday Python built-ins.
- **Files:**
  - Word and PowerPoint tables are read.
  - "Created" dates are no longer invented on Linux.
- **Open app:** localized app names are pasted, not typed with their letters
  dropped.
- **System monitor:**
  - An NVML failure reads as "unavailable", not 0 % GPU.
  - Windows CPU temperature no longer fails on worker threads (COM is
    initialised first).
- **Code helper:**
  - `~` paths are expanded.
  - "Build" can start from an existing file, working on a `.fixed` copy.
- **Phone dashboard:**
  - Malformed requests no longer crash handlers.
  - One bad message no longer ends the session.
  - Each upload shows one card, with no replayed toasts.

### 📦 Setup

- `setup.py` reaches its version message on Python 3.8, and stops with a
  sentence when `pip install .` tries to build it.
- It checks pywin32 correctly on a first install.
- `nvidia-ml-py` replaces the deprecated `pynvml` package.
- The README names the right packages for `win32com`, `cv2` and `PIL`.

### Known issues still open

- Four areas were not reviewed:
  - the `ui.py` settings overlays
  - the plugin and config loaders
  - browser control
  - the cross-module check
- `core/llm_client.py`, `core/stt.py`, `core/tts.py` and `core/installer.py`
  are unused leftovers from an older version. They were left in place, not
  deleted.

## 2026-09-25 — Audit fixes

A line-by-line audit of the assistant. Every fix below was reproduced first
against the real code, and each one has a regression test in `tests/` that
fails on the old code and passes on the new.

Run the tests with:

```bash
QT_QPA_PLATFORM=offscreen python -m pytest tests
```

### 🔒 Your data

- **Secrets were not git-ignored.** `config/api_keys.json` (your Gemini key),
  `config/certs/` (the dashboard's TLS private key) and `memory/long_term.json`
  are now in `.gitignore`, as the README already claimed. None of them had been
  committed.
- **Re-entering a rejected API key wiped every other setting** — names, voice,
  colour, wake word and plugin credentials. It now changes only the key.
- **A damaged memory file was erased on the next save.** It is now kept aside
  as `long_term.corrupt-<time>.json` and you are told. Saves are atomic, so a
  crash or full disk can no longer leave a half-written file.
- **Moving or copying a file overwrote one with the same name**, and undo could
  not bring it back (undoing a copy even deleted your file). Both now refuse to
  overwrite.
- **Undo corrupted non-text files** (images, Office files, non-UTF-8 text,
  Windows line endings). It now restores the exact bytes.
- **Code helper could destroy source files:** "optimize" wrote back only the
  first 6000 characters, and "screen debug" could write the quoted error over
  your file. Long files are now refused, fixes are saved next to the file as
  `name.fixed.ext`, and every code helper write can be undone.

### 🛡️ Security

- **Archives:** a crafted `.tar` could write files outside the extract folder
  (for example over `~/.bashrc`).
- **Dev agent:** could write files outside its project folder, pass options to
  pip through its dependency list, and run any command. Paths are now contained,
  only real package names are installed, and only Python/Node entry points run.
- **Desktop tasks** ran model-written code in-process with an escapable
  sandbox. The code is now shown on the HUD and runs only after you press
  CONFIRM.
- **Phone dashboard:** anyone on your network could fill your disk through the
  upload endpoint before being authenticated. Authentication and the size limit
  now come first.
- **Windows firewall helper** switched every Public network (café, airport) to
  Private and opened `python.exe` on all ports. It now opens only the dashboard
  port, and only to the local subnet on private networks.

### 🐞 Crashes and broken features

- **App crashes:**
  - A dropped file that was later moved or deleted crashed the app.
  - A busy dashboard port shut down the voice assistant.
  - Pairing a phone updated the UI from the wrong thread.
- **Push-to-talk:**
  - When saved ON, the microphone stayed closed after a restart on macOS/Linux.
  - On macOS the chord became ⌘Space, which Spotlight owns. It is now the
    physical Control key.
- **Wake word:**
  - It re-triggered itself right after going to sleep.
  - The one-click install was broken on Linux with Python 3.12/3.13.
- **Conversation:**
  - A stray Esc silently swallowed your next reply.
  - One failed screenshot or camera capture blocked vision for the rest of the
    session.
  - The conversation was thrown away on the second reconnect.
- **Linux startup:** without tkinter the assistant silently never started.
  `setup.py` now names the missing system libraries (Tk, PortAudio,
  xcb-cursor) with the install command for apt, dnf and pacman.
- **Game updater:**
  - Scheduled daily updates crashed on every run.
  - "Update Fortnite" installed an unrelated Steam game.
  - Updating Epic games launched up to ten of them.
- **Reminders:**
  - Two reminders set for the same minute overwrote each other.
  - On Windows with Python 3.12+ they beeped with no text.
- **Computer control:**
  - Windows volume never changed with the current pycaw.
  - "Unmute" muted on macOS.
  - Zoom, tab switching and show-desktop shortcuts did nothing (or typed a
    letter).
  - Typing failed on Linux without a clipboard tool.
- **Files and media:**
  - Image OCR/describe answered without seeing the image.
  - Audio and video transcription always failed.
  - Every CSV/TSV action failed.
  - YouTube summaries always failed with the current youtube-transcript-api.
- **Messaging:** "Signal" messages were sent through Instagram.
