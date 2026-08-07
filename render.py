"""발행: 처리결과(dict) → docs/index.html + docs/archive/YYYY-MM-DD.html + 아카이브 목록.

책형 2단 레이아웃(가운데 분할) · 분류별 5개 노출 + 나머지 접기 · 라이트/다크 자동 대응.
외부 의존 없음(인라인 CSS, 접기는 <details> 네이티브).
"""
from __future__ import annotations

import glob
import html
import json
import os
from datetime import datetime, timedelta

from util import KST, now_kst

DOCS = "docs"
ARCHIVE = os.path.join(DOCS, "archive")
DATA = os.path.join(DOCS, "data")

CSS = """
:root{--bg:#f6f7f9;--card:#fff;--fg:#1a1d21;--muted:#6b7280;--line:#e5e7eb;
--accent:#2563eb;--chip:#eef2ff;--chipfg:#3730a3;--hot:#dc2626;--hotbg:#fee2e2;
--spine:#d5d9e0}
@media (prefers-color-scheme:dark){:root{--bg:#0f1216;--card:#171b21;--fg:#e5e7eb;
--muted:#9aa4b2;--line:#252b34;--accent:#60a5fa;--chip:#1e2536;--chipfg:#a5b4fc;
--hot:#f87171;--hotbg:#3b1d1d;--spine:#2b323d}}
*{box-sizing:border-box}
body{margin:0;background:var(--bg);color:var(--fg);
font-family:-apple-system,BlinkMacSystemFont,"Segoe UI","Malgun Gothic","Apple SD Gothic Neo",sans-serif;
line-height:1.5;-webkit-text-size-adjust:100%}
.wrap{max-width:1180px;margin:0 auto;padding:22px 18px 72px}
header h1{font-size:1.4rem;margin:0 0 4px;letter-spacing:-.02em}
.sub{color:var(--muted);font-size:.86rem;margin-bottom:16px}
.sub a{color:var(--accent);text-decoration:none}
.live{background:var(--chip);color:var(--chipfg);border:1px solid var(--line);
border-radius:10px;padding:9px 13px;font-size:.83rem;margin:2px 0 18px;line-height:1.45}
.live a{color:var(--accent);font-weight:700;text-decoration:none}
.trend-sep{margin:32px 0 16px;padding-top:22px;border-top:3px solid var(--accent);text-align:center}
.trend-sep h2{font-size:1.25rem;margin:0 0 3px;letter-spacing:-.01em}
.trend-sep span{color:var(--muted);font-size:.82rem}
.stats{display:flex;flex-wrap:wrap;gap:8px;margin:14px 0 24px}
.stat{background:var(--card);border:1px solid var(--line);border-radius:10px;padding:8px 14px;min-width:76px}
.stat b{display:block;font-size:1.2rem;line-height:1.2}
.stat span{font-size:.72rem;color:var(--muted)}

/* 책형 2단: 신문처럼 세로로 흐름(왼단을 채우고 오른단으로) — 우선순위 순서 유지 +
   행 높이 차이로 생기는 빈 공간이 없어 스크롤이 최소가 된다. */
.book{column-count:2;column-gap:40px;column-rule:1px solid var(--spine)}
.book>section{break-inside:avoid;-webkit-column-break-inside:avoid;page-break-inside:avoid}
@media (max-width:760px){.book{column-count:1;column-rule:none}}

section{margin:0 0 26px;min-width:0}
.sec-h{display:flex;align-items:baseline;gap:8px;margin:0 0 11px;
padding-bottom:6px;border-bottom:2px solid var(--line)}
.sec-h h2{font-size:1.05rem;margin:0;letter-spacing:-.01em}
.sec-h .n{color:var(--muted);font-size:.8rem}
.card{background:var(--card);border:1px solid var(--line);border-radius:11px;
padding:11px 13px;margin-bottom:8px}
.card a.t{color:var(--fg);text-decoration:none;font-weight:650;font-size:.96rem}
.card a.t:hover{color:var(--accent)}
.meta{display:flex;flex-wrap:wrap;align-items:center;gap:6px;margin-top:6px;font-size:.77rem;color:var(--muted)}
.src{font-weight:600;color:var(--fg)}
.hot{background:var(--hotbg);color:var(--hot);border-radius:20px;padding:1px 8px;font-weight:700;font-size:.71rem}
.snip{margin:7px 0 0;font-size:.84rem;color:var(--muted);
display:-webkit-box;-webkit-line-clamp:2;-webkit-box-orient:vertical;overflow:hidden}
.chips{margin-top:8px;display:flex;flex-wrap:wrap;gap:5px}
.chip{background:var(--chip);color:var(--chipfg);border-radius:20px;padding:2px 9px;font-size:.73rem;text-decoration:none}
.chip:hover{filter:brightness(.96)}

/* 더보기 접기 */
details.more{margin:2px 0 0}
details.more>summary{list-style:none;cursor:pointer;user-select:none;
color:var(--accent);font-size:.82rem;font-weight:600;padding:7px 0 2px;
display:flex;align-items:center;gap:6px}
details.more>summary::-webkit-details-marker{display:none}
details.more>summary .arw{transition:transform .15s;font-size:.9em}
details.more[open]>summary .arw{transform:rotate(180deg)}
details.more[open]>summary .lbl-more{display:none}
details.more:not([open])>summary .lbl-less{display:none}
details.more>.rest{margin-top:8px}

.empty{color:var(--muted);background:var(--card);border:1px dashed var(--line);
border-radius:12px;padding:22px;text-align:center;font-size:.88rem}
footer{margin-top:40px;padding-top:16px;border-top:1px solid var(--line);color:var(--muted);font-size:.76rem}
.arc li{margin:6px 0}
.arc a{color:var(--accent);text-decoration:none}

/* 지난 기록 검색 */
.search{margin:0 0 18px}
.search input{width:100%;padding:11px 14px;border:1px solid var(--line);border-radius:10px;
background:var(--card);color:var(--fg);font-size:.92rem}
.search input::placeholder{color:var(--muted)}
.qcount{color:var(--muted);font-size:.8rem;margin:2px 0 10px}
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
    ago = _ago(item.get("ts", 0))
    meta = [f'<span class="src">{esc(item.get("source"))}</span>']
    if cnt > 1:
        meta.append(f'<span class="hot">🔥 {cnt}개 매체</span>')
    if ago:
        meta.append(f"<span>{esc(ago)}</span>")
    snip = f'<p class="snip">{esc(item["snippet"])}</p>' if item.get("snippet") else ""
    chips = ""
    if cnt > 1:
        parts = "".join(
            f'<a class="chip" href="{esc(s["url"])}" target="_blank" rel="noopener">{esc(s["name"])}</a>'
            for s in item.get("sources", [])[:8])
        chips = f'<div class="chips">{parts}</div>'
    return (
        f'<div class="card">'
        f'<a class="t" href="{esc(item["url"])}" target="_blank" rel="noopener">{esc(item["title"])}</a>'
        f'<div class="meta">{"".join(meta)}</div>{snip}{chips}</div>'
    )


def _section(group: dict, preview: int) -> str:
    preview = group.get("preview") or preview   # 그룹별 지정이 있으면 우선
    items = group.get("items", [])
    head = "".join(_card(it) for it in items[:preview])
    rest = items[preview:]
    more = ""
    if rest:
        rest_cards = "".join(_card(it) for it in rest)
        more = (
            f'<details class="more"><summary>'
            f'<span class="arw">▾</span>'
            f'<span class="lbl-more">나머지 {len(rest)}개 보기</span>'
            f'<span class="lbl-less">접기</span>'
            f'</summary><div class="rest">{rest_cards}</div></details>'
        )
    return (
        f'<section><div class="sec-h"><h2>{esc(group["label"])}</h2>'
        f'<span class="n">{group.get("count", 0)}건</span></div>{head}{more}</section>'
    )


def render_html(result: dict, rel: str = "index") -> str:
    c = result.get("counts", {})
    pv = result.get("preview_items", 5)
    gen = result.get("generated_at", "")[:16].replace("T", " ")
    srcs = " · ".join(result.get("sources", [])) or "구글뉴스"
    naver_note = "" if result.get("use_naver") else \
        ' · <span title="네이버 키 미설정">네이버 키 추가 시 정확도↑</span>'

    all_groups = result.get("groups", [])
    main_groups = [g for g in all_groups if g.get("page", "main") != "trends"]
    trend_groups = [g for g in all_groups if g.get("page") == "trends"]

    main_body = "".join(_section(g, pv) for g in main_groups)
    body = (f'<div class="book">{main_body}</div>' if main_body
            else '<div class="empty">해당 시간대에 수집된 관련 기사가 없습니다.<br>'
                 '(키워드는 keywords.yaml에서 조정)</div>')

    trend_body = "".join(_section(g, pv) for g in trend_groups)
    if trend_body:
        body += ('<div class="trend-sep" id="trends"><h2>📈 AI·콘텐츠 산업 트렌드</h2>'
                 '<span>위클리 Gcon 스타일 · 기관과 무관한 AI·콘텐츠 산업 동향(자동수집)</span></div>'
                 f'<div class="book">{trend_body}</div>')

    if rel == "index":
        nav = ('<a href="#trends">📈 산업 트렌드 &darr;</a> · '
               '<a href="archive/">지난 기록 &raquo;</a>')
    else:
        nav = '<a href="../index.html">&laquo; 오늘</a> · <a href="./">지난 기록</a>'

    if rel == "index":
        banner = ('<div class="live">🟢 <b>이 주소가 항상 최신입니다.</b> 북마크해 두고 '
                  '<b>새로고침</b>만 하면 최신 뉴스가 떠요 · 업무시간(08:35~17:35) 30분 간격 자동 갱신.'
                  '<br>※ 아래로 내리면 <a href="#trends">📈 AI·콘텐츠 산업 트렌드</a>, 지난 기록은 '
                  '<a href="archive/">아카이브</a>(제목·내용 검색 가능).</div>')
    else:
        banner = ('<div class="live">📅 이 페이지는 <b>지난 기록</b>입니다. '
                  '최신 뉴스는 <a href="../index.html">오늘 보기 »</a></div>')

    tiles = "".join(
        f'<div class="stat"><b>{c.get(k,0)}</b><span>{lbl}</span></div>'
        for k, lbl in [("collected", "수집"), ("consolidated", "통합"),
                       ("excluded", "제외"), ("multi", "복수보도")])
    stats = f'<div class="stats">{tiles}</div>'

    return f"""<!doctype html>
<html lang="ko"><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width,initial-scale=1">
<meta http-equiv="Cache-Control" content="no-cache, no-store, must-revalidate">
<meta http-equiv="Pragma" content="no-cache"><meta http-equiv="Expires" content="0">
<title>경기콘텐츠진흥원 일일 언론 모니터링 · {esc(result.get('date'))}</title>
<style>{CSS}</style></head>
<body><div class="wrap">
<header>
<h1>경기콘텐츠진흥원 일일 언론 모니터링</h1>
<div class="sub">{esc(result.get('date'))} · 최근 {esc(result.get('window_hours'))}시간 ·
소스 {esc(srcs)}{naver_note}<br>생성 {esc(gen)} KST · {nav}</div>
</header>
{banner}
{stats}
{body}
<footer>
자동 수집·정리(규칙기반, 무료). 저작권상 <b>제목·짧은 요약·원문 링크</b>만 제공하며 기사 전문은 각 언론사 원문을 확인하세요.<br>
분류·순서·필터는 <code>keywords.yaml</code>에서 편집 · GitHub Actions로 매일 자동 갱신.
</footer>
</div></body></html>"""


_SEARCH_JS = """
(function(){
  var input = document.getElementById('q');
  var out = document.getElementById('qresult');
  var list = document.querySelector('.arc');
  var idx = null, timer = null;
  function esc(s){
    return String(s||'').replace(/[&<>"']/g, function(c){
      return {'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}[c];
    });
  }
  function render(hits, kw){
    if(!hits.length){
      out.innerHTML = kw ? '<div class="empty">검색 결과가 없습니다.</div>' : '';
      return;
    }
    out.innerHTML = '<div class="qcount">' + hits.length + '건</div>' + hits.slice(0, 80).map(function(e){
      return '<div class="card"><a class="t" href="' + esc(e.u) + '" target="_blank" rel="noopener">' +
        esc(e.t) + '</a><div class="meta"><span class="src">' + esc(e.src) + '</span><span>' +
        esc(e.d) + '</span><span>' + esc(e.g) + '</span></div>' +
        (e.s ? '<p class="snip">' + esc(e.s) + '</p>' : '') + '</div>';
    }).join('');
  }
  function search(kw){
    kw = (kw || '').trim().toLowerCase();
    if(!kw){ out.innerHTML = ''; if(list) list.style.display = ''; return; }
    if(list) list.style.display = 'none';
    if(!idx){ out.innerHTML = '<div class="empty">검색 인덱스 불러오는 중…</div>'; return; }
    var hits = idx.filter(function(e){
      return (e.t && e.t.toLowerCase().indexOf(kw) !== -1) ||
             (e.s && e.s.toLowerCase().indexOf(kw) !== -1);
    });
    hits.sort(function(a, b){ return b.d.localeCompare(a.d) || b.ts - a.ts; });
    render(hits, kw);
  }
  input.addEventListener('input', function(){
    clearTimeout(timer);
    var v = input.value;
    timer = setTimeout(function(){ search(v); }, 150);
  });
  fetch('../data/search-index.json').then(function(r){ return r.json(); }).then(function(j){
    idx = j;
    input.placeholder = '제목·내용으로 검색 (' + j.length + '건 대상)';
    if(input.value) search(input.value);
  }).catch(function(){
    input.placeholder = '검색 인덱스를 불러오지 못했습니다';
    input.disabled = true;
  });
})();
"""


def _archive_index_html(entries: list) -> str:
    items = "".join(
        f'<li><a href="{esc(e["date"])}.html">{esc(e["date"])}</a> '
        f'— 통합 {e["consolidated"]}건 · 복수보도 {e["multi"]}건</li>'
        for e in entries)
    return f"""<!doctype html>
<html lang="ko"><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width,initial-scale=1">
<meta http-equiv="Cache-Control" content="no-cache, no-store, must-revalidate">
<meta http-equiv="Pragma" content="no-cache"><meta http-equiv="Expires" content="0">
<title>지난 기록 · 경기콘텐츠진흥원 언론 모니터링</title>
<style>{CSS}</style></head>
<body><div class="wrap">
<header><h1>지난 기록</h1>
<div class="sub"><a href="../index.html">&laquo; 오늘 보기</a></div></header>
<div class="search">
<input type="search" id="q" placeholder="제목·내용으로 검색" autocomplete="off">
<div id="qresult"></div>
</div>
<ul class="arc">{items or '<li class="empty">아카이브가 아직 없습니다.</li>'}</ul>
</div>
<script>{_SEARCH_JS}</script>
</body></html>"""


def write_outputs(result: dict):
    os.makedirs(ARCHIVE, exist_ok=True)
    with open(os.path.join(DOCS, "index.html"), "w", encoding="utf-8") as f:
        f.write(render_html(result, rel="index"))
    with open(os.path.join(ARCHIVE, f"{result['date']}.html"), "w", encoding="utf-8") as f:
        f.write(render_html(result, rel="archive"))
    stale = os.path.join(DOCS, "trends.html")   # 트렌드를 메인에 병합 → 옛 별도페이지 정리
    if os.path.exists(stale):
        os.remove(stale)
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


def build_search_index(days: int = 180) -> int:
    """최근 아카이브(오늘 포함) 기사를 지난 기록 검색용 경량 인덱스로 저장
    → docs/data/search-index.json (archive/index.html의 검색창이 fetch해서 사용).
    days: 포함할 최근 일수(파일 크기 관리용). 0/None이면 전체(retention 그대로)."""
    cutoff = ""
    if days:
        cutoff = (now_kst() - timedelta(days=int(days))).strftime("%Y-%m-%d")
    entries = []
    for p in sorted(glob.glob(os.path.join(DATA, "*.json"))):
        if os.path.basename(p) == "search-index.json":
            continue
        date = os.path.basename(p)[:-5]
        if cutoff and date < cutoff:
            continue
        try:
            with open(p, "r", encoding="utf-8") as f:
                d = json.load(f)
        except Exception:
            continue
        date = d.get("date", date)
        for g in d.get("groups", []):
            for it in g.get("items", []):
                entries.append({
                    "d": date, "t": it.get("title", ""),
                    "s": (it.get("snippet") or "")[:120],
                    "u": it.get("url", ""), "src": it.get("source", ""),
                    "g": g.get("label", ""), "ts": it.get("ts", 0),
                })
    with open(os.path.join(DATA, "search-index.json"), "w", encoding="utf-8") as f:
        json.dump(entries, f, ensure_ascii=False, separators=(",", ":"))
    print(f"[render] search-index.json 작성 ({len(entries)}건)")
    return len(entries)


def main():
    files = sorted(glob.glob(os.path.join(DATA, "*.json")))
    if not files:
        print("[render] docs/data/*.json 없음 — 먼저 process.py 실행")
        return
    with open(files[-1], "r", encoding="utf-8") as f:
        result = json.load(f)
    write_outputs(result)
    build_archive_index()
    build_search_index()


if __name__ == "__main__":
    main()
