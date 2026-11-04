# -*- coding: utf-8 -*-
"""把 idolcal 打包成静态站点（dist/），供 GitHub Pages 等静态托管使用。

用法：python build_static.py
产出：dist/index.html + dist/data.json
"""
import json
import os
import shutil
import sys
import time

ROOT = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, ROOT)
os.chdir(ROOT)

import app  # noqa: E402


def main():
    groups = app.load_groups()
    events = app.build_events(force=True)

    errors = app._cache.get("errors", [])
    per = {}
    for e in events:
        per[e["group"]] = per.get(e["group"], 0) + 1
    print("\n===== 抓取结果 =====")
    for g in groups:
        n = per.get(g["name"], 0)
        print(f"{'ok  ' if n else 'FAIL'} {g['name']:18} {n:5} 场")
    if errors:
        print("\n===== 失败详情 =====")
        for e in errors:
            print(f"  {e['group']}: {e['error']}")

    out = os.path.join(ROOT, "dist")
    os.makedirs(out, exist_ok=True)

    payload = {"updated": time.time(), "groups": groups,
               "events": events, "errors": errors}
    with open(os.path.join(out, "data.json"), "w", encoding="utf-8") as f:
        json.dump(payload, f, ensure_ascii=False)

    shutil.copy(os.path.join(ROOT, "index.html"), os.path.join(out, "index.html"))
    open(os.path.join(out, ".nojekyll"), "w").close()

    print(f"\nOK: {len(events)} events / {len(groups)} groups -> {out}")
    if errors and len(errors) >= len(groups):
        sys.exit(1)


if __name__ == "__main__":
    main()
