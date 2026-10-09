"""RotoWire's free NFL news RSS feed -- the "why is this player hot" text
Sleeper's own trending-add counts don't carry. Read-only, stdlib only.

Each item's title is "Player Name: short headline" -- e.g. "Puka Nacua:
Making progress in recovery". Only the ~50 latest leaguewide headlines are
available, so this is a leading-indicator annotation on top of the trending
list, not a lookup that will have an entry for most players.
"""

from __future__ import annotations

import urllib.request
import xml.etree.ElementTree as ET
from typing import Dict

FEED_URL = "https://www.rotowire.com/rss/news.php?sport=NFL"


def fetch_headlines() -> Dict[str, str]:
    """`{player_name.lower(): headline}`, most recent item per player (the
    feed is newest-first, so the first title seen per name wins).
    """
    with urllib.request.urlopen(FEED_URL) as response:
        root = ET.fromstring(response.read())

    headlines: Dict[str, str] = {}
    for item in root.iter("item"):
        title = (item.findtext("title") or "").strip()
        name, _, headline = title.partition(": ")
        if not headline:
            continue
        key = name.lower()
        if key not in headlines:
            headlines[key] = headline
    return headlines
