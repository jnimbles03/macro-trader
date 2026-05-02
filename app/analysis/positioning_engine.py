"""Light-weight positioning engine.

In v1 this just surfaces positioning-tagged headlines + flags crowded longs.
In a later cut we'll plug COT / dealer gamma / vol-control feeds.
"""

from __future__ import annotations

from app.models.headline import HeadlineCluster


def positioning_summary(clusters: list[HeadlineCluster]) -> str:
    pos = [c for c in clusters if c.channel == "positioning"]
    if not pos:
        return "No positioning-tagged headlines in window."
    bullets = []
    for c in pos:
        for h in c.headlines:
            bullets.append(f"- {h.title} ({h.source}, {h.tier.value})")
    return "\n".join(bullets)
