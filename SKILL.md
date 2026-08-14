---
name: workbuddy-checkin
description: WorkBuddy/腾讯 copilot 每日积分自动签到。触发词："签到"、"每日签到"、"checkin"、"积分签到"、"签到脚本"。运行 scripts/checkin.py 读取 WorkBuddy 登录态直接调用 copilot 签到接口，可配合 WorkBuddy 自动化每日定时执行并汇报结果。
agent_created: true
---

# WorkBuddy 每日签到

直接读 WorkBuddy 登录态 accessToken 调 copilot 签到接口。纯标准库单文件，零凭证落盘。

## 用法

```bash
python <skill_dir>/scripts/checkin.py           # 签到（幂等：今日已签则跳过）
python <skill_dir>/scripts/checkin.py --dry-run # 只查状态，不签到
python <skill_dir>/scripts/checkin.py --force   # 强制调签到接口（依赖服务端幂等）
```

`<skill_dir>` = 本 skill 目录，如 `C:\Users\<你的用户名>\.workbuddy\skills\workbuddy-checkin`。

## 退出码

| 码 | 含义 | 处理 |
|---|---|---|
| 0 | 签到成功 / 今日已签 | 无需处理 |
| 1 | 业务失败（接口错误、网络重试耗尽） | 查看输出，可重跑 |
| 2 | 登录态缺失/失效（401） | 重新登录 WorkBuddy 客户端 |

## Token 来源

`%LOCALAPPDATA%\CodeBuddyExtension\Data\Public\auth\workbuddy-desktop.info` 的 `auth.accessToken`（WorkBuddy 自动续期）；回退 `Tencent-Cloud.coding-copilot.info`。

## 接口

| 用途 | 路径 |
|---|---|
| 查活动/签到状态 | `POST /v2/billing/meter/checkin-activity-status` |
| 执行签到 | `POST /v2/billing/meter/daily-checkin`（已签返回 `code=10001`，预期幂等） |

勿用 `/checkin-status`（无 `-activity-`，已废弃：HTTP 200 但 `active=false`）。报文字段与本地累加逻辑见 README.md。

## 与自动化集成

每日 automation prompt 模板：

```
运行签到脚本 <skill_dir>/scripts/checkin.py 完成每日签到（<skill_dir> 替换为各自机器实际路径，
如 C:\Users\<用户名>\.workbuddy\skills\workbuddy-checkin），
将输出（活动状态/积分/连续天数）简要汇报给用户。
若退出码为 2（登录态失效），提示用户重新登录 WorkBuddy 客户端。
```

## 故障排查

- **退出码 2**：登录态失效。重登 WorkBuddy，Token 自动续期，次日恢复。
- **"活动: 未激活"**：当前无签到活动，属正常状态，脚本仍会尝试签到。
- **状态"未签"但签到返回已签**：服务端缓存延迟，以 `code=10001` 为准，属预期。

## 免责声明

接口归腾讯所有，无隶属/授权关系；仅供个人自动化学习，禁止商业用途，使用者自负风险。完整声明见仓库 README。
