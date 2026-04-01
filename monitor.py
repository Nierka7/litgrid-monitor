"""
Litgrid AEI Pralaidumų Monitoringas
=====================================
Gauna duomenis iš Litgrid ArcGIS API (ElektrosPerdavimasAEI),
palygina su vakar, siunčia pranešimus per Telegram ir Gmail.
"""

import os
import json
import smtplib
import requests
from datetime import datetime, timezone
from email.mime.multipart import MIMEMultipart
from email.mime.text import MIMEText
from pathlib import Path

# ─── Konfigūracija (iš GitHub Secrets) ────────────────────────────────────────
TELEGRAM_TOKEN   = os.environ["TELEGRAM_TOKEN"]
TELEGRAM_CHAT_ID = os.environ["TELEGRAM_CHAT_ID"]
GMAIL_USER       = os.environ["GMAIL_USER"]
GMAIL_APP_PASS   = os.environ["GMAIL_APP_PASS"]
NOTIFY_EMAIL     = os.environ.get("NOTIFY_EMAIL", GMAIL_USER)

DATA_FILE = Path("data/previous.json")

# ─── Litgrid ArcGIS API ────────────────────────────────────────────────────────
API_URL = (
    "https://services-eu1.arcgis.com/NDrrY0T7kE7A7pU0/ArcGIS/rest/services"
    "/ElektrosPerdavimasAEI/FeatureServer/10/query"
)

def fetch_data() -> list[dict]:
    """Gauna visus įrašus iš Litgrid ArcGIS API."""
    params = {
        "where": "metai=2026",
        "outFields": "*",
        "f": "pjson",
    }
    resp = requests.get(API_URL, params=params, timeout=30)
    resp.raise_for_status()
    data = resp.json()

    if "features" not in data:
        raise ValueError(f"Netikėtas API atsakymas: {data}")

    return [feature["attributes"] for feature in data["features"]]


def snapshot(records: list[dict]) -> dict:
    """
    Paverčia sąrašą į žodyną pagal unikalų identifikatorių.
    Pašalina laukus su laiko žymomis (jos keičiasi visada).
    """
    result = {}
    for rec in records:
        # Randame geriausią raktą identifikavimui
        key = (
            rec.get("OBJECTID")
            or rec.get("objectid")
            or rec.get("FID")
            or str(rec)
        )
        # Filtruojame laukus kurie keičiasi nesvariai (datos, null)
        filtered = {
            k: v for k, v in rec.items()
            if v is not None and k.upper() not in ("SHAPE", "GLOBALID")
        }
        result[str(key)] = filtered
    return result


def compare(old: dict, new: dict) -> list[str]:
    """Grąžina sąrašą pakeitimų aprašymų."""
    changes = []

    old_keys = set(old.keys())
    new_keys = set(new.keys())

    # Nauji įrašai
    for key in new_keys - old_keys:
        rec = new[key]
        name = rec.get("PAVADINIMAS") or rec.get("NAME") or rec.get("ZONA") or f"ID {key}"
        changes.append(f"🆕 NAUJAS įrašas: <b>{name}</b>")

    # Išnykę įrašai
    for key in old_keys - new_keys:
        rec = old[key]
        name = rec.get("PAVADINIMAS") or rec.get("NAME") or rec.get("ZONA") or f"ID {key}"
        changes.append(f"❌ PAŠALINTAS įrašas: <b>{name}</b>")

    # Pasikeitę įrašai
    for key in old_keys & new_keys:
        old_rec = old[key]
        new_rec = new[key]
        diffs = []
        all_keys = set(old_rec.keys()) | set(new_rec.keys())
        for field in sorted(all_keys):
            ov = old_rec.get(field)
            nv = new_rec.get(field)
            if ov != nv:
                diffs.append(f"    • {field}: {ov} → {nv}")
        if diffs:
            name = new_rec.get("PAVADINIMAS") or new_rec.get("NAME") or new_rec.get("ZONA") or f"ID {key}"
            changes.append(f"📝 <b>{name}</b> pasikeitė:\n" + "\n".join(diffs))

    return changes


# ─── Duomenų saugojimas ────────────────────────────────────────────────────────
def load_previous() -> dict:
    if DATA_FILE.exists():
        with open(DATA_FILE) as f:
            return json.load(f)
    return {}


def save_snapshot(data: dict):
    DATA_FILE.parent.mkdir(exist_ok=True)
    with open(DATA_FILE, "w") as f:
        json.dump(data, f, indent=2, ensure_ascii=False)


# ─── Pranešimai ────────────────────────────────────────────────────────────────
def send_telegram(message: str):
    url = f"https://api.telegram.org/bot{TELEGRAM_TOKEN}/sendMessage"
    payload = {
        "chat_id": TELEGRAM_CHAT_ID,
        "text": message,
        "parse_mode": "HTML",
    }
    resp = requests.post(url, json=payload, timeout=15)
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


# ─── Pagrindinis ──────────────────────────────────────────────────────────────
def main():
    now = datetime.now(timezone.utc)
    print(f"\n{'='*55}")
    print(f" Litgrid AEI Monitoringas — {now.strftime('%Y-%m-%d %H:%M UTC')}")
    print(f"{'='*55}\n")

    # 1. Gauti duomenis
    print("Gaunami duomenys iš Litgrid API...")
    records = fetch_data()
    print(f"  Rasta įrašų: {len(records)}")

    # 2. Paruošti snapshot
    current = snapshot(records)

    # 3. Palyginti su praėjusiu
    previous = load_previous()

    if not previous:
        print("\nPirmas paleidimas – nėra su kuo lyginti.")
        print("Išsaugomas pradinis snapshot. Rytoj bus lyginama.")
        save_snapshot(current)
        # Vis tiek siunčiame info pranešimą apie pradinį paleidimą
        msg = (
            f"⚡ <b>Litgrid monitoringas paleistas</b>\n\n"
            f"📊 Stebimi įrašai: {len(current)}\n"
            f"📅 Data: {now.strftime('%Y-%m-%d')}\n\n"
            f"Nuo rytojaus gausite pranešimus kai duomenys pasikeičia."
        )
        try:
            send_telegram(msg)
        except Exception as e:
            print(f"[Telegram] Klaida: {e}")
        return

    # 4. Rasti pakeitimus
    print("\nLyginama su ankstesniais duomenimis...")
    changes = compare(previous, current)

    # 5. Išsaugoti naują snapshot
    save_snapshot(current)
    print(f"Snapshot išsaugotas ({len(current)} įrašai).")

    # 6. Siųsti pranešimus
    if not changes:
        print("\n✅ Pakeitimų nerasta. Pranešimų nesiųsti.")
        return

    print(f"\n⚠ Rasta pakeitimų: {len(changes)}")

    date_str = now.strftime("%Y-%m-%d")
    lines = [
        f"⚡ <b>Litgrid AEI pralaidumų pokyčiai</b>",
        f"📅 {date_str} | Pakeitimų: {len(changes)}\n",
    ] + changes + [
        f"\n<i>Šaltinis: Litgrid ElektrosPerdavimasAEI API</i>",
    ]
    message = "\n".join(lines)

    try:
        send_telegram(message)
    except Exception as e:
        print(f"[Telegram] Klaida: {e}")

    try:
        html = f"""
        <html><body style="font-family:Arial,sans-serif;max-width:650px;margin:auto;padding:20px;">
        <h2 style="color:#1a5276;border-bottom:2px solid #1a5276;padding-bottom:8px;">
          ⚡ Litgrid AEI Pralaidumų Monitoringas
        </h2>
        <p><b>Data:</b> {date_str} &nbsp;|&nbsp; <b>Pakeitimų:</b> {len(changes)}</p>
        <hr style="border:none;border-top:1px solid #eee;"/>
        <div style="line-height:1.8;">
          {'<br/>'.join(l.replace('<b>','<strong>').replace('</b>','</strong>') for l in lines[2:])}
        </div>
        <hr style="border:none;border-top:1px solid #eee;margin-top:20px;"/>
        <small style="color:#888;">Automatinis pranešimas | Litgrid ElektrosPerdavimasAEI</small>
        </body></html>
        """
        send_email(f"⚡ Litgrid pokyčiai — {date_str} ({len(changes)} pakeitimų)", html)
    except Exception as e:
        print(f"[Gmail] Klaida: {e}")


if __name__ == "__main__":
    main()
