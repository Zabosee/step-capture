"""PDF-Export der Anleitung (reportlab)."""
from __future__ import annotations

import logging
import os
from datetime import datetime
from pathlib import Path
from typing import Iterable, Optional
from xml.sax.saxutils import escape

from PIL import Image
from reportlab.lib import colors
from reportlab.lib.enums import TA_CENTER
from reportlab.lib.pagesizes import A4
from reportlab.lib.styles import ParagraphStyle, getSampleStyleSheet
from reportlab.lib.units import cm
from reportlab.pdfbase import pdfmetrics
from reportlab.pdfbase.ttfonts import TTFont
from reportlab.platypus import (CondPageBreak, Image as RLImage, KeepTogether, Paragraph,
                                SimpleDocTemplate, Spacer, Table, TableStyle)

from .exporter import IMAGE_WIDTH_CM, NOTE_FILLS, ZOOM_WIDTH_CM, prepare_images
from .models import Step, clean_text

log = logging.getLogger(__name__)

CODE_LINE_CHARS = 90        # maximale Zeichen je Zeile im Textfeld "Eingegebener Text"

_FONT_DIRS = [os.path.join(os.environ.get("WINDIR", r"C:\Windows"), "Fonts"),
              "/usr/share/fonts/truetype/dejavu", "/Library/Fonts"]


def _register(name: str, candidates) -> Optional[str]:
    """Registriert die erste vorhandene TrueType-Schrift (für Umlaute und Sonderzeichen)."""
    for directory in _FONT_DIRS:
        for file in candidates:
            path = os.path.join(directory, file)
            if os.path.exists(path):
                try:
                    pdfmetrics.registerFont(TTFont(name, path))
                    return name
                except Exception:
                    log.debug("Schrift %s nicht ladbar", path, exc_info=True)
    return None


def _fonts():
    """(Normal, Fett, Kursiv, Monospace); Fallback auf die eingebauten Helvetica/Courier."""
    normal = _register("PR-Normal", ["segoeui.ttf", "arial.ttf", "DejaVuSans.ttf"])
    bold = _register("PR-Bold", ["segoeuib.ttf", "arialbd.ttf", "DejaVuSans-Bold.ttf"])
    italic = _register("PR-Italic", ["segoeuii.ttf", "ariali.ttf", "DejaVuSans-Oblique.ttf"])
    mono = _register("PR-Mono", ["consola.ttf", "cour.ttf", "DejaVuSansMono.ttf"])
    return (normal or "Helvetica", bold or normal and "PR-Normal" or "Helvetica-Bold",
            italic or normal and "PR-Normal" or "Helvetica-Oblique", mono or "Courier")


def _paragraph(text: str, style) -> Paragraph:
    return Paragraph(escape(clean_text(text)).replace("\n", "<br/>"), style)


def _image(buf, width_cm: float) -> RLImage:
    with Image.open(buf) as im:
        w, h = im.size
    buf.seek(0)
    width = width_cm * cm
    return RLImage(buf, width=width, height=width * h / w)


def export_pdf(steps: Iterable[Step], output: Path, monitor_label: str = "",
               title: str = "", intro: str = "", outro: str = "", zoom: bool = True) -> Path:
    """Erzeugt die Anleitung als PDF und gibt den Pfad zurück."""
    steps = list(steps)
    title, intro, monitor_label = clean_text(title), clean_text(intro), clean_text(monitor_label)
    outro = clean_text(outro)
    normal, bold, italic, mono = _fonts()
    base = getSampleStyleSheet()
    body = ParagraphStyle("body", parent=base["Normal"], fontName=normal, fontSize=10.5, leading=15)
    meta = ParagraphStyle("meta", parent=body, fontName=italic, textColor=colors.HexColor("#555555"))
    h_title = ParagraphStyle("title", parent=body, fontName=bold, fontSize=22, leading=27,
                             spaceAfter=8)
    h_step = ParagraphStyle("step", parent=body, fontName=bold, fontSize=13, leading=17,
                            textColor=colors.HexColor("#1F2340"), spaceBefore=14, spaceAfter=3)
    h_section = ParagraphStyle("section", parent=h_step, fontSize=16, leading=20, spaceBefore=18,
                               spaceAfter=2)
    caption = ParagraphStyle("caption", parent=meta, alignment=TA_CENTER, fontSize=9)
    label = ParagraphStyle("label", parent=body, fontName=bold, fontSize=9.5)
    code = ParagraphStyle("code", parent=body, fontName=mono, fontSize=10, leading=13,
                          wordWrap="CJK")

    story = [_paragraph(title.strip() or "Prozessdokumentation", h_title)]
    if intro.strip():
        story += [_paragraph(intro.strip(), body), Spacer(1, 6)]
    info = f"Erstellt am {datetime.now():%d.%m.%Y um %H:%M} Uhr"
    if monitor_label:
        info += f"\nAufgenommener Bildschirm: {monitor_label}"
    info += f"\nAnzahl Schritte: {len(steps)}"
    story.append(_paragraph(info, meta))

    images = prepare_images(steps, zoom)
    def box(rows, fill):
        table = Table(rows, colWidths=[17 * cm])
        table.setStyle(TableStyle([("BACKGROUND", (0, 0), (-1, -1), colors.HexColor(fill)),
                                   ("BOX", (0, 0), (-1, -1), 0.5, colors.HexColor("#BBBBBB")),
                                   ("LEFTPADDING", (0, 0), (-1, -1), 8)]))
        return table

    def note(step):
        if not step.note.strip():
            return []
        fill = "#" + NOTE_FILLS.get(step.note_kind, NOTE_FILLS["Hinweis"])
        return [Spacer(1, 6), box([[_paragraph(f"{step.note_kind}:", label)],
                                   [_paragraph(step.note.strip(), body)]], fill)]

    for number, (step, (image, zoomed)) in enumerate(zip(steps, images), start=1):
        if step.section.strip():
            story.append(CondPageBreak(6 * cm))
            story.append(_paragraph(step.section.strip(), h_section))
        block = [_paragraph(f"Schritt {number}", h_step),
                 _paragraph(step.text_for_export(), body), Spacer(1, 4)]
        if step.kind == "protected":
            hint = box([[_paragraph("Hinweis: Dieser Bereich wurde bewusst nicht aufgezeichnet.",
                                    body)]], "#FFF2CC")
            story.append(KeepTogether(block + [hint] + note(step)))
            continue
        if image is not None:
            block.append(_image(image, IMAGE_WIDTH_CM))
        story.append(KeepTogether(block))
        if zoomed is not None:
            story.append(KeepTogether([Spacer(1, 4), _paragraph("Ausschnitt (vergrößert)", caption),
                                       _image(zoomed, ZOOM_WIDTH_CM)]))
        if step.kind == "text" and step.text:
            # eine Zeile je Textzeile, damit die Tabelle über Seiten hinweg umbrechen kann
            rows = [[_paragraph("Eingegebener Text zum Kopieren:", label)]]
            # lange Zeichenketten ohne Leerzeichen hart umbrechen (sonst LayoutError)
            rows += [[_paragraph(line[i:i + CODE_LINE_CHARS], code)]
                     for line in clean_text(step.text).split("\n")
                     for i in range(0, max(len(line), 1), CODE_LINE_CHARS)]
            story += [Spacer(1, 4), box(rows, "#F2F2F2")]
        story += note(step)

    if outro.strip():
        story += [_paragraph("Abschluss", h_section), _paragraph(outro.strip(), body)]

    output = Path(output)
    SimpleDocTemplate(str(output), pagesize=A4, leftMargin=2 * cm, rightMargin=2 * cm,
                      topMargin=2 * cm, bottomMargin=2 * cm,
                      title=title.strip() or "Prozessdokumentation").build(story)
    return output
