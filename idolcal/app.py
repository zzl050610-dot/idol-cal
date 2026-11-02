# -*- coding: utf-8 -*-
"""idolcal - 多个偶像团体的日程聚合器（本地 Web 应用）

支持两类数据源：
  timetree : TimeTree 公开日历 alias（timetreeapp.com/public_calendars/<alias>）
  gcal     : Google Calendar 公开日历 ID（calendar/ical/<id>/public/basic.ics）
  ics      : 任意 iCalendar URL

运行：python app.py  然后打开 http://127.0.0.1:8899
"""
import datetime as dt
import html
import json
import os
import re
import threading
import time
import urllib.error
import urllib.parse
import urllib.request
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

ROOT = os.path.dirname(os.path.abspath(__file__))
GROUPS_FILE = os.path.join(ROOT, "groups.json")
CACHE_FILE = os.path.join(ROOT, "cache.json")
INDEX_FILE = os.path.join(ROOT, "index.html")

JST = dt.timezone(dt.timedelta(hours=9))
TTL = 30 * 60  # 缓存 30 分钟
UA = {"User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64)"}
TT_HEADERS = dict(UA, **{"X-Timetreea": "web/2.1.0/en",
                         "Content-Type": "application/json"})
TT_API = "https://timetreeapp.com/api/v2/public_calendars"

_lock = threading.Lock()
_cache = {"ts": 0, "events": [], "errors": []}
_state = {"running": False, "last": 0, "count": 0, "errors": [], "error": None}


# ---------------------------------------------------------------- 数据源
def _http(url, headers, tries=3):
    last = None
    for _ in range(tries):
        try:
            return urllib.request.urlopen(
                urllib.request.Request(url, headers=headers), timeout=40).read()
        except Exception as e:  # noqa: BLE001
            last = e
            time.sleep(1.5)
    raise last


def fetch_timetree(alias):
    meta = json.loads(_http(f"{TT_API}/{alias}", TT_HEADERS))
    cal = meta["public_calendar"]
    events, cursor = [], None
    while True:
        url = f"{TT_API}/{alias}/public_events?from=0"
        if cursor:
            url += "&cursor=" + urllib.parse.quote(cursor)
        data = json.loads(_http(url, TT_HEADERS))
        events.extend(data.get("public_events") or [])
        paging = data.get("paging") or {}
        if not paging.get("next") or not paging.get("next_cursor"):
            break
        cursor = paging["next_cursor"]
    return cal.get("name") or alias, events


def fetch_ics(calendar_id):
    url = (calendar_id if calendar_id.startswith("http") else
           f"https://calendar.google.com/calendar/ical/"
           f"{urllib.parse.quote(calendar_id)}/public/basic.ics")
    raw = _http(url, UA).decode("utf-8", "ignore")
    raw = raw.replace("\r\n", "\n").replace("\n ", "").replace("\n\t", "")
    out = []
    for block in re.findall(r"BEGIN:VEVENT(.*?)END:VEVENT", raw, re.S):
        def field(name):
            m = re.search(name + r"[^:]*:(.*)", block)
            return m.group(1).strip() if m else ""
        start = field("DTSTART")
        m = re.search(r"(\d{4})(\d{2})(\d{2})(?:T(\d{2})(\d{2}))?", start)
        if not m:
            continue
        y, mo, d, hh, mm = m.groups()
        out.append({
            "start_at": int(dt.datetime(int(y), int(mo), int(d),
                                        int(hh or 0), int(mm or 0),
                                        tzinfo=JST).timestamp() * 1000),
            "title": field("SUMMARY").replace("\\,", ",").replace("\\n", " "),
            "location_name": field("LOCATION").replace("\\,", ","),
            "link_url": field("URL"),
            "note": field("DESCRIPTION").replace("\\n", "\n").replace("\\,", ","),
            "all_day": "VALUE=DATE" in start,
        })
    return calendar_id, out


def clean_note(text):
    text = text or ""
    text = re.sub(r"<br\s*/?>", "\n", text, flags=re.I)
    text = re.sub(r"</p>", "\n", text, flags=re.I)
    text = re.sub(r"<[^>]+>", "", text)
    text = html.unescape(text)
    text = re.sub(r"[ \t\u3000]+", " ", text)
    text = re.sub(r"\n{3,}", "\n\n", text)
    return text.strip()[:600]


def normalize(group, raw):
    ts = raw.get("start_at")
    if not ts:
        return None
    d = dt.datetime.fromtimestamp(ts / 1000, JST)
    url = (raw.get("link_url") or raw.get("url") or "").strip()
    if url.startswith("//"):
        url = "https:" + url
    # 很多团把「当天」录成 00:00，这种一律按无时间处理
    clock = "" if raw.get("all_day") else d.strftime("%H:%M")
    if clock in ("00:00", "23:59"):
        clock = ""
    return {
        "date": d.strftime("%Y-%m-%d"),
        "time": clock,
        "title": (raw.get("title") or "").replace("\n", " ").strip(),
        "location": (raw.get("location_name") or "").replace("\n", " ").strip(),
        "url": url,
        "note": clean_note(raw.get("note")),
        "group": group["name"],
        "color": group["color"],
        "short": group["short"],
    }


def load_groups():
    with open(GROUPS_FILE, encoding="utf-8") as f:
        return json.load(f)["groups"]


def build_events(groups=None, force=False):
    groups = groups or load_groups()
    with _lock:
        if not force and _cache["events"] and time.time() - _cache["ts"] < TTL:
            return _cache["events"]

    collected, errors = [], []
    lock = threading.Lock()

    def work(g):
        try:
            if g["type"] == "timetree":
                _, raws = fetch_timetree(g["id"])
            elif g["type"] in ("gcal", "ics"):
                _, raws = fetch_ics(g["id"])
            else:
                raise ValueError("unknown type")
            items = [x for x in (normalize(g, r) for r in raws) if x]
            with lock:
                collected.extend(items)
        except Exception as e:  # noqa: BLE001
            with lock:
                errors.append({"group": g["name"], "error": str(e)[:120]})

    threads = [threading.Thread(target=work, args=(g,)) for g in groups]
    for t in threads:
        t.start()
    for t in threads:
        t.join()

    if errors and not collected:
        raise RuntimeError("; ".join(f'{e["group"]}: {e["error"]}' for e in errors))

    collected.sort(key=lambda x: (x["date"], x["time"] or "99:99", x["group"]))
    with _lock:
        _cache.update({"ts": time.time(), "events": collected, "errors": errors})
        try:
            with open(CACHE_FILE, "w", encoding="utf-8") as f:
                json.dump(_cache, f, ensure_ascii=False)
        except OSError:
            pass
    return collected


def refresh_async():
    """后台重新抓取，立刻返回。"""
    with _lock:
        if _state["running"]:
            return False
        _state["running"] = True

    def run():
        try:
            events = build_events(force=True)
            with _lock:
                _state.update(last=time.time(), count=len(events),
                              errors=_cache.get("errors", []), error=None)
        except Exception as e:  # noqa: BLE001
            with _lock:
                _state["error"] = str(e)[:300]
        finally:
            with _lock:
                _state["running"] = False

    threading.Thread(target=run, daemon=True).start()
    return True


# ---------------------------------------------------------------- HTTP
class Handler(BaseHTTPRequestHandler):
    server_version = "idolcal/1.0"

    def log_message(self, *_):
        pass

    def _send(self, code, body, ctype="application/json; charset=utf-8"):
        if isinstance(body, str):
            body = body.encode("utf-8")
        self.send_response(code)
        self.send_header("Content-Type", ctype)
        self.send_header("Content-Length", str(len(body)))
        self.send_header("Cache-Control", "no-store")
        self.end_headers()
        self.wfile.write(body)

    def do_GET(self):  # noqa: N802
        parsed = urllib.parse.urlparse(self.path)
        path, query = parsed.path, urllib.parse.parse_qs(parsed.query)

        if path in ("/", "/index.html"):
            with open(INDEX_FILE, "rb") as f:
                return self._send(200, f.read(), "text/html; charset=utf-8")

        if path == "/api/config":
            return self._send(200, json.dumps({"groups": load_groups()},
                                              ensure_ascii=False))

        if path == "/api/status":
            with _lock:
                st = dict(_state, cached_at=_cache.get("ts", 0),
                          cached_count=len(_cache.get("events", [])))
            return self._send(200, json.dumps(st, ensure_ascii=False))

        if path == "/api/events":
            force = query.get("refresh", ["0"])[0] == "1"
            try:
                events = build_events(force=force)
            except Exception as e:  # noqa: BLE001
                return self._send(500, json.dumps({"error": str(e)[:300]},
                                                  ensure_ascii=False))
            lo = query.get("from", ["2000-01-01"])[0]
            hi = query.get("to", ["2099-12-31"])[0]
            subset = [e for e in events if lo <= e["date"] <= hi]
            return self._send(200, json.dumps(
                {"events": subset, "total": len(events),
                 "errors": _cache.get("errors", []),
                 "updated": _cache["ts"]}, ensure_ascii=False))

        return self._send(404, json.dumps({"error": "not found"}))

    def do_POST(self):  # noqa: N802
        route = urllib.parse.urlparse(self.path).path

        if route == "/api/refresh":
            started = refresh_async()
            return self._send(200, json.dumps({"started": started},
                                              ensure_ascii=False))

        if route != "/api/groups":
            return self._send(404, json.dumps({"error": "not found"}))
        length = int(self.headers.get("Content-Length") or 0)
        payload = json.loads(self.rfile.read(length) or b"{}")
        alias = (payload.get("id") or "").strip()
        kind = payload.get("type") or "timetree"
        if not alias:
            return self._send(400, json.dumps({"error": "id 不能为空"}))
        cfg = json.load(open(GROUPS_FILE, encoding="utf-8"))
        if any(g["id"] == alias for g in cfg["groups"]):
            return self._send(409, json.dumps({"error": "已存在"}))
        probe = {"name": alias, "type": kind, "id": alias}
        try:
            if kind == "timetree":
                name, raws = fetch_timetree(alias)
            else:
                name, raws = fetch_ics(alias)
                name = alias
            probe["name"] = name
            probe["short"] = name[:3]
            probe["color"] = "#888888"
            normalize(probe, raws[0]) if raws else None
        except Exception as e:  # noqa: BLE001
            return self._send(400, json.dumps({"error": f"读取失败: {str(e)[:120]}"},
                                              ensure_ascii=False))
        cfg["groups"].append(probe)
        with open(GROUPS_FILE, "w", encoding="utf-8") as f:
            json.dump(cfg, f, ensure_ascii=False, indent=2)
        build_events(force=True)
        return self._send(200, json.dumps({"ok": True, "name": probe["name"]},
                                          ensure_ascii=False))

    def do_DELETE(self):  # noqa: N802
        parsed = urllib.parse.urlparse(self.path)
        if parsed.path != "/api/groups":
            return self._send(404, json.dumps({"error": "not found"}))
        alias = (urllib.parse.parse_qs(parsed.query).get("id") or [""])[0]
        cfg = json.load(open(GROUPS_FILE, encoding="utf-8"))
        before = len(cfg["groups"])
        cfg["groups"] = [g for g in cfg["groups"] if g["id"] != alias]
        if len(cfg["groups"]) == before:
            return self._send(404, json.dumps({"error": "没找到"}))
        with open(GROUPS_FILE, "w", encoding="utf-8") as f:
            json.dump(cfg, f, ensure_ascii=False, indent=2)
        build_events(force=True)
        return self._send(200, json.dumps({"ok": True}))


def main():
    port = int(os.environ.get("PORT", "8899"))
    print(f"idolcal 启动中 … http://127.0.0.1:{port}")
    try:
        build_events()
        print(f"已载入 {len(_cache['events'])} 条日程")
        with _lock:
            _state.update(last=time.time(), count=len(_cache["events"]),
                          errors=_cache.get("errors", []))
    except Exception as e:  # noqa: BLE001
        print("首次抓取失败（页面可手动刷新）:", e)
    ThreadingHTTPServer(("127.0.0.1", port), Handler).serve_forever()


if __name__ == "__main__":
    main()
