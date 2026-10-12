"""Load and cache portrait cover art for supported games."""

from __future__ import annotations

import os
import urllib.error
import urllib.request

from PyQt6.QtCore import Qt, QSize, QRectF
from PyQt6.QtGui import (
    QPainter, QLinearGradient, QColor, QFont, QPen, QPixmap, QBrush,
    QPainterPath, QImageReader, QFontMetrics,
)

from game_catalog import GameInfo

_ASSET_DIR = os.path.join(os.path.dirname(os.path.abspath(__file__)), "images")
os.makedirs(_ASSET_DIR, exist_ok=True)

COVER_URLS: dict[str, str] = {
    "fortnite": "https://images.igdb.com/igdb/image/upload/t_cover_big/cocj20.jpg",
    "valorant": "https://images.igdb.com/igdb/image/upload/t_cover_big/co2mvt.jpg",
    "apex": "https://shared.fastly.steamstatic.com/store_item_assets/steam/apps/1172470/library_600x900.jpg",
    "cs2": "https://shared.fastly.steamstatic.com/store_item_assets/steam/apps/730/library_600x900.jpg",
    "warzone": "https://shared.fastly.steamstatic.com/store_item_assets/steam/apps/1938090/library_600x900.jpg",
    "mw3": "https://shared.fastly.steamstatic.com/store_item_assets/steam/apps/2519060/library_600x900.jpg",
    "bo6": "https://images.igdb.com/igdb/image/upload/t_cover_big/co8a9f.jpg",
    "overwatch2": "https://shared.fastly.steamstatic.com/store_item_assets/steam/apps/2357570/library_600x900.jpg",
    "r6": "https://shared.fastly.steamstatic.com/store_item_assets/steam/apps/359550/library_600x900.jpg",
    "pubg": "https://shared.fastly.steamstatic.com/store_item_assets/steam/apps/578080/library_600x900.jpg",
    "marvel_rivals": "https://shared.fastly.steamstatic.com/store_item_assets/steam/apps/2767030/library_600x900.jpg",
    "destiny2": "https://shared.fastly.steamstatic.com/store_item_assets/steam/apps/1085660/library_600x900.jpg",
    "halo": "https://shared.fastly.steamstatic.com/store_item_assets/steam/apps/1240440/library_600x900.jpg",
    "the_finals": "https://shared.fastly.steamstatic.com/store_item_assets/steam/apps/2073850/library_600x900.jpg",
    "paladins": "https://shared.fastly.steamstatic.com/store_item_assets/steam/apps/444090/library_600x900.jpg",
    "tf2": "https://shared.fastly.steamstatic.com/store_item_assets/steam/apps/440/library_600x900.jpg",
    "rust": "https://shared.fastly.steamstatic.com/store_item_assets/steam/apps/252490/library_600x900.jpg",
    "tarkov": "https://images.igdb.com/igdb/image/upload/t_cover_big/co1wyy.jpg",
    "bf2042": "https://shared.fastly.steamstatic.com/store_item_assets/steam/apps/1517290/library_600x900.jpg",
    "splitgate": "https://shared.fastly.steamstatic.com/store_item_assets/steam/apps/677620/library_600x900.jpg",
    "rogue_company": "https://shared.fastly.steamstatic.com/store_item_assets/steam/apps/872200/library_600x900.jpg",
    "deadlock": "https://shared.fastly.steamstatic.com/store_item_assets/steam/apps/1422450/library_600x900.jpg",
    "xdefiant": "https://shared.fastly.steamstatic.com/store_item_assets/steam/apps/2073850/library_600x900.jpg",
    "helldivers2": "https://shared.fastly.steamstatic.com/store_item_assets/steam/apps/553850/library_600x900.jpg",
    "gray_zone": "https://shared.fastly.steamstatic.com/store_item_assets/steam/apps/2479810/library_600x900.jpg",
    "arena_breakout": "https://shared.fastly.steamstatic.com/store_item_assets/steam/apps/2073620/library_600x900.jpg",
    "bloodstrike": "https://shared.fastly.steamstatic.com/store_item_assets/steam/apps/2918150/library_600x900.jpg",
    "farlight": "https://shared.fastly.steamstatic.com/store_item_assets/steam/apps/1928420/library_600x900.jpg",
    "supervive": "https://shared.fastly.steamstatic.com/store_item_assets/steam/apps/1283700/library_600x900.jpg",
    "fragpunk": "https://shared.fastly.steamstatic.com/store_item_assets/steam/apps/2943650/library_600x900.jpg",
    "cod_mobile": "https://shared.fastly.steamstatic.com/store_item_assets/steam/apps/1938090/library_600x900.jpg",
    "fortnite_zero": "https://images.igdb.com/igdb/image/upload/t_cover_big/cocj20.jpg",
    "roblox": "https://shared.fastly.steamstatic.com/store_item_assets/steam/apps/1677740/library_600x900.jpg",
}

_CACHE: dict[str, QPixmap | None] = {}


def cache_path(game_id: str) -> str:
    return os.path.join(_ASSET_DIR, f"{game_id}.jpg")


def _download(url: str, dest: str) -> bool:
    try:
        req = urllib.request.Request(url, headers={"User-Agent": "Mozilla/5.0 InchroUI/1.0"})
        with urllib.request.urlopen(req, timeout=20) as resp:
            data = resp.read()
        if len(data) < 1024:
            return False
        tmp = dest + ".tmp"
        with open(tmp, "wb") as f:
            f.write(data)
        os.replace(tmp, dest)
        return True
    except (OSError, urllib.error.URLError, TimeoutError):
        return False


def ensure_cached(game_id: str) -> bool:
    path = cache_path(game_id)
    if os.path.isfile(path) and os.path.getsize(path) > 1024:
        return True
    url = COVER_URLS.get(game_id)
    if not url:
        return False
    return _download(url, path)


def prefetch_all() -> None:
    for game_id in COVER_URLS:
        ensure_cached(game_id)


def clear_cache() -> None:
    _CACHE.clear()


def _load_cover_pixmap(game_id: str) -> QPixmap | None:
    if game_id in _CACHE:
        return _CACHE[game_id]

    path = cache_path(game_id)
    if not os.path.isfile(path):
        ensure_cached(game_id)

    if os.path.isfile(path):
        reader = QImageReader(path)
        reader.setAutoTransform(True)
        image = reader.read()
        if not image.isNull():
            pm = QPixmap.fromImage(image)
            pm.setDevicePixelRatio(1.0)
            _CACHE[game_id] = pm
            return pm

    _CACHE[game_id] = None
    return None


def footer_height(card_width: int) -> int:
    """Reserved bottom band so titles never clip into cover art."""
    return max(52, int(card_width * 0.26))


def draw_card_footer(
    p: QPainter,
    outer_rect,
    title: str,
    accent: str,
    radius: float = 16,
) -> None:
    """Draw a solid footer bar + accent rule + wrapped title inside the card."""
    rf = QRectF(outer_rect)
    fh = footer_height(int(rf.width()))
    footer = QRectF(rf.left(), rf.bottom() - fh, rf.width(), fh)

    clip = QPainterPath()
    clip.addRoundedRect(rf, radius, radius)
    p.setClipPath(clip)
    p.fillRect(footer, QColor(0, 0, 0, 230))

    sep_y = footer.top() + 5
    p.setPen(QPen(QColor(accent), 2))
    p.drawLine(int(footer.left() + 10), int(sep_y), int(footer.right() - 10), int(sep_y))

    text_rect = QRectF(
        footer.left() + 8,
        footer.top() + 12,
        footer.width() - 16,
        footer.height() - 16,
    )
    align = int(Qt.AlignmentFlag.AlignHCenter | Qt.AlignmentFlag.AlignVCenter | Qt.TextFlag.TextWordWrap)

    for pt in (9, 8, 7):
        font = QFont()
        font.setBold(True)
        font.setPointSize(pt)
        p.setFont(font)
        metrics = QFontMetrics(font)
        bounds = metrics.boundingRect(text_rect.toRect(), align, title)
        if bounds.height() <= text_rect.height() + 2:
            break

    p.setPen(QColor("#ffffff"))
    p.drawText(text_rect, align, title)
    p.setClipping(False)


def _draw_cover(p: QPainter, cover: QPixmap, rect, radius: float) -> None:
    rf = QRectF(rect)
    clip = QPainterPath()
    clip.addRoundedRect(rf, radius, radius)
    p.setClipPath(clip)

    scaled = cover.scaled(
        rect.size(),
        Qt.AspectRatioMode.KeepAspectRatioByExpanding,
        Qt.TransformationMode.SmoothTransformation,
    )
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
    """Cover image only — labels are painted separately so they never scale/clip."""
    pm = QPixmap(width, height)
    pm.fill(Qt.GlobalColor.transparent)
    p = QPainter(pm)
    p.setRenderHint(QPainter.RenderHint.Antialiasing, True)
    p.setRenderHint(QPainter.RenderHint.SmoothPixmapTransform, True)

    rect = pm.rect().adjusted(0, 0, -1, -1)
    cover = _load_cover_pixmap(game.id)

    if cover and not cover.isNull():
        _draw_cover(p, cover, rect, 16)
    else:
        grad = QLinearGradient(0, 0, 0, height)
        grad.setColorAt(0.0, QColor(game.color_top))
        grad.setColorAt(1.0, QColor(game.color_bottom))
        p.setBrush(QBrush(grad))
        p.setPen(Qt.PenStyle.NoPen)
        p.drawRoundedRect(rect, 16, 16)

        p.setPen(QColor("#ffffff"))
        font = QFont()
        font.setBold(True)
        font.setPointSize(10)
        p.setFont(font)
        fh = footer_height(width)
        p.drawText(
            10, 18, width - 20, height - fh - 24,
            int(Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignTop | Qt.TextFlag.TextWordWrap),
            game.name.upper(),
        )

    p.end()
    pm.setDevicePixelRatio(1.0)
    return pm


def render_game_art(game: GameInfo, width: int = 126, height: int = 224) -> QPixmap:
    """Full card with cover + footer (for static previews in dialogs)."""
    pm = QPixmap(width, height)
    pm.fill(Qt.GlobalColor.transparent)
    p = QPainter(pm)
    p.setRenderHint(QPainter.RenderHint.Antialiasing, True)
    p.setRenderHint(QPainter.RenderHint.SmoothPixmapTransform, True)

    rect = pm.rect().adjusted(0, 0, -1, -1)
    cover = render_cover_only(game, width, height)
    p.drawPixmap(0, 0, cover)
    draw_card_footer(p, rect, game.name, game.accent, 16)
    p.end()
    pm.setDevicePixelRatio(1.0)
    return pm


def art_for_game(game: GameInfo, size: QSize) -> QPixmap:
    """Return card art scaled exactly to widget size."""
    base = render_game_art(game, max(1, size.width()), max(1, size.height()))
    if base.size() == size:
        return base
    out = base.scaled(size, Qt.AspectRatioMode.IgnoreAspectRatio,
                      Qt.TransformationMode.SmoothTransformation)
    out.setDevicePixelRatio(1.0)
    return out
