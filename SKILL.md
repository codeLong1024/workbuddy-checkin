---
name: workbuddy-checkin
description: WorkBuddy/腾讯 copilot 每日积分自动签到。触发词："签到"、"每日签到"、"checkin"、"积分签到"、"签到脚本"、"安装签到"、"部署签到"。已安装则运行 ~/.workbuddy/scripts/checkin/checkin.py 完成签到；未安装则引导用户提供/确认仓库链接，按仓库 checkin/README.md「AI 一键安装」节自动安装并创建每日自动化。
agent_created: true
---

# WorkBuddy 每日签到

读 WorkBuddy 登录态调 copilot 签到接口。纯标准库，零凭证落盘。脚本以自用脚本分发（非技能注入），安装/卸载/接口细节见仓库 `checkin/README.md`。

**依赖**：`~/.workbuddy/scripts/wb_oracle/`（登录态已 at-rest 加密，脚本不再读明文 token）。缺它退出码 2，安装见仓库 `oracle/README.md`。

## 已安装（本机）

```bash
python ~/.workbuddy/scripts/checkin/checkin.py           # 签到（幂等：今日已签则跳过）
python ~/.workbuddy/scripts/checkin/checkin.py --dry-run # 只查状态，不签到
python ~/.workbuddy/scripts/checkin/checkin.py --force   # 强制签到（依赖服务端幂等）
```

退出码：0 成功/已签 | 1 业务失败 | 2 登录态失效（重新登录 WorkBuddy）。

## 未安装（部署）

仓库：`https://github.com/codeLong1024/workbuddy-checkin`——按 `checkin/README.md` 的「AI 一键安装」节执行复制脚本 + 创建每日自动化。全部细节见 README。
