# checkin 模块：每日积分签到

WorkBuddy「Buddy 加油站」每日积分自动签到：读客户端登录态直接调签到接口，纯 Python 标准库、零依赖。本模块以自用脚本分发，skill 仅保留触发壳——通过本 README 在任意 WorkBuddy 客户端安装。

**依赖 [`oracle` 模块](../oracle/README.md)**（登录态已加密，脚本不再读明文 token）。

## AI 一键安装（把本仓库链接丢给 AI 即完成）

**给 LLM 的执行手册**：用户说"安装签到"或丢来本仓库链接并指定 checkin 模块时，按以下步骤执行：

0. **先装 oracle**：按 [`oracle/README.md`](../oracle/README.md) 的「AI 一键安装」完成（缺它本模块跑不起来）
1. **检查是否已安装**：`ls ~/.workbuddy/scripts/checkin/checkin.py`
   - 已存在 → 跳过复制；不存在 → `mkdir -p ~/.workbuddy/scripts/checkin && cp <仓库路径>/checkin/scripts/checkin.py ~/.workbuddy/scripts/checkin/`
2. **验证脚本**：`python ~/.workbuddy/scripts/checkin/checkin.py --dry-run`
   - 输出含"活动:"为成功；退出码 2 → 提示用户重新登录 WorkBuddy 客户端后重试
3. **交互确认签到时间**：问用户"每天几点自动签到？"（默认 `09:10`）
4. **创建每日签到自动化**（automation_update）：
   - name: `WorkBuddy 每日自动签到`
   - scheduleType: `recurring`，rrule: `FREQ=DAILY;BYHOUR=<确认的小时>;BYMINUTE=<确认的分钟>`
   - prompt: `运行签到脚本 <实际绝对路径>/checkin.py 完成每日签到，将输出（活动状态/积分/连续天数）简要汇报给用户；若退出码为 2（登录态失效），提示用户重新登录 WorkBuddy 客户端。`
   - 若平台支持指定执行模型，选低成本模型（如混元轻量版 hy3）
5. **汇报**：脚本安装位置 + 验证结果 + 自动化任务 ID

> Windows 下 `~` = `C:\Users\<你的用户名>`；`<仓库路径>` 为 clone 后的本地路径。

## 手动安装

```bash
# 1. 放置脚本（oracle 先按 ../oracle/README.md 装好）
mkdir -p ~/.workbuddy/scripts/checkin
cp checkin/scripts/checkin.py ~/.workbuddy/scripts/checkin/
# 2. 验证（只查状态，不签到）
python ~/.workbuddy/scripts/checkin/checkin.py --dry-run
# 3. 按上文「AI 一键安装」创建每日自动化（交互确认签到时间）
```

## 用法

```bash
python checkin.py           # 签到（幂等：今日已签则跳过）
python checkin.py --dry-run # 只查询签到状态（不签到、不发通知）
python checkin.py --force   # 强制签到（忽略今日已签，依赖服务端幂等）
```

## 退出码

| 码 | 含义 | 处理 |
|----|------|------|
| 0 | 签到成功 / 今日已签 | 无需处理 |
| 1 | 业务失败（接口错误、网络重试耗尽） | 查看输出，可重跑 |
| 2 | 登录态缺失/失效（含缺 oracle、未登录客户端） | 重新登录 WorkBuddy 客户端 |

## 接口与机制（逆向确认）

- **登录态**：`%LOCALAPPDATA%\CodeBuddyExtension\Data\Public\auth\workbuddy-desktop.info` 的 `auth.accessToken`，客户端自动续期。**已加密，脚本不直接读**——统一经 `wb_oracle` 在进程内解密并代发请求
- **查询接口**：`POST copilot.tencent.com/v2/billing/meter/checkin-activity-status`（返回 `streak_days` / `today_credit` / `total_credits`）
- **签到接口**：`POST copilot.tencent.com/v2/billing/meter/daily-checkin`（幂等，已签返回 `code=10001`；成功报文含 `credit`（本次积分）/ `streak_days`，**不含总积分**——脚本本地累加：签到前 `total_credits` + 本次 `credit`，省去二次查询）
- 请求体为空 `{}`；`/v2` 前缀为客户端真实路径（逆向 `app.asar` 确认）
- ⚠️ `/billing/meter/checkin-status`（无 `-activity-`）是已废弃接口（仍返回 HTTP 200 但 `active=false`），请勿使用

## 故障排查

| 现象 | 原因 | 处理 |
|---|---|---|
| 「活动: 未激活」 | 当前无签到活动 | 属正常状态 |
| 输出「未找到 wb_oracle 目录」 | 没装 oracle 模块，或装在自定义位置 | 按 [`oracle/README.md`](../oracle/README.md) 安装；自定义位置用环境变量 `WB_ORACLE_DIR` 指定 |
| 输出「未找到 WorkBuddy 客户端」 | 客户端未安装或路径不同 | 确认客户端安装位置，脚本默认 `%LOCALAPPDATA%\Programs\WorkBuddy\WorkBuddy.exe` |
| 状态显示未签但签到返回已签 | 服务端状态缓存延迟 | 以签到接口 `code=10001` 为准，属预期行为 |

## 卸载

```bash
rm -rf ~/.workbuddy/scripts/checkin          # 删除脚本
# 在 WorkBuddy「自动化」管理页停用/删除「WorkBuddy 每日自动签到」任务
```
