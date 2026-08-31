#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""WorkBuddy「Buddy 加油站」每日积分自动签到  v1.1.0

原理：读取本机 WorkBuddy 客户端登录态中的 accessToken，直接调用官方签到接口。
      不做任何 GUI 模拟点击（Electron 会过滤 isTrusted=false 的模拟事件）。

基于开源项目改造：github.com/codeLong1024/workbuddy-checkin（MIT）

v1.1.0 新增「版本更新自适应」能力：
  - 登录态文件通配扫描（*.info 按 mtime 排序），不依赖固定文件名
  - 接口路径候选回退（v2 → 无版本前缀），官方升 v3 不会立刻失效
  - JWT 判定放宽：非 JWT / 无 exp 字段的 token 交给服务端裁决，不主观判死
  - --doctor 一键自检（只读）：登录态/接口/历史健康度/计划任务
  - 连续失败连击检测：静默失效主动告警，配合 notify.ps1 弹 Windows Toast

用法:
    python checkin.py              执行签到（幂等，今日已签则跳过）
    python checkin.py --dry-run    只查询状态，不签到（安全，可放心测）
    python checkin.py --force      忽略"今日已签"强制调接口（依赖服务端幂等）
    python checkin.py --json       以 JSON 格式输出结果
    python checkin.py --quiet      静默模式（只写日志，不打终端）
    python checkin.py --doctor     环境自检（只读），失效排查第一步

退出码:
    0  签到成功 / 今日已签（幂等跳过也算成功）
    1  业务失败（网络异常、接口错误）—— 可重跑
    2  登录态缺失或失效 —— 需重新登录 WorkBuddy 客户端
"""

import argparse
import base64
import json
import os
import sys
import time
import urllib.error
import urllib.request
from datetime import datetime, timedelta

# ---------------------------------------------------------------- 常量配置

# 接口路径：v2 为客户端当前真实路径，去掉版本前缀作为回退。
# 官方若升到 v3，v2 会返回 404 —— 此时自动尝试无版本路径，避免直接失效。
API_PATHS_STATUS = ("/v2/billing/meter/checkin-activity-status",
                    "/billing/meter/checkin-activity-status")
API_PATHS_CHECKIN = ("/v2/billing/meter/daily-checkin",
                     "/billing/meter/daily-checkin")

# 域名回退顺序：优先登录态文件里的 domain，其次这些候选
DOMAIN_FALLBACKS = ("www.workbuddy.cn", "copilot.tencent.com", "www.codebuddy.cn")

# 登录态文件名（按优先级）
AUTH_FILENAMES = ("workbuddy-desktop.info", "Tencent-Cloud.coding-copilot.info")

RETRIES = 2              # 网络/5xx 最多额外重试次数
RETRY_DELAYS = (5, 10)   # 重试间隔（秒）
TIMEOUT = 15             # 单次请求超时（秒）

LOG_DIR = os.path.join(os.path.dirname(os.path.abspath(__file__)), "logs")


# ---------------------------------------------------------------- 基础工具

def _ensure_utf8_console():
    """Windows 控制台默认 GBK，中文输出会炸，强制切 UTF-8。"""
    for stream in (sys.stdout, sys.stderr):
        try:
            stream.reconfigure(encoding="utf-8", errors="replace")
        except Exception:
            pass


def mask(value, keep_head=6, keep_tail=4):
    """凭证脱敏：只留首尾少量字符 + 长度，绝不明文输出。"""
    if not isinstance(value, str) or not value:
        return "(empty)"
    if len(value) <= keep_head + keep_tail:
        return "*" * len(value)
    return "{}...{}(len={})".format(value[:keep_head], value[-keep_tail:], len(value))


def jwt_payload(token):
    """解 JWT payload，失败返回 None。"""
    try:
        payload = token.split(".")[1]
        payload += "=" * (-len(payload) % 4)
        return json.loads(base64.urlsafe_b64decode(payload))
    except Exception:
        return None


def jwt_exp_ok(token, skew=300):
    """Token 是否可用。

    关键：只在我们「能确定它过期」时才返回 False。
    若 token 不是 JWT（解析失败）或没有 exp 字段，一律放行——交给服务端 401 裁决。
    否则一旦官方把 token 换成非 JWT 格式，脚本会永远误报「登录态失效」，
    而实际上 token 完全有效（这类静默失效最难排查）。
    """
    payload = jwt_payload(token)
    if payload is None:          # 非 JWT / 解析失败 → 不主观判定
        return True
    if "exp" not in payload:     # JWT 但无过期字段 → 不主观判定
        return True
    return (payload.get("exp") or 0) > time.time() + skew


# ---------------------------------------------------------------- 登录态

def auth_file_paths():
    """返回候选登录态文件路径（Windows / macOS 都覆盖）。

    版本更新自适应：不依赖固定文件名，扫描 auth 目录下所有 *.info，
    按修改时间降序（客户端最新写的优先）。固定名仅作目录扫描失败时的兜底。
    """
    bases = []
    local = os.environ.get("LOCALAPPDATA", "")
    if local:
        bases.append(os.path.join(local, "CodeBuddyExtension",
                                  "Data", "Public", "auth"))
    home = os.path.expanduser("~")
    bases.append(os.path.join(os.environ.get("APPDATA", ""),
                              "CodeBuddyExtension", "Data", "Public", "auth"))
    bases.append(os.path.join(home, "Library", "Application Support",
                              "CodeBuddyExtension", "Data", "Public", "auth"))

    found = []
    for base in bases:
        if not os.path.isdir(base):
            continue
        try:
            infos = [os.path.join(base, f) for f in os.listdir(base)
                     if f.endswith(".info")]
            # 主登录态文件优先（避免历史备份文件里的旧 token 抢先）
            infos.sort(key=lambda p: (os.path.basename(p) != "workbuddy-desktop.info",
                                      -os.path.getmtime(p)))
            found += infos
        except OSError:
            continue
    if not found:  # 兜底：目录扫描失败时按固定名猜
        for base in bases:
            for name in AUTH_FILENAMES:
                found.append(os.path.join(base, name))
    return found


def read_json_retry(path, attempts=4, delay=0.8):
    """读 JSON 并重试。

    实测：WorkBuddy 客户端刷新 token 时会重写登录态文件，此时读取会拿到
    半截/空内容导致 json 解析失败。后台任务撞上就会误判"登录态缺失"。
    这里做短间隔重试（无 token 打印），总耗时最多约 2.4 秒。
    """
    for i in range(attempts):
        try:
            with open(path, encoding="utf-8") as f:
                raw = f.read()
            if raw.strip():
                return json.loads(raw)
        except (OSError, ValueError):
            pass
        if i < attempts - 1:
            time.sleep(delay)
    return None


def load_session():
    """读取登录态，返回 (token, uid, domain)。任一缺失返回 (None, None, None)。

    只读，绝不修改/删除登录态文件。
    """
    for path in auth_file_paths():
        if not os.path.isfile(path):
            continue
        data = read_json_retry(path)
        if not isinstance(data, dict):
            continue
        auth = data.get("auth") or {}
        token = auth.get("accessToken") or ""
        # token 过期时尝试用 refreshToken 字段兜底（客户端通常会自动刷新）
        if not token or not jwt_exp_ok(token):
            continue
        uid = (data.get("account") or {}).get("uid") or jwt_payload(token)
        uid = uid if isinstance(uid, str) else (jwt_payload(token) or {}).get("sub", "")
        domain = (auth.get("domain") or "").strip()
        if token and uid:
            return token, uid, domain
    return None, None, None


# ---------------------------------------------------------------- 网络请求

def api_post(domain, path, token, uid):
    """调用接口一次，返回 (http_code, json_body)。"""
    req = urllib.request.Request(
        "https://" + domain + path,
        data=b"{}",
        headers={
            "Content-Type": "application/json",
            "Accept": "application/json",
            "Authorization": "Bearer " + token,
            "X-User-Id": uid,
            "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
                          "AppleWebKit/537.36 Chrome/120.0 Safari/537.36",
        },
        method="POST",
    )
    try:
        with urllib.request.urlopen(req, timeout=TIMEOUT) as resp:
            return resp.status, json.loads(resp.read().decode("utf-8", "replace"))
    except urllib.error.HTTPError as e:
        raw = e.read().decode("utf-8", "replace") or "{}"
        try:
            return e.code, json.loads(raw)
        except ValueError:
            return e.code, {"msg": raw[:200]}
    except urllib.error.URLError as e:
        raise RuntimeError("网络错误: {}".format(e.reason))
    except Exception as e:  # noqa: BLE001 - 兜底，避免异常堆栈泄露 token
        raise RuntimeError("请求异常: {}".format(type(e).__name__))


def call(domains, paths, token, uid):
    """依次尝试 (路径 × 域名) 组合，带重试。返回 (http_code, json_body)。

    - 401：登录态问题，立即返回（换域名/路径也没用）
    - 404：域名或路径不对 → 换下一个组合
    - 5xx / 网络异常：重试，耗尽后换下一个组合
    """
    if isinstance(paths, str):
        paths = (paths,)
    last_err = None
    for path in paths:
        for domain in domains:
            for i in range(RETRIES + 1):
                try:
                    code, body = api_post(domain, path, token, uid)
                    if code == 401:
                        return code, body
                    if code == 404:
                        last_err = "HTTP 404 @ {}{}".format(domain, path)
                        break                      # 换下一个组合
                    if code >= 500:
                        last_err = "HTTP {} @ {}{}".format(code, domain, path)
                        if i < RETRIES:
                            time.sleep(RETRY_DELAYS[i])
                            continue
                        break
                    return code, body
                except RuntimeError as e:
                    last_err = str(e)
                    if i < RETRIES:
                        time.sleep(RETRY_DELAYS[i])
                        continue
                    break
    raise RuntimeError(last_err or "请求失败")


# ---------------------------------------------------------------- 日志

def write_log(result):
    """追加一行 JSON 日志到 logs/checkin-YYYY-MM-DD.log（不含任何凭证）。"""
    try:
        os.makedirs(LOG_DIR, exist_ok=True)
        log_file = os.path.join(
            LOG_DIR, "checkin-{}.log".format(datetime.now().strftime("%Y-%m-%d")))
        entry = dict(result)
        entry["ts"] = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        with open(log_file, "a", encoding="utf-8") as f:
            f.write(json.dumps(entry, ensure_ascii=False) + "\n")
    except Exception:
        pass  # 日志失败不影响主流程


# ---------------------------------------------------------------- 健康度

# 视为「当天 OK」的状态：签到成功 / 已签 / 活动未激活（非脚本故障）
OK_STATUSES = ("checked_in", "already_checked", "inactive")


def recent_fail_streak(max_days=7):
    """统计「截至昨天」连续多少天没成功签到。

    - 日志文件不存在 = 任务根本没跑（如电脑关机、计划任务被清），同样计为失败
    - 今天的结果尚未落盘，故从昨天开始回溯
    - 冷启动修正：以 logs/ 里最早一份日志的日期为起点，早于它的天数不累计。
      否则新装的系统每天都会误报「连续 N 天未成功签到」
    """
    today = datetime.now().date()
    # 冷启动修正：找到最早一份日志的日期
    earliest = None
    try:
        if os.path.isdir(LOG_DIR):
            for f in os.listdir(LOG_DIR):
                if f.startswith("checkin-") and f.endswith(".log"):
                    try:
                        d = datetime.strptime(f[8:-4], "%Y-%m-%d").date()
                        if earliest is None or d < earliest:
                            earliest = d
                    except ValueError:
                        continue
    except OSError:
        pass
    streak = 0
    for i in range(1, max_days + 1):
        day = today - timedelta(days=i)
        if earliest and day < earliest:
            break  # 早于安装日，不算失败
        path = os.path.join(LOG_DIR, "checkin-{}.log".format(day.strftime("%Y-%m-%d")))
        ok = False
        if os.path.isfile(path):
            try:
                with open(path, encoding="utf-8") as f:
                    for line in f:
                        try:
                            rec = json.loads(line)
                        except ValueError:
                            continue
                        if (rec.get("exit_code") == 0
                                and rec.get("status") in OK_STATUSES):
                            ok = True
                            break
            except OSError:
                pass
        if ok:
            break
        streak += 1
    return streak


def doctor():
    """一键自检：环境健康度体检，只读、不签到、不修改任何东西。

    排查"为什么没自动领到积分"时先跑这个。
    """
    print("=" * 56)
    print(" WorkBuddy Checkin Doctor  (read-only)")
    print("=" * 56)

    # 1) Python 解释器
    print("\n[1] Python")
    print("    version : {}".format(sys.version.split()[0]))
    print("    exe     : {}".format(sys.executable))
    warn_py = ".workbuddy" in sys.executable.replace("\\", "/")
    if warn_py:
        print("    [WARN] 当前 Python 位于 WorkBuddy 托管目录，")
        print("           WorkBuddy 升级/清理后可能失效，建议改用系统 Python")

    # 2) 脚本位置
    print("\n[2] Script location")
    here = os.path.dirname(os.path.abspath(__file__))
    print("    path    : {}".format(here))
    warn_dir = any(k in here.replace("\\", "/")
                   for k in ("/WorkBuddy/20", "/Temp/", "/tmp/"))
    if warn_dir:
        print("    [WARN] 位于会话工作区/临时目录，可能被清理，")
        print("           建议迁移到 C:\\Users\\<你>\\.workbuddy\\scripts\\checkin\\")

    # 3) 登录态
    print("\n[3] Login session")
    token, uid, domain = load_session()
    if not token:
        print("    [FAIL] 未读到登录态：打开 WorkBuddy 客户端重新登录一次")
    else:
        print("    token   : {}".format(mask(token)))
        print("    domain  : {}".format(domain or "(空，将用回退列表)"))
        print("    authfile: OK")

    # 4) 接口连通性
    print("\n[4] API connectivity")
    if token:
        domains = [d for d in [domain] + list(DOMAIN_FALLBACKS) if d]
        ordered, seen = [], set()
        for d in domains:
            if d not in seen:
                seen.add(d)
                ordered.append(d)
        try:
            code, body = call(ordered, API_PATHS_STATUS, token, uid)
            print("    HTTP    : {}".format(code))
            if code == 200:
                d2 = body.get("data") or {}
                print("    status  : active={} today_checked_in={} streak={} "
                      "total={}".format(
                          d2.get("active"), d2.get("today_checked_in"),
                          d2.get("streak_days"), d2.get("total_credits")))
                print("    period  : {} ~ {} (season {})".format(
                    d2.get("start_time"), d2.get("end_time"), d2.get("season")))
                if not d2.get("active"):
                    print("    [WARN] 活动当前未激活，签到会被跳过")
            elif code == 401:
                print("    [FAIL] 401 登录态失效，需重新登录客户端")
            else:
                print("    [FAIL] 接口返回 HTTP {} —— 多半是接口变更".format(code))
        except RuntimeError as e:
            print("    [FAIL] {}".format(e))
    else:
        print("    skipped (no session)")

    # 5) 历史健康度
    print("\n[5] History (based on logs/)")
    try:
        log_count = len([f for f in os.listdir(LOG_DIR) if f.endswith(".log")]) \
            if os.path.isdir(LOG_DIR) else 0
    except OSError:
        log_count = 0
    if log_count < 2:
        print("    记录不足（仅 {} 天日志），需运行 2 天以上才能判断趋势".format(log_count))
    else:
        streak = recent_fail_streak()
        if streak == 0:
            print("    OK: 昨天有成功记录")
        else:
            print("    [WARN] 连续 {} 天无成功记录（含任务未运行）".format(streak))

    # 6) Windows 计划任务
    print("\n[6] Scheduled task (Windows)")
    if sys.platform.startswith("win"):
        try:
            import subprocess
            out = subprocess.run(
                ["powershell", "-NoProfile", "-Command",
                 "$i = Get-ScheduledTaskInfo -TaskName 'WorkBuddyDailyCheckin' "
                 "-ErrorAction SilentlyContinue; "
                 "if ($i) { $t = Get-ScheduledTask -TaskName 'WorkBuddyDailyCheckin'; "
                 "Write-Output ('FOUND state=' + $t.State + ' lastResult=' + "
                 "$i.LastTaskResult + ' nextRun=' + $i.NextRunTime) } "
                 "else { Write-Output 'NOTFOUND' }"],
                capture_output=True, text=True, timeout=30)
            line = (out.stdout or "").strip().splitlines()
            val = line[-1] if line else "UNKNOWN"
            if val == "NOTFOUND":
                print("    [FAIL] 任务未注册，运行 install.bat")
            else:
                print("    {}".format(val))
        except Exception as e:  # noqa: BLE001
            print("    [SKIP] 无法查询: {}".format(type(e).__name__))
    else:
        print("    skipped (not Windows)")

    print("\n" + "=" * 56)
    print(" Doctor done. 此命令只读，不会签到、不会改动任何东西。")
    print("=" * 56)


# ---------------------------------------------------------------- 主流程

def main():
    _ensure_utf8_console()
    parser = argparse.ArgumentParser(description="WorkBuddy 每日积分自动签到 v1.1.0")
    parser.add_argument("--dry-run", action="store_true", help="只查询状态，不签到")
    parser.add_argument("--force", action="store_true",
                        help="今日已签也强制调签到接口（依赖服务端幂等）")
    parser.add_argument("--json", action="store_true", help="以 JSON 输出结果")
    parser.add_argument("--quiet", action="store_true", help="静默，只写日志")
    parser.add_argument("--doctor", action="store_true",
                        help="环境自检（只读）：Python/目录/登录态/接口/历史/计划任务")
    args = parser.parse_args()

    if args.doctor:
        doctor()
        sys.exit(0)

    def emit(result, exit_code=0):
        """统一出口：写日志 → 输出 → 退出。"""
        result["exit_code"] = exit_code
        # 静默失效最危险：本次失败 + 之前连续多天也没成功 → 显式告警
        if exit_code != 0 and not args.quiet:
            streak = recent_fail_streak()
            if streak >= 2:
                result["fail_streak"] = streak
                result["message"] += (
                    " | 已连续 {} 天未成功签到，多为接口变更或客户端版本更新，"
                    "请运行 checkin.py --doctor 自检").format(streak)
        write_log(result)
        if not args.quiet:
            if args.json:
                print(json.dumps(result, ensure_ascii=False))
            else:
                print(result.get("message", ""))
        sys.exit(exit_code)

    # 1) 读登录态
    token, uid, domain = load_session()
    if not token:
        emit({
            "ok": False,
            "status": "no_session",
            "message": "登录态缺失或 accessToken 已过期，请打开 WorkBuddy 客户端重新登录",
        }, 2)

    domains = [d for d in [domain] + list(DOMAIN_FALLBACKS) if d]
    seen, ordered = set(), []
    for d in domains:                      # 去重保序
        if d not in seen:
            seen.add(d)
            ordered.append(d)

    # 2) 查状态（只读，不会领积分）
    try:
        code, body = call(ordered, API_PATHS_STATUS, token, uid)
    except RuntimeError as e:
        emit({"ok": False, "status": "network_error",
              "step": "query", "detail": str(e),
              "message": "查询签到状态失败: {}".format(e)}, 1)
    if code == 401:
        emit({"ok": False, "status": "unauthorized",
              "message": "登录态失效（401），请打开 WorkBuddy 客户端重新登录"}, 2)
    if code != 200:
        emit({"ok": False, "status": "api_error", "http_code": code,
              "message": "查询签到状态失败: HTTP {}".format(code)}, 1)

    data = body.get("data") or {}
    active = bool(data.get("active", False))
    checked = bool(data.get("today_checked_in", False))
    streak = data.get("streak_days", 0)          # 实测为「累计签到天数」，非连续天数
    total = data.get("total_credits", 0)         # 实测为「本期活动累计积分」，非账号总余额
    end_time = (data.get("end_time") or "")[:10]
    season = data.get("season", 0)

    # 活动到期提醒：实测活动按「期」滚动（本期 2026-08-13 ~ 2026-08-31），
    # 到期后接口可能直接失效，需人工确认新一期是否已上线。
    expire_note = ""
    if end_time:
        try:
            left = (datetime.strptime(end_time, "%Y-%m-%d").date()
                    - datetime.now().date()).days
            if left < 0:
                expire_note = " | ⚠ 活动已于 {} 到期，请确认新一期".format(end_time)
            elif left <= 3:
                expire_note = " | ⚠ 活动 {} 到期（剩 {} 天）".format(end_time, left)
        except ValueError:
            pass

    state_line = ("活动: {}{} | 今日已签: {} | 累计签到 {} 天 | 本期积分 {}".format(
        "进行中" if active else "未激活",
        " (第{}期)".format(season) if season else "",
        "是" if checked else "否", streak, total))
    state_line += expire_note

    if args.dry_run:
        emit({"ok": True, "status": "dry_run", "active": active,
              "today_checked_in": checked, "streak_days": streak,
              "total_credits": total, "end_time": end_time, "season": season,
              "message": "[DRY-RUN] " + state_line})

    # 活动未激活：不是脚本故障，属正常跳过，但必须明确提示以便人工介入
    if not active:
        emit({"ok": True, "status": "inactive", "season": season,
              "end_time": end_time, "total_credits": total,
              "message": "签到活动未激活（本期已结束或新一期未上线），本次跳过 | "
                         + state_line})

    if checked and not args.force:
        emit({"ok": True, "status": "already_checked", "streak_days": streak,
              "total_credits": total, "end_time": end_time,
              "message": "今日已签到，无需重复 | " + state_line})

    # 3) 签到
    try:
        code, body = call(ordered, API_PATHS_CHECKIN, token, uid)
    except RuntimeError as e:
        emit({"ok": False, "status": "network_error", "step": "checkin",
              "detail": str(e), "message": "签到失败: {}".format(e)}, 1)
    if code == 401:
        emit({"ok": False, "status": "unauthorized",
              "message": "登录态失效（401），请打开 WorkBuddy 客户端重新登录"}, 2)
    if code != 200:
        # 实测：今日已签时强制调用会返回 HTTP 400，而非业务码 10001。
        # 这类"重复签到"属于正常幂等情况，必须按成功退出，避免误报失败。
        hint = "{} {}".format(body.get("msg") or "", json.dumps(body, ensure_ascii=False))
        if any(k in hint for k in ("已签", "重复", "already", "checked")):
            emit({"ok": True, "status": "already_checked",
                  "streak_days": streak, "total_credits": total,
                  "message": "今日已签到（HTTP {} 接口确认），无需重复".format(code)})
        emit({"ok": False, "status": "api_error", "http_code": code,
              "detail": (body.get("msg") or "")[:200],
              "message": "签到失败: HTTP {}".format(code)}, 1)

    biz_code = body.get("code")
    msg = body.get("msg") or ""
    d = body.get("data") or {}

    if biz_code == 0:
        credit = d.get("credit", 0)
        new_streak = d.get("streak_days", streak)
        emit({
            "ok": True, "status": "checked_in", "credit": credit,
            "streak_days": new_streak,
            "total_credits": total + credit, "end_time": end_time,
            "message": "签到成功 本次 +{} 积分 | 累计签到 {} 天 | 本期积分约 {}{}".format(
                credit, new_streak, total + credit, expire_note),
        })
    if biz_code == 10001 or "已签" in msg:
        emit({"ok": True, "status": "already_checked", "streak_days": streak,
              "total_credits": total, "end_time": end_time,
              "message": "今日已签到（接口确认 code={}），无需重复".format(biz_code)})

    emit({"ok": False, "status": "biz_error", "biz_code": biz_code,
          "detail": msg, "message": "签到失败: code={} msg={}".format(biz_code, msg)}, 1)


if __name__ == "__main__":
    main()
