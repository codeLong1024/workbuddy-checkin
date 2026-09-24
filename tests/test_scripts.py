#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""离线测试：oracle 输出解析契约 + 退出码语义 + 幂等判定 + 控制台编码。

    python -m unittest discover -s tests -v

不访问网络、不需要登录态。需要真实 WorkBuddy 客户端的端到端用例会自动跳过。
"""

import importlib.util
import json
import os
import shutil
import subprocess
import sys
import tempfile
import unittest

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))


def _load(rel):
    """按路径加载脚本（两个模块都不在包内）。"""
    name = rel.replace("/", "_")[:-3]
    spec = importlib.util.spec_from_file_location(name, os.path.join(ROOT, rel))
    mod = importlib.util.module_from_spec(spec)
    sys.modules[name] = mod
    spec.loader.exec_module(mod)
    return mod


TRAVEL = _load("travel/scripts/travel.py")
CHECKIN = _load("checkin/scripts/checkin.py")
MODS = (("travel", TRAVEL), ("checkin", CHECKIN))


def _client_exe():
    cands = (
        os.path.join(os.environ.get("LOCALAPPDATA", ""), "Programs", "WorkBuddy", "WorkBuddy.exe"),
        "/Applications/WorkBuddy.app/Contents/MacOS/WorkBuddy",
    )
    for c in cands:
        if c and os.path.isfile(c):
            return c
    return None


class TestParseOracleOutput(unittest.TestCase):
    """stdout 契约：按 `HTTP <3位数字>` 定位，该行之后全部内容为 body。"""

    def test_clean(self):
        for name, mod in MODS:
            with self.subTest(mod=name):
                self.assertEqual(mod.parse_oracle_output('HTTP 200\n{"code":0}'),
                                 (200, {"code": 0}))

    def test_leading_noise(self):
        """Electron 可能往 stdout 打噪音，首行不一定是状态。"""
        text = 'electron noise\nHTTP 200\n{"code":0,"msg":"OK"}\n'
        for name, mod in MODS:
            with self.subTest(mod=name):
                self.assertEqual(mod.parse_oracle_output(text),
                                 (200, {"code": 0, "msg": "OK"}))

    def test_multiline_body(self):
        text = 'HTTP 200\n{\n "a": 1,\n "b": [1, 2]\n}\n'
        for name, mod in MODS:
            with self.subTest(mod=name):
                self.assertEqual(mod.parse_oracle_output(text), (200, {"a": 1, "b": [1, 2]}))

    def test_error_status_html_body(self):
        """401 时网关回 HTML：状态码必须保留，原文收进 msg。"""
        text = "HTTP 401\n<html><title>401 Authorization Required</title></html>\n"
        for name, mod in MODS:
            with self.subTest(mod=name):
                code, body = mod.parse_oracle_output(text)
                self.assertEqual(code, 401)
                self.assertIn("401", body["msg"])

    def test_empty_body(self):
        for name, mod in MODS:
            with self.subTest(mod=name):
                self.assertEqual(mod.parse_oracle_output("HTTP 204\n"), (204, {}))

    def test_status_line_without_body(self):
        for name, mod in MODS:
            with self.subTest(mod=name):
                self.assertEqual(mod.parse_oracle_output("HTTP 500"), (500, {}))

    def test_no_status_line(self):
        for name, mod in MODS:
            with self.subTest(mod=name):
                self.assertIsNone(mod.parse_oracle_output("boom\nnothing here"))

    def test_status_word_inside_body_not_confused(self):
        """body 里出现 "HTTP 200" 字样时，应以第一处可解析行为准。"""
        text = 'HTTP 200\n{"msg":"upstream said HTTP 500"}\n'
        for name, mod in MODS:
            with self.subTest(mod=name):
                self.assertEqual(mod.parse_oracle_output(text),
                                 (200, {"msg": "upstream said HTTP 500"}))


class TestFindOracleDir(unittest.TestCase):
    """定位规则：WB_ORACLE_DIR > 脚本同级（单模块安装）> 上一级（共享安装）。"""

    def setUp(self):
        self._saved = os.environ.pop("WB_ORACLE_DIR", None)

    def tearDown(self):
        if self._saved is not None:
            os.environ["WB_ORACLE_DIR"] = self._saved

    @staticmethod
    def _mk(root, rel):
        d = os.path.join(root, rel)
        os.makedirs(d, exist_ok=True)
        open(os.path.join(d, "main.js"), "w").close()
        return d

    def test_env_override_wins(self):
        with tempfile.TemporaryDirectory() as tmp:
            exp = self._mk(tmp, "wb_oracle")
            os.environ["WB_ORACLE_DIR"] = exp
            for name, mod in MODS:
                with self.subTest(mod=name):
                    self.assertEqual(mod.find_oracle_dir(os.path.join(tmp, "elsewhere")),
                                     os.path.abspath(exp))

    def test_env_override_invalid_returns_none(self):
        """指定了但目录里没有 main.js —— 明确失败，不静默回退到其它位置。"""
        with tempfile.TemporaryDirectory() as tmp:
            self._mk(tmp, "wb_oracle")
            os.environ["WB_ORACLE_DIR"] = os.path.join(tmp, "nope")
            for name, mod in MODS:
                with self.subTest(mod=name):
                    self.assertIsNone(mod.find_oracle_dir(tmp))

    def test_same_level(self):
        with tempfile.TemporaryDirectory() as tmp:
            exp = self._mk(tmp, "wb_oracle")
            for name, mod in MODS:
                with self.subTest(mod=name):
                    self.assertEqual(mod.find_oracle_dir(tmp), os.path.abspath(exp))

    def test_parent_level(self):
        with tempfile.TemporaryDirectory() as tmp:
            exp = self._mk(tmp, "wb_oracle")
            scripts = os.path.join(tmp, "checkin")
            os.makedirs(scripts, exist_ok=True)
            for name, mod in MODS:
                with self.subTest(mod=name):
                    self.assertEqual(mod.find_oracle_dir(scripts), os.path.abspath(exp))

    def test_missing(self):
        with tempfile.TemporaryDirectory() as tmp:
            for name, mod in MODS:
                with self.subTest(mod=name):
                    self.assertIsNone(mod.find_oracle_dir(tmp))

    def test_dir_without_main_js_ignored(self):
        with tempfile.TemporaryDirectory() as tmp:
            os.makedirs(os.path.join(tmp, "wb_oracle"), exist_ok=True)
            for name, mod in MODS:
                with self.subTest(mod=name):
                    self.assertIsNone(mod.find_oracle_dir(tmp))


class TestCliGuards(unittest.TestCase):
    """缺客户端时必须给明确退出码 2，而不是抛 traceback（那会变成退出码 1）。"""

    def setUp(self):
        self._td = tempfile.TemporaryDirectory()
        self.empty_localappdata = os.path.join(self._td.name, "no-client")

    def tearDown(self):
        self._td.cleanup()

    def _run(self, script, *args):
        env = dict(os.environ, LOCALAPPDATA=self.empty_localappdata)
        env.pop("WB_ORACLE_DIR", None)          # 用例只验证「缺客户端」路径
        return subprocess.run([sys.executable, os.path.join(ROOT, script), *args],
                              capture_output=True, text=True, env=env, timeout=60)

    def test_travel_no_client(self):
        p = self._run("travel/scripts/travel.py", "status")
        self.assertEqual(p.returncode, 2, p.stdout + p.stderr)
        self.assertIn("未找到 WorkBuddy 客户端", p.stdout)
        self.assertNotIn("Traceback", p.stderr)

    def test_checkin_no_client(self):
        p = self._run("checkin/scripts/checkin.py", "--dry-run")
        self.assertEqual(p.returncode, 2, p.stdout + p.stderr)
        self.assertIn("未找到 WorkBuddy 客户端", p.stdout)
        self.assertNotIn("Traceback", p.stderr)

    def test_travel_unknown_command(self):
        p = self._run("travel/scripts/travel.py", "bogus")
        self.assertEqual(p.returncode, 1)
        self.assertIn("未知命令", p.stdout)

    def test_travel_no_args_prints_usage(self):
        p = self._run("travel/scripts/travel.py")
        self.assertEqual(p.returncode, 1)
        self.assertIn("用法", p.stdout)

    def test_checkin_bad_flag(self):
        p = self._run("checkin/scripts/checkin.py", "--nope")
        self.assertEqual(p.returncode, 2)          # argparse 用法错误
        self.assertIn("usage", p.stderr.lower())


class TestAlreadyChecked(unittest.TestCase):
    """幂等判定表：只有明确属于「今日已签」的响应才算成功，真失败不得被吞成 exit 0。

    只测 checkin —— travel 没有这层语义。
    实测来源：重复签到时服务端可能回业务码 10001，也可能直接回 HTTP 400（无业务码）。
    """

    CASES = (
        (200, {"code": 10001}, True),                      # 标准重复签到码
        (200, {"code": 0, "data": {"credit": 100}}, False),  # 正常签到成功
        (400, {}, True),                                   # 400 无业务码
        (400, {"msg": "already checked in"}, True),
        (400, {"code": 40001, "msg": "参数错误"}, False),   # 400 但带业务码 = 真失败
        (200, {"msg": "已签到"}, False),                    # 2xx 不参与 msg 兜底
        (500, {"msg": "当日已签，请勿重复"}, True),
        (500, {"msg": "internal error"}, False),
    )

    def test_cases(self):
        for code, body, expected in self.CASES:
            with self.subTest(code=code, body=body):
                self.assertEqual(CHECKIN.already_checked(code, body), expected)

    def test_returns_bool(self):
        for code, body, _ in self.CASES:
            with self.subTest(code=code, body=body):
                self.assertIsInstance(CHECKIN.already_checked(code, body), bool)


class TestConsoleEncoding(unittest.TestCase):
    """Windows 窄编码控制台（GBK/ascii）下中文输出不得抛 UnicodeEncodeError。"""

    def setUp(self):
        self._td = tempfile.TemporaryDirectory()
        self.no_client = os.path.join(self._td.name, "no-client")

    def tearDown(self):
        self._td.cleanup()

    def test_callable_and_idempotent(self):
        for name, mod in MODS:
            with self.subTest(mod=name):
                mod.ensure_utf8_console()
                mod.ensure_utf8_console()               # 重复调用不应抛
                self.assertEqual(sys.stdout.encoding, "utf-8")

    def test_ascii_console_no_crash(self):
        """PYTHONIOENCODING=ascii 模拟窄编码：应正常落到退出码 2，而不是编码异常。"""
        for script, args in (("checkin/scripts/checkin.py", ["--dry-run"]),
                             ("travel/scripts/travel.py", ["status"])):
            with self.subTest(script=script):
                env = dict(os.environ, LOCALAPPDATA=self.no_client,
                           PYTHONIOENCODING="ascii")
                env.pop("WB_ORACLE_DIR", None)
                p = subprocess.run([sys.executable, os.path.join(ROOT, script), *args],
                                   capture_output=True, env=env, timeout=60)
                self.assertEqual(p.returncode, 2, p.stdout + p.stderr)
                self.assertNotIn(b"UnicodeEncodeError", p.stderr)
                self.assertNotIn(b"Traceback", p.stderr)


class TestOracleAssets(unittest.TestCase):
    def test_package_json_entry(self):
        path = os.path.join(ROOT, "oracle", "scripts", "wb_oracle", "package.json")
        with open(path, encoding="utf-8") as f:
            self.assertEqual(json.load(f)["main"], "main.js")

    @unittest.skipUnless(shutil.which("node"), "未安装 node，跳过 JS 语法检查")
    def test_main_js_syntax(self):
        path = os.path.join(ROOT, "oracle", "scripts", "wb_oracle", "main.js")
        p = subprocess.run([shutil.which("node"), "--check", path],
                           capture_output=True, text=True)
        self.assertEqual(p.returncode, 0, p.stderr)


class TestOracleIntegration(unittest.TestCase):
    """端到端：用真实客户端跑 oracle。只读（check / status），不签到、不派出。"""

    ORACLE = os.path.join(ROOT, "oracle", "scripts", "wb_oracle")

    def setUp(self):
        exe = _client_exe()
        if not exe:
            self.skipTest("未安装 WorkBuddy 客户端")
        self.exe = exe

    def _oracle(self, *args):
        return subprocess.run([self.exe, self.ORACLE, *args],
                              capture_output=True, text=True, timeout=180)

    def test_check(self):
        p = self._oracle("check")
        if p.returncode != 0:
            self.skipTest("登录态不可用（未登录客户端？）: {}".format(p.stderr.strip()[:200]))
        d = json.loads(p.stdout.strip().splitlines()[-1])
        self.assertTrue(d["ok"])
        for k in ("protectorKeyId", "tokenLength", "tokenFingerprint", "uidTail"):
            self.assertIn(k, d)
        self.assertNotIn("atRestSecretKey", p.stdout)          # 不得泄漏保护钥
        self.assertGreater(d["tokenLength"], 100)

    def test_travel_status_end_to_end(self):
        """travel.py 走 oracle 拿 status，必须是退出码 0 + 可读输出。

        从仓库目录直接跑（未安装到 ~/.workbuddy）时用 WB_ORACLE_DIR 指向仓库内的 oracle。
        """
        env = dict(os.environ, WB_ORACLE_DIR=self.ORACLE)
        p = subprocess.run([sys.executable, os.path.join(ROOT, "travel/scripts/travel.py"), "status"],
                           capture_output=True, text=True, env=env, timeout=180)
        if p.returncode == 2:
            self.skipTest("登录态不可用（未登录客户端？）: {}".format((p.stdout + p.stderr).strip()[:200]))
        self.assertEqual(p.returncode, 0, p.stdout + p.stderr)
        self.assertIn("状态:", p.stdout)
        self.assertNotIn("Traceback", p.stderr)


if __name__ == "__main__":
    unittest.main(verbosity=2)
