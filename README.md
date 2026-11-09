# Stock Scanner → LINE / Discord

ระบบสแกนหุ้น US 2 ตัว รันอัตโนมัติวันจันทร์–ศุกร์ แล้วส่งผลเข้า LINE / Discord

| | Scanner A: Pre-market Gappers | Scanner B: Trend-join Long |
|---|---|---|
| เงื่อนไข | Gap > 5% จากราคาปิดเมื่อวาน, ราคา > $3, วอลุ่ม pre-market > 50,000 | ราคา > High เมื่อวาน, Close เมื่อวาน > SMA 200, ราคา > High pre-market และ > High of day |
| เวลา (ET) | 08:30–14:00 ทุก 30 นาที | 5 นาทีหลัง A (08:35–14:35) + 15:00, ให้สัญญาณหลัง 10:00 เท่านั้น |
| ข้อมูล | Yahoo Finance + ข่าวจาก Benzinga | หุ้นจาก Scanner A |
| ไฟล์ผล | `results/premarket_YYYY-MM-DD.json` | `results/strategy_YYYY-MM-DD.json` |

**เวลาไทย:** ช่วง พ.ย.–มี.ค. ระบบทำงาน 20:30–03:00 น. ส่วนช่วง มี.ค.–พ.ย. (US daylight saving) จะเร็วขึ้น 1 ชม. เป็น 19:30–02:00 น. โปรแกรมปรับเวลาเองอัตโนมัติ

## 1. ติดตั้ง

```bash
python -m venv venv
venv\Scripts\activate          # Windows   (Mac/Linux: source venv/bin/activate)
pip install -r requirements.txt
```

## 2. ตั้งค่า Discord

1. ในแอป Discord สร้างเซิร์ฟเวอร์ส่วนตัว (กด + ทางซ้าย → Create My Own → For me and my friends)
2. คลิกขวาที่ช่อง #general → **Edit Channel** → **Integrations** → **Webhooks** → **New Webhook**
3. กด **Copy Webhook URL**
4. คัดลอก `.env.example` เป็น `.env` (ถ้ายังไม่มี) แล้ววาง URL ต่อท้าย `DISCORD_WEBHOOK_URL=`

ทดสอบ: `python notify.py --test`

> Webhook URL ใช้ส่งข้อความเข้าช่องได้ทันที อย่าแชร์ให้ใคร ถ้าหลุดให้ลบ webhook แล้วสร้างใหม่

## 3. (ไม่บังคับ) Benzinga

ใส่ `BENZINGA_API_KEY` ใน `.env` เพื่อดึงข่าวจาก Benzinga (API ของ Benzinga เป็นแบบเสียเงิน)
ถ้าไม่ใส่ ระบบใช้หัวข่าวจาก Yahoo Finance แทน

## 4. รัน

```bash
python scheduler.py --once     # ทดสอบ: สแกนทันทีแล้วส่ง Discord (ข้ามเงื่อนไขเวลา)
python scheduler.py            # รันตามตารางเวลา เปิดทิ้งไว้
```

รันแยกได้: `python premarket_scanner.py`, `python strategy_scanner.py --force`

**เครื่องต้องเปิดและต่อเน็ตตลอดช่วงเวลาทำงาน** ถ้าไม่อยากเปิดคอมทิ้งไว้ ให้รันบน VPS
หรือ Raspberry Pi แทน (คำสั่งเดียวกัน)

## พอร์ต, แจ้งเตือนราคา และ Dashboard

**ใส่ข้อมูลพอร์ตใน `portfolio.csv`** (เปิดด้วย `open -e portfolio.csv`)

| คอลัมน์ | ความหมาย |
|---|---|
| ticker | ชื่อหุ้น |
| shares | จำนวนหุ้น (เศษหุ้นได้ เช่น 0.35) |
| avg_cost | ราคาทุนเฉลี่ยต่อหุ้น (USD) |
| stop | จุดตัดขาดทุน ว่างไว้ = ต้นทุน -10% |
| target | ราคาเป้าหมาย ว่างไว้ = ไม่แจ้ง |

**แจ้งเตือนราคา** เช็กทุกรอบของ Scanner B: หลุด stop, ถึง target หรือขยับแรงเกิน ±5% ในวันเดียว
แต่ละเรื่องแจ้งวันละครั้ง ต่อท้ายในข้อความเดียวกับผลสแกน (ไม่เปลืองโควตา LINE เพิ่ม)

**สรุปพอร์ตประจำวัน** ส่งหลังตลาดปิด 16:10 ET (~04:10 น. เวลาไทย)
ราคา, กำไร/ขาดทุน, แนวรับ-แนวต้าน 20 วัน, RSI, จุดตัดขาดทุน และข่าวล่าสุดของแต่ละตัว

**Dashboard** `results/dashboard.html` อัปเดตทุกรอบ เปิดด้วย `python dashboard.py`
แท็บที่เปิดค้างไว้จะรีเฟรชเองทุก 5 นาที

**โควตา LINE** ถ้าเหลือไม่ถึง 40 ข้อความต่อเดือน ระบบจะหยุดส่งผลสแกนรอบปกติเข้า LINE
แต่ยังส่งแจ้งเตือนราคาและสรุปประจำวันเสมอ (Discord ส่งได้ไม่จำกัด)

ทดสอบ: `python portfolio.py` (แสดงผลเฉยๆ) หรือ `python portfolio.py --send` (ส่งสรุปเข้า LINE ทันที)

## รันออนไลน์ด้วย GitHub Actions (ไม่ต้องเปิดคอม)

ไฟล์ `.github/workflows/scanner.yml` สั่งให้ GitHub รัน `cloud_run.py` ทุก 30 นาที วันจันทร์–ศุกร์
สแกนช่วงตลาดเปิด ส่งสรุปพอร์ตหลังตลาดปิด แล้วอัปเดตหน้า Dashboard บน GitHub Pages (ล็อกด้วยรหัสผ่าน)

**Secrets ที่ต้องใส่** (Settings → Secrets and variables → Actions → New repository secret)

| ชื่อ | ค่า |
|---|---|
| `LINE_CHANNEL_ACCESS_TOKEN` | token ของบอท LINE |
| `LINE_USER_ID` | User ID ของคุณ (ขึ้นต้นด้วย U) |
| `PORTFOLIO_CSV` | เนื้อหาไฟล์ portfolio.csv ทั้งไฟล์ |
| `DASHBOARD_PASSWORD` | รหัสผ่านสำหรับเปิดหน้า Dashboard |
| `DISCORD_WEBHOOK_URL`, `BENZINGA_API_KEY` | ไม่บังคับ |

**เปิด Dashboard:** Settings → Pages → Source: Deploy from a branch → `gh-pages` / root
แล้วเข้าที่ `https://<ชื่อผู้ใช้>.github.io/stock-scanner/`

**สั่งรันเอง:** แท็บ Actions → Stock scanner → Run workflow → เลือก `all`

ข้อมูลพอร์ตและ token ไม่ถูกเก็บในโค้ด ผลสแกนย้อนหลังเก็บใน Actions cache (ไม่เปิดเผย)
หน้าเว็บที่เผยแพร่มีแค่ไฟล์ที่เข้ารหัสแล้ว

## 5. TradingView

TradingView ไม่มี API ให้สคริปต์ภายนอกสั่งสแกนได้ `strategy_scanner.py` จึงคำนวณเงื่อนไขเดียวกันจากข้อมูล Yahoo
ส่วน `trend_join_long.pine` คือเงื่อนไขเดียวกันในรูป Pine Script สำหรับดูบนกราฟหรือตั้ง alert:
Pine Editor → วางโค้ด → Add to chart (กราฟ 1–5 นาที, เปิด Extended trading hours)

## ปรับแต่ง

ค่าทั้งหมดอยู่ใน `config.py`: เกณฑ์ gap/ราคา/วอลุ่ม, เวลา, จำนวนผลสูงสุด
และ `STRATEGY_TICKER_SOURCE` (`union` = หุ้นที่เคยผ่าน A ทั้งวัน, `latest` = เฉพาะรอบล่าสุด)
เพิ่มหุ้นที่อยากให้เช็กเสมอได้ใน `universe.txt`

## ข้อจำกัด

- ข้อมูล Yahoo ผ่าน yfinance ไม่ใช่ API ทางการ อาจดีเลย์หรือใช้ไม่ได้ชั่วคราว
- Yahoo ไม่มี screener pre-market โดยตรง ระบบจึงสแกนจาก `universe.txt` + ลิสต์ gainers/most active ของ Yahoo
  หุ้นเล็กที่ไม่อยู่ในลิสต์อาจหลุดไป
- "Stop ref" ในข้อความคือระดับ breakout ใช้อ้างอิงเท่านั้น ไม่ใช่คำแนะนำซื้อขาย
