"""파이프라인 엔트리: 수집 → 가공 → 발행 → 오래된 아카이브 정리 (CI/로컬 공용).

    python main.py

산출물: docs/index.html, docs/archive/<날짜>.html, docs/data/<날짜>.json
retention_days(설정) 지난 아카이브는 자동 삭제.
"""
from __future__ import annotations

import glob
import json
import os
import re
from datetime import timedelta

import collect
import process
import render
from util import load_config, now_kst, today_str

_DATE_RE = re.compile(r"(\d{4}-\d{2}-\d{2})")


def prune_old(days) -> int:
    """retention_days 지난 archive/*.html·data/*.json 삭제(파일명 날짜 기준). 0/None=무제한."""
    try:
        days = int(days)
    except (TypeError, ValueError):
        return 0
    if days <= 0:
        return 0
    cutoff = (now_kst() - timedelta(days=days)).strftime("%Y-%m-%d")
    removed = 0
    targets = (glob.glob(os.path.join("docs", "data", "*.json"))
               + glob.glob(os.path.join("docs", "archive", "*.html")))
    for p in targets:
        m = _DATE_RE.match(os.path.basename(p))   # archive/index.html 등은 매칭 안 됨
        if m and m.group(1) < cutoff:
            try:
                os.remove(p)
                removed += 1
            except OSError:
                pass
    if removed:
        print(f"[prune] {cutoff} 이전 아카이브 {removed}개 삭제")
    return removed


def main():
    cfg = load_config()

    articles, meta = collect.collect(cfg)

    # 원자료 캐시(비공개, .gitignore) — 재현/디버깅용
    os.makedirs(".cache", exist_ok=True)
    with open(os.path.join(".cache", f"raw-{today_str()}.json"), "w",
              encoding="utf-8") as f:
        json.dump({"meta": meta, "articles": articles}, f,
                  ensure_ascii=False, indent=2)

    result = process.process(articles, meta, cfg)

    # 처리결과 JSON(공개 docs/data) — 아카이브 목록·재렌더의 원천
    os.makedirs(os.path.join("docs", "data"), exist_ok=True)
    with open(os.path.join("docs", "data", f"{result['date']}.json"), "w",
              encoding="utf-8") as f:
        json.dump(result, f, ensure_ascii=False, indent=2)

    render.write_outputs(result)
    prune_old(cfg.get("settings", {}).get("retention_days", 0))
    render.build_archive_index()   # 정리 후 남은 것으로 목록 재생성
    print("[main] 완료")


if __name__ == "__main__":
    main()
