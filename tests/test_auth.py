"""auth.py 纯逻辑测试: cookie 解析 / 登录 URL / 卡住干预判定 (不创建窗口)."""
from __future__ import annotations

from http.cookies import SimpleCookie
from urllib.parse import quote

from app import auth


def _mk_simple_cookie(pairs):
    sc = SimpleCookie()
    for name, value in pairs:
        sc[name] = value
    return sc


def test_cookie_pairs_simplecookie_form():
    sc = _mk_simple_cookie([
        ("__Secure-commandcode_prod_.session_token", "tok"),
        ("__Secure-commandcode_prod_.session_data", "d"),
        ("dotcom_user", "alice"),
    ])
    pairs = auth._cookie_pairs([sc])
    assert ("dotcom_user", "alice") in pairs


def test_cookie_pairs_dict_form():
    pairs = auth._cookie_pairs([
        {"name": "a", "value": "1"},
        {"name": "", "value": "v"},          # 无名 cookie 被跳过
        {"name": "b", "value": ""},          # 无值被跳过
    ])
    assert pairs == [("a", "1")]


def test_cookie_pairs_mixed_and_none():
    sc = _mk_simple_cookie([("x", "y")])
    assert auth._cookie_pairs([sc, {"name": "z", "value": "w"}, None]) == [
        ("x", "y"), ("z", "w"),
    ]


def test_pick_session_cookies_found():
    pairs = [
        ("__Secure-commandcode_prod_.session_token", "tok"),
        ("__Secure-commandcode_prod_.session_data", "d"),
        ("dotcom_user", "alice"),
    ]
    header, login = auth.pick_session_cookies(pairs)
    assert "session_token=tok" in header
    assert "session_data=d" in header
    assert login == "alice"


def test_pick_session_cookies_by_hint_only():
    # hint 命中前提是名字里带站点前缀 (commandcode)
    header, _login = auth.pick_session_cookies([("commandcode_session_token", "v")])
    assert header == "commandcode_session_token=v"


def test_pick_session_cookies_missing():
    assert auth.pick_session_cookies([("a", "1")]) == ("", "")
    assert auth.pick_session_cookies([]) == ("", "")


def test_host_of():
    assert auth.host_of("https://GitHub.com/x") == "github.com"
    assert auth.host_of("not a url") == ""


def test_needs_nudge_github_stuck_markers():
    assert auth.needs_nudge("github.com", "You have been redirected to the authorized application")
    assert auth.needs_nudge("github.com", "does not redirect you back")
    assert not auth.needs_nudge("github.com", "Sign in to GitHub")   # 普通登录页留给用户


def test_needs_nudge_api_subdomain_always():
    assert auth.needs_nudge("api.commandcode.ai", "")
    assert not auth.needs_nudge("commandcode.ai", "")


def test_build_login_url_quotes_return_to():
    url = auth.build_login_url("/settings/usage")
    assert url.startswith("https://commandcode.ai/signin?returnTo=")
    assert quote("/settings/usage", safe="")[3:] in url


def test_build_login_url_no_return_to():
    assert auth.build_login_url("") == auth.LOGIN_URL
