# -*- coding: utf-8 -*-
"""读取 GitHub Issue 表单，把新团追加到 groups.json。

由 .github/workflows/add-group.yml 调用。
结果写入 result.txt，供工作流回帖。
"""
import json
import os
import re
import sys
import urllib.request

ROOT = os.path.dirname(os.path.abspath(__file__))
GROUPS = os.path.join(ROOT, "groups.json")
RESULT = os.path.join(os.getcwd(), "result.txt")

TT_API = "https://timetreeapp.com/api/v2/public_calendars"
H = {"X-Timetreea": "web/2.1.0/en", "Content-Type": "application/json",
     "User-Agent": "Mozilla/5.0"}


def log(msg):
    print(msg)
    with open(RESULT, "w", encoding="utf-8") as f:
        f.write(msg)


def field(body, title):
    """从 issue 表单正文里取某个字段的值。"""
    m = re.search(r"###\s*" + re.escape(title) + r"\s*\n+(.+?)(?=\n###|\Z)",
                  body, re.S)
    if not m:
        return ""
    v = m.group(1).strip()
    return "" if v in ("_No response_", "") else v


def tt_meta(alias):
    url = f"{TT_API}/{alias}"
    return json.loads(urllib.request.urlopen(
        urllib.request.Request(url, headers=H), timeout=30).read())["public_calendar"]


def main():
    body = os.environ.get("ISSUE_BODY", "")
    if not body:
        log("读不到 issue 内容")
        sys.exit(1)

    name = field(body, "团名")
    kind = field(body, "日历类型") or "TimeTree"
    ident = field(body, "日历 ID 或链接")
    color = field(body, "颜色（可选）") or "#3fa38f"

    if not ident:
        log("「日历 ID 或链接」是空的")
        sys.exit(1)

    # 从整条链接里抠出 alias
    m = re.search(r"public_calendars/([A-Za-z0-9_\-]+)", ident)
    if m:
        ident = m.group(1)
    ident = ident.strip().rstrip("/")

    typ = "gcal" if "google" in kind.lower() else "timetree"

    cfg = json.load(open(GROUPS, encoding="utf-8"))
    if any(g["id"] == ident for g in cfg["groups"]):
        log(f"`{ident}` 已经在列表里了，不用重复加")
        sys.exit(1)

    if typ == "timetree":
        try:
            cal = tt_meta(ident)
        except Exception as e:  # noqa: BLE001
            log(f"打不开这个日历：`{ident}`\n\n错误：{str(e)[:120]}\n\n"
                f"确认一下 alias 是否正确（链接里 `public_calendars/` 后面那段）。")
            sys.exit(1)
        real = cal.get("name") or ident
        name = name or real
    else:
        name = name or ident

    if not re.fullmatch(r"#[0-9a-fA-F]{6}", color):
        color = "#3fa38f"

    cfg["groups"].append({
        "name": name,
        "short": name[:3],
        "color": color,
        "type": typ,
        "id": ident,
    })
    with open(GROUPS, "w", encoding="utf-8") as f:
        json.dump(cfg, f, ensure_ascii=False, indent=2)

    log(f"已加入 **{name}**（`{ident}`，{typ}）")


if __name__ == "__main__":
    main()
