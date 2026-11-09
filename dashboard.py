"""Builds results/dashboard.html: portfolio, price alerts, Scanner A and Scanner B in one page.
Self-contained (no internet needed to view). Rebuilt after every scheduled run;
an open tab reloads itself every 5 minutes.

    python dashboard.py          # rebuild from the latest saved results and open it
"""
from __future__ import annotations

import json
import subprocess
import sys
from datetime import datetime
from html import escape

import config as C

OUT = C.RESULTS_DIR / "dashboard.html"


def _load(name):
    p = C.RESULTS_DIR / name
    try:
        return json.loads(p.read_text()) if p.exists() else None
    except Exception:
        return None


def _sign(v, pct=False, money=False):
    if v is None:
        return '<span class="muted">–</span>'
    v = 0.0 if abs(v) < 0.005 else v
    cls = "up" if v > 0 else "down" if v < 0 else "muted"
    txt = f"{v:+,.2f}%" if pct else (f"{v:+,.2f}" if money else f"{v:+,.2f}")
    return f'<span class="{cls}">{txt}</span>'


def sparkline(history, stop=None, w=140, h=36):
    vals = [v for _, v in history]
    if len(vals) < 2:
        return ""
    lo, hi = min(vals + ([stop] if stop else [])), max(vals)
    rng = (hi - lo) or 1
    pts = " ".join(f"{i * w / (len(vals) - 1):.1f},{h - (v - lo) / rng * (h - 4) - 2:.1f}"
                   for i, v in enumerate(vals))
    cls = "up" if vals[-1] >= vals[0] else "down"
    sl = ""
    if stop and lo <= stop <= hi:
        y = h - (stop - lo) / rng * (h - 4) - 2
        sl = f'<line x1="0" x2="{w}" y1="{y:.1f}" y2="{y:.1f}" class="sl"/>'
    return (f'<svg class="spark" viewBox="0 0 {w} {h}" width="{w}" height="{h}" '
            f'aria-label="90-day price">{sl}<polyline points="{pts}" class="{cls}"/></svg>')


def build(alerts=None) -> str:
    snap = _load("portfolio_latest.json") or {"holdings": [], "totals": {}}
    today = datetime.now(C.ET).date().isoformat()
    pa = _load(f"premarket_{today}.json")
    sb = _load(f"strategy_{today}.json")
    a_hits = pa["latest"]["hits"] if pa else []
    a_time = pa["latest"]["run_at"][11:16] if pa else None
    b_run = sb["runs"][-1] if sb and sb.get("runs") else None
    t = snap.get("totals", {})
    alerts = alerts if alerts is not None else [
        a for s in snap["holdings"] for a in __import__("portfolio").check_alerts(s)]

    # --- holdings rows ---
    rows = []
    for s in sorted(snap["holdings"], key=lambda r: -r["value"]):
        trend = {"up": "▲ ขาขึ้น", "down": "▼ ขาลง", "mixed": "↔ ผสม"}[s["trend"]]
        rsi = s.get("rsi14")
        rsi_cls = "down" if rsi and rsi >= 70 else "up" if rsi and rsi <= 30 else ""
        news = escape(s.get("news") or "")
        rows.append(f"""
<tr>
  <td><b>{s['ticker']}</b>{f' <span class="badge">📅 งบ {s["earnings_date"][5:]}</span>' if s.get('earnings_in_days') is not None else ''}<div class="muted small">{s['shares']:g} หุ้น @ {s['avg_cost'] or '–'}</div></td>
  <td class="num">${s['price']:,.2f}<div class="small">{_sign(s['day_change_pct'], pct=True)}</div></td>
  <td class="num">${s['value']:,.2f}<div class="bar"><i style="width:{s.get('weight_pct', 0)}%"></i></div><div class="muted small">{s.get('weight_pct', 0)}%</div></td>
  <td class="num">{_sign(s.get('pl'), money=True)}<div class="small">{_sign(s.get('pl_pct'), pct=True)}</div></td>
  <td>{sparkline(s.get('history', []), s.get('stop'))}</td>
  <td class="small">{trend}<br>RSI <span class="{rsi_cls}">{rsi if rsi is not None else '–'}</span></td>
  <td class="small num">รับ {s.get('support_20d') or '–'}<br>ต้าน {s.get('resistance_20d') or '–'}<br><span class="down">SL {s.get('stop') or '–'}</span>{f'<br><span class="up">TP {s["target"]}</span>' if s.get('target') else ''}</td>
</tr>
<tr class="news"><td colspan="7">📰 {news or '<span class="muted">ไม่มีข่าวล่าสุด</span>'}</td></tr>""")

    a_rows = "".join(
        f"<tr><td><b>{h['ticker']}</b></td><td class='num'>${h['price']:,.2f}</td>"
        f"<td class='num up'>+{h['gap_pct']:.1f}%</td><td class='num'>{h['premarket_volume']:,}</td>"
        f"<td class='small'>{escape(h.get('catalyst', ''))}</td></tr>" for h in a_hits
    ) or "<tr><td colspan='5' class='muted'>ยังไม่มีหุ้นผ่านเงื่อนไข</td></tr>"
    b_hits = b_run["hits"] if b_run else []
    b_rows = "".join(
        f"<tr><td><b>{h['ticker']}</b> ✅</td><td class='num'>${h['price']:,.2f}</td>"
        f"<td class='num'>{h['yesterday_high']}</td><td class='num'>{h['premarket_high']}</td>"
        f"<td class='num'>{h['hod_before_bar']}</td><td class='num down'>{h['stop_ref']} (-{h['risk_pct']}%)</td></tr>"
        for h in b_hits
    ) or f"<tr><td colspan='6' class='muted'>{'ยังไม่มีสัญญาณ (เริ่มหลัง 10:00 ET)' if not b_run else 'ไม่มีหุ้นผ่านครบทุกเงื่อนไข'}</td></tr>"
    alert_html = "".join(f"<li>{escape(a['text'])}</li>" for a in alerts)
    as_of = snap.get("as_of", "")[:16].replace("T", " ")
    m = snap.get("market")
    if m:
        cls = {"Risk-on": "up", "Risk-off": "down"}.get(m["label"], "")
        th = {"Risk-on": "ขาขึ้น", "Caution": "ระวัง", "Risk-off": "อ่อนแอ"}[m["label"]]
        vix = f" · VIX {m['vix']}" if m.get("vix") else ""
        market_card = (f'<div class="card kpi"><div class="label">สภาพตลาด</div>'
                       f'<div class="val {cls}">{th}</div><div class="small muted">SPY '
                       f'{m["spy"]["day_pct"]:+.1f}% · QQQ {m["qqq"]["day_pct"]:+.1f}%{vix}</div></div>')
    else:
        market_card = ""

    return f"""<!doctype html>
<html lang="th"><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<meta http-equiv="refresh" content="300">
<title>Stock Dashboard</title>
<style>
:root{{--bg:#f6f7f9;--card:#fff;--fg:#14171c;--muted:#6b7280;--line:#e5e7eb;--up:#0f9d58;--down:#d93025;--acc:#3b5bdb}}
@media (prefers-color-scheme:dark){{:root{{--bg:#0f1115;--card:#171a21;--fg:#e8eaed;--muted:#9aa0a6;--line:#2a2f3a;--up:#34c77b;--down:#ff6b6b;--acc:#7b93ff}}}}
*{{box-sizing:border-box}}body{{margin:0;background:var(--bg);color:var(--fg);font:14px/1.45 -apple-system,BlinkMacSystemFont,"Sukhumvit Set","Segoe UI",sans-serif}}
main{{max-width:1100px;margin:0 auto;padding:20px 16px 40px}}
h1{{font-size:20px;margin:0}}h2{{font-size:15px;margin:0 0 10px}}
.head{{display:flex;justify-content:space-between;align-items:baseline;flex-wrap:wrap;gap:8px;margin-bottom:16px}}
.kpis{{display:grid;grid-template-columns:repeat(auto-fit,minmax(170px,1fr));gap:12px;margin-bottom:16px}}
.card{{background:var(--card);border:1px solid var(--line);border-radius:12px;padding:14px 16px;margin-bottom:16px}}
.kpi .label{{color:var(--muted);font-size:12px}}.kpi .val{{font-size:22px;font-weight:650;font-variant-numeric:tabular-nums}}
.scroll{{overflow-x:auto}}table{{width:100%;border-collapse:collapse;min-width:640px}}
th{{text-align:left;font-weight:500;color:var(--muted);font-size:12px;padding:6px 8px;border-bottom:1px solid var(--line)}}
td{{padding:8px;border-bottom:1px solid var(--line);vertical-align:top}}tr.news td{{padding-top:0;color:var(--muted);font-size:12px}}
.num{{text-align:right;font-variant-numeric:tabular-nums}}.small{{font-size:12px}}.muted{{color:var(--muted)}}
.up{{color:var(--up)}}.down{{color:var(--down)}}
.bar{{height:4px;background:var(--line);border-radius:2px;margin-top:4px}}.bar i{{display:block;height:100%;background:var(--acc);border-radius:2px}}
.spark polyline{{fill:none;stroke-width:1.6}}.spark polyline.up{{stroke:var(--up)}}.spark polyline.down{{stroke:var(--down)}}
.spark .sl{{stroke:var(--down);stroke-dasharray:3 3;stroke-width:1;opacity:.6}}
.alerts{{border-color:var(--down)}}.alerts ul{{margin:0;padding-left:18px}}
footer{{color:var(--muted);font-size:12px;text-align:center}}
.badge{{font-size:11px;font-weight:500;padding:1px 6px;border-radius:8px;background:var(--line);white-space:nowrap}}
</style></head><body><main>
<div class="head"><h1>📊 Stock Dashboard</h1><span class="muted small">อัปเดต {escape(as_of)} ET · รีเฟรชเองทุก 5 นาที</span></div>

<div class="kpis">
  <div class="card kpi"><div class="label">มูลค่าพอร์ต</div><div class="val">${t.get('value', 0):,.2f}</div></div>
  <div class="card kpi"><div class="label">กำไร/ขาดทุนวันนี้</div><div class="val">{_sign(t.get('day_pl'), money=True)}</div></div>
  <div class="card kpi"><div class="label">กำไร/ขาดทุนรวม</div><div class="val">{_sign(t.get('pl'), money=True)}</div><div class="small">{_sign(t.get('pl_pct'), pct=True)}</div></div>
  {market_card}
  <div class="card kpi"><div class="label">สัญญาณวันนี้</div><div class="val">{len(a_hits)} <span class="muted small">gappers</span> · {len(b_hits)} <span class="muted small">entries</span></div></div>
</div>

{f'<div class="card alerts"><h2>🔔 แจ้งเตือนราคา</h2><ul>{alert_html}</ul></div>' if alerts else ''}

<div class="card"><h2>พอร์ตของฉัน</h2><div class="scroll"><table>
<tr><th>หุ้น</th><th class="num">ราคา</th><th class="num">มูลค่า / สัดส่วน</th><th class="num">กำไร/ขาดทุน</th><th>90 วัน (เส้นประ = SL)</th><th>แนวโน้ม</th><th class="num">ระดับราคา</th></tr>
{''.join(rows) or "<tr><td colspan='7' class='muted'>ยังไม่มีข้อมูล — กรอก portfolio.csv แล้วรัน python portfolio.py</td></tr>"}
</table></div></div>

<div class="card"><h2>Scanner A: Pre-market Gappers {f'<span class="muted small">· {a_time} ET</span>' if a_time else ''}</h2><div class="scroll"><table>
<tr><th>หุ้น</th><th class="num">ราคา</th><th class="num">Gap</th><th class="num">วอลุ่ม PM</th><th>ข่าว</th></tr>{a_rows}</table></div></div>

<div class="card"><h2>Scanner B: Trend-join Long Hits {f'<span class="muted small">· {b_run["run_at"][11:16]} ET</span>' if b_run else ''}</h2><div class="scroll"><table>
<tr><th>หุ้น</th><th class="num">Entry</th><th class="num">High เมื่อวาน</th><th class="num">High PM</th><th class="num">HOD</th><th class="num">Stop ref</th></tr>{b_rows}</table></div></div>

<footer>ข้อมูลจาก Yahoo Finance อาจล่าช้า · เพื่อการศึกษาและทำการบ้านต่อ ไม่ใช่คำแนะนำการลงทุน</footer>
</main></body></html>"""


def write(alerts=None):
    C.RESULTS_DIR.mkdir(exist_ok=True)
    OUT.write_text(build(alerts), encoding="utf-8")
    return OUT


if __name__ == "__main__":
    p = write()
    print(p)
    if sys.platform == "darwin" and "--no-open" not in sys.argv:
        subprocess.run(["open", str(p)])
