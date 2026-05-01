-- db/init/01-schema.sql
-- =============================================
-- Schema for dual-sentiment stock news analysis
-- Alpha Vantage (baseline) + Local FinBERT model on Finnhub articles
-- =============================================

CREATE TABLE IF NOT EXISTS articles (
    id                  SERIAL PRIMARY KEY,
    symbol              TEXT        NOT NULL,
    published_at        TIMESTAMP   NOT NULL,
    title               TEXT        NOT NULL,
    summary             TEXT,
    source              TEXT,
    url                 TEXT,
    news_source         TEXT        DEFAULT 'finnhub',   -- 'finnhub' or future sources
    av_sentiment        NUMERIC,                         -- NULL for Finnhub articles
    model_sentiment     NUMERIC,                         -- from local transformer
    model_confidence    NUMERIC,
    quality_score       NUMERIC,                         -- optional future use
    created_at          TIMESTAMP   DEFAULT NOW()
);

CREATE INDEX IF NOT EXISTS idx_articles_symbol_published 
    ON articles (symbol, published_at DESC);

CREATE INDEX IF NOT EXISTS idx_articles_symbol_source 
    ON articles (symbol, news_source, published_at DESC);

-- Daily aggregated record (core table for dashboard)
CREATE TABLE IF NOT EXISTS stock_daily (
    symbol                TEXT      NOT NULL,
    date                  DATE      NOT NULL,
    open_price            NUMERIC,
    close_price           NUMERIC,
    volume                BIGINT,
    
    -- Alpha Vantage baseline sentiment
    av_sentiment          NUMERIC,
    
    -- Local FinBERT model on Finnhub articles
    finbert_sentiment     NUMERIC,
    finbert_confidence    NUMERIC,
    finbert_explanation   TEXT,
    
    article_count         INTEGER   DEFAULT 0,   -- total Finnhub articles before/after filter
    created_at            TIMESTAMP DEFAULT NOW(),
    
    PRIMARY KEY (symbol, date)
);

CREATE INDEX IF NOT EXISTS idx_stock_daily_symbol_date 
    ON stock_daily (symbol, date DESC);

CREATE INDEX IF NOT EXISTS idx_stock_daily_symbol_av 
    ON stock_daily (symbol, av_sentiment);

CREATE INDEX IF NOT EXISTS idx_stock_daily_symbol_finbert 
    ON stock_daily (symbol, finbert_sentiment);

-- Helpful view for dashboards (includes delta)
CREATE OR REPLACE VIEW daily_sentiment_view AS
SELECT 
    symbol,
    date,
    open_price,
    close_price,
    volume,
    av_sentiment,
    finbert_sentiment,
    finbert_confidence,
    finbert_explanation,
    article_count,
    ROUND((finbert_sentiment - av_sentiment)::numeric, 4) AS sentiment_delta,
    CASE 
        WHEN finbert_sentiment > av_sentiment + 0.05 THEN 'Model more bullish'
        WHEN finbert_sentiment < av_sentiment - 0.05 THEN 'Model more bearish'
        WHEN finbert_sentiment IS NOT NULL AND av_sentiment IS NOT NULL THEN 'Aligned'
        ELSE 'Insufficient data'
    END AS sentiment_alignment
FROM stock_daily
ORDER BY symbol, date DESC;