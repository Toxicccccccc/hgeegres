"""Game detection and per-game profile mapping for DisabledAssistance.

This module discovers the games on the machine and pairs each one with an assist
profile, so switching game is one selection rather than re-tuning every slider.

What it provides:

* **A known-game catalog.** A table of popular titles mapped to the executable
  names they run as (``VALORANT-Win64-Shipping``, ``cs2``, ``r5apex`` ...). This
  is what lets a running game be recognised and have its profile selected
  automatically, without the player naming it.
* **Running-game detection.** It enumerates visible top-level windows, resolves
  each one's owning process, and matches that executable against the catalog.
  This is a user-space, read-only enumeration of window titles and process
  names; it never injects into a game or reads its memory.
* **Logo extraction.** For a recognised game it extracts the executable's own
  icon with the Win32 shell API and caches it as a PNG next to the profiles, so
  the GUI can show each game's app logo. When no icon can be extracted it
  generates a deterministic coloured monogram instead, so there is always a
  visual.

The module is deliberately split so the platform-free parts (catalog matching,
name normalisation, monogram generation) can be unit tested without Windows.
"""

from __future__ import annotations

import os
import re
import struct
from pathlib import Path

# ---------------------------------------------------------------------------
# Known-game catalog
# ---------------------------------------------------------------------------
# Maps a canonical display name to the set of executable stems (lower-case, no
# ".exe") that identify it. Matching is by exact stem first, then by the
# longest catalog stem contained in the process name, so versioned or
# anti-cheat-suffixed names ("VALORANT-Win64-Shipping") still resolve.
KNOWN_GAMES = {
    "Valorant": {"valorant", "valorant-win64-shipping", "riotclientux"},
    "Counter-Strike 2": {"cs2", "counter-strike 2"},
    "Apex Legends": {"r5apex", "r5apex_dx12"},
    "The Finals": {"discovery", "thefinals"},
    "Overwatch 2": {"overwatch", "overwatch 2"},
    "Rainbow Six Siege": {"rainbowsix", "rainbowsix_dx11", "rainbowsix_vulkan"},
    "Fortnite": {"fortniteclient-win64-shipping", "fortnite"},
    "PUBG: Battlegrounds": {"tslgame"},
    "Call of Duty": {"cod", "codmw2", "codmw3", "modernwarfare", "sp-cod", "codhq"},
    "Escape from Tarkov": {"escapefromtarkov"},
    "Destiny 2": {"destiny2"},
    "Halo Infinite": {"haloinfinite"},
    "Battlefield 2042": {"bf2042"},
    "Rust": {"rustclient", "rust"},
    "Warframe": {"warframe.x64", "warframe"},
    "Team Fortress 2": {"hl2", "tf_win64"},
    "Dota 2": {"dota2"},
    "League of Legends": {"leagueclientux", "league of legends"},
    "Rocket League": {"rocketleague"},
    "Minecraft": {"javaw", "minecraft", "minecraft.windows"},
    "Grand Theft Auto V": {"gta5", "gta5_enhanced"},
}

# Reverse index: executable stem -> canonical game name. Built once at import.
_EXE_TO_GAME = {
    stem: game for game, stems in KNOWN_GAMES.items() for stem in stems
}


def normalise_stem(value: str) -> str:
    """Normalise a process or file name to a matchable executable stem."""
    if not value:
        return ""
    name = os.path.basename(str(value)).lower().strip()
    if name.endswith(".exe"):
        name = name[:-4]
    return name


def match_game(process_name: str) -> str | None:
    """Return the canonical game name for a process, or None when unknown.

    Exact stems win. Otherwise the longest catalog stem contained in the process
    name is used, so a title that ships under a longer internal name still
    resolves ("VALORANT-Win64-Shipping" -> "Valorant").
    """
    stem = normalise_stem(process_name)
    if not stem:
        return None
    if stem in _EXE_TO_GAME:
        return _EXE_TO_GAME[stem]
    best_game = None
    best_length = 0
    for candidate, game in _EXE_TO_GAME.items():
        if candidate in stem and len(candidate) > best_length:
            best_game = game
            best_length = len(candidate)
    return best_game


# ---------------------------------------------------------------------------
# Running-game detection (Windows only, read-only)
# ---------------------------------------------------------------------------
def _process_name_for_pid(pid: int) -> str:
    """Best-effort executable name for a PID, without extra dependencies.

    ``win32process`` can return the module name directly; if that fails we fall
    back to the psutil-free trick of querying the process image path.
    """
    try:
        import win32process

        handle = win32process.OpenProcess(0x1000, False, pid)  # PROCESS_QUERY_LIMITED_INFORMATION
        if handle:
            try:
                return win32process.GetModuleFileNameEx(handle, 0)
            finally:
                win32process.CloseHandle(handle)
    except Exception:
        pass
    return ""


def running_games():
    """Return a list of detected games currently running.

    Each entry is ``{"name": <canonical>, "exe": <path or stem>}``. Detection is
    a user-space enumeration of visible windows and their owning processes; a
    game that runs without a visible window will not be seen, which is the
    conservative and privacy-preserving behaviour.
    """
    detected = {}
    try:
        import win32gui
        import win32process
    except Exception:
        return []

    def visit(hwnd, _):
        try:
            if not win32gui.IsWindowVisible(hwnd):
                return
            _, pid = win32process.GetWindowThreadProcessId(hwnd)
            if not pid:
                return
            exe_path = _process_name_for_pid(pid)
            stem = normalise_stem(exe_path)
            if not stem:
                return
            game = match_game(stem)
            if game and game not in detected:
                detected[game] = {"name": game, "exe": exe_path or stem}
        except Exception:
            return

    try:
        win32gui.EnumWindows(visit, None)
    except Exception:
        return list(detected.values())
    return list(detected.values())


# ---------------------------------------------------------------------------
# Logo extraction and monogram fallback
# ---------------------------------------------------------------------------
def _extract_exe_icon_png(exe_path: str, out_path: Path, size: int = 128) -> bool:
    """Extract the icon embedded in an executable and save it as a PNG.

    Uses the Win32 shell/``ExtractIconEx`` path, then win32ui to render it to a
    bitmap and dump it as PNG. Returns True on success, False otherwise.
    """
    try:
        import win32api
        import win32con
        import win32ui
        from PIL import Image

        # ExtractIconEx returns (large, small) HICON handles for a given index.
        large, small = win32api.ExtractIconEx(exe_path, 0)
        icon = (large or small)[0] if (large or small) else None
        if icon is None:
            return False

        # Render the HICON into a device-independent bitmap we can read back.
        source_dc = win32ui.CreateDCFromHandle(win32gui_get_dc())
        memory_dc = source_dc.CreateCompatibleDC()
        bitmap = win32ui.CreateBitmap()
        bitmap.CreateCompatibleBitmap(source_dc, size, size)
        memory_dc.SelectObject(bitmap)

        import win32gui

        win32gui.DrawIconEx(
            memory_dc.GetSafeHdc(), 0, 0, icon, size, size, 0, None,
            win32con.DI_NORMAL,
        )
        bits = bitmap.GetBitmapBits(True)
        image = Image.frombuffer("RGBA", (size, size), bits, "raw", "BGRA", 0, 1)
        image.save(str(out_path), "PNG")

        win32gui.DestroyIcon(icon)
        memory_dc.DeleteDC()
        source_dc.DeleteDC()
        return True
    except Exception:
        return False


def win32gui_get_dc():
    """Small helper so the icon renderer can grab the desktop DC safely."""
    import win32gui

    return win32gui.GetDC(0)


def _monogram_png(name: str, out_path: Path, size: int = 128) -> bool:
    """Generate a deterministic coloured monogram PNG for a game.

    This is the always-available fallback: even when no icon can be extracted,
    the profile list shows a distinct, stable tile for every game. The colour is
    derived from the name so it never changes between runs.
    """
    try:
        from PIL import Image, ImageDraw, ImageFont
    except Exception:
        return False
    try:
        digest = 0
        for char in name:
            digest = (digest * 131 + ord(char)) & 0xFFFFFFFF
        base = (digest & 0xFF, (digest >> 8) & 0xFF, (digest >> 16) & 0xFF)
        # Keep the tile dark enough for white text to stay legible.
        colour = tuple(40 + (channel % 140) for channel in base)
        image = Image.new("RGBA", (size, size), colour + (255,))
        draw = ImageDraw.Draw(image)
        initials = "".join(
            word[0] for word in re.findall(r"[A-Za-z0-9]+", name)[:2]
        ).upper() or "?"
        try:
            font = ImageFont.truetype("segoeuib.ttf", int(size * 0.5))
        except Exception:
            font = ImageFont.load_default()
        box = draw.textbbox((0, 0), initials, font=font)
        text_w = box[2] - box[0]
        text_h = box[3] - box[1]
        draw.text(
            ((size - text_w) / 2 - box[0], (size - text_h) / 2 - box[1]),
            initials,
            fill=(255, 255, 255, 255),
            font=font,
        )
        image.save(str(out_path), "PNG")
        return True
    except Exception:
        return False


def logo_cache_dir(root: Path) -> Path:
    """Where extracted game logos live (created on demand)."""
    folder = Path(root) / "assets" / "game logos"
    folder.mkdir(parents=True, exist_ok=True)
    return folder


def ensure_logo(name: str, exe_path: str | None, root: Path) -> str | None:
    """Return a PNG path for a game's logo, creating it from the exe or a
    monogram when missing. Returns None only when PNG writing is impossible."""
    folder = logo_cache_dir(root)
    safe = re.sub(r"[^A-Za-z0-9._-]+", "_", name).strip("_") or "game"
    target = folder / f"{safe}.png"
    if target.is_file():
        return str(target)
    if exe_path and Path(exe_path).is_file() and _extract_exe_icon_png(exe_path, target):
        return str(target)
    if _monogram_png(name, target):
        return str(target)
    return None
