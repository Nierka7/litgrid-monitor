"""
Litgrid AEI Pralaidumų Monitoringas
=====================================
Gauna duomenis iš Litgrid ArcGIS API (ElektrosPerdavimasAEI),
saugo ir lygina duomenis pagal ZONA,
siunčia pranešimus su pokyčiais per Telegram ir Gmail.
"""

import os
import json
import html as _html
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

# ─── Zonų pavadinimai ─────────────────────────────────────────────────────────
ZONE_NAMES = {
    0: "Pavienės TP",
    1: "Klaipėda-Rietavas-Kelmė-Šiauliai",
    2: "Kelmė-Raseiniai-Jurbarkas",
    3: "Klaipėda-Šilutė-Pagėgiai",
    4: "Pagėgiai-Tauragė-Jurbarkas",
    5: "Jurbarkas-Šakiai-Kybartai-Marijampolė",
    6: "Jurbarkas-Seredžius",
    7: "Klaipėda-Palanga-Skuodas-Mažeikiai",
    8: "Telšiai-Mažeikiai-N.Akmenė",
    9: "N.Akmenė-Joniškis-Šiauliai-Kuršėnai",
    10: "Klaipėda-Kretinga-Plungė-Telšiai",
    11: "Telšiai-Šiauliai",
    12: "Šiauliai-Pakruojis-Panevėžys",
    13: "Šiauliai-Radviliškis-Panevėžys",
    14: "Panevėžys-Biržai",
    15: "Biržai-Rokiškis-Utena",
    16: "Panevėžys-Kupiškis-Rokiškis",
    17: "Panevėžys-Velžys",
    18: "Panevėžys (18)",
    19: "Panevėžys (19)",
    20: "Panevėžys-Kėdainiai",
    21: "Krekenava-Gudžiūnai",
    22: "Kėdainiai-Kaunas",
    23: "Kėdainiai-Jonava",
    24: "Kaunas-Jonava (24)",
    25: "Kaunas-Jonava (25)",
    26: "Jonava-Ukmergė",
    27: "Ukmergė-Utena",
    28: "Utena-Molėtai-Širvintos-Nemenčinė",
    29: "Anykščiai-Utena-Švenčionys-Ignalina",
    30: "Dirvupiai",
    31: "Zarasai-Visaginas",
    32: "Visaginas-Ignalina",
    33: "Švenčionėliai-Pabradė-Nemenčinė",
    34: "Kaunas (34)",
    35: "Kaunas-Kaišiadorys",
    36: "Kaišiadorys-Kruonis-Elektrėnai-Vilnius",
    37: "Kauno HE-Kruonio HAE",
    38: "Kauno HE-Kazlų rūda-Marijampolė-Prienai-Alytus",
    39: "Kruonis-Prienai-Alytus",
    40: "Alytus-Šeštokai",
    41: "Alytus-Vilnius-Šalčininkai",
    42: "Vilnius-Jašiūnai",
    43: "Vilnia-Kalveliai",
    44: "Vilnius-Nemenčinė",
    45: "Vilnius-Vilnia2",
    46: "Pagiriai-VE2",
    47: "Pagiriai-Grigiškės",
    48: "Zujūnai-Nemenčinė",
    49: "Grigiškės-Vilkpėdė",
    50: "Buividiškės-Nemenčinė",
    51: "Šeškinė-VE3",
    52: "Vilnius-VE3II",
    53: "Vilnius-VE3IV",
    54: "Kino studija-Vilnia",
    55: "Klaipėda-Marios",
    56: "Klaipėda-Atš. Gedminai II",
    57: "Klaipėda-Danė I",
    58: "Šiauliai-Gubernija I ir II",
    59: "Alytus-Griškonys I",
    60: "Alytus-Putinai I ir II",
    61: "Telšiai-Tausalas I",
    62: "Panevėžys-Ekranas I",
    63: "Panevėžys-Ekranas II",
    64: "Kaunas-Murava I ir II",
    65: "Vilnius-Vaidotai II",
    66: "Klaipėda (66)",
    67: "Klaipėda-Bitėnai (330 kV)",
    68: "Klaipėda-Joniškis (330 kV)",
    69: "Klaipėda-Bitėnai (69)",
    70: "Elektrėnai-Panevėžys (330 kV)",
    71: "Utena-Visaginas (330 kV)",
    72: "Kaunas-Kruonio HAE (330 kV)",
    73: "Elektrėnai-Alytus (330 kV)",
    74: "Elektrėnai-Nemenčinė (330 kV)",
    75: "Jurbarkas-Kaunas-Marijampolė (330 kV)",
    76: "Kaunas-Šiauliai (330 kV)",
    77: "Biržai-Pasvalys-Utena-Molėtai-Vilnius (330 kV)",
    78: "Klaipėda (330 kV)",
    79: "Bitėnai",
    80: "Telšiai (330 kV)",
    81: "Jurbarkas (330 kV)",
    82: "Panevėžys (330 kV)",
    83: "Utena (330 kV)",
    84: "Šiauliai (330 kV)",
    85: "Kaunas (330 kV)",
    86: "AEI atominė (330 kV)",
    87: "Neris (330 kV)",
    88: "Vilnius (330 kV)",
    89: "Alytus (330 kV)",
    90: "Jonava (330 kV)",
    91: "Kruonio HAE (330 kV)",
    92: "Kauno HE-Kruonio HAE1",
    93: "Velžys-Vašuokėnai",
    94: "Mūša perspektyvinė (330 kV)",
    95: "Darbėnai-Perspektyvinė (330 kV)",
    96: "Demontuojama (96)",
    97: "Demontuojama (97)",
    98: "Bitėnai 330 kV",
    99: "Panevėžys 330 kV",
    100: "Utena 330 kV",
    101: "Kaunas 330 kV",
    102: "IAE 330 kV",
    103: "Neris 330 kV",
    104: "Vilnius 330 kV",
    105: "Alytus 330 kV",
    106: "Kruonio HAE 330 kV",
    107: "Lietuvos E 330 kV",
}

def zone_label(zona: str) -> str:
    """Grąžina 'Zona 3 – Klaipėda-Šilutė-Pagėgiai' arba 'Zona 3' jei pavadinimo nėra."""
    name = ZONE_NAMES.get(int(zona))
    return f"Zona {zona} – {name}" if name else f"Zona {zona}"


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
            entry[field] = rec.get(field)
        for field in TEXT_FIELDS:
            raw = rec.get(field)
            entry[field] = raw.strip() if isinstance(raw, str) and raw.strip() else None
        result[key] = entry
    return result


# ─── Palyginimas ──────────────────────────────────────────────────────────────
def compare(old: dict, new: dict) -> list[dict]:
    """
    Grąžina sąrašą pakeitimų.
    Kiekvienas elementas: { "zona": "3", "label": "Zona 3 – ...", "diffs": [...] }

    Teksto reikšmės yra HTML-escaped, kad Telegram HTML parse_mode veiktų
    net jei API grąžina specialius simbolius (<, >, &).
    """
    changes = []

    old_zones = set(old.keys())
    new_zones = set(new.keys())

    for z in sorted(new_zones - old_zones, key=int):
        changes.append({"zona": z, "label": zone_label(z), "diffs": ["🆕 Nauja zona atsirado duomenyse"]})

    for z in sorted(old_zones - new_zones, key=int):
        changes.append({"zona": z, "label": zone_label(z), "diffs": ["❌ Zona dingo iš duomenų"]})

    for z in sorted(old_zones & new_zones, key=int):
        old_rec = old[z]
        new_rec = new[z]
        diffs = []

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
                diffs.append(f"  {arrow} {label}: {ov} → {nv} ({sign}{delta:.0f} MW)")

        for field, label in TEXT_FIELDS.items():
            ov = old_rec.get(field)
            nv = new_rec.get(field)
            if ov == nv:
                continue
            # FIX: HTML-escape teksto reikšmes, nes Telegram naudoja parse_mode HTML.
            # Jei API grąžina simbolius kaip <, >, &, Telegram atmes pranešimą.
            ov_safe = _html.escape(ov) if ov else ov
            nv_safe = _html.escape(nv) if nv else nv
            if not ov and nv:
                diffs.append(f"  📌 {label}: atsirado → \"{nv_safe}\"")
            elif ov and not nv:
                diffs.append(f"  🗑 {label}: dingo (buvo: \"{ov_safe}\")")
            else:
                diffs.append(f"  📝 {label}: \"{ov_safe}\" → \"{nv_safe}\"")

        if diffs:
            changes.append({"zona": z, "label": zone_label(z), "diffs": diffs})

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
        lines.append(f"<b>▸ {ch['label']}</b>")
        lines.extend(ch["diffs"])
        lines.append("")
    lines.append("<i>Šaltinis: Litgrid ElektrosPerdavimasAEI</i>")
    msg = "\n".join(lines)
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
            {ch['label']}
          </td>
          <td style="padding:10px 14px;border-bottom:1px solid #eee;
                     font-family:monospace;font-size:13px;line-height:1.8;">
            {diffs_html}
          </td>
        </tr>"""

    return f"""
    <html><body style="font-family:Arial,sans-serif;max-width:750px;margin:auto;padding:20px;">
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
    import re

    resp = requests.post(
        f"https://api.telegram.org/bot{TELEGRAM_TOKEN}/sendMessage",
        json={"chat_id": TELEGRAM_CHAT_ID, "text": message, "parse_mode": "HTML"},
        timeout=15,
    )

    if resp.status_code == 400:
        # Telegram atmetė HTML – parodome tikslią klaidą ir siunčiame be formatavimo
        err = resp.json().get("description", resp.text)
        print(f"[Telegram] HTML klaida: {err}")
        plain = re.sub(r"<[^>]+>", "", message)
        resp = requests.post(
            f"https://api.telegram.org/bot{TELEGRAM_TOKEN}/sendMessage",
            json={"chat_id": TELEGRAM_CHAT_ID, "text": plain},
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

    print("Gaunami duomenys iš Litgrid API...")
    records = fetch_data()
    print(f"  Rasta įrašų: {len(records)}")

    current = to_snapshot(records)
    print(f"  Unikalių zonų: {len(current)}")

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

    print("\nLyginama su ankstesniais duomenimis...")
    changes = compare(previous, current)

    save_snapshot(current)
    print("Snapshot išsaugotas.")

    if not changes:
        print("\n✅ Pakeitimų nerasta. Pranešimų nesiųsti.")
        return

    print(f"\n⚠ Pasikeitė {len(changes)} zona(-ų):")
    for ch in changes:
        print(f"  {ch['label']}: {len(ch['diffs'])} pakeitimas(-ai)")

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
