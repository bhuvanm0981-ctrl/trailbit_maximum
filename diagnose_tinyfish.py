"""Check that TINYFISH_API_KEY works. Run from the repository root:  python diagnose_tinyfish.py"""

import asyncio

from backend.services.tinyfish_api import TinyFishClient, TinyFishError
from backend.text import contributing_highlights

GUIDE = "https://github.com/psf/requests/blob/main/.github/CONTRIBUTING.md"


async def main() -> int:
    client = TinyFishClient()
    if not client.configured:
        print("ERROR: TINYFISH_API_KEY is not set (put it in .env or the environment).")
        return 1
    try:
        results = await client.search("python requests library contributing guide", include_domains="github.com")
        print(f"Search OK: {len(results)} results")
        for item in results[:3]:
            print("  ", item.get("title"), "->", item.get("url"))

        text = await client.fetch_text(GUIDE, include_selectors=["article.markdown-body"])
        print(f"Fetch OK: {len(text)} characters from {GUIDE}")
        for rule in contributing_highlights(text):
            print("   -", rule)
    except TinyFishError as error:
        print("ERROR:", error)
        return 1
    finally:
        await client.aclose()
    return 0


if __name__ == "__main__":
    raise SystemExit(asyncio.run(main()))
