#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""WorkBuddy 每日积分自动签到（单文件最小实现）。

直接读取 WorkBuddy 客户端登录态中的 accessToken，调用腾讯 copilot
签到接口完成每日签到。不依赖界面自动化，不存储任何凭证，纯标准库。

用法:
    python checkin.py            执行签到（幂等，今日已签则跳过）
    python checkin.py --dry-run  只查询签到状态，不执行签到
    python checkin.py --force    忽略"今日已签"强制调接口（依赖服务端幂等）

退出码:
    0  签到成功 / 今日已签
    1  业务失败（接口错误、网络异常重试耗尽）
    2  登录态失效或缺失，需重新登录 WorkBuddy 客户端
"""

import argparse
import base64
import json
import os
import sys
import time
import urllib.error
import urllib.request

API_BASE = "https://copilot.tencent.com/billing/meter"
AUTH_FILENAMES = ("workbuddy-desktop.info", "Tencent-Cloud.coding-copilot.info")
RETRIES = 2              # 网络/5xx 最多额外重试次数
RETRY_DELAYS = (5, 10)   # 重试间隔（秒）


def auth_file_paths():
    """CodeBuddy/WorkBuddy 官方认证文件路径（Windows）。"""
    base = os.path.join(
        os.environ.get("LOCALAPPDATA", os.path.expanduser("~/AppData/Local")),
        "CodeBuddyExtension", "Data", "Public", "auth",
    )
    return [os.path.join(base, name) for name in AUTH_FILENAMES]


def jwt_payload(token):
    """解 JWT payload，失败返回 None。"""
    try:
        payload = token.split(".")[1]
        payload += "=" * (-len(payload) % 4)
        return json.loads(base64.urlsafe_b64decode(payload))
    except Exception:
        return None


def jwt_sub(token):
    payload = jwt_payload(token)
    return (payload or {}).get("sub") or ""


def jwt_exp_ok(token, skew=300):
    """Token 有效期是否足够（预留 5 分钟余量）。"""
    payload = jwt_payload(token)
    if not payload:
        return False
    return (payload.get("exp") or 0) > time.time() + skew


def load_token():
    """从认证文件读取 (accessToken, uid)，均有效才返回。"""
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
        if not token or not jwt_exp_ok(token):
            continue
        uid = (data.get("account") or {}).get("uid") or jwt_sub(token)
        if uid:
            return token, uid
    return None, None


def api(path, token, uid):
    """调用接口一次，返回 (http_code, json_body)。"""
    req = urllib.request.Request(
        API_BASE + path,
        data=b"{}",
        headers={
            "Content-Type": "application/json",
            "Accept": "application/json",
            "Authorization": "Bearer " + token,
            "X-User-Id": uid,
        },
        method="POST",
    )
    try:
        with urllib.request.urlopen(req, timeout=15) as resp:
            return resp.status, json.loads(resp.read().decode())
    except urllib.error.HTTPError as e:
        raw = e.read().decode() or "{}"
        try:
            return e.code, json.loads(raw)
        except ValueError:
            return e.code, {"msg": raw}
    except urllib.error.URLError as e:
        raise RuntimeError("网络错误: {}".format(e.reason))


def call(path, token, uid):
    """带重试调用，仅对网络异常和 5xx 重试，401/4xx 立即返回。"""
    last = None
    for i in range(RETRIES + 1):
        try:
            code, body = api(path, token, uid)
            if code >= 500 and i < RETRIES:
                last = "HTTP {}".format(code)
                time.sleep(RETRY_DELAYS[i])
                continue
            return code, body
        except RuntimeError as e:
            last = str(e)
            if i < RETRIES:
                time.sleep(RETRY_DELAYS[i])
                continue
    raise RuntimeError(last or "请求失败")


def report(prefix, data):
    print("{} 今日积分 {} | 连续 {} 天 | 总积分 {}".format(
        prefix, data.get("today_credit", 0), data.get("streak_days", 0),
        data.get("total_credits", 0)))


def main():
    parser = argparse.ArgumentParser(description="WorkBuddy 每日签到")
    parser.add_argument("--dry-run", action="store_true", help="只查询状态")
    parser.add_argument("--force", action="store_true",
                        help="今日已签也强制调签到接口")
    args = parser.parse_args()

    token, uid = load_token()
    if not token:
        print("登录态缺失或 accessToken 已过期，请重新登录 WorkBuddy 客户端")
        sys.exit(2)

    try:
        code, body = call("/checkin-activity-status", token, uid)
    except RuntimeError as e:
        print("查询签到状态失败: {}".format(e))
        sys.exit(1)
    if code == 401:
        print("登录态失效（401），请重新登录 WorkBuddy 客户端")
        sys.exit(2)
    data = body.get("data") or {}
    active = data.get("active", False)
    checked = data.get("today_checked_in", False)
    print("活动: {} | 今日已签: {} | 连续 {} 天 | 总积分 {}".format(
        "进行中" if active else "未激活",
        "是" if checked else "否",
        data.get("streak_days", 0), data.get("total_credits", 0)))

    if args.dry_run:
        return

    if checked and not args.force:
        print("今日已签到，无需重复")
        return

    try:
        code, body = call("/daily-checkin", token, uid)
    except RuntimeError as e:
        print("签到失败: {}".format(e))
        sys.exit(1)
    if code == 401:
        print("登录态失效（401），请重新登录 WorkBuddy 客户端")
        sys.exit(2)

    biz_code = body.get("code")
    msg = body.get("msg") or ""
    if biz_code == 0:
        report("签到成功", body.get("data") or {})
        return
    if biz_code == 10001 or "已签" in msg:
        print("今日已签到（接口确认），无需重复")
        return
    print("签到失败: code={} msg={}".format(biz_code, msg))
    sys.exit(1)


if __name__ == "__main__":
    main()
