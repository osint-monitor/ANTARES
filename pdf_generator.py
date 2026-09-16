# -*- coding: utf-8 -*-
"""
Generazione server-side del Report PDF per A.N.T.A.R.E.S.
Il PDF è costruito interamente lato server con reportlab: output
vettoriale, deterministico, senza dipendenze di sistema pesanti (nessun
Chromium/wkhtmltopdf/Cairo richiesto — solo `pip install reportlab`).

Lo stile non replica il tema scuro dell'interfaccia web: è pensato apposta
per la carta, con una gerarchia tipografica pulita e accenti colore per
distinguere le sezioni (stesso schema colori dell'app, in versione chiara).

── LOCALIZZAZIONE (IT/EN) ───────────────────────────────────────────
Le etichette statiche (titoli sezione, intestazioni, footer...) sono
centralizzate nel dizionario TR qui sotto e risolte con tr(key, lang).
Il contenuto vero e proprio (output dell'IA, Red/Blue Team) NON viene
tradotto qui: la lingua di quel testo dipende dal prompt con cui è stato
generato (vedi campo `lang` salvato per ogni task in app.py/database.py).
Tutte le funzioni pubbliche accettano un parametro `lang` ("it"/"en"),
che il chiamante (le route Flask) valorizza con la lingua attiva di
flask-babel al momento del download.
"""

import re
import json
import io
from functools import partial
from xml.sax.saxutils import escape as xml_escape

from reportlab.lib.pagesizes import A4, landscape
from reportlab.lib.units import mm
from reportlab.lib import colors
from reportlab.lib.styles import ParagraphStyle
from reportlab.lib.enums import TA_LEFT
from reportlab.platypus import (
    SimpleDocTemplate, Paragraph, Spacer, Table, TableStyle,
    ListFlowable, ListItem, KeepTogether, HRFlowable
)


# ══════════════════════════════════════════════════════════════════
# I18N — etichette statiche del PDF (IT/EN)
# ══════════════════════════════════════════════════════════════════
DEFAULT_LANG = "it"

TR = {
    "it": {
        "na": "N/D",
        "eyebrow": "A.N.T.A.R.E.S. — TASK MONITOR",
        "report_operativo": "Report Operativo",
        "meta_attore": "ATTORE",
        "meta_backend": "BACKEND AI",
        "meta_avvio": "AVVIO",
        "meta_fine": "FINE",
        "meta_testo_origine": "TESTO ORIGINE",

        "red_team_title": "RED TEAM &mdash; Analisi PSYOPS",
        "red_team_title_matrix": "RED TEAM &mdash; Matrice Analisi PSYOPS",
        "blue_team_title": "BLUE TEAM &mdash; Playbook di Contrasto FIMI",
        "blue_team_title_matrix": "BLUE TEAM &mdash; Matrice Playbook di Contrasto",

        "raw_output_error": "Raw Output (errore di parsing)",
        "field_psyops_objectives": "Obiettivi PSYOPS",
        "field_target_audience": "Target Audience",
        "field_product_dev": "Prodotti e Tattiche",
        "field_social_payload": "Payload Social",
        "field_indicators": "Indicatori di Amplificazione",
        "field_disarm": "Tecniche DISARM",
        "field_weak_spots": "Punti Deboli dell'Attore",
        "score_virulence": "VIRULENZA",
        "score_impact": "IMPATTO STRATEGICO",
        "risk_assessment": "Risk Assessment",

        "no_blue_output": "Nessun output Blue Team disponibile.",

        "footer_text": "A.N.T.A.R.E.S. — Documento generato automaticamente. Uso riservato.",
        "footer_page": "Pagina {n}",

        "matrice_comparativa": "Matrice Comparativa",
        "gruppo": "Gruppo",
        "meta_attori_confrontati": "ATTORI CONFRONTATI",
        "meta_creato_il": "CREATO IL",
        "evento_testo_origine": "EVENTO (TESTO ORIGINE)",
        "no_tasks_found": "Nessun task trovato per questo gruppo.",

        "matrix_metrica": "METRICA",

        "status_pending": "IN CODA",
        "status_processing": "IN ELABORAZIONE (RED)",
        "status_processing_blue": "IN ELABORAZIONE (BLUE)",
        "status_error": "ERRORE",

        "metric_risk_assessment": "Risk Assessment",
        "metric_psyops_objectives": "Obiettivi PSYOPS",
        "metric_target_audience": "Target Audience",
        "metric_social_payload": "Payload Social",
        "metric_disarm": "Tecniche DISARM",
        "metric_weak_spots": "Punti Deboli",

        "metric_blue_threat": "Valutazione Minaccia",
        "metric_blue_counter": "Contro-Narrativa",
        "metric_blue_media": "Direttive Media",
        "metric_blue_osint": "Piano OSINT",
        "metric_blue_debunk": "Debunking",
        "metric_blue_escalation": "Escalation",
    },
    "en": {
        "na": "N/A",
        "eyebrow": "A.N.T.A.R.E.S. — TASK MONITOR",
        "report_operativo": "Operational Report",
        "meta_attore": "ACTOR",
        "meta_backend": "AI BACKEND",
        "meta_avvio": "STARTED",
        "meta_fine": "ENDED",
        "meta_testo_origine": "SOURCE TEXT",

        "red_team_title": "RED TEAM &mdash; PSYOPS Analysis",
        "red_team_title_matrix": "RED TEAM &mdash; PSYOPS Analysis Matrix",
        "blue_team_title": "BLUE TEAM &mdash; FIMI Counter Playbook",
        "blue_team_title_matrix": "BLUE TEAM &mdash; Counter Playbook Matrix",

        "raw_output_error": "Raw Output (parsing error)",
        "field_psyops_objectives": "PSYOPS Objectives",
        "field_target_audience": "Target Audience",
        "field_product_dev": "Products & Tactics",
        "field_social_payload": "Social Payload",
        "field_indicators": "Amplification Indicators",
        "field_disarm": "DISARM Techniques",
        "field_weak_spots": "Actor's Weak Spots",
        "score_virulence": "VIRULENCE",
        "score_impact": "STRATEGIC IMPACT",
        "risk_assessment": "Risk Assessment",

        "no_blue_output": "No Blue Team output available.",

        "footer_text": "A.N.T.A.R.E.S. — Automatically generated document. Restricted use.",
        "footer_page": "Page {n}",

        "matrice_comparativa": "Comparison Matrix",
        "gruppo": "Group",
        "meta_attori_confrontati": "ACTORS COMPARED",
        "meta_creato_il": "CREATED ON",
        "evento_testo_origine": "EVENT (SOURCE TEXT)",
        "no_tasks_found": "No tasks found for this group.",

        "matrix_metrica": "METRIC",

        "status_pending": "QUEUED",
        "status_processing": "PROCESSING (RED)",
        "status_processing_blue": "PROCESSING (BLUE)",
        "status_error": "ERROR",

        "metric_risk_assessment": "Risk Assessment",
        "metric_psyops_objectives": "PSYOPS Objectives",
        "metric_target_audience": "Target Audience",
        "metric_social_payload": "Social Payload",
        "metric_disarm": "DISARM Techniques",
        "metric_weak_spots": "Weak Spots",

        "metric_blue_threat": "Threat Assessment",
        "metric_blue_counter": "Counter-Narrative",
        "metric_blue_media": "Media Directives",
        "metric_blue_osint": "OSINT Plan",
        "metric_blue_debunk": "Debunking",
        "metric_blue_escalation": "Escalation",
    },
}


def tr(key, lang):
    """Risolve un'etichetta statica nella lingua richiesta (fallback: DEFAULT_LANG)."""
    table = TR.get(lang, TR[DEFAULT_LANG])
    return table.get(key, TR[DEFAULT_LANG].get(key, key))


STATUS_LABEL_KEYS = {
    "pending":         "status_pending",
    "processing":      "status_processing",
    "processing_blue": "status_processing_blue",
    "error":           "status_error",
}


# ══════════════════════════════════════════════════════════════════
# PALETTE — versione "print-safe" (chiara) del tema ANTARES
# ══════════════════════════════════════════════════════════════════
COL_TEXT        = colors.HexColor('#1a1a1a')
COL_TEXT_MUTED  = colors.HexColor('#767676')
COL_BORDER      = colors.HexColor('#dddddd')
COL_BG_LIGHT    = colors.HexColor('#f7f7f7')
COL_BG_WHITE    = colors.white

COL_RED    = colors.HexColor('#b93a2e')
COL_AMBER  = colors.HexColor('#b98a2e')
COL_BLUE   = colors.HexColor('#2e5fb9')
COL_GREEN  = colors.HexColor('#2e8f5b')
COL_TEAL   = colors.HexColor('#227a7a')
COL_ORANGE = colors.HexColor('#c96a1f')
COL_PURPLE = colors.HexColor('#7a4fb9')

ACCENTS = {
    "accent-red": COL_RED, "accent-amber": COL_AMBER, "accent-blue": COL_BLUE,
    "accent-green": COL_GREEN, "accent-teal": COL_TEAL,
    "accent-orange": COL_ORANGE, "accent-purple": COL_PURPLE,
}

PAGE_W, PAGE_H = A4
MARGIN = 16 * mm
CONTENT_W = PAGE_W - 2 * MARGIN


# ══════════════════════════════════════════════════════════════════
# STILI TIPOGRAFICI
# ══════════════════════════════════════════════════════════════════
def _styles():
    s = {}
    s['eyebrow'] = ParagraphStyle('eyebrow', fontName='Courier-Bold', fontSize=8.5,
        textColor=COL_TEXT_MUTED, leading=11, spaceAfter=2)
    s['title'] = ParagraphStyle('title', fontName='Helvetica-Bold', fontSize=19,
        textColor=COL_TEXT, leading=23, spaceAfter=4)
    s['phase_title_red'] = ParagraphStyle('phase_title_red', fontName='Helvetica-Bold',
        fontSize=13, textColor=COL_RED, leading=16, spaceBefore=4, spaceAfter=2)
    s['phase_title_blue'] = ParagraphStyle('phase_title_blue', fontName='Helvetica-Bold',
        fontSize=13, textColor=COL_BLUE, leading=16, spaceBefore=4, spaceAfter=2)
    s['section_title'] = ParagraphStyle('section_title', fontName='Helvetica-Bold',
        fontSize=9.5, textColor=colors.HexColor('#333333'), leading=12, spaceAfter=5)
    s['h4'] = ParagraphStyle('h4', fontName='Helvetica-Bold', fontSize=9,
        textColor=colors.HexColor('#555555'), leading=12, spaceBefore=6, spaceAfter=3)
    s['body'] = ParagraphStyle('body', fontName='Helvetica', fontSize=9.3,
        textColor=COL_TEXT, leading=13.5, spaceAfter=6, alignment=TA_LEFT)
    s['body_muted'] = ParagraphStyle('body_muted', parent=s['body'], textColor=COL_TEXT_MUTED)
    s['mono_box'] = ParagraphStyle('mono_box', fontName='Courier', fontSize=8.3,
        textColor=colors.HexColor('#333333'), leading=12, spaceBefore=3, spaceAfter=6,
        backColor=COL_BG_LIGHT, borderColor=COL_BORDER, borderWidth=0.6,
        borderPadding=7, borderRadius=2)
    s['post_box'] = ParagraphStyle('post_box', parent=s['mono_box'], fontName='Helvetica-Oblique')
    s['communique_box'] = ParagraphStyle('communique_box', fontName='Helvetica', fontSize=8.8,
        textColor=colors.HexColor('#1e5c33'), leading=13, spaceBefore=3, spaceAfter=6,
        backColor=colors.HexColor('#eef7f0'), borderColor=COL_TEAL, borderWidth=0.6,
        borderPadding=8, borderRadius=2)
    s['fact_box'] = ParagraphStyle('fact_box', fontName='Helvetica', fontSize=8.6,
        textColor=colors.HexColor('#444444'), leading=13,
        backColor=COL_BG_LIGHT, borderColor=COL_BORDER, borderWidth=0.6, borderPadding=9)
    s['meta_key'] = ParagraphStyle('meta_key', fontName='Courier-Bold', fontSize=7.3,
        textColor=COL_TEXT_MUTED, leading=10)
    s['meta_val'] = ParagraphStyle('meta_val', fontName='Helvetica', fontSize=9,
        textColor=COL_TEXT, leading=12)
    s['score_label'] = ParagraphStyle('score_label', fontName='Courier-Bold', fontSize=7,
        textColor=COL_TEXT_MUTED, leading=9)
    s['score_value'] = ParagraphStyle('score_value', fontName='Helvetica-Bold', fontSize=16,
        leading=19)
    s['footer'] = ParagraphStyle('footer', fontName='Helvetica', fontSize=7.3,
        textColor=COL_TEXT_MUTED)
    # Stili per la matrice comparativa (tabella orizzontale multi-attore)
    s['matrix_header'] = ParagraphStyle('matrix_header', fontName='Helvetica-Bold', fontSize=8.5,
        textColor=colors.HexColor('#222222'), leading=11)
    s['matrix_row_label'] = ParagraphStyle('matrix_row_label', fontName='Helvetica-Bold', fontSize=7.6,
        textColor=colors.HexColor('#444444'), leading=10)
    s['matrix_cell'] = ParagraphStyle('matrix_cell', fontName='Helvetica', fontSize=7.8,
        textColor=COL_TEXT, leading=10.8)
    s['matrix_cell_mono'] = ParagraphStyle('matrix_cell_mono', fontName='Courier', fontSize=7.2,
        textColor=colors.HexColor('#333333'), leading=10)
    s['matrix_cell_muted'] = ParagraphStyle('matrix_cell_muted', parent=s['matrix_cell'],
        textColor=COL_TEXT_MUTED, fontName='Helvetica-Oblique')
    return s


# ══════════════════════════════════════════════════════════════════
# HELPER — escaping e micro-markdown inline
# ══════════════════════════════════════════════════════════════════
def esc(s):
    return xml_escape(str(s)) if s else ""


def inline_md(s):
    """Escape XML + converte **grassetto** in <b>...</b> per Paragraph di reportlab."""
    t = esc(s)
    t = re.sub(r'\*\*(.+?)\*\*', r'<b>\1</b>', t)
    t = t.replace('\n', '<br/>')
    return t


def clean_json_str(raw):
    if not raw:
        return ""
    s = raw.replace("```json", "").replace("```", "").strip()
    a, b = s.find('{'), s.rfind('}')
    return s[a:b + 1] if (a != -1 and b > a) else s


# ══════════════════════════════════════════════════════════════════
# SECTION CARD — blocco con titolo + bordo accento colorato
# ══════════════════════════════════════════════════════════════════
def section_card(title, flowables, accent_class, styles, na_label="N/D"):
    if not flowables:
        flowables = [Paragraph(na_label, styles['body'])]
    accent = ACCENTS.get(accent_class, colors.HexColor('#999999'))

    inner = [Paragraph(esc(title).upper(), styles['section_title'])] + flowables
    tbl = Table([[inner]], colWidths=[CONTENT_W])
    tbl.setStyle(TableStyle([
        ('BOX', (0, 0), (-1, -1), 0.6, COL_BORDER),
        ('LINEBEFORE', (0, 0), (0, -1), 2.6, accent),
        ('BACKGROUND', (0, 0), (-1, -1), COL_BG_WHITE),
        ('LEFTPADDING', (0, 0), (-1, -1), 13),
        ('RIGHTPADDING', (0, 0), (-1, -1), 12),
        ('TOPPADDING', (0, 0), (-1, -1), 9),
        ('BOTTOMPADDING', (0, 0), (-1, -1), 10),
        ('VALIGN', (0, 0), (-1, -1), 'TOP'),
    ]))
    return KeepTogether([tbl, Spacer(1, 8)])


# ══════════════════════════════════════════════════════════════════
# RED TEAM — parsing del JSON e costruzione delle card
# ══════════════════════════════════════════════════════════════════
def build_red_team(raw, styles, lang=DEFAULT_LANG):
    na = tr('na', lang)
    story = [Paragraph(tr('red_team_title', lang), styles['phase_title_red']),
             HRFlowable(width=CONTENT_W, thickness=1.4, color=COL_RED, spaceAfter=10)]

    try:
        data = json.loads(clean_json_str(raw))
    except Exception:
        story.append(section_card(tr('raw_output_error', lang),
            [Paragraph(esc(raw or na), styles['mono_box'])], "accent-red", styles, na_label=na))
        return story

    risk_str = data.get("risk_assessment", "") or ""
    # "Virul\w+" copre già Virulenza/Virulence; "Impa(tto|ct)" copre Impatto/Impact
    # (il testo generato dall'IA può essere in IT o EN a seconda del task).
    vmatch = re.search(r'[Vv]irul\w+[:\s]+(\d)', risk_str)
    imatch = re.search(r'[Ii]mpa(?:tto|ct)\w*[:\s]+(\d)', risk_str)

    fields = [
        ("field_psyops_objectives", data.get("psyops_objectives"),        "accent-amber", "body"),
        ("field_target_audience",   data.get("target_audience_analysis"), "accent-amber", "body"),
        ("field_product_dev",       data.get("product_development"),      "accent-blue",  "body"),
        ("field_social_payload",    data.get("social_payload"),           "accent-purple", "mono"),
        ("field_indicators",        data.get("indicators_of_influence"),  "accent-blue",  "body"),
        ("field_disarm",            data.get("disarm_techniques"),        "accent-orange", "body"),
        ("field_weak_spots",        data.get("weak_spots"),               "accent-orange", "body"),
    ]
    for title_key, val, accent, kind in fields:
        title = tr(title_key, lang)
        style = styles['mono_box'] if kind == "mono" else styles['body']
        content = esc(val or na) if kind == "mono" else inline_md(val or na)
        story.append(section_card(title, [Paragraph(content, style)], accent, styles, na_label=na))

    # Risk assessment con box punteggio
    risk_flows = []
    if vmatch or imatch:
        v = (vmatch.group(1) + "/5") if vmatch else "—"
        i = (imatch.group(1) + "/5") if imatch else "—"
        score_tbl = Table([[
            [Paragraph(tr('score_virulence', lang), styles['score_label']),
             Paragraph(v, ParagraphStyle('sv', parent=styles['score_value'], textColor=COL_RED))],
            [Paragraph(tr('score_impact', lang), styles['score_label']),
             Paragraph(i, ParagraphStyle('si', parent=styles['score_value'], textColor=COL_AMBER))],
        ]], colWidths=[CONTENT_W / 2 - 12] * 2)
        score_tbl.setStyle(TableStyle([
            ('BOX', (0, 0), (-1, -1), 0.6, COL_BORDER),
            ('BACKGROUND', (0, 0), (-1, -1), COL_BG_LIGHT),
            ('LEFTPADDING', (0, 0), (-1, -1), 10), ('TOPPADDING', (0, 0), (-1, -1), 7),
            ('BOTTOMPADDING', (0, 0), (-1, -1), 8),
        ]))
        risk_flows.append(score_tbl)
        risk_flows.append(Spacer(1, 6))
    risk_flows.append(Paragraph(inline_md(risk_str or na), styles['body']))
    story.append(section_card(tr('risk_assessment', lang), risk_flows, "accent-red", styles, na_label=na))

    return story


# ══════════════════════════════════════════════════════════════════
# BLUE TEAM — parsing del Markdown e costruzione delle card
# ══════════════════════════════════════════════════════════════════
def parse_md_sections(md):
    sections, current = [], None
    for line in (md or "").split("\n"):
        h3 = re.match(r'^###\s+(.+)', line)
        if h3:
            if current:
                sections.append(current)
            title = re.sub(r'^\d+\.\s*', '', h3.group(1)).strip()
            current = {"title": title, "body": ""}
        elif current is not None and not re.match(r'^---+\s*$', line):
            current["body"] += line + "\n"
    if current:
        sections.append(current)
    return sections


def render_bt_body(raw, styles):
    flows = []
    blocks = re.split(r'\n\s*\n', (raw or "").strip())
    for block in blocks:
        block = block.strip('\n')
        if not block.strip():
            continue
        lines = [l for l in block.split('\n')]

        h4 = re.match(r'^####\s+(.+)', lines[0])
        if h4:
            flows.append(Paragraph(inline_md(h4.group(1)), styles['h4']))
            rest = '\n'.join(lines[1:]).strip()
            if rest:
                flows.extend(render_bt_body(rest, styles))
            continue

        non_empty = [l for l in lines if l.strip()]
        if non_empty and all(re.match(r'^-\s+', l) for l in non_empty):
            items = [ListItem(Paragraph(inline_md(re.sub(r'^-\s+', '', l)), styles['body']),
                               leftIndent=4, spaceAfter=2)
                     for l in non_empty]
            flows.append(ListFlowable(items, bulletType='bullet', start='•',
                                       leftIndent=13, bulletFontSize=7))
            continue

        if non_empty and all(re.match(r'^(\d+\.\s+|\([a-zA-Z]\)\s+)', l) for l in non_empty):
            for l in non_empty:
                flows.append(Paragraph(inline_md(l.strip()), styles['body']))
            continue

        joined = ' '.join(l.strip() for l in non_empty)
        if not joined:
            continue

        if re.match(r'^(\[.+\]|AND |OR |site:|lang:)', joined, re.IGNORECASE):
            mono_text = '<br/>'.join(esc(l.strip()) for l in non_empty)
            flows.append(Paragraph(mono_text, styles['mono_box']))
        elif joined.startswith("Presidenza del Consiglio"):
            flows.append(Paragraph(inline_md(joined), styles['communique_box']))
        elif re.match(r'^["\u201c\u00ab](.+)["\u201d\u00bb]$', joined):
            flows.append(Paragraph(inline_md(joined), styles['post_box']))
        else:
            flows.append(Paragraph(inline_md(joined), styles['body']))

    return flows


# Riconoscimento del "tema" della sezione Blue Team per assegnare l'accento
# colore: i pattern coprono sia le intestazioni italiane sia quelle inglesi,
# perché il titolo qui arriva dal Markdown generato dall'IA (che segue la
# lingua del task, non quella dell'interfaccia).
ACCENT_BY_TOPIC = [
    (re.compile(r'valutazione|minaccia|threat|assessment', re.I), "accent-red"),
    (re.compile(r'contro.?narrat|prebunk|counter.?narrat', re.I), "accent-green"),
    (re.compile(r'media|mainstream', re.I), "accent-teal"),
    (re.compile(r'osint|monitorag|monitoring', re.I), "accent-blue"),
    (re.compile(r'debunk|smentita', re.I), "accent-amber"),
    (re.compile(r'escalation|coordinam|coordinat', re.I), "accent-red"),
]


def build_blue_team(md, styles, lang=DEFAULT_LANG):
    story = [Paragraph(tr('blue_team_title', lang), styles['phase_title_blue']),
             HRFlowable(width=CONTENT_W, thickness=1.4, color=COL_BLUE, spaceAfter=10)]

    if not md or len(md.strip()) < 20:
        story.append(Paragraph(tr('no_blue_output', lang), styles['body_muted']))
        return story

    for sec in parse_md_sections(md):
        accent = "accent-blue"
        for pattern, acc in ACCENT_BY_TOPIC:
            if pattern.search(sec["title"]):
                accent = acc
                break
        body_flows = render_bt_body(sec["body"], styles)
        story.append(section_card(sec["title"], body_flows, accent, styles, na_label=tr('na', lang)))

    return story


# ══════════════════════════════════════════════════════════════════
# FOOTER / NUMERAZIONE PAGINE
# ══════════════════════════════════════════════════════════════════
def _footer(canvas, doc, lang=DEFAULT_LANG):
    canvas.saveState()
    canvas.setFont('Helvetica', 7.3)
    canvas.setFillColor(COL_TEXT_MUTED)
    # Usiamo le dimensioni reali del documento (doc.pagesize/margini) invece
    # delle costanti globali (pensate per l'A4 verticale): così il footer
    # risulta allineato correttamente anche nel PDF orizzontale (matrice
    # comparativa), cosa che prima non accadeva.
    page_w = doc.pagesize[0]
    left_margin = doc.leftMargin
    right_margin = doc.rightMargin
    canvas.drawString(left_margin, 10 * mm, tr('footer_text', lang))
    canvas.drawRightString(page_w - right_margin, 10 * mm, tr('footer_page', lang).format(n=doc.page))
    canvas.setStrokeColor(COL_BORDER)
    canvas.setLineWidth(0.5)
    canvas.line(left_margin, 14 * mm, page_w - right_margin, 14 * mm)
    canvas.restoreState()


# ══════════════════════════════════════════════════════════════════
# ENTRY POINT
# ══════════════════════════════════════════════════════════════════
def generate_task_pdf(task, task_id, lang=DEFAULT_LANG):
    lang = lang if lang in TR else DEFAULT_LANG
    na = tr('na', lang)
    styles = _styles()
    buf = io.BytesIO()
    doc = SimpleDocTemplate(buf, pagesize=A4,
        leftMargin=MARGIN, rightMargin=MARGIN, topMargin=MARGIN, bottomMargin=20 * mm,
        title=f"ANTARES Report Task {task_id}")

    red_raw  = task.get("result") or task.get("result_text") or ""
    blue_raw = task.get("blue_team_result") or ""
    actor    = (task.get("actor_id") or na).upper()
    backend  = (task.get("backend") or "local").upper()
    started  = task.get("started_at") or "—"
    ended    = task.get("completed_at") or "—"
    fact     = task.get("fact_text") or ""

    story = []

    # ── Intestazione ──
    story.append(Paragraph(tr('eyebrow', lang), styles['eyebrow']))
    story.append(Paragraph(f"{tr('report_operativo', lang)} &mdash; Task #{esc(task_id)}", styles['title']))
    story.append(HRFlowable(width=CONTENT_W, thickness=1.6, color=COL_TEXT, spaceAfter=10))

    # ── Metadata ──
    meta_tbl = Table([
        [Paragraph(tr('meta_attore', lang), styles['meta_key']), Paragraph(esc(actor), styles['meta_val']),
         Paragraph(tr('meta_backend', lang), styles['meta_key']), Paragraph(esc(backend), styles['meta_val'])],
        [Paragraph(tr('meta_avvio', lang), styles['meta_key']), Paragraph(esc(started), styles['meta_val']),
         Paragraph(tr('meta_fine', lang), styles['meta_key']), Paragraph(esc(ended), styles['meta_val'])],
    ], colWidths=[CONTENT_W*0.13, CONTENT_W*0.37, CONTENT_W*0.13, CONTENT_W*0.37])
    meta_tbl.setStyle(TableStyle([
        ('BOX', (0, 0), (-1, -1), 0.6, COL_BORDER),
        ('INNERGRID', (0, 0), (-1, -1), 0.6, COL_BORDER),
        ('BACKGROUND', (0, 0), (0, -1), COL_BG_LIGHT),
        ('BACKGROUND', (2, 0), (2, -1), COL_BG_LIGHT),
        ('LEFTPADDING', (0, 0), (-1, -1), 8), ('RIGHTPADDING', (0, 0), (-1, -1), 8),
        ('TOPPADDING', (0, 0), (-1, -1), 6), ('BOTTOMPADDING', (0, 0), (-1, -1), 6),
        ('VALIGN', (0, 0), (-1, -1), 'MIDDLE'),
    ]))
    story.append(meta_tbl)
    story.append(Spacer(1, 10))

    # ── Testo Origine ──
    story.append(Paragraph(tr('meta_testo_origine', lang), styles['meta_key']))
    story.append(Spacer(1, 3))
    story.append(Paragraph(esc(fact).replace('\n', '<br/>') or na, styles['fact_box']))
    story.append(Spacer(1, 16))

    # ── Red / Blue Team ──
    story.extend(build_red_team(red_raw, styles, lang))
    story.append(Spacer(1, 10))
    story.extend(build_blue_team(blue_raw, styles, lang))

    footer_fn = partial(_footer, lang=lang)
    doc.build(story, onFirstPage=footer_fn, onLaterPages=footer_fn)
    buf.seek(0)
    return buf.read()


# ══════════════════════════════════════════════════════════════════
# MATRICE COMPARATIVA — PDF multi-attore (landscape)
# ══════════════════════════════════════════════════════════════════

METRICS_RED_PDF = [
    ("risk_assessment",           "metric_risk_assessment",   "risk"),
    ("psyops_objectives",         "metric_psyops_objectives", "text"),
    ("target_audience_analysis",  "metric_target_audience",   "text"),
    ("social_payload",            "metric_social_payload",    "mono"),
    ("disarm_techniques",         "metric_disarm",            "text"),
    ("weak_spots",                "metric_weak_spots",        "text"),
]

# Chiave = numero progressivo della sezione ("### 1. ...", "### 2. ..."),
# NON il titolo: il titolo del Markdown generato dall'IA cambia lingua in
# base al task, mentre la numerazione resta stabile. Vedi
# parse_blue_sections_keyed() più sotto.
METRICS_BLUE_PDF = [
    ("1", "metric_blue_threat"),
    ("2", "metric_blue_counter"),
    ("3", "metric_blue_media"),
    ("4", "metric_blue_osint"),
    ("5", "metric_blue_debunk"),
    ("6", "metric_blue_escalation"),
]


def slugify_title(title):
    t = re.sub(r'[()]', '', title).strip().lower()
    t = t.replace('-', ' ')
    t = re.sub(r'[^\w\s]', '', t)
    t = re.sub(r'\s+', '_', t)
    return t


def parse_blue_sections_keyed(md):
    """Indicizza le sezioni Blue Team per NUMERO progressivo (non per
    titolo): l'intestazione "### 2. ..." può essere in qualunque lingua a
    seconda del task, ma la numerazione resta stabile — è quindi la chiave
    giusta per la Matrice Comparativa multi-attore, che deve funzionare
    anche confrontando task generati in lingue diverse.
    """
    sections = {}
    current_key = None
    for line in (md or "").split("\n"):
        h3 = re.match(r'^###\s+(\d+)\.\s+(.+)', line)
        if h3:
            current_key = h3.group(1)
            sections[current_key] = ""
        elif current_key is not None and not re.match(r'^-{3,}\s*$', line):
            sections[current_key] += line + "\n"
    return {k: v.strip() for k, v in sections.items()}


def clean_cell_text(text, na_label="N/D"):
    """Pulisce il testo grezzo da residui markdown inutili mantenendo la leggibilità."""
    if not text:
        return na_label
    t = str(text)
    t = re.sub(r'^-{3,}\s*$', '', t, flags=re.MULTILINE)
    t = re.sub(r'^####\s+', '', t, flags=re.MULTILINE)
    t = re.sub(r'^###\s+', '', t, flags=re.MULTILINE)
    t = re.sub(r'^-\s+', '\u2022 ', t, flags=re.MULTILINE)
    t = re.sub(r'\n{3,}', '\n\n', t)
    return t.strip() or na_label


def format_cell_content(text, kind, color_hex=None, na_label="N/D"):
    """Applica la formattazione HTML / Markdown all'intero testo della cella."""
    if not text or text == na_label:
        return na_label
    if kind == "mono":
        text_replaced = esc(text).replace("\n", "<br/>")
        return f'<font face="Courier" size=7.2>{text_replaced}</font>'

    formatted = inline_md(text)
    if kind == "risk" and color_hex:
        formatted = f'<font color="{color_hex}"><b>{formatted}</b></font>'
    return formatted


def risk_max_score(risk_str):
    scores = [int(x) for x in re.findall(r'(\d)/5', risk_str or "")]
    return max(scores) if scores else 0


def risk_color(score):
    if score >= 4:
        return COL_RED
    if score >= 3:
        return COL_AMBER
    return COL_GREEN


def _hex(color):
    return '#%02x%02x%02x' % (int(color.red*255), int(color.green*255), int(color.blue*255))


def _red_cell_data(task, key, kind, lang=DEFAULT_LANG):
    na = tr('na', lang)
    try:
        data = json.loads(clean_json_str(task.get("result_text") or task.get("result") or ""))
    except Exception:
        data = {}
    val = data.get(key) or na
    text = clean_cell_text(val, na_label=na)
    color_hex = None
    if kind == "risk":
        score = risk_max_score(val)
        color_hex = _hex(risk_color(score))
    return text, kind, color_hex


def _blue_cell_data(task, key, kind, lang=DEFAULT_LANG):
    na = tr('na', lang)
    sections = parse_blue_sections_keyed(task.get("blue_team_result") or "")
    val = sections.get(key) or na
    text = clean_cell_text(val, na_label=na)
    return text, kind, None


# ══════════════════════════════════════════════════════════════════
# MATRIX TABLE — Tabella dinamica nativa ReportLab (senza sotto-righe)
# ══════════════════════════════════════════════════════════════════
def _chunk_text(text, max_len, na_label="N/D"):
    """Spezza un testo lungo in blocchi (per paragrafo, poi per parola se un
    singolo paragrafo supera max_len) così che nessun singolo blocco produca
    una riga di tabella più alta della pagina.
    """
    if not text or text == na_label:
        return [na_label]

    paragraphs = [p.strip() for p in str(text).split('\n') if p.strip()]
    if not paragraphs:
        return [na_label]

    chunks = []
    for p in paragraphs:
        if len(p) > max_len:
            words = p.split(' ')
            curr, curr_len = [], 0
            for w in words:
                if curr_len + len(w) + 1 > max_len and curr:
                    chunks.append(" ".join(curr))
                    curr, curr_len = [w], len(w)
                else:
                    curr.append(w)
                    curr_len += len(w) + 1
            if curr:
                chunks.append(" ".join(curr))
        else:
            chunks.append(p)

    return chunks or [na_label]


def _safe_max_chars(col_width_pts, safe_height_pts=300.0, font_size=7.8, leading=10.8, padding=12.0):
    """Stima quanti caratteri di testo (con andata a capo naturale) possono
    stare in un blocco alto al massimo `safe_height_pts`, data la larghezza
    reale della colonna. Usata come soglia di sicurezza per NON generare mai
    una riga di tabella più alta della pagina (che manderebbe in errore
    ReportLab): è una stima volutamente prudente (larghezza media del
    carattere sovrastimata), quindi in pratica la maggior parte dei testi
    reali rientra in un unico blocco/riga.
    """
    avail_width = max(col_width_pts - padding, 24.0)
    avg_char_width = font_size * 0.52  # stima prudente per un font proporzionale
    chars_per_line = max(8.0, avail_width / avg_char_width)
    max_lines = max(3.0, safe_height_pts / leading)
    max_chars = int(chars_per_line * max_lines)
    return max(250, min(max_chars, 900))  # clamp: né troppo frammentato, né troppo largo


# ══════════════════════════════════════════════════════════════════
# MATRIX TABLE — Tabella dinamica nativa ReportLab
# ══════════════════════════════════════════════════════════════════
def _matrix_table(row_defs, tasks, cell_data_fn, styles, content_width, lang=DEFAULT_LANG):
    """Costruisce la tabella-matrice.

    Di norma ogni cella è un UNICO paragrafo continuo (una sola riga di
    tabella per metrica): ReportLab gestisce da solo l'a-capo, senza
    sotto-righe artificiali sincronizzate tra colonne (quel meccanismo,
    usato in passato con soglie fisse basse, lasciava vuoti bianchi nelle
    colonne più corte).

    ATTENZIONE (vincolo tecnico): ReportLab non riesce a disegnare una riga
    di tabella più alta di una pagina — se capita, l'intero documento fallisce
    con un errore ("too large on page"). Per questo, SOLO quando il testo di
    una cella è così lungo da rischiare di superare l'altezza utile della
    pagina, quella singola colonna viene spezzata in più sotto-righe (la
    soglia è calcolata dinamicamente sulla larghezza reale della colonna).
    Le altre colonne, più corte, restano su un'unica riga: non usiamo lo
    SPAN verticale (causava un altro errore interno di ReportLab quando
    combinato a righe molto alte), quindi in questo caso raro può comparire
    un piccolo spazio vuoto sotto il testo delle colonne più corte — ma solo
    per la metrica specifica in cui serve, non sistematicamente come prima.
    """
    na = tr('na', lang)
    label_w = 40 * mm
    n = len(tasks)
    other_w = (content_width - label_w) / max(n, 1)
    col_widths = [label_w] + [other_w] * n
    max_chars = _safe_max_chars(other_w)

    # --- Intestazione ---
    header = [Paragraph(tr('matrix_metrica', lang), styles['matrix_header'])]
    for t in tasks:
        actor = esc((t.get("actor_id") or na).upper())
        header.append(Paragraph(
            f"{actor}<br/><font size=6.5 color='#777777'>TASK #{t.get('id')}</font>",
            styles['matrix_header']
        ))

    table_data = [header]
    separator_row_indices = [0]  # Indici di riga dove tracciare il bordo orizzontale

    for row in row_defs:
        key, label_key = row[0], row[1]
        kind = row[2] if len(row) > 2 else "text"
        label = tr(label_key, lang)

        task_data = []
        for t in tasks:
            status = (t.get("status") or "").lower()
            if status not in ("completed",):
                status_key = STATUS_LABEL_KEYS.get(status)
                lbl = tr(status_key, lang) if status_key else (status.upper() or na)
                task_data.append(([lbl], "muted", None))
            else:
                raw_text, k, color_hex = cell_data_fn(t, key, kind, lang)
                chunks = _chunk_text(raw_text, max_chars, na_label=na)
                task_data.append((chunks, k, color_hex))

        max_subrows = max(len(td[0]) for td in task_data)

        for sub_idx in range(max_subrows):
            lbl_para = Paragraph(esc(label).upper(), styles['matrix_row_label']) if sub_idx == 0 else Paragraph("", styles['matrix_cell'])
            cells = [lbl_para]

            for chunks, k, color_hex in task_data:
                if sub_idx < len(chunks):
                    chunk_text = chunks[sub_idx]
                    if k == "muted" or chunk_text == na:
                        cells.append(Paragraph(chunk_text, styles['matrix_cell_muted']))
                    else:
                        formatted_content = format_cell_content(chunk_text, k, color_hex, na_label=na)
                        style = styles['matrix_cell_mono'] if k == "mono" else styles['matrix_cell']
                        cells.append(Paragraph(formatted_content, style))
                else:
                    cells.append(Paragraph("", styles['matrix_cell']))

            table_data.append(cells)

        # Il bordo orizzontale va solo alla fine dell'ultima sotto-riga di
        # questa metrica, non dopo ogni sotto-riga intermedia.
        separator_row_indices.append(len(table_data) - 1)

    matrix_tbl = Table(table_data, colWidths=col_widths, repeatRows=1)

    style_cmds = [
        ('BACKGROUND', (0, 0), (-1, 0), colors.HexColor('#eeeeee')),
        ('BACKGROUND', (0, 1), (0, -1), COL_BG_LIGHT),
        ('VALIGN', (0, 0), (-1, -1), 'TOP'),
        ('LEFTPADDING', (0, 0), (-1, -1), 6),
        ('RIGHTPADDING', (0, 0), (-1, -1), 6),
        ('TOPPADDING', (0, 0), (-1, -1), 4),
        ('BOTTOMPADDING', (0, 0), (-1, -1), 4),
        ('BOX', (0, 0), (-1, -1), 0.5, COL_BORDER),
    ]

    # Linee divisorie verticali tra colonne
    for col in range(len(col_widths) - 1):
        style_cmds.append(('LINEAFTER', (col, 0), (col, -1), 0.5, COL_BORDER))

    # Linee orizzontali SOLO sotto l'intestazione e tra metriche diverse
    for r_idx in separator_row_indices:
        style_cmds.append(('LINEBELOW', (0, r_idx), (-1, r_idx), 0.5, COL_BORDER))

    matrix_tbl.setStyle(TableStyle(style_cmds))
    return [matrix_tbl]


def generate_group_pdf(tasks, group_id, group=None, lang=DEFAULT_LANG):
    lang = lang if lang in TR else DEFAULT_LANG
    na = tr('na', lang)
    styles = _styles()
    buf = io.BytesIO()
    page_w, page_h = landscape(A4)
    margin = 14 * mm
    content_w = page_w - 2 * margin

    doc = SimpleDocTemplate(buf, pagesize=landscape(A4),
        leftMargin=margin, rightMargin=margin, topMargin=margin, bottomMargin=20 * mm,
        title=f"ANTARES Matrice Comparativa {group_id[:8]}")

    fact = (tasks[0].get("fact_text") if tasks else None) or (group or {}).get("fact_text_preview") or ""
    created = (group or {}).get("created_at") or "—"

    story = []
    story.append(Paragraph(tr('eyebrow', lang), styles['eyebrow']))
    story.append(Paragraph(
        f"{tr('matrice_comparativa', lang)} &mdash; {tr('gruppo', lang)} {esc(group_id[:8])}&hellip;",
        styles['title']))
    story.append(HRFlowable(width=content_w, thickness=1.6, color=COL_TEXT, spaceAfter=10))

    meta_tbl = Table([[
        Paragraph(tr('meta_attori_confrontati', lang), styles['meta_key']), Paragraph(str(len(tasks)), styles['meta_val']),
        Paragraph(tr('meta_creato_il', lang), styles['meta_key']), Paragraph(esc(created), styles['meta_val']),
    ]], colWidths=[content_w*0.18, content_w*0.32, content_w*0.18, content_w*0.32])
    meta_tbl.setStyle(TableStyle([
        ('BOX', (0, 0), (-1, -1), 0.6, COL_BORDER),
        ('INNERGRID', (0, 0), (-1, -1), 0.6, COL_BORDER),
        ('BACKGROUND', (0, 0), (0, -1), COL_BG_LIGHT),
        ('BACKGROUND', (2, 0), (2, -1), COL_BG_LIGHT),
        ('LEFTPADDING', (0, 0), (-1, -1), 8), ('RIGHTPADDING', (0, 0), (-1, -1), 8),
        ('TOPPADDING', (0, 0), (-1, -1), 6), ('BOTTOMPADDING', (0, 0), (-1, -1), 6),
        ('VALIGN', (0, 0), (-1, -1), 'MIDDLE'),
    ]))
    story.append(meta_tbl)
    story.append(Spacer(1, 8))

    story.append(Paragraph(tr('evento_testo_origine', lang), styles['meta_key']))
    story.append(Spacer(1, 3))
    story.append(Paragraph(esc(fact).replace('\n', '<br/>') or na, styles['fact_box']))
    story.append(Spacer(1, 14))

    footer_fn = partial(_footer, lang=lang)

    if not tasks:
        story.append(Paragraph(tr('no_tasks_found', lang), styles['body_muted']))
        doc.build(story, onFirstPage=footer_fn, onLaterPages=footer_fn)
        buf.seek(0)
        return buf.read()

    story.append(Paragraph(tr('red_team_title_matrix', lang), styles['phase_title_red']))
    story.append(HRFlowable(width=content_w, thickness=1.4, color=COL_RED, spaceAfter=8))
    story.extend(_matrix_table(
        METRICS_RED_PDF, tasks,
        _red_cell_data,
        styles, content_w, lang
    ))
    story.append(Spacer(1, 16))

    story.append(Paragraph(tr('blue_team_title_matrix', lang), styles['phase_title_blue']))
    story.append(HRFlowable(width=content_w, thickness=1.4, color=COL_BLUE, spaceAfter=8))
    story.extend(_matrix_table(
        METRICS_BLUE_PDF, tasks,
        _blue_cell_data,
        styles, content_w, lang
    ))

    doc.build(story, onFirstPage=footer_fn, onLaterPages=footer_fn)
    buf.seek(0)
    return buf.read()