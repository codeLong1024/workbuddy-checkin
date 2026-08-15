# travel 模块：派猫旅行自动领奖

WorkBuddy 成长空间「派猫旅行」：每日派出暴富喵去旅行（1-4 小时，5-10 积分），到点自动领奖。纯 Python 标准库、零依赖。**本模块以自用脚本分发，不作为 Skill 暴露**——通过本 README 在任意 WorkBuddy 客户端安装。

## AI 一键安装（把本仓库链接丢给 AI 即完成）

**给 LLM 的执行手册**：用户说"安装派猫旅行"或丢来本仓库链接并指定 travel 模块时，按以下步骤执行：

1. **检查是否已安装**：`ls ~/.workbuddy/scripts/travel/travel.py`
   - 已存在 → 跳过复制；确认与仓库最新一致可手动覆盖
   - 不存在 → 复制：`mkdir -p ~/.workbuddy/scripts/travel && cp <仓库路径>/travel/scripts/travel.py ~/.workbuddy/scripts/travel/`
2. **验证脚本**：`python ~/.workbuddy/scripts/travel/travel.py status`
   - 输出含"状态:"为成功；退出码 2 → 提示用户重新登录 WorkBuddy 客户端后重试
3. **交互确认派出时间**：问用户"每天几点派出暴富喵？"（默认 `08:00`，仅需确认小时，旅行时长 1-4h 随机由接口决定）
4. **创建每日派猫自动化**（automation_update）：
   - name: `每日派猫旅行`
   - scheduleType: `recurring`，rrule: `FREQ=DAILY;BYHOUR=<确认的小时>;BYMINUTE=0`
   - modelId: `hy3`，modelIsThinking: `false`（**必须传真布尔值 false，禁止传字符串 "false"，否则落库为 1**）
   - prompt：见下方「任务 A prompt 模板」（复用激活模式）
5. **创建领奖锚点任务**（automation_update，一次性）：
   - name: `派猫旅行领奖（一次性）`
   - scheduleType: `once`，scheduledAt: `2099-12-31T23:59`（远期占位，防未激活时误跑）
   - modelId: `hy3`，modelIsThinking: `false`
   - prompt：见下方「任务 B prompt 模板」——该任务是**常驻复用锚点**，每日由任务 A update 激活（改 scheduledAt=当天领奖时间），永不新建
6. **汇报**：脚本安装位置 + 任务 A/B 的 ID 与触发机制

> Windows 下 `~` = `C:\Users\<你的用户名>`；`<仓库路径>` 为 clone 后的本地路径（如 `~/.workbuddy/skills/workbuddy-checkin`）。

## 任务 A prompt 模板（每日派猫旅行，recurring，复用激活模式）

```
执行每日派猫旅行。运行命令：python <实际绝对路径>/travel.py depart，读取输出：

1. 若输出"已派出"且含 arrive_at_iso: YYYY-MM-DDTHH:MM → 计算领奖时间 = arrive_at_iso 加 10 分钟（用 date 命令换算），调用 automation_update 更新固定领奖任务（id=<任务B的ID>，mode=update）：scheduledAt=领奖时间，status=ACTIVE。该任务是常驻复用锚点，勿新建；若 update 报错（任务不存在），再按「mode=create，scheduleType=once，name=派猫旅行领奖（一次性），modelId="hy3"，modelIsThinking=false」创建。prompt 固定为「执行派猫旅行领奖。运行命令：python <实际绝对路径>/travel.py claim，若输出"领奖成功 +N 积分"则一句话汇报；若提示旅行未结束则调用 automation_update 更新本任务（id=<任务B的ID>，mode=update）：scheduledAt=当前时间+10 分钟（date 命令换算），status=ACTIVE；若退出码 2 则提示重新登录」。向用户简报派出结果（以脚本输出为准：时长如"3h"、奖励如"已锁定 9 积分"、预计到达时间）。

2. 若输出"派出失败"且提示已派出/达上限（今日已有旅行）→ 运行 python <实际绝对路径>/travel.py status 获取 arrive_at_iso，按第 1 条逻辑 update 固定领奖任务（id=<任务B的ID>），并简报当前旅行状态。

3. 若退出码为 2（登录态失效）→ 提示用户重新登录 WorkBuddy 客户端。
```

> 模板中 `<实际绝对路径>` 一律替换为 `C:\Users\<用户名>\.workbuddy\scripts\travel\travel.py`（Windows）或 `~/.workbuddy/scripts/travel/travel.py`（macOS/Linux）；`<任务B的ID>` 替换为安装时创建的任务 B 的实际 ID。

## 任务 B prompt 模板（派猫旅行领奖，once 常驻锚点）

```
执行派猫旅行领奖。运行命令：python <实际绝对路径>/travel.py claim，若输出"领奖成功 +N 积分"则一句话汇报；若提示旅行未结束则调用 automation_update 更新本任务（id=<任务B的ID>，mode=update）：scheduledAt=当前时间+10 分钟（用 date 命令换算），status=ACTIVE；若退出码 2 则提示重新登录
```

## 手动安装

```bash
# 1. 放置脚本
mkdir -p ~/.workbuddy/scripts/travel
cp travel/scripts/travel.py ~/.workbuddy/scripts/travel/
# 2. 验证
python ~/.workbuddy/scripts/travel/travel.py status
# 3. 按上文「AI 一键安装」创建任务 A（每日派猫）+ 任务 B（领奖锚点）
```

## 脚本用法

```bash
python travel.py status          # 查旅行状态（含 arrive_at_iso 机器可读时间）
python travel.py depart          # 派出（自动选奖励上限最高的地点，输出 arrive_at_iso）
python travel.py claim           # 立即领奖（仅到达后有效）
python travel.py records         # 旅行记录
python travel.py watch           # [备用] 挂机轮询到到达后自动领奖（秒级低延迟场景）
python travel.py depart --watch  # [备用] 派出并挂机轮询
```

关键输出：`depart`/`status` 均输出机器可读行 `arrive_at_iso: YYYY-MM-DDTHH:MM`，供自动化换算一次性任务的 scheduledAt（+10 分钟缓冲）。

## 规则（实测）

- 4 个地点（咖啡馆/商场店铺/健身房/古镇客栈），时长 1-4h 随机、奖励 5-10 积分随机（depart 时服务端锁定，独立随机）
- 状态机：`idle` → `traveling` → `arrive_at` 到达 → `claim` 领奖；每日 1 次，自然日重置
- **响应字段分布**：`config`=地点与 min/max 范围；`status`=`duration_hours` + `reward_credit`（本次确定值）；`depart`=状态字段（**无时长/奖励**，只有 arrive_at 等）；`records`=`reward_credit` 无 `duration_hours`；`claim`=到账 `reward_credit`
- 脚本内置修复：depart 响应缺时长/奖励时自动回查 status 补齐权威值
- 退出码：0 成功 | 1 业务失败 | 2 登录态失效（重新登录 WorkBuddy）

## 卸载

```bash
rm -rf ~/.workbuddy/scripts/travel          # 删除脚本
# 在 WorkBuddy「自动化」管理页停用/删除「每日派猫旅行」和「派猫旅行领奖（一次性）」两个任务
```
