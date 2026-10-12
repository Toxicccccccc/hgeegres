disabled_input_style = """
QLineEdit:disabled {
    background-color: rgba(0, 0, 0, 0.2);
    border: none;
    opacity: 0.05;
}
"""

sidebar_style = """
QFrame {
    background: transparent;
}
QFrame#sidebar {
    background-color: rgba(100, 100, 100, 0.12);
}
"""
sidebar_btn_style = """
QWidget {
    background: transparent;
}
"""
discord_btn_style = """
QWidget {
    background: transparent;
    border: none;
}
"""
# This is for each "element" that holds sliders/buttons/dropdowns/etc.
# Unfortunately this cant be refreshed using the refresh button
#background: rgba(0, 0, 0, 0.45);
card_style = """
QFrame {
    background: transparent;
    border-radius: 12px;
    padding: 10px;
}
QLabel {
    background: transparent;
}
"""
card_title_style = """
QLabel {
    font-weight: bold;
    font-size: 11pt;
    background: transparent;
}
"""

# This is for the 3 floating buttons on the bottom right
floating_buttons_style = """ 
QPushButton {
    border-radius: 26px;
    background-color: #222;
}
QPushButton:hover {
    background-color: #333;
}
"""

# This is for the popups you see when you click for example "Save Settings"
popup_style = """
QWidget {
    background-color: #121212;
}
QLabel {
    text-align: center;
    margin-right: 30px;
    margin-top: 40px;
    margin-bottom: 15px;
    background-color: #121212;
    color: #fff;
}
QPushButton {
    padding: 5px 20px;
    border: 1px solid #333;
    border-radius: 6px;
}
QPushButton:hover {
    border: 1px solid #777;
}
"""

# For setting up custom background image
use_custom_background_image = False
background_image_path = "lib/assets/bg.png" # WEB URLs might not work

frosted_glass_effect = False

# Setting this to transparent will allow you to see the background image
scroll_style = """
QScrollArea {
    border: none;
    background: transparent;
}
"""
tab_style = """
QWidget {
}
"""
#to use image put this in the QWidget below:
#background: transparent; 
style = """
QWidget {
    background: transparent;
    color: #eaeaea;
    font-size: 10.5pt;
}

QLabel {
    background: transparent;
}

QWidget#main_tab {

}

QWidget#main_scroll {

}


QWidget#advanced_tab {
}

QWidget#account_tab {
}

QLabel {
    font-weight: 500;
}

QFrame {
    border: none;
}

QLineEdit {
    border: 1px solid #2e2e2e;
    border-radius: 6px;
    padding: 6px 10px;
    background-color: #151515;
    color: #eaeaea;
    selection-background-color: #4169E1;
}
QLineEdit:focus {
    border: 1px solid #4169E1;
}

QPushButton {
    background-color: #1c1c1c;
    border: 2px solid #2c2c2c;
    border-radius: 18px;
    padding: 8px 16px;
    font-weight: 600;
    color: #eaeaea;
}
QPushButton:hover {
    background-color: #242424;
    border-color: #3a3a3a;
}
QPushButton:pressed {
    background-color: #303030;
    border-color: #4169E1;
}

QPushButton#colorButton {
    border: 2px solid #333;
    font-weight: bold;
    padding: 8px;
    border-radius: 6px;
    color: #000;
}
QPushButton#colorButton[styleSheet*="background-color: rgb(0, 0, 0)"] {
    color: white;
}
QPushButton#colorButton:disabled {
    color: #444;
}

QCheckBox {
    background: transparent;
    padding: 3px;
    spacing: 8px;
}
QCheckBox::indicator {
    width: 16px;
    height: 16px;
    border-radius: 10px;
    border: 2px solid #444;
}
QCheckBox::indicator:checked {
    background-color: #c66fff;
    border: 2px solid #c66fff;
}

QSlider {
    padding: 4px 0;
    background: transparent;
    border: none;
}
QSlider::groove:horizontal {
    background: transparent;
    border-radius: 4px;
    padding: 1px;
    height: 6px;
    margin: 0px;
}
QSlider::sub-page:horizontal {
    background: qlineargradient(x1: 0, y1: 0, x2: 1, y2: 0,
                stop: 0 #3a8dde,
                stop: 0.5 #4169E1,
                stop: 1 #7a6ff0);
    border-radius: 4px;
}

QSlider::add-page:horizontal {
    background: #333333;
    border-radius: 4px;
}
QSlider::handle:horizontal {
    background-color: #F2F2F2;
    border: none;
    width: 14px;
    height: 14px;
    border-radius: 7px;
    margin: -4px 0;
}
QSlider::handle:horizontal:hover {
    background-color: #F2F2F2;
}

NoScrollComboBox {
    background-color: #151515;
    border: 1px solid #2e2e2e;
    border-radius: 6px;
    padding: 6px 32px 6px 10px;
    color: #eaeaea;
    font-weight: 500;
}

NoScrollComboBox:hover {
    border: 1px solid #4169E1;
    background-color: #1b1b1b;
}

NoScrollComboBox:focus {
    border: 1px solid #7a6ff0;
    background-color: #1c1c1c;
}

NoScrollComboBox::drop-down {
    subcontrol-origin: padding;
    subcontrol-position: top right;
    width: 28px;
    border-left: 1px solid #2e2e2e;
    background-color: #1c1c1c;
    border-top-right-radius: 6px;
    border-bottom-right-radius: 6px;
}

NoScrollComboBox::down-arrow {
    image: url(lib/assets/arrow-down-light.svg);
    width: 12px;
    height: 12px;
}

NoScrollComboBox QAbstractItemView {
    background-color: #202020;
    border: 1px solid #2e2e2e;
    border-radius: 6px;
    padding: 4px;
    color: #eaeaea;
    selection-background-color: #7a6ff0;
    selection-color: #ffffff;
    outline: none;
}

NoScrollComboBox QAbstractItemView::item {
    padding: 6px 10px;
    border-radius: 4px;
}

NoScrollComboBox QAbstractItemView::item:hover {
    background-color: #2a2a2a;
}

QScrollBar:vertical {
    border: none;
    background: #151515;
    width: 10px;
}
QScrollBar::handle:vertical {
    background: qlineargradient(x1: 0, y1: 0, x2: 0, y2: 1,
                stop: 0 #3a8dde,
                stop: 0.5 #4169E1,
                stop: 1 #4169E1);
    border-radius: 3px;
    min-height: 20px;
}
QScrollBar::handle:vertical:hover {
    background: qlineargradient(x1: 0, y1: 0, x2: 0, y2: 1,
                stop: 0 #3a8dde,
                stop: 0.5 #4169E1,
                stop: 1 #4169E1);
}
QScrollBar::add-line:vertical,
QScrollBar::sub-line:vertical {
    height: 0px;
    background: none;
    border: none;
}

QTabBar::tab {
    border: 1px solid #2c2c2c;
    padding: 6px 14px;
    border-top-left-radius: 6px;
    border-top-right-radius: 6px;
    color: #b0b0b0;
    font-weight: 600;
}
QTabBar::tab:selected {
    color: #ffffff;
    border-bottom: 2px solid #3a8dde;
}
QTabBar::tab:hover {
    background: #222;
    color: #ffffff;
}
QTabWidget::pane {
    border: none;
    margin-top: -1px;
}

QPushButton[selected="true"] {
    background-color: #b74aff;
    border: 2px solid #4169E1;
}

QCheckBox, QSlider, QLineEdit, QComboBox {
    margin-left: 10px;
    margin-right: 10px;
}

"""
