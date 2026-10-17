"""Word (.docx) fayllar bilan ishlash: testlarni o'qish, testlarni Word'ga chiqarish, darslik matnini olish."""
import html
import io
import re

import docx
from docx.oxml.ns import qn
from docx.shared import Pt
from docx.table import Table
from docx.text.paragraph import Paragraph

LATIN = "ABCDEFGHIJ"
CYR_TO_LAT = {"А": "A", "В": "B", "С": "C", "Д": "D", "Е": "E", "Б": "B", "Г": "C"}

Q_RE = re.compile(r"^\s*(\d{1,3})\s*[.)]?\s+(\S.*)$")
O_RE = re.compile(r"^\s*([A-Ea-eАБВГДЕабвгде])\s*[).]\s*(.*\S)\s*$")
KEY_RE = re.compile(r"(\d{1,3})\s*(?:[-—–.):]+|\s)\s*([A-EА-Е])(?![A-Za-zА-Яа-я])")
STOP_WORDS = ("NAZARIY QO", "ISHCHI DAFTAR", "UYGA VAZIFA")
EXPL_RE = re.compile(r"^\s*(?:Izoh|Изоҳ|💡)\s*:?\s*(.+)$", re.I)


def _norm_letter(ch: str) -> str:
    ch = ch.upper()
    return CYR_TO_LAT.get(ch, ch)


def _iter_paragraphs(document):
    """Hujjatdagi barcha paragraflar (jadvallar ichidagilar ham) tartib bilan."""
    for el in document.element.body.iterchildren():
        if el.tag == qn("w:p"):
            yield Paragraph(el, document)
        elif el.tag == qn("w:tbl"):
            for row in Table(el, document).rows:
                seen = set()
                for cell in row.cells:
                    if id(cell._tc) in seen:
                        continue
                    seen.add(id(cell._tc))
                    yield from cell.paragraphs


def _para_lines(p):
    """Paragrafni qatorlarga bo'ladi: (matn, belgilangan_harflar, jami_harflar, yulduzcha)."""
    lines = [["", 0, 0]]
    for r in p.runs:
        mark = bool(r.bold) or bool(r.underline)
        for ch in r._r:
            if ch.tag in (qn("w:br"), qn("w:cr")):
                lines.append(["", 0, 0])
            elif ch.tag == qn("w:t"):
                t = ch.text or ""
                lines[-1][0] += t
                n = len(t.replace(" ", ""))
                lines[-1][2] += n
                if mark:
                    lines[-1][1] += n
            elif ch.tag == qn("w:tab"):
                lines[-1][0] += " "
    return lines


def parse_tests(data: bytes) -> tuple[list[dict], list[str]]:
    """Word fayldan testlarni o'qiydi.

    To'g'ri javob quyidagi usullardan biri bilan aniqlanadi:
      1) variant qalin (bold) yoki tagiga chizilgan bo'lsa;
      2) variant boshida * yoki + belgisi bo'lsa;
      3) fayl oxirida javoblar kaliti bo'lsa: "1 — A", "2-B", "3) D" ...
    """
    document = docx.Document(io.BytesIO(data))
    lines = []
    for p in _iter_paragraphs(document):
        for text, m, tot in _para_lines(p):
            if text.strip():
                lines.append((text.strip(), tot > 0 and m / tot > 0.6))

    qs, key = [], {}
    cur = None
    for text, marked in lines:
        if any(w in text.upper() for w in STOP_WORDS) and qs:
            break
        mo = O_RE.match(text)
        if mo and cur is not None:
            label = _norm_letter(mo.group(1))
            opt = mo.group(2).strip()
            star = False
            if opt[:1] in "*+":
                opt, star = opt[1:].strip(), True
            if opt.endswith("✓") or opt.endswith("✔"):
                opt, star = opt[:-1].strip(), True
            cur["options"].append({"label": label, "text": opt, "marked": marked, "star": star})
            continue
        me = EXPL_RE.match(text)
        if me and cur is not None and cur["options"]:
            cur["explanation"] = me.group(1).strip()
            continue
        found_keys = KEY_RE.findall(text)
        # kalit qatori: faqat raqam-harf juftliklaridan iborat
        stripped = KEY_RE.sub("", text)
        if found_keys and not re.search(r"[A-Za-zА-Яа-яЁё]{2,}", stripped):
            for n, letter in found_keys:
                key[int(n)] = _norm_letter(letter)
            continue
        mq = Q_RE.match(text)
        if mq and (cur is None or len(cur["options"]) >= 2):
            cur = {"n": int(mq.group(1)), "q": mq.group(2).strip(), "options": [], "explanation": ""}
            qs.append(cur)
            continue
        if cur is not None and not cur["options"]:
            cur["q"] += " " + text

    result, issues = [], []
    for q in qs:
        opts = q["options"]
        if len(opts) < 2:
            continue
        idx = None
        stars = [i for i, o in enumerate(opts) if o["star"]]
        marks = [i for i, o in enumerate(opts) if o["marked"]]
        if len(stars) == 1:
            idx = stars[0]
        elif len(marks) == 1:
            idx = marks[0]
        elif q["n"] in key:
            labels = [o["label"] for o in opts]
            if key[q["n"]] in labels:
                idx = labels.index(key[q["n"]])
        texts = [re.sub(r"\s+", " ", o["text"]) for o in opts]
        if idx is None:
            issues.append(f"{q['n']}-savol: to'g'ri javob aniqlanmadi")
            continue
        if len(set(texts)) != len(texts) or len(texts) > 10:
            issues.append(f"{q['n']}-savol: variantlar takrorlangan yoki 10 tadan ko'p")
            continue
        qt = re.sub(r"\s+", " ", q["q"])
        if len(qt) > 290 or any(len(t) > 100 for t in texts):
            issues.append(f"{q['n']}-savol: matn juda uzun (savol ≤ 290, variant ≤ 100 belgi)")
            continue
        result.append({"q": qt, "options": texts, "correct": idx, "explanation": q["explanation"][:200]})
    return result, issues


def export_tests(title: str, questions: list[dict], note: str = "") -> bytes:
    """Testni Word faylga chiqaradi (to'g'ri javob qalin). Shu faylni tahrirlab botga qayta yuklash mumkin."""
    d = docx.Document()
    style = d.styles["Normal"]
    style.font.name = "Times New Roman"
    style.font.size = Pt(12)
    d.add_heading(title, level=1)
    if note:
        d.add_paragraph().add_run(note).italic = True
    for i, q in enumerate(questions, 1):
        p = d.add_paragraph()
        p.paragraph_format.space_before = Pt(8)
        p.paragraph_format.space_after = Pt(0)
        p.add_run(f"{i}. {q['q']}").bold = True
        for j, opt in enumerate(q["options"]):
            op = d.add_paragraph()
            op.paragraph_format.space_after = Pt(0)
            op.paragraph_format.left_indent = Pt(18)
            r = op.add_run(f"{LATIN[j]}) {opt}")
            if j == q["correct"]:
                r.bold = True
        if q.get("explanation"):
            ep = d.add_paragraph()
            ep.paragraph_format.left_indent = Pt(18)
            ep.add_run(f"Izoh: {q['explanation']}").italic = True
    buf = io.BytesIO()
    d.save(buf)
    return buf.getvalue()


# ---------------- darslik matni ----------------
def _runs_html(p) -> str:
    out = ""
    for r in p.runs:
        t = ""
        for ch in r._r:
            if ch.tag == qn("w:t"):
                t += ch.text or ""
            elif ch.tag in (qn("w:br"), qn("w:cr")):
                t += "\n"
            elif ch.tag == qn("w:tab"):
                t += " "
        if not t:
            continue
        e = html.escape(t, quote=False)
        if r.bold and t.strip():
            e = f"<b>{e}</b>"
        elif r.italic and t.strip():
            e = f"<i>{e}</i>"
        out += e
    out = re.sub(r"</b>(\s*)<b>", r"\1", out)
    out = re.sub(r"</i>(\s*)<i>", r"\1", out)
    return out.strip()


def _plain(s: str) -> str:
    return re.sub("<[^>]+>", "", html.unescape(s))


def _table_html(t: Table) -> str:
    rows = []
    for r in t.rows:
        cells, seen = [], set()
        for c in r.cells:
            if id(c._tc) in seen:
                continue
            seen.add(id(c._tc))
            cells.append("\n".join(x for x in (_runs_html(p) for p in c.paragraphs) if x).strip())
        rows.append(cells)
    if not rows:
        return ""
    hdr = rows[0]
    is_hdr = len(rows) > 1 and all(c.startswith("<b>") and c.endswith("</b>") for c in hdr if c)
    lines = []
    if is_hdr:
        names = [_plain(h).replace("\n", " ") for h in hdr]
        for r in rows[1:]:
            if not any(r):
                continue
            lines.append(f"▪️ <b>{html.escape(_plain(r[0]).replace(chr(10), ' '), quote=False)}</b>")
            for h, c in zip(names[1:], r[1:]):
                if c:
                    lines.append(f"   <i>{html.escape(h, quote=False)}:</i> " + c.replace("\n", " "))
    else:
        ncol = max(len(r) for r in rows)
        for ci in range(ncol):
            for r in rows:
                if ci < len(r) and r[ci].strip():
                    c = r[ci].replace("\n", " ").strip()
                    pl = _plain(c).lstrip()
                    lines.append(c if (pl.startswith("•") or re.match(r"\d+\.", pl)) else "• " + c)
    return "\n".join(lines)


def lesson_blocks(data: bytes) -> list[str]:
    document = docx.Document(io.BytesIO(data))
    out = []
    for el in document.element.body.iterchildren():
        if el.tag == qn("w:p"):
            h = _runs_html(Paragraph(el, document))
            if h:
                out.append(h)
        elif el.tag == qn("w:tbl"):
            h = _table_html(Table(el, document))
            if h:
                out.append(h)
    return out


def paginate(blocks: list[str], limit: int = 3300) -> list[str]:
    """Matnni Telegram xabariga sig'adigan sahifalarga bo'ladi."""
    pages, cur = [], ""
    for b in blocks:
        b = b.strip()
        if not b:
            continue
        parts = [b]
        if len(b) > limit:
            parts, acc = [], ""
            for ln in b.split("\n"):
                while len(ln) > limit:
                    parts.append(ln[:limit])
                    ln = ln[limit:]
                if len(acc) + len(ln) + 1 > limit:
                    parts.append(acc)
                    acc = ""
                acc += ("\n" if acc else "") + ln
            if acc:
                parts.append(acc)
        for x in parts:
            if len(cur) + len(x) + 2 > limit and cur:
                pages.append(cur)
                cur = ""
            cur += ("\n\n" if cur else "") + x
    if cur:
        pages.append(cur)
    return pages
