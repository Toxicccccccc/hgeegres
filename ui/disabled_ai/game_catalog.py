"""Supported games, each with cover art colours and the executables it runs as.

A profile is saved per game, so switching game is one click instead of re-tuning
every slider. The ``exe`` set lets a running game be recognised automatically and
its profile offered, without the player naming it.
"""

from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class GameInfo:
    id: str
    name: str
    color_top: str
    color_bottom: str
    accent: str
    exe: frozenset[str] = frozenset()


GAMES: tuple[GameInfo, ...] = (
    GameInfo("valorant", "Valorant", "#450a0a", "#dc2626", "#ff4655",
             frozenset({"valorant", "valorant-win64-shipping", "riotclientux"})),
    GameInfo("cs2", "Counter-Strike 2", "#171717", "#f59e0b", "#de9b35",
             frozenset({"cs2", "counter-strike 2"})),
    GameInfo("apex", "Apex Legends", "#1e1b4b", "#ea580c", "#ff4d00",
             frozenset({"r5apex", "r5apex_dx12"})),
    GameInfo("the_finals", "The Finals", "#831843", "#db2777", "#fbcfe8",
             frozenset({"discovery", "thefinals"})),
    GameInfo("overwatch2", "Overwatch 2", "#312e81", "#6366f1", "#f97316",
             frozenset({"overwatch", "overwatch 2"})),
    GameInfo("r6", "Rainbow Six Siege", "#0c4a6e", "#0369a1", "#facc15",
             frozenset({"rainbowsix", "rainbowsix_dx11", "rainbowsix_vulkan"})),
    GameInfo("fortnite", "Fortnite", "#5b21b6", "#2563eb", "#fbbf24",
             frozenset({"fortniteclient-win64-shipping", "fortnite"})),
    GameInfo("pubg", "PUBG", "#422006", "#ca8a04", "#fef08a",
             frozenset({"tslgame"})),
    GameInfo("cod", "Call of Duty", "#0f172a", "#334155", "#38bdf8",
             frozenset({"cod", "codmw2", "codmw3", "modernwarfare", "sp-cod", "codhq"})),
    GameInfo("tarkov", "Escape From Tarkov", "#27272a", "#52525b", "#a3a3a3",
             frozenset({"escapefromtarkov"})),
    GameInfo("destiny2", "Destiny 2", "#111827", "#374151", "#60a5fa",
             frozenset({"destiny2"})),
    GameInfo("halo", "Halo Infinite", "#064e3b", "#059669", "#34d399",
             frozenset({"haloinfinite"})),
    GameInfo("bf2042", "Battlefield 2042", "#0e7490", "#0891b2", "#67e8f9",
             frozenset({"bf2042"})),
    GameInfo("rust", "Rust", "#3f3f46", "#71717a", "#ef4444",
             frozenset({"rustclient", "rust"})),
    GameInfo("warframe", "Warframe", "#1c1917", "#44403c", "#fbbf24",
             frozenset({"warframe.x64", "warframe"})),
    GameInfo("tf2", "Team Fortress 2", "#7c2d12", "#ea580c", "#fcd34d",
             frozenset({"hl2", "tf_win64"})),
    GameInfo("dota2", "Dota 2", "#7f1d1d", "#b91c1c", "#fca5a5",
             frozenset({"dota2"})),
    GameInfo("lol", "League of Legends", "#1e3a8a", "#2563eb", "#93c5fd",
             frozenset({"leagueclientux", "league of legends"})),
    GameInfo("rocketleague", "Rocket League", "#0c4a6e", "#0284c7", "#7dd3fc",
             frozenset({"rocketleague"})),
    GameInfo("marvel_rivals", "Marvel Rivals", "#4c0519", "#be123c", "#fde047",
             frozenset({"marvelrivals", "marvel-rivals"})),
    GameInfo("deadlock", "Deadlock", "#3f6212", "#65a30d", "#d9f99d",
             frozenset({"deadlock", "project8staging"})),
    GameInfo("fragpunk", "FragPunk", "#701a75", "#c026d3", "#f0abfc",
             frozenset({"fragpunk"})),
    GameInfo("xdefiant", "XDefiant", "#713f12", "#b45309", "#fdba74",
             frozenset({"xdefiant"})),
    GameInfo("custom", "Other / Custom", "#18181b", "#3f3f46", "#a1a1aa",
             frozenset()),
)

_BY_ID = {game.id: game for game in GAMES}
# exe stem -> game id, for detecting a running game.
_BY_EXE = {stem: game.id for game in GAMES for stem in game.exe}


def get_game(game_id: str) -> GameInfo | None:
    return _BY_ID.get(game_id)


def search_games(query: str) -> list[GameInfo]:
    text = query.strip().lower()
    if not text:
        return list(GAMES)
    return [g for g in GAMES if text in g.name.lower() or text in g.id.replace("_", " ")]


def game_for_process(process_name: str) -> str | None:
    """Return the game id whose executable matches this process name, if any."""
    if not process_name:
        return None
    name = str(process_name).lower().strip()
    if name.endswith(".exe"):
        name = name[:-4]
    if name in _BY_EXE:
        return _BY_EXE[name]
    # Longest-match against the known stems, so versioned/anti-cheat suffixed
    # names ("valorant-win64-shipping") still resolve.
    best = None
    for stem, game_id in _BY_EXE.items():
        if stem in name and (best is None or len(stem) > len(best[0])):
            best = (stem, game_id)
    return best[1] if best else None
