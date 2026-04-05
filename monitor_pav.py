"""
PAV (Planuojamos ūkinės veiklos) Monitoringas
==============================================
Kiekvieną dieną tikrina ar Google Sheets lentelėje neatsirado
naujų eilučių, kur "PŪV pavadinimas" turi žodžius "vėjo elektrinių".
Jei atsirado — siunčia pranešimą į Telegram ir Gmail.
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

# ─── Konfigūracija (iš GitHub Secrets – tie patys kaip monitor.py) ────────────
TELEGRAM_TOKEN   = os.environ["TELEGRAM_TOKEN"]
TELEGRAM_CHAT_ID = os.environ["TELEGRAM_CHAT_ID"]
GMAIL_USER       = os.environ["GMAIL_USER"]
GMAIL_APP_PASS   = os.environ["GMAIL_APP_PASS"]
NOTIFY_EMAIL     = os.environ.get("NOTIFY_EMAIL", GMAIL_USER)

DATA_FILE = Path("data/pav_previous.json")

# ─── Google Sheets eksporto URL (viešas lapas) ────────────────────────────────
SHEET_ID  = "1r5q6rPjSL6eF2c08LfIaym5t3wwL9nZ-"
GID       = "1337314935"
CSV_URL   = f"https://docs.google.com/spreadsheets/d/{SHEET_ID}/export?format=csv&gid={GID}"

# ─── Stulpelių pavadinimai (tiksliai kaip lentelėje) ─────────────────────────
COL_PAVADINIMAS  = "PŪV pavadinimas"
COL_ORGANIZATORIUS = "PŪV organizatorius"
COL_DATA         = "Paskelbimo data"
COL_VIETA        = "PŪV vieta"

SEARCH_KEYWORD   = "vėjo elektrinių"
# Atsarginė paieška be diakritikų — veikia net jei enkodingo problema
SEARCH_KEYWORD_ASCII = "vejo elektrini"


# ─── Duomenų gavimas ──────────────────────────────────────────────────────────
def fetch_csv() -> list[dict]:
    """Parsisiunčia CSV iš Google Sheets ir grąžina eilučių sąrašą."""
    resp = requests.get(CSV_URL, timeout=30)
    resp.raise_for_status()

    # Bandome enkodingus iš eilės kol tekstas atrodo teisingas
    raw = resp.content
    content = None
    for enc in ("utf-8-sig", "utf-8", "windows-1257", "iso-8859-13", "cp1252"):
        try:
            decoded = raw.decode(enc)
            # Patikriname ar lietuviški simboliai atpažinti teisingai
            if "vėjo" in decoded.lower() or "ė" in decoded or "ž" in decoded or "ū" in decoded:
                content = decoded
                print(f"  Enkodingo aptikimas: {enc} ✓")
                break
            content = decoded  # Priimame net jei nerasta lietuviškų simbolių
        except (UnicodeDecodeError, LookupError):
            continue

    if content is None:
        content = raw.decode("utf-8-sig", errors="replace")
        print("  Įspėjimas: nepavyko tiksliai nustatyti enkodingo, naudojamas UTF-8 su klaidų pakeitimu")

    reader = csv.DictReader(io.StringIO(content))
    rows = []
    for row in reader:
        # Pašaliname tarpus iš stulpelių pavadinimų (kartais būna papildomi)
        clean = {k.strip(): v.strip() for k, v in row.items() if k}
        rows.append(clean)
    return rows


def find_wind_rows(rows: list[dict]) -> list[dict]:
    """Grąžina tik tas eilutes, kur PŪV pavadinimas turi 'vėjo elektrinių'."""
    result = []
    for row in rows:
        pav = row.get(COL_PAVADINIMAS, "").lower()
        if SEARCH_KEYWORD.lower() in pav or SEARCH_KEYWORD_ASCII in pav:
            result.append(row)
    return result


# ─── Atminties failas ─────────────────────────────────────────────────────────
def make_key(row: dict) -> str:
    """
    Unikalus raktas eilutei – derinys iš pavadinimo + datos.
    Jei data tuščia, naudojame tik pavadinimą.
    """
    pav  = row.get(COL_PAVADINIMAS, "").strip()
    data = row.get(COL_DATA, "").strip()
    return f"{pav}||{data}"


def load_previous() -> dict:
    if DATA_FILE.exists():
        with open(DATA_FILE, encoding="utf-8") as f:
            return json.load(f)
    return {}


def save_snapshot(keys: list[str]):
    DATA_FILE.parent.mkdir(exist_ok=True)
    snapshot = {k: True for k in keys}
    with open(DATA_FILE, "w", encoding="utf-8") as f:
        json.dump(snapshot, f, indent=2, ensure_ascii=False)


# ─── Pranešimų formatavimas ───────────────────────────────────────────────────
def format_row_telegram(row: dict) -> str:
    org   = row.get(COL_ORGANIZATORIUS, "–") or "–"
    data  = row.get(COL_DATA, "–") or "–"
    vieta = row.get(COL_VIETA, "–") or "–"
    pav   = row.get(COL_PAVADINIMAS, "–") or "–"
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
        pav   = row.get(COL_PAVADINIMAS, "–") or "–"
        org   = row.get(COL_ORGANIZATORIUS, "–") or "–"
        data  = row.get(COL_DATA, "–") or "–"
        vieta = row.get(COL_VIETA, "–") or "–"
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
      <p><b>Data:</b> {date_str} &nbsp;|&nbsp;
         <b>Naujų įrašų:</b> {len(new_rows)}</p>
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


# ─── Pranešimų siuntimas ──────────────────────────────────────────────────────
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


# ─── Pagrindinis ─────────────────────────────────────────────────────────────
def main():
    now = datetime.now(timezone.utc)
    date_str = now.strftime("%Y-%m-%d")
    print(f"\n{'='*55}")
    print(f" PAV Monitoringas — {now.strftime('%Y-%m-%d %H:%M UTC')}")
    print(f"{'='*55}\n")

    print("Gaunami duomenys iš Google Sheets...")
    try:
        rows = fetch_csv()
    except Exception as e:
        print(f"[KLAIDA] Nepavyko gauti CSV: {e}")
        return
    print(f"  Iš viso eilučių: {len(rows)}")

    wind_rows = find_wind_rows(rows)
    print(f"  Vėjo elektrinių įrašų: {len(wind_rows)}")

    previous = load_previous()

    if not previous:
        # Pirmas paleidimas – išsaugome viską, pranešimų nesiųsti
        keys = [make_key(r) for r in wind_rows]
        save_snapshot(keys)
        print(f"\nPirmas paleidimas – išsaugota {len(keys)} vėjo elektrinių įrašų.")
        try:
            send_telegram(
                f"🌬️ <b>PAV monitoringas paleistas</b>\n\n"
                f"📊 Šiuo metu stebima: {len(wind_rows)} vėjo elektrinių projektų\n"
                f"📅 Data: {date_str}\n\n"
                f"Nuo rytojaus gausite pranešimus kai atsiras nauji įrašai."
            )
        except Exception as e:
            print(f"[Telegram] Klaida: {e}")
        return

    # Ieškome naujų įrašų
    new_rows = []
    for row in wind_rows:
        key = make_key(row)
        if key not in previous:
            new_rows.append(row)

    # Atnaujiname snapshot (išsaugome VISUS dabartinius)
    all_keys = [make_key(r) for r in wind_rows]
    save_snapshot(all_keys)
    print("Snapshot išsaugotas.")

    if not new_rows:
        print("\n✅ Naujų vėjo elektrinių įrašų nerasta.")
        return

    print(f"\n⚠ Rasta {len(new_rows)} naujų įrašų:")
    for row in new_rows:
        print(f"  • {row.get(COL_PAVADINIMAS, '?')}")

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
