"""The fpdf2 document both reports are drawn on.

Replaced WeasyPrint on 2026-08-23: WeasyPrint needs GTK/Pango, which pip does
not ship on Windows, so it could not import on the dev machine at all. fpdf2 is
pure Python and renders the same here as on the ECS box. See PROJECT_LOG.md.

Two things in here are load-bearing and easy to break:

1. `set_text_shaping(True)` plus uharfbuzz. Without it Urdu comes out as
   disconnected letters in left-to-right order - unreadable. The patient's own
   words are quoted verbatim in the doctor report and ASR returns Urdu script,
   so this path is always exercised.
2. The fonts are bundled in `fonts/`, not taken from the system. Noto Sans
   carries the Latin text and Noto Naskh Arabic is registered as its fallback,
   because Noto Naskh has no Latin glyphs and a core font like Helvetica
   raises before fallback can engage. A bare Ubuntu box has neither font
   installed, so bundling is what makes the ECS output match this one.
"""

from __future__ import annotations

import logging
from pathlib import Path

from fpdf import FPDF
from fpdf.enums import Align, XPos, YPos

log = logging.getLogger(__name__)

FONT_DIR = Path(__file__).parent / "fonts"

#: Latin body font, and the one every set_font call names.
SANS = "notosans"
#: Registered as SANS's fallback so Urdu inside an otherwise English line -
#: a verbatim quote - renders without the caller doing anything.
NASKH = "notonaskh"

PAGE_W = 210.0          # A4 portrait, mm
MARGIN = 16.0
CONTENT_W = PAGE_W - 2 * MARGIN

INK = (33, 37, 41)
MUTED = (110, 117, 125)
RULE = (222, 226, 230)
WASH = (247, 248, 250)
GOOD = (30, 126, 82)
WARN = (176, 96, 22)
BAD = (176, 42, 42)


class MissingFont(RuntimeError):
    """The bundled fonts are not where they should be."""


class Report(FPDF):
    """A4 portrait with the fonts and the footer already set up.

    `accent` colours the rules and headings, and is the one visual difference
    between the clinical report and the warm one.
    """

    def __init__(self, accent: tuple[int, int, int], footer_note: str = "") -> None:
        super().__init__(orientation="P", unit="mm", format="A4")
        self.accent = accent
        self.footer_note = footer_note
        self.set_margins(MARGIN, MARGIN, MARGIN)
        self.set_auto_page_break(True, margin=18)
        self._load_fonts()
        self.set_text_shaping(True)
        self.add_page()

    # -- setup -----------------------------------------------------------

    def _load_fonts(self) -> None:
        faces = {
            (SANS, ""): "NotoSans-Regular.ttf",
            (SANS, "B"): "NotoSans-Bold.ttf",
            (NASKH, ""): "NotoNaskhArabic-Regular.ttf",
            (NASKH, "B"): "NotoNaskhArabic-Bold.ttf",
        }
        for (family, style), filename in faces.items():
            path = FONT_DIR / filename
            if not path.exists():
                raise MissingFont(
                    f"{path} is missing. The report fonts are committed to the "
                    f"repo on purpose - see AGENTS.md section 6."
                )
            self.add_font(family, style, str(path))
        # Urdu inside a Latin line resolves through here.
        self.set_fallback_fonts([NASKH])

    def footer(self) -> None:
        self.set_y(-14)
        self.set_font(SANS, size=7)
        self.set_text_color(*MUTED)
        self.cell(CONTENT_W - 20, 4, self.footer_note, align=Align.L)
        self.cell(20, 4, str(self.page_no()), align=Align.R)
        self.set_text_color(*INK)

    # -- primitives ------------------------------------------------------

    def title_block(self, title: str, subtitle: str, right: str = "") -> None:
        self.set_font(SANS, "B", 17)
        self.set_text_color(*self.accent)
        self.cell(CONTENT_W - 42, 9, title, new_x=XPos.RIGHT, new_y=YPos.TOP)

        self.set_font(SANS, size=8)
        self.set_text_color(*MUTED)
        self.cell(42, 9, right, align=Align.R,
                  new_x=XPos.LMARGIN, new_y=YPos.NEXT)

        self.set_font(SANS, size=10)
        self.set_text_color(*INK)
        self.multi_cell(CONTENT_W, 5.5, subtitle,
                        new_x=XPos.LMARGIN, new_y=YPos.NEXT)
        self.ln(2.5)
        self.rule(thick=True)
        self.ln(4)

    def rule(self, thick: bool = False) -> None:
        self.set_draw_color(*(self.accent if thick else RULE))
        self.set_line_width(0.6 if thick else 0.2)
        y = self.get_y()
        self.line(MARGIN, y, PAGE_W - MARGIN, y)
        self.set_line_width(0.2)

    def heading(self, text: str) -> None:
        self._keep_together(14)
        self.set_font(SANS, "B", 9.5)
        self.set_text_color(*self.accent)
        self.cell(CONTENT_W, 6, text.upper(),
                  new_x=XPos.LMARGIN, new_y=YPos.NEXT)
        self.set_text_color(*INK)
        self.rule()
        self.ln(2.5)

    def body(self, text: str, size: float = 10, gap: float = 2.0,
             colour: tuple[int, int, int] | None = None,
             indent: float = 0.0) -> None:
        self.set_font(SANS, size=size)
        self.set_text_color(*(colour or INK))
        self.set_x(MARGIN + indent)
        self.multi_cell(CONTENT_W - indent, size * 0.52, text,
                        new_x=XPos.LMARGIN, new_y=YPos.NEXT)
        self.set_text_color(*INK)
        if gap:
            self.ln(gap)

    def facts(self, pairs: list[tuple[str, str]],
              widths: list[float] | None = None) -> None:
        """A row of label/value pairs - the header stats.

        `widths` are fractions of the content width and must sum to 1. They
        are worth setting by hand: a date range needs roughly twice the room
        of a percentage, and an equal split silently overlaps the next value.
        """
        if widths is None:
            widths = [1 / len(pairs)] * len(pairs)
        cols = [CONTENT_W * w for w in widths]
        offsets = [MARGIN + sum(cols[:i]) for i in range(len(cols))]
        top = self.get_y()

        self.set_font(SANS, size=7.5)
        self.set_text_color(*MUTED)
        for x, width, (label, _) in zip(offsets, cols, pairs):
            self.set_xy(x, top)
            self.cell(width, 4, label.upper())

        self.set_font(SANS, "B", 11)
        self.set_text_color(*INK)
        for x, width, (_, value) in zip(offsets, cols, pairs):
            self.set_xy(x, top + 4)
            self.cell(width, 6, value)

        self.set_xy(MARGIN, top + 11)
        self.ln(1)

    def table(self, headers: list[str], rows: list[list[str]],
              widths: list[float], aligns: str = "") -> None:
        """A plain table. `widths` are fractions of the content width."""
        cols = [CONTENT_W * w for w in widths]
        aligns = aligns or "L" * len(headers)

        self._keep_together(16)
        self.set_font(SANS, "B", 8)
        self.set_text_color(*MUTED)
        self.set_fill_color(*WASH)
        for width, head, align in zip(cols, headers, aligns):
            self.cell(width, 6, head.upper(), align=align, fill=True)
        self.ln(6)

        self.set_font(SANS, size=9)
        self.set_text_color(*INK)
        for row in rows:
            self._keep_together(8)
            for width, cell, align in zip(cols, row, aligns):
                self.cell(width, 5.6, cell, align=align)
            self.ln(5.6)
            self.set_draw_color(*RULE)
            self.line(MARGIN, self.get_y(), PAGE_W - MARGIN, self.get_y())
        self.ln(3)

    #: Left offset of a quote's text, so a line that is NOT a quote can be
    #: indented to match instead of sitting alone against the margin.
    QUOTE_INDENT = 6.0

    def quote(self, said: str, attribution: str,
              attribution_colour: tuple[int, int, int] | None = None,
              bar_colour: tuple[int, int, int] | None = None) -> None:
        """A verbatim line from the patient, marked as theirs and untouched."""
        self._keep_together(14)
        left = MARGIN + 3
        top = self.get_y()

        self.set_font(SANS, size=9.5)
        self.set_text_color(*INK)
        self.set_xy(MARGIN + self.QUOTE_INDENT, top)
        self.multi_cell(CONTENT_W - self.QUOTE_INDENT, 5, said,
                        new_x=XPos.LMARGIN, new_y=YPos.NEXT)

        self.set_x(MARGIN + self.QUOTE_INDENT)
        self.set_font(SANS, size=7.5)
        self.set_text_color(*(attribution_colour or MUTED))
        self.cell(CONTENT_W - self.QUOTE_INDENT, 4, attribution,
                  new_x=XPos.LMARGIN, new_y=YPos.NEXT)

        self.set_draw_color(*(bar_colour or self.accent))
        self.set_line_width(0.8)
        self.line(left, top, left, self.get_y() - 0.5)
        self.set_line_width(0.2)
        self.set_text_color(*INK)
        self.ln(2.5)

    def callout(self, text: str, colour: tuple[int, int, int] | None = None) -> None:
        """A boxed line that must not be skimmed past."""
        colour = colour or MUTED
        self._keep_together(16)
        top = self.get_y()
        self.set_font(SANS, size=8.5)
        self.set_text_color(*colour)
        self.set_fill_color(*WASH)
        self.set_xy(MARGIN, top)
        self.multi_cell(CONTENT_W, 4.6, text, fill=True, border=0,
                        padding=(2.5, 3, 2.5, 3),
                        new_x=XPos.LMARGIN, new_y=YPos.NEXT)
        self.set_text_color(*INK)
        self.ln(2)

    def _keep_together(self, height: float) -> None:
        """Start a new page rather than orphan a heading at the bottom."""
        if self.get_y() + height > self.h - self.b_margin:
            self.add_page()

    def render(self) -> bytes:
        return bytes(self.output())
