#!/usr/bin/env python3
"""
usage_query.py — 查詢 Claude Usage Widget 寫下的用量紀錄（只用 Python 標準函式庫，Windows / Linux 皆可執行）

紀錄位置：與本檔同資料夾的 usage_history/usage_YYYY-MM-DD.jsonl，每行一筆：
  {"t": "2026-11-07T09:30:00+08:00", "ok": true, "src": "timer",
   "usage": {"five_hour": {"pct": 41.0, "resets_at": "..."}, "seven_day": {...}}, "error": null}

指令（輸出皆為 JSON，方便其他程式或 AI 解析）：
  latest                         最新一筆紀錄與距今秒數
  snapshot [--timeout 30]        要求小窗立即更新，等到新紀錄寫入後輸出（小窗須在執行中）
  mark LABEL [--timeout 30]      先 snapshot，再把該筆用量以 LABEL 記入 usage_history/marks.jsonl
  at TIME                        TIME 當下（或之前最近）的一筆紀錄
  diff FROM TO [--metric M ...]  兩個時間點之間的用量消耗（會處理中途額度重置）
  range FROM TO                  兩個時間點之間的所有紀錄
  marks [--last N]               列出最近的標記

FROM / TO / TIME 可以是：
  ISO 時間（例如 2026-11-07T09:00 或 "2026-11-07 09:00"；沒寫時區時，視為紀錄所用的時區）
  now                            最新一筆紀錄
  mark:LABEL                     最近一次以 LABEL 標記的時間
  now-30m / now-2h / now-1d       相對最新紀錄往前的時間

排程前後量測的典型用法：
  python usage_query.py mark "job-A start"
  ...執行排程...
  python usage_query.py mark "job-A end"
  python usage_query.py diff "mark:job-A start" "mark:job-A end"

注意：API 回傳的是整數百分比，解析度為 1%；消耗量 = 各區段內百分比上升量的總和，
遇到百分比下降（額度重置）時，該區段消耗以重置後的百分比計。
"""

import argparse
import json
import re
import sys
import time
from datetime import datetime, timedelta, timezone
from pathlib import Path

HERE = Path(__file__).resolve().parent
HISTORY_DIR = HERE / "usage_history"
MARKS_FILE = HISTORY_DIR / "marks.jsonl"
REFRESH_FLAG = HERE / ".refresh_request"


def out(obj):
    sys.stdout.write(json.dumps(obj, ensure_ascii=False, indent=1) + "\n")


def parse_t(s):
    return datetime.fromisoformat(str(s).replace("Z", "+00:00"))


def history_files():
    return sorted(HISTORY_DIR.glob("usage_*.jsonl"))


def read_records(files=None):
    recs = []
    for f in files if files is not None else history_files():
        try:
            with open(f, encoding="utf-8") as fh:
                for line in fh:
                    line = line.strip()
                    if not line:
                        continue
                    try:
                        r = json.loads(line)
                        r["_t"] = parse_t(r["t"])
                        recs.append(r)
                    except Exception:
                        continue  # 寫入中被截斷的最後一行等
        except FileNotFoundError:
            continue
    recs.sort(key=lambda r: r["_t"])
    return recs


def last_record(ok_only=False):
    for f in reversed(history_files()):
        recs = [r for r in read_records([f]) if r.get("ok") or not ok_only]
        if recs:
            return recs[-1]
    return None


def clean(r):
    return {k: v for k, v in r.items() if not k.startswith("_")} if r else None


def read_marks():
    marks = []
    if MARKS_FILE.exists():
        with open(MARKS_FILE, encoding="utf-8") as fh:
            for line in fh:
                try:
                    m = json.loads(line)
                    m["_t"] = parse_t(m["t"])
                    marks.append(m)
                except Exception:
                    continue
    return marks


def resolve_time(spec, ref_tz):
    """把 FROM/TO/TIME 轉成 aware datetime。"""
    spec = spec.strip()
    if spec == "now":
        r = last_record()
        if not r:
            raise SystemExit("no records yet")
        return r["_t"]
    if spec.startswith("mark:"):
        label = spec[5:]
        ms = [m for m in read_marks() if m.get("label") == label]
        if not ms:
            raise SystemExit(f"mark not found: {label}")
        return ms[-1]["_t"]
    m = re.fullmatch(r"now-(\d+(?:\.\d+)?)([smhd])", spec)
    if m:
        r = last_record()
        if not r:
            raise SystemExit("no records yet")
        unit = {"s": "seconds", "m": "minutes", "h": "hours", "d": "days"}[m.group(2)]
        return r["_t"] - timedelta(**{unit: float(m.group(1))})
    t = datetime.fromisoformat(spec.replace(" ", "T").replace("Z", "+00:00"))
    return t if t.tzinfo else t.replace(tzinfo=ref_tz)


def ref_tz():
    r = last_record()
    return r["_t"].tzinfo if r else datetime.now().astimezone().tzinfo


def at(t):
    best = None
    for r in read_records():
        if r["_t"] <= t and r.get("ok"):
            best = r
        elif r["_t"] > t:
            break
    return best


def consumption(recs, metric):
    """recs 已依時間排序且皆 ok；回傳 (消耗百分點, 重置次數, 起始%, 結束%)。"""
    vals = [r["usage"][metric]["pct"] for r in recs if metric in r.get("usage", {})]
    if not vals:
        return None
    used, resets = 0.0, 0
    for prev, cur in zip(vals, vals[1:]):
        if cur >= prev:
            used += cur - prev
        else:
            used += cur
            resets += 1
    return round(used, 2), resets, vals[0], vals[-1]


def cmd_latest(a):
    r = last_record()
    if not r:
        return out({"ok": False, "error": "no records yet"})
    age = (datetime.now(timezone.utc) - r["_t"]).total_seconds()
    out({"record": clean(r), "age_seconds": round(age)})


def snapshot(timeout):
    before = last_record()
    before_t = before["t"] if before else None
    try:
        REFRESH_FLAG.write_text("1", encoding="utf-8")
    except Exception as e:
        raise SystemExit(f"cannot write refresh flag: {e}")
    deadline = time.time() + timeout
    while time.time() < deadline:
        time.sleep(1)
        r = last_record()
        if r and r["t"] != before_t:
            return r
    try:
        REFRESH_FLAG.unlink()
    except Exception:
        pass
    return None


def cmd_snapshot(a):
    r = snapshot(a.timeout)
    if not r:
        return out({"ok": False, "error": f"no new record within {a.timeout}s — is the widget running?",
                    "latest": clean(last_record())})
    out({"ok": True, "record": clean(r)})


def cmd_mark(a):
    r = snapshot(a.timeout)
    warning = None
    if r is None:
        warning = "widget did not refresh in time; used latest successful record"
    elif not r.get("ok"):
        warning = f"fresh fetch failed ({r.get('error')}); used latest successful record"
    fresh = warning is None
    if not fresh:
        r = last_record(ok_only=True)
        if not r:
            return out({"ok": False, "error": "no successful records yet"})
    m = {"t": r["t"], "label": a.label, "fresh": fresh, "usage": r.get("usage", {})}
    HISTORY_DIR.mkdir(exist_ok=True)
    with open(MARKS_FILE, "a", encoding="utf-8") as fh:
        fh.write(json.dumps(m, ensure_ascii=False, separators=(",", ":")) + "\n")
    out({"ok": True, "mark": m, **({"warning": warning} if warning else {})})


def cmd_at(a):
    t = resolve_time(a.time, ref_tz())
    out({"time": t.isoformat(), "record": clean(at(t))})


def window(a):
    tz = ref_tz()
    t1, t2 = resolve_time(a.start, tz), resolve_time(a.end, tz)
    if t2 < t1:
        t1, t2 = t2, t1
    recs = [r for r in read_records() if r.get("ok")]
    start = at(t1)
    inside = [r for r in recs if t1 < r["_t"] <= t2]
    seq = ([start] if start else []) + inside
    return t1, t2, seq


def cmd_diff(a):
    t1, t2, seq = window(a)
    if len(seq) < 1:
        return out({"ok": False, "error": "no records in range"})
    metrics = a.metric or sorted({k for r in seq for k in r.get("usage", {})})
    res = {}
    for mname in metrics:
        c = consumption(seq, mname)
        if c:
            res[mname] = {"used_pct_points": c[0], "resets_in_between": c[1], "from_pct": c[2], "to_pct": c[3]}
    out({"ok": True, "from": t1.isoformat(), "to": t2.isoformat(), "from_record_t": seq[0]["t"],
         "to_record_t": seq[-1]["t"], "records": len(seq), "consumption": res,
         "note": "resolution 1 pct point; consumption counts increases, a drop is treated as a quota reset"})


def cmd_range(a):
    t1, t2, seq = window(a)
    out({"from": t1.isoformat(), "to": t2.isoformat(), "records": [clean(r) for r in seq]})


def cmd_marks(a):
    out([clean(m) for m in read_marks()[-a.last:]])


def main():
    ap = argparse.ArgumentParser(description="Query Claude Usage Widget history")
    sp = ap.add_subparsers(dest="cmd", required=True)
    sp.add_parser("latest").set_defaults(f=cmd_latest)
    p = sp.add_parser("snapshot"); p.add_argument("--timeout", type=int, default=30); p.set_defaults(f=cmd_snapshot)
    p = sp.add_parser("mark"); p.add_argument("label"); p.add_argument("--timeout", type=int, default=30); p.set_defaults(f=cmd_mark)
    p = sp.add_parser("at"); p.add_argument("time"); p.set_defaults(f=cmd_at)
    for name, fn in (("diff", cmd_diff), ("range", cmd_range)):
        p = sp.add_parser(name); p.add_argument("start"); p.add_argument("end")
        if name == "diff":
            p.add_argument("--metric", action="append", help="five_hour / seven_day / ...（可重複）")
        p.set_defaults(f=fn)
    p = sp.add_parser("marks"); p.add_argument("--last", type=int, default=20); p.set_defaults(f=cmd_marks)
    a = ap.parse_args()
    a.f(a)


if __name__ == "__main__":
    main()
