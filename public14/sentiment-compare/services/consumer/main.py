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

# NYSE/NASDAQ regular session closes at 16:00 ET.
MARKET_CLOSE_UTC_HOUR = 20

# ---------------------------------------------------------
# ARTICLE QUALITY FILTER CONFIGURATION
# ---------------------------------------------------------
# Minimum quality score [0.0, 1.0] for an article to be passed to the
# sentiment model.  Tune this after reviewing a few weeks of filter logs.
#
#   0.30  — permissive;
#   0.45  — moderate;
#   0.60  — strict;
QUALITY_THRESHOLD = float(os.getenv("QUALITY_THRESHOLD", "0.40"))

# Sources that are noisy receive a quality penalty.
# These are matched as substrings (case-insensitive) against the item's
# `source` field.  Add to this list low-quality feeds.
NOISY_SOURCE_SUBSTRINGS = {
    "reddit", "stocktwits", "twitter", "x.com", "discord",
    "telegram", "benzinga_community", "seekingalpha_comments",
}

# Sources that are high-quality wire/financial press and should receive
# a quality bonus.
QUALITY_SOURCE_SUBSTRINGS = {
    "reuters", "bloomberg", "wsj", "ft.com", "financialtimes",
    "apnews", "cnbc", "marketwatch", "barron", "sec.gov",
}

# Regex for social-media noise signals
_SOCIAL_NOISE_RE = re.compile(
    r"(\$[A-Z]{1,5}\b"               # $TICKER cashtag
    r"|\U0001F680{2,}"                # two or more 🚀
    r"|to\s+the\s+moon"              # "to the moon"
    r"|diamond\s+hands?"             # "diamond hands"
    r"|#[A-Za-z]+"                   # hashtag
    r"|\bDD\b"                       # "due diligence" shorthand common on Reddit
    r"|\bYOLO\b"                     # YOLO
    r")",
    re.IGNORECASE,
)

# Terms that signal genuine financial / business reporting.
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
# Primary model: DistilRoBERTa fine-tuned on financial news sentences.
# Fast, financially-domain-aware, and easy on CPU.
#
# Option A (default) — DistilRoBERTa, ~82M params, fast on CPU:
# SENTIMENT_MODEL_NAME = "mrm8488/distilroberta-finetuned-financial-news-sentiment-analysis"
#
# Option B — RoBERTa-Large fine-tuned on filings + news, ~355M params,
# higher accuracy, noticeably slower on CPU, comfortable on GPU:
#
# Option C - FinBERT
SENTIMENT_MODEL_NAME = "soleimanian/financial-roberta-large-sentiment"

# Label order: 0=negative, 1=neutral, 2=positive
# This ordering is consistent across both model options above.
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
# Known US market holidays (NYSE/NASDAQ) for the current year.
US_MARKET_HOLIDAYS = {
    date(2026, 1,  1),   # New Year's Day
    date(2026, 1, 19),   # MLK Day
    date(2026, 2, 16),   # Presidents' Day
    date(2026, 4,  3),   # Good Friday
    date(2026, 5, 25),   # Memorial Day
    date(2026, 7,  3),   # Independence Day (observed)
    date(2026, 9,  7),   # Labor Day
    date(2026, 11, 26),  # Thanksgiving
    date(2026, 11, 27),  # Black Friday (early close, treated as holiday)
    date(2026, 12, 24),  # Christmas Eve (early close, treated as holiday)
    date(2026, 12, 25),  # Christmas Day
}

def is_trading_day(dt: date) -> bool:
    """Return True if dt is a weekday that is not a US market holiday."""
    if dt.weekday() >= 5:
        return False
    if dt in US_MARKET_HOLIDAYS:
        return False
    return True

def market_has_closed(dt: date) -> bool:
    """
    Return True if the NYSE/NASDAQ regular session for dt has definitely
    ended by now (UTC). We use 20:00 UTC as a conservative threshold —
    that is 16:00 EDT (UTC-4), the latest the session can close in summer.
    """
    now_utc = datetime.now(tz=timezone.utc)
    today_utc = now_utc.date()

    if dt < today_utc:
        return True
    if dt == today_utc:
        return now_utc.hour >= MARKET_CLOSE_UTC_HOUR
    return False

def should_retry_price(dt_str: str) -> tuple[bool, str]:
    """
    Decide whether a backfill retry for dt_str makes sense right now.
    Returns (should_retry: bool, skip_reason: str | "").

    Skip reasons:
      "weekend"  — Saturday or Sunday, no bar will ever exist.
      "holiday"  — US market holiday, no bar will ever exist.
      "open"     — trading day but market has not yet closed today.
    """
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
    Returns (score, reason) where reason is a short human-readable label
    that explains the dominant factor. It is never written to the database.

    Scoring components (each clamped so the sum stays in [0, 1]):

      length_score    (0.00–0.25)  Rewards articles with a meaningful body.
                                   Short blurbs score low; very long articles
                                   are capped to avoid gaming.

      substance_score (0.00–0.30)  Financial term density relative to word
                                   count.  Rewards domain-specific language.

      sentence_score  (0.00–0.20)  More sentences → more structured reporting.
                                   Single-sentence items score near zero.

      source_score    (0.00–0.15)  Bonus for known quality outlets; penalty
                                   for known noisy sources.

      noise_penalty   (0.00–0.20)  Deducted when social-media signals are
                                   present (cashtags, emoji clusters, memes).

    Tuning guide:
      If legitimate wire-service articles are being filtered out, lower
      QUALITY_THRESHOLD or reduce the noise_penalty weight.
      If social posts are passing, increase the noise_penalty weight or
      add patterns to _SOCIAL_NOISE_RE.
    """
    headline = item.get("headline", "")
    summary  = item.get("summary",  "")
    source   = (item.get("source") or "").lower()
    text     = f"{headline} {summary}".strip()

    # -- Length score -------------------------------------------------------
    # 0 chars → 0.0, 150 chars → ~0.13, 500 chars → ~0.22, 1000+ chars → 0.25
    char_count   = len(text)
    length_score = min(char_count / 1000.0, 1.0) * 0.25

    # -- Substance score (financial term density) ---------------------------
    # Count distinct financial term *types* present (not raw occurrences,
    # to avoid an article that just repeats "revenue" scoring artificially
    # high).
    words = text.split()
    word_count = max(len(words), 1)
    unique_fin_terms = len(set(m.group(0).lower() for m in _FINANCIAL_TERM_RE.finditer(text)))
    # Normalise by word count so a 10-word blurb doesn't beat a 200-word
    # article that mentions four terms vs three.
    term_density     = unique_fin_terms / word_count
    substance_score  = min(term_density * 15.0, 1.0) * 0.30   # 5 % density → full marks

    # -- Sentence structure score -------------------------------------------
    # Split on '.', '!', '?' as rough sentence boundaries.
    sentence_count   = max(len(re.split(r'[.!?]+', text)), 1)
    # 1 sentence → 0.0, 3 → 0.10, 6+ → 0.20
    sentence_score   = min((sentence_count - 1) / 5.0, 1.0) * 0.20

    # -- Source score -------------------------------------------------------
    if any(q in source for q in QUALITY_SOURCE_SUBSTRINGS):
        source_score = 0.15   # known quality outlet
    elif any(n in source for n in NOISY_SOURCE_SUBSTRINGS):
        source_score = -0.10  # known noisy outlet (penalty, not zero)
    else:
        source_score = 0.05   # unknown — neutral small positive

    # -- Noise penalty ------------------------------------------------------
    noise_hits   = len(_SOCIAL_NOISE_RE.findall(text))
    noise_penalty = min(noise_hits * 0.07, 0.20)   # cap at 0.20

    # -- Final score --------------------------------------------------------
    raw = length_score + substance_score + sentence_score + source_score - noise_penalty
    score = max(0.0, min(raw, 1.0))

    # Human-readable dominant reason (for debug logs)
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
) -> tuple[list[dict], int, int]:
    """
    Apply quality scoring to a list of news items.

    Returns:
        kept      list[dict]  — items that passed the quality threshold.
        n_total   int         — total articles received.
        n_kept    int         — articles that passed the filter.

    The fraction n_kept / n_total is logged but never written to the DB,
    keeping this change fully schema-free.
    """
    n_total = len(news_items)
    kept    = []

    for item in news_items:
        score, reason = score_article_quality(item)
        if score >= QUALITY_THRESHOLD:
            item["_quality_score"] = score   # stash for downstream logging
            kept.append(item)
        else:
            headline_preview = (item.get("headline") or "")[:50]
            print(
                f"    🚫 FILTERED [{symbol} {date_str}] "
                f"score={score:.2f} ({reason}) — \"{headline_preview}\""
            )

    n_kept = len(kept)
    pct    = (n_kept / n_total * 100) if n_total else 0.0

    if n_total > 0:
        bar_len  = 12
        filled   = round(bar_len * n_kept / n_total)
        bar      = "█" * filled + "░" * (bar_len - filled)
        print(
            f"    🔍 Filter [{symbol} {date_str}]: "
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

    Returns:
        score       float  — pos_prob minus neg_prob, range [-1.0, +1.0].
                             Positive values lean bullish, negative bearish.
        confidence  float  — softmax probability of the winning class.
        label       str    — "positive", "neutral", or "negative".

    Weights are applied by the *caller* (process_daily_sentiment), not
    here.  This function is a pure model wrapper with no AV dependency,
    which keeps our sentiment stream fully independent of Alpha Vantage.
    """
    try:
        inputs = sentiment_tokenizer(
            text, return_tensors="pt", truncation=True, max_length=512
        )
        with torch.no_grad():
            outputs = sentiment_model(**inputs)
        probs = torch.softmax(outputs.logits[0], dim=0)
        neg, neu, pos = probs.tolist()
        score = pos - neg
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

    Two fully independent sentiment streams are computed:

    Stream 1 — OUR MODEL SCORE
        model_sentiment() is called on (headline + summary) for each article.
        Articles are weighted by text length (clamped to [50, 1000] chars),
        which is a proxy for information density.

    Stream 2 — BASELINE
        AV's pre-computed sentiment scores are averaged with equal weight.

    After scoring, each article that passes the quality filter is persisted
    to the articles table via write_article().  This powers the live news
    feed on the dashboard.

    Price data is written if Polygon has a closing bar for this date.
    If not, NULL is written and the backfill step in run_consumer() will
    fill in the price on the next fetch.

    article_count written to the DB reflects total articles received;
    the filter pass-rate is logged here.
    """
    all_news_items = day_data.get("news_items", [])
    price_info     = day_data.get("price_data")  # None if market has not closed yet

    if not all_news_items:
        return

    # ------------------------------------------------------------------
    # Article quality filtering
    # Filter before running the model.  article_count in the DB remains
    # the total received; the pass-rate fraction is logged only.
    # ------------------------------------------------------------------
    news_items, n_total, n_kept = filter_articles(all_news_items, symbol, date_str)

    if not news_items:
        print(
            f"  ⚠️  {symbol} | {date_str} | "
            f"All {n_total} article(s) filtered out — skipping sentiment run."
        )
        return

    # ------------------------------------------------------------------
    # Stream 1: independent model scores
    # Weight each article by text length
    # ------------------------------------------------------------------
    our_weighted_scores = []   # list of (score * weight)
    our_weights         = []   # list of weights (for normalisation)
    our_confidences     = []
    best_explanation    = "Neutral/Mixed outlook."
    max_impact          = 0.0

    for item in news_items:
        headline = item.get("headline", "")
        summary  = item.get("summary",  "")
        text     = f"{headline} {summary}".strip()

        # Text-length weight: longer articles carry more information.
        # Clamped to [50, 1000] chars so very short blurbs and very long
        # articles don't dominate. Normalised to (0, 1] range.
        text_weight = max(50, min(len(text), 1000)) / 1000.0

        score, conf, label = model_sentiment(text)

        our_weighted_scores.append(score * text_weight)
        our_weights.append(text_weight)
        our_confidences.append(conf)

        # XAI: pick the highest-impact article.
        # Impact = confidence × weight.
        impact = conf * text_weight
        if impact > max_impact:
            max_impact = impact
            prefix = {"positive": "Bullish", "negative": "Bearish", "neutral": "Neutral"}[label]
            best_explanation = f"{prefix}: {headline[:60]}..."

        # ------------------------------------------------------------------
        # The dashboard sorts by published_at DESC
        # 
        # ------------------------------------------------------------------
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
            av_sentiment=item.get("av_sentiment_score"),
            model_sentiment=round(score, 4),
            model_confidence=round(conf, 4),
        )

    # ------------------------------------------------------------------
    # Stream 2: baseline — plain equal-weight average.
    # Already weighs internally;
    # ------------------------------------------------------------------
    av_raw = [
        item["av_sentiment_score"]
        for item in news_items
        if item.get("av_sentiment_score") is not None
    ]
    avg_av_score = sum(av_raw) / len(av_raw) if av_raw else None

    total_weight  = sum(our_weights)
    avg_our_score = sum(our_weighted_scores) / total_weight if total_weight > 0 else 0.0
    avg_our_conf  = sum(our_confidences) / len(our_confidences)

    # ------------------------------------------------------------------
    # Logging
    # ------------------------------------------------------------------
    av_display = f"{avg_av_score:+.4f}" if avg_av_score is not None else "N/A"

    # Delta: how far apart are the two streams?
    # A consistently large delta is a sign to investigate model fit.
    if avg_av_score is not None:
        delta_str = f"  Δ={abs(avg_our_score - avg_av_score):+.3f}"
    else:
        delta_str = ""

    price_display = (
        f"open ${price_info.get('open'):.2f} / close ${price_info.get('close'):.2f}"
        if price_info else "pending (market open)"
    )

    # Pass-rate fraction: logged here, not persisted.
    filter_display = f"{n_kept}/{n_total} articles ({n_kept/n_total*100:.0f}% passed)"

    print(
        f"  📊 {symbol} | {date_str} | "
        f"Model: {avg_our_score:+.4f} (conf {avg_our_conf:.2f}) | "
        f"AV: {av_display}{delta_str} | "
        f"n={filter_display} | "
        f"Price: {price_display} | "
        f"{best_explanation}"
    )

    # article_count = n_total (total received), not n_kept.
    write_daily_record(
        symbol=symbol,
        date=date_str,
        open_price=price_info.get("open")   if price_info else None,
        close_price=price_info.get("close") if price_info else None,
        volume=price_info.get("volume")     if price_info else None,
        finbert_sentiment=round(avg_our_score, 4),
        finbert_confidence=round(avg_our_conf, 4),
        finbert_explanation=best_explanation,
        article_count=n_total,    # ← total received, filter fraction logged only
        av_sentiment=round(avg_av_score, 4) if avg_av_score is not None else None,
    )


# ---------------------------------------------------------
# MAIN LOOP
# ---------------------------------------------------------
def run_consumer():
    consumer = get_kafka_consumer()
    print("👂 Consumer is listening for messages on topic: stock-data")

    # buffer[symbol][date_string] = {"news_items": [...], "price_data": {...}}
    buffer = defaultdict(lambda: defaultdict(lambda: {"news_items": [], "price_data": None}))

    for message in consumer:
        data     = message.value
        msg_type = data.get("type")

        if msg_type == "end_of_fetch":
            print("🏁 End of fetch signal received. Processing...")

            for sym, dates in buffer.items():

                # --------------------------------------------------
                # STEP 1: Run model on dates that have news
                # --------------------------------------------------
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

                # --------------------------------------------------
                # STEP 2: Backfill price for dates that already have
                # sentiment but were missing price data (market was
                # still open when they were first written).
                # --------------------------------------------------
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

        if msg_type == "news":
            dt_str = data.get("date")
            buffer[symbol][dt_str]["news_items"].append(data)

        elif msg_type == "price":
            dt_str = data["date"]
            buffer[symbol][dt_str]["price_data"] = data


if __name__ == "__main__":
    run_consumer()
