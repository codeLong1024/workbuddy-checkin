# workbuddy-checkin

WorkBuddy / 腾讯 copilot 每日打卡积分全家桶 —— 读本机客户端登录态直接调接口，纯 Python 标准库、零依赖、零凭证落盘。

> **仓库地址（两个入口内容一致，用能打开的那个）**
> - GitHub：[codeLong1024/workbuddy-checkin](https://github.com/codeLong1024/workbuddy-checkin)
> - 国内镜像：[cnb.cool/codeLong1024/workbuddy-checkin](https://cnb.cool/codeLong1024/workbuddy-checkin) —— 同一份代码，为国内网络访问提供更稳的下载入口；文件路径、安装步骤与 GitHub 版完全相同。
>
> 把仓库链接交给 AI 安装时，任选其一即可。

## 功能模块（按序安装）

| 模块 | 功能 | 安装位置 | 安装手册 |
|------|------|------|------|
| **oracle** 登录态代理 | checkin / travel 的**共同依赖**，不含业务 | `~/.workbuddy/scripts/wb_oracle/` | [oracle/README.md](oracle/README.md) |
| **checkin** 每日签到 | 积分签到（幂等，今日已签跳过） | `~/.workbuddy/scripts/checkin/` | [checkin/README.md](checkin/README.md) |
| **travel** 派猫旅行 | 派出暴富喵旅行 + 到点自动领奖 | `~/.workbuddy/scripts/travel/` | [travel/README.md](travel/README.md) |

**把本仓库链接丢给 AI，说"安装签到"或"安装派猫旅行"，AI 按对应模块 README 自动完成下载 + 创建自动化**（会交互确认触发时间，默认：签到 09:10 / 派猫 08:00）。

> **先装 oracle**：2026-09 起客户端把 `accessToken` 改为 at-rest 信封存储，脚本不再读明文 token，请求统一经 oracle 代发。缺它两个模块都跑不起来。

```
.
├── oracle/    登录态代理（存储格式见 docs/at-rest-format.md）
├── checkin/   每日签到
├── travel/    派猫旅行
├── docs/      登录态存储格式说明（仅维护时读）
└── tests/     离线测试
```

模块设计：**自包含**（独立目录 + 独立 README，AI 只读该模块即可安装）、**零耦合**（脚本落 `~/.workbuddy/scripts/<模块名>/`，卸载 A 不影响 B；oracle 是两者共同依赖，除外）、**统一安装**（自用脚本分发，skill 仅 checkin 保留触发壳）。

> Windows 下 `~` = `C:\Users\<你的用户名>`。

## 测试

```bash
python -m unittest discover -s tests -v
```

## 安全

- 脚本不存储任何凭证，不存在配置文件；token 只在 oracle 进程内存里流转，不落盘、不打印、不进 argv
- 登录态文件 `%LOCALAPPDATA%\CodeBuddyExtension\Data\Public\auth\workbuddy-desktop.info` 请勿分享

## 免责声明（Disclaimer）

1. **接口归属**：本项目所调用接口均位于 `copilot.tencent.com` 域名下，接口及其返回的数据、权益均归腾讯公司（或其关联公司）所有。本项目与腾讯公司无任何隶属、授权或合作关系，不代表腾讯公司立场或背书。
2. **商标声明**：WorkBuddy、腾讯 copilot 等名称与标识均为腾讯公司（或其关联公司）的商标或服务标识，仅在本项目中用于描述兼容对象；本项目为独立第三方工具，未经腾讯公司审核或认可。
3. **使用边界**：本项目仅供个人自动化学习与技术研究，禁止用于商业用途，禁止用于任何违反腾讯服务条款、法律法规或使用者所在组织合规要求的行为（含公司内部大规模使用）。
4. **接口稳定性**：签到/旅行接口由腾讯公司独立控制，可能随时变更、调整或下线。本项目不保证接口的持续可用性，亦不承诺脚本永续有效；因接口变更导致的失效，作者不承担任何责任。
5. **责任承担**：使用者应自行评估使用风险（包括但不限于账号安全、数据安全与合规风险），因使用本项目产生的任何直接或间接后果，由使用者自行承担，作者不承担任何责任。
6. **无担保**：本项目按「现状」（AS-IS）提供，不提供任何明示或默示的担保。
7. **配合下架**：如腾讯公司或相关权利方认为本项目存在合规问题，作者将积极配合处理（包括但不限于移除相关接口信息或下架项目）。

## 致谢

- [@lzmy1232](https://github.com/lzmy1232)：[PR #1](https://github.com/codeLong1024/workbuddy-checkin/pull/1) 中提出的三块改进已被吸收进本项目 —— 登录态文件读取重试、签到幂等与退出码语义、Windows 控制台编码（见 `df85070`）。其余建议因与「零状态落盘」的设计约束冲突或与既有能力职责重叠未采纳，原因见该 PR 下的讨论。

## License

MIT
