"""CI-style consistency check: i18n key parity + DOM ids referenced by app.js.

- app.js 的 I18N zh/en 两个语言包键集合必须一致 (漏一个键, 另一语言显示原始 key)
- index.html 的 data-i18n 引用与 app.js 的 t("...") 调用必须都能在 I18N 里找到
- app.js 里 $(\"id\") 引用的元素必须存在于 index.html 或由 JS 动态创建

运行: python scripts/check_i18n_ids.py  (退出码 0 = 全部通过)
"""
from __future__ import annotations

import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
JS = (ROOT / "app" / "web" / "app.js").read_text(encoding="utf-8")
HTML = (ROOT / "app" / "web" / "index.html").read_text(encoding="utf-8")

failures: list[str] = []

# --- i18n key parity -------------------------------------------------------
zh_block = JS.split("  en: {")[0]
en_block = JS.split("  en: {")[1].split("\n};")[0]
pat = re.compile(r'(\w+):\s*"((?:[^"\\]|\\.)*)"')
zh = dict(pat.findall(zh_block))
en = dict(pat.findall(en_block))

zh_only = sorted(set(zh) ^ set(en))
if zh_only:
    failures.append(f"zh/en key mismatch: {zh_only}")

used = set(re.findall(r'data-i18n(?:-title)?="([^"]+)"', HTML))
used |= set(re.findall(r'[^\w.]t\("(\w+)"\)', JS))
missing = sorted(used - set(zh))
if missing:
    failures.append(f"i18n keys used but not defined: {missing}")

# --- DOM ids ---------------------------------------------------------------
used_ids = set(re.findall(r'\$\("([^"]+)"\)', JS))
used_ids |= set(re.findall(r'getElementById\("([^"]+)"\)', JS))
defined_ids = set(re.findall(r'id="([^"]+)"', HTML))
# JS 动态创建: .id = "..." 赋值, 或模板串里的 id="..." (modal 输入框/用户菜单项)
dyn_ids = set(re.findall(r'\.id\s*=\s*"([^"]+)"', JS)) | set(re.findall(r'\bid="([^"]+)"', JS))
missing_ids = sorted(used_ids - defined_ids - dyn_ids)
if missing_ids:
    failures.append(f"DOM ids used in app.js but missing: {missing_ids}")

if failures:
    for f in failures:
        print("FAIL", f)
    sys.exit(1)
print(f"OK: i18n zh/en parity ({len(zh)} keys), "
      f"all {len(used)} used keys defined, "
      f"all {len(used_ids)} DOM ids resolvable")
