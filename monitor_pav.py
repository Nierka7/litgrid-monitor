"""
PAV (Planuojamos ūkinės veiklos) Monitoringas
"""

import os
import csv
import json
import io
import smtplib
import requests
from datetime import datetime, timezone
from email.mime.multipart import MIMEMultipart
from email.mime.text import MIMEText
from pathlib import Path

TELEGRAM_TOKEN   = os.environ["TELEGRAM_TOKEN"]
TELEGRAM_CHAT_ID = os.environ["TELEGRAM_CHAT_ID"]
GMAIL_USER       = os.environ["GMAIL_USER"]
GMAIL_APP_PASS   = os.environ["GMAIL_APP_PASS"]
NOTIFY_EMAIL     = os.environ.get("NOTIFY_EMAIL", GMAIL_USER)

DATA_FILE = Path("data/pav_previous.json")

SHEET_ID = "1r5q6rPjSL6eF2c08LfIaym5t3wwL9nZ-"
GID      = "1337314935"
CSV_URL  = f"https://docs.google.com/spreadsheets/d/{SHEET_ID}/export?format=csv&gid={GID}"

# Ieškome šių variantų — vienas veiks nepriklausomai nuo enkodingo
WIND_VARIANTS = [
    "vėjo elektrinių",   # UTF-8 teisingas
    "vejo elektrini",    # be diakritikų (atsarginis)
    "v\u00c4\u0097jo",  # latin-1 iškraipymas: ė → Ä—
    "elektrini\u00c5\u00b3",  # latin-1 iškraipymas: ų → Å³
]


def fetch_csv() -> tuple[list[dict], list[list[str]]]:
    """Grąžina (struktūruotos eilutės, visos raw eilutės)."""
    resp = requests.get(CSV_URL, timeout=30)
    resp.raise_for_status()

    raw = resp.content

    # Dekoduojame — pirma bandome UTF-8, po to latin-1 (niekada nekelia klaidos)
    content = None
    used_enc = None
    for enc in ("utf-8-sig", "utf-8"):
        try:
            decoded = raw.decode(enc)
            content = decoded
            used_enc = enc
            break
        except UnicodeDecodeError:
            continue
    if content is None:
        content = raw.decode("latin-1")
        used_enc = "latin-1"

    print(f"  Enkodingo: {used_enc}")

    all_rows = list(csv.reader(io.StringIO(content)))

    # Randame antraštės eilutę — pirma ne tuščia eilutė
    header_idx = None
    headers = None
    for i, row in enumerate(all_rows):
        if row and any(c.strip() for c in row):
            header_idx = i
            headers = [h.strip() for h in row]
            break

    if header_idx is None:
        raise ValueError("CSV visiškai tuščias")

    print(f"  Antraštė eilutėje {header_idx}: {headers[:4]}")

    # Surenkame duomenų eilutes — praleisti tuščias ir skyriklines
    result = []
    for row in all_rows[header_idx + 1:]:
        if len(row) < 3:
            continue
        vals = [v.strip() for v in row]
        # Tuščia eilutė arba skyriklis (tik pirmas stulpelis užpildytas)
        if not vals[0] or (not vals[1] and not vals[2]):
            continue
        entry = dict(zip(headers, vals))
        result.append(entry)

    return result, all_rows


def is_wind_row(row: dict) -> bool:
    """Tikrina ar eilutė yra apie vėjo elektrines — veikia bet kokiu enkodingu."""
    # Tikriname visus stulpelius (apsauga jei antraštė iškraipyta)
    all_text = " ".join(row.values()).lower()
    return any(v.lower() in all_text for v in WIND_VARIANTS)


def find_wind_rows(rows: list[dict]) -> list[dict]:
    return [r for r in rows if is_wind_row(r)]


def make_key(row: dict) -> str:
    # Naudojame visų reikšmių hash — nepriklausomai nuo stulpelių pavadinimų
    vals = list(row.values())
    return "||".join(vals[:4])


def load_previous() -> tuple[dict, bool]:
    if not DATA_FILE.exists():
        return {}, False
    with open(DATA_FILE, encoding="utf-8") as f:
        return json.load(f), True


def save_snapshot(keys: list[str]):
    DATA_FILE.parent.mkdir(exist_ok=True)
    snapshot = {"__initialized__": True}
    snapshot.update({k: True for k in keys})
    with open(DATA_FILE, "w", encoding="utf-8") as f:
        json.dump(snapshot, f, indent=2, ensure_ascii=False)


def get_col(row: dict, *keywords) -> str:
    """Gauna stulpelio reikšmę pagal raktažodžius — veikia net jei pavadinimas iškraipytas."""
    for key in row:
        key_lower = key.lower()
        for kw in keywords:
            if kw in key_lower:
                return row[key].strip() or "–"
    return "–"


def format_row_telegram(row: dict) -> str:
    pav   = get_col(row, "pavadinimas")
    org   = get_col(row, "organizatorius")
    data  = get_col(row, "data")
    vieta = get_col(row, "vieta")
    return (
        f"<b>📋 {pav}</b>\n"
        f"  🏢 Organizatorius: {org}\n"
        f"  📅 Paskelbimo data: {data}\n"
        f"  📍 Vieta: {vieta}"
    )


def build_telegram_message(new_rows: list[dict], date_str: str) -> str:
    lines = [
        "🌬️ <b>PAV — naujas vėjo elektrinių projektas!</b>",
        f"📅 {date_str} | Naujų įrašų: {len(new_rows)}\n",
    ]
    for row in new_rows:
        lines.append(format_row_telegram(row))
        lines.append("")
    lines.append("<i>Šaltinis: PAV viešųjų konsultacijų lentelė</i>")
    msg = "\n".join(lines)
    if len(msg) > 4000:
        msg = msg[:3990] + "\n\n<i>... (pranešimas sutrumpintas)</i>"
    return msg


def build_email_html(new_rows: list[dict], date_str: str) -> str:
    rows_html = ""
    for row in new_rows:
        pav   = get_col(row, "pavadinimas")
        org   = get_col(row, "organizatorius")
        data  = get_col(row, "data")
        vieta = get_col(row, "vieta")
        rows_html += f"""
        <tr>
          <td style="padding:10px 14px;border-bottom:1px solid #eee;vertical-align:top;
                     font-weight:bold;color:#1a5276;">{pav}</td>
          <td style="padding:10px 14px;border-bottom:1px solid #eee;">{org}</td>
          <td style="padding:10px 14px;border-bottom:1px solid #eee;white-space:nowrap;">{data}</td>
          <td style="padding:10px 14px;border-bottom:1px solid #eee;">{vieta}</td>
        </tr>"""

    return f"""
    <html><body style="font-family:Arial,sans-serif;max-width:900px;margin:auto;padding:20px;">
      <h2 style="color:#1a5276;border-bottom:2px solid #1a5276;padding-bottom:8px;">
        🌬️ PAV — naujas vėjo elektrinių projektas
      </h2>
      <p><b>Data:</b> {date_str} &nbsp;|&nbsp; <b>Naujų įrašų:</b> {len(new_rows)}</p>
      <table style="width:100%;border-collapse:collapse;margin-top:16px;">
        <thead>
          <tr style="background:#1a5276;color:#fff;">
            <th style="padding:10px 14px;text-align:left;">PŪV pavadinimas</th>
            <th style="padding:10px 14px;text-align:left;">Organizatorius</th>
            <th style="padding:10px 14px;text-align:left;">Paskelbimo data</th>
            <th style="padding:10px 14px;text-align:left;">Vieta</th>
          </tr>
        </thead>
        <tbody>{rows_html}</tbody>
      </table>
      <hr style="margin-top:24px;border:none;border-top:1px solid #eee;"/>
      <small style="color:#999;">Automatinis pranešimas | PAV monitoringas</small>
    </body></html>
    """


def send_telegram(message: str):
    resp = requests.post(
        f"https://api.telegram.org/bot{TELEGRAM_TOKEN}/sendMessage",
        json={"chat_id": TELEGRAM_CHAT_ID, "text": message, "parse_mode": "HTML"},
        timeout=15,
    )
    resp.raise_for_status()
    print("[Telegram] Išsiųsta ✓")


def send_email(subject: str, body_html: str):
    msg = MIMEMultipart("alternative")
    msg["Subject"] = subject
    msg["From"]    = GMAIL_USER
    msg["To"]      = NOTIFY_EMAIL
    msg.attach(MIMEText(body_html, "html"))
    with smtplib.SMTP_SSL("smtp.gmail.com", 465) as server:
        server.login(GMAIL_USER, GMAIL_APP_PASS)
        server.sendmail(GMAIL_USER, NOTIFY_EMAIL, msg.as_string())
    print(f"[Gmail] Išsiųsta į {NOTIFY_EMAIL} ✓")


def main():
    now = datetime.now(timezone.utc)
    date_str = now.strftime("%Y-%m-%d")
    print(f"\n{'='*55}")
    print(f" PAV Monitoringas — {now.strftime('%Y-%m-%d %H:%M UTC')}")
    print(f"{'='*55}\n")

    print("Gaunami duomenys iš Google Sheets...")
    try:
        rows, _ = fetch_csv()
    except Exception as e:
        print(f"[KLAIDA] Nepavyko gauti CSV: {e}")
        return
    print(f"  Iš viso duomenų eilučių: {len(rows)}")

    wind_rows = find_wind_rows(rows)
    print(f"  Vėjo elektrinių įrašų: {len(wind_rows)}")
    for r in wind_rows:
        print(f"    • {get_col(r, 'pavadinimas')}")

    previous, file_existed = load_previous()

    if not file_existed:
        keys = [make_key(r) for r in wind_rows]
        save_snapshot(keys)
        print(f"\nPirmas paleidimas – išsaugota {len(keys)} įrašų.")
        try:
            send_telegram(
                f"🌬️ <b>PAV monitoringas paleistas</b>\n\n"
                f"📊 Šiuo metu lentelėje: {len(wind_rows)} vėjo elektrinių projektų\n"
                f"📅 Data: {date_str}\n\n"
                f"Nuo rytojaus gausite pranešimus kai atsiras nauji įrašai."
            )
        except Exception as e:
            print(f"[Telegram] Klaida: {e}")
        return

    new_rows = [r for r in wind_rows if make_key(r) not in previous]
    save_snapshot([make_key(r) for r in wind_rows])
    print("Snapshot išsaugotas.")

    if not new_rows:
        print("\n✅ Naujų vėjo elektrinių įrašų nerasta.")
        return

    print(f"\n⚠ Rasta {len(new_rows)} naujų įrašų!")

    try:
        send_telegram(build_telegram_message(new_rows, date_str))
    except Exception as e:
        print(f"[Telegram] Klaida: {e}")

    try:
        send_email(
            f"🌬️ PAV — naujas vėjo elektrinių projektas — {date_str}",
            build_email_html(new_rows, date_str),
        )
    except Exception as e:
        print(f"[Gmail] Klaida: {e}")


if __name__ == "__main__":
    main()
