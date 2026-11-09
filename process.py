"""가공: 관련도 필터 → 동일사건 통합(중복제거) → 그룹/정렬 → 요약 카운트.

모두 규칙기반(무료). 결과는 docs/data/YYYY-MM-DD.json 에 저장.
"""
from __future__ import annotations

import glob
import json
import math
import os
import re
from collections import Counter
from difflib import SequenceMatcher

from util import (is_domainish, load_config, normalize_title, now_kst,
                  press_display, press_key, press_name, today_str)


_RE_CACHE = {}


def _match(word: str, text: str) -> bool:
    """키워드 일치 판정. 're:'로 시작하면 정규식으로 본다.

    영문 약칭(GH 등)은 단순 포함으로 보면 'HIGH'·'LIGHT'에 걸린다.
    keywords.yaml에 're:(?<![A-Za-z])GH(?![A-Za-z])' 처럼 적어 낱말 경계를 준다.
    """
    if word.startswith("re:"):
        rx = _RE_CACHE.get(word)
        if rx is None:
            rx = _RE_CACHE[word] = re.compile(word[3:])
        return bool(rx.search(text))
    return word in text


def build_group_map(cfg: dict) -> dict:
    return {g["id"]: g for g in cfg.get("groups", [])}


def is_relevant(art: dict, group: dict, global_exclude: list,
                lead_window: int = 14) -> bool:
    title = art.get("title", "")
    snip = art.get("snippet", "")
    text = f"{title} {snip}"
    for w in global_exclude:
        if w and _match(w, text):
            return False
    for w in (group.get("exclude") or []):
        if w and _match(w, text):
            return False
    # 내용 게이트(있으면): 제목/요약 어디든 하나
    req = group.get("require_any") or []
    if req and not any(_match(w, text) for w in req):
        return False
    # 주제(subject) 게이트: 아래 중 정의된 게 있으면 최소 하나는 충족해야
    #   title_any    : 제목에 하나라도(엔티티 헤드라인)
    #   lead_any     : 기사 도입부(요약 앞 N자)에 하나라도 → 사업명 제목이어도 주체가 그 기관
    #   title_all_of : 제목에 각 하위목록에서 하나씩 모두(예: 경기지역 AND 콘텐츠)
    tany = group.get("title_any") or []
    lany = group.get("lead_any") or []
    tall = group.get("title_all_of") or []
    if tany or lany or tall:
        ok = (any(_match(w, title) for w in tany)
              or any(_match(w, snip[:lead_window]) for w in lany)
              or (bool(tall) and all(any(_match(w, title) for w in sub)
                                     for sub in tall)))
        if not ok:
            return False
    return True


# ── 통합용 토큰 ───────────────────────────────────────────────────────────
# 흔한 단어(고유성 없는)는 제외 — 병합 오작동 방지
_TOK_RE = re.compile(r"[가-힣A-Za-z0-9]{2,}")
_BRACKET_RE = re.compile(r"\[[^\]]*\]")
STOP_TOKENS = set(
    "추미애 경기 경기도 지사 도지사 경기지사 경기도지사 기자 종합 인터뷰 민선 "
    "위원장 선출 의원 시장 국힘 민주당 오늘 관련".split())

# 조사·어미·복수접미사. 떼어낸 뒤 2글자 이상 남을 때만 적용한다.
# ★ 접두(startswith) 매칭을 쓰지 않는 이유: '재정난에'가 '재정'의 접두 일치로 잡히면
#   DF(희소도)를 '재정난에'(1건) 기준으로 오판해 무관한 기사가 병합된다(2026-09-07 사고).
#   대신 어미만 규칙적으로 떼어 '정확히 같은 형태'일 때만 같은 낱말로 본다.
_SUFFIXES = ("에서는", "으로는", "에게는", "이라는", "라는", "들에게", "에서", "으로",
             "에게", "까지", "부터", "보다", "마다", "조차", "처럼", "이라", "와의",
             "과의", "들의", "들이", "들은", "들을", "들", "의", "은", "는", "이",
             "가", "을", "를", "에", "와", "과", "도", "로", "만")


def _stem(w: str) -> str:
    if not ('가' <= w[0] <= '힣'):
        return w
    for suf in _SUFFIXES:
        if len(w) - len(suf) >= 2 and w.endswith(suf):
            return w[:-len(suf)]
    return w


def title_tokens(title: str) -> set:
    t = _BRACKET_RE.sub("", title or "")
    out = set()
    for w in _TOK_RE.findall(t):
        if w in STOP_TOKENS:
            continue
        s = _stem(w)
        if len(s) >= 2 and s not in STOP_TOKENS:
            out.add(s)
    return out


def _overlap(sa: set, sb: set, idf: dict):
    """겹치는 낱말 수와 변별력 가중합.

    'KB금융'과 'KB금융그룹'처럼 접두만 같은 낱말도 같은 말로 본다. 단 가중치는
    ★더 흔한 쪽(낮은 idf) 기준★ — 예전엔 min(df), 즉 더 드문 쪽으로 계산해서
    '재정'(흔함)이 '재정난'(드묾)의 희소도를 뒤집어쓰고 무관한 기사를 끌어당겼다
    (2026-09-07 '25개 매체' 오표기 사고의 근본 원인).
    """
    if len(sa) > len(sb):
        sa, sb = sb, sa
    n, w = 0, 0.0
    for x in sa:
        best = -1.0
        for y in sb:
            if x == y:
                best = idf.get(x, 4.0)
                break
            if x.startswith(y) or y.startswith(x):
                c = min(idf.get(x, 4.0), idf.get(y, 4.0))
                if c > best:
                    best = c
        if best >= 0:
            n += 1
            w += best
    return n, w


def same_story(a: dict, b: dict, threshold: float, idf: dict) -> bool:
    """같은 사건인가. ★오탐(다른 기사를 한 묶음으로)이 누락보다 훨씬 해롭다★
    — 카드에 '25개 매체'로 표시되는데 링크가 딴 기사면 신뢰가 무너진다. 보수적으로 판정."""
    if a["norm_url"] and a["norm_url"] == b["norm_url"]:
        return True
    ta, tb = a["norm_title"], b["norm_title"]
    if not ta or not tb:
        return False
    # 한쪽이 다른 쪽에 통째로 포함(부제 유무 차이) — 길이차가 크면 별개 사건일 수 있어 제한
    if (min(len(ta), len(tb)) >= 12
            and min(len(ta), len(tb)) / max(len(ta), len(tb)) >= 0.55
            and (ta in tb or tb in ta)):
        return True
    if SequenceMatcher(None, ta, tb).ratio() >= threshold:
        return True
    # 낱말 겹침 — '몇 개 겹쳤나'만 보면 긴 제목끼리 흔한 낱말로 붙는다.
    # 짧은 쪽 낱말의 몇 %가 겹쳤는지(커버리지)를 함께 본다.
    sa, sb = a["_toks"], b["_toks"]
    if not sa or not sb:
        return False
    n, w = _overlap(sa, sb, idf)
    if n < 2:
        return False
    cover = n / min(len(sa), len(sb))
    # ★몇 개 겹쳤나가 아니라 '얼마나 특징적인 낱말이 겹쳤나'로 본다★
    #   'AI·개최·경진대회'는 무관한 기사도 쉽게 겹친다(실측 가중합 7.5 → 불통합).
    #   '공공기관·직원·위기'(14.5), '청송·숏폼·영상·공모전'(16.3)은 같은 사건이었다.
    #   2026-09-07 실측(오병합 vs 정상통합 가중합):
    #     오병합 12.0 / 10.9 / 7.4   ·   정상 16.6 ~ 26.4  → 경계 14.0
    if n >= 2 and cover >= 0.40 and w >= 14.0:
        return True
    if n >= 4 and w >= 18.0:               # 겹침이 많으면 커버리지는 완화
        return True
    return False


def _entity_of(title: str, entities: list):
    """제목에 등장한 기관(별칭 묶음의 대표 표기). 못 찾으면 None."""
    for names in entities or []:
        for n in names:
            if n and _match(n, title):
                return names[0].replace("re:", "")
    return None


def _spread(items: list, window: int, entities: list) -> list:
    """상단 window칸을 서로 다른 기관으로 채운다(나머지는 받은 순서 유지).

    같은 사건이 여러 덩이로 쪼개지면 한 기관이 섹션 상단을 통째로 차지한다
    (2026-11-04: 경과원 AI 행정혁신 한 건이 상위 5칸을 독식, 경기신보 건이 묻힘).

    - 기관마다 한 칸. 그 칸의 대표는 경영·혁신 배지 기사 우선, 그다음 매체 수.
      (GH 칸에 '전원주택 공급' 대신 'GH 부채 관리·감독'이 오도록 — 섹션 목적이
      경영평가 벤치마킹이다. 배지 기준을 넓혀둬서 같은 사건의 큰 기사에도 대개
      배지가 붙으므로, 작은 조각이 대표가 되는 일은 드물다.)
    - 기관명을 특정할 수 없는 기사는 '(공통)' 한 칸. 도 재정난처럼 산하기관 전체에
      걸린 이슈가 대개 여기 속한다(2026-11-09: '공공기관 계약직 1천명 해고 위기'가
      23위에 묻혀 있었다).
    - 어느 기관이 앞칸을 받을지도 배지 기사가 있는 기관 우선.
    """
    best = {}
    for it in items:
        t = it.get("title", "")
        e = _entity_of(t, entities)
        if e is None:
            # 기관명 없는 기사는 '경기 산하기관 전체' 이야기일 때만 앞칸 후보.
            # (2026-11-05 백테스트: '국토교통부, 토지개발 인허가 AI 서비스'가
            #  'AI 서비스' 배지로 1위에 올라옴 → 경기·공공기관 언급 없으면 제외)
            if not any(w in t for w in ("경기", "공공기관", "산하기관", "출연기관")):
                continue
            e = "(공통)"
        k = (bool(it.get("flag")), it["source_count"], it["ts"])
        if e not in best or k > best[e][0]:
            best[e] = (k, it)
    ranked = sorted(best.values(), key=lambda kv: kv[0], reverse=True)
    reps = [it for _, it in ranked[:window]]
    picked = {id(x) for x in reps}
    return reps + [x for x in items if id(x) not in picked]


def process(articles: list, meta: dict, cfg: dict) -> dict:
    settings = cfg.get("settings", {})
    gmap = build_group_map(cfg)
    gexcl = cfg.get("global_exclude") or []
    thr = settings.get("min_title_similarity", 0.6)
    maxg = settings.get("max_items_per_group", 40)

    # 선거 표현 필터(경기도지사 그룹 한정): 평상시 옛 선거기사 재발행 차단.
    # ★선거철엔 keywords.yaml에서 filter_old_election_terms=false 로!★
    if settings.get("filter_old_election_terms", True) and "governor" in gmap:
        g = gmap["governor"]
        g["exclude"] = list(g.get("exclude") or []) + list(settings.get("old_election_terms") or [])

    lead_win = settings.get("lead_window", 14)
    collected = len(articles)
    kept = [a for a in articles
            if a["group"] in gmap and is_relevant(a, gmap[a["group"]], gexcl, lead_win)]
    kept.sort(key=lambda a: a["ts"], reverse=True)

    # 토큰·DF 준비(드문단어 기반 통합)
    for a in kept:
        a["_toks"] = title_tokens(a["title"])
    df = Counter()
    for a in kept:
        for w in a["_toks"]:
            df[w] += 1
    # 낱말별 변별력(IDF) — 통합 판정의 가중치
    _N = max(len(kept), 1)
    df = {w: math.log(_N / c) for w, c in df.items()}

    # ── 동일사건 통합 ────────────────────────────────────────────────────
    def _greedy(items):
        cls = []
        for a in items:
            for c in cls:
                if any(same_story(a, m, thr, df) for m in c["members"]):
                    c["members"].append(a)
                    break
            else:
                cls.append({"members": [a]})
        # 2차: 들어온 순서 탓에 쪼개진 같은 사건을 재병합.
        # ★기준 기사끼리만 비교★ — 아무 멤버나 걸리면 A~B, B~C 연쇄로 무관한 A·C까지
        #   한 덩어리가 된다(2026-09-07 '25개 매체' 오표기 사고의 증폭 경로).
        i = 0
        while i < len(cls):
            j = i + 1
            while j < len(cls):
                if same_story(cls[i]["members"][0], cls[j]["members"][0], thr, df):
                    cls[i]["members"].extend(cls[j]["members"])
                    cls.pop(j)
                else:
                    j += 1
            i += 1
        return cls

    def _pick_rep(members):
        """화면에 뜰 대표기사. 특정 기관 분류(spec 낮음)가 광범위 분류보다 우선."""
        prim = min(members, key=lambda m: (
            gmap.get(m["group"], {}).get("spec", 99), m["group_priority"]))
        pm = [m for m in members if m["group"] == prim["group"]]
        return max(pm, key=lambda m: (bool(m["snippet"]), m["ts"]))

    # 3차: 대표기사 기준 재검증.
    # 묶음 안에서는 이웃끼리만 닮아도 한 덩어리가 되지만, 사용자가 보는 건 대표 제목 하나다.
    # 대표와 직접 같은 사건이 아닌 기사는 떼어내 다시 군집시킨다(최대 4회, 나머지는 단독).
    clusters, pending, split = [], kept, 0
    for _ in range(4):
        if not pending:
            break
        rest = []
        for c in _greedy(pending):
            members = c["members"]
            rep = _pick_rep(members)
            keep = [m for m in members if m is rep or same_story(rep, m, thr, df)]
            rest.extend([m for m in members if not any(m is k for k in keep)])
            clusters.append({"members": keep, "rep": rep})
        split += len(rest)
        pending = rest
    for m in pending:
        clusters.append({"members": [m], "rep": m})

    # 4차: 회차를 넘나드는 재병합.
    # 3차 재검증은 '떨어져 나온 기사끼리'만 다시 묶으므로, 한 번 확정된 묶음과는
    # 두 번 다시 비교되지 않는다 → 제목이 완전히 같은 기사가 서로 다른 묶음으로
    # 남는 일이 생겼다(2026-11-04 실측: 경과원 AI 행정혁신 1개 사건이 20덩이).
    # 대표끼리 한 번 더 훑어 합친다(낱말이 하나도 안 겹치는 쌍은 건너뛰어 비용 절감).
    tok_idx = {}
    for i, c in enumerate(clusters):
        for t in c["rep"]["_toks"]:
            tok_idx.setdefault(t, []).append(i)
    gone = [False] * len(clusters)
    for i, c in enumerate(clusters):
        if gone[i]:
            continue
        cand = sorted({j for t in c["rep"]["_toks"]
                       for j in tok_idx.get(t, []) if j > i})
        for j in cand:
            if gone[j]:
                continue
            if same_story(c["rep"], clusters[j]["rep"], thr, df):
                c["members"].extend(clusters[j]["members"])
                gone[j] = True
    before_merge = len(clusters)
    clusters = [c for i, c in enumerate(clusters) if not gone[i]]
    remerged = before_merge - len(clusters)

    out_clusters = []
    for c in clusters:
        members, rep = c["members"], c["rep"]
        # 매체 목록: 대표기사 매체를 맨 앞에(카드의 매체명·제목·링크가 늘 같은 기사이도록),
        # 그다음 네이버(원문 URL) 우선. 같은 매체가 경로만 달라 두 번 세어지지 않게 키로 판정.
        seen, sources = set(), []
        for m in sorted(members, key=lambda m: (m is not rep,
                                                m["origin"] != "naver", -m["ts"])):
            nm = m["source"] or press_name(m["url"])
            k = press_key(nm, m["url"])
            if not k or k in seen:
                continue
            seen.add(k)
            sources.append({"name": press_display(nm, m["url"]),
                            "url": m["url"], "origin": m["origin"],
                            "title": m["title"]})
        # 매체명 매핑에 없는 곳은 도메인 그대로 들어와('metroseoul.co.kr' vs '메트로신문')
        # 같은 매체가 두 번 세어진다. 제목이 똑같고 한쪽만 도메인 표기면 같은 기사로 보고
        # 사람이 읽을 수 있는 쪽만 남긴다(모르면 적게 세는 쪽이 안전).
        by_title = {}
        for s_ in sources:
            by_title.setdefault(normalize_title(s_.get("title") or ""), []).append(s_)
        drop = set()
        for nt, grp in by_title.items():
            if not nt or len(grp) < 2:
                continue
            if any(not is_domainish(x["name"]) for x in grp):
                for x in grp:
                    if is_domainish(x["name"]):
                        drop.add(id(x))
        if drop:
            sources = [x for x in sources if id(x) not in drop]
        out_clusters.append({
            "title": rep["title"], "url": rep["url"], "snippet": rep["snippet"],
            "source": sources[0]["name"] if sources else rep["source"],
            "sources": sources, "source_count": len(sources),
            "published": rep["published"], "ts": rep["ts"],
            "group": rep["group"], "group_label": rep["group_label"],
        })

    groups_out = []
    prev_n = settings.get("preview_items", 5)
    for g in sorted(cfg.get("groups", []), key=lambda x: x.get("priority", 99)):
        items = [c for c in out_clusters if c["group"] == g["id"]]
        # boost: 그룹이 지정한 '먼저 보여줄 유형'을 섹션 맨 앞으로(그 안에서는 매체수·시각 순).
        # 건수가 많은 섹션에서 기본 노출 5개가 행사·홍보로만 채워지는 걸 막는다.
        bo = g.get("boost") or []
        if bo:
            for c in items:
                if any(_match(w, c["title"]) for w in bo):
                    c["flag"] = g.get("boost_label", "경영·혁신")
        items.sort(key=lambda c: (bool(c.get("flag")), c["source_count"], c["ts"]),
                   reverse=True)
        if g.get("spread_by_entity"):
            items = _spread(items, g.get("preview_items") or prev_n,
                            g.get("entities"))
        if items:
            groups_out.append({"id": g["id"], "label": g["label"],
                               "priority": g.get("priority", 99),
                               "page": g.get("page", "main"),
                               "preview": g.get("preview_items"),
                               "count": len(items), "items": items[:maxg]})

    multi = sum(1 for c in out_clusters if c["source_count"] > 1)
    result = {
        "date": today_str(),
        "generated_at": now_kst().isoformat(),
        "window_hours": meta.get("window_hours", settings.get("hours_window", 30)),
        "sources": meta.get("sources", []),
        "use_naver": meta.get("use_naver", False),
        "preview_items": settings.get("preview_items", 5),
        "counts": {"collected": collected, "kept": len(kept),
                   "excluded": collected - len(kept),
                   "consolidated": len(out_clusters), "multi": multi},
        "groups": groups_out,
    }
    print(f"[process] 수집 {collected} → 관련 {len(kept)} → 통합 {len(out_clusters)}개 "
          f"(제외 {collected - len(kept)}, 복수보도 {multi}, 오병합분리 {split}, 회차간재병합 {remerged})")
    return result


def _latest_raw() -> str:
    files = sorted(glob.glob(os.path.join(".cache", "raw-*.json")))
    return files[-1] if files else ""


def main():
    cfg = load_config()
    path = _latest_raw()
    if not path:
        print("[process] .cache/raw-*.json 없음 — 먼저 collect.py 실행")
        return
    with open(path, "r", encoding="utf-8") as f:
        blob = json.load(f)
    result = process(blob.get("articles", []), blob.get("meta", {}), cfg)
    os.makedirs(os.path.join("docs", "data"), exist_ok=True)
    out = os.path.join("docs", "data", f"{result['date']}.json")
    with open(out, "w", encoding="utf-8") as f:
        json.dump(result, f, ensure_ascii=False, indent=2)
    print(f"[process] 저장 → {out}")


if __name__ == "__main__":
    main()
