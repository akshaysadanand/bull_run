"""Quick test of the scraper against real tickers."""

from scraper import scrape_news

print("=== Testing AAPL ===")
articles = scrape_news("AAPL")
print(f"Found {len(articles)} articles")
for i, a in enumerate(articles[:5]):
    print(f"\n[{i}]")
    print(f"  title: {a['title']}")
    print(f"  source: {a['source']}")
    print(f"  date: {a['date']}")
    print(f"  url: {a['url']}")
    print(f"  snippet: {a['snippet']}")

print("\n\n=== Testing TSLA ===")
articles = scrape_news("TSLA")
print(f"Found {len(articles)} articles")
for i, a in enumerate(articles[:3]):
    print(f"\n[{i}]")
    print(f"  title: {a['title']}")
    print(f"  source: {a['source']}")
    print(f"  date: {a['date']}")
    print(f"  url: {a['url']}")

print("\n\n=== Testing INVALID ===")
articles = scrape_news("INVALIDTICKER123")
print(f"Found {len(articles)} articles (expected 0)")

print("\n\n=== Testing MSFT ===")
articles = scrape_news("MSFT")
print(f"Found {len(articles)} articles")
for i, a in enumerate(articles[:3]):
    print(f"\n[{i}]")
    print(f"  title: {a['title']}")
    print(f"  source: {a['source']}")
    print(f"  date: {a['date']}")
    print(f"  url: {a['url']}")
