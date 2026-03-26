#!/usr/bin/env python3
"""
スタジオスケジュール集約プログラム

ゴールドジム（原宿東京・原宿Annex・表参道・渋谷・四ツ谷・代々木上原・南青山・サウス東京・溝の口）
チャコットスタジオ（代官山）の最新スケジュールを起動時に取得してHTML一覧を生成します。

使い方:
    python schedule_aggregator.py
"""

import asyncio
import json
import sys
import os
import subprocess
import webbrowser
import io
import re
from pathlib import Path
from datetime import datetime


# ─────────────────────────────────────────────
# 依存パッケージの自動インストール
# ─────────────────────────────────────────────

def ensure_dependencies():
    packages = {
        "playwright": "playwright",
        "pdfplumber": "pdfplumber",
        "bs4": "beautifulsoup4",
    }
    missing = [pkg for mod, pkg in packages.items() if not _importable(mod)]
    if missing:
        print(f"必要なパッケージをインストール中: {', '.join(missing)}")
        subprocess.check_call(
            [sys.executable, "-m", "pip", "install"] + missing,
            stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
        )
        print("インストール完了")

    # Playwright Chromium ブラウザのインストール
    print("Playwright Chromium ブラウザを確認中...")
    result = subprocess.run(
        [sys.executable, "-m", "playwright", "install", "chromium"],
        capture_output=True, text=True,
    )
    if result.returncode == 0:
        print("Chromium 準備完了")
    else:
        print("  ※ Playwright Chromium の自動インストールに失敗しました")
        print("  ※ 手動インストール: python -m playwright install chromium")


def _importable(module_name):
    try:
        __import__(module_name)
        return True
    except ImportError:
        return False


# ─────────────────────────────────────────────
# 店舗設定
# ─────────────────────────────────────────────

GOLDSGYM_SHOPS = [
    {"id": "13150", "name": "ゴールドジム 原宿東京",    "short": "原宿東京"},
    {"id": "9999",  "name": "ゴールドジム 原宿Annex",   "short": "原宿Annex"},
    {"id": "13160", "name": "ゴールドジム 表参道",       "short": "表参道"},
    {"id": "13180", "name": "ゴールドジム 渋谷",         "short": "渋谷"},
    {"id": "13121", "name": "ゴールドジム 四ツ谷",       "short": "四ツ谷"},
    {"id": "13190", "name": "ゴールドジム 代々木上原",   "short": "代々木上原"},
    {"id": "13170", "name": "ゴールドジム 南青山",       "short": "南青山"},
    {"id": "13230", "name": "ゴールドジム サウス東京",   "short": "サウス東京"},
    {"id": "14110", "name": "ゴールドジム 溝の口",       "short": "溝の口"},
]

CHACOTT_STUDIO = {
    "name": "チャコットスタジオ 代官山",
    "short": "代官山(チャコット)",
    "url": "https://www.chacott-jp.com/lesson/studio/daikanyama/schedule/",
}

DAYS_JP = ["月", "火", "水", "木", "金", "土", "日"]
TIME_RE = re.compile(r"(\d{1,2}:\d{2})\s*[～〜\-~ー]\s*(\d{1,2}:\d{2})")


# ─────────────────────────────────────────────
# Gold's Gym 取得
# ─────────────────────────────────────────────

async def fetch_goldsgym_shop(browser, shop):
    page = await browser.new_page()
    classes = []
    pdf_url = None
    error = None

    try:
        url = f"https://www.goldsgym.jp/shop/{shop['id']}/schedule"
        print(f"  [{shop['short']}] {url}")

        await page.goto(url, wait_until="networkidle", timeout=40000)
        await page.wait_for_timeout(2000)

        # ── PDF リンクを探す ──
        pdf_links = await page.evaluate("""
            () => Array.from(document.querySelectorAll('a[href]'))
                .filter(a => a.href.toLowerCase().includes('.pdf'))
                .map(a => ({ href: a.href, text: a.textContent.trim() }))
        """)

        # スケジュール関連を優先
        schedule_keywords = ["schedule", "studio", "スタジオ", "スケジュール", "program"]
        scored = []
        for link in pdf_links:
            score = sum(
                1 for kw in schedule_keywords
                if kw in link["href"].lower() or kw in link["text"]
            )
            scored.append((score, link["href"]))
        scored.sort(reverse=True)
        candidate_pdfs = [href for _, href in scored] or [l["href"] for l in pdf_links]

        for candidate in candidate_pdfs[:3]:
            try:
                resp = await page.request.get(candidate, timeout=20000)
                if resp.ok:
                    pdf_bytes = await resp.body()
                    parsed = _parse_pdf(pdf_bytes, shop["short"])
                    if parsed:
                        classes = parsed
                        pdf_url = candidate
                        print(f"    PDF解析: {len(classes)} 件")
                        break
            except Exception:
                continue

        # ── PDF が無ければ HTML から解析 ──
        if not classes:
            html = await page.content()
            classes = _parse_goldsgym_html(html, shop["short"])
            if classes:
                print(f"    HTML解析: {len(classes)} 件")
            else:
                error = "スケジュールデータが見つかりませんでした"
                print(f"    スケジュールデータなし")

    except Exception as e:
        error = str(e)
        print(f"    エラー: {error[:80]}")
    finally:
        await page.close()

    return {
        "gym": shop["name"],
        "gym_short": shop["short"],
        "gym_type": "goldsgym",
        "source_url": f"https://www.goldsgym.jp/shop/{shop['id']}/schedule",
        "pdf_url": pdf_url,
        "classes": classes,
        "error": error,
    }


# ─────────────────────────────────────────────
# PDF 解析
# ─────────────────────────────────────────────

def _parse_pdf(pdf_bytes, gym_short):
    import pdfplumber

    classes = []
    try:
        with pdfplumber.open(io.BytesIO(pdf_bytes)) as pdf:
            for page in pdf.pages:
                tables = page.extract_tables()
                if tables:
                    for table in tables:
                        classes.extend(_parse_table(table, gym_short))
                else:
                    text = page.extract_text() or ""
                    classes.extend(_parse_text(text, gym_short))
    except Exception as e:
        print(f"    PDF解析例外: {e}")
    return classes


def _parse_table(table, gym_short):
    classes = []
    if not table or len(table) < 2:
        return classes

    # ── ヘッダー行から曜日列を特定 ──
    header = table[0]
    day_cols = {}
    for ci, cell in enumerate(header):
        txt = str(cell or "").strip()
        for day in DAYS_JP:
            if day in txt:
                day_cols[ci] = day
                break

    for row in table[1:]:
        if not row:
            continue
        time_cell = str(row[0] or "").strip()
        m = TIME_RE.search(time_cell)
        if not m:
            continue
        t_start, t_end = m.group(1), m.group(2)

        for ci, day in day_cols.items():
            if ci >= len(row) or not row[ci]:
                continue
            content = str(row[ci]).strip()
            if content in ("-", "－", "—", ""):
                continue
            info = _split_cell(content)
            if info["name"]:
                classes.append({
                    "day": day,
                    "time_start": t_start,
                    "time_end": t_end,
                    **info,
                    "gym_short": gym_short,
                })
    return classes


def _parse_text(text, gym_short):
    """テキスト形式の PDF フォールバック解析"""
    classes = []
    current_day = None
    for line in text.splitlines():
        line = line.strip()
        if not line:
            continue
        for day in DAYS_JP:
            if re.match(rf"^{day}(曜日?)?$", line):
                current_day = day
                break
        m = TIME_RE.search(line)
        if m and current_day:
            rest = line[m.end():].strip()
            parts = re.split(r"\s{2,}|　", rest)
            name = parts[0] if parts else rest
            instructor = parts[1] if len(parts) > 1 else ""
            if name:
                classes.append({
                    "day": current_day,
                    "time_start": m.group(1),
                    "time_end": m.group(2),
                    "name": name,
                    "instructor": instructor,
                    "level": "",
                    "gym_short": gym_short,
                })
    return classes


def _split_cell(content):
    """セル内テキストをクラス名・インストラクター・レベルに分割"""
    lines = [l.strip() for l in re.split(r"[\n\r]+", content) if l.strip()]
    level_kw = ["初級", "中級", "上級", "初中級", "中上級", "入門", "応用",
                "ALL", "全レベル", "LEVEL", "Lv"]

    name_parts, inst_parts, level_parts = [], [], []
    for line in lines:
        if any(kw in line for kw in level_kw):
            level_parts.append(line)
        elif name_parts and re.match(r"^[\u3040-\u30FFa-zA-Z\s・]{2,20}$", line):
            inst_parts.append(line)
        else:
            name_parts.append(line)

    return {
        "name": " ".join(name_parts),
        "instructor": " ".join(inst_parts),
        "level": " ".join(level_parts),
    }


# ─────────────────────────────────────────────
# Gold's Gym HTML 解析（フォールバック）
# ─────────────────────────────────────────────

def _parse_goldsgym_html(html, gym_short):
    from bs4 import BeautifulSoup
    classes = []
    soup = BeautifulSoup(html, "html.parser")

    for table in soup.find_all("table"):
        rows = table.find_all("tr")
        if len(rows) < 2:
            continue
        header_cells = rows[0].find_all(["th", "td"])
        day_cols = {}
        for ci, cell in enumerate(header_cells):
            txt = cell.get_text()
            for day in DAYS_JP:
                if day in txt:
                    day_cols[ci] = day
                    break
        if not day_cols:
            continue

        for row in rows[1:]:
            cells = row.find_all(["th", "td"])
            if not cells:
                continue
            m = TIME_RE.search(cells[0].get_text())
            if not m:
                continue
            t_start, t_end = m.group(1), m.group(2)
            for ci, day in day_cols.items():
                if ci >= len(cells):
                    continue
                content = cells[ci].get_text("\n").strip()
                if content in ("-", "－", "—", ""):
                    continue
                info = _split_cell(content)
                if info["name"]:
                    classes.append({
                        "day": day,
                        "time_start": t_start,
                        "time_end": t_end,
                        **info,
                        "gym_short": gym_short,
                    })
    return classes


# ─────────────────────────────────────────────
# Chacott 代官山 取得
# ─────────────────────────────────────────────

async def fetch_chacott(browser):
    page = await browser.new_page()
    classes = []
    error = None
    s = CHACOTT_STUDIO

    try:
        print(f"  [{s['short']}] {s['url']}")
        await page.goto(s["url"], wait_until="networkidle", timeout=40000)
        await page.wait_for_timeout(2000)
        html = await page.content()
        classes = _parse_chacott_html(html, s["short"])
        print(f"    解析: {len(classes)} 件")
    except Exception as e:
        error = str(e)
        print(f"    エラー: {error[:80]}")
    finally:
        await page.close()

    return {
        "gym": s["name"],
        "gym_short": s["short"],
        "gym_type": "chacott",
        "source_url": s["url"],
        "pdf_url": None,
        "classes": classes,
        "error": error,
    }


def _parse_chacott_html(html, gym_short):
    from bs4 import BeautifulSoup
    classes = []
    soup = BeautifulSoup(html, "html.parser")

    # ── テーブル形式 ──
    for table in soup.find_all("table"):
        rows = table.find_all("tr")
        if len(rows) < 2:
            continue
        header_cells = rows[0].find_all(["th", "td"])
        day_cols = {}
        for ci, cell in enumerate(header_cells):
            txt = cell.get_text()
            for day in DAYS_JP:
                if day in txt:
                    day_cols[ci] = day
                    break
        if not day_cols:
            continue
        for row in rows[1:]:
            cells = row.find_all(["th", "td"])
            if not cells:
                continue
            m = TIME_RE.search(cells[0].get_text())
            if not m:
                continue
            t_start, t_end = m.group(1), m.group(2)
            for ci, day in day_cols.items():
                if ci >= len(cells):
                    continue
                cell = cells[ci]
                content = cell.get_text("\n").strip()
                if not content or content in ("-", "－", "—"):
                    continue
                # クラス名とインストラクターを取得
                name_el = cell.find(class_=re.compile(r"name|title|program", re.I))
                inst_el = cell.find(class_=re.compile(r"instructor|teacher|staff", re.I))
                name = name_el.get_text().strip() if name_el else ""
                instructor = inst_el.get_text().strip() if inst_el else ""
                if not name:
                    info = _split_cell(content)
                    name, instructor = info["name"], info["instructor"]
                if name:
                    classes.append({
                        "day": day,
                        "time_start": t_start,
                        "time_end": t_end,
                        "name": name,
                        "instructor": instructor,
                        "level": "",
                        "gym_short": gym_short,
                    })

    # ── リスト/カード形式（テーブルで取れなかった場合） ──
    if not classes:
        # 曜日ブロックを探す
        current_day = None
        for el in soup.find_all(True):
            txt = el.get_text().strip()
            # 曜日ヘッダーを検出
            if el.name in ["h2", "h3", "h4", "dt", "th"] and len(txt) <= 4:
                for day in DAYS_JP:
                    if day in txt:
                        current_day = day
                        break
                continue

            # 時間＋クラスのエントリを検出
            m = TIME_RE.search(txt)
            if m and current_day and el.name in ["li", "tr", "dd", "div", "p"]:
                rest = txt[m.end():].strip()
                lines = [l.strip() for l in rest.splitlines() if l.strip()]
                name = lines[0] if lines else ""
                instructor = lines[1] if len(lines) > 1 else ""
                if name and len(name) < 50:
                    classes.append({
                        "day": current_day,
                        "time_start": m.group(1),
                        "time_end": m.group(2),
                        "name": name,
                        "instructor": instructor,
                        "level": "",
                        "gym_short": gym_short,
                    })
    return classes


# ─────────────────────────────────────────────
# HTML 生成
# ─────────────────────────────────────────────

def generate_html(all_data):
    updated_at = datetime.now().strftime("%Y年%m月%d日 %H:%M")
    json_data = json.dumps(all_data, ensure_ascii=False)

    html = f"""<!DOCTYPE html>
<html lang="ja">
<head>
<meta charset="UTF-8">
<meta name="viewport" content="width=device-width, initial-scale=1.0">
<title>スタジオスケジュール一覧</title>
<style>
*{{box-sizing:border-box;margin:0;padding:0}}
body{{font-family:'Hiragino Sans','Meiryo',sans-serif;background:#f5f5f7;color:#1d1d1f;font-size:14px}}
header{{background:linear-gradient(135deg,#1a1a2e 0%,#16213e 50%,#0f3460 100%);color:#fff;padding:16px 20px;position:sticky;top:0;z-index:100;box-shadow:0 2px 8px rgba(0,0,0,.3)}}
header h1{{font-size:20px;font-weight:700;letter-spacing:.05em}}
header .meta{{font-size:11px;color:#aaa;margin-top:4px}}
.filters{{background:#fff;padding:14px 20px;border-bottom:1px solid #e0e0e0;display:flex;flex-wrap:wrap;gap:12px;align-items:flex-end}}
.filter-group{{display:flex;flex-direction:column;gap:4px}}
.filter-group label{{font-size:11px;color:#666;font-weight:600;text-transform:uppercase;letter-spacing:.05em}}
input[type=text]{{border:1px solid #ddd;border-radius:6px;padding:6px 10px;font-size:13px;width:180px;outline:none}}
input[type=text]:focus{{border-color:#0f3460}}
select{{border:1px solid #ddd;border-radius:6px;padding:6px 10px;font-size:13px;background:#fff;outline:none;cursor:pointer}}
select:focus{{border-color:#0f3460}}
.day-btns{{display:flex;gap:4px;flex-wrap:wrap}}
.day-btn{{border:1px solid #ddd;border-radius:6px;padding:5px 10px;font-size:13px;background:#fff;cursor:pointer;transition:all .15s}}
.day-btn.active{{background:#0f3460;color:#fff;border-color:#0f3460}}
.gym-pills{{display:flex;gap:6px;flex-wrap:wrap}}
.gym-pill{{border:1px solid #ddd;border-radius:20px;padding:4px 12px;font-size:12px;background:#fff;cursor:pointer;transition:all .15s;white-space:nowrap}}
.gym-pill.active{{background:#0f3460;color:#fff;border-color:#0f3460}}
.gym-pill.goldsgym.active{{background:#c8a200;border-color:#c8a200}}
.gym-pill.chacott.active{{background:#7b2d8b;border-color:#7b2d8b}}
.toolbar{{display:flex;justify-content:space-between;align-items:center;padding:10px 20px;background:#fff;border-bottom:1px solid #e0e0e0}}
.count{{font-size:13px;color:#555}}
.count strong{{color:#0f3460;font-size:15px}}
.view-btns{{display:flex;gap:4px}}
.view-btn{{border:1px solid #ddd;border-radius:6px;padding:5px 12px;font-size:12px;background:#fff;cursor:pointer}}
.view-btn.active{{background:#0f3460;color:#fff;border-color:#0f3460}}
.main{{padding:16px 20px}}
/* テーブルビュー */
.table-wrap{{overflow-x:auto}}
table.schedule{{width:100%;border-collapse:collapse;background:#fff;border-radius:10px;overflow:hidden;box-shadow:0 1px 4px rgba(0,0,0,.08)}}
table.schedule th{{background:#0f3460;color:#fff;padding:10px 12px;text-align:left;font-size:12px;white-space:nowrap}}
table.schedule td{{padding:9px 12px;border-bottom:1px solid #f0f0f0;vertical-align:top}}
table.schedule tr:last-child td{{border-bottom:none}}
table.schedule tr:hover td{{background:#f8f9ff}}
.badge-day{{display:inline-block;background:#e8f0fe;color:#1a56db;border-radius:4px;padding:1px 6px;font-size:11px;font-weight:700}}
.badge-day.土{{background:#fff0e8;color:#d05000}}
.badge-day.日{{background:#fde8e8;color:#c0392b}}
.badge-gym{{display:inline-block;border-radius:4px;padding:2px 7px;font-size:11px;white-space:nowrap}}
.badge-gym.goldsgym{{background:#fff8dc;color:#7a5c00}}
.badge-gym.chacott{{background:#f3e8ff;color:#5b21b6}}
.class-name{{font-weight:600;font-size:13px}}
.instructor{{color:#555;font-size:12px;margin-top:2px}}
.level{{color:#888;font-size:11px}}
.time-cell{{white-space:nowrap;font-weight:500;color:#333}}
/* カードビュー */
.card-grid{{display:grid;grid-template-columns:repeat(auto-fill,minmax(260px,1fr));gap:12px}}
.card{{background:#fff;border-radius:10px;box-shadow:0 1px 4px rgba(0,0,0,.08);padding:14px;display:flex;flex-direction:column;gap:6px}}
.card-top{{display:flex;justify-content:space-between;align-items:flex-start;gap:8px}}
.card-gym{{font-size:11px;font-weight:600}}
.card-gym.goldsgym{{color:#7a5c00}}
.card-gym.chacott{{color:#5b21b6}}
.card-time{{font-size:12px;color:#555;white-space:nowrap}}
.card-name{{font-weight:700;font-size:14px;line-height:1.4}}
.card-inst{{font-size:12px;color:#555}}
.card-level{{font-size:11px;color:#888}}
.card-day-badge{{font-size:11px;font-weight:700}}
.no-data{{text-align:center;padding:60px 20px;color:#999;font-size:16px}}
.error-notice{{background:#fff8f0;border:1px solid #ffd0a0;border-radius:8px;padding:10px 14px;margin-bottom:12px;font-size:12px;color:#884400}}
.hidden{{display:none!important}}
@media(max-width:600px){{
  .filters{{flex-direction:column}}
  input[type=text]{{width:100%}}
}}
</style>
</head>
<body>

<header>
  <h1>🏋️ スタジオスケジュール一覧</h1>
  <div class="meta">最終更新: {updated_at}</div>
</header>

<div class="filters">
  <div class="filter-group">
    <label>インストラクター検索</label>
    <input type="text" id="searchInst" placeholder="名前を入力...">
  </div>
  <div class="filter-group">
    <label>プログラム</label>
    <select id="programFilter"><option value="">すべて</option></select>
  </div>
  <div class="filter-group">
    <label>曜日</label>
    <div class="day-btns" id="dayBtns">
      <button class="day-btn active" data-day="">全</button>
      <button class="day-btn" data-day="月">月</button>
      <button class="day-btn" data-day="火">火</button>
      <button class="day-btn" data-day="水">水</button>
      <button class="day-btn" data-day="木">木</button>
      <button class="day-btn" data-day="金">金</button>
      <button class="day-btn" data-day="土">土</button>
      <button class="day-btn" data-day="日">日</button>
    </div>
  </div>
  <div class="filter-group" style="flex:1 1 100%">
    <label>店舗</label>
    <div class="gym-pills" id="gymPills"></div>
  </div>
</div>

<div class="toolbar">
  <div class="count"><strong id="countNum">0</strong> 件表示中</div>
  <div class="view-btns">
    <button class="view-btn active" id="btnTable" onclick="setView('table')">📋 リスト</button>
    <button class="view-btn" id="btnCard" onclick="setView('card')">🃏 カード</button>
  </div>
</div>

<div class="main">
  <div id="errorNotices"></div>
  <div id="tableView" class="table-wrap">
    <table class="schedule">
      <thead>
        <tr>
          <th>曜日</th>
          <th>時間</th>
          <th>プログラム</th>
          <th>インストラクター</th>
          <th>店舗</th>
        </tr>
      </thead>
      <tbody id="tableBody"></tbody>
    </table>
  </div>
  <div id="cardView" class="card-grid hidden"></div>
  <div id="noData" class="no-data hidden">該当するスケジュールがありません</div>
</div>

<script>
const RAW = {json_data};

// フラット化
const ALL_CLASSES = [];
const GYM_INFO = {{}};

RAW.schedules.forEach(s => {{
  GYM_INFO[s.gym_short] = {{ type: s.gym_type, name: s.gym }};
  s.classes.forEach(c => {{
    ALL_CLASSES.push({{
      ...c,
      gym: s.gym,
      gym_short: s.gym_short,
      gym_type: s.gym_type,
    }});
  }});
}});

// ── ソート: 曜日 → 時間 ──
const DAY_ORDER = {{"月":0,"火":1,"水":2,"木":3,"金":4,"土":5,"日":6}};
ALL_CLASSES.sort((a,b) => {{
  const dd = (DAY_ORDER[a.day]??9) - (DAY_ORDER[b.day]??9);
  if (dd !== 0) return dd;
  return (a.time_start||"").localeCompare(b.time_start||"");
}});

// ── プログラムドロップダウン構築 ──
const programs = [...new Set(ALL_CLASSES.map(c => c.name).filter(Boolean))].sort();
const progSel = document.getElementById("programFilter");
programs.forEach(p => {{
  const o = document.createElement("option");
  o.value = p; o.textContent = p;
  progSel.appendChild(o);
}});

// ── 店舗ピル構築 ──
const gymPills = document.getElementById("gymPills");
const allPill = document.createElement("button");
allPill.className = "gym-pill active"; allPill.textContent = "すべて"; allPill.dataset.gym = "";
gymPills.appendChild(allPill);

RAW.schedules.forEach(s => {{
  const btn = document.createElement("button");
  btn.className = `gym-pill ${{s.gym_type}}`;
  btn.textContent = s.gym_short; btn.dataset.gym = s.gym_short;
  gymPills.appendChild(btn);
}});

// ── エラー表示 ──
const errorDiv = document.getElementById("errorNotices");
RAW.schedules.filter(s => s.error).forEach(s => {{
  const d = document.createElement("div");
  d.className = "error-notice";
  d.textContent = `⚠️ ${{s.gym_short}}: ${{s.error}}`;
  errorDiv.appendChild(d);
}});

// ── 状態 ──
let state = {{ day:"", gym:"", program:"", search:"", view:"table" }};

function setView(v) {{
  state.view = v;
  document.getElementById("tableView").classList.toggle("hidden", v !== "table");
  document.getElementById("cardView").classList.toggle("hidden", v !== "card");
  document.getElementById("btnTable").classList.toggle("active", v === "table");
  document.getElementById("btnCard").classList.toggle("active", v === "card");
}}

// ── フィルター ──
function applyFilters() {{
  const q = state.search.toLowerCase();
  const filtered = ALL_CLASSES.filter(c => {{
    if (state.day && c.day !== state.day) return false;
    if (state.gym && c.gym_short !== state.gym) return false;
    if (state.program && c.name !== state.program) return false;
    if (q && !(c.instructor||"").toLowerCase().includes(q) && !(c.name||"").toLowerCase().includes(q)) return false;
    return true;
  }});

  document.getElementById("countNum").textContent = filtered.length;
  renderTable(filtered);
  renderCards(filtered);
  document.getElementById("noData").classList.toggle("hidden", filtered.length > 0);
}}

function dayClass(day) {{
  if (day === "土") return "badge-day 土";
  if (day === "日") return "badge-day 日";
  return "badge-day";
}}

function renderTable(data) {{
  const tbody = document.getElementById("tableBody");
  tbody.innerHTML = "";
  data.forEach(c => {{
    const tr = document.createElement("tr");
    tr.innerHTML = `
      <td><span class="${{dayClass(c.day)}}">${{c.day}}</span></td>
      <td class="time-cell">${{c.time_start}}〜${{c.time_end}}</td>
      <td>
        <div class="class-name">${{esc(c.name)}}</div>
        ${{c.level ? `<div class="level">${{esc(c.level)}}</div>` : ""}}
      </td>
      <td><div class="instructor">${{esc(c.instructor||"—")}}</div></td>
      <td><span class="badge-gym ${{c.gym_type}}">${{esc(c.gym_short)}}</span></td>
    `;
    tbody.appendChild(tr);
  }});
}}

function renderCards(data) {{
  const grid = document.getElementById("cardView");
  grid.innerHTML = "";
  data.forEach(c => {{
    const card = document.createElement("div");
    card.className = "card";
    card.innerHTML = `
      <div class="card-top">
        <span class="card-gym ${{c.gym_type}}">${{esc(c.gym_short)}}</span>
        <span class="card-time">${{c.time_start}}〜${{c.time_end}}</span>
      </div>
      <div class="card-name">${{esc(c.name)}}</div>
      ${{c.instructor ? `<div class="card-inst">👤 ${{esc(c.instructor)}}</div>` : ""}}
      ${{c.level ? `<div class="card-level">${{esc(c.level)}}</div>` : ""}}
      <div><span class="${{dayClass(c.day)}}" style="font-size:12px">${{c.day}}曜日</span></div>
    `;
    grid.appendChild(card);
  }});
}}

function esc(s) {{
  return String(s||"").replace(/&/g,"&amp;").replace(/</g,"&lt;").replace(/>/g,"&gt;");
}}

// ── イベントリスナー ──
document.getElementById("searchInst").addEventListener("input", e => {{
  state.search = e.target.value; applyFilters();
}});

progSel.addEventListener("change", e => {{
  state.program = e.target.value; applyFilters();
}});

document.getElementById("dayBtns").addEventListener("click", e => {{
  if (!e.target.dataset.hasOwnProperty("day")) return;
  state.day = e.target.dataset.day;
  document.querySelectorAll(".day-btn").forEach(b => b.classList.toggle("active", b.dataset.day === state.day));
  applyFilters();
}});

gymPills.addEventListener("click", e => {{
  const btn = e.target.closest(".gym-pill");
  if (!btn) return;
  state.gym = btn.dataset.gym;
  document.querySelectorAll(".gym-pill").forEach(b => b.classList.toggle("active", b.dataset.gym === state.gym));
  applyFilters();
}});

// ── 初期表示 ──
applyFilters();
</script>
</body>
</html>"""
    return html


# ─────────────────────────────────────────────
# メイン
# ─────────────────────────────────────────────

async def main():
    ensure_dependencies()

    from playwright.async_api import async_playwright

    print("=" * 55)
    print("  スタジオスケジュール集約プログラム")
    print(f"  {datetime.now().strftime('%Y年%m月%d日 %H:%M')} 取得開始")
    print("=" * 55)

    all_data = {
        "updated_at": datetime.now().isoformat(),
        "schedules": [],
    }

    async with async_playwright() as pw:
        # システムの Chromium/Chrome がある場合は優先して使用
        system_chrome_paths = [
            "/Applications/Google Chrome.app/Contents/MacOS/Google Chrome",  # macOS Chrome
            "/Applications/Chromium.app/Contents/MacOS/Chromium",            # macOS Chromium
            "/usr/bin/google-chrome",
            "/usr/bin/google-chrome-stable",
            "/usr/bin/chromium",
            "/usr/bin/chromium-browser",
        ]
        executable = next(
            (p for p in system_chrome_paths if os.path.isfile(p)), None
        )
        launch_opts = {"headless": True}
        if executable:
            launch_opts["executable_path"] = executable
            print(f"  ブラウザ: {executable}")
        browser = await pw.chromium.launch(**launch_opts)

        print("\n【ゴールドジム】")
        for shop in GOLDSGYM_SHOPS:
            result = await fetch_goldsgym_shop(browser, shop)
            all_data["schedules"].append(result)

        print("\n【チャコットスタジオ 代官山】")
        chacott = await fetch_chacott(browser)
        all_data["schedules"].append(chacott)

        await browser.close()

    total = sum(len(s["classes"]) for s in all_data["schedules"])
    print(f"\n合計 {total} 件のクラスを取得")

    print("\nHTMLを生成中...")
    html = generate_html(all_data)
    out = Path(__file__).parent / "schedule.html"
    out.write_text(html, encoding="utf-8")
    print(f"生成完了: {out}")

    print("ブラウザで開いています...")
    webbrowser.open(out.as_uri())
    print("\n完了！")


if __name__ == "__main__":
    asyncio.run(main())
