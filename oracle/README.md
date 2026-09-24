# oracle 模块：登录态代理

checkin / travel 的**共同依赖**，不含业务逻辑。客户端 2026-09 起把 `accessToken` 改为 at-rest 信封存储，脚本不再读明文 token，请求统一经本模块在**进程内**取出凭证并代发（token 不落盘、不打印、不进 argv）。

**没装它，另外两个模块都跑不起来。**

> 保护钥推导、信封与 AAD 布局等见 [`docs/at-rest-format.md`](../docs/at-rest-format.md)，仅维护时需要读。

## AI 一键安装

**给 LLM 的执行手册**：用户说"安装签到 / 安装派猫旅行"时，**先执行本节**，再执行对应模块 README。

1. **检查**：`ls ~/.workbuddy/scripts/wb_oracle/main.js`
   - 已存在 → 跳过；不存在 → 复制：`mkdir -p ~/.workbuddy/scripts/wb_oracle && cp <仓库路径>/oracle/scripts/wb_oracle/* ~/.workbuddy/scripts/wb_oracle/`
2. **验证**：必须用 WorkBuddy 客户端当解释器跑自检
   ```bash
   "C:/Users/<用户名>/AppData/Local/Programs/WorkBuddy/WorkBuddy.exe" "C:/Users/<用户名>/.workbuddy/scripts/wb_oracle" check
   ```
   - 输出含 `protectorKeyId` 与 `tokenLength` 即成功
   - 退出码 3 → 看 stderr 提示：未登录客户端，或客户端结构已变（按 docs 重校）
3. **不要**把 oracle 复制进 `checkin/` 或 `travel/` 目录——脚本按「`WB_ORACLE_DIR` 环境变量 → 脚本同级 → 上一级」自动定位。装在别处时用 `WB_ORACLE_DIR` 显式指定即可。

> macOS 客户端路径换成 `/Applications/WorkBuddy.app/Contents/MacOS/WorkBuddy`。

## 手动安装

```bash
mkdir -p ~/.workbuddy/scripts/wb_oracle
cp oracle/scripts/wb_oracle/* ~/.workbuddy/scripts/wb_oracle/
```

## 用法

一般由 checkin / travel 脚本内部调用，也可直接命令行排查：

```bash
WB="C:/Users/<用户名>/AppData/Local/Programs/WorkBuddy/WorkBuddy.exe"
O="C:/Users/<用户名>/.workbuddy/scripts/wb_oracle"

"$WB" "$O" check                                          # 诊断：keyId / 长度 / 指纹（不打印凭证）
"$WB" "$O" request GET  /activity/growth/buddy/travel/status
"$WB" "$O" request POST /v2/billing/meter/daily-checkin '{}'
```

| 项 | 约定 |
|---|---|
| stdout | 含一行 `HTTP <status>`，该行之后全部内容为接口原始 body |
| 退出码 0 | 已发出请求（HTTP 非 2xx 也照常打印 body，业务错误看 body 的 `code` / `msg`） |
| 退出码 3 | 取用凭证或环境错误，细节在 stderr → 调用方据此提示重新登录 |
| `WB_API_BASE` | 换基址，默认 `https://copilot.tencent.com` |

调用方解析时按 `^HTTP \d{3}$` 定位，**不要假定首行就是状态**（Electron 偶尔会往 stdout 打噪音）。

## 故障排查

| 现象 | 处理 |
|---|---|
| `原生绑定不可用` | 没用 `WorkBuddy.exe` 当解释器；仍失败说明客户端结构变了，见 docs |
| `accessToken 读取失败` | 保护钥换代。跑 `check` 看 `protectorKeyId` 是否变化，按 docs 重校 |
| `accessToken 不是 $wbEncrypted 信封` | 登录态格式又变了，见 docs「背景」节 |
| `读取登录态文件失败（已重试 4 次）` | 客户端从没登录过，或文件正被重写/占用；稍后重试 |
| 接口 401 | 登录态过期，重新登录客户端 |
| 每次调用慢 1–2 s | 正常——每次都会起一个 Electron 进程，别做高频轮询 |

## 卸载

```bash
rm -rf ~/.workbuddy/scripts/wb_oracle
```

> 免责声明见[仓库根 README](../README.md)。
