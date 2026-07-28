# CLAUDE.md

Guidance for Claude Code (and other AI assistants) working in this repository.

## What this is

J.A.R.V.I.S. is a single-user, locally-run voice assistant for **Windows desktops**, written in
plain Python with no framework. It listens for a wake word, routes the transcribed command to a
local "skill" if one matches, and otherwise falls back to an LLM. It can also run headless in text
mode or with an optional browser-based holographic HUD.

There is no package manager beyond `pip`, no build step, no test suite, and no linter config. The
whole thing is ~1200 lines across 12 files. Keep it that way — this codebase's value is that a
single person can read all of it.

## Architecture

The data flow is a single funnel, and every entry point converges on one function:

```
voice (Ears) ─┐
text stdin   ─┼─> main.handle_command(command, skills, brain)
UI POST      ─┘         │
                        ├─> SkillDispatcher.handle(cmd) ──> returns str  (local skill matched)
                        └─> Brain.think(cmd)            ──> returns str  (nothing matched)
                                                              │
                                              response str ────┴──> mouth.say(...)
```

`main.py:18` `handle_command` is the contract every input path shares: **one command string in,
one response string out**. If you add an input surface, route it through `handle_command`; do not
reimplement dispatch.

### Modules

| File | Role |
|---|---|
| `main.py` | Entry point, CLI flag parsing, the three run loops (voice / text / UI), shutdown phrases |
| `core/config.py` | Loads `config.json`, writes defaults on first run, backfills missing keys |
| `core/brain.py` | LLM calls — Anthropic, OpenAI, OpenRouter — via raw `requests` |
| `core/memory.py` | Long-term memory: append-only list of facts in a JSON file |
| `core/voice.py` | `Ears` (SpeechRecognition → Google recognizer), `Mouth` (pyttsx3 offline TTS) |
| `core/ui_server.py` | `http.server`-based HUD backend: `GET /`, `GET /state`, `POST /command` |
| `skills/dispatcher.py` | String-matching router — the one place skills get wired up |
| `skills/pc_control.py` | Open/close apps, screenshot, volume keys, web search |
| `skills/files.py` | Filename search, folder organizing, largest-files report |
| `skills/browser.py` | Playwright automation: read page, screenshot page, light research |
| `skills/info.py` | Time, date, weather (wttr.in, no API key) |
| `skills/tools.py` | Reminders (background thread + JSON), system status (psutil) |
| `ui/interface.html` | Self-contained HUD — canvas orb, polls `/state` every 700ms, posts commands |

## Run modes

```bash
python main.py          # voice mode: wake word or push-to-talk
python main.py --ui     # voice mode + HUD, opens http://localhost:8765
python main.py --text   # text-only, no mic — the mode to use when testing
```

Flags are parsed by naive `in sys.argv` checks in `main.py:28`. `--text` swaps the real `Mouth`
for a print-only stub and never imports `core.voice`, which is why text mode works without a
microphone, pyaudio, or a TTS engine.

**Always develop and verify against `--text`.** Voice mode needs Windows, a mic, and SAPI5 voices;
none of that exists in CI or a Linux dev container.

## Setup

```bash
pip install -r requirements.txt
python main.py            # first run writes config.json, then tells you to add a key
# edit config.json -> set your API key
python main.py --text
```

`playwright` is deliberately **not** in `requirements.txt` — browser skills degrade to a friendly
"not installed" string instead of crashing. Install it only if you're touching `skills/browser.py`:

```bash
pip install playwright && playwright install chromium
```

On Windows, `pyaudio` often fails to build: `pip install pipwin && pipwin install pyaudio`.

## Config

`config.json` lives at the repo root, is **gitignored**, and is generated from `DEFAULT_CONFIG` in
`core/config.py:5`. `load_config()` backfills any missing key with its default, so adding a new
setting is safe for existing users — add it to `DEFAULT_CONFIG` and read it with `.get()`.

Never commit `config.json`, never hardcode a key, and never print config values that could contain
one. The three runtime files — `config.json`, `jarvis_memory.json`, `reminders.json` — are all
gitignored.

One key is read but undeclared: `info.weather` does `config.get("city", "")`, and `city` is not in
`DEFAULT_CONFIG`, so it never lands in a generated `config.json` and weather always auto-detects by
IP. Users have to add it by hand. Either add it to `DEFAULT_CONFIG` or leave it — just don't assume
a key exists in `config.json` because some module reads it.

Note that `memory_file` and `REMINDERS_FILE` are **relative paths**, so state lands in the current
working directory. Run the app from the repo root or state will appear to vanish between runs.

## Adding a skill

1. Write a module in `skills/` exposing plain functions that take parsed args and **return a
   string**. No printing, no speaking, no `sys.exit` — the caller owns output.
2. Import it in `skills/dispatcher.py` and add a match branch in `SkillDispatcher.handle`.
3. Return `None` from `handle` for anything you don't own — that `None` is the signal to fall
   through to the LLM. Returning `""` would swallow the command.

Dispatch is **ordered, first-match-wins** string matching over a lowercased command
(`skills/dispatcher.py:22`). Order is load-bearing: broad substring checks placed early will
shadow more specific ones below them. Add narrow patterns above broad ones, and prefer
`cmd.startswith(...)` over `in` when the skill takes an argument.

Slicing conventions in the dispatcher are literal (`command[5:]` for `"open "`, `command[9:]` for
`"research "`), and they index the **original** command, not the lowercased copy, so casing in
arguments is preserved. If you change a trigger prefix, fix the slice length with it.

### Writing responses

Every returned string is spoken aloud. Keep responses to one or two sentences, address the user as
"sir", and avoid characters TTS mangles — no markdown, no bullet lists, no emoji in anything
`Mouth.say` will read. The multi-line listings in `files.py` are an accepted exception because
they're primarily read on screen.

Skills should not raise. Wrap fallible work in `try/except` and return an apologetic string; an
uncaught exception in voice mode is caught by the loop in `main.py:117` but costs the user their
turn. This is the convention for new code, not a property the existing code fully has —
`tools.system_status` catches only `ImportError`, and `pc_control.web_search` and the three
functions in `files.py` have no handler at all. Don't assume a skill is already safe because the
convention says so.

Heavy or platform-specific imports go **inside** the function that needs them (`psutil` in
`tools.py:54` and `ui_server.py:37`, `pyautogui` in `pc_control.py:61`, `pyttsx3` in the reminder
thread at `tools.py:41`, `playwright` in `browser.py:17`) so one broken package degrades one skill
instead of breaking startup. Note that only `playwright` is genuinely optional — `psutil`,
`pyautogui`, and `pyttsx3` are all declared in `requirements.txt`; they're lazy-imported for
startup isolation, not because they're expected to be missing.

## The Brain

`Brain.think` is the LLM fallback. Three providers share one code path; each `_ask_*` method builds
a provider-shaped request with raw `requests` and returns the text. Notable behaviors:

- Session history is capped at the last 20 messages (`core/brain.py:19`); it is not persisted.
- The system prompt is `config["personality"]` plus the last 30 remembered facts, injected fresh
  on every call.
- Any user message containing the word "remember" is appended verbatim to long-term memory
  (`core/brain.py:43`) — a deliberately crude heuristic.
- Network and API failures are swallowed into a spoken apology, so a broken key looks like a
  personality quirk rather than a stack trace. When debugging, check the returned string.

The default model in `DEFAULT_CONFIG` is a Claude model name. If you touch model IDs, don't
guess — check current Anthropic model IDs rather than inventing one, and keep the key readable
from `config.get("model", <fallback>)` so user config always wins.

## The UI server

`core/ui_server.py` runs a single-threaded `HTTPServer` on a daemon thread bound to `127.0.0.1`.
State flows one way: the main loop calls `set_state(...)` at each phase transition, the page polls
`GET /state`, and typed commands come back via `POST /command` into the module-global
`COMMAND_HANDLER`, which `main.py:52` assigns.

Keep it bound to localhost and keep it dependency-free — `http.server` was chosen so the HUD costs
nothing to run. Because the server is single-threaded, a slow `POST /command` blocks `/state`
polling; that's a known and accepted tradeoff, not a bug to "fix" by adding a framework.

`ui/interface.html` is a single self-contained file with inline CSS and JS and no external
requests. It honors `prefers-reduced-motion`. It degrades to a standalone demo animation when the
backend isn't running, so it can be opened directly from disk.

## Safety constraints

These are product invariants, not suggestions. Do not relax them without being asked to:

- **File skills are sandboxed** to `SAFE_ROOTS` in `skills/files.py:13` (Desktop, Documents,
  Downloads, Pictures). Don't widen the roots and don't add a path-from-user-input escape hatch.
- **`organize_folder` moves, never deletes, never overwrites** — collisions get a `_1`, `_2`
  suffix. There is no delete skill; don't add one without an explicit confirmation flow.
- **Browser automation never logs in, never submits personal data, never purchases.** `research`
  reads the first DuckDuckGo result and stops there.
- `pc_control.close_app` shells out to `taskkill /F`. It's already a blunt instrument — don't
  extend it to pattern-matched or bulk kills.

Note that `open_app` and `close_app` interpolate user speech into a shell command / process name.
That's inherent to the feature on a single-user local machine, but it means: don't route remote or
untrusted input into these skills, and don't expose the UI server beyond localhost.

## Platform assumptions

Windows-only paths are load-bearing throughout: `os.system("start ...")` and `taskkill` in
`pc_control.py`, `~/Pictures` as the screenshot destination, SAPI5 voices behind pyttsx3, and
`~/Desktop`-style capitalized folder names in `files.py`. On Linux/macOS, `--text` mode, the brain,
memory, info, and browser skills work; PC control does not. Don't add cross-platform branches
speculatively — the README states Windows.

## Conventions

- Every module opens with a short docstring saying what it does and, where relevant, what it
  refuses to do. Match that.
- Comments explain *why* (`# Never overwrite — append number if name exists`), not *what*. Comment
  density is low; don't inflate it.
- Type hints appear on public function signatures only (`-> str`, `keyword: str`). Internals are
  untyped. Match locally rather than adding annotations everywhere.
- Classes are used for things holding state (`Brain`, `Memory`, `Ears`, `Mouth`,
  `SkillDispatcher`); skills are module-level functions. Don't turn a skill into a class.
- 4-space indent, double quotes, stdlib-first import grouping. No formatter is enforced.
- `SkillDispatcher.try_handle` (`skills/dispatcher.py:15`) is a speak-and-report wrapper that
  nothing currently calls — `main.py` uses `handle` directly. Leave it or remove it deliberately;
  don't accidentally wire new code to it.

## Verifying changes

There are no tests. Verify manually:

```bash
python -m compileall -q core skills main.py     # syntax check, no deps needed
python main.py --text                           # exercise the dispatch path
```

In `--text` mode, type the trigger phrases for whatever you changed and confirm the response
string. To check that a command reaches the LLM fallback rather than being shadowed by a skill,
type something that should *not* match and confirm it hits the brain (or the "trouble reaching my
brain" message when no key is set).

For UI changes: `python main.py --ui --text` is not a supported combination — `--text` returns
before the voice loop, but the server still starts, so the HUD works for typed commands.

## CI

`.github/workflows/semgrep.yml` runs `semgrep ci` on pull requests, pushes touching the workflow
file, a daily schedule, and manual dispatch. It runs on a **self-hosted** runner in the
`semgrep/semgrep` container and needs the `SEMGREP_APP_TOKEN` secret. There is no test, lint, or
build job — Semgrep is the only automated gate, so a security finding is the failure mode to
expect on a PR.

## Git workflow

The default branch is `main`. Work on a feature branch, commit with a descriptive message, push
with `git push -u origin <branch>`, and open a PR. Never commit `config.json`,
`jarvis_memory.json`, `reminders.json`, screenshots, or `__pycache__`.
