"""
L69: Job Scraper — Real Swiss Job Listings
==========================================
Fetches live job listings from Swiss job portals.
Primary source: jobs.ch public API (no key required).

Usage:
    scraper = JobScraper()
    jobs = await scraper.search("business analyst", location="zurich")
"""

import hashlib
import json
import logging
import os
import time

logger = logging.getLogger(__name__)

# In-memory cache: {cache_key: (timestamp, results)}
_cache: dict = {}
CACHE_TTL = int(os.getenv("JOB_SCRAPER_CACHE_TTL", "900"))


class JobScraper:
    """Fetch real job listings from Swiss job portals."""

    JOBS_CH_API = os.getenv("JOBS_CH_API_URL", "https://www.jobs.ch/api/v1/public/search")
    USER_AGENT = os.getenv(
        "JTP_USER_AGENT",
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
        "AppleWebKit/537.36 (KHTML, like Gecko) "
        "Chrome/120.0.0.0 Safari/537.36",
    )

    def __init__(self, cache_ttl: int = CACHE_TTL):
        self.cache_ttl = cache_ttl

    async def search(
        self,
        query: str,
        location: str = "",
        limit: int = 10,
    ) -> list[dict]:
        """Search Swiss job portals for matching positions.

        Args:
            query: Job title or keywords (e.g., "business analyst")
            location: City or region (e.g., "zurich")
            limit: Maximum results to return

        Returns:
            List of job dicts with: id, title, company, location, url,
            published, source
        """
        if not query or not query.strip():
            return []

        # Check cache
        cache_key = self._cache_key(query, location)
        cached = _cache.get(cache_key)
        if cached and (time.time() - cached[0]) < self.cache_ttl:
            logger.info("L69: Cache hit for '%s' (%d jobs)", query, len(cached[1]))
            return cached[1][:limit]

        # Fetch from sources
        results = []
        for source_fn in [self._fetch_jobs_ch]:
            try:
                jobs = await source_fn(query, location, limit)
                results.extend(jobs)
            except Exception as exc:
                logger.warning("L69: Source %s failed: %s", source_fn.__name__, exc)
                continue

        # Deduplicate by title+company
        seen = set()
        unique = []
        for job in results:
            key = (job.get("title", "").lower(), job.get("company", "").lower())
            if key not in seen:
                seen.add(key)
                unique.append(job)

        # Cache results
        _cache[cache_key] = (time.time(), unique)
        logger.info("L69: Fetched %d unique jobs for '%s'", len(unique), query)

        return unique[:limit]

    async def _fetch_jobs_ch(self, query: str, location: str, limit: int) -> list[dict]:
        """Fetch jobs from jobs.ch public API."""
        import httpx

        params = {"query": query, "rows": min(limit, 20)}
        if location:
            params["location"] = location

        async with httpx.AsyncClient(timeout=10.0) as client:
            resp = await client.get(
                self.JOBS_CH_API,
                params=params,
                headers={"User-Agent": self.USER_AGENT},
            )
            resp.raise_for_status()

        data = resp.json()
        documents = data.get("documents", [])

        jobs = []
        for doc in documents:
            job = {
                "id": hashlib.md5(  # nosec B324
                    # nosec B324
                    json.dumps(doc, default=str, sort_keys=True).encode()
                ).hexdigest()[:12],
                "title": doc.get("title", "Unknown"),
                "company": doc.get("company_name", "Unknown"),
                "location": doc.get("place", "Switzerland"),
                "published": (doc.get("publication_date", "") or "")[:10],
                "url": doc.get("url", ""),
                "source": "jobs.ch",
            }
            jobs.append(job)

        return jobs

    @staticmethod
    def _cache_key(query: str, location: str) -> str:
        raw = f"{query.lower().strip()}|{location.lower().strip()}"
        return hashlib.md5(  # nosec B324
            # nosec B324
            raw.encode()
        ).hexdigest()
