#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""WorkBuddy「Buddy 加油站」每日积分自动签到（单文件，纯标准库）。

不依赖界面自动化，不存储任何凭证。

用法:
    python checkin.py            执行签到（幂等，今日已签则跳过）
    python checkin.py --dry-run  只查询签到状态，不执行签到
    python checkin.py --force    忽略"今日已签"强制调接口（依赖服务端幂等）

退出码:
    0  签到成功 / 今日已签
    1  业务失败（接口错误、网络异常重试耗尽）
    2  登录态失效或缺失，需重新登录 WorkBuddy 客户端

登录态: 客户端 2026-09 起把 accessToken 改为 at-rest 加密，本脚本不再读 token，
请求统一交给 wb_oracle/（借 WorkBuddy 定制版 Electron 运行）在进程内解密并代发。
oracle 定位顺序：环境变量 WB_ORACLE_DIR > 脚本同级 > 上一级（~/.workbuddy/scripts/wb_oracle）。
"""

import argparse
import json
import os
import subprocess
import sys
import time

# 基址为 copilot.tencent.com（预言机默认值）；/v2 为客户端真实路径（app.asar 逆向确认）
STATUS_PATH = "/v2/billing/meter/checkin-activity-status"
CHECKIN_PATH = "/v2/billing/meter/daily-checkin"
RETRIES = 2              # 网络/5xx 最多额外重试次数
RETRY_DELAYS = (5, 10)   # 重试间隔（秒）

ORACLE_EXE = os.path.join(
    os.environ.get("LOCALAPPDATA", os.path.expanduser("~/AppData/Local")),
    "Programs", "WorkBuddy", "WorkBuddy.exe")
HERE = os.path.dirname(os.path.abspath(__file__))


class OracleError(RuntimeError):
    """登录态 / 预言机层错误 —— 一律映射为退出码 2（重登即可），不做重试。"""


def find_oracle_dir(here=None):
    """定位 wb_oracle 目录，找不到返回 None。

    顺序：WB_ORACLE_DIR 显式指定 > 脚本同级（单模块安装）> 上一级（共享安装）。
    """
    env = os.environ.get("WB_ORACLE_DIR")
    if env:
        return env if os.path.isfile(os.path.join(env, "main.js")) else None
    here = here or HERE
    for cand in (os.path.join(here, "wb_oracle"),
                 os.path.join(here, os.pardir, "wb_oracle")):
        if os.path.isfile(os.path.join(cand, "main.js")):
            return os.path.abspath(cand)
    return None


def parse_oracle_output(text):
    """解析预言机 stdout -> (http_status, body_dict)，定位不到状态返回 None。

    不假定首行即状态：Electron 偶尔会往 stdout 打噪音，按 `HTTP <数字>` 定位，
    该行之后全部内容作为 body。
    """
    lines = text.splitlines()
    for i, line in enumerate(lines):
        parts = line.split()
        if len(parts) == 2 and parts[0] == "HTTP" and parts[1].isdigit():
            rest = "\n".join(lines[i + 1:]).strip()
            try:
                return int(parts[1]), (json.loads(rest) if rest else {})
            except ValueError:
                return int(parts[1]), {"msg": rest}
    return None


def api(path):
    """经 wb_oracle 发起一次已鉴权 POST（body {}），返回 (http_code, json_body)。"""
    if not os.path.isfile(ORACLE_EXE):
        raise OracleError("未找到 WorkBuddy 客户端: {}".format(ORACLE_EXE))
    oracle = find_oracle_dir()
    if not oracle:
        raise OracleError("未找到 wb_oracle 目录（可用 WB_ORACLE_DIR 指定），见仓库 oracle/README.md")
    try:
        proc = subprocess.run(
            [ORACLE_EXE, oracle, "request", "POST", path, "{}"],
            capture_output=True, text=True, timeout=60)
    except (OSError, subprocess.SubprocessError) as e:
        raise OracleError("调用预言机失败: {}".format(e))
    if proc.returncode != 0:
        raise OracleError((proc.stderr or "").strip()
                          or "登录态不可用，请重新登录 WorkBuddy 客户端")
    parsed = parse_oracle_output(proc.stdout)
    if not parsed:
        raise OracleError("预言机输出异常: {}".format(proc.stdout[:200]))
    return parsed


def call(path):
    """带重试调用，仅对网络异常和 5xx 重试；登录态错误立即抛出。"""
    last = None
    for i in range(RETRIES + 1):
        try:
            code, body = api(path)
            if code >= 500 and i < RETRIES:
                last = "HTTP {}".format(code)
                time.sleep(RETRY_DELAYS[i])
                continue
            return code, body
        except OracleError:
            raise
        except RuntimeError as e:
            last = str(e)
            if i < RETRIES:
                time.sleep(RETRY_DELAYS[i])
                continue
    raise RuntimeError(last or "请求失败")


def main():
    parser = argparse.ArgumentParser(description="WorkBuddy 每日签到")
    parser.add_argument("--dry-run", action="store_true", help="只查询状态")
    parser.add_argument("--force", action="store_true",
                        help="今日已签也强制调签到接口")
    args = parser.parse_args()

    try:
        code, body = call(STATUS_PATH)
    except OracleError as e:
        print("查询签到状态失败: {}".format(e))
        sys.exit(2)
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
        code, body = call(CHECKIN_PATH)
    except OracleError as e:
        print("签到失败: {}".format(e))
        sys.exit(2)
    except RuntimeError as e:
        print("签到失败: {}".format(e))
        sys.exit(1)
    if code == 401:
        print("登录态失效（401），请重新登录 WorkBuddy 客户端")
        sys.exit(2)

    biz_code = body.get("code")
    msg = body.get("msg") or ""
    if biz_code == 0:
        d = body.get("data") or {}
        # 本地累加，省去签到后二次状态查询：
        # 总积分 = 签到前 total_credits + 本次 credit；连续天数取签到报文 streak_days（服务端权威值）。
        # 注：is_streak_day=true（连续奖励日）时服务端可能另有加成，具体以状态接口为准。
        total_after = data.get("total_credits", 0) + d.get("credit", 0)
        print("签到成功 本次 +{} 积分 | 连续 {} 天 | 总积分 {}".format(
            d.get("credit", 0), d.get("streak_days", 0), total_after))
        return
    if biz_code == 10001 or "已签" in msg:
        print("今日已签到（接口确认），无需重复")
        return
    print("签到失败: code={} msg={}".format(biz_code, msg))
    sys.exit(1)


if __name__ == "__main__":
    main()
