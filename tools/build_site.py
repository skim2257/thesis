#!/usr/bin/env python3
"""Build the thesis website from the dissertation .docx.

    python tools/build_site.py path/to/thesis.docx

Writes:
  docs/index.html      full standalone page (GitHub Pages ready)
  docs/figures/*.webp  optimized figures
  build/artifact.html  same page without the document skeleton (for claude.ai Artifacts)

Requires: pandoc on PATH, python packages beautifulsoup4 and Pillow.
"""
from __future__ import annotations

import argparse
import copy
import json
import re
import subprocess
import tempfile
from pathlib import Path

from bs4 import BeautifulSoup, NavigableString, Tag
from PIL import Image

HERE = Path(__file__).resolve().parent
REPO = HERE.parent
SRC = HERE / "src"

MAX_FIG_WIDTH = 1800
WEBP_QUALITY = 82

# ---------------------------------------------------------------------------
# Hand-written editorial layer: chapter openers. Every sentence and number here
# is taken from the thesis text (Ch.1.7 objectives and the chapters' results).
# ---------------------------------------------------------------------------
CHAPTERS = {
    1: dict(
        kicker="Introduction",
        lede="Clinical deep learning is a data-engineering and evaluation problem at least as much as a "
        "modelling problem, and treating it that way is what makes a model clinically applicable.",
        stats=[
            ("830,000+", "new head and neck SCC cases worldwide each year"),
            ("54–71%", "of HNSCC patients never undergo neck resection, so pathologic ENE is never known"),
            ("0.64", "median AUROC of 34 experts reading ENE on preoperative CT"),
        ],
    ),
    2: dict(
        kicker="Infrastructure",
        lede="Automated, scripted curation can supersede manual curation in fidelity while being transparent, "
        "faster, and reproducible by design.",
        lede_label="Hypothesis",
        stats=[
            ("3,346", "patients in RADCURE, the largest head and neck CT collection on TCIA"),
            ("4", "downstream chapters that run on one curation engine, Med-ImageTools"),
            ("1,000", "core-hours that pre-crawled TCIA databases are expected to save"),
        ],
    ),
    3: dict(
        kicker="Evaluation",
        lede="A substantial fraction of published imaging “signal” is attributable to tumour volume or context, "
        "and geometric performance metrics do not translate to clinical acceptability.",
        lede_label="Hypothesis",
        stats=[
            ("12", "prognostic models benchmarked in the RADCURE challenge"),
            ("9", "negative controls that destroy image content but keep volume"),
            ("22%", "of expert manual contours failed blinded peer review"),
        ],
    ),
    4: dict(
        kicker="Decision-aligned model",
        lede="A patient-level model can exceed volume and clinical baselines and stratify outcomes comparably "
        "to a clinician.",
        lede_label="Hypothesis",
        stats=[
            ("0.913", "AUROC on the RADCURE held-out test set (n=163)"),
            ("0.671", "AUROC on the external Maastro cohort (n=175)"),
            ("0", "lymph node contours required at inference"),
        ],
    ),
    5: dict(
        kicker="Supportive care",
        lede="Per-tooth dose reporting can be produced unattended from the planning DICOM study to help dentists "
        "make better informed and more granular decisions to manage tooth extraction and osteoradionecrosis.",
        lede_label="Hypothesis",
        stats=[
            ("885", "RADCURE patients with both a planning dose and a panorex"),
            ("70 / 60 Gy", "prophylactic extraction thresholds, maxilla / mandible"),
            ("0", "manual contours or operator steps in the pipeline"),
        ],
    ),
    6: dict(
        kicker="Conclusion",
        lede="The distance between a raw, clinical dataset and a complex clinical decision is usually described "
        "as a modelling problem. This thesis measured that distance differently.",
        stats=[],
    ),
}

# Short titles for navigation
SHORT = {
    1: "Earning a place in the clinic",
    2: "From DICOM to ML-ready data",
    3: "What models actually learn",
    4: "Patient-level iENE from planning CT",
    5: "Dosarex: per-tooth dose",
    6: "Adopting models in the clinic",
}

# Interactive widgets, inserted after the element with the given id
WIDGETS = {
    "fig-3-5": "widget_negctrl.html",
    "s3-4-3": "widget_scarf.html",
    "tbl-4-3": "widget_forest.html",
    "tbl-4-4": "widget_threshold.html",
    "s5-2": "widget_dosarex.html",
}


# ---------------------------------------------------------------------------
def slug(s: str) -> str:
    s = s.lower().replace("’", "").replace("'", "")
    s = re.sub(r"[^a-z0-9]+", "-", s)
    return s.strip("-")


def norm_key(s: str) -> str:
    s = s.replace("’", "'").replace(" ", " ")
    return re.sub(r"\s+", " ", s).strip()


def run_pandoc(docx: Path, media_dir: Path) -> str:
    out = subprocess.run(
        ["pandoc", "-f", "docx", "-t", "html5", "--wrap=none", f"--extract-media={media_dir}", str(docx)],
        check=True,
        capture_output=True,
        text=True,
    )
    return out.stdout


def convert_images(media_dir: Path, out_dir: Path) -> dict[str, dict]:
    out_dir.mkdir(parents=True, exist_ok=True)
    info = {}
    for f in sorted((media_dir / "media").glob("*")):
        im = Image.open(f)
        im = im.convert("RGBA") if im.mode in ("P", "LA", "RGBA") else im.convert("RGB")
        if im.mode == "RGBA":
            bg = Image.new("RGB", im.size, (255, 255, 255))
            bg.paste(im, mask=im.split()[3])
            im = bg
        if im.width > MAX_FIG_WIDTH:
            im = im.resize((MAX_FIG_WIDTH, round(im.height * MAX_FIG_WIDTH / im.width)), Image.LANCZOS)
        name = f.stem + ".webp"
        im.save(out_dir / name, "WEBP", quality=WEBP_QUALITY, method=6)
        info[str(f.resolve())] = dict(name=name, w=im.width, h=im.height)
    return info


# ---------------------------------------------------------------------------
class Builder:
    def __init__(self, html: str, images: dict[str, dict]):
        self.soup = BeautifulSoup(html, "html.parser")
        self.images = images
        self.refs: dict[str, dict] = {}
        self.unmatched: set[str] = set()
        self.fig_ids: set[str] = set()
        self.sec_ids: set[str] = set()
        self.figures: list[dict] = []

    # -- generic cleanup ---------------------------------------------------
    def clean(self):
        s = self.soup
        for t in s.find_all(["mark", "u"]):
            t.unwrap()
        for t in s.find_all("blockquote"):
            t.unwrap()
        for t in s.find_all("colgroup"):
            t.decompose()
        for t in s.find_all(["table", "td", "th", "col"]):
            for a in ("style", "width"):
                if t.has_attr(a):
                    del t[a]
        # merge adjacent identical inline tags produced by Word run splits
        for name in ("strong", "em"):
            for t in s.find_all(name):
                if t.parent is None:
                    continue
                while True:
                    nxt = t.next_sibling
                    gap = ""
                    if isinstance(nxt, NavigableString) and not nxt.strip():
                        gap, nxt = str(nxt), nxt.next_sibling
                    if not (isinstance(nxt, Tag) and nxt.name == name):
                        break
                    if gap:
                        t.next_sibling.extract()
                        t.append(gap)
                    for c in list(nxt.contents):
                        t.append(c)
                    nxt.decompose()
        for br in s.find_all("br"):
            # stray line breaks at the start of strong blocks
            if br.parent and br.parent.name == "strong" and not br.previous_sibling:
                br.decompose()

    # -- split document into parts by h1 -------------------------------------
    def parts(self):
        parts, cur = [], ("front", [])
        for node in list(self.soup.contents):
            if isinstance(node, Tag) and node.name == "h1":
                parts.append(cur)
                cur = (node.get_text(" ", strip=True), [])
            elif isinstance(node, Tag):
                cur[1].append(node)
        parts.append(cur)
        return parts

    # -- figures & tables ---------------------------------------------------
    def img_tag(self, img: Tag, sizes="(min-width: 1100px) 960px, 100vw") -> Tag:
        meta = self.images[str(Path(img["src"]).resolve())]
        new = self.soup.new_tag("img")
        new["src"] = f"figures/{meta['name']}"
        new["width"] = str(meta["w"])
        new["height"] = str(meta["h"])
        new["loading"] = "lazy"
        new["decoding"] = "async"
        new["alt"] = ""
        return new

    @staticmethod
    def is_img_para(t) -> bool:
        return (
            isinstance(t, Tag)
            and t.name == "p"
            and t.find("img") is not None
            and not t.get_text(strip=True)
        )

    @staticmethod
    def is_img_table(t) -> bool:
        return isinstance(t, Tag) and t.name == "table" and t.find("img") is not None

    CAP_RE = re.compile(r"^\s*(Supplementary\s+)?(Figure|Table)\s+(\d+(?:\.\d+)?)\s*[.:]?\s*")

    def caption_info(self, p) -> tuple[str, str, str] | None:
        if not isinstance(p, Tag) or p.name != "p":
            return None
        m = self.CAP_RE.match(p.get_text(" ", strip=True).replace(" ", " "))
        if not m:
            return None
        supp, kind, num = m.group(1), m.group(2), m.group(3)
        label = f"{'Supplementary ' if supp else ''}{kind} {num}"
        fid = f"{'s' if supp else ''}{'fig' if kind == 'Figure' else 'tbl'}-{num.replace('.', '-')}"
        return label, fid, kind

    def strip_label(self, p: Tag):
        """Remove the leading 'Figure 2.1.' text from a caption paragraph."""
        pat = re.compile(r"^\s*(Supplementary)?\s*(Figure|Table)?\s*(\d+(?:\.\d+)?)?\s*[.:]?\s*")
        need = self.CAP_RE.match(p.get_text(" ", strip=True)).group(0).strip()
        removed = ""
        for tn in list(p.find_all(string=True)):
            if len(re.sub(r"\s", "", removed)) >= len(re.sub(r"\s", "", need)):
                break
            txt = str(tn)
            remaining = re.sub(r"\s", "", need)[len(re.sub(r"\s", "", removed)):]
            # consume characters of txt that belong to the label
            i, j = 0, 0
            while i < len(txt) and j < len(remaining):
                if txt[i].isspace() or txt[i] == " ":
                    i += 1
                    continue
                if txt[i] == remaining[j]:
                    i += 1
                    j += 1
                else:
                    break
            removed += txt[:i]
            rest = txt[i:].lstrip(" .: ") if j == len(remaining) else txt[i:]
            tn.replace_with(rest)
        _ = pat
        # drop now-empty inline wrappers and stray leading punctuation
        for t in p.find_all(["strong", "em"]):
            if not t.get_text(strip=True) and not t.find("img"):
                t.decompose()
        first = next((x for x in p.descendants if isinstance(x, NavigableString) and x.strip()), None)
        if first is not None:
            first.replace_with(re.sub(r"^[\s.:]+", "", str(first)))

    def build_figure(self, imgs: list[Tag], cap: Tag | None, sub: list[list[Tag]] | None = None) -> Tag:
        s = self.soup
        fig = s.new_tag("figure", attrs={"class": "fig"})
        label, fid = None, None
        if cap is not None:
            label, fid, _ = self.caption_info(cap)
            fig["id"] = fid
            self.fig_ids.add(fid)
        media = s.new_tag("div", attrs={"class": "fig-media"})
        if sub:
            media["class"] = "fig-media fig-grid"
            for letter, group in zip("abcdefgh", sub):
                cell = s.new_tag("div", attrs={"class": "fig-cell"})
                for im in group:
                    cell.append(self.img_tag(im))
                tag = s.new_tag("span", attrs={"class": "fig-sub"})
                tag.string = f"({letter})"
                cell.append(tag)
                media.append(cell)
        else:
            if len(imgs) > 1:
                media["class"] = "fig-media fig-stack"
            for im in imgs:
                media.append(self.img_tag(im))
        btn = s.new_tag("button", attrs={"class": "fig-zoom", "type": "button", "aria-label": f"Enlarge {label or 'figure'}"})
        btn.append(media)
        fig.append(btn)
        if cap is not None:
            self.strip_label(cap)
            fc = s.new_tag("figcaption")
            lab = s.new_tag("span", attrs={"class": "fig-label"})
            lab.string = label
            fc.append(lab)
            body = s.new_tag("span", attrs={"class": "fig-text"})
            for c in list(cap.contents):
                body.append(c)
            fc.append(body)
            fig.append(fc)
            self.figures.append(dict(id=fid, label=label))
        return fig

    def build_table(self, table: Tag, cap: Tag | None) -> Tag:
        s = self.soup
        fig = s.new_tag("figure", attrs={"class": "tbl"})
        if cap is not None:
            label, fid, _ = self.caption_info(cap)
            fig["id"] = fid
            self.fig_ids.add(fid)
            self.strip_label(cap)
            fc = s.new_tag("figcaption")
            lab = s.new_tag("span", attrs={"class": "fig-label"})
            lab.string = label
            fc.append(lab)
            body = s.new_tag("span", attrs={"class": "fig-text"})
            for c in list(cap.contents):
                body.append(c)
            fc.append(body)
            fig.append(fc)
        wrap = s.new_tag("div", attrs={"class": "tbl-scroll", "tabindex": "0"})
        self.fix_table(table, fig.get("id"))
        wrap.append(table)
        fig.append(wrap)
        return fig

    def fix_table(self, table: Tag, fid: str | None):
        s = self.soup
        # Promote an all-<th> first body row into <thead>
        if fid == "tbl-4-1":
            self.fix_table_4_1(table)
            return
        if fid == "tbl-3-3":
            self.fix_table_3_3(table)
        thead, tbody = table.find("thead"), table.find("tbody")
        if thead and (tbody is None or not tbody.find("tr")):
            hrows = thead.find_all("tr", recursive=False)
            if len(hrows) > 2:
                tb = tbody or s.new_tag("tbody")
                for tr in hrows[1:]:
                    for c in tr.find_all("th", recursive=False):
                        c.name = "td"
                    tb.append(tr.extract())
                if tbody is None:
                    table.append(tb)
        # Row-level alignment: label cell with one extra (header) paragraph
        for tr in table.find_all("tr"):
            cells = tr.find_all(["td", "th"], recursive=False)
            if len(cells) < 2:
                continue
            counts = [len(c.find_all("p", recursive=False)) for c in cells]
            if counts[0] >= 2 and all(c == counts[0] - 1 for c in counts[1:] if c):
                for c in cells[1:]:
                    if c.find("p"):
                        c.insert(0, s.new_tag("p"))
        # numeric alignment hint
        for td in table.find_all(["td", "th"]):
            t = td.get_text(" ", strip=True)
            if re.fullmatch(r"[\d.,%()\[\]–\-\s<>≥≤±/]+(\s*\(.*\))?", t) and re.search(r"\d", t):
                td["class"] = (td.get("class") or []) + ["num"]

    def fix_table_4_1(self, table: Tag):
        """Table 4.1 comes out of Word with every row in the header, a shifted header row and
        stacked values split by line breaks. Rebuild it as label lines aligned with value lines."""
        rows = table.find_all("tr")[2:]

        def lines(cell: Tag, label: bool = False) -> list[str]:
            for t in cell.find_all(["strong", "em"]):
                if not label or t.name == "em":
                    t.unwrap()
            html = cell.decode_contents()
            html = re.sub(r"</?p>", "<br>", html)
            parts = [x.strip() for x in re.split(r"<br\s*/?>", html)]
            return [x for x in parts if BeautifulSoup(x, "html.parser").get_text(strip=True)]

        out = ['<thead><tr><th></th><th colspan="3" class="grp">RADCURE</th><th class="grp">Maastro</th></tr>'
               '<tr><th></th><th class="num">Training<br><span class="n">n=752</span></th>'
               '<th class="num">Test<br><span class="n">n=163</span></th>'
               '<th class="num">Total<br><span class="n">n=915</span></th>'
               '<th class="num">External<br><span class="n">n=175</span></th></tr></thead><tbody>']
        for tr in rows:
            cells = tr.find_all(["td", "th"], recursive=False)
            cells = [c for c in cells if c.get_text(strip=True) or c is cells[0]][:5]
            labels = lines(cells[0], label=True)
            n = len(labels)
            row = ['<th scope="row">' + "".join(f"<p>{x}</p>" for x in labels) + "</th>"]
            for c in cells[1:]:
                vals = lines(c)
                if any("Not Available" in v for v in vals):
                    vals = ["Not available"]
                if n == 1:
                    vals = [" ".join(vals)]
                elif len(vals) < n:
                    vals = [""] + vals
                    vals += [""] * (n - len(vals))
                row.append('<td class="num">' + "".join(f"<p>{v}</p>" for v in vals) + "</td>")
            while len(row) < 5:
                row.append("<td></td>")
            out.append("<tr>" + "".join(row) + "</tr>")
        out.append("</tbody>")
        table.clear()
        table.append(BeautifulSoup("".join(out), "html.parser"))
        table["class"] = ["t-41"]

    def fix_table_3_3(self, table: Tag):
        # header has "Available Data" spanning three sub-columns on a second row
        for tr in table.find_all("tr"):
            for c in tr.find_all(["td", "th"]):
                t = c.get_text(strip=True)
                if t in ("☑️", "☑"):
                    c.string = "●"
                    c["class"] = ["dot"]

    def group_media(self, nodes: list[Tag]) -> list[Tag]:
        out, i = [], 0
        while i < len(nodes):
            n = nodes[i]
            if self.is_img_para(n):
                imgs = []
                while i < len(nodes) and self.is_img_para(nodes[i]):
                    imgs.extend(nodes[i].find_all("img"))
                    i += 1
                cap = nodes[i] if i < len(nodes) and self.caption_info(nodes[i]) else None
                if cap is not None:
                    i += 1
                out.append(self.build_figure(imgs, cap))
                continue
            if self.is_img_table(n):
                cells = []
                first_row = n.find("tr")
                for td in first_row.find_all(["td", "th"]):
                    if td.find("img"):
                        cells.append(td.find_all("img"))
                if not cells:
                    for tr in n.find_all("tr"):
                        for td in tr.find_all(["td", "th"]):
                            if td.find("img"):
                                cells.append(td.find_all("img"))
                i += 1
                cap = nodes[i] if i < len(nodes) and self.caption_info(nodes[i]) else None
                if cap is not None:
                    i += 1
                out.append(self.build_figure([], cap, sub=cells))
                continue
            if isinstance(n, Tag) and n.name == "table":
                i += 1
                cap = nodes[i] if i < len(nodes) and self.caption_info(nodes[i]) else None
                if cap is not None:
                    i += 1
                out.append(self.build_table(n, cap))
                continue
            out.append(n)
            i += 1
        return out

    # -- headings ------------------------------------------------------------
    def style_heading(self, h: Tag, chapter: int | None):
        text = h.get_text(" ", strip=True).replace(" ", " ")
        m = re.match(r"^(\d+(?:\s*\.\s*\d+)*)\s+(.*)$", text)
        h.clear()
        if m:
            num = re.sub(r"\s", "", m.group(1))
            title = m.group(2)
            hid = "s" + num.replace(".", "-")
            n = self.soup.new_tag("span", attrs={"class": "h-num"})
            n.string = num
            h.append(n)
        else:
            num, title = None, text
            hid = f"s{chapter}-{slug(text)}" if chapter else slug(text)
        condensed = "(Condensed)" in title
        title = title.replace("(Condensed)", "").strip()
        t = self.soup.new_tag("span", attrs={"class": "h-title"})
        t.string = title
        h.append(t)
        if condensed:
            tag = self.soup.new_tag("span", attrs={"class": "h-tag"})
            tag.string = "Condensed"
            h.append(tag)
        while hid in self.sec_ids:
            hid += "-x"
        h["id"] = hid
        self.sec_ids.add(hid)
        return dict(id=hid, num=num, title=title, level=int(h.name[1]))

    # -- paragraphs ------------------------------------------------------------
    def style_paragraphs(self, nodes: list[Tag]):
        prev_heading = False
        for n in nodes:
            if not isinstance(n, Tag):
                continue
            if n.name in ("h2", "h3", "h4"):
                prev_heading = True
                continue
            if n.name == "p":
                text = n.get_text(" ", strip=True)
                ems = n.find_all("em", recursive=False)
                non_em = "".join(
                    str(c) for c in n.contents if isinstance(c, NavigableString)
                ).strip()
                if ems and not non_em and len(text) > 20 and (prev_heading or text.startswith("This work")):
                    n["class"] = ["paper-meta"]
                    prev_heading = True
                    continue
                first = n.contents[0] if n.contents else None
                if isinstance(first, Tag) and first.name == "strong":
                    st = first.get_text(strip=True)
                    if len(st) < 70 and st.endswith((".", ":")) and len(text) > len(st) + 20:
                        first["class"] = ["runin"]
                for st in n.find_all("strong"):
                    if "runin" in (st.get("class") or []):
                        continue
                    if len(st.get_text(strip=True)) > 55:
                        st["class"] = ["claim"]
            prev_heading = False

    # -- citations & cross references ----------------------------------------
    _KEY = r"(?:(?:van|von|de|der|den|du|da|di|le|la) )*[^\W\d_a-z][^\W\d_’'\-\. ]*(?:[’'\-\. ]+[^\W\d_]+)*?(?: et al\.?)? \d{4}[a-z]?"
    CITE_RE = re.compile(rf"\[((?:{_KEY})(?:\s*[,;]\s*{_KEY})*)\]")
    XREF_RE = re.compile(
        r"(?P<sf>Supplementary Figure (?P<sfn>\d+))"
        r"|(?P<st>Supplementary Table (?P<stn>\d+))"
        r"|(?P<f>Figure (?P<fn>\d+\.\d+)(?P<fl>[a-z]?))"
        r"|(?P<t>Table (?P<tn>\d+\.\d+))"
        r"|(?P<c>(?:Ch\.\s?|Chapter |Sections? )(?P<cn>\d(?:\.\d+)*))"
    )

    def link_text(self, root: Tag):
        s = self.soup
        for tn in list(root.find_all(string=True)):
            if not isinstance(tn, NavigableString) or tn.parent is None:
                continue
            if tn.find_parent(["a", "figcaption"]) is not None and tn.find_parent("figcaption") is None:
                continue
            if tn.find_parent("a") is not None or tn.find_parent(class_="fig-label") is not None:
                continue
            txt = str(tn)
            if "[" not in txt and not self.XREF_RE.search(txt):
                continue
            pieces: list = []
            pos = 0
            combined = re.compile(f"{self.CITE_RE.pattern}|{self.XREF_RE.pattern}")
            for m in combined.finditer(txt):
                pieces.append(txt[pos : m.start()])
                if m.group(1):
                    pieces.append(self.make_cites(m.group(1)))
                else:
                    pieces.append(self.make_xref(m))
                pos = m.end()
            pieces.append(txt[pos:])
            if len(pieces) == 1:
                continue
            new = []
            for p in pieces:
                if isinstance(p, str):
                    if p:
                        new.append(NavigableString(p))
                elif p is not None:
                    new.append(p)
            tn.replace_with(*new)

    def make_cites(self, inner: str) -> Tag:
        s = self.soup
        wrap = s.new_tag("span", attrs={"class": "cites"})
        keys = [k.strip() for k in re.split(r"[,;]", inner) if k.strip()]
        for k in keys:
            nk = norm_key(k)
            ref = self.refs.get(nk)
            if ref:
                a = s.new_tag("a", attrs={"class": "cite", "href": f"#{ref['id']}", "data-ref": ref["id"]})
            else:
                self.unmatched.add(nk)
                a = s.new_tag("span", attrs={"class": "cite cite-x"})
            a.string = nk
            wrap.append(a)
        return wrap

    def make_xref(self, m) -> Tag | str:
        s = self.soup
        whole = m.group(0)
        if m.group("sf"):
            target = f"sfig-{m.group('sfn')}"
        elif m.group("st"):
            target = f"stbl-{m.group('stn')}"
        elif m.group("f"):
            target = f"fig-{m.group('fn').replace('.', '-')}"
        elif m.group("t"):
            target = f"tbl-{m.group('tn').replace('.', '-')}"
        else:
            num = m.group("cn")
            target = f"ch{num}" if "." not in num else "s" + num.replace(".", "-")
        a = s.new_tag("a", attrs={"class": "xref", "href": f"#{target}"})
        a.string = whole
        return a

    # -- references ------------------------------------------------------------
    def parse_refs(self, nodes: list[Tag]) -> list[dict]:
        groups = []
        group = None
        counter = 0
        for n in nodes:
            if n.name == "h2":
                group = dict(title=n.get_text(strip=True), items=[])
                groups.append(group)
            elif n.name == "ol" and group is not None:
                for li in n.find_all("li", recursive=False):
                    body = li.find("p") or li
                    # Some list items hold two references (a soft line break in Word);
                    # split on every bold "[Author Year]" key.
                    chunks = re.split(r"<strong>\s*\[([^\]]+)\]\s*</strong>", body.decode_contents())
                    for key_raw, html in zip(chunks[1::2], chunks[2::2]):
                        key = norm_key(key_raw)
                        counter += 1
                        item = dict(n=counter, key=key, id="ref-" + slug(key), html=html.strip())
                        group["items"].append(item)
                        self.refs[key] = item
        return groups

    # -- glossary -------------------------------------------------------------
    @staticmethod
    def parse_glossary(nodes: list[Tag]) -> list[tuple[str, str]]:
        out = []
        for n in nodes:
            for tr in n.find_all("tr") if isinstance(n, Tag) else []:
                cells = [c.get_text(" ", strip=True) for c in tr.find_all(["td", "th"])]
                if len(cells) >= 2 and cells[0]:
                    out.append((cells[0], cells[1]))
        return sorted(set(out), key=lambda x: x[0].lower())

    # -- contributions --------------------------------------------------------
    @staticmethod
    def parse_contributions(nodes: list[Tag]):
        intro, rows, roles = [], [], {}
        for n in nodes:
            if n.name == "table":
                for tr in n.find_all("tr"):
                    cells = tr.find_all(["td", "th"])
                    if len(cells) < 4 or not cells[0].get_text(strip=True).isdigit():
                        continue
                    rows.append(
                        dict(
                            ch=cells[0].get_text(strip=True),
                            title=cells[1].get_text(" ", strip=True),
                            venue=[p.decode_contents() for p in cells[2].find_all("p")] or [cells[2].decode_contents()],
                            pos=[p.decode_contents() for p in cells[3].find_all("p")] or [cells[3].decode_contents()],
                        )
                    )
            elif n.name == "p":
                st = n.find("strong")
                t = n.get_text(" ", strip=True)
                m = re.match(r"^([A-Za-z0-9\-]+)\s*:\s*(.+)$", t)
                if st and m and len(rows) > 0:
                    roles[m.group(1)] = [r.strip(" .") for r in re.split(r",", m.group(2))]
                else:
                    intro.append(n)
        return intro, rows, roles


# ---------------------------------------------------------------------------
def render(docx: Path, out_dir: Path, art_path: Path):
    with tempfile.TemporaryDirectory() as td:
        media = Path(td) / "m"
        html = run_pandoc(docx, media)
        images = convert_images(media, out_dir / "figures")

        b = Builder(html, images)
        b.clean()
        parts = b.parts()

        def part(prefix):
            for name, nodes in parts:
                if name.lower().startswith(prefix.lower()):
                    return nodes
            return []

        ref_groups = b.parse_refs(part("References"))
        glossary = b.parse_glossary(part("List of Abbreviations"))
        intro, pubs, roles = b.parse_contributions(part("Statement of Contributions"))
        abstract_nodes = part("Abstract")

        chapters = []
        nav = []
        for name, nodes in parts:
            m = re.match(r"Chapter (\d+):\s*(.*)", name)
            if not m:
                continue
            num = int(m.group(1))
            title = m.group(2).strip()
            nodes = b.group_media(nodes)
            secs = []
            for n in nodes:
                if isinstance(n, Tag) and n.name in ("h2", "h3", "h4"):
                    secs.append(b.style_heading(n, num))
            b.style_paragraphs(nodes)
            words = sum(len(n.get_text(" ", strip=True).split()) for n in nodes if isinstance(n, Tag))
            chapters.append(dict(num=num, title=title, nodes=nodes, secs=secs, words=words))
            nav.append(dict(num=num, title=title, secs=[x for x in secs if x["level"] == 2]))

        supp_nodes = b.group_media(part("Supplementary"))

        # Build chapter HTML
        widgets = {k: (SRC / v).read_text() for k, v in WIDGETS.items()}
        ch_html = []
        for ch in chapters:
            meta = CHAPTERS[ch["num"]]
            minutes = max(1, round(ch["words"] / 230))
            nfig = sum(1 for n in ch["nodes"] if isinstance(n, Tag) and "fig" in (n.get("class") or []))
            ntbl = sum(1 for n in ch["nodes"] if isinstance(n, Tag) and "tbl" in (n.get("class") or []))
            body = []
            for n in ch["nodes"]:
                b.link_text(n)
                body.append(str(n))
                nid = n.get("id") if isinstance(n, Tag) else None
                if nid in widgets:
                    body.append(widgets[nid])
            stats = "".join(
                f'<div class="stat"><span class="stat-v">{v}</span><span class="stat-l">{l}</span></div>'
                for v, l in meta["stats"]
            )
            lede_label = meta.get("lede_label", "Thesis" if ch["num"] == 1 else "")
            lede_label_html = f'<span class="lede-label">{lede_label}</span>' if lede_label else ""
            counts = [f"{minutes} min read"]
            if nfig:
                counts.append(f"{nfig} figure{'s' if nfig > 1 else ''}")
            if ntbl:
                counts.append(f"{ntbl} table{'s' if ntbl > 1 else ''}")
            ch_html.append(
                f"""
<section class="chapter" id="ch{ch['num']}" data-ch="{ch['num']}" data-short="{SHORT[ch['num']]}" style="--c: var(--c{ch['num']}); --c-soft: var(--c{ch['num']}-soft)">
  <header class="ch-open">
    <div class="ch-open-inner">
      <div class="ch-meta"><span class="ch-no">Chapter {ch['num']}</span><span class="ch-kicker">{meta['kicker']}</span><span class="ch-count">{' · '.join(counts)}</span></div>
      <div class="ch-numeral" aria-hidden="true">{ch['num']:02d}</div>
      <h1 class="ch-title">{ch['title']}</h1>
      <p class="ch-lede">{lede_label_html}{meta['lede']}</p>
      {'<div class="stats">' + stats + '</div>' if stats else ''}
    </div>
  </header>
  <div class="prose">
{chr(10).join(body)}
  </div>
</section>"""
            )

        # Abstract
        abstract = []
        for n in abstract_nodes:
            b.link_text(n)
            abstract.append(str(n))

        # Publications
        pub_cards = []
        for r in pubs:
            key = r["title"]
            rl = roles.get(key, [])
            first = any("First" in p or "first" in p for p in r["pos"])
            pos = "".join(f"<span>{p}</span>" for p in r["pos"])
            venue = "".join(f"<span>{re.sub(r',\s*$', '', v.strip())}</span>" for v in r["venue"])
            role_html = "".join(f"<li>{x}</li>" for x in rl)
            pub_cards.append(
                f"""<article class="pub{' pub-first' if first else ''}" style="--c: var(--c{r['ch']})">
  <div class="pub-top"><a class="pub-ch" href="#ch{r['ch']}">Ch. {r['ch']}</a><span class="pub-pos">{pos}</span></div>
  <h3 class="pub-title">{key}</h3>
  <p class="pub-venue">{venue}</p>
  {'<ul class="pub-roles" aria-label="CRediT roles">' + role_html + '</ul>' if role_html else ''}
</article>"""
            )
        intro_html = "".join(str(n) for n in intro)

        # References
        ref_html = []
        for g in ref_groups:
            items = "".join(
                f'<li id="{it["id"]}" data-key="{it["key"].lower()}"><span class="ref-n">{it["n"]}</span>'
                f'<span class="ref-key">{it["key"]}</span><span class="ref-body">{it["html"]}</span></li>'
                for it in g["items"]
            )
            ref_html.append(f'<div class="ref-group"><h3>{g["title"]}</h3><ol class="refs">{items}</ol></div>')
        ref_json = {it["id"]: dict(k=it["key"], n=it["n"], h=it["html"]) for g in ref_groups for it in g["items"]}
        nref = sum(len(g["items"]) for g in ref_groups)

        gloss_html = "".join(f"<div><dt>{a}</dt><dd>{d}</dd></div>" for a, d in glossary)

        supp = []
        for n in supp_nodes:
            b.link_text(n)
            supp.append(str(n))

        # Navigation rail
        rail = []
        for c in nav:
            items = "".join(
                f'<li><a href="#{s["id"]}" data-target="{s["id"]}"><span class="rn">{s["num"] or ""}</span>{s["title"]}</a></li>'
                for s in c["secs"]
            )
            rail.append(
                f'<li class="rail-ch" style="--c: var(--c{c["num"]})"><a class="rail-ch-link" href="#ch{c["num"]}" data-target="ch{c["num"]}">'
                f'<span class="rail-no">{c["num"]:02d}</span><span>{SHORT[c["num"]]}</span></a><ol>{items}</ol></li>'
            )
        rail_html = "".join(rail)

        nfig_total = len([f for f in b.figures])
        replacements = {
            "{{RAIL}}": rail_html,
            "{{ABSTRACT}}": "\n".join(abstract),
            "{{CHAPTERS}}": "\n".join(ch_html),
            "{{PUB_INTRO}}": intro_html,
            "{{PUBS}}": "\n".join(pub_cards),
            "{{REFS}}": "\n".join(ref_html),
            "{{REF_JSON}}": json.dumps(ref_json, ensure_ascii=False).replace("</", "<\\/"),
            "{{GLOSSARY}}": gloss_html,
            "{{SUPP}}": "\n".join(supp),
            "{{NFIG}}": str(nfig_total),
            "{{NREF}}": str(nref),
            "{{NCH}}": str(len(chapters)),
            "{{COHORT}}": (SRC / "widget_cohort.html").read_text(),
        }
        page = (SRC / "page.html").read_text()
        for k, v in replacements.items():
            page = page.replace(k, v)
        css = (SRC / "style.css").read_text()
        js = (SRC / "app.js").read_text()
        page = page.replace("{{CSS}}", css).replace("{{JS}}", js)

        head, body = page.split("<!--BODY-->", 1)
        full = (
            '<!doctype html>\n<html lang="en">\n<head>\n<meta charset="utf-8">\n'
            '<meta name="viewport" content="width=device-width, initial-scale=1, viewport-fit=cover">\n'
            '<meta name="description" content="Reproducible Deep Learning for Head and Neck Radiotherapy — PhD thesis, '
            'Sejin Kim, Department of Medical Biophysics, University of Toronto, 2026.">\n'
            f"{head}\n</head>\n<body>\n{body}\n</body>\n</html>\n"
        )
        (out_dir / "index.html").write_text(full)
        art_path.parent.mkdir(parents=True, exist_ok=True)
        art_path.write_text(page.replace("<!--BODY-->", ""))

        print(f"chapters: {len(chapters)}  figures+tables: {len(b.fig_ids)}  refs: {nref}  glossary: {len(glossary)}")
        missing_xref = set(re.findall(r'class="xref" href="#([^"]+)"', full)) - b.fig_ids - b.sec_ids - {
            f"ch{c['num']}" for c in chapters
        }
        if missing_xref:
            print("unresolved cross-refs:", sorted(missing_xref))
        if b.unmatched:
            print("unmatched citations:", sorted(b.unmatched))


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("docx", type=Path)
    ap.add_argument("--out", type=Path, default=REPO / "docs")
    ap.add_argument("--artifact", type=Path, default=REPO / "build" / "artifact.html")
    a = ap.parse_args()
    render(a.docx, a.out, a.artifact)


if __name__ == "__main__":
    main()
