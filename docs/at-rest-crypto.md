# WorkBuddy 登录态 at-rest 加密与解密原理

> 供维护 `oracle/` 模块时参考。日常安装/使用不需要读本文。

## 背景

2026-09 起 WorkBuddy 客户端把登录态文件里的敏感字段改成静态加密：

```
%LOCALAPPDATA%\CodeBuddyExtension\Data\Public\auth\workbuddy-desktop.info
  auth.accessToken   = {"$wbEncrypted": 1, "envelope": "<base64(JSON 信封)>"}
  auth.refreshToken  = 同上
  account.nickname / account.phoneNumber 同样是信封
  auth.domain / account.uid / auth.expiresIn 等非敏感字段仍是明文
```

按明文字符串读会挂在拼接上：`TypeError: can only concatenate str (not "dict") to str`。
**重新登录不解决问题**——客户端落地时就写加密格式。

## 为什么必须借客户端的进程

- 信封密钥来自「**编译期保护钥**」，由**定制版 Electron 的原生绑定**运行时产出：

  ```js
  process._linkedBinding("electron_browser_workbuddy_storage").loggerGet()
  // -> {version, atRestSecretKey(44 字符 base64), atRestDeveloperPublicKey}
  ```

- 编译期密钥**在 200 MB 的 WorkBuddy.exe 里没有明文常量**——对全部 44 字符 base64 常量做
  `keyId` 暴力比对，0 命中。只能进程内问。
- 定制版 Electron 能跑任意 app 目录（含 `package.json` + `main.js`）：
  `WorkBuddy.exe <你的 app 目录>`。于是把客户端当「解密预言机」——
  **进程内解密 → 立刻用 token 发 HTTP**，token 永不落盘。

相关代码位置（`app.asar` 里的主进程代码**未压缩**，带 `//#region src/main/...` 与注释，直接读即可）：

```
src/main/credential-protection/main-bootstrap.ts
  this.credentialProtectionBootstrap = loadMainCredentialProtectionBootstrap(
    getAtRestEncryptionPolicy(),
    () => electron.workbuddyStorage.loggerGet(),   // ← 编译期保护钥
    { configDir: getWorkbuddyConfigDir() });
```

## 密钥链

```
loggerGet().atRestSecretKey
  → protectorKey   = sha256(atRestSecretKey, utf8)       # 32B
  → protectorKeyId = sha256(protectorKey).hex[:16]      # 实测 9127dea1b44020a7
  → auth 文件的 $wbEncrypted 字段用它直接解出 accessToken   # framing=field
```

`~/.workbuddy/keyblob`（keyId 实测 `e88b751c3c1bdc47`，static-v1 slot）解出的主密钥用于
settings 等资源；**登录态字段用的是保护钥，不是主密钥**，keyblob 这一步本模块不需要。

## 信封与 AAD

信封（base64 解出后是 JSON）：`{suite:1, keyId, nonce(12B), authTag(16B), ciphertext}`，
算法 AES-256-GCM，`keyId = sha256(key).hex[:16]`。

AAD（`buildAuthenticatedContextAad`，scheme=sym-v1）：

```
"WB-AAD\0" | 0x01 | LP(magic) | LP("sym-v1") | uint32BE(1) | LP(keyId) | [framingCode] | 0x00 | 0x00
LP(s) = uint32BE(len(s)) + utf8(s)

framing: file  → magic "WBEF1", code 1     # keyblob 槽位
         field → magic "WBEV1", code 2    # 单个字段（accessToken / refreshToken / nickname …）
```

## 排错顺序

1. 跑 `check` 出 `protectorKeyId` / `tokenLength` —— 有数字说明原生绑定与解密链都通。
2. `accessToken 解密失败` → 保护钥换代或 AAD 变了，回本文重校（先确认 framing 与 magic 表）。
3. `原生绑定不可用` → 没用 `WorkBuddy.exe` 跑，或客户端结构变了（改查 `app.asar` 主进程代码）。
4. API 401 → 登录态真过期，重新登录客户端；403 / 业务码 → 看 body 的 `code` / `msg`。

## 已知边界

- 借壳进程用 `package.json` 的 `name` 建 `%APPDATA%\wb-oracle` 作为 userData，**不碰**用户真实 profile。
- 每次调用起一个 Electron 进程（约 1–2 s），别做高频轮询。
- 依赖客户端内部实现，**大版本升级后可能失效**；`check` 是第一道哨兵，`protectorKeyId` 变化即换代信号。
- `check` 只输出 `protectorKeyId` / 长度 / `sha256` 指纹前 8 位，不含任何密钥或 token 片段。
