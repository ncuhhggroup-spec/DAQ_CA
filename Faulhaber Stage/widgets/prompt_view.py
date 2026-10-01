# widgets/prompt_view.py
"""
PromptViewWidget - displays the system prompt loaded from Prompt.docx.
Future integration point for a Conversational Assistant (CA) can be added here.
"""

from pathlib import Path
from PyQt6.QtWidgets import QWidget, QVBoxLayout, QTextEdit, QLabel
from PyQt6.QtCore import Qt

# Optional: Import python-docx if available, otherwise fallback to plain text placeholder.
try:
    from docx import Document
except ImportError:
    Document = None


class PromptViewWidget(QWidget):
    """Widget that loads and displays the content of `Prompt.docx`.

    The widget shows the prompt in a read‑only QTextEdit. In the future, this
    area can be extended to host a conversational assistant UI.
    """

    def __init__(self, parent=None, prompt_path: str = "Prompt.docx"):
        super().__init__(parent)
        self.prompt_path = Path(prompt_path)
        self._setup_ui()
        self._load_prompt()

    def _setup_ui(self):
        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(4)

        title = QLabel("System Prompt")
        title.setAlignment(Qt.AlignmentFlag.AlignCenter)
        title.setStyleSheet(
            "font-weight: 600; color: #38BDF8; font-size: 14px; margin-bottom: 4px;"
        )
        layout.addWidget(title)

        self.text_edit = QTextEdit(self)
        self.text_edit.setReadOnly(True)
        self.text_edit.setStyleSheet(
            "background-color: #0F172A; color: #F8FAFC; border: 1px solid #334155; border-radius: 6px;"
        )
        layout.addWidget(self.text_edit, 1)

    def _load_prompt(self):
        if not self.prompt_path.is_file():
            self.text_edit.setPlainText(f"Prompt file not found: {self.prompt_path}")
            return

        if Document is None:
            # Fallback: read raw text if the file is plain text.
            try:
                content = self.prompt_path.read_text(encoding="utf-8")
                self.text_edit.setPlainText(content)
            except Exception as e:
                self.text_edit.setPlainText(f"Unable to read prompt: {e}")
            return

        try:
            doc = Document(self.prompt_path)
            full_text = []
            for para in doc.paragraphs:
                full_text.append(para.text)
            self.text_edit.setPlainText("\n".join(full_text))
        except Exception as e:
            self.text_edit.setPlainText(f"Error loading Prompt.docx: {e}")
