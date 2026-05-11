#!/usr/bin/env python3
# src/build_site.py
# ─────────────────────────────────────────────────────────────────────────────
# 把 output/summary.json 複製為 site/data.json
# 把 web/ 底下的靜態資源複製到 site/
# 產生 site/404.html（redirect 回首頁）
# 後續由 actions/upload-pages-artifact 上傳整個 site/ 部署到 GitHub Pages
# ─────────────────────────────────────────────────────────────────────────────

import json
import os
import shutil
import sys
from datetime import datetime
from zoneinfo import ZoneInfo

TZ = ZoneInfo("Asia/Taipei")

SITE_DIR    = "site"
WEB_DIR     = "web"
SUMMARY_SRC = os.path.join("output", "summary.json")
DATA_DST    = os.path.join(SITE_DIR, "data.json")


def ensure_clean_site_dir():
    """清空 site/ 目錄"""
    if os.path.exists(SITE_DIR):
        shutil.rmtree(SITE_DIR)
    os.makedirs(SITE_DIR, exist_ok=True)


def copy_web_assets():
    """把 web/ 全部複製到 site/"""
    if not os.path.isdir(WEB_DIR):
        print(f"[build_site] ⚠ {WEB_DIR}/ 不存在，跳過靜態資源複製")
        return
    for name in os.listdir(WEB_DIR):
        src = os.path.join(WEB_DIR, name)
        dst = os.path.join(SITE_DIR, name)
        if os.path.isfile(src):
            shutil.copy2(src, dst)
            print(f"[build_site] copy {src} → {dst}")
        elif os.path.isdir(src):
            shutil.copytree(src, dst)
            print(f"[build_site] copytree {src} → {dst}")


def copy_summary_to_data():
    """把 output/summary.json → site/data.json"""
    if not os.path.exists(SUMMARY_SRC):
        print(f"[build_site] ✗ {SUMMARY_SRC} 不存在")
        # 寫一個最小 data.json 避免前端 fetch 失敗
        minimal = {
            "generated_at": datetime.now(TZ).isoformat(),
            "success": False,
            "errors": ["summary.json 不存在"],
            "total_rows": 0,
            "top_preview": [],
            "ai_analysis": "",
        }
        with open(DATA_DST, "w", encoding="utf-8") as f:
            json.dump(minimal, f, ensure_ascii=False, indent=2)
        return False

    with open(SUMMARY_SRC, "r", encoding="utf-8") as f:
        summary = json.load(f)

    # 加上 build 時間戳
    summary["site_built_at"] = datetime.now(TZ).isoformat()

    with open(DATA_DST, "w", encoding="utf-8") as f:
        json.dump(summary, f, ensure_ascii=False, indent=2)

    size_kb = os.path.getsize(DATA_DST) / 1024
    print(f"[build_site] ✓ {SUMMARY_SRC} → {DATA_DST} ({size_kb:.1f} KB)")
    return True


def write_404():
    """寫一個 404.html 自動 redirect 回首頁"""
    html = """<!DOCTYPE html>
<html><head><meta charset="utf-8">
<title>404 - 券商分點狙擊分析</title>
<meta http-equiv="refresh" content="0; url=./index.html">
</head><body>
<p>頁面不存在，<a href="./index.html">返回首頁</a>...</p>
</body></html>"""
    with open(os.path.join(SITE_DIR, "404.html"), "w", encoding="utf-8") as f:
        f.write(html)
    print("[build_site] ✓ 寫入 404.html")


def main():
    print("[build_site] === 開始建構網頁版 ===")
    ensure_clean_site_dir()
    copy_web_assets()
    ok = copy_summary_to_data()
    write_404()

    # 確認 index.html 存在
    idx = os.path.join(SITE_DIR, "index.html")
    if not os.path.exists(idx):
        print(f"[build_site] ✗ 缺少 {idx}（請確認 web/index.html 存在）")
        sys.exit(1)

    print(f"[build_site] === 完成，site/ 內容如下 ===")
    for name in sorted(os.listdir(SITE_DIR)):
        path = os.path.join(SITE_DIR, name)
        size = os.path.getsize(path) / 1024 if os.path.isfile(path) else 0
        print(f"  {name}  ({size:.1f} KB)")


if __name__ == "__main__":
    main()
