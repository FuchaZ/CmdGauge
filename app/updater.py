"""检查 GitHub Releases 是否有新版本 (轻量更新提示, 不自动下载替换).

流程: 优先请求 GitHub API 最新 release -> 解析 tag -> 与本地 __version__ 比较;
API 受未认证限流(403)/502/超时影响时, 自动降级到 Releases Atom 流(不受 API 限流).
发现新版本后由用户点击按钮用系统浏览器打开 Releases 页自行下载.
"""
from __future__ import annotations

import html as _html
import json
import re
import time
import urllib.error
import urllib.request
import xml.etree.ElementTree as ET
from typing import Any, Optional

from . import __version__

REPO = "FuchaZ/CmdGauge"  # 发布仓库 (为空则「检查更新」直接提示未配置)
RELEASES_URL = f"https://api.github.com/repos/{REPO}/releases/latest"
ATOM_URL = f"https://github.com/{REPO}/releases.atom"
RELEASE_PAGE_URL = f"https://github.com/{REPO}/releases/latest"
_ATOM_NS = {"a": "http://www.w3.org/2005/Atom"}
_TIMEOUT = 8  # 秒; GitHub 直连可能超时, 快速失败避免卡住 UI
_MAX_ATTEMPTS = 3  # 境内直连 GitHub 间歇性 502/超时/重置, 自动重试提高成功率
_RETRY_SLEEP = 0.8  # 每次重试间隔(秒)

_TAG_RE = re.compile(r"^v?(\d+)\.(\d+)\.(\d+)(?:[-+].*)?$")
_HTML_TAG_RE = re.compile(r"<[^>]*>")
_WS_RE = re.compile(r"\s+")


def _fetch_text(url: str) -> str:
    """请求指定 URL 并返回文本, 失败自动重试.

    重试耗尽后抛出最后一次底层异常, 由调用方决定降级或转为友好提示.

    Args:
        url: 完整请求地址

    Returns:
        响应文本

    Raises:
        urllib.error.HTTPError / URLError / TimeoutError / OSError: 重试仍失败
    """
    req = urllib.request.Request(
        url,
        headers={"User-Agent": f"CmdGauge/{__version__}", "Accept": "application/vnd.github+json"},
    )
    last: Optional[BaseException] = None
    for attempt in range(1, _MAX_ATTEMPTS + 1):
        try:
            with urllib.request.urlopen(req, timeout=_TIMEOUT) as resp:
                return resp.read().decode("utf-8", "replace")
        except (urllib.error.HTTPError, urllib.error.URLError, TimeoutError, OSError) as exc:
            last = exc
            if attempt < _MAX_ATTEMPTS:
                time.sleep(_RETRY_SLEEP)
                continue
    if last:
        raise last  # type: ignore[misc]
    raise RuntimeError("unknown network error")


def _fetch_json(url: str) -> dict[str, Any]:
    """请求 GitHub API 并解析 JSON 对象.

    Args:
        url: 完整请求地址

    Returns:
        解析后的 JSON 对象

    Raises:
        见 _fetch_text: 重试仍失败时抛出底层异常
    """
    return json.loads(_fetch_text(url))


def _strip_html(text: str) -> str:
    """去除 HTML 标签并压缩空白, 供 Atom content 转纯文本展示."""
    text = _html.unescape(text or "")
    text = _HTML_TAG_RE.sub("", text)
    return _WS_RE.sub(" ", text).strip()


def _fetch_latest_atom() -> dict[str, str]:
    """从 Releases Atom 流解析最新 release (不受 GitHub API 限流).

    Returns:
        {"tag": str, "release_url": str, "notes": str}

    Raises:
        RuntimeError: 流为空或解析失败
    """
    root = ET.fromstring(_fetch_text(ATOM_URL))
    entry = root.find("a:entry", _ATOM_NS)
    if entry is None:
        raise RuntimeError("GitHub Releases 订阅流为空，未获取到版本信息")

    tag = ""
    id_el = entry.find("a:id", _ATOM_NS)
    if id_el is not None and id_el.text:
        tag = id_el.text.rsplit("/", 1)[-1].strip()

    release_url = RELEASE_PAGE_URL
    for link in entry.findall("a:link", _ATOM_NS):
        href = link.get("href") or ""
        if link.get("rel") == "alternate" and "/releases/tag/" in href:
            release_url = href
            break

    notes = ""
    content = entry.find("a:content", _ATOM_NS)
    if content is not None and content.text:
        notes = _strip_html(content.text)

    return {"tag": tag, "release_url": release_url, "notes": notes}


def _parse_version(text: str) -> Optional[tuple[int, int, int]]:
    m = _TAG_RE.match((text or "").strip())
    if not m:
        return None
    return int(m.group(1)), int(m.group(2)), int(m.group(3))


def check_update() -> dict[str, Any]:
    """请求 GitHub 最新 release 并与本地版本比较.

    API 首优(数据齐全); 受未认证限流(403)/502/超时影响时降级 Atom 流(约等于无限额),
    两者均失败才抛错, 并把具体原因带给前端展示.

    Returns:
        {"has_update": bool, "current": str, "latest": str,
         "release_url": str, "notes": str}

    Raises:
        RuntimeError: 两种来源均失败时的可读提示
    """
    errors: list[str] = []
    tag = release_url = notes = ""
    try:
        data = _fetch_json(RELEASES_URL)
        tag = data.get("tag_name") or ""
        release_url = data.get("html_url") or RELEASE_PAGE_URL
        notes = (data.get("body") or "").strip()[:600]
    except Exception as exc:  # noqa: BLE001 首次失败仅记录, 交由 Atom 兜底
        errors.append(str(exc))

    if not tag:
        try:
            atom = _fetch_latest_atom()
            tag = atom["tag"]
            release_url = atom["release_url"]
            notes = atom["notes"][:600]
        except Exception as exc:  # noqa: BLE001 双来源都失败 -> 友好提示
            errors.append(str(exc))
            raise RuntimeError(
                f"无法连接 GitHub，无法检查更新（{'；'.join(errors)}）。\n"
                "通常是境内直连 GitHub 暂时不可用：请稍后重试，"
                "或开启系统代理 / VPN 后再次「检查更新」。"
            )

    latest = _parse_version(tag)
    current = _parse_version(__version__)
    has_update = bool(latest and current and latest > current)
    return {
        "has_update": has_update,
        "current": __version__,
        "latest": tag,
        "release_url": release_url,
        "notes": notes,
    }