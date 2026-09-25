#desktop.py
import os
import sys
import json
import shutil
import subprocess
import tempfile
import platform
from pathlib import Path
from datetime import datetime
from types import SimpleNamespace

from core.undo import push_undo

try:
    import pyautogui
    _PYAUTOGUI = True
except ImportError:
    _PYAUTOGUI = False

_OS = platform.system()  # "Windows" | "Darwin" | "Linux"


def _get_base_dir() -> Path:
    if getattr(sys, "frozen", False):
        return Path(sys.executable).parent
    return Path(__file__).resolve().parent.parent

def _get_api_key() -> str:
    path = _get_base_dir() / "config" / "api_keys.json"
    with open(path, "r", encoding="utf-8") as f:
        return json.load(f)["gemini_api_key"]
    
def _get_desktop() -> Path:
    from actions.file_controller import _known_folder   # user-dirs.dirs / OneDrive aware
    return _known_folder("Desktop")

def _build_sandbox() -> dict:
    import time

    safe_builtins = {
        "print": print,
        "len": len, "str": str, "int": int, "float": float,
        "bool": bool, "list": list, "dict": dict, "tuple": tuple,
        "range": range, "enumerate": enumerate, "sorted": sorted,
        "isinstance": isinstance, "hasattr": hasattr, "getattr": getattr,
        "max": max, "min": min, "sum": sum, "abs": abs,
        "zip": zip, "map": map, "filter": filter,
    }

    sandbox = {
        "__builtins__": safe_builtins,
        "Path": Path,
        "time": time,
        # A class instance would bind these as methods (self = first arg).
        "shutil": SimpleNamespace(copy2=shutil.copy2, copytree=shutil.copytree,
                                  disk_usage=shutil.disk_usage),
        "os_path": os.path,  
    }

    if _PYAUTOGUI:
        sandbox["pyautogui"] = pyautogui

    if _OS == "Windows":
        try:
            import ctypes
            import winreg
            sandbox["ctypes"] = ctypes
            sandbox["winreg"] = type("winreg", (), {
                # Sadece okuma
                "OpenKey":      winreg.OpenKey,
                "QueryValueEx": winreg.QueryValueEx,
                "HKEY_CURRENT_USER": winreg.HKEY_CURRENT_USER,
            })()
        except ImportError:
            pass

    return sandbox


def _confirm_and_execute(task: str, code: str, player=None) -> str:
    """Model-written code cannot be sandboxed in-process — os is reachable
    through os.path and Path can delete — so it only runs after the user reads
    it on the HUD and presses CONFIRM."""
    if code.startswith("ERROR:"):
        # A failed Gemini call, not code — it used to be exec'd and reported
        # as "invalid syntax".
        return f"Could not work out how to do that: {code[6:].strip()}"
    if code.strip() == "UNSAFE":
        return "That desktop task cannot be done safely with the tools I have."
    from core import confirm
    if confirm.pending_title():
        return ("There is already a confirmation waiting on screen. "
                "Ask the user to answer that one first.")
    preview = "\n".join(code.strip().splitlines()[:12])
    return confirm.request(
        key="desktop_task", title=f"Run desktop task: {task[:80]}", detail=preview,
        run=lambda: _execute_generated_code(code, player=player),
    )


def _execute_generated_code(code: str, player=None) -> str:
    if not code or code.strip() == "UNSAFE":
        return "This action cannot be performed safely."

    # Kod temizleme
    if code.startswith("```"):
        lines = code.split("\n")
        code  = "\n".join(lines[1:-1]).strip()

    sandbox      = _build_sandbox()
    output_lines = []
    sandbox["__builtins__"]["print"] = lambda *a: output_lines.append(" ".join(str(x) for x in a))

    try:
        exec(compile(code, "<jarvis_desktop>", "exec"), sandbox)
        return "\n".join(output_lines) if output_lines else "Done."
    except Exception as e:
        print(f"[Desktop] Exec error: {e}\nCode:\n{code[:300]}")
        return f"Execution error: {e}"


def _ask_gemini_for_desktop_action(task: str) -> str:

    from google import genai as _genai

    desktop = str(_get_desktop())

    os_specific = ""
    if _OS == "Windows":
        os_specific = "- ctypes (Windows API calls, read-only)\n- winreg (registry READ only)"
    elif _OS == "Darwin":
        os_specific = "- subprocess is NOT available; use pyautogui or Path only"
    else:
        os_specific = "- subprocess is NOT available; use pyautogui or Path only"

    prompt = f"""You are a desktop automation assistant.
Current OS: {_OS}
Desktop path: {desktop}

Generate safe Python code to accomplish the task below.
Allowed modules ONLY:
- pyautogui (mouse, keyboard — if needed)
- pathlib.Path (file/folder inspection only, no deletion)
- shutil.copy2, shutil.copytree, shutil.disk_usage (NO move, NO rmtree)
- os_path (os.path equivalent, read-only)
- time.sleep
{os_specific}

Hard rules:
- NO file deletion (no unlink, no rmtree, no remove)
- NO subprocess calls
- NO exec() or eval() inside the code
- NO import statements (modules are pre-injected)
- NO file write operations except explicitly requested
- If task cannot be done safely with these tools, output exactly: UNSAFE

Output ONLY the Python code. No explanation, no markdown, no backticks.

Task: {task}"""

    try:
        from core import gemini
        response = gemini.call(prompt, tier=gemini.SMART, timeout_ms=30_000)
        if response is None:
            return "ERROR: every Gemini model on the ladder failed"
        code = (response.text or "").strip()
        if code.startswith("```"):
            lines = code.split("\n")
            code  = "\n".join(lines[1:-1]).strip()
        return code
    except Exception as e:
        return f"ERROR: {e}"

def set_wallpaper(image_path: str) -> str:
    path = Path(image_path).expanduser().resolve()
    if not path.exists():
        return f"Image not found: {image_path}"
    if path.suffix.lower() not in {".jpg", ".jpeg", ".png", ".bmp", ".webp"}:
        return f"Unsupported format: {path.suffix}. Use jpg, png, bmp or webp."

    try:
        if _OS == "Windows":
            import ctypes
            if path.suffix.lower() in {".webp", ".png"}:
                try:
                    from PIL import Image
                    bmp_path = Path(tempfile.mktemp(suffix=".bmp"))
                    Image.open(path).convert("RGB").save(bmp_path, "BMP")
                    path = bmp_path
                except ImportError:
                    pass 
            ctypes.windll.user32.SystemParametersInfoW(20, 0, str(path), 3)
            return f"Wallpaper set: {path.name}"

        elif _OS == "Darwin":
            script = (
                f'tell application "System Events" to tell every desktop to '
                f'set picture to POSIX file "{path}"'
            )
            subprocess.run(["osascript", "-e", script], capture_output=True)
            return f"Wallpaper set: {path.name}"

        else:
            desktop_env = os.environ.get("XDG_CURRENT_DESKTOP", "").lower()
            uri = f"file://{path}"

            if "gnome" in desktop_env or "unity" in desktop_env:
                subprocess.run([
                    "gsettings", "set", "org.gnome.desktop.background",
                    "picture-uri", uri
                ], capture_output=True)
                subprocess.run([
                    "gsettings", "set", "org.gnome.desktop.background",
                    "picture-uri-dark", uri
                ], capture_output=True)

            elif "kde" in desktop_env:
                # KDE Plasma
                script = f"""
var allDesktops = desktops();
for (var i = 0; i < allDesktops.length; i++) {{
    d = allDesktops[i];
    d.wallpaperPlugin = "org.kde.image";
    d.currentConfigGroup = ["Wallpaper", "org.kde.image", "General"];
    d.writeConfig("Image", "file://{path}");
}}
"""
                subprocess.run(
                    ["qdbus", "org.kde.plasmashell", "/PlasmaShell",
                     "org.kde.PlasmaShell.evaluateScript", script],
                    capture_output=True
                )

            elif "xfce" in desktop_env:
                subprocess.run([
                    "xfconf-query", "-c", "xfce4-desktop",
                    "-p", "/backdrop/screen0/monitor0/workspace0/last-image",
                    "-s", str(path)
                ], capture_output=True)

            else:
                result = subprocess.run(
                    ["feh", "--bg-scale", str(path)],
                    capture_output=True
                )
                if result.returncode != 0:
                    return (
                        f"Could not set wallpaper automatically on {desktop_env}. "
                        f"Try manually or install 'feh'."
                    )

            return f"Wallpaper set: {path.name}"

    except Exception as e:
        return f"Could not set wallpaper: {e}"


def set_wallpaper_from_url(url: str) -> str:
    try:
        import hashlib
        import urllib.request
        if not url.lower().startswith(("http://", "https://")):
            return "Only http(s) image links can be used as a wallpaper."
        suffix = Path(url.split("?")[0]).suffix.lower() or ".jpg"
        # Kept, not deleted: the OS reads the wallpaper file again later (on
        # login, on a display change), so deleting it blanks the desktop.
        folder = Path.home() / "Pictures" / "JARVIS Wallpapers"
        folder.mkdir(parents=True, exist_ok=True)
        dest = folder / (hashlib.sha1(url.encode()).hexdigest()[:16] + suffix)
        # A timeout and a size cap: this runs inside a voice tool call.
        with urllib.request.urlopen(url, timeout=15) as resp:
            data = resp.read(_WALLPAPER_MAX_BYTES + 1)
        if len(data) > _WALLPAPER_MAX_BYTES:
            return "That image is too large to use as a wallpaper (over 25 MB)."
        dest.write_bytes(data)
        return set_wallpaper(str(dest))
    except Exception as e:
        return f"Could not download wallpaper: {e}"


def get_current_wallpaper() -> str:
    try:
        if _OS == "Windows":
            import winreg
            key = winreg.OpenKey(
                winreg.HKEY_CURRENT_USER, r"Control Panel\Desktop"
            )
            val, _ = winreg.QueryValueEx(key, "Wallpaper")
            winreg.CloseKey(key)
            return f"Current wallpaper: {val}"

        elif _OS == "Darwin":
            script = (
                'tell application "System Events" to get picture of desktop 1'
            )
            result = subprocess.run(
                ["osascript", "-e", script],
                capture_output=True, text=True
            )
            return f"Current wallpaper: {result.stdout.strip()}"

        else:
            desktop_env = os.environ.get("XDG_CURRENT_DESKTOP", "").lower()
            if "gnome" in desktop_env or "unity" in desktop_env:
                result = subprocess.run(
                    ["gsettings", "get", "org.gnome.desktop.background", "picture-uri"],
                    capture_output=True, text=True
                )
                return f"Current wallpaper: {result.stdout.strip()}"
            return "Wallpaper path retrieval not supported for this desktop environment."

    except Exception as e:
        return f"Could not get wallpaper: {e}"

FILE_TYPE_MAP = {
    "Images":      {".jpg", ".jpeg", ".png", ".gif", ".bmp", ".webp", ".svg", ".ico", ".heic"},
    "Documents":   {".pdf", ".doc", ".docx", ".txt", ".xls", ".xlsx",
                    ".ppt", ".pptx", ".csv", ".odt", ".ods", ".odp"},
    "Videos":      {".mp4", ".avi", ".mkv", ".mov", ".wmv", ".flv", ".webm", ".m4v"},
    "Music":       {".mp3", ".wav", ".flac", ".aac", ".ogg", ".wma", ".m4a"},
    "Archives":    {".zip", ".rar", ".7z", ".tar", ".gz", ".bz2", ".xz"},
    "Code":        {".py", ".js", ".ts", ".html", ".css", ".json", ".xml",
                    ".cpp", ".java", ".cs", ".go", ".rs", ".sh", ".php"},
    "Executables": {".exe", ".msi", ".bat", ".cmd", ".sh", ".appimage", ".deb", ".rpm"},
}

_SKIP_EXTENSIONS = {
    "Windows": {".lnk", ".url", ".ini"},   # desktop.ini is a hidden system file
    "Darwin":  {".webloc"},
    "Linux":   {".desktop"},
}


_WALLPAPER_MAX_BYTES = 25 * 1024 * 1024


def _move_journaled(item: Path, new_path: Path, journal: list, failed: list) -> bool:
    """One move of a bulk operation: a failure is recorded, not fatal."""
    try:
        shutil.move(str(item), str(new_path))
    except OSError as e:
        print(f"[Desktop] Could not move {item.name}: {e}")
        failed.append(item.name)
        return False
    journal.append((item, new_path))
    return True


def _push_bulk_undo(label: str, journal: list, created: set) -> None:
    """One undo that puts every file back and removes folders it made (if empty)."""
    if not journal:
        return

    def _undo():
        restored = 0
        for src, dst in journal:
            if dst.exists() and not src.exists():
                shutil.move(str(dst), str(src))
                restored += 1
        for folder in created:
            try:
                if folder.is_dir() and not any(folder.iterdir()):
                    folder.rmdir()
            except OSError:
                pass
        return f"{restored} file(s) put back on the desktop."
    push_undo(label, _undo)


def organize_desktop(mode: str = "by_type") -> str:
    desktop       = _get_desktop()
    skip_exts     = _SKIP_EXTENSIONS.get(_OS, set())
    moved, skipped, failed = [], [], []
    journal: list = []
    created: set = set()

    for item in desktop.iterdir():
        if item.is_dir() or item.name.startswith("."):
            continue
        if item.suffix.lower() in skip_exts:
            continue

        if mode == "by_date":
            mtime       = datetime.fromtimestamp(item.stat().st_mtime)
            folder_name = mtime.strftime("%Y-%m")
        else:
            ext         = item.suffix.lower()
            folder_name = "Others"
            for folder, exts in FILE_TYPE_MAP.items():
                if ext in exts:
                    folder_name = folder
                    break

        target_dir = desktop / folder_name
        if not target_dir.exists():
            target_dir.mkdir()
            created.add(target_dir)
        new_path = target_dir / item.name

        if new_path.exists():
            skipped.append(item.name)
            continue

        if _move_journaled(item, new_path, journal, failed):
            moved.append(f"{item.name} → {folder_name}/")

    _push_bulk_undo(f"organized the desktop ({len(journal)} files)", journal, created)
    result = f"Desktop organized ({mode}): {len(moved)} files moved."
    if moved:
        result += "\n" + "\n".join(moved[:8])
        if len(moved) > 8:
            result += f"\n... and {len(moved) - 8} more."
    if skipped:
        result += f"\n{len(skipped)} file(s) skipped (name conflict)."
    if failed:
        result += f"\n{len(failed)} file(s) could not be moved: {', '.join(failed[:5])}."
    return result


def list_desktop() -> str:
    desktop = _get_desktop()
    items   = []
    for item in sorted(desktop.iterdir()):
        if item.name.startswith("."):
            continue
        if item.is_dir():
            try:
                count = len(list(item.iterdir()))
            except PermissionError:
                count = "?"
            items.append(f"📁 {item.name}/ ({count} items)")
        else:
            size     = item.stat().st_size
            size_str = (
                f"{size / 1024:.1f} KB" if size < 1024 * 1024
                else f"{size / 1024 / 1024:.1f} MB"
            )
            items.append(f"📄 {item.name} ({size_str})")

    if not items:
        return "Desktop is empty."
    return f"Desktop ({len(items)} items):\n" + "\n".join(items)


def clean_desktop() -> str:
    desktop     = _get_desktop()
    skip_exts   = _SKIP_EXTENSIONS.get(_OS, set())
    today       = datetime.now().strftime("%Y-%m-%d")
    archive_dir = desktop / f"Desktop Archive {today}"
    created = set() if archive_dir.exists() else {archive_dir}
    archive_dir.mkdir(exist_ok=True)

    journal: list = []
    failed: list = []
    for item in desktop.iterdir():
        if item.is_dir() or item.name.startswith("."):
            continue
        if item.suffix.lower() in skip_exts:
            continue
        new_path = archive_dir / item.name
        if not new_path.exists():
            _move_journaled(item, new_path, journal, failed)

    _push_bulk_undo(f"cleaned the desktop ({len(journal)} files)", journal, created)
    result = f"Desktop cleaned: {len(journal)} files archived to '{archive_dir.name}'."
    if failed:
        result += f" {len(failed)} could not be moved: {', '.join(failed[:5])}."
    return result


def get_desktop_stats() -> str:
    desktop    = _get_desktop()
    files      = [i for i in desktop.iterdir() if i.is_file()]
    folders    = [i for i in desktop.iterdir() if i.is_dir()]
    total_size = sum(f.stat().st_size for f in files if f.exists())
    size_str   = (
        f"{total_size / 1024:.1f} KB" if total_size < 1024 * 1024
        else f"{total_size / 1024 / 1024:.1f} MB"
    )
    return (
        f"Desktop stats ({_OS}):\n"
        f"  Files   : {len(files)}\n"
        f"  Folders : {len(folders)}\n"
        f"  Size    : {size_str}\n"
        f"  Path    : {desktop}"
    )

def desktop_control(
    parameters: dict = None,
    response=None,
    player=None,
    session_memory=None,
) -> str:
    """
    parameters:
        action : wallpaper | wallpaper_url | current_wallpaper |
                 organize  | clean | list | stats |
                 task (AI-powered)
        path   : image path for 'wallpaper'
        url    : image URL for 'wallpaper_url'
        mode   : 'by_type' or 'by_date' for 'organize'
        task   : natural language description for AI-powered actions
    """
    params = parameters or {}
    action = params.get("action", "").lower().strip()
    task   = params.get("task", "").strip()

    if player:
        player.write_log(f"[desktop] {action or task[:40]}")

    try:
        if action == "wallpaper":
            path = params.get("path", "")
            return set_wallpaper(path) if path else "No image path provided."

        elif action == "wallpaper_url":
            url = params.get("url", "")
            return set_wallpaper_from_url(url) if url else "No URL provided."

        elif action == "current_wallpaper":
            return get_current_wallpaper()

        elif action == "organize":
            return organize_desktop(params.get("mode", "by_type"))

        elif action == "clean":
            return clean_desktop()

        elif action == "list":
            return list_desktop()

        elif action == "stats":
            return get_desktop_stats()

        elif action == "task" or task:
            actual_task = task or params.get("description", "")
            if not actual_task:
                return "Please describe what you want to do on the desktop."

            print(f"[Desktop] Asking Gemini: {actual_task}")
            if player:
                player.write_log("[Desktop] Generating action...")

            code = _ask_gemini_for_desktop_action(actual_task)
            return _confirm_and_execute(actual_task, code, player=player)

        else:
            if action:
                code = _ask_gemini_for_desktop_action(action)
                return _confirm_and_execute(action, code, player=player)
            return "No action or task specified."

    except Exception as e:
        print(f"[Desktop] Error: {e}")
        return f"Desktop control error: {e}"


# ── Tool declaration (auto-discovered by core/action_loader.py) ──────────────
TOOL = {
    "name": "desktop_control",
    "description": "Controls the desktop: wallpaper, organize, clean, list, stats.",
    "parameters": {
        "type": "OBJECT",
        "properties": {
            "action": {
                "type": "STRING",
                "description": "wallpaper | wallpaper_url | organize | clean | list | stats | task"
            },
            "path": {
                "type": "STRING",
                "description": "Image path for wallpaper"
            },
            "url": {
                "type": "STRING",
                "description": "Image URL for wallpaper_url"
            },
            "mode": {
                "type": "STRING",
                "description": "by_type or by_date for organize"
            },
            "task": {
                "type": "STRING",
                "description": "Natural language desktop task"
            }
        },
        "required": [
            "action"
        ]
    },
    "handler": desktop_control,
}
