#!/usr/bin/env python3
"""
OSINT NLP Pipeline - Gush Dan Impact Tracker
Processes raw reports from various sources, extracts locations,
classifies confidence, deduplicates, and outputs structured JSON.

Usage:
    python3 nlp_pipeline.py --output ../docs/data/impacts.json
"""

import json
import re
import hashlib
import logging
from datetime import datetime, timezone
from dataclasses import dataclass, field, asdict
from typing import Optional
from pathlib import Path

logging.basicConfig(level=logging.INFO, format='%(asctime)s [%(levelname)s] %(message)s')
log = logging.getLogger(__name__)

# ─────────────────────────────────────────────────────
#  GEO KNOWLEDGE BASE  (Gush Dan only)
# ─────────────────────────────────────────────────────
GUSH_DAN_LOCATIONS = {
    # Hebrew name → (district, lat, lng, precision_radius_m)
    "תל אביב": ("Tel Aviv", 32.0853, 34.7818, 800),
    "יפו": ("Tel Aviv", 32.0550, 34.7556, 400),
    "נמל תל אביב": ("Tel Aviv", 32.0990, 34.7710, 200),
    "נוה צדק": ("Tel Aviv", 32.0575, 34.7620, 250),
    "פלורנטין": ("Tel Aviv", 32.0600, 34.7700, 250),
    "הולון": ("Holon", 32.0158, 34.7800, 600),
    "אזור תעשייה הולון": ("Holon", 32.0120, 34.7730, 300),
    "בת ים": ("Bat Yam", 32.0218, 34.7515, 500),
    "רמת גן": ("Ramat Gan", 32.0700, 34.8260, 600),
    "גבעתיים": ("Givatayim", 32.0720, 34.8130, 400),
    "בני ברק": ("Bnei Brak", 32.0830, 34.8330, 600),
    "פתח תקווה": ("Petah Tikva", 32.0870, 34.8870, 800),
    "ראשון לציון": ("Rishon LeZion", 31.9730, 34.7880, 700),
    "אזור": ("Azor", 32.0200, 34.8200, 400),
    "חולון": ("Holon", 32.0158, 34.7800, 600),  # alternate spelling
}

IMPACT_KEYWORDS = {
    "direct_hit": [
        "פגיעה ישירה", "נפל", "נחת", "טיל נחת", "פגע ב", "פגיעה ב",
        "hit", "direct hit", "landed", "impact", "struck"
    ],
    "interception_debris": [
        "שיירי יירוט", "פסולת יירוט", "כיפת ברזל", "יירוט", "שריד",
        "debris", "interception", "iron dome", "intercepted", "shrapnel from interception"
    ],
    "fragment_impact": [
        "רסיסים", "שברי", "פגיעת רסיס", "fragment", "shrapnel", "splinter"
    ]
}

SOURCE_WEIGHTS = {
    "official": 40,     # IDF, police, Home Front Command
    "news": 25,         # Established outlets (Ynet, Haaretz, Channel 12/13)
    "social_verified": 15,  # Verified social media accounts
    "social": 5,        # Unverified Telegram/Twitter
    "single": -10,      # Penalty for single source
}

RELIABLE_NEWS_SOURCES = {
    "ynet", "haaretz", "maariv", "channel 12", "channel 13",
    "times of israel", "jerusalem post", "walla", "n12", "kan"
}

OFFICIAL_SOURCES = {
    "idf", "צבא", "דובר צבא", "פיקוד העורף", "home front command",
    "police", "משטרה", "כיבוי אש"
}


@dataclass
class RawReport:
    source_type: str        # 'official' | 'news' | 'social' | 'telegram'
    source_name: str
    text: str
    timestamp: str          # ISO 8601
    url: Optional[str] = None
    has_media: bool = False


@dataclass
class ProcessedEvent:
    id: str
    timestamp: str
    type: str
    confidence: int
    confidence_level: str
    location: dict
    description: str
    sources: list = field(default_factory=list)
    source_count: int = 0
    casualties: dict = field(default_factory=lambda: {"confirmed": False, "details": None})
    damage_level: str = "unknown"
    verified_media: bool = False


# ─────────────────────────────────────────────────────
#  ENTITY EXTRACTION
# ─────────────────────────────────────────────────────

def extract_location(text: str) -> Optional[tuple]:
    """
    Simple rule-based NER for Gush Dan locations.
    Returns (location_key, district, lat, lng, radius) or None.
    Sorted by string length (longer = more specific) to prefer specific matches.
    """
    text_lower = text.lower()
    matches = []

    for heb_name, (district, lat, lng, radius) in GUSH_DAN_LOCATIONS.items():
        if heb_name in text:
            matches.append((len(heb_name), heb_name, district, lat, lng, radius))

    if not matches:
        return None

    # Return most specific (longest) match
    matches.sort(reverse=True)
    _, name, district, lat, lng, radius = matches[0]

    # Add small jitter for privacy (±0.001 degrees ≈ 100m)
    import random
    jitter = 0.001
    lat += random.uniform(-jitter, jitter)
    lng += random.uniform(-jitter, jitter)

    return name, district, round(lat, 4), round(lng, 4), radius


def classify_impact_type(text: str) -> str:
    """Classify event type from text using keyword matching."""
    text_lower = text.lower()
    scores = {t: 0 for t in IMPACT_KEYWORDS}

    for impact_type, keywords in IMPACT_KEYWORDS.items():
        for kw in keywords:
            if kw.lower() in text_lower:
                scores[impact_type] += 1

    best = max(scores, key=scores.get)
    return best if scores[best] > 0 else "direct_hit"


def classify_damage(text: str) -> str:
    """Estimate damage level from text."""
    text_lower = text.lower()
    if any(w in text_lower for w in ["הרוג", "נהרג", "קטלני", "fatal", "killed"]):
        return "major"
    if any(w in text_lower for w in ["נזק כבד", "בניין", "שריפה", "heavy damage", "fire"]):
        return "significant"
    if any(w in text_lower for w in ["נזק", "שבור", "damage", "broken"]):
        return "moderate"
    if any(w in text_lower for w in ["קל", "minor", "small"]):
        return "minor"
    return "unknown"


def extract_casualties(text: str) -> dict:
    """Check if casualties are mentioned."""
    text_lower = text.lower()
    killed = any(w in text_lower for w in ["הרוג", "נהרג", "killed", "dead"])
    injured = any(w in text_lower for w in ["פצוע", "נפצע", "injured", "wounded"])

    if killed or injured:
        detail = "פצועים" if injured and not killed else "הרוגים" if killed else None
        return {"confirmed": True, "details": detail}
    return {"confirmed": False, "details": None}


# ─────────────────────────────────────────────────────
#  CONFIDENCE SCORING
# ─────────────────────────────────────────────────────

def calculate_confidence(reports: list[RawReport], location_precision: str) -> int:
    """
    Score 0–100 based on:
    - Number and type of sources
    - Presence of official sources
    - Media verification
    - Location precision
    """
    score = 0

    has_official = any(r.source_type == 'official' for r in reports)
    has_news = any(r.source_type == 'news' for r in reports)
    has_media = any(r.has_media for r in reports)

    # Source type scoring
    if has_official:
        score += SOURCE_WEIGHTS["official"]
    if has_news:
        score += SOURCE_WEIGHTS["news"]

    social_count = sum(1 for r in reports if r.source_type in ('social', 'telegram'))
    score += min(social_count * SOURCE_WEIGHTS["social"], 20)

    # Single source penalty
    if len(reports) == 1:
        score += SOURCE_WEIGHTS["single"]

    # Media bonus
    if has_media:
        score += 15

    # Multi-source corroboration bonus
    if len(reports) >= 3:
        score += 10
    elif len(reports) >= 2:
        score += 5

    # Precision penalty
    if location_precision == 'city':
        score -= 15
    elif location_precision == 'neighborhood':
        score -= 5

    return max(0, min(100, score))


def confidence_level_label(score: int) -> str:
    if score >= 80:
        return "high"
    if score >= 50:
        return "medium"
    return "low"


# ─────────────────────────────────────────────────────
#  DEDUPLICATION
# ─────────────────────────────────────────────────────

def dedup_reports(events: list[ProcessedEvent],
                  time_window_minutes: int = 30,
                  geo_radius_km: float = 0.5) -> list[ProcessedEvent]:
    """
    Merge events that:
    1. Occurred within `time_window_minutes` of each other
    2. Are within `geo_radius_km` of each other
    3. Have the same type

    Keeps the highest-confidence version and merges sources.
    """
    import math

    def haversine(lat1, lng1, lat2, lng2):
        R = 6371
        dlat = math.radians(lat2 - lat1)
        dlng = math.radians(lng2 - lng1)
        a = math.sin(dlat/2)**2 + math.cos(math.radians(lat1)) * math.cos(math.radians(lat2)) * math.sin(dlng/2)**2
        return R * 2 * math.asin(math.sqrt(a))

    merged = []
    used = set()

    for i, evt_a in enumerate(events):
        if i in used:
            continue
        group = [evt_a]
        ts_a = datetime.fromisoformat(evt_a.timestamp.replace('Z','+00:00'))

        for j, evt_b in enumerate(events):
            if j <= i or j in used:
                continue
            if evt_b.type != evt_a.type:
                continue

            ts_b = datetime.fromisoformat(evt_b.timestamp.replace('Z','+00:00'))
            time_diff = abs((ts_b - ts_a).total_seconds()) / 60

            dist = haversine(
                evt_a.location['lat'], evt_a.location['lng'],
                evt_b.location['lat'], evt_b.location['lng']
            )

            if time_diff <= time_window_minutes and dist <= geo_radius_km:
                group.append(evt_b)
                used.add(j)

        # Pick best from group
        best = max(group, key=lambda e: e.confidence)
        all_sources = []
        for g in group:
            all_sources.extend(g.sources)

        # Deduplicate sources
        seen_sources = set()
        unique_sources = []
        for s in all_sources:
            key = s.get('name','')
            if key not in seen_sources:
                seen_sources.add(key)
                unique_sources.append(s)

        best.sources = unique_sources
        best.source_count = len(unique_sources)
        merged.append(best)
        used.add(i)

    log.info(f"Dedup: {len(events)} → {len(merged)} events")
    return merged


# ─────────────────────────────────────────────────────
#  MAIN PIPELINE
# ─────────────────────────────────────────────────────

def process_raw_reports(raw_reports: list[RawReport]) -> list[ProcessedEvent]:
    """Full pipeline: extract → score → structure."""
    events = []

    for report in raw_reports:
        loc = extract_location(report.text)
        if not loc:
            log.debug(f"No Gush Dan location found in: {report.text[:80]}")
            continue

        loc_name, district, lat, lng, blur_radius = loc
        impact_type = classify_impact_type(report.text)
        damage = classify_damage(report.text)
        casualties = extract_casualties(report.text)

        # Determine precision level
        if blur_radius <= 200:
            precision = "exact"
        elif blur_radius <= 400:
            precision = "approximate"
        elif blur_radius <= 700:
            precision = "neighborhood"
        else:
            precision = "city"

        conf_score = calculate_confidence([report], precision)

        # Generate stable ID from content hash
        content_hash = hashlib.md5(f"{report.text}{report.timestamp}".encode()).hexdigest()[:8]
        event_id = f"evt_{content_hash}"

        source = {
            "type": report.source_type,
            "name": report.source_name,
            "url": report.url
        }

        event = ProcessedEvent(
            id=event_id,
            timestamp=report.timestamp,
            type=impact_type,
            confidence=conf_score,
            confidence_level=confidence_level_label(conf_score),
            location={
                "name": loc_name,
                "district": district,
                "lat": lat,
                "lng": lng,
                "precision": precision,
                "blur_radius": blur_radius
            },
            description=report.text[:200],
            sources=[source],
            source_count=1,
            casualties=casualties,
            damage_level=damage,
            verified_media=report.has_media
        )
        events.append(event)

    deduped = dedup_reports(events)
    return deduped


def build_output_json(events: list[ProcessedEvent]) -> dict:
    """Assemble final JSON with metadata and stats."""
    from collections import Counter

    events_dicts = [asdict(e) for e in events]

    type_counts = Counter(e.type for e in events)
    conf_counts = Counter(e.confidence_level for e in events)
    district_counts = Counter(e.location['district'] for e in events)

    return {
        "metadata": {
            "last_updated": datetime.now(timezone.utc).strftime('%Y-%m-%dT%H:%M:%SZ'),
            "total_events": len(events),
            "coverage_start": "2026-02-26T00:00:00Z",
            "coverage_area": "Gush Dan",
            "pipeline_version": "1.0.0",
            "disclaimer": "Data is based on open sources and may not be accurate. "
                          "Locations may be approximated for security reasons."
        },
        "events": events_dicts,
        "stats": {
            "by_type": dict(type_counts),
            "by_confidence": dict(conf_counts),
            "by_district": dict(district_counts)
        }
    }


def run_pipeline(input_path: Optional[str] = None, output_path: str = "../docs/data/impacts.json"):
    """
    Main entry point.
    In production: fetch from APIs/Telegram. For now, reads from input JSON.
    """
    log.info("Starting OSINT pipeline...")

    if input_path and Path(input_path).exists():
        with open(input_path) as f:
            raw = json.load(f)
        reports = [RawReport(**r) for r in raw.get('reports', [])]
        log.info(f"Loaded {len(reports)} raw reports from {input_path}")
    else:
        # Demo: produce empty update (real run would fetch from APIs)
        log.warning("No input file. Using empty reports for demo.")
        reports = []

    events = process_raw_reports(reports)
    output = build_output_json(events)

    out_path = Path(output_path)
    out_path.parent.mkdir(parents=True, exist_ok=True)

    with open(out_path, 'w', encoding='utf-8') as f:
        json.dump(output, f, ensure_ascii=False, indent=2)

    log.info(f"Pipeline complete. {len(events)} events written to {out_path}")
    return output


if __name__ == "__main__":
    import argparse
    parser = argparse.ArgumentParser(description='OSINT NLP Pipeline')
    parser.add_argument('--input', default=None, help='Raw reports JSON path')
    parser.add_argument('--output', default='../docs/data/impacts.json')
    args = parser.parse_args()
    run_pipeline(args.input, args.output)
