# services/consumer/main.py
from kafka import KafkaConsumer
import json
import os
import re
import time
from datetime import datetime, timezone, date
from collections import defaultdict
import warnings
warnings.filterwarnings("ignore", category=FutureWarning)

from transformers import AutoTokenizer, AutoModelForSequenceClassification
import torch

from db.postgres import (
    write_daily_record,
    write_article,
    backfill_price,
    get_existing_dates,
    get_incomplete_dates,
)

# ---------------------------------------------------------
# CONFIGURATION
# ---------------------------------------------------------
KAFKA_BOOTSTRAP_SERVERS = os.getenv("KAFKA_BOOTSTRAP_SERVERS", "kafka:29092")
KAFKA_TOPIC = "stock-data"

MARKET_CLOSE_UTC_HOUR = 20

QUALITY_THRESHOLD = float(os.getenv("QUALITY_THRESHOLD", "0.21"))

NOISY_SOURCE_SUBSTRINGS = {
    "reddit", "stocktwits", "twitter", "x.com", "discord",
    "telegram", "benzinga_community", "seekingalpha_comments",
}

QUALITY_SOURCE_SUBSTRINGS = {
    "reuters", "bloomberg", "wsj", "ft.com", "financialtimes",
    "apnews", "cnbc", "marketwatch", "barron", "sec.gov",
    # Finnhub commonly surfaces these quality outlets — add them here
    # so their articles get the quality bonus rather than the neutral score.
    "yahoo", "businesswire", "prnewswire", "globenewswire",
}

_SOCIAL_NOISE_RE = re.compile(
    r"(\$[A-Z]{1,5}\b"
    r"|\U0001F680{2,}"
    r"|to\s+the\s+moon"
    r"|diamond\s+hands?"
    r"|#[A-Za-z]+"
    r"|\bDD\b"
    r"|\bYOLO\b"
    r")",
    re.IGNORECASE,
)

_FINANCIAL_TERMS = [
    "revenue", "earnings", "eps", "guidance", "forecast",
    "acquisition", "merger", "ipo", "dividend", "buyback",
    "ceo", "cfo", "board", "quarterly", "annual", "fiscal",
    "regulatory", "filing", "sec", "patent", "lawsuit",
    "partnership", "contract", "analyst", "downgrade", "upgrade",
    "margin", "outlook", "debt", "equity", "shares", "stock split",
]
_FINANCIAL_TERM_RE = re.compile(
    r"\b(" + "|".join(re.escape(t) for t in _FINANCIAL_TERMS) + r")\b",
    re.IGNORECASE,
)


# ---------------------------------------------------------
# SENTIMENT MODEL INITIALIZATION
# ---------------------------------------------------------
SENTIMENT_MODEL_NAME = "soleimanian/financial-roberta-large-sentiment"
SENTIMENT_LABEL_ORDER = ["negative", "neutral", "positive"]

print(f"🔧 Loading sentiment model: {SENTIMENT_MODEL_NAME} ...")
sentiment_tokenizer = AutoTokenizer.from_pretrained(SENTIMENT_MODEL_NAME)
sentiment_model = AutoModelForSequenceClassification.from_pretrained(SENTIMENT_MODEL_NAME)
sentiment_model.eval()
print("✓ Sentiment model loaded successfully.")


# ---------------------------------------------------------
# KAFKA CONNECTION
# ---------------------------------------------------------
def get_kafka_consumer():
    max_retries = 10
    for attempt in range(max_retries):
        try:
            consumer = KafkaConsumer(
                KAFKA_TOPIC,
                bootstrap_servers=KAFKA_BOOTSTRAP_SERVERS,
                value_deserializer=lambda m: json.loads(m.decode("utf-8")),
                auto_offset_reset="earliest",
                enable_auto_commit=True,
                group_id="stock-consumer-group",
            )
            print(f"✓ Connected to Kafka at {KAFKA_BOOTSTRAP_SERVERS}")
            return consumer
        except Exception as e:
            print(f"❌ Kafka connection failed ({attempt+1}/10): {e}")
            time.sleep(5)
    raise RuntimeError("Could not connect to Kafka")


# ---------------------------------------------------------
# TRADING DAY HELPERS
# ---------------------------------------------------------
US_MARKET_HOLIDAYS = {
    date(2026, 1,  1),
    date(2026, 1, 19),
    date(2026, 2, 16),
    date(2026, 4,  3),
    date(2026, 5, 25),
    date(2026, 7,  3),
    date(2026, 9,  7),
    date(2026, 11, 26),
    date(2026, 11, 27),
    date(2026, 12, 24),
    date(2026, 12, 25),
}

def is_trading_day(dt: date) -> bool:
    if dt.weekday() >= 5:
        return False
    if dt in US_MARKET_HOLIDAYS:
        return False
    return True

def market_has_closed(dt: date) -> bool:
    now_utc = datetime.now(tz=timezone.utc)
    today_utc = now_utc.date()
    if dt < today_utc:
        return True
    if dt == today_utc:
        return now_utc.hour >= MARKET_CLOSE_UTC_HOUR
    return False

def should_retry_price(dt_str: str) -> tuple[bool, str]:
    try:
        dt = date.fromisoformat(dt_str)
    except ValueError:
        return False, "invalid date"

    if not is_trading_day(dt):
        reason = "holiday" if dt in US_MARKET_HOLIDAYS else "weekend"
        return False, reason

    if not market_has_closed(dt):
        return False, "open"

    return True, ""


# ---------------------------------------------------------
# ARTICLE QUALITY FILTER
# ---------------------------------------------------------
def score_article_quality(item: dict) -> tuple[float, str]:
    """
    Score a single news item for quality/relevance on a [0.0, 1.0] scale.
    Identical logic for both AV and Finnhub articles — the filter is
    feed-agnostic and operates only on headline, summary, and source.
    """
    headline = item.get("headline", "")
    summary  = item.get("summary",  "")
    source   = (item.get("source") or "").lower()
    text     = f"{headline} {summary}".strip()

    char_count   = len(text)
    length_score = min(char_count / 1000.0, 1.0) * 0.25

    words = text.split()
    word_count = max(len(words), 1)
    unique_fin_terms = len(set(m.group(0).lower() for m in _FINANCIAL_TERM_RE.finditer(text)))
    term_density     = unique_fin_terms / word_count
    substance_score  = min(term_density * 15.0, 1.0) * 0.30

    sentence_count  = max(len(re.split(r'[.!?]+', text)), 1)
    sentence_score  = min((sentence_count - 1) / 5.0, 1.0) * 0.20

    if any(q in source for q in QUALITY_SOURCE_SUBSTRINGS):
        source_score = 0.15
    elif any(n in source for n in NOISY_SOURCE_SUBSTRINGS):
        source_score = -0.10
    else:
        source_score = 0.05

    noise_hits    = len(_SOCIAL_NOISE_RE.findall(text))
    noise_penalty = min(noise_hits * 0.07, 0.20)

    raw   = length_score + substance_score + sentence_score + source_score - noise_penalty
    score = max(0.0, min(raw, 1.0))

    components = {
        "length":    length_score,
        "substance": substance_score,
        "structure": sentence_score,
        "source":    source_score,
        "noise":     -noise_penalty,
    }
    dominant = max(components, key=lambda k: abs(components[k]))
    reason   = f"{dominant}={components[dominant]:+.2f}"

    return score, reason


def filter_articles(
    news_items: list[dict],
    symbol: str,
    date_str: str,
    feed_label: str = "",
) -> tuple[list[dict], int, int]:
    """
    Apply quality scoring to a list of news items.
    feed_label is used only in log output to distinguish AV vs Finnhub.
    """
    n_total = len(news_items)
    kept    = []
    label   = f" [{feed_label}]" if feed_label else ""

    for item in news_items:
        score, reason = score_article_quality(item)
        if score >= QUALITY_THRESHOLD:
            item["_quality_score"] = score
            kept.append(item)
        else:
            headline_preview = (item.get("headline") or "")[:50]
            print(
                f"    🚫 FILTERED{label} [{symbol} {date_str}] "
                f"score={score:.2f} ({reason}) — \"{headline_preview}\""
            )

    n_kept = len(kept)
    pct    = (n_kept / n_total * 100) if n_total else 0.0

    if n_total > 0:
        bar_len = 12
        filled  = round(bar_len * n_kept / n_total)
        bar     = "█" * filled + "░" * (bar_len - filled)
        print(
            f"    🔍 Filter{label} [{symbol} {date_str}]: "
            f"{n_kept}/{n_total} passed [{bar}] {pct:.0f}% "
            f"(threshold={QUALITY_THRESHOLD})"
        )

    return kept, n_total, n_kept


# ---------------------------------------------------------
# SENTIMENT ENGINE
# ---------------------------------------------------------
def model_sentiment(text: str) -> tuple[float, float, str]:
    """
    Run the loaded sentiment model on a single text string.
    Returns (score, confidence, label).
    score = pos_prob - neg_prob, range [-1.0, +1.0].
    """
    try:
        inputs = sentiment_tokenizer(
            text, return_tensors="pt", truncation=True, max_length=512
        )
        with torch.no_grad():
            outputs = sentiment_model(**inputs)
        probs = torch.softmax(outputs.logits[0], dim=0)
        neg, neu, pos = probs.tolist()
        score = (pos - neg) * (1.0 - neu)
        label_idx = int(torch.argmax(probs))
        return score, probs[label_idx].item(), SENTIMENT_LABEL_ORDER[label_idx]
    except Exception:
        return 0.0, 0.0, "neutral"


# ---------------------------------------------------------
# DATA PROCESSING LOGIC
# ---------------------------------------------------------
def process_daily_sentiment(symbol: str, date_str: str, day_data: dict):
    """
    Score sentiment for a single symbol/date and write the result to Postgres.

    Two fully independent sentiment streams:

    Stream 1 — LOCAL MODEL (Finnhub articles)
        model_sentiment() runs on Finnhub headline+summary for each article
        that passes the quality filter. Articles are weighted by text length.
        The local model score is stored in finbert_sentiment /
        finbert_confidence / finbert_explanation.

    Stream 2 — ALPHA VANTAGE BASELINE (AV articles)
        AV pre-computed scores are averaged with equal weight.
        Stored in av_sentiment. Unchanged from previous behaviour.

    Each Finnhub article that passes quality filter is written to the
    articles table (with news_source='finnhub'). AV articles are NOT
    written to the articles table individually — only their averaged
    score contributes to the daily record, exactly as before.
    """
    # Separate the two article lists from the buffer
    finnhub_items  = day_data.get("finnhub_items",  [])
    av_items       = day_data.get("av_items",        [])
    price_info     = day_data.get("price_data")

    # We need at least one feed to have something to process
    if not finnhub_items and not av_items:
        return

    # ------------------------------------------------------------------
    # Stream 1: Local model on Finnhub articles
    # ------------------------------------------------------------------
    avg_our_score    = None
    avg_our_conf     = None
    best_explanation = "Neutral/Mixed outlook."
    n_fh_total       = 0
    n_fh_kept        = 0

    if finnhub_items:
        fh_filtered, n_fh_total, n_fh_kept = filter_articles(
            finnhub_items, symbol, date_str, feed_label="Finnhub"
        )

        if fh_filtered:
            our_weighted_scores = []
            our_weights         = []
            our_confidences     = []
            max_impact          = 0.0

            for item in fh_filtered:
                headline = item.get("headline", "")
                summary  = item.get("summary",  "")
                text     = f"{headline} {summary}".strip()

                text_weight = max(50, min(len(text), 1000)) / 1000.0
                score, conf, label = model_sentiment(text)

                our_weighted_scores.append(score * text_weight)
                our_weights.append(text_weight)
                our_confidences.append(conf)

                impact = conf * text_weight
                if impact > max_impact:
                    max_impact = impact
                    prefix = {"positive": "Bullish", "negative": "Bearish", "neutral": "Neutral"}[label]
                    best_explanation = f"{prefix}: {headline[:60]}..."

                # Persist quality-filtered, scored Finnhub article
                try:
                    published_at = datetime.strptime(date_str, "%Y-%m-%d").replace(
                        tzinfo=timezone.utc
                    )
                except ValueError:
                    published_at = datetime.now(tz=timezone.utc)

                write_article(
                    symbol=symbol,
                    published_at=published_at,
                    title=headline,
                    summary=summary,
                    source=item.get("source"),
                    url=item.get("url"),
                    av_sentiment=None,           # Finnhub articles have no AV score
                    model_sentiment=round(score, 4),
                    model_confidence=round(conf, 4),
                    news_source="finnhub",
                )

            total_weight  = sum(our_weights)
            avg_our_score = sum(our_weighted_scores) / total_weight if total_weight > 0 else 0.0
            avg_our_conf  = sum(our_confidences) / len(our_confidences)

        else:
            print(
                f"  ⚠️  {symbol} | {date_str} | "
                f"All {n_fh_total} Finnhub article(s) filtered out — "
                f"local model score will be NULL for this date."
            )

    # ------------------------------------------------------------------
    # Stream 2: Alpha Vantage baseline — equal-weight average of AV scores.
    # AV articles are not re-scored by the local model; only their
    # pre-computed av_sentiment_score contributes to avg_av_score.
    # ------------------------------------------------------------------
    avg_av_score  = None
    n_av_total    = len(av_items)

    if av_items:
        av_raw = [
            item["av_sentiment_score"]
            for item in av_items
            if item.get("av_sentiment_score") is not None
        ]
        avg_av_score = sum(av_raw) / len(av_raw) if av_raw else None

    # ------------------------------------------------------------------
    # Logging
    # ------------------------------------------------------------------
    our_display = f"{avg_our_score:+.4f} (conf {avg_our_conf:.2f})" if avg_our_score is not None else "N/A"
    av_display  = f"{avg_av_score:+.4f}" if avg_av_score is not None else "N/A"

    if avg_our_score is not None and avg_av_score is not None:
        delta_str = f"  Δ={abs(avg_our_score - avg_av_score):+.3f}"
    else:
        delta_str = ""

    price_display = (
        f"open ${price_info.get('open'):.2f} / close ${price_info.get('close'):.2f}"
        if price_info else "pending (market open)"
    )

    print(
        f"  📊 {symbol} | {date_str} | "
        f"Model (Finnhub): {our_display} | "
        f"AV: {av_display}{delta_str} | "
        f"Finnhub n={n_fh_kept}/{n_fh_total} | AV n={n_av_total} | "
        f"Price: {price_display} | "
        f"{best_explanation}"
    )

    # article_count = total Finnhub articles received (pre-filter),
    # keeping the metric comparable across runs even if threshold changes.
    write_daily_record(
        symbol=symbol,
        date=date_str,
        open_price=price_info.get("open")   if price_info else None,
        close_price=price_info.get("close") if price_info else None,
        volume=price_info.get("volume")     if price_info else None,
        finbert_sentiment=round(avg_our_score, 4)   if avg_our_score is not None else None,
        finbert_confidence=round(avg_our_conf, 4)   if avg_our_conf  is not None else None,
        finbert_explanation=best_explanation         if avg_our_score is not None else None,
        article_count=n_fh_total,
        av_sentiment=round(avg_av_score, 4) if avg_av_score is not None else None,
    )


# ---------------------------------------------------------
# MAIN LOOP
# ---------------------------------------------------------
def run_consumer():
    consumer = get_kafka_consumer()
    print("👂 Consumer is listening for messages on topic: stock-data")

    # buffer[symbol][date_string] = {
    #   "finnhub_items": [...],   ← fed to local model
    #   "av_items":      [...],   ← AV baseline scores only
    #   "price_data":    {...},
    # }
    buffer = defaultdict(
        lambda: defaultdict(
            lambda: {"finnhub_items": [], "av_items": [], "price_data": None}
        )
    )

    for message in consumer:
        data     = message.value
        msg_type = data.get("type")

        if msg_type == "end_of_fetch":
            print("🏁 End of fetch signal received. Processing...")

            for sym, dates in buffer.items():

                existing_dates = get_existing_dates(sym)
                new_dates = {
                    dt: d for dt, d in dates.items() if dt not in existing_dates
                }

                skipped = len(dates) - len(new_dates)
                print(
                    f"  ⚙️  {sym}: {len(new_dates)} new dates to process "
                    f"(skipping {skipped} already complete)"
                )

                for dt, d_data in new_dates.items():
                    process_daily_sentiment(sym, dt, d_data)

                # Backfill price for dates missing price data
                incomplete_dates = get_incomplete_dates(sym)
                if incomplete_dates:
                    print(
                        f"  🔍 {sym}: checking backfill for "
                        f"{len(incomplete_dates)} incomplete date(s): "
                        f"{sorted(incomplete_dates)}"
                    )

                for dt in list(incomplete_dates):
                    retry, skip_reason = should_retry_price(dt)

                    if not retry:
                        if skip_reason == "weekend":
                            print(f"  ⏭️  {sym} {dt}: weekend — no price bar exists, skipping")
                        elif skip_reason == "holiday":
                            print(f"  ⏭️  {sym} {dt}: market holiday — no price bar exists, skipping")
                        elif skip_reason == "open":
                            print(f"  🕐 {sym} {dt}: market still open, will retry after 20:00 UTC")
                        else:
                            print(f"  ⏭️  {sym} {dt}: skipping backfill ({skip_reason})")
                        continue

                    price_info = dates.get(dt, {}).get("price_data")
                    if price_info:
                        backfill_price(
                            symbol=sym,
                            date=dt,
                            open_price=price_info.get("open"),
                            close_price=price_info.get("close"),
                            volume=price_info.get("volume"),
                        )
                    else:
                        print(
                            f"  ⏳ {sym} {dt}: no price bar in this fetch, "
                            f"will retry on next fetch"
                        )

                print(f"  ✓  {sym} done.")

            print("✅ All done. Buffer cleared, waiting for next fetch.")
            buffer.clear()
            continue

        symbol = data.get("symbol")
        if not symbol:
            continue

        if msg_type == "finnhub_news":
            # New: Finnhub articles — routed to local model
            dt_str = data.get("date")
            buffer[symbol][dt_str]["finnhub_items"].append(data)

        elif msg_type == "news":
            # Existing: AV articles — routed to AV baseline only
            dt_str = data.get("date")
            buffer[symbol][dt_str]["av_items"].append(data)

        elif msg_type == "price":
            dt_str = data["date"]
            buffer[symbol][dt_str]["price_data"] = data


if __name__ == "__main__":
    run_consumer()
