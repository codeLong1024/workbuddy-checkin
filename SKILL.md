---
name: workbuddy-checkin
description: WorkBuddy/腾讯 copilot 每日积分自动签到。触发词："签到"、"每日签到"、"checkin"、"积分签到"、"签到脚本"。运行 scripts/checkin.py 读取 WorkBuddy 登录态直接调用 copilot 签到接口，可配合 WorkBuddy 自动化每日定时执行并汇报结果。
agent_created: true
---

# WorkBuddy 每日签到

直接读取 WorkBuddy 客户端登录态（accessToken），调用腾讯 copilot 签到接口完成每日积分签到。不依赖界面自动化，不存储任何凭证，纯 Python 标准库单文件。

## 用法

```bash
# 执行签到（幂等：今日已签则跳过）
python <skill_dir>/scripts/checkin.py

# 只查询签到状态（不签到）
python <skill_dir>/scripts/checkin.py --dry-run

# 强制签到（忽略今日已签，依赖服务端幂等）
python <skill_dir>/scripts/checkin.py --force
```

`<skill_dir>` 指本 skill 所在目录。本机安装位置示例：`C:\Users\<你的用户名>\.workbuddy\skills\workbuddy-checkin\scripts\checkin.py`（克隆仓库到 `~/.workbuddy/skills/workbuddy-checkin/` 后即为此路径）。

## 退出码

| 码 | 含义 | 处理 |
|----|------|------|
| 0 | 签到成功 / 今日已签 | 无需处理 |
| 1 | 业务失败（接口错误、网络重试耗尽） | 查看输出，可重跑 |
| 2 | 登录态缺失/失效（401） | 需用户重新登录 WorkBuddy 客户端 |

## Token 来源

- 主来源：`%LOCALAPPDATA%\CodeBuddyExtension\Data\Public\auth\workbuddy-desktop.info` 的 `auth.accessToken`（WorkBuddy 自动续期，无需干预）
- 回退：`Tencent-Cloud.coding-copilot.info`
- 脚本不写任何配置文件，不存储凭证

## 接口路径（事实校正）

脚本使用以下端点（直接取自 WorkBuddy 客户端 `app.asar` 资源，已实际验证）：

| 用途 | 路径 |
|---|---|
| 查活动/签到状态 | `POST /billing/meter/checkin-activity-status` |
| 执行签到 | `POST /billing/meter/daily-checkin` |

注意：`/checkin-status`（无 `-activity-`）是已废弃/语义变更的老接口（仍返回 HTTP 200 但 `active=false`），sun-olympic/workbuddy-checkin 仓库用的是它，已不能正确反映客户端活动状态——切勿使用。

## 与自动化集成

创建每日 automation，prompt 模板：

```
运行签到脚本 <skill_dir>/scripts/checkin.py 完成每日签到（<skill_dir> 替换为各自机器上的实际路径，
如 C:\Users\<用户名>\.workbuddy\skills\workbuddy-checkin），
将输出（活动状态/积分/连续天数）简要汇报给用户。
若退出码为 2（登录态失效），提示用户重新登录 WorkBuddy 客户端。
```

## 故障排查

- **退出码 2**：WorkBuddy 登录态失效。打开 WorkBuddy 重新登录，Token 会自动续期，次日自动化即可恢复。
- **"活动: 未激活"**：当前签到活动未上线，属正常状态，脚本仍会尝试签到。
- **状态接口显示"未签"但签到接口返回已签**：服务端状态缓存延迟，以签到接口（code=10001）为准，属预期行为。
