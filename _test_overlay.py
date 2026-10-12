"""Render the preview overlay (body box + head box + crosshair line) to PNG."""
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent
for folder in (ROOT, ROOT / "engine", ROOT / "app", ROOT / "ui", ROOT / "ui" / "disabled_ai"):
    sys.path.insert(0, str(folder))

import cv2
import numpy as np

from qt import QApplication, QTimer
import theme
from main_window import MainWindow

app = QApplication([])
theme.apply(app)
window = MainWindow()

# A synthetic FOV crop: mid-grey with a lighter "player" rectangle.
fov = 320
frame = np.full((fov, fov, 3), 45, dtype=np.uint8)
frame[80:260, 120:200] = (90, 90, 100)

boxes = [(120.0, 80.0, 200.0, 260.0, 0.87, 0)]
window._values["fov"] = fov
window._values["preview_overlay"] = True
window._values["preview_head_box"] = True
window._values["preview_distance_line"] = True

size = 360
mini = cv2.resize(frame, (size, size), interpolation=cv2.INTER_AREA)
window._draw_preview_boxes(mini, boxes, size, fov)
cv2.imwrite(str(ROOT / "_overlay_test.png"), mini)
print("wrote _overlay_test.png")

# Confirm the overlay actually marked pixels: count head-box-blue pixels.
blue = int(((mini[:, :, 0] > 200) & (mini[:, :, 1] > 150) & (mini[:, :, 2] < 120)).sum())
green = int(((mini[:, :, 1] > 180) & (mini[:, :, 0] < 120) & (mini[:, :, 2] < 120)).sum())
print("head-box pixels:", blue, " body/line pixels:", green)

QTimer.singleShot(100, app.quit)
app.exec()
