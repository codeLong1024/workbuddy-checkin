#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""WorkBuddy 成长空间·派猫旅行工具（单文件，纯标准库）。

用法:
    python travel.py status      查旅行状态
    python travel.py depart      派出（自动选奖励上限最高的地点）
    python travel.py depart --watch   派出并轮询，到达后自动领奖（时长随机也通用）
    python travel.py watch       轮询现有旅行直到到达并领奖（已派出时用）
    python travel.py claim       立即领奖（仅到达后有效）
    python travel.py records     旅行记录

接口（逆向 growth-space 前端确认）:
    GET  /activity/growth/buddy/travel/config    地点配置
    GET  /activity/growth/buddy/travel/status    旅行状态
    POST /activity/growth/buddy/travel/depart    派出 {location_id}
    POST /activity/growth/buddy/travel/claim     领奖 {}
    GET  /activity/growth/buddy/travel/records   记录 {page,page_size}

规则: 每日可派 1 次（自然日重置），旅行 1-4 小时，奖励 5-10 积分。
"""

import json
import os
import sys
import urllib.error
import urllib.request

API_BASE = "https://copilot.tencent.com"
AUTH_FILENAMES = ("workbuddy-desktop.info", "Tencent-Cloud.coding-copilot.info")


def auth_file_paths():
    base = os.path.join(
        os.environ.get("LOCALAPPDATA", os.path.expanduser("~/AppData/Local")),
        "CodeBuddyExtension", "Data", "Public", "auth",
    )
    return [os.path.join(base, name) for name in AUTH_FILENAMES]


def load_token():
    for path in auth_file_paths():
        if not os.path.isfile(path):
            continue
        try:
            with open(path, encoding="utf-8") as f:
                data = json.load(f)
        except (OSError, ValueError):
            continue
        auth = data.get("auth") or {}
        token = auth.get("accessToken") or ""
        if not token:
            continue
        uid = (data.get("account") or {}).get("uid") or ""
        if uid:
            return token, uid
    return None, None


def call(method, path, body=None):
    data = json.dumps(body).encode() if body is not None else None
    req = urllib.request.Request(
        API_BASE + path, data=data,
        headers={"Content-Type": "application/json", "Accept": "application/json",
                 "Authorization": "Bearer " + token, "X-User-Id": uid},
        method=method)
    try:
        with urllib.request.urlopen(req, timeout=15) as r:
            return r.status, json.loads(r.read().decode())
    except urllib.error.HTTPError as e:
        return e.code, json.loads(e.read().decode() or "{}")


def fmt_time(ts):
    import time
    return time.strftime("%H:%M", time.localtime(ts)) if ts else "-"


def iso_time(ts):
    """ISO 8601 分钟级时间，供 LLM 直接换算 scheduledAt 用。"""
    import time
    return time.strftime("%Y-%m-%dT%H:%M", time.localtime(ts)) if ts else ""


def run_watch(interval=120, timeout=6 * 3600):
    """轮询旅行状态直到到达，然后自动领奖。时长随机（1-4h）也通用。"""
    import time
    deadline = time.time() + timeout
    while True:
        code, resp = call("GET", "/activity/growth/buddy/travel/status")
        d = resp.get("data") or {}
        state = d.get("state")
        arrive = d.get("arrive_at") or 0
        now = d.get("server_now") or int(time.time())
        loc = (d.get("location") or {}).get("name", "-")
        if state == "traveling" and now < arrive:
            left = arrive - now
            print("[watch] 旅行中 {} | 还有 {:.1f}h 到达（{}）".format(
                loc, left / 3600, fmt_time(arrive)), flush=True)
            time.sleep(max(10, min(interval, left + 1)))
            continue
        # 到达 / 空闲 → 尝试领奖
        code, resp = call("POST", "/activity/growth/buddy/travel/claim", {})
        rd = resp.get("data") or {}
        if resp.get("code") == 0:
            print("✅ 领奖成功: +{} 积分".format(
                rd.get("reward_credit", rd.get("credit", 0))))
            if rd.get("letter"):
                print("信件: {}".format(rd["letter"]))
            return 0
        print("领奖未成功: code={} msg={}".format(resp.get("code"), resp.get("msg")))
        if time.time() > deadline:
            return 1
        time.sleep(interval)


def main():
    if len(sys.argv) < 2:
        print(__doc__)
        sys.exit(1)
    cmd = sys.argv[1]

    global token, uid
    token, uid = load_token()
    if not token:
        print("登录态缺失或已过期，请重新登录 WorkBuddy 客户端")
        sys.exit(2)

    if cmd == "status":
        code, resp = call("GET", "/activity/growth/buddy/travel/status")
        d = resp.get("data") or {}
        loc = d.get("location") or {}
        print("状态: {} | 地点: {} | 旅行时长: {}h | 奖励: {} 积分 | 今日上限: {}".format(
            d.get("state"), loc.get("name", "-"), d.get("duration_hours", 0),
            d.get("reward_credit", 0), "已达" if d.get("daily_limit_reached") else "未达"))
        if d.get("arrive_at"):
            if d["server_now"] >= d["arrive_at"]:
                print("预计到达: {}（已到达，可执行 claim 领奖）".format(fmt_time(d["arrive_at"])))
            else:
                left_h = (d["arrive_at"] - d["server_now"]) / 3600
                print("预计到达: {}（还有 {:.1f} 小时）".format(fmt_time(d["arrive_at"]), left_h))
            print("arrive_at_iso: {}".format(iso_time(d["arrive_at"])))
        if d.get("letter"):
            print("信件: {}".format(d["letter"]))
        sys.exit(0)

    if cmd == "depart":
        code, cfg = call("GET", "/activity/growth/buddy/travel/config")
        locs = (cfg.get("data") or {}).get("locations") or []
        if not locs:
            print("获取地点失败"); sys.exit(1)
        best = max(locs, key=lambda l: (l["reward_credit_max"], -l["sort"]))
        code, resp = call("POST", "/activity/growth/buddy/travel/depart",
                          {"location_id": best["id"]})
        d = resp.get("data") or {}
        if resp.get("code") != 0:
            print("派出失败: code={} msg={}".format(resp.get("code"), resp.get("msg")))
            # 幂等：今日已派则接管现有旅行（watch 到到达后自动领奖）
            if "--watch" in sys.argv:
                sys.exit(run_watch())
            sys.exit(1)
        # 实测坑：depart 成功响应缺 duration_hours/reward_credit（与 status 响应结构不同），
        # 直接 d.get(..., 0) 会落默认 0 → 简报曾出现"0h / 0积分"。缺字段时回查 status 补齐权威值。
        if d.get("arrive_at") is None or d.get("duration_hours") is None or d.get("reward_credit") is None:
            _, sresp = call("GET", "/activity/growth/buddy/travel/status")
            sd = sresp.get("data") or {}
            if d.get("arrive_at") is None:
                d["arrive_at"] = sd.get("arrive_at", 0)
            if d.get("duration_hours") is None:
                d["duration_hours"] = sd.get("duration_hours", 0)
            if d.get("reward_credit") is None:
                d["reward_credit"] = sd.get("reward_credit", 0)
        print("✅ 已派出: {}（{}）| {}h | 预计 {} 到达 | 奖励已锁定 {}".format(
            best["name"], best["code"], d.get("duration_hours", 0),
            fmt_time(d.get("arrive_at", 0)), d.get("reward_credit", 0)))
        if d.get("arrive_at"):
            print("arrive_at_iso: {}".format(iso_time(d["arrive_at"])))
        if "--watch" in sys.argv:
            sys.exit(run_watch())
        sys.exit(0)

    if cmd == "watch":
        sys.exit(run_watch())

    if cmd == "claim":
        code, resp = call("POST", "/activity/growth/buddy/travel/claim", {})
        d = resp.get("data") or {}
        if resp.get("code") == 0:
            print("✅ 领奖成功: +{} 积分".format(d.get("reward_credit", d.get("credit", 0))))
            if d.get("letter"):
                print("信件: {}".format(d["letter"]))
        else:
            print("领奖未成功: code={} msg={}".format(resp.get("code"), resp.get("msg")))
            sys.exit(1)
        sys.exit(0)

    if cmd == "records":
        code, resp = call("GET", "/activity/growth/buddy/travel/records",
                          {"page": 1, "page_size": 10})
        print(json.dumps(resp, ensure_ascii=False, indent=1)[:2000])
        sys.exit(0)

    print("未知命令: {}".format(cmd))
    sys.exit(1)


if __name__ == "__main__":
    main()
