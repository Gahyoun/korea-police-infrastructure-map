#!/usr/bin/env python3
"""report.md → GNU template(A4) 연구보고서 HTML(조판 전 flow 문서).

    python3 build_report.py <gnu-template 폴더> <출력 flow.html>
    node paginate.mjs <flow.html> <report.html>      # A4 쪽 나누기 → 정적 HTML
    node <gnu-template>/scripts/export.mjs report.html <출력폴더>   # PDF·PNG·배치 검사

GNU template: https://github.com/Gahyoun/gnu-network-science-skills/tree/main/templates/gnu-template
표지는 공식 서식형(form), 본문 쪽은 0.5mm GNU Blue 테두리 + 하단 시그니처(DESIGN.md 7장)를 따른다.
"""
import base64
import html
import json
import re
import subprocess
import sys
import tempfile
from pathlib import Path

import markdown

HERE = Path(__file__).resolve().parent
NOTE = HERE.parent
TPL = Path(sys.argv[1]).resolve()
OUT = Path(sys.argv[2]).resolve()

AUTHOR = "김가현"
AFFIL = "테크노베이션파트너스 · 경상국립대학교 졸업생"
DATE = "2026. 10. 26."
TITLE = "진주시 무인순찰로봇 배치 세미 시뮬레이션"
SUBTITLE = "준지도학습 기반 ABM과 현장 배치(FDE) 설계 — 경상국립대학교 소재지 진주 사례"
RUN = "진주시 무인순찰로봇 배치 세미 시뮬레이션 · 준지도학습 ABM"
SIGN = NOTE / "figures/signature.png"     # 서명 이미지(있으면 마지막 쪽에 삽입)


def b64(path, mime):
    return f"data:{mime};base64," + base64.b64encode(Path(path).read_bytes()).decode("ascii")


def img(path, cls, alt):
    mime = {".svg": "image/svg+xml", ".png": "image/png", ".jpg": "image/jpeg"}[Path(path).suffix.lower()]
    return f'<img class="{cls}" alt="{html.escape(alt)}" src="{b64(path, mime)}">'


fonts = "@font-face{font-family:'Noto Sans KR';src:url('%s') format('woff2');font-weight:100 900;font-style:normal;font-display:block}" % \
    b64(TPL / "assets/fonts/NotoSansKR-Variable.subset.woff2", "font/woff2")
theme = (TPL / "assets/theme.css").read_text(encoding="utf-8")

# 연구보고서 쪽(이 문서용 추가 규칙). 토큰·서체는 theme.css를 그대로 쓴다.
report_css = """
@page{size:A4 portrait;margin:0}
.cover .form-frame .sheet-body{padding:15mm 11mm 6mm;gap:5.5mm}
.cover .form-title{font-size:23pt}
.cover .form-title .subtitle{font-size:.68em;margin-top:2.5mm}
.cover-facts{display:grid;grid-template-columns:max-content 1fr;column-gap:7mm;row-gap:2.6mm;font-size:11.5pt;line-height:1.5}
.cover-facts dt{font-weight:700;color:var(--ui-action);white-space:nowrap}
.cover-facts dd{word-break:keep-all}
.cover-photo{margin-top:auto;display:grid;grid-template-columns:62mm 1fr;gap:6mm;align-items:end}
.cover-photo img{display:block;width:62mm;height:auto;border:1px solid var(--ui-line)}
.cover-photo figcaption{font-size:8.8pt;line-height:1.6;color:var(--ui-subtle);word-break:keep-all}
.page-run{display:flex;justify-content:space-between;gap:6mm;padding:3.6mm 9mm 2.6mm;font-size:8.4pt;color:var(--ui-subtle);border-bottom:1px solid var(--ui-line)}
.report-body{flex:1;min-height:0;overflow:hidden;padding:6mm 9mm 3mm}
.report-body>*:first-child{margin-top:0!important}
.report-body h2{font-size:14pt;font-weight:700;border-bottom:.6mm solid var(--gnu-blue);padding-bottom:1.6mm;margin:5mm 0 3mm}
.report-body h3{font-size:11.2pt;font-weight:700;margin:4mm 0 1.8mm}
.report-body p,.report-body li{font-size:9.8pt;line-height:1.72;word-break:keep-all}
.report-body p{margin-bottom:2mm;text-align:justify}
.report-body ul,.report-body ol{padding-left:5.5mm;margin:0 0 2mm}
.report-body li{margin-bottom:.8mm}
.report-body strong{font-weight:700}
.report-body code{font-family:ui-monospace,'DejaVu Sans Mono',monospace;font-size:.88em;background:var(--ui-surface);padding:0 .8mm}
.report-body pre{background:var(--ui-surface);border-left:.8mm solid var(--gnu-blue);padding:2.4mm 3.5mm;margin:0 0 3mm;white-space:pre-wrap;font-size:8.6pt;line-height:1.6}
.report-body pre code{background:none;padding:0;font-size:1em}
.report-body table{width:100%;border-collapse:collapse;border-top:.5mm solid var(--ui-text);margin:1mm 0 3.5mm;font-size:8.3pt;line-height:1.5}
.report-body th,.report-body td{padding:1.1mm 1.6mm;border-bottom:1px solid var(--ui-line);text-align:left;vertical-align:top;word-break:keep-all}
.report-body thead th{background:var(--ui-surface);font-weight:700}
.report-body td[align=right],.report-body th[align=right]{text-align:right;font-variant-numeric:tabular-nums}
.report-body figure{margin:1mm 0 3.5mm}
.report-body figure img{display:block;width:100%;height:auto}
.report-body figcaption{font-size:8.4pt;line-height:1.55;color:#333;margin-top:1.5mm;word-break:keep-all}
.report-body .refs-list li{font-size:8.4pt;line-height:1.55;padding-left:5mm;text-indent:-5mm;list-style:none;overflow-wrap:anywhere}
.report-body .refs-list{padding-left:0}
.sign-block{margin-top:8mm;break-inside:avoid}
.sign-facts{display:grid;grid-template-columns:24mm 1fr;row-gap:3mm;column-gap:6mm;font-size:11pt;line-height:1.5;margin-top:4mm;border-top:.5mm solid var(--ui-text);padding-top:4mm}
.sign-facts dt{font-weight:700;color:var(--ui-action)}
.sign-cell{display:flex;align-items:center;gap:8mm;font-weight:700}
.sign-img{height:16mm;width:auto}
.sign-slot{display:inline-flex;align-items:center;justify-content:center;width:42mm;height:16mm;border:1px solid #b1b8be;color:var(--ui-subtle);font-weight:400;font-size:9pt}
.math-display{margin:1mm 0 3mm;overflow-x:auto}
.math-display .katex-display{margin:0}
.report-body .katex{font-size:1.06em}
.report-body td .katex{font-size:1em}
.report-foot{display:flex;align-items:flex-end;justify-content:space-between;gap:5mm;padding:0 6mm 3.5mm 9mm;min-height:15mm}
.report-foot .pno{font-size:9pt;color:var(--ui-subtle);font-variant-numeric:tabular-nums}
.report-foot .identity .logo{height:7.6mm}
.report-foot .identity .unit{font-size:11.5pt}
"""

md = (NOTE / "report.md").read_text(encoding="utf-8")
body_md = md[md.index("## 요약"):]
body_md = re.sub(r"^---\s*$", "", body_md, flags=re.M)

# ── LaTeX 수식: 코드 블록을 보호한 뒤 $$…$$·$…$를 자리표시자로 빼고 KaTeX로 렌더링 ──
code = []
def keep_code(m):
    code.append(m.group(0))
    return f"CODEPH{len(code) - 1}X"
body_md = re.sub(r"```.*?```|`[^`\n]+`", keep_code, body_md, flags=re.S)
math = []
def take_math(m):
    disp = m.group(1) is not None
    math.append({"tex": (m.group(1) if disp else m.group(2)).strip(), "display": disp})
    return f"MATHPH{len(math) - 1}X"
body_md = re.sub(r"\$\$(.+?)\$\$|\$([^$\n]+?)\$", take_math, body_md, flags=re.S)
body_md = re.sub(r"CODEPH(\d+)X", lambda m: code[int(m.group(1))], body_md)
with tempfile.TemporaryDirectory() as tmp:
    src, dst = Path(tmp) / "in.json", Path(tmp) / "out.json"
    src.write_text(json.dumps(math, ensure_ascii=False), encoding="utf-8")
    subprocess.run(["node", str(HERE / "render_math.mjs"), str(src), str(dst)], check=True, cwd=HERE)
    rendered = json.loads(dst.read_text(encoding="utf-8"))

body = markdown.markdown(body_md, extensions=["tables", "fenced_code"])
def put_math(m):
    i = int(m.group(1))
    return f'<div class="math-display">{rendered[i]}</div>' if math[i]["display"] else rendered[i]
body = re.sub(r"<p>\s*(MATHPH\d+X)\s*</p>", lambda m: put_math(re.match(r"MATHPH(\d+)X", m.group(1))), body)
body = re.sub(r"MATHPH(\d+)X", put_math, body)

# KaTeX CSS: 글꼴은 woff2만 base64로 내장(오프라인 출력)
kcss = (HERE / "node_modules/katex/dist/katex.min.css").read_text(encoding="utf-8")
kfont = HERE / "node_modules/katex/dist"
kcss = re.sub(r"src:url\((fonts/[^)]+\.woff2)\) format\(\"woff2\"\)(,url\([^)]+\) format\(\"[a-z]+\"\))*",
              lambda m: f'src:url({b64(kfont / m.group(1), "font/woff2")}) format("woff2")', kcss)

# 그림 + 기울임 캡션 → figure
def fig(m):
    src, cap = m.group(2), m.group(3)
    return f'<figure>{img(NOTE / src, "figure-image", m.group(1))}<figcaption>{cap}</figcaption></figure>'
body = re.sub(r'<p><img alt="([^"]*)" src="([^"]+)" /></p>\s*<p><em>(.*?)</em></p>', fig, body, flags=re.S)
# 참고문헌 목록 표시
body = re.sub(r'(<h2>참고문헌</h2>\s*)<ul>', r'\1<ul class="refs-list">', body)
body = body.replace('<p><strong>국내 실증 자료(보도·기관 게시)</strong></p>\n<ul>',
                    '<p><strong>국내 실증 자료(보도·기관 게시)</strong></p>\n<ul class="refs-list">')

slogan = img(TPL / "assets/derived/fly-with-gnu.svg", "logo", "FLY WITH G.N.U")
emblem = img(TPL / "assets/derived/emblem-signature-white.svg", "logo", "경상국립대학교")
signature = img(TPL / "assets/derived/gnu-signature.svg", "logo", "경상국립대학교")
photo = img(NOTE / "figures/photo_20261022_songdo.jpg", "photo", "제12회 과학치안 아이디어 공모전 시상식 테이블의 명패와 안내 책자")

facts = [("일자", "2026. 10. 22.(목)"), ("시간", "12:30 – 13:30"), ("장소", "송도컨벤시아 (인천광역시 연수구)"),
         ("계기", "제12회 과학치안 아이디어 공모전 시상식<br>주최 경찰청·과학기술정보통신부 · 주관 과학치안진흥센터·한국과학기술연구원"),
         ("작성", f"{AUTHOR} ({AFFIL})"), ("대상 지역", "경상남도 진주시 · 지구대 5, 파출소 8 · 도로 10m 구간 117,351개"),
         ("문서", f"연구보고서 초안 v0.3 · {DATE}")]
cover = f"""
<main class="sheet a4 cover" data-export-page>
 <div class="form-frame"><div class="slogan-gap">{slogan}</div>
  <div class="sheet-body">
   <p class="form-series">연구노트 · 연구보고서 초안</p>
   <h1 class="form-title">{TITLE}<span class="subtitle">{SUBTITLE}</span></h1>
   <dl class="cover-facts">{''.join(f'<dt>{k}</dt><dd>{v}</dd>' for k, v in facts)}</dl>
   <figure class="cover-photo">{photo}<figcaption>현장 사진. 제12회 과학치안 아이디어 공모전 시상식,
   2026. 10. 22. 12:15 촬영(인천광역시 연수구).<br><br>본 보고서는 레포 공개 산출물만으로 작성한 초안이며,
   수치는 모형 기반 진단값으로 실제 치안 수준과 다를 수 있다.</figcaption></figure>
  </div>
 </div>
 <div class="form-band"><div class="foot-text"><strong>{AUTHOR}</strong>{AFFIL}</div>{emblem}</div>
</main>"""

sign_img = img(SIGN, "sign-img", f"{AUTHOR} 서명") if SIGN.exists() else '<span class="sign-slot">[서명]</span>'
sign_block = f"""
<section class="sign-block"><h2>작성자 확인</h2>
 <p>본 연구노트·보고서 초안은 아래 작성자가 2026. 10. 22. 송도컨벤시아에서 수행한 연구 내용을 정리한 것이다.</p>
 <dl class="sign-facts"><dt>작성자</dt><dd>{AUTHOR}</dd><dt>소속</dt><dd>{AFFIL}</dd>
 <dt>작성일</dt><dd>{DATE}</dd><dt>서명</dt><dd class="sign-cell">{AUTHOR} {sign_img}</dd></dl>
</section>"""

page_tpl = f"""
<template id="page-tpl"><main class="sheet a4" data-export-page><div class="frame">
 <div class="page-run"><span>{RUN}</span><span>연구보고서 초안</span></div>
 <div class="report-body"></div>
 <footer class="report-foot"><span class="pno"></span><div class="identity">{signature}</div></footer>
</div></main></template>"""

doc = f"""<!doctype html>
<html lang="ko"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1">
<meta name="gnu-template-kind" content="report"><title>{TITLE} — {SUBTITLE}</title>
<style>{fonts}{kcss}{theme}{report_css}</style></head><body>
{cover}
<div id="flow">{body}{sign_block}</div>
{page_tpl}
</body></html>
"""
OUT.write_text(doc, encoding="utf-8")
print(OUT, f"{len(doc) / 1e6:.1f} MB")
