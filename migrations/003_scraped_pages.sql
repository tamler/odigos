CREATE TABLE IF NOT EXISTS scraped_pages (
    id TEXT PRIMARY KEY,
    url TEXT NOT NULL,
    title TEXT,
    summary TEXT,
    scraped_at TEXT NOT NULL DEFAULT (datetime('now'))
);

CREATE INDEX IF NOT EXISTS idx_scraped_pages_url ON scraped_pages(url);
CREATE INDEX IF NOT EXISTS idx_scraped_pages_scraped_at ON scraped_pages(scraped_at);
