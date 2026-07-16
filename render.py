"""발행: 처리결과(dict) → docs/index.html + docs/archive/YYYY-MM-DD.html + 아카이브 목록.

반응형 · 라이트/다크 자동 대응. 외부 의존 없음(인라인 CSS).
"""
from __future__ import annotations

import glob
import html
import json
import os
from datetime import datetime

from util import KST, now_kst

DOCS = "docs"
ARCHIVE = os.path.join(DOCS, "archive")
DATA = os.path.join(DOCS, "data")

CSS = """
:root{--bg:#f6f7f9;--card:#fff;--fg:#1a1d21;--muted:#6b7280;--line:#e5e7eb;
--accent:#2563eb;--chip:#eef2ff;--chipfg:#3730a3;--hot:#dc2626;--hotbg:#fee2e2}
@media (prefers-color-scheme:dark){:root{--bg:#0f1216;--card:#171b21;--fg:#e5e7eb;
--muted:#9aa4b2;--line:#252b34;--accent:#60a5fa;--chip:#1e2536;--chipfg:#a5b4fc;
--hot:#f87171;--hotbg:#3b1d1d}}
*{box-sizing:border-box}
body{margin:0;background:var(--bg);color:var(--fg);
font-family:-apple-system,BlinkMacSystemFont,"Segoe UI","Malgun Gothic","Apple SD Gothic Neo",sans-serif;
line-height:1.55;-webkit-text-size-adjust:100%}
.wrap{max-width:880px;margin:0 auto;padding:20px 16px 64px}
header h1{font-size:1.4rem;margin:0 0 4px;letter-spacing:-.02em}
.sub{color:var(--muted);font-size:.86rem;margin-bottom:16px}
.sub a{color:var(--accent);text-decoration:none}
.stats{display:flex;flex-wrap:wrap;gap:8px;margin:14px 0 26px}
.stat{background:var(--card);border:1px solid var(--line);border-radius:10px;
padding:8px 14px;min-width:78px}
.stat b{display:block;font-size:1.25rem;line-height:1.2}
.stat span{font-size:.72rem;color:var(--muted)}
section{margin:0 0 30px}
.sec-h{display:flex;align-items:baseline;gap:8px;margin:0 0 12px;
padding-bottom:6px;border-bottom:2px solid var(--line)}
.sec-h h2{font-size:1.05rem;margin:0;letter-spacing:-.01em}
.sec-h .n{color:var(--muted);font-size:.8rem}
.card{background:var(--card);border:1px solid var(--line);border-radius:12px;
padding:13px 15px;margin-bottom:10px}
.card a.t{color:var(--fg);text-decoration:none;font-weight:650;font-size:1rem}
.card a.t:hover{color:var(--accent)}
.meta{display:flex;flex-wrap:wrap;align-items:center;gap:7px;
margin-top:7px;font-size:.78rem;color:var(--muted)}
.src{font-weight:600;color:var(--fg)}
.hot{background:var(--hotbg);color:var(--hot);border-radius:20px;
padding:1px 9px;font-weight:700;font-size:.72rem}
.snip{margin:8px 0 0;font-size:.87rem;color:var(--muted)}
.chips{margin-top:9px;display:flex;flex-wrap:wrap;gap:6px}
.chip{background:var(--chip);color:var(--chipfg);border-radius:20px;
padding:2px 10px;font-size:.74rem;text-decoration:none}
.chip:hover{filter:brightness(.96)}
.empty{color:var(--muted);background:var(--card);border:1px dashed var(--line);
border-radius:12px;padding:24px;text-align:center}
footer{margin-top:40px;padding-top:16px;border-top:1px solid var(--line);
color:var(--muted);font-size:.76rem}
.arc li{margin:6px 0}
.arc a{color:var(--accent);text-decoration:none}
"""


def esc(s) -> str:
    return html.escape(str(s or ""))


def _ago(ts: float) -> str:
    if not ts:
        return ""
    dt = datetime.fromtimestamp(ts, KST)
    sec = (now_kst() - dt).total_seconds()
    if sec < 0:
        return "방금"
    if sec < 3600:
        return f"{int(sec//60)}분 전"
    if sec < 86400:
        return f"{int(sec//3600)}시간 전"
    return f"{int(sec//86400)}일 전"


def _card(item: dict) -> str:
    cnt = item.get("source_count", 1)
    hot = f'<span class="hot">🔥 {cnt}개 매체</span>' if cnt > 1 else ""
    ago = _ago(item.get("ts", 0))
    meta = [f'<span class="src">{esc(item.get("source"))}</span>']
    if hot:
        meta.append(hot)
    if ago:
        meta.append(f"<span>{esc(ago)}</span>")
    snip = f'<p class="snip">{esc(item["snippet"])}</p>' if item.get("snippet") else ""
    chips = ""
    if cnt > 1:
        parts = "".join(
            f'<a class="chip" href="{esc(s["url"])}" target="_blank" '
            f'rel="noopener">{esc(s["name"])}</a>'
            for s in item.get("sources", [])[:8])
        chips = f'<div class="chips">{parts}</div>'
    return (
        f'<div class="card">'
        f'<a class="t" href="{esc(item["url"])}" target="_blank" rel="noopener">'
        f'{esc(item["title"])}</a>'
        f'<div class="meta">{"".join(meta)}</div>{snip}{chips}</div>'
    )


def _section(group: dict) -> str:
    cards = "".join(_card(it) for it in group.get("items", []))
    return (
        f'<section><div class="sec-h"><h2>{esc(group["label"])}</h2>'
        f'<span class="n">{group.get("count", 0)}건</span></div>{cards}</section>'
    )


def render_html(result: dict, rel: str = "index") -> str:
    c = result.get("counts", {})
    gen = result.get("generated_at", "")[:16].replace("T", " ")
    srcs = " · ".join(result.get("sources", [])) or "구글뉴스"
    naver_note = "" if result.get("use_naver") else \
        ' · <span title="네이버 키 미설정">네이버 키 추가 시 정확도↑</span>'
    nav = ('<a href="archive/">지난 기록 &raquo;</a>' if rel == "index"
           else '<a href="../index.html">&laquo; 오늘</a> · <a href="./">지난 기록</a>')

    sections = "".join(_section(g) for g in result.get("groups", []))
    if not sections:
        sections = ('<div class="empty">해당 시간대에 수집된 관련 기사가 없습니다.<br>'
                    '(수집창·키워드는 keywords.yaml에서 조정)</div>')

    stats = "".join(
        f'<div class="stat"><b>{c.get(k,0)}</b><span>{lbl}</span></div>'
        for k, lbl in [("collected", "수집"), ("consolidated", "통합"),
                       ("excluded", "제외"), ("multi", "복수보도")])

    return f"""<!doctype html>
<html lang="ko"><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width,initial-scale=1">
<title>경기콘텐츠진흥원 일일 언론 모니터링 · {esc(result.get('date'))}</title>
<style>{CSS}</style></head>
<body><div class="wrap">
<header>
<h1>경기콘텐츠진흥원 일일 언론 모니터링</h1>
<div class="sub">{esc(result.get('date'))} · 최근 {esc(result.get('window_hours'))}시간 ·
소스 {esc(srcs)}{naver_note}<br>생성 {esc(gen)} KST · {nav}</div>
</header>
<div class="stats">{stats}</div>
{sections}
<footer>
자동 수집·정리(규칙기반, 무료). 저작권상 <b>제목·짧은 요약·원문 링크</b>만 제공하며 기사 전문은 각 언론사 원문을 확인하세요.<br>
키워드·필터는 <code>keywords.yaml</code>에서 편집 · GitHub Actions로 매일 자동 갱신.
</footer>
</div></body></html>"""


def _archive_index_html(entries: list) -> str:
    items = "".join(
        f'<li><a href="{esc(e["date"])}.html">{esc(e["date"])}</a> '
        f'— 통합 {e["consolidated"]}건 · 복수보도 {e["multi"]}건</li>'
        for e in entries)
    return f"""<!doctype html>
<html lang="ko"><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width,initial-scale=1">
<title>지난 기록 · 경기콘텐츠진흥원 언론 모니터링</title>
<style>{CSS}</style></head>
<body><div class="wrap">
<header><h1>지난 기록</h1>
<div class="sub"><a href="../index.html">&laquo; 오늘 보기</a></div></header>
<ul class="arc">{items or '<li class="empty">아카이브가 아직 없습니다.</li>'}</ul>
</div></body></html>"""


def write_outputs(result: dict):
    os.makedirs(ARCHIVE, exist_ok=True)
    with open(os.path.join(DOCS, "index.html"), "w", encoding="utf-8") as f:
        f.write(render_html(result, rel="index"))
    with open(os.path.join(ARCHIVE, f"{result['date']}.html"), "w", encoding="utf-8") as f:
        f.write(render_html(result, rel="archive"))
    print(f"[render] index.html + archive/{result['date']}.html 작성")


def build_archive_index():
    os.makedirs(ARCHIVE, exist_ok=True)
    entries = []
    for p in sorted(glob.glob(os.path.join(DATA, "*.json")), reverse=True):
        try:
            with open(p, "r", encoding="utf-8") as f:
                d = json.load(f)
            c = d.get("counts", {})
            entries.append({"date": d.get("date", os.path.basename(p)[:-5]),
                            "consolidated": c.get("consolidated", 0),
                            "multi": c.get("multi", 0)})
        except Exception:
            continue
    with open(os.path.join(ARCHIVE, "index.html"), "w", encoding="utf-8") as f:
        f.write(_archive_index_html(entries))
    print(f"[render] archive/index.html 작성 ({len(entries)}일)")


def main():
    import glob as _g
    files = sorted(_g.glob(os.path.join(DATA, "*.json")))
    if not files:
        print("[render] docs/data/*.json 없음 — 먼저 process.py 실행")
        return
    with open(files[-1], "r", encoding="utf-8") as f:
        result = json.load(f)
    write_outputs(result)
    build_archive_index()


if __name__ == "__main__":
    main()
