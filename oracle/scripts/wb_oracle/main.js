/**
 * wb_oracle —— 借 WorkBuddy 客户端自带的 Electron 运行时，在进程内取出 at-rest
 * 登录态，并代发一次已鉴权请求。token 只在内存里流转：不落盘、不打印、不进 argv。
 *
 * 用法（必须用 WorkBuddy.exe 当解释器）：
 *   WorkBuddy.exe <本目录> check                          诊断：打印 keyId/长度/指纹等非敏感信息
 *   WorkBuddy.exe <本目录> request GET  /path             发 GET
 *   WorkBuddy.exe <本目录> request POST /path '{"a":1}'   发 POST（第 5 个参数为请求体）
 *
 * 环境变量：WB_API_BASE  基址，默认 https://copilot.tencent.com
 *
 * stdout 契约：含一行 `HTTP <status>`，其后为接口原始 body（status 之后全部内容）。
 * 退出码：0 = 已发出请求（HTTP 非 2xx 也照常打印 body，业务错误看 body 的 code/msg）
 *         3 = 取用凭证或环境错误，细节在 stderr（调用方据此提示重新登录）
 *
 * 登录态文件读取失败会重试 4 次 × 0.8 s：客户端刷新 token 时会整体重写该文件，
 * 撞上写入中途会读到半截 JSON。
 *
 * 存储格式说明见 ../../docs/at-rest-format.md
 */
const crypto = require("crypto");
const fs = require("fs");
const os = require("os");
const path = require("path");

const API_BASE = process.env.WB_API_BASE || "https://copilot.tencent.com";
const AUTH_FILE = path.join(
  process.env.LOCALAPPDATA || path.join(os.homedir(), "AppData", "Local"),
  "CodeBuddyExtension", "Data", "Public", "auth", "workbuddy-desktop.info"
);
const READ_TRIES = 4;      // 读登录态文件的重试次数
const READ_RETRY_MS = 800; // 每次间隔（客户端可能正在重写该文件）

function die(msg) {
  process.stderr.write("[wb_oracle] " + msg + "\n");
  process.exit(3);
}

/** 同步 sleep（Node 无 sleepSync，靠 Atomics.wait 阻塞）。 */
function sleepSync(ms) {
  Atomics.wait(new Int32Array(new SharedArrayBuffer(4)), 0, 0, ms);
}

/**
 * 读登录态文件。客户端刷新 token 时会整体重写该文件，
 * 撞上写入中途会读到半截 JSON —— 重试若干次再判失败。
 */
function readAuthJson() {
  let last;
  for (let i = 0; i < READ_TRIES; i++) {
    try {
      return JSON.parse(fs.readFileSync(AUTH_FILE, "utf8"));
    } catch (e) {
      last = e;
      if (i < READ_TRIES - 1) sleepSync(READ_RETRY_MS);
    }
  }
  die("读取登录态文件失败（已重试 " + READ_TRIES + " 次）: " + last.message +
      " —— 若从未登录过，请先打开客户端登录一次");
}

/** 长度前缀字符串：uint32BE(len) + utf8 */
function lp(s) {
  const b = Buffer.from(s, "utf8");
  const l = Buffer.alloc(4);
  l.writeUInt32BE(b.length);
  return Buffer.concat([l, b]);
}

/** sym-v1 AAD = "WB-AAD\0" | 0x01 | LP(magic) | LP("sym-v1") | u32(suite) | LP(keyId) | [code] | 0x00 | 0x00 */
function buildAadSymV1(keyId, framing) {
  const file = framing === "file";
  const suite = Buffer.alloc(4);
  suite.writeUInt32BE(1); // SUITE_AES_256_GCM_V1
  return Buffer.concat([
    Buffer.from("WB-AAD\0", "latin1"),
    Buffer.from([1]),
    lp(file ? "WBEF1" : "WBEV1"),
    lp("sym-v1"),
    suite,
    lp(keyId),
    Buffer.from([file ? 1 : 2]),
    Buffer.from([0]), // encodeOptionalUint64(undefined)
    Buffer.from([0]), // final: undefined -> 0
  ]);
}

function keyIdOf(key) {
  return crypto.createHash("sha256").update(key).digest("hex").slice(0, 16);
}

/** 还原 AES-256-GCM 信封：env = {keyId, nonce, authTag, ciphertext}（base64） */
function openEnvelope(env, key, framing) {
  const d = crypto.createDecipheriv("aes-256-gcm", key, Buffer.from(env.nonce, "base64"), { authTagLength: 16 });
  d.setAAD(buildAadSymV1(env.keyId, framing));
  d.setAuthTag(Buffer.from(env.authTag, "base64"));
  return Buffer.concat([d.update(Buffer.from(env.ciphertext, "base64")), d.final()]);
}

function loadCredential() {
  let payload;
  try {
    payload = JSON.parse(process._linkedBinding("electron_browser_workbuddy_storage").loggerGet());
  } catch (e) {
    die("原生绑定不可用（需用 WorkBuddy.exe 运行）: " + e.message);
  }
  const protectorKey = crypto.createHash("sha256").update(payload.atRestSecretKey, "utf8").digest();

  const auth = readAuthJson();
  const wrapper = (auth.auth || {}).accessToken;
  if (!wrapper || wrapper.$wbEncrypted !== 1 || typeof wrapper.envelope !== "string") {
    die("accessToken 不是 $wbEncrypted 信封（登录态格式可能已变）");
  }
  let token;
  try {
    token = openEnvelope(
      JSON.parse(Buffer.from(wrapper.envelope, "base64").toString("utf8")),
      protectorKey, "field"
    ).toString("utf8");
  } catch {
    die("accessToken 读取失败（保护钥不匹配，可能客户端已升级）");
  }
  if (!token) die("accessToken 为空，请重新登录 WorkBuddy 客户端");
  return { token, uid: (auth.account || {}).uid || "", protectorKeyId: keyIdOf(protectorKey) };
}

async function main() {
  const mode = process.argv[2] || "check";
  const cred = loadCredential();

  if (mode === "check") {
    process.stdout.write(JSON.stringify({
      ok: true,
      protectorKeyId: cred.protectorKeyId,
      tokenLength: cred.token.length,
      tokenFingerprint: crypto.createHash("sha256").update(cred.token).digest("hex").slice(0, 8),
      uidTail: cred.uid.slice(-6)
    }) + "\n");
    return;
  }

  if (mode === "request") {
    const method = (process.argv[3] || "GET").toUpperCase();
    const apiPath = process.argv[4] || "";
    if (!apiPath.startsWith("/")) die("path 必须以 / 开头");
    const headers = { Accept: "application/json", Authorization: "Bearer " + cred.token };
    if (cred.uid) headers["X-User-Id"] = cred.uid;
    const bodyArg = process.argv[5];
    if (bodyArg) headers["Content-Type"] = "application/json";
    // fetch 规范禁止 GET/HEAD 带 body，这里静默丢弃，保持旧 urllib 行为不报错
    const sendBody = method === "GET" || method === "HEAD" ? undefined : bodyArg;
    let resp;
    try {
      resp = await fetch(API_BASE + apiPath, { method, headers, body: sendBody });
    } catch (e) {
      die("请求失败: " + e.message);
    }
    const text = await resp.text();
    process.stdout.write("HTTP " + resp.status + "\n" + text + "\n");
    return;
  }

  die("未知模式: " + mode);
}

main().catch((e) => die(e && e.stack ? e.stack : String(e)));
