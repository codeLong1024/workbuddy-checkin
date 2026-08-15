# workbuddy-checkin

WorkBuddy / 腾讯 copilot 每日打卡积分全家桶 —— 读取 WorkBuddy 客户端登录态直接调接口，纯 Python 标准库、零依赖、零凭证落盘。

## 功能模块（可插拔安装）

| 模块 | 功能 | 安装方式 | 位置 |
|------|------|------|------|
| **签到 checkin** | 每日积分签到（幂等） | 本仓库根目录 `scripts/checkin.py`，见下文「AI 一键部署」 | `~/.workbuddy/skills/workbuddy-checkin/` |
| **派猫旅行 travel** | 每日派出暴富喵旅行 + 到点自动领奖 | `travel/` 模块，见 [travel/README.md](travel/README.md) | `~/.workbuddy/scripts/travel/` |

丢仓库链接给 AI，说"安装签到"或"安装派猫旅行"，AI 按对应模块的 README 自动完成下载 + 创建自动化（会交互确认触发时间）。

## 特性（checkin 模块）

- **免界面自动化**：直接读取 WorkBuddy 已登录的 accessToken（JWT），调用腾讯 copilot 签到接口
- **幂等安全**：今日已签自动跳过（服务端 `code=10001` 判定），可反复执行无副作用
- **零凭证存储**：不写配置文件、不保存 Token，登录态失效时提示重新登录客户端即可
- **单文件**：仅 `scripts/checkin.py`（120 行，纯标准库，Python 3.8+）
- **静默失败重试**：网络异常/5xx 自动重试 2 次（5s/10s）

## AI 一键部署（把仓库链接丢给 AI 即可完成安装）

**给 LLM 的执行手册**：用户说"帮我安装/部署 workbuddy-checkin"或丢来本仓库链接时，按以下步骤执行：

1. **检查是否已安装**：`ls ~/.workbuddy/skills/workbuddy-checkin/scripts/checkin.py`
   - 已存在 → 跳过 clone，执行 `git -C ~/.workbuddy/skills/workbuddy-checkin pull` 更新
   - 不存在 → `git clone https://github.com/codeLong1024/workbuddy-checkin ~/.workbuddy/skills/workbuddy-checkin`
2. **验证脚本**：`python ~/.workbuddy/skills/workbuddy-checkin/scripts/checkin.py --dry-run`
   - 输出含"活动:"或退出码为 0/2 → 部署成功；退出码 2 → 提示用户重新登录 WorkBuddy 后重试
3. **创建每日自动化**（用户需要时）：用 automation_update 创建：
   - name: `WorkBuddy 每日自动签到`
   - scheduleType: `recurring`，rrule: `FREQ=DAILY;BYHOUR=9;BYMINUTE=10`
   - prompt: `运行签到脚本 <实际绝对路径>/checkin.py 完成每日签到，将输出（活动状态/积分/连续天数）简要汇报给用户；若退出码为 2（登录态失效），提示用户重新登录 WorkBuddy 客户端。`
   - 若平台支持指定执行模型，选低成本模型（如混元轻量版）
4. **汇报**：安装位置 + 验证结果 + 自动化任务 ID

> Windows 下 `~` = `C:\Users\<你的用户名>`。

## 安装（2 分钟）

```bash
# 克隆到 WorkBuddy 用户级 skills 目录
git clone https://github.com/codeLong1024/workbuddy-checkin ~/.workbuddy/skills/workbuddy-checkin

# 立即验证（只查状态，不签到）
python ~/.workbuddy/skills/workbuddy-checkin/scripts/checkin.py --dry-run
```

> Windows 下 `~` 为 `C:\Users\<你的用户名>`。安装后 WorkBuddy 会自动热加载该 skill（重启 WorkBuddy 更保险）。

## 用法

```bash
# 执行签到（幂等：今日已签则跳过）
python <skill_dir>/scripts/checkin.py

# 只查询签到状态（不签到、不发通知）
python <skill_dir>/scripts/checkin.py --dry-run

# 强制签到（忽略今日已签，依赖服务端幂等）
python <skill_dir>/scripts/checkin.py --force
```

### 退出码

| 码 | 含义 | 处理 |
|----|------|------|
| 0 | 签到成功 / 今日已签 | 无需处理 |
| 1 | 业务失败（接口错误、网络重试耗尽） | 查看输出，可重跑 |
| 2 | 登录态缺失/失效 | 重新登录 WorkBuddy 客户端 |

## 与 WorkBuddy 自动化集成（推荐：每日自动签到）

在 WorkBuddy 自动化中创建每日任务，调度 `FREQ=DAILY;BYHOUR=9;BYMINUTE=10`，prompt：

```
运行签到脚本 <skill_dir>/scripts/checkin.py 完成每日签到
（<skill_dir> 替换为各自机器实际路径，如 C:\Users\<用户名>\.workbuddy\skills\workbuddy-checkin），
将输出（活动状态/积分/连续天数）简要汇报给用户。
若退出码为 2（登录态失效），提示用户重新登录 WorkBuddy 客户端。
```

自动化跑完自动汇报结果，即完成「签到 + 通知」闭环。

## Token 与接口说明

- **Token 来源**：`%LOCALAPPDATA%\CodeBuddyExtension\Data\Public\auth\workbuddy-desktop.info` 的 `auth.accessToken`，WorkBuddy 客户端自动续期，脚本只读不改
- **查询接口**：`POST /v2/billing/meter/checkin-activity-status`（返回 `streak_days` / `today_credit` / `total_credits`）
- **签到接口**：`POST /v2/billing/meter/daily-checkin`（幂等，已签返回 `code=10001`；成功报文含 `credit`（本次积分）/ `streak_days`，**不含总积分**——脚本本地累加：签到前 `total_credits` + 本次 `credit`，省去二次查询）
- 请求体为空 `{}`，鉴权仅靠 `Authorization: Bearer <JWT>` + `X-User-Id`
- `/v2` 前缀为客户端真实路径（逆向 `app.asar` 确认），无 `v2` 版本服务端仍兼容但非主路径，请勿依赖

> ⚠️ `/billing/meter/checkin-status`（无 `-activity-`）是已废弃接口（仍返回 HTTP 200 但 `active=false`），请勿使用。

## 安全

- 脚本不存储任何凭证，`checkin_config.json` 等配置文件不存在、也不需要
- Token 即登录态，请勿分享认证文件 `workbuddy-desktop.info`
- 本项目仅供个人自动化学习，使用者须自行遵守腾讯 copilot 服务条款与所在公司合规要求

## 免责声明（Disclaimer）

1. **接口归属**：本项目所调用接口均位于 `copilot.tencent.com` 域名下，接口及其返回的数据、权益均归腾讯公司（或其关联公司）所有。本项目与腾讯公司无任何隶属、授权或合作关系，不代表腾讯公司立场或背书。
2. **商标声明**：WorkBuddy、腾讯 copilot 等名称与标识均为腾讯公司（或其关联公司）的商标或服务标识，仅在本项目中用于描述兼容对象；本项目为独立第三方工具，未经腾讯公司审核或认可。
3. **使用边界**：本项目仅供个人自动化学习与技术研究，禁止用于商业用途，禁止用于任何违反腾讯服务条款、法律法规或使用者所在组织合规要求的行为（含公司内部大规模使用）。
4. **接口稳定性**：签到接口由腾讯公司独立控制，可能随时变更、调整或下线。本项目不保证接口的持续可用性，亦不承诺脚本永续有效；因接口变更导致的失效，作者不承担任何责任。
5. **责任承担**：使用者应自行评估使用风险（包括但不限于账号安全、数据安全与合规风险），因使用本项目产生的任何直接或间接后果，由使用者自行承担，作者不承担任何责任。
6. **无担保**：本项目按「现状」（AS-IS）提供，不提供任何明示或默示的担保。
7. **配合下架**：如腾讯公司或相关权利方认为本项目存在合规问题，作者将积极配合处理（包括但不限于移除相关接口信息或下架项目）。

## 故障排查

| 现象 | 原因 | 处理 |
|---|---|---|
| 退出码 2 | WorkBuddy 登录态失效 | 打开 WorkBuddy 重新登录，Token 自动续期 |
| 「活动: 未激活」 | 当前无签到活动 | 属正常状态，脚本仍会尝试签到 |
| 状态显示未签但签到返回已签 | 服务端状态缓存延迟 | 以签到接口 `code=10001` 为准，属预期行为 |

## License

MIT
