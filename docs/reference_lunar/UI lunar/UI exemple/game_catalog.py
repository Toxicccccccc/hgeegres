"""Supported games for profile-based config presets."""

from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class GameInfo:
    id: str
    name: str
    color_top: str
    color_bottom: str
    accent: str


GAMES: tuple[GameInfo, ...] = (
    GameInfo("fortnite", "Fortnite", "#5b21b6", "#2563eb", "#fbbf24"),
    GameInfo("valorant", "Valorant", "#450a0a", "#dc2626", "#ff4655"),
    GameInfo("apex", "Apex Legends", "#1e1b4b", "#ea580c", "#ff4d00"),
    GameInfo("cs2", "Counter-Strike 2", "#171717", "#f59e0b", "#de9b35"),
    GameInfo("warzone", "Call of Duty: Warzone", "#052e16", "#14532d", "#84cc16"),
    GameInfo("mw3", "Call of Duty: MW3", "#0f172a", "#334155", "#38bdf8"),
    GameInfo("bo6", "Call of Duty: BO6", "#1c1917", "#44403c", "#f97316"),
    GameInfo("overwatch2", "Overwatch 2", "#312e81", "#6366f1", "#f97316"),
    GameInfo("r6", "Rainbow Six Siege", "#0c4a6e", "#0369a1", "#facc15"),
    GameInfo("pubg", "PUBG", "#422006", "#ca8a04", "#fef08a"),
    GameInfo("marvel_rivals", "Marvel Rivals", "#4c0519", "#be123c", "#fde047"),
    GameInfo("destiny2", "Destiny 2", "#111827", "#374151", "#60a5fa"),
    GameInfo("halo", "Halo Infinite", "#064e3b", "#059669", "#34d399"),
    GameInfo("the_finals", "The Finals", "#831843", "#db2777", "#fbcfe8"),
    GameInfo("paladins", "Paladins", "#1e3a8a", "#2563eb", "#93c5fd"),
    GameInfo("tf2", "Team Fortress 2", "#7c2d12", "#ea580c", "#fcd34d"),
    GameInfo("rust", "Rust", "#3f3f46", "#71717a", "#ef4444"),
    GameInfo("tarkov", "Escape From Tarkov", "#27272a", "#52525b", "#a3a3a3"),
    GameInfo("bf2042", "Battlefield 2042", "#0e7490", "#0891b2", "#67e8f9"),
    GameInfo("splitgate", "Splitgate 2", "#312e81", "#7c3aed", "#c4b5fd"),
    GameInfo("rogue_company", "Rogue Company", "#134e4a", "#0d9488", "#5eead4"),
    GameInfo("deadlock", "Deadlock", "#3f6212", "#65a30d", "#d9f99d"),
    GameInfo("xdefiant", "XDefiant", "#713f12", "#b45309", "#fdba74"),
    GameInfo("helldivers2", "Helldivers 2", "#1e293b", "#475569", "#f8fafc"),
    GameInfo("gray_zone", "Gray Zone Warfare", "#365314", "#4d7c0f", "#bef264"),
    GameInfo("arena_breakout", "Arena Breakout", "#292524", "#57534e", "#d6d3d1"),
    GameInfo("bloodstrike", "Blood Strike", "#7f1d1d", "#b91c1c", "#fca5a5"),
    GameInfo("farlight", "Farlight 84", "#581c87", "#9333ea", "#e9d5ff"),
    GameInfo("supervive", "Supervive", "#155e75", "#0891b2", "#a5f3fc"),
    GameInfo("fragpunk", "FragPunk", "#701a75", "#c026d3", "#f0abfc"),
    GameInfo("cod_mobile", "Call of Duty: Mobile", "#1e40af", "#1d4ed8", "#93c5fd"),
    GameInfo("fortnite_zero", "Fortnite Zero Build", "#4c1d95", "#7c3aed", "#fde68a"),
    GameInfo("roblox", "Roblox FPS", "#1d4ed8", "#3b82f6", "#ffffff"),
    GameInfo("custom", "Other / Custom", "#18181b", "#3f3f46", "#a1a1aa"),
)

_BY_ID = {g.id: g for g in GAMES}


def get_game(game_id: str) -> GameInfo | None:
    return _BY_ID.get(game_id)


def search_games(query: str) -> list[GameInfo]:
    q = query.strip().lower()
    if not q:
        return list(GAMES)
    return [g for g in GAMES if q in g.name.lower() or q in g.id.replace("_", " ")]
