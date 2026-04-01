"""
Litgrid AEI Pralaidumų Monitoringas
=====================================
Gauna duomenis iš Litgrid ArcGIS API (ElektrosPerdavimasAEI),
saugo ir lygina duomenis pagal ZONA,
siunčia pranešimus su pokyčiais per Telegram ir Gmail.
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

# ─── Stebimi laukai ir jų lietuviški pavadinimai ───────────────────────────────
# Skaitiniai laukai – rodomas pokytis (+/-)
NUMERIC_FIELDS = {
    "Laisva_prijungimo_galia_VE":      "Laisva prijungimo galia VE",
    "Laisva_prijungimo_galia_SE":      "Laisva prijungimo galia SE",
    "Rezer_ESO_tinklo_galia_VE":       "Rezerv. ESO tinklo galia VE",
    "Rezer_ESO_tinklo_galia_SE":       "Rezerv. ESO tinklo galia SE",
    "Rezer_VE_tinklo_galia_LIT_ESO":   "Rezerv. VE tinklo galia LIT/ESO",
    "Rezer_SE_tinklo_galia_LIT_ESO":   "Rezerv. SE tinklo galia LIT/ESO",
    "Zonos_pralaidumas":               "Zonos pralaidumas",
    "Laisva_galia_kaupikliams":        "Laisva galia kaupikliams",
    "Rezervuota_galia_kaupikliams":    "Rezervuota galia kaupikliams",
    "Atributas_12":                    "Atributas 12",
    "Rez_prij_galia_LITGRID_kaup":     "Rez. prijungimo galia LITGRID kaup.",
}

# Tekstinis laukas – pranešimas jei atsirado arba dingo turinys
TEXT_FIELDS = {
    "Papildoma_informacija": "Papildoma informacija",
}

# ─── Litgrid ArcGIS API ────────────────────────────────────────────────────────
API_URL = (
    "https://services-eu1.arcgis.com/NDrrY0T7kE7A7pU0/ArcGIS/rest/services"
    "/ElektrosPerdavimasAEI/FeatureServer/10/query"
)

def fetch_data() -> list[dict]:
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


# ─── Snapshot: saugome pagal ZONA ─────────────────────────────────────────────
def to_snapshot(records: list[dict]) -> dict:
    """
    Grąžina žodyną: { "1": {...stebimi laukai...}, "2": {...}, ... }
    Raktas – ZONA numeris (kaip string).
    """
    result = {}
    for rec in records:
        zona = rec.get("ZONA")
        if zona is None:
            continue
        key = str(zona)
        entry = {}
        for field in NUMERIC_FIELDS:
            entry[field] = rec.get(field)  # gali būti None
        for field in TEXT_FIELDS:
            raw = rec.get(field)
            # Normalizuojame: tuščia string = None
            entry[field] = raw.strip() if isinstance(raw, str) and raw.strip() else None
        result[key] = entry
    return result


# ─── Palyginimas ──────────────────────────────────────────────────────────────
def compare(old: dict, new: dict) -> list[dict]:
    """
    Grąžina sąrašą pakeitimų.
    Kiekvienas elementas: { "zona": "3", "diffs": ["...", ...] }
    """
    changes = []

    old_zones = set(old.keys())
    new_zones = set(new.keys())

    # Naujos zonos
    for z in sorted(new_zones - old_zones, key=int):
        changes.append({
            "zona": z,
            "diffs": ["🆕 Nauja zona atsirado duomenyse"],
        })

    # Dingusios zonos
    for z in sorted(old_zones - new_zones, key=int):
        changes.append({
            "zona": z,
            "diffs": ["❌ Zona dingo iš duomenų"],
        })

    # Esamos zonos – lyginame laukus
    for z in sorted(old_zones & new_zones, key=int):
        old_rec = old[z]
        new_rec = new[z]
        diffs = []

        # Skaitiniai laukai – rodome pokytį
        for field, label in NUMERIC_FIELDS.items():
            ov = old_rec.get(field)
            nv = new_rec.get(field)
            if ov == nv:
                continue
            if ov is None:
                diffs.append(f"  • {label}: (nebuvo) → {nv} MW")
            elif nv is None:
                diffs.append(f"  • {label}: {ov} MW → (nėra duomenų)")
            else:
                delta = nv - ov
                sign = "+" if delta > 0 else ""
                arrow = "📈" if delta > 0 else "📉"
                diffs.append(
                    f"  {arrow} {label}: {ov} → {nv} ({sign}{delta:.0f} MW)"
                )

        # Tekstinis laukas – tik ar atsirado / dingo turinys
        for field, label in TEXT_FIELDS.items():
            ov = old_rec.get(field)
            nv = new_rec.get(field)
            if ov == nv:
                continue
            if not ov and nv:
                diffs.append(f"  📌 {label}: atsirado → \"{nv}\"")
            elif ov and not nv:
                diffs.append(f"  🗑 {label}: dingo (buvo: \"{ov}\")")
            else:
                diffs.append(f"  📝 {label}: \"{ov}\" → \"{nv}\"")

        if diffs:
            changes.append({"zona": z, "diffs": diffs})

    return changes


# ─── Duomenų saugojimas ────────────────────────────────────────────────────────
def load_previous() -> dict:
    if DATA_FILE.exists():
        with open(DATA_FILE, encoding="utf-8") as f:
            return json.load(f)
    return {}


def save_snapshot(data: dict):
    DATA_FILE.parent.mkdir(exist_ok=True)
    with open(DATA_FILE, "w", encoding="utf-8") as f:
        json.dump(data, f, indent=2, ensure_ascii=False)


# ─── Pranešimų formatavimas ────────────────────────────────────────────────────
def build_telegram_message(changes: list[dict], date_str: str) -> str:
    lines = [
        f"⚡ <b>Litgrid AEI — zonų pokyčiai</b>",
        f"📅 {date_str} | Pasikeitė zonų: {len(changes)}\n",
    ]
    for ch in changes:
        lines.append(f"<b>▸ Zona {ch['zona']}</b>")
        lines.extend(ch["diffs"])
        lines.append("")
    lines.append("<i>Šaltinis: Litgrid ElektrosPerdavimasAEI</i>")
    msg = "\n".join(lines)
    # Telegram riboja žinutę iki 4096 simbolių
    if len(msg) > 4000:
        msg = msg[:3990] + "\n\n<i>... (pranešimas sutrumpintas)</i>"
    return msg


def build_email_html(changes: list[dict], date_str: str) -> str:
    rows = ""
    for ch in changes:
        diffs_html = "<br/>".join(
            d.replace("<b>", "<strong>").replace("</b>", "</strong>")
            for d in ch["diffs"]
        )
        rows += f"""
        <tr>
          <td style="padding:10px 14px;font-weight:bold;white-space:nowrap;
                     border-bottom:1px solid #eee;vertical-align:top;color:#1a5276;">
            Zona {ch['zona']}
          </td>
          <td style="padding:10px 14px;border-bottom:1px solid #eee;
                     font-family:monospace;font-size:13px;line-height:1.8;">
            {diffs_html}
          </td>
        </tr>"""

    return f"""
    <html><body style="font-family:Arial,sans-serif;max-width:700px;margin:auto;padding:20px;">
      <h2 style="color:#1a5276;border-bottom:2px solid #1a5276;padding-bottom:8px;">
        ⚡ Litgrid AEI — zonų pralaidumų pokyčiai
      </h2>
      <p><b>Data:</b> {date_str} &nbsp;|&nbsp;
         <b>Pasikeitė zonų:</b> {len(changes)}</p>
      <table style="width:100%;border-collapse:collapse;margin-top:16px;">
        <thead>
          <tr style="background:#1a5276;color:#fff;">
            <th style="padding:10px 14px;text-align:left;">Zona</th>
            <th style="padding:10px 14px;text-align:left;">Pakeitimai</th>
          </tr>
        </thead>
        <tbody>{rows}</tbody>
      </table>
      <hr style="margin-top:24px;border:none;border-top:1px solid #eee;"/>
      <small style="color:#999;">Automatinis pranešimas | Litgrid ElektrosPerdavimasAEI</small>
    </body></html>
    """


# ─── Pranešimų siuntimas ───────────────────────────────────────────────────────
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


# ─── Pagrindinis ──────────────────────────────────────────────────────────────
def main():
    now = datetime.now(timezone.utc)
    date_str = now.strftime("%Y-%m-%d")
    print(f"\n{'='*55}")
    print(f" Litgrid AEI Monitoringas — {now.strftime('%Y-%m-%d %H:%M UTC')}")
    print(f"{'='*55}\n")

    # 1. Gauti duomenis
    print("Gaunami duomenys iš Litgrid API...")
    records = fetch_data()
    print(f"  Rasta įrašų: {len(records)}")

    # 2. Paruošti snapshot (pagal ZONA)
    current = to_snapshot(records)
    print(f"  Unikalių zonų: {len(current)}")

    # 3. Palyginti su praėjusiu
    previous = load_previous()

    if not previous:
        print("\nPirmas paleidimas – išsaugomas pradinis snapshot.")
        save_snapshot(current)
        try:
            send_telegram(
                f"⚡ <b>Litgrid monitoringas paleistas</b>\n\n"
                f"📊 Stebimos zonos: {', '.join(sorted(current.keys(), key=int))}\n"
                f"📅 Data: {date_str}\n\n"
                f"Nuo rytojaus gausite pranešimus kai duomenys pasikeičia."
            )
        except Exception as e:
            print(f"[Telegram] Klaida: {e}")
        return

    # 4. Rasti pakeitimus
    print("\nLyginama su ankstesniais duomenimis...")
    changes = compare(previous, current)

    # 5. Išsaugoti naują snapshot
    save_snapshot(current)
    print("Snapshot išsaugotas.")

    # 6. Siųsti pranešimus
    if not changes:
        print("\n✅ Pakeitimų nerasta. Pranešimų nesiųsti.")
        return

    print(f"\n⚠ Pasikeitė {len(changes)} zona(-ų):")
    for ch in changes:
        print(f"  Zona {ch['zona']}: {len(ch['diffs'])} pakeitimas(-ai)")

    try:
        send_telegram(build_telegram_message(changes, date_str))
    except Exception as e:
        print(f"[Telegram] Klaida: {e}")

    try:
        send_email(
            f"⚡ Litgrid zonų pokyčiai — {date_str} ({len(changes)} zonos)",
            build_email_html(changes, date_str),
        )
    except Exception as e:
        print(f"[Gmail] Klaida: {e}")


if __name__ == "__main__":
    main()
