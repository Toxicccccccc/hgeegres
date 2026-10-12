"""Load and cache portrait cover art for the games in the catalog.

Covers are fetched once, on the main thread, into ``assets/game_covers`` and
reused. When a cover cannot be fetched (offline, blocked), a deterministic
gradient card with the game name is drawn instead, so the grid always looks
complete.
"""

from __future__ import annotations

import os
import urllib.error
import urllib.request

from qt import (
    Qt, QSize, QRectF, QPainter, QLinearGradient, QColor, QFont, QPen,
    QPixmap, QBrush, QPainterPath, QImageReader, QFontMetrics,
)

from game_catalog import GameInfo

# assets/game_covers sits at <root>/assets/game_covers; this file is
# <root>/ui/disabled_ai/game_art.py.
_ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
_ASSET_DIR = os.path.join(_ROOT, "assets", "game_covers")
os.makedirs(_ASSET_DIR, exist_ok=True)

# Public cover-art URLs. These are official store/IGDB artwork served publicly;
# nothing private is fetched, and a failure simply falls back to the gradient.
COVER_URLS: dict[str, str] = {
    "valorant": "https://images.igdb.com/igdb/image/upload/t_cover_big/co2mvt.jpg",
    "cs2": "https://shared.fastly.steamstatic.com/store_item_assets/steam/apps/730/library_600x900.jpg",
    "apex": "https://shared.fastly.steamstatic.com/store_item_assets/steam/apps/1172470/library_600x900.jpg",
    "the_finals": "https://shared.fastly.steamstatic.com/store_item_assets/steam/apps/2073850/library_600x900.jpg",
    "overwatch2": "https://shared.fastly.steamstatic.com/store_item_assets/steam/apps/2357570/library_600x900.jpg",
    "r6": "https://shared.fastly.steamstatic.com/store_item_assets/steam/apps/359550/library_600x900.jpg",
    "fortnite": "https://images.igdb.com/igdb/image/upload/t_cover_big/cocj20.jpg",
    "pubg": "https://shared.fastly.steamstatic.com/store_item_assets/steam/apps/578080/library_600x900.jpg",
    "cod": "https://shared.fastly.steamstatic.com/store_item_assets/steam/apps/2519060/library_600x900.jpg",
    "tarkov": "https://images.igdb.com/igdb/image/upload/t_cover_big/co1wyy.jpg",
    "destiny2": "https://shared.fastly.steamstatic.com/store_item_assets/steam/apps/1085660/library_600x900.jpg",
    "halo": "https://shared.fastly.steamstatic.com/store_item_assets/steam/apps/1240440/library_600x900.jpg",
    "bf2042": "https://shared.fastly.steamstatic.com/store_item_assets/steam/apps/1517290/library_600x900.jpg",
    "rust": "https://shared.fastly.steamstatic.com/store_item_assets/steam/apps/252490/library_600x900.jpg",
    "warframe": "https://shared.fastly.steamstatic.com/store_item_assets/steam/apps/230410/library_600x900.jpg",
    "tf2": "https://shared.fastly.steamstatic.com/store_item_assets/steam/apps/440/library_600x900.jpg",
    "dota2": "https://shared.fastly.steamstatic.com/store_item_assets/steam/apps/570/library_600x900.jpg",
    "lol": "https://images.igdb.com/igdb/image/upload/t_cover_big/co254s.jpg",
    "rocketleague": "https://shared.fastly.steamstatic.com/store_item_assets/steam/apps/252950/library_600x900.jpg",
    "marvel_rivals": "https://shared.fastly.steamstatic.com/store_item_assets/steam/apps/2767030/library_600x900.jpg",
    "deadlock": "https://shared.fastly.steamstatic.com/store_item_assets/steam/apps/1422450/library_600x900.jpg",
    "fragpunk": "https://shared.fastly.steamstatic.com/store_item_assets/steam/apps/2943650/library_600x900.jpg",
    "xdefiant": "https://shared.fastly.steamstatic.com/store_item_assets/steam/apps/2073850/library_600x900.jpg",
}

_CACHE: dict[str, QPixmap | None] = {}


def cache_path(game_id: str) -> str:
    return os.path.join(_ASSET_DIR, f"{game_id}.jpg")


def _download(url: str, dest: str) -> bool:
    try:
        request = urllib.request.Request(url, headers={"User-Agent": "Mozilla/5.0"})
        with urllib.request.urlopen(request, timeout=20) as response:
            data = response.read()
        if len(data) < 1024:
            return False
        tmp = dest + ".tmp"
        with open(tmp, "wb") as handle:
            handle.write(data)
        os.replace(tmp, dest)
        return True
    except (OSError, urllib.error.URLError, TimeoutError):
        return False


def ensure_cached(game_id: str) -> bool:
    path = cache_path(game_id)
    if os.path.isfile(path) and os.path.getsize(path) > 1024:
        return True
    url = COVER_URLS.get(game_id)
    return _download(url, path) if url else False


def prefetch_all() -> None:
    for game_id in COVER_URLS:
        ensure_cached(game_id)


def clear_cache() -> None:
    _CACHE.clear()


def _local_logo_path(game_id: str, game_name: str) -> str | None:
    """Prefer a logo that already ships with the app over a download.

    Users can drop their own image into assets/game_covers/logos/ named either
    after the game id (valorant.png) or the display name (Valorant.png), and it
    is used automatically.
    """
    logo_dir = os.path.join(_ROOT, "assets", "game_covers", "logos")
    for candidate in (game_id, game_name):
        for extension in (".png", ".jpg", ".jpeg", ".webp"):
            path = os.path.join(logo_dir, candidate + extension)
            if os.path.isfile(path):
                return path
    return None


def _load_cover_pixmap(game_id: str, game_name: str = "") -> QPixmap | None:
    cache_key = game_id
    if cache_key in _CACHE:
        return _CACHE[cache_key]

    path = _local_logo_path(game_id, game_name) or cache_path(game_id)
    if not path or not os.path.isfile(path):
        ensure_cached(game_id)
        path = cache_path(game_id)

    if os.path.isfile(path):
        reader = QImageReader(path)
        reader.setAutoTransform(True)
        image = reader.read()
        if not image.isNull():
            pixmap = QPixmap.fromImage(image)
            pixmap.setDevicePixelRatio(1.0)
            _CACHE[cache_key] = pixmap
            return pixmap
    _CACHE[cache_key] = None
    return None


def footer_height(card_width: int) -> int:
    return max(52, int(card_width * 0.26))


def draw_card_footer(p: QPainter, outer_rect, title: str, accent: str, radius: float = 16) -> None:
    """Solid footer bar + accent rule + wrapped title, so the name never clips."""
    rf = QRectF(outer_rect)
    height = footer_height(int(rf.width()))
    footer = QRectF(rf.left(), rf.bottom() - height, rf.width(), height)

    clip = QPainterPath()
    clip.addRoundedRect(rf, radius, radius)
    p.setClipPath(clip)
    p.fillRect(footer, QColor(0, 0, 0, 230))

    p.setPen(QPen(QColor(accent), 2))
    p.drawLine(int(footer.left() + 10), int(footer.top() + 5),
               int(footer.right() - 10), int(footer.top() + 5))

    text_rect = QRectF(footer.left() + 8, footer.top() + 12,
                       footer.width() - 16, footer.height() - 16)
    align = int(Qt.AlignmentFlag.AlignHCenter | Qt.AlignmentFlag.AlignVCenter
                | Qt.TextFlag.TextWordWrap)

    for point_size in (9, 8, 7):
        font = QFont()
        font.setBold(True)
        font.setPointSize(point_size)
        p.setFont(font)
        if QFontMetrics(font).boundingRect(text_rect.toRect(), align, title).height() <= text_rect.height() + 2:
            break

    p.setPen(QColor("#ffffff"))
    p.drawText(text_rect, align, title)
    p.setClipping(False)


def _draw_cover(p: QPainter, cover: QPixmap, rect, radius: float) -> None:
    rf = QRectF(rect)
    clip = QPainterPath()
    clip.addRoundedRect(rf, radius, radius)
    p.setClipPath(clip)
    scaled = cover.scaled(rect.size(),
                          Qt.AspectRatioMode.KeepAspectRatioByExpanding,
                          Qt.TransformationMode.SmoothTransformation)
    x = rect.x() + (rect.width() - scaled.width()) // 2
    y = rect.y() + (rect.height() - scaled.height()) // 2
    p.drawPixmap(x, y, scaled)
    p.setClipping(False)

    fade = QLinearGradient(0, rect.y() + rect.height() * 0.62, 0, rect.bottom())
    fade.setColorAt(0.0, QColor(0, 0, 0, 0))
    fade.setColorAt(0.45, QColor(0, 0, 0, 60))
    fade.setColorAt(1.0, QColor(0, 0, 0, 140))
    p.fillRect(rect, fade)


def render_cover_only(game: GameInfo, width: int = 126, height: int = 224) -> QPixmap:
    """Cover image only — the title is painted separately so it never scales."""
    pixmap = QPixmap(width, height)
    pixmap.fill(Qt.GlobalColor.transparent)
    p = QPainter(pixmap)
    p.setRenderHint(QPainter.RenderHint.Antialiasing, True)
    p.setRenderHint(QPainter.RenderHint.SmoothPixmapTransform, True)

    rect = pixmap.rect().adjusted(0, 0, -1, -1)
    cover = _load_cover_pixmap(game.id, game.name)

    if cover and not cover.isNull():
        _draw_cover(p, cover, rect, 16)
    else:
        gradient = QLinearGradient(0, 0, 0, height)
        gradient.setColorAt(0.0, QColor(game.color_top))
        gradient.setColorAt(1.0, QColor(game.color_bottom))
        p.setBrush(QBrush(gradient))
        p.setPen(Qt.PenStyle.NoPen)
        p.drawRoundedRect(rect, 16, 16)
        p.setPen(QColor("#ffffff"))
        font = QFont()
        font.setBold(True)
        font.setPointSize(10)
        p.setFont(font)
        reserved = footer_height(width)
        p.drawText(10, 18, width - 20, height - reserved - 24,
                   int(Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignTop
                       | Qt.TextFlag.TextWordWrap),
                   game.name.upper())

    p.end()
    pixmap.setDevicePixelRatio(1.0)
    return pixmap


def render_game_art(game: GameInfo, width: int = 126, height: int = 224) -> QPixmap:
    """Full card: cover plus footer bar with the game's name."""
    pixmap = QPixmap(width, height)
    pixmap.fill(Qt.GlobalColor.transparent)
    p = QPainter(pixmap)
    p.setRenderHint(QPainter.RenderHint.Antialiasing, True)
    p.setRenderHint(QPainter.RenderHint.SmoothPixmapTransform, True)
    rect = pixmap.rect().adjusted(0, 0, -1, -1)
    p.drawPixmap(0, 0, render_cover_only(game, width, height))
    draw_card_footer(p, rect, game.name, game.accent, 16)
    p.end()
    pixmap.setDevicePixelRatio(1.0)
    return pixmap


def art_for_game(game: GameInfo, size: QSize) -> QPixmap:
    base = render_game_art(game, max(1, size.width()), max(1, size.height()))
    if base.size() == size:
        return base
    out = base.scaled(size, Qt.AspectRatioMode.IgnoreAspectRatio,
                      Qt.TransformationMode.SmoothTransformation)
    out.setDevicePixelRatio(1.0)
    return out
