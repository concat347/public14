-- db/init/01-schema.sql

CREATE TABLE IF NOT EXISTS articles (
    id                SERIAL PRIMARY KEY,
    symbol            TEXT        NOT NULL,
    published_at      TIMESTAMP   NOT NULL,
    title             TEXT        NOT NULL,
    summary           TEXT,
    source            TEXT,
    url               TEXT,
    av_sentiment      FLOAT,
    model_sentiment   FLOAT,
    model_confidence  FLOAT,
    created_at        TIMESTAMP   DEFAULT NOW()
);

CREATE INDEX IF NOT EXISTS idx_articles_symbol_published
    ON articles (symbol, published_at DESC);

CREATE TABLE IF NOT EXISTS stock_daily (
    symbol               TEXT        NOT NULL,
    date                 DATE        NOT NULL,
    open_price           NUMERIC,
    close_price          NUMERIC,
    volume               BIGINT,
    finbert_sentiment    NUMERIC,
    finbert_confidence   NUMERIC,
    finbert_explanation  TEXT,
    article_count        INTEGER,
    av_sentiment         NUMERIC,
    PRIMARY KEY (symbol, date)
);

CREATE INDEX IF NOT EXISTS idx_stock_daily_symbol_date
    ON stock_daily (symbol, date DESC);
