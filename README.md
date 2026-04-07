[README.md](https://github.com/user-attachments/files/26528999/README.md)
# 🛰 Gush Dan Impact Map
### מפת אירועים אינטראקטיבית – מלחמת ישראל-איראן השנייה

Real-time OSINT-based map of reported missile impacts in the Gush Dan metropolitan area.
Data coverage: February 26, 2026 → present.

---

## 🚀 Deploy in 5 Minutes

### 1. Fork & Clone
```bash
git clone https://github.com/YOUR_USERNAME/gushdan-impact-map
cd gushdan-impact-map
```

### 2. Enable GitHub Pages
- Go to **Settings → Pages**
- Source: **Deploy from a branch**
- Branch: `main`, folder: `/docs`
- Save

### 3. Enable GitHub Actions
- Go to **Settings → Actions → General**
- Allow all actions
- Set workflow permissions to **Read and write**

### 4. Add Secrets (optional, for live data)
Go to **Settings → Secrets → Actions**:
```
TELEGRAM_API_ID       → your Telegram API id
TELEGRAM_API_HASH     → your Telegram API hash
TWITTER_BEARER_TOKEN  → Twitter/X bearer token
```

### 5. Push & Live
Your site will be at:
```
https://YOUR_USERNAME.github.io/gushdan-impact-map/
```

---

## 📁 Project Structure

```
gushdan-impact-map/
├── docs/                    ← GitHub Pages root
│   ├── index.html           ← Main app
│   └── data/
│       └── impacts.json     ← Processed event data
├── data/
│   └── raw_reports.json     ← Raw OSINT input
├── scripts/
│   ├── nlp_pipeline.py      ← NLP processing engine
│   └── requirements.txt     ← Python deps
├── .github/
│   └── workflows/
│       └── update-data.yml  ← Auto-update every 10 min
└── README.md
```

---

## 🧩 Data Schema

```json
{
  "id": "evt_001",
  "timestamp": "2026-02-26T02:14:00Z",
  "type": "direct_hit | interception_debris | fragment_impact",
  "confidence": 92,
  "confidence_level": "high | medium | low",
  "location": {
    "name": "הולון - אזור תעשייה",
    "district": "Holon",
    "lat": 32.012,
    "lng": 34.773,
    "precision": "exact | approximate | neighborhood | city",
    "blur_radius": 300
  },
  "source_count": 3,
  "verified_media": true,
  "damage_level": "major | significant | moderate | minor | unknown"
}
```

---

## 🧠 Confidence Scoring

| Score | Level | Criteria |
|-------|-------|----------|
| 80–100 | 🟢 High | Official source + news + media |
| 50–79 | 🟡 Medium | Partial corroboration, 2+ sources |
| 0–49 | 🟠 Low | Single source, unverified |

---

## ⚠️ Disclaimer

Data is based entirely on open-source intelligence (OSINT).
It may be incomplete, delayed, or inaccurate.
**DO NOT use for operational or life-safety decisions.**
Always follow official Home Front Command (פיקוד העורף) guidance.

---

## 🛠 Local Development

```bash
# Serve locally
python3 -m http.server 8080 --directory docs

# Run pipeline manually
python3 scripts/nlp_pipeline.py --input data/raw_reports.json --output docs/data/impacts.json
```

---

*Built with Leaflet.js · Hosted on GitHub Pages · Auto-updated via GitHub Actions*
