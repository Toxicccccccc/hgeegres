"""Login dialog shown when the backend needs credentials."""

from PyQt6.QtCore import Qt
from PyQt6.QtWidgets import (
    QDialog, QVBoxLayout, QLabel, QLineEdit,
    QFormLayout, QDialogButtonBox,
)


class LoginDialog(QDialog):
    def __init__(self, parent=None, username: str = "", message: str = "",
                 app_name: str = "Lunar V2"):
        super().__init__(parent)
        self.setWindowTitle(f"{app_name} Login")
        self.setModal(True)
        self.setMinimumWidth(360)

        lay = QVBoxLayout(self)
        lay.setSpacing(12)

        hint = QLabel(message or "Sign in to continue.")
        hint.setWordWrap(True)
        hint.setObjectName("hint")
        lay.addWidget(hint)

        form = QFormLayout()
        self.user_edit = QLineEdit(username or "")
        self.user_edit.setPlaceholderText("Username")
        self.pass_edit = QLineEdit()
        self.pass_edit.setEchoMode(QLineEdit.EchoMode.Password)
        self.pass_edit.setPlaceholderText("Password")
        form.addRow("Username", self.user_edit)
        form.addRow("Password", self.pass_edit)
        lay.addLayout(form)

        buttons = QDialogButtonBox(
            QDialogButtonBox.StandardButton.Ok | QDialogButtonBox.StandardButton.Cancel
        )
        buttons.button(QDialogButtonBox.StandardButton.Ok).setText("Login")
        buttons.accepted.connect(self.accept)
        buttons.rejected.connect(self.reject)
        lay.addWidget(buttons)

        if username:
            self.pass_edit.setFocus(Qt.FocusReason.OtherFocusReason)
        else:
            self.user_edit.setFocus(Qt.FocusReason.OtherFocusReason)

    def credentials(self) -> tuple[str, str]:
        return self.user_edit.text().strip(), self.pass_edit.text()
