#!/usr/bin/env python3
"""
Tech & Auto Daily Digest — versione GitHub Actions
Le chiavi API vengono lette dalle variabili d'ambiente di GitHub Secrets.
"""

import json
import re
import os
import feedparser
import resend
from datetime import datetime, timezone, timedelta
import pytz
from groq import Groq

# ─────────────────────────────────────────────
# CONFIGURAZIONE — le chiavi vengono da GitHub Secrets
# ─────────────────────────────────────────────
GROQ_API_KEY   = os.environ["GROQ_API_KEY"]
RESEND_API_KEY = os.environ["RESEND_API_KEY"]
FROM_EMAIL     = "onboarding@resend.dev"
TO_EMAIL       = "os.environ["TO_EMAIL"]
TIMEZONE       = "Europe/Rome"
SOURCES_FILE   = "sources.json"

ANALYSIS_PROMPT = """Sei un editor specializzato in tecnologia e automotive che cura una newsletter per un pubblico prevalentemente italiano (75% contatti italiani).

Ti fornisco due liste di articoli delle ultime 24 ore:
- ARTICOLI ITALIANI: da testate italiane o su notizie riguardanti l'Italia
- ARTICOLI INTERNAZIONALI: da testate internazionali

DEFINIZIONI DELLE AREE:
- "Automotive News": notizie generaliste del settore auto — nuovi modelli, strategie aziendali, dati di mercato/vendite, interviste a CEO e manager rilevanti, accordi commerciali, espansioni di mercato.
- "Tecnica Automotive": novità tecniche sui veicoli — nuovi motori, cambi, turbine, sistemi di distribuzione, materiali innovativi, nuove piattaforme, soluzioni ingegneristiche specifiche.
- "EV & Mobilità Elettrica": batterie, infrastruttura di ricarica, nuovi modelli elettrici, normative EV.
- "Guida Autonoma & ADAS": sistemi di assistenza alla guida, robotaxi, software di guida autonoma.
- "AI & Machine Learning": modelli AI, applicazioni industriali, investimenti, ricerca.
- "Auto di Lusso & Supercar": supercar, hypercar, vetture di lusso estremo.
- "Startup & Venture Capital Tech": round di finanziamento, acquisizioni, nuove aziende tech.

DISTRIBUZIONE OBBLIGATORIA su 15 notizie totali:
- Automotive News: 3 notizie (22%)
- EV & Mobilità Elettrica: 3 notizie (18%)
- AI & Machine Learning: 3 notizie (18%)
- Guida Autonoma & ADAS: 2 notizie (15%)
- Tecnica Automotive: 2 notizie (15%)
- Startup & Venture Capital Tech: 1 notizia (7%)
- Auto di Lusso & Supercar: 1 notizia (5%)

REGOLE IMPORTANTI:
1. Almeno il 50% delle notizie deve essere da testate italiane o riguardare il mercato italiano/europeo.
2. Non selezionare mai lo stesso articolo due volte, anche se appare con titoli leggermente diversi.
3. Rispetta la distribuzione per area il più possibile.
4. Privilegia notizie con impatto concreto su business, mercato o innovazione tecnica reale.

Criteri di score (1-10):
- Impatto sul mercato (finanziario/business): fino a +3
- Innovazione tecnologica reale: fino a +3
- Rilevanza Italia/Europa: fino a +2
- Freschezza e fonte autorevole: fino a +2
Penalizza: rumor senza fonti, contenuti promozionali, notizie irrilevanti.

Restituisci SOLO un JSON valido (nessun testo prima o dopo, nessun backtick):
{
  "news": [
    {
      "score": 9,
      "area": "Automotive News",
      "emoji": "🚘",
      "title_it": "Titolo riscritto in italiano (max 12 parole)",
      "title_en": "Titolo originale in inglese",
      "summary_it": "Due righe di sintesi in italiano. Conciso e informativo.",
      "source": "Nome testata",
      "url": "https://url-articolo.com"
    }
  ]
}
"""

AREA_EMOJIS = {
    "Automotive News": "🚘",
    "EV & Mobilità Elettrica": "🔋",
    "Guida Autonoma & ADAS": "🚗",
    "AI & Machine Learning": "🤖",
    "Tecnica Automotive": "🔧",
    "Auto di Lusso & Supercar": "🏎️",
    "Startup & Venture Capital Tech": "🚀"
}


def load_sources():
    with open(SOURCES_FILE, "r", encoding="utf-8") as f:
        data = json.load(f)
    return data["sources"]


def fetch_rss_articles(sources):
    italian = []
    international = []
    cutoff = datetime.now(timezone.utc) - timedelta(hours=24)

    for category, source_list in sources.items():
        for source in source_list:
            try:
                feed = feedparser.parse(source["rss"])
                for entry in feed.entries[:3]:
                    url = entry.get("link", "")
                    published = None
                    if hasattr(entry, "published_parsed") and entry.published_parsed:
                        published = datetime(*entry.published_parsed[:6], tzinfo=timezone.utc)
                    if published is None or published >= cutoff:
                        article = {
                            "source": source["name"],
                            "lingua": source.get("lingua", "EN"),
                            "area_hint": source["area"][0] if source["area"] else "",
                            "title": entry.get("title", ""),
                            "summary": entry.get("summary", "")[:150],
                            "url": url,
                            "published": published.strftime("%d/%m %H:%M") if published else "recente"
                        }
                        if source.get("lingua") == "IT":
                            italian.append(article)
                        else:
                            international.append(article)
            except Exception as e:
                print(f"  ⚠️  Errore RSS {source['name']}: {e}")

    print(f"  📥 Articoli IT: {len(italian)} | Internazionali: {len(international)}")
    return italian, international


def analyze_with_groq(italian, international):
    client = Groq(api_key=GROQ_API_KEY)

    def format_list(articles, label):
        text = f"\n### {label}\n"
        for i, a in enumerate(articles, 1):
            text += f"{i}. [{a['source']}] {a['title']}\n   Area suggerita: {a['area_hint']}\n   Sintesi: {a['summary']}\n   URL: {a['url']}\n   Data: {a['published']}\n"
        return text

    articles_text = format_list(italian, "ARTICOLI ITALIANI") + format_list(international, "ARTICOLI INTERNAZIONALI")

    print("  🤖 Groq sta analizzando gli articoli...")
    response = client.chat.completions.create(
        model="llama-3.3-70b-versatile",
        messages=[
            {"role": "system", "content": "Sei un editor specializzato in tecnologia e automotive. Rispondi SOLO con JSON valido, nessun testo aggiuntivo."},
            {"role": "user", "content": ANALYSIS_PROMPT + "\n\nArticoli da analizzare:" + articles_text}
        ],
        temperature=0.3,
        max_tokens=4000
    )

    raw = response.choices[0].message.content.strip()
    clean = re.sub(r"```json|```", "", raw).strip()
    data = json.loads(clean)
    news = data.get("news", [])

    for item in news:
        if not item.get("emoji"):
            item["emoji"] = AREA_EMOJIS.get(item.get("area", ""), "📰")

    area_count = {}
    for n in news:
        area_count[n.get("area", "?")] = area_count.get(n.get("area", "?"), 0) + 1
    it_sources = [s["source"] for s in italian]
    it_count = sum(1 for n in news if n["source"] in it_sources)
    print(f"  ✅ Notizie selezionate: {len(news)} (italiane: {it_count})")
    for area, count in sorted(area_count.items()):
        print(f"     {AREA_EMOJIS.get(area,'📰')} {area}: {count}")
    return news


def score_to_color(score):
    if score >= 9:
        return "#16a34a"
    elif score >= 7:
        return "#d97706"
    else:
        return "#6b7280"


def build_email_html(news):
    tz = pytz.timezone(TIMEZONE)
    now = datetime.now(tz)
    weekday_it = ["Lunedì","Martedì","Mercoledì","Giovedì","Venerdì","Sabato","Domenica"]
    months_it = ["","Gennaio","Febbraio","Marzo","Aprile","Maggio","Giugno","Luglio","Agosto","Settembre","Ottobre","Novembre","Dicembre"]
    date_str = f"{now.day} {months_it[now.month]} {now.year}"
    day_name = weekday_it[now.weekday()]

    articles_html = ""
    for item in news:
        color = score_to_color(item["score"])
        articles_html += f"""
        <tr>
          <td style="padding:20px 0;border-bottom:1px solid #e5e7eb;">
            <table width="100%" cellpadding="0" cellspacing="0">
              <tr><td>
                <span style="font-size:11px;font-weight:700;text-transform:uppercase;letter-spacing:0.08em;color:#6b7280;">{item['emoji']} {item['area']}</span>
                &nbsp;&nbsp;
                <span style="display:inline-block;background:{color};color:#fff;font-size:11px;font-weight:700;border-radius:20px;padding:2px 9px;vertical-align:middle;">{item['score']}/10</span>
              </td></tr>
              <tr><td style="padding-top:8px;">
                <a href="{item['url']}" style="font-size:17px;font-weight:700;color:#111827;text-decoration:none;line-height:1.4;">{item['title_it']}</a>
              </td></tr>
              <tr><td style="padding-top:3px;font-size:12px;color:#9ca3af;font-style:italic;">{item['title_en']}</td></tr>
              <tr><td style="padding-top:10px;font-size:14px;color:#374151;line-height:1.6;">{item['summary_it']}</td></tr>
              <tr><td style="padding-top:10px;">
                <a href="{item['url']}" style="font-size:12px;color:#4f46e5;font-weight:600;text-decoration:none;">Leggi su {item['source']} →</a>
              </td></tr>
            </table>
          </td>
        </tr>"""

    return f"""<!DOCTYPE html>
<html lang="it">
<head><meta charset="UTF-8"/></head>
<body style="margin:0;padding:0;background:#f3f4f6;font-family:'Helvetica Neue',Arial,sans-serif;">
  <table width="100%" cellpadding="0" cellspacing="0" bgcolor="#f3f4f6">
    <tr><td align="center" style="padding:32px 16px;">
      <table width="620" cellpadding="0" cellspacing="0"
             style="max-width:620px;background:#fff;border-radius:12px;box-shadow:0 1px 4px rgba(0,0,0,0.07);overflow:hidden;">
        <tr><td style="background:linear-gradient(135deg,#111827 0%,#1e3a5f 100%);padding:32px 36px;">
          <p style="margin:0;font-size:11px;font-weight:700;color:#6b7280;letter-spacing:0.12em;text-transform:uppercase;">Daily Digest</p>
          <h1 style="margin:8px 0 0;font-size:24px;font-weight:800;color:#fff;letter-spacing:-0.02em;">Tech &amp; Auto Brief</h1>
          <p style="margin:6px 0 0;font-size:14px;color:#9ca3af;">{day_name}, {date_str} &nbsp;·&nbsp; {len(news)} notizie selezionate</p>
        </td></tr>
        <tr><td style="background:#f9fafb;padding:12px 36px;border-bottom:1px solid #e5e7eb;">
          <span style="font-size:11px;color:#6b7280;">Score: &nbsp;</span>
          <span style="font-size:11px;font-weight:700;color:#16a34a;">● 9–10 Alta</span> &nbsp;&nbsp;
          <span style="font-size:11px;font-weight:700;color:#d97706;">● 7–8 Media</span> &nbsp;&nbsp;
          <span style="font-size:11px;font-weight:700;color:#6b7280;">● 6 Normale</span>
        </td></tr>
        <tr><td style="padding:8px 36px 0;">
          <table width="100%" cellpadding="0" cellspacing="0">{articles_html}</table>
        </td></tr>
        <tr><td style="padding:24px 36px;background:#f9fafb;border-top:1px solid #e5e7eb;text-align:center;">
          <p style="margin:0;font-size:11px;color:#9ca3af;">Generato automaticamente da Groq AI · Fonti verificate · Solo notizie ultime 24h</p>
        </td></tr>
      </table>
    </td></tr>
  </table>
</body></html>"""


def send_email(html_body, num_news):
    tz = pytz.timezone(TIMEZONE)
    now = datetime.now(tz)
    months_it = ["","Gennaio","Febbraio","Marzo","Aprile","Maggio","Giugno","Luglio","Agosto","Settembre","Ottobre","Novembre","Dicembre"]
    date_str = f"{now.day} {months_it[now.month]} {now.year}"
    resend.api_key = RESEND_API_KEY
    response = resend.Emails.send({
        "from":    FROM_EMAIL,
        "to":      [TO_EMAIL],
        "subject": f"📰 Tech & Auto Digest — {date_str} ({num_news} notizie)",
        "html":    html_body,
    })
    print(f"  ✅ Email inviata a {TO_EMAIL} [id: {response['id']}]")


def main():
    print("=" * 50)
    print("  Tech & Auto Daily Digest")
    tz = pytz.timezone(TIMEZONE)
    print(f"  {datetime.now(tz).strftime('%d/%m/%Y %H:%M')} — Europe/Rome")
    print("=" * 50)

    print("\n[1/3] Lettura feed RSS...")
    sources = load_sources()
    italian, international = fetch_rss_articles(sources)

    print("\n[2/3] Analisi con Groq AI...")
    news = analyze_with_groq(italian, international)

    print("\n[3/3] Invio email...")
    html = build_email_html(news)
    send_email(html, len(news))

    print("\n" + "=" * 50)
    print("  ✅ Tutto completato con successo!")
    print("=" * 50)


if __name__ == "__main__":
    main()
