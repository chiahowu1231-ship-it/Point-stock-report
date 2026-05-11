#!/usr/bin/env python3
# src/telegram_sender.py
# ─────────────────────────────────────────────────────────────────────────────
# 把 output/summary.json 內容組合成 Telegram HTML 訊息推送，
# 並將 IKE_Report_*.pdf 當作附件送出。
#
# 支援多 chat_id：TELEGRAM_CHAT_ID 用逗號/分號/空白/換行分隔
# 例：TELEGRAM_CHAT_ID = 987654321,-1001234567890
# ─────────────────────────────────────────────────────────────────────────────

import glob
import json
import os
import re
import sys
from datetime import datetime
from zoneinfo import ZoneInfo

import requests

TZ = ZoneInfo("Asia/Taipei")

TG_API       = "https://api.telegram.org"
SUMMARY_PATH = os.path.join("output", "summary.json")
PDF_PATTERN  = os.path.join("output", "IKE_Report_*.pdf")

# Telegram sendMessage 上限為 4096 字元，留一些緩衝
MAX_MSG_LEN = 3900


# ─────────────────────────────────────────────────────────
#  工具
# ─────────────────────────────────────────────────────────
def _esc(s) -> str:
    """Telegram HTML escape"""
    return (str(s)
            .replace("&", "&amp;")
            .replace("<", "&lt;")
            .replace(">", "&gt;"))


def _fb(n) -> str:
    """格式化買賣超數字（億/萬）"""
    try:
        v = int(n)
    except Exception:
        return str(n)
    if abs(v) >= 1_000_000_000:
        return f"{v / 1e9:+.2f}B"
    if abs(v) >= 1_0000_0000:
        return f"{v / 1e8:+.1f}億"
    if abs(v) >= 1_0000:
        return f"{v / 1e4:+.0f}萬"
    return f"{v:+,}"


def _fi(n) -> str:
    try:
        v = int(n)
        return f"{v:+,}" if v > 0 else f"{v:,}"
    except Exception:
        return str(n)


def _emoji_pn(v) -> str:
    """根據正負回傳台股慣例 emoji（正=🔴漲, 負=🟢跌）"""
    try:
        n = float(str(v).replace(",", "").replace("+", "").replace("%", ""))
        if n > 0:
            return "🔴"
        if n < 0:
            return "🟢"
    except Exception:
        pass
    return "⚪"


def _trim_to_limit(text: str, limit: int = MAX_MSG_LEN) -> str:
    """超過長度則截斷並補省略訊息"""
    if len(text) <= limit:
        return text
    return text[:limit - 60] + "\n\n… (訊息過長，已截斷，請見 PDF 附件)"


def _parse_chat_ids(raw: str) -> list:
    """解析逗號/分號/空白/換行分隔的 chat_id 字串"""
    if not raw:
        return []
    parts = re.split(r"[,;\s\n]+", raw.strip())
    return [p.strip() for p in parts if p.strip()]


# ─────────────────────────────────────────────────────────
#  訊息組合
# ─────────────────────────────────────────────────────────
def build_telegram_message(summary: dict) -> str:
    ok = summary.get("success", False)
    status_emoji = "✅" if ok else "⚠️"
    status_text = "正常" if ok else "部分失敗"

    gen_at = summary.get("generated_at", "")
    date_str = gen_at[:10] if gen_at else datetime.now(TZ).strftime("%Y-%m-%d")
    time_str = gen_at[11:19] if len(gen_at) > 11 else ""

    market = summary.get("market_data") or {}
    inst   = market.get("institutional") or []
    taiex  = market.get("taiex") or []
    futures = market.get("futures") or []

    L = []  # lines

    # ── Header ────────────────────────────────────────
    L.append(f"🎯 <b>券商分點狙擊分析</b>")
    L.append(f"📅 {date_str}  {status_emoji} {status_text}")
    if time_str:
        L.append(f"⏰ {date_str} {time_str}")
    L.append("")

    # ── 大盤指數 ──────────────────────────────────────
    if taiex:
        t0 = taiex[0]
        close = t0.get("close", 0)
        chg = float(t0.get("change", 0) or 0)
        chg_pct = float(t0.get("change_pct", 0) or 0)
        amt = float(t0.get("amount_billion", 0) or 0)
        sign = "+" if chg > 0 else ""
        L.append("📊 <b>大盤</b>")
        L.append(f"  指數 <code>{close:,}</code> {_emoji_pn(chg)}{sign}{chg:.2f} ({sign}{chg_pct:.2f}%)")
        L.append(f"  量能 {amt:.0f} 億")
        L.append("")

    # ── 三大法人（今日） ──────────────────────────────
    if inst:
        today = inst[0]
        f_net = today.get("foreign", {}).get("net", 0)
        t_net = today.get("trust",   {}).get("net", 0)
        d_net = today.get("dealer",  {}).get("net", 0)
        L.append("🏦 <b>三大法人（今日）</b>")
        L.append(f"  外資 {_emoji_pn(f_net)} <code>{_fb(f_net)}</code>")
        L.append(f"  投信 {_emoji_pn(t_net)} <code>{_fb(t_net)}</code>")
        L.append(f"  自營 {_emoji_pn(d_net)} <code>{_fb(d_net)}</code>")

        # 6 日累計
        if len(inst) > 1:
            cum_f = sum(int(d.get("foreign", {}).get("net", 0) or 0) for d in inst[:6])
            cum_t = sum(int(d.get("trust",   {}).get("net", 0) or 0) for d in inst[:6])
            cum_d = sum(int(d.get("dealer",  {}).get("net", 0) or 0) for d in inst[:6])
            L.append(f"📊 <b>{min(len(inst), 6)} 日累計</b>")
            L.append(f"  外資 <code>{_fb(cum_f)}</code>  投信 <code>{_fb(cum_t)}</code>  自營 <code>{_fb(cum_d)}</code>")
        L.append("")

    # ── 期貨淨部位 ────────────────────────────────────
    if futures:
        f0 = futures[0]
        prev = futures[1] if len(futures) > 1 else {}

        def _oi_pair(key):
            cur = int(f0.get(key, {}).get("net_oi", 0) or 0)
            prv = int(prev.get(key, {}).get("net_oi", 0) or 0)
            diff = cur - prv
            return cur, diff

        f_oi, f_diff = _oi_pair("foreign")
        t_oi, t_diff = _oi_pair("trust")
        d_oi, d_diff = _oi_pair("dealer")

        L.append("📉 <b>期貨淨部位（口）</b>")
        L.append(f"  外資 <code>{f_oi:+,}</code> ({f_diff:+,})")
        L.append(f"  投信 <code>{t_oi:+,}</code> ({t_diff:+,})")
        L.append(f"  自營 <code>{d_oi:+,}</code> ({d_diff:+,})")
        L.append("")

    # ── 券商分點 Top 3（券商分點重點） ────────────────
    top_preview = summary.get("top_preview") or []
    if top_preview:
        L.append(f"🏛 <b>券商分點 Top {min(len(top_preview), 3)}</b>")
        medals = ["🥇", "🥈", "🥉"]
        for i, block in enumerate(top_preview[:3]):
            medal = medals[i] if i < 3 else f"#{i+1}"
            broker_name = block.get("broker", "")
            total_net = int(block.get("total_net", 0))
            L.append(f"  {medal} <b>{_esc(broker_name)}</b>  <code>{_fi(total_net)}</code> 張")
            rows = block.get("rows") or []
            for r in rows[:2]:  # 每家只列前 2 檔
                sid = r.get("sid", "")
                name = r.get("name", "")
                net = int(r.get("net", 0))
                price = r.get("price", 0)
                bias = r.get("bias", "0%")
                L.append(
                    f"     · {sid} {_esc(name)} <code>{_fi(net)}</code>張  "
                    f"{price} ({bias})"
                )
        L.append("")

    # ── AI 分析（取 A 段 + C 段，截斷至各 600 字） ─────
    ai_text = summary.get("ai_analysis", "")
    if ai_text:
        sec_a = _extract_section(ai_text, "A")
        sec_c = _extract_section(ai_text, "C")

        if sec_a:
            L.append("🤖 <b>AI 分析｜A) 大盤研判</b>")
            L.append(_strip_md(sec_a[:600]))
            L.append("")
        if sec_c:
            L.append("🎯 <b>C) 個股觀察清單</b>")
            L.append(_strip_md(sec_c[:600]))
            L.append("")

    # ── 網頁版連結 ────────────────────────────────────
    pages_url = (os.environ.get("PAGES_URL", "") or "").strip()
    if pages_url:
        L.append(f"🌐 <a href=\"{pages_url}\">開啟網頁版完整報告</a>")

    # ── Workflow 連結（debug 用，可選） ────────────────
    srv  = os.environ.get("GITHUB_SERVER_URL", "")
    repo = os.environ.get("GITHUB_REPOSITORY", "")
    rid  = os.environ.get("GITHUB_RUN_ID", "")
    if srv and repo and rid:
        wf_url = f"{srv}/{repo}/actions/runs/{rid}"
        L.append(f"🔗 <a href=\"{wf_url}\">Workflow 記錄</a>")

    return _trim_to_limit("\n".join(L))


def _extract_section(text: str, code: str) -> str:
    """從 AI 分析中提取 A) / B) / C) ... 章節內容"""
    pat = re.compile(
        rf"^{re.escape(code)}\)\s*(.+?)(?=^[A-F]\)\s|\Z)",
        re.MULTILINE | re.DOTALL,
    )
    m = pat.search(text)
    if not m:
        return ""
    body = m.group(1).strip()
    # 去掉章節標題那行（保留下方內容）
    lines = body.splitlines()
    if lines:
        first = lines[0]
        # 如果第一行是標題（短且結尾沒句點），去掉
        if len(first) < 30 and not first.endswith(("。", ".", "！", "？")):
            body = "\n".join(lines[1:]).strip()
    return body


def _strip_md(text: str) -> str:
    """去除 markdown 標記，避免 Telegram HTML parse 錯誤"""
    text = re.sub(r"\*\*(.+?)\*\*", r"\1", text)
    text = re.sub(r"\*([^*]+?)\*", r"\1", text)
    text = re.sub(r"`(.+?)`", r"\1", text)
    return _esc(text)


# ─────────────────────────────────────────────────────────
#  Telegram API 呼叫
# ─────────────────────────────────────────────────────────
def send_telegram_message(token: str, chat_id: str, text: str) -> bool:
    url = f"{TG_API}/bot{token}/sendMessage"
    payload = {
        "chat_id": chat_id,
        "text": text,
        "parse_mode": "HTML",
        "disable_web_page_preview": True,
    }
    try:
        r = requests.post(url, json=payload, timeout=30)
        if r.status_code == 200:
            print(f"[telegram] ✓ 訊息已送出 → {chat_id}")
            return True
        print(f"[telegram] ✗ HTTP {r.status_code} ({chat_id}): {r.text[:200]}")
    except Exception as e:
        print(f"[telegram] ✗ 例外 ({chat_id}): {e}")
    return False


def send_telegram_document(token: str, chat_id: str, file_path: str, caption: str = "") -> bool:
    if not file_path or not os.path.exists(file_path):
        print(f"[telegram] ⚠ 檔案不存在: {file_path}")
        return False

    url = f"{TG_API}/bot{token}/sendDocument"
    try:
        with open(file_path, "rb") as f:
            files = {"document": (os.path.basename(file_path), f)}
            data  = {
                "chat_id": chat_id,
                "caption": caption[:1000],
                "parse_mode": "HTML",
            }
            r = requests.post(url, data=data, files=files, timeout=60)
        if r.status_code == 200:
            print(f"[telegram] ✓ 附件已送出 → {chat_id}: {os.path.basename(file_path)}")
            return True
        print(f"[telegram] ✗ HTTP {r.status_code} ({chat_id}): {r.text[:200]}")
    except Exception as e:
        print(f"[telegram] ✗ 附件例外 ({chat_id}): {e}")
    return False


def pick_latest(pattern: str):
    files = sorted(glob.glob(pattern))
    return files[-1] if files else None


# ─────────────────────────────────────────────────────────
#  主入口
# ─────────────────────────────────────────────────────────
def main():
    token   = (os.environ.get("TELEGRAM_BOT_TOKEN") or "").strip()
    raw_cid = (os.environ.get("TELEGRAM_CHAT_ID")   or "").strip()
    chat_ids = _parse_chat_ids(raw_cid)

    if not token or not chat_ids:
        print("[telegram] 跳過：TELEGRAM_BOT_TOKEN 或 TELEGRAM_CHAT_ID 未設定")
        return

    if not os.path.exists(SUMMARY_PATH):
        print(f"[telegram] ⚠ {SUMMARY_PATH} 不存在")
        return

    with open(SUMMARY_PATH, "r", encoding="utf-8") as f:
        summary = json.load(f)

    msg = build_telegram_message(summary)
    print(f"[telegram] 訊息長度 {len(msg)} 字元")
    print(f"[telegram] 目標 chat_id 數量：{len(chat_ids)}")

    pdf_path = pick_latest(PDF_PATTERN)
    ymd = datetime.now(TZ).strftime("%Y-%m-%d")

    success_count = 0
    fail_count = 0
    for cid in chat_ids:
        print(f"[telegram] ── 推送至 {cid} ──")
        ok_msg = send_telegram_message(token, cid, msg)

        if pdf_path:
            send_telegram_document(
                token, cid, pdf_path,
                caption=f"📎 <b>{ymd} 券商分點完整報告</b>"
            )
        else:
            print(f"[telegram]   ⚠ 找不到 PDF，跳過附件")

        if ok_msg:
            success_count += 1
        else:
            fail_count += 1

    print(f"[telegram] 完成：成功 {success_count} / 失敗 {fail_count}")

    # 全部失敗才回 exit code 1
    if success_count == 0 and fail_count > 0:
        sys.exit(1)


if __name__ == "__main__":
    main()
