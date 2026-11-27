#!/usr/bin/env python3
"""Convert Ang Malayang Biblia (amb+.nt) to USFM 3.0 (.usfm.zip) and e-Sword 11+ (.bbli).

Usage:
    python3 scripts/convert_amb.py <path/to/amb+.nt> <output_dir>
"""
import html
import json
import os
import re
import sqlite3
import sys
import zipfile

# KJV NT versification: (book_num, ubs_code, tagalog_name, tagalog_abbr, chapter_verse_counts)
NT_BOOKS = [
    (40, "MAT", "Mateo", "Mat", [25,23,17,25,48,34,29,34,38,42,30,50,58,36,39,28,27,35,30,34,46,46,39,51,46,75,66,20]),
    (41, "MRK", "Marcos", "Mar", [45,28,35,41,43,56,37,38,50,52,33,44,37,72,47,20]),
    (42, "LUK", "Lucas", "Luc", [80,52,38,44,39,49,50,56,62,42,54,59,35,35,32,31,37,43,48,47,38,71,56,53]),
    (43, "JHN", "Juan", "Jua", [51,25,36,54,47,71,53,59,41,42,57,50,38,31,27,33,26,40,42,31,25]),
    (44, "ACT", "Mga Gawa", "Gaw", [26,47,26,37,42,15,60,40,43,48,30,25,52,28,41,40,34,28,41,38,40,30,35,27,27,32,44,31]),
    (45, "ROM", "Roma", "Rom", [32,29,31,25,21,23,25,39,33,21,36,21,14,23,33,27]),
    (46, "1CO", "1 Corinto", "1Co", [31,16,23,21,13,20,40,13,27,33,34,31,13,40,58,24]),
    (47, "2CO", "2 Corinto", "2Co", [24,17,18,18,21,18,16,24,15,18,33,21,14]),
    (48, "GAL", "Galacia", "Gal", [24,21,29,31,26,18]),
    (49, "EPH", "Efeso", "Efe", [23,22,21,32,33,24]),
    (50, "PHP", "Filipos", "Fil", [30,30,21,23]),
    (51, "COL", "Colosas", "Col", [29,23,25,18]),
    (52, "1TH", "1 Tesalonica", "1Te", [10,20,13,18,28]),
    (53, "2TH", "2 Tesalonica", "2Te", [12,17,18]),
    (54, "1TI", "1 Timoteo", "1Ti", [20,15,16,16,25,21]),
    (55, "2TI", "2 Timoteo", "2Ti", [18,26,17,22]),
    (56, "TIT", "Tito", "Tit", [16,15,15]),
    (57, "PHM", "Filemon", "Flm", [25]),
    (58, "HEB", "Hebreo", "Heb", [14,18,19,16,14,20,28,13,28,39,40,29,25]),
    (59, "JAS", "Santiago", "San", [27,26,18,17,20]),
    (60, "1PE", "1 Pedro", "1Pe", [25,25,22,19,14]),
    (61, "2PE", "2 Pedro", "2Pe", [21,22,18]),
    (62, "1JN", "1 Juan", "1Ju", [10,29,24,21,21]),
    (63, "2JN", "2 Juan", "2Ju", [13]),
    (64, "3JN", "3 Juan", "3Ju", [14]),
    (65, "JUD", "Judas", "Jud", [25]),
    (66, "REV", "Pahayag", "Pah", [20,29,22,11,14,17,17,13,21,11,19,17,18,20,8,21,18,24,21,15,27,21]),
]

# Standard USFM 2-digit book file prefix (41=MAT .. 67=REV)
def usfm_file_num(book_num: int) -> int:
    return book_num + 1  # 40->41 (MAT) .. 66->67 (REV)

WT_RE = re.compile(r'<wt>([^<]*)((?:<W[GH]\d+>|<WT[^>]+>)+)')
WG_RE = re.compile(r'<W([GH]\d+)>')
WT_ATTR_RE = re.compile(r'<WT([^\s>]+)(?:\s+l="([^"]*)")?>')
TS_RE = re.compile(r'<TS\d*>(.*?)<Ts>')
RF_RE = re.compile(r'<RF[^>]*>(.*?)<Rf>')
A_TAG_RE = re.compile(r'<a\b[^>]*>(.*?)</a>', re.I | re.S)
FONT_TAG_RE = re.compile(r'</?font\b[^>]*>', re.I)

ABOUT_HTML = (
    '<h2>Ang Malayang Biblia (Bagong Testamento)</h2>'
    '<p>Ang Malayang Biblia (AMB) ay isang malayang salin sa Tagalog ng Bagong Testamento '
    'na nakabatay sa Textus Receptus, na may kasamang Strong\'s Numbers, Greek lemmas, at '
    'pagsusuring gramatikal (morphology) sa bawat salita o parirala.</p>'
    '<p><b>Prepackaged sa Timotheos Bible App</b> (Linux, Windows, Android): '
    '<a href="https://github.com/SalitaNgDiyos/Timotheos">https://github.com/SalitaNgDiyos/Timotheos</a></p>'
    '<p>Source &amp; License (CC BY-SA 4.0): '
    '<a href="https://github.com/SalitaNgDiyos/Ang-Malayang-Biblia-Translation">'
    'https://github.com/SalitaNgDiyos/Ang-Malayang-Biblia-Translation</a></p>'
)


def parse_wt_tags(tags_str: str):
    strongs = WG_RE.findall(tags_str)
    morphs = []
    lemmas = []
    for m, lem in WT_ATTR_RE.findall(tags_str):
        if m:
            morphs.append(m)
        if lem:
            lemmas.append(lem)
    return strongs, morphs, lemmas


def clean_note_text(raw_note: str) -> str:
    txt = A_TAG_RE.sub(r'\1', raw_note)
    txt = FONT_TAG_RE.sub('', txt)
    txt = re.sub(r'<[^>]+>', '', txt)
    return re.sub(r'\s+', ' ', txt).strip()


def convert_verse_to_usfm(raw: str, ch: int, vs: int):
    """Return (headings_list, verse_usfm_text, trailing_para_break)."""
    s = raw

    # Extract section headings <TS>...<Ts>
    headings = []
    def _grab_ts(m):
        h = re.sub(r'<[^>]+>', '', m.group(1)).strip()
        if h:
            headings.append(h)
        return ''
    s = TS_RE.sub(_grab_ts, s)

    # Check if verse ends with a paragraph break (<CM>)
    trailing_para = False
    if re.search(r'<CM>\s*$', s):
        trailing_para = True
        s = re.sub(r'<CM>\s*$', '', s)

    # Remove layout/indent tags; convert mid-verse <CM> or <CI> to space
    s = re.sub(r'<(?:CM|CI|CL|PF\d*|PI\d*)>', ' ', s)
    s = FONT_TAG_RE.sub('', s)

    # Extract footnotes <RF>...<Rf> into placeholders so they don't interfere with <FR>/<wt>
    notes = []
    def _grab_rf(m):
        txt = clean_note_text(m.group(1))
        if not txt:
            return ''
        idx = len(notes)
        notes.append(f'\\f + \\fr {ch}:{vs} \\ft {txt}\\f*')
        return f'\uE000FN{idx}\uE001'
    s = RF_RE.sub(_grab_rf, s)

    # Walk <FR>...<Fr> regions so nested markers inside \wj get the USFM 3.0 '+' prefix
    out_parts = []
    pos = 0
    in_wj = False
    token_re = re.compile(r'<FR>|<Fr>')

    def _transform_segment(seg: str, nested: bool) -> str:
        prefix = '+' if nested else ''

        def _repl_wt(m):
            word = m.group(1).replace('|', '').replace('\\', '')
            if not word:
                return ''
            strongs, morphs, lemmas = parse_wt_tags(m.group(2))
            attrs = []
            if strongs:
                attrs.append(f'strong="{" ".join(strongs)}"')
            if morphs:
                attrs.append(f'x-morph="{" ".join(morphs)}"')
            if lemmas:
                attrs.append(f'lemma="{" ".join(lemmas)}"')
            if not attrs:
                return word
            return f'\\{prefix}w {word}|{" ".join(attrs)}\\{prefix}w*'

        seg = WT_RE.sub(_repl_wt, seg)
        seg = re.sub(r'<FI>(.*?)<Fi>', lambda m: f'\\{prefix}add {m.group(1)}\\{prefix}add*', seg)
        # Strip any leftover unknown tags safely
        seg = re.sub(r'<[^>]+>', '', seg)
        return seg

    for tm in token_re.finditer(s):
        chunk = s[pos:tm.start()]
        if chunk:
            out_parts.append(_transform_segment(chunk, in_wj))
        tag = tm.group(0)
        if tag == '<FR>':
            if not in_wj:
                out_parts.append('\\wj ')
                in_wj = True
        else:
            if in_wj:
                out_parts.append('\\wj*')
                in_wj = False
        pos = tm.end()

    if pos < len(s):
        out_parts.append(_transform_segment(s[pos:], in_wj))
    if in_wj:
        out_parts.append('\\wj*')

    usfm_text = ''.join(out_parts)
    # Restore footnotes
    usfm_text = re.sub(r'\uE000FN(\d+)\uE001', lambda m: notes[int(m.group(1))], usfm_text)
    usfm_text = re.sub(r'\s+', ' ', usfm_text).strip()
    return headings, usfm_text, trailing_para


def convert_verse_to_esword(raw: str):
    """Return (scripture_html, notes_list[(id, note_html)])."""
    s = raw
    notes = []

    # Headings <TS>...<Ts> -> <h2>...</h2>
    s = TS_RE.sub(lambda m: f'<h2>{html.escape(re.sub(r"<[^>]+>", "", m.group(1)).strip())}</h2>', s)

    # Footnotes <RF>...<Rf> -> <not>N1</not> + Notes table row
    def _repl_rf(m):
        txt = clean_note_text(m.group(1))
        if not txt:
            return ''
        nid = f'N{len(notes) + 1}'
        notes.append((nid, html.escape(txt)))
        return f'<not>{nid}</not>'
    s = RF_RE.sub(_repl_rf, s)

    # Strip trailing <CM>, remove layout tags
    s = re.sub(r'<CM>\s*$', '', s)
    s = re.sub(r'<(?:CM|CI|CL|PF\d*|PI\d*)>', ' ', s)
    s = FONT_TAG_RE.sub('', s)

    # Words of Jesus and added words
    s = s.replace('<FR>', '<red>').replace('<Fr>', '</red>')
    s = s.replace('<FI>', '<i>').replace('<Fi>', '</i>')

    # Tagged words <wt>WORD<WG...><WT...> -> WORD<num>G...</num><tvm>...</tvm>
    def _repl_wt(m):
        word = m.group(1)
        strongs, morphs, _lemmas = parse_wt_tags(m.group(2))
        tags = ''.join(f'<num>{st}</num>' for st in strongs) + ''.join(f'<tvm>{mo}</tvm>' for mo in morphs)
        return f'{word}{tags}'
    s = WT_RE.sub(_repl_wt, s)

    s = re.sub(r'\s+', ' ', s).strip()
    return s, notes


def build_outputs(nt_path: str, out_dir: str):
    os.makedirs(out_dir, exist_ok=True)
    with open(nt_path, 'r', encoding='utf-8-sig') as f:
        lines = f.read().splitlines()

    total_expected = sum(sum(chs) for _, _, _, _, chs in NT_BOOKS)
    assert len(lines) >= total_expected, f"Expected at least {total_expected} lines, got {len(lines)}"
    verses = lines[:total_expected]

    usfm_zip_path = os.path.join(out_dir, 'amb+.usfm.zip')
    bbli_path = os.path.join(out_dir, 'amb+.bbli')
    if os.path.exists(bbli_path):
        os.remove(bbli_path)

    conn = sqlite3.connect(bbli_path)
    cur = conn.cursor()
    cur.executescript("""
        CREATE TABLE Details (
            Title NVARCHAR(255),
            Abbreviation NVARCHAR(50),
            Information TEXT,
            Version INT,
            OldTestament BOOL,
            NewTestament BOOL,
            Apocrypha BOOL,
            Strongs BOOL,
            RightToLeft BOOL
        );
        CREATE TABLE Bible (
            Book INT,
            Chapter INT,
            Verse INT,
            Scripture TEXT
        );
        CREATE TABLE Notes (
            Book INT,
            Chapter INT,
            Verse INT,
            ID NVARCHAR(50),
            Note TEXT
        );
    """)
    cur.execute(
        "INSERT INTO Details VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)",
        ("Ang Malayang Biblia (Bagong Testamento)", "AMB", ABOUT_HTML, 4, 0, 1, 0, 1, 0),
    )

    idx = 0
    bible_rows = []
    note_rows = []

    with zipfile.ZipFile(usfm_zip_path, 'w', compression=zipfile.ZIP_DEFLATED) as zf:
        for book_num, ubs, tgl_name, tgl_abbr, ch_counts in NT_BOOKS:
            usfm_lines = [
                "# timotheos.title=Ang Malayang Biblia (Bagong Testamento)",
                "# timotheos.abbr=AMB",
                "# timotheos.lang=tgl",
                f"\\id {ubs} Ang Malayang Biblia (Bagong Testamento)",
                "\\ide UTF-8",
                "\\rem Converted from amb+.nt (2026.1) - Prepackaged in Timotheos Bible App",
                f"\\h {tgl_name}",
                f"\\toc1 {tgl_name}",
                f"\\toc2 {tgl_name}",
                f"\\toc3 {tgl_abbr}",
                f"\\mt1 {tgl_name}",
            ]

            for ch_idx, v_count in enumerate(ch_counts, start=1):
                usfm_lines.append(f"\\c {ch_idx}")
                need_p = True
                for v_num in range(1, v_count + 1):
                    raw = verses[idx]
                    idx += 1

                    # USFM
                    headings, u_text, trail_p = convert_verse_to_usfm(raw, ch_idx, v_num)
                    for h in headings:
                        usfm_lines.append(f"\\s1 {h}")
                        need_p = True
                    if need_p:
                        usfm_lines.append("\\p")
                        need_p = False
                    usfm_lines.append(f"\\v {v_num} {u_text}")
                    if trail_p:
                        need_p = True

                    # e-Sword .bbli
                    e_html, e_notes = convert_verse_to_esword(raw)
                    bible_rows.append((book_num, ch_idx, v_num, e_html))
                    for nid, ntext in e_notes:
                        note_rows.append((book_num, ch_idx, v_num, nid, ntext))

            fname = f"{usfm_file_num(book_num):02d}-{ubs}.usfm"
            zf.writestr(fname, "\n".join(usfm_lines) + "\n")

    cur.executemany("INSERT INTO Bible VALUES (?, ?, ?, ?)", bible_rows)
    cur.executemany("INSERT INTO Notes VALUES (?, ?, ?, ?, ?)", note_rows)
    cur.execute("CREATE INDEX BookChapterVerseIndex ON Bible (Book, Chapter, Verse)")
    cur.execute("CREATE INDEX NotesIndex ON Notes (Book, Chapter, Verse)")
    conn.commit()
    conn.close()

    print(f"Converted {idx} verses across {len(NT_BOOKS)} NT books.")
    print(f"  USFM 3.0 archive: {usfm_zip_path} ({os.path.getsize(usfm_zip_path):,} bytes)")
    print(f"  e-Sword 11+ Bible: {bbli_path} ({os.path.getsize(bbli_path):,} bytes, {len(note_rows)} footnotes)")


if __name__ == '__main__':
    if len(sys.argv) != 3:
        print("Usage: python3 scripts/convert_amb.py <amb+.nt> <out_dir>", file=sys.stderr)
        sys.exit(1)
    build_outputs(sys.argv[1], sys.argv[2])
