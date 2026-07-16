"""파이프라인 엔트리: 수집 → 가공 → 발행 (CI/로컬 공용).

    python main.py

산출물: docs/index.html, docs/archive/<날짜>.html, docs/data/<날짜>.json
"""
from __future__ import annotations

import json
import os

import collect
import process
import render
from util import load_config, today_str


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
    render.build_archive_index()
    print("[main] 완료")


if __name__ == "__main__":
    main()
