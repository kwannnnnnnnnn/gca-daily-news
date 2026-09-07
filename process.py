"""가공: 관련도 필터 → 동일사건 통합(중복제거) → 그룹/정렬 → 요약 카운트.

모두 규칙기반(무료). 결과는 docs/data/YYYY-MM-DD.json 에 저장.
"""
from __future__ import annotations

import glob
import json
import os
import re
from collections import Counter
from difflib import SequenceMatcher

from util import (load_config, now_kst, press_key, press_name, today_str)


def build_group_map(cfg: dict) -> dict:
    return {g["id"]: g for g in cfg.get("groups", [])}


def is_relevant(art: dict, group: dict, global_exclude: list,
                lead_window: int = 14) -> bool:
    title = art.get("title", "")
    snip = art.get("snippet", "")
    text = f"{title} {snip}"
    for w in global_exclude:
        if w and w in text:
            return False
    for w in (group.get("exclude") or []):
        if w and w in text:
            return False
    # 내용 게이트(있으면): 제목/요약 어디든 하나
    req = group.get("require_any") or []
    if req and not any(w in text for w in req):
        return False
    # 주제(subject) 게이트: 아래 중 정의된 게 있으면 최소 하나는 충족해야
    #   title_any    : 제목에 하나라도(엔티티 헤드라인)
    #   lead_any     : 기사 도입부(요약 앞 N자)에 하나라도 → 사업명 제목이어도 주체가 그 기관
    #   title_all_of : 제목에 각 하위목록에서 하나씩 모두(예: 경기지역 AND 콘텐츠)
    tany = group.get("title_any") or []
    lany = group.get("lead_any") or []
    tall = group.get("title_all_of") or []
    if tany or lany or tall:
        ok = (any(w in title for w in tany)
              or any(w in snip[:lead_window] for w in lany)
              or (bool(tall) and all(any(w in title for w in sub) for sub in tall)))
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


def same_story(a: dict, b: dict, threshold: float, df: dict) -> bool:
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
    shared = sa & sb
    n = len(shared)
    if n < 2:
        return False
    cover = n / min(len(sa), len(sb))
    if n >= 4:                             # 핵심어 4개↑ 겹침 — 그 자체로 강한 신호
        return True
    if n >= 3 and cover >= 0.5:            # 핵심어 3개↑ + 절반 이상 겹침
        return True
    if n >= 2 and cover >= 0.6 and any(df.get(w, 99) <= 3 for w in shared):
        return True                        # 드문 낱말(≤3건) 포함 + 대부분 겹침
    return False


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
            sources.append({"name": press_name(m["url"], fallback=nm),
                            "url": m["url"], "origin": m["origin"],
                            "title": m["title"]})
        out_clusters.append({
            "title": rep["title"], "url": rep["url"], "snippet": rep["snippet"],
            "source": sources[0]["name"] if sources else rep["source"],
            "sources": sources, "source_count": len(sources),
            "published": rep["published"], "ts": rep["ts"],
            "group": rep["group"], "group_label": rep["group_label"],
        })

    groups_out = []
    for g in sorted(cfg.get("groups", []), key=lambda x: x.get("priority", 99)):
        items = [c for c in out_clusters if c["group"] == g["id"]]
        items.sort(key=lambda c: (c["source_count"], c["ts"]), reverse=True)
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
          f"(제외 {collected - len(kept)}, 복수보도 {multi}, 오병합분리 {split})")
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
