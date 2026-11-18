"""updater.py 测试: 版本比较 / Atom 解析 / 4xx 快速失败 (不触网)."""
from __future__ import annotations

import urllib.error

from app import updater


def test_parse_version_basic():
    assert updater._parse_version("v1.2.3") == (1, 2, 3)
    prerelease = updater._parse_version("v1.2.3-rc1")
    assert prerelease == (1, 2, 3)          # 后缀被剥掉 (不区分预发布)


def test_parse_version_invalid():
    assert updater._parse_version("abc") is None
    assert updater._parse_version("v1.2") is None
    assert updater._parse_version("") is None


def test_strip_html():
    assert updater._strip_html("<p>a &amp; b</p>\n<p>c</p>") == "a & b c"


def test_fetch_latest_atom():
    atom_xml = (
        '<feed xmlns="http://www.w3.org/2005/Atom"><entry>'
        "<id>tag:github.com,2008:release/v9.9.9</id>"
        '<link rel="alternate" href="https://github.com/FuchaZ/CmdGauge/releases/tag/v9.9.9"/>'
        "<content> &lt;p&gt;Notes &lt;/p&gt; </content>"
        "</entry></feed>"
    )
    updater._fetch_text = lambda url: atom_xml
    try:
        out = updater._fetch_latest_atom()
        assert out["tag"] == "v9.9.9"
        assert out["release_url"].endswith("/releases/tag/v9.9.9")
        assert out["notes"] == "Notes"
    finally:
        _restore(updater)


def test_check_update_has_update():
    updater._fetch_json = lambda url: {"tag_name": "v9.9.9", "html_url": "u", "body": "n"}
    try:
        out = updater.check_update()
        assert out["has_update"] is True
        assert out["latest"] == "v9.9.9"
    finally:
        _restore(updater)


def test_check_update_same_version():
    updater._fetch_json = lambda url: {"tag_name": "1.0.5"}   # 与 __version__ 相同
    try:
        out = updater.check_update()
        assert out["has_update"] is False
    finally:
        _restore(updater)


def test_check_update_falls_back_to_atom_on_api_failure():
    def boom(url):
        raise RuntimeError("api down")

    updater._fetch_json = boom
    updater._fetch_text = lambda url: (
        '<feed xmlns="http://www.w3.org/2005/Atom"><entry>'
        "<id>x/</id><content>v0.0.1</content></entry></feed>"
    )
    try:
        out = updater.check_update()
        assert out["has_update"] is False
        assert out["latest"] == ""
    finally:
        _restore(updater)


def test_check_update_raises_friendly_error_when_both_fail():
    def boom(url):
        raise RuntimeError("down")

    updater._fetch_json = boom
    updater._fetch_text = boom
    try:
        try:
            updater.check_update()
            raised = False
        except RuntimeError as exc:
            raised = True
            assert "无法连接 GitHub" in str(exc)
        assert raised
    finally:
        _restore(updater)


def test_no_retry_on_deterministic_4xx():
    """404 属确定性失败: 只请求 1 次, 不烧完 3 轮重试 (429/5xx 仍重试)."""
    calls = {"n": 0}

    def fake_urlopen(req, timeout=None):  # noqa: ARG001
        calls["n"] += 1
        raise urllib.error.HTTPError(req.full_url, 404, "nope", hdrs=None, fp=None)

    real_urlopen = updater.urllib.request.urlopen
    updater.urllib.request.urlopen = fake_urlopen
    try:
        try:
            updater._fetch_text("https://example.com/x")
            raised = False
        except urllib.error.HTTPError:
            raised = True
        assert raised and calls["n"] == 1
    finally:
        updater.urllib.request.urlopen = real_urlopen
        _restore(updater)


def test_retry_on_5xx():
    calls = {"n": 0}

    def fake_urlopen(req, timeout=None):  # noqa: ARG001
        calls["n"] 	= calls["n"] + 1
        if calls["n"] < 3:
            raise urllib.error.HTTPError(req.full_url, 502, "bad gw", hdrs=None, fp=None)
        class _R:
            def __enter__(self):
                return self

            def read(self, n=-1):
                return b"{}"

            def __exit__(self, *a):
                return False
        return _R()

    real_urlopen = updater.urllib.request.urlopen
    updater.urllib.request.urlopen = fake_urlopen
    try:
        out = updater._fetch_json("https://example.com/x")
        assert out == {} and calls["n"] == 3
    finally:
        updater.urllib.request.urlopen = real_urlopen
        _restore(updater)


def _restore(mod) -> None:
    """还原被测试替换的模块级 _fetch_text/_fetch_json (importlib reload 还原最直接)."""
    import importlib

    importlib.reload(mod)
