import time

from app.fetcher import Item, store_items


def add(conn, cfg, source_id, publisher, topic, title, summary="", hours_ago=1.0, region=None, paywall=False):
    now = int(time.time())
    source = {"id": source_id, "publisher": publisher, "topic": topic, "region": region}
    slug = abs(hash((source_id, title))) % 10**9
    store_items(conn, source, [Item(url=f"https://{source_id}.test/{slug}", title=title, summary=summary,
                                    image_url=None, published_at=now - int(hours_ago * 3600),
                                    paywall=paywall)], now, cfg)
    return conn.execute("SELECT id FROM articles ORDER BY id DESC LIMIT 1").fetchone()[0]
