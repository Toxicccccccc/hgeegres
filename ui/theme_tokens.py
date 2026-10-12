"""Binding-independent design tokens shared by the desktop interfaces."""

TOKENS = {
    "bg_app": "#0B0D1A",
    "bg_chrome": "#0F1224",
    "bg_panel": "#12152A",
    "bg_raised": "#171B33",
    "bg_input": "#0E1122",
    "bg_hover": "#1A1F3A",
    "border": "#232842",
    "border_strong": "#2A2F4A",
    "text_primary": "#FFFFFF",
    "text_secondary": "#8A90A8",
    "text_tertiary": "#7A80A0",
    "text_accent": "#8FA6FF",
    "accent": "#2F4BFF",
    "accent_hover": "#4159FF",
    "accent_active": "#2440E6",
    "accent_soft": "#171E4C",
    "accent_line": "#22339F",
    "accent_disabled": "#1C2875",
    "ok": "#3DD68C",
    "warn": "#F5A623",
    "danger": "#E5484D",
    "info": "#4EA8FF",
    "ok_soft": "#16281F",
    "danger_soft": "#2A1A20",
    "scrim": "rgba(4, 6, 18, 184)",
    "shadow": "rgba(0, 0, 0, 140)",
    "overlay_key": "#010203",
    # Hero/banner gradient (blue -> purple). Only ever painted behind the
    # header band, never on buttons, cards or text.
    "gradient_from": "#2F4BFF",
    "gradient_to": "#7B3FE4",
}

SP = {"1": 4, "2": 8, "3": 12, "4": 16, "5": 20, "6": 24, "8": 32}
RADIUS = {"xs": 3, "sm": 4, "md": 6, "pill": 999}
FONT_FAMILIES = ("Inter", "Manrope", "Segoe UI", "Noto Sans", "Ubuntu", "Arial")
FONT_MONO = ("JetBrains Mono", "Cascadia Mono", "Consolas", "DejaVu Sans Mono", "monospace")

# Desktop shell dimensions and behavior breakpoints.
#
# Vertical rhythm: titlebar 36 -> header 52 -> body -> footer 30. Sidebar 240
# fixed, content flexible, right rail 320 fixed, so only the middle grows when
# the window is resized.
UI_SIZES = {
    "window_min_width": 1024, "window_min_height": 680,
    "window_default_width": 1680, "window_default_height": 1040,
    "titlebar_height": 36, "header_height": 52, "banner_height": 68, "footer_height": 30,
    "sidebar_width": 240, "sidebar_compact_width": 56,
    "right_rail_width": 320, "content_min_width": 560,
    "quick_menu_width": 248,
    "card_gap": 16, "panel_pad": 16, "panel_pad_dense": 12,
    "row_height": 32, "list_row_height": 48,
    "field_width": 132, "field_wide_width": 190,
    "control_height": 32, "control_height_sm": 26,
    "rail_collapse_width": 1440,
    "sidebar_compact_breakpoint": 1200,
    "divider": 1, "overlay_stroke": 2, "page_fade_ms": 140,
    "message_poll_ms": 40, "settings_debounce_ms": 140,
    "binding_poll_ms": 20, "preview_size": 240,
    "preview_max_width": 360,
}
