"""
L69+L64: Job Scraper — Multi-Source Swiss Job Listings
======================================================
Fetches live job listings from 5 Swiss job portals:
  1. jobs.ch   — public API (no key required)
  2. LinkedIn  — official REST API (LINKEDIN_CLIENT_ID + SECRET)
  3. Indeed.ch — Firecrawl web scraping with source-specific parser
  4. Jobup.ch  — Firecrawl web scraping with extended JS wait
  5. Glassdoor — Firecrawl web scraping with source-specific parser

Each source runs concurrently (asyncio.gather) with independent error handling.
Sources that fail silently return [] — the user always gets results from working sources.

Usage:
    scraper = JobScraper()
    jobs = await scraper.search("business analyst", location="zurich")
    jobs = await scraper.search("data scientist", location="basel", sources=["linkedin", "jobs.ch"])
"""

import asyncio
import hashlib
import json
import logging
import os
import re
import time
import urllib.parse

logger = logging.getLogger(__name__)

# In-memory cache: {cache_key: (timestamp, results)}
_cache: dict = {}
CACHE_TTL = int(os.getenv("JOB_SCRAPER_CACHE_TTL", "900"))

# API keys
FIRECRAWL_API_KEY = os.getenv("FIRECRAWL_API_KEY", "")
FIRECRAWL_API_URL = os.getenv("FIRECRAWL_API_URL", "https://api.firecrawl.dev/v1")
LINKEDIN_CLIENT_ID = os.getenv("LINKEDIN_CLIENT_ID", "")
LINKEDIN_CLIENT_SECRET = os.getenv("LINKEDIN_CLIENT_SECRET", "")

ALL_SOURCES = ["jobs.ch", "linkedin", "indeed", "jobup.ch", "glassdoor"]

# Navigation/junk patterns to filter from scraped results
_JUNK_TITLES = re.compile(
    r"(?i)^(skip to|post your|sign in|log in|cookie|privacy|terms|about us|"
    r"help center|contact|menu|home|back to|next page|previous|for employers|"
    r"find out more|see more|show more|load more|view all|create alert|"
    r"upload.*resume|get started|download app|install|subscribe|"
    r"salary|salaries|review|overview|benefit|photo|"
    r"questions.*answers|hybrid work|job type|"
    r".*logo$|.*jobs$|.*@|.*\|.*\|)"  # Pipe-separated junk (Indeed salary tables)
)

# Swiss location keywords for validation
_SWISS_LOCATIONS = {
    "zurich", "zürich", "geneva", "genève", "genf", "basel", "bern",
    "lausanne", "lucerne", "luzern", "winterthur", "st. gallen", "st gallen",
    "lugano", "biel", "thun", "zug", "fribourg", "freiburg", "schaffhausen",
    "chur", "aarau", "olten", "baden", "dietikon", "uster", "wädenswil",
    "switzerland", "schweiz", "suisse", "svizzera", "remote", "hybrid",
}


class JobScraper:
    """Fetch real job listings from multiple Swiss job portals."""

    JOBS_CH_API = os.getenv("JOBS_CH_API_URL", "https://www.jobs.ch/api/v1/public/search")
    USER_AGENT = os.getenv(
        "JTP_USER_AGENT",
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
        "AppleWebKit/537.36 (KHTML, like Gecko) "
        "Chrome/120.0.0.0 Safari/537.36",
    )

    def __init__(self, cache_ttl: int = CACHE_TTL):
        self.cache_ttl = cache_ttl
        self._firecrawl_ok = bool(FIRECRAWL_API_KEY)
        self._linkedin_ok = bool(LINKEDIN_CLIENT_ID and LINKEDIN_CLIENT_SECRET)
        self._linkedin_token: str = ""
        self._linkedin_token_exp: float = 0

    # Swiss 4-language role translations — same as gateway's _ROLE_TRANSLATIONS
    _ROLE_TRANSLATIONS = {
        "business analyst": {"de": "Business Analyst", "fr": "Analyste d'affaires", "it": "Analista aziendale"},
        "project manager": {"de": "Projektleiter", "fr": "Chef de projet", "it": "Responsabile di progetto"},
        "software engineer": {"de": "Softwareentwickler", "fr": "Ingénieur logiciel", "it": "Ingegnere del software"},
        "data scientist": {"de": "Datenwissenschaftler", "fr": "Scientifique des données", "it": "Scienziato dei dati"},
        "product manager": {"de": "Produktmanager", "fr": "Chef de produit", "it": "Product Manager"},
        "devops engineer": {"de": "DevOps-Ingenieur", "fr": "Ingénieur DevOps", "it": "Ingegnere DevOps"},
        "ux designer": {"de": "UX-Designer", "fr": "Designer UX", "it": "Designer UX"},
        "frontend developer": {"de": "Frontend-Entwickler", "fr": "Développeur frontend", "it": "Sviluppatore frontend"},
        "backend developer": {"de": "Backend-Entwickler", "fr": "Développeur backend", "it": "Sviluppatore backend"},
        "full stack developer": {"de": "Fullstack-Entwickler", "fr": "Développeur full stack", "it": "Sviluppatore full stack"},
        "data engineer": {"de": "Dateningenieur", "fr": "Ingénieur de données", "it": "Ingegnere dei dati"},
        "machine learning engineer": {"de": "Machine-Learning-Ingenieur", "fr": "Ingénieur ML", "it": "Ingegnere ML"},
        "scrum master": {"de": "Scrum Master", "fr": "Scrum Master", "it": "Scrum Master"},
        "team lead": {"de": "Teamleiter", "fr": "Chef d'équipe", "it": "Capo squadra"},
        "system administrator": {"de": "Systemadministrator", "fr": "Administrateur système", "it": "Amministratore di sistema"},
        "network engineer": {"de": "Netzwerkingenieur", "fr": "Ingénieur réseau", "it": "Ingegnere di rete"},
        "security analyst": {"de": "Sicherheitsanalyst", "fr": "Analyste sécurité", "it": "Analista sicurezza"},
        "cloud architect": {"de": "Cloud-Architekt", "fr": "Architecte cloud", "it": "Architetto cloud"},
        "marketing manager": {"de": "Marketingleiter", "fr": "Responsable marketing", "it": "Responsabile marketing"},
        "sales manager": {"de": "Verkaufsleiter", "fr": "Directeur des ventes", "it": "Direttore vendite"},
        "hr manager": {"de": "HR-Manager", "fr": "Responsable RH", "it": "Responsabile HR"},
        "accountant": {"de": "Buchhalter", "fr": "Comptable", "it": "Contabile"},
        "financial analyst": {"de": "Finanzanalyst", "fr": "Analyste financier", "it": "Analista finanziario"},
        "consultant": {"de": "Berater", "fr": "Consultant", "it": "Consulente"},
    }

    def _get_multilingual_queries(self, query: str) -> list[str]:
        """Generate search queries in all 4 Swiss languages.

        Switzerland has 4 official languages — job titles are posted in the
        local language of the canton. A comprehensive search must cover all 4.
        """
        queries = [query]
        query_lower = query.lower().strip()
        for en_role, translations in self._ROLE_TRANSLATIONS.items():
            if en_role in query_lower:
                for lang, translated in translations.items():
                    q = query_lower.replace(en_role, translated)
                    if q.lower() not in [existing.lower() for existing in queries]:
                        queries.append(q)
                break
        return queries

    # ════════════════════════════════════════════════════════════════════════
    #  Public API
    # ════════════════════════════════════════════════════════════════════════

    async def search(
        self,
        query: str,
        location: str = "",
        limit: int = 10,
        sources: list[str] | None = None,
    ) -> list[dict]:
        """Search multiple Swiss job portals concurrently."""
        if not query or not query.strip():
            return []

        cache_key = self._cache_key(query, location, sources)
        cached = _cache.get(cache_key)
        if cached and (time.time() - cached[0]) < self.cache_ttl:
            logger.info("L69: Cache hit for '%s' (%d jobs)", query, len(cached[1]))
            return cached[1][:limit]

        requested = [s.lower() for s in (sources or ALL_SOURCES)]

        # Generate multilingual queries (EN + DE + FR + IT)
        queries = self._get_multilingual_queries(query)
        logger.info("L64: Searching %d sources × %d languages for '%s'", len(requested), len(queries), query)

        source_map = {
            "jobs.ch": ("api", self._fetch_jobs_ch),
            "linkedin": ("linkedin_api", self._fetch_linkedin),
            "indeed": ("firecrawl", self._fetch_indeed),
            "jobup.ch": ("firecrawl", self._fetch_jobup),
            "glassdoor": ("firecrawl", self._fetch_glassdoor),
        }

        tasks = []
        for src in requested:
            entry = source_map.get(src)
            if not entry:
                continue
            kind, fn = entry
            if kind == "firecrawl" and not self._firecrawl_ok:
                logger.debug("L64: Skipping %s (no FIRECRAWL_API_KEY)", src)
                continue
            if kind == "linkedin_api" and not self._linkedin_ok and not self._firecrawl_ok:
                logger.debug("L64: Skipping linkedin (no credentials)")
                continue
            # For Firecrawl sources: only search primary query (rate limit protection)
            # For jobs.ch API: search all language variants (free, no rate limit)
            if kind == "api":
                for q in queries:
                    tasks.append(self._safe_fetch(fn, q, location, limit, src))
            else:
                # Firecrawl: primary query only (avoid 408 timeouts from too many concurrent requests)
                tasks.append(self._safe_fetch(fn, query, location, limit, src))

        results = []
        if tasks:
            source_results = await asyncio.gather(*tasks)
            for jobs in source_results:
                results.extend(jobs)

        # Deduplicate by normalized title+company
        seen = set()
        unique = []
        for job in results:
            key = (
                re.sub(r"\s+", " ", job.get("title", "")).lower().strip(),
                re.sub(r"\s+", " ", job.get("company", "")).lower().strip(),
            )
            if key not in seen and key[0] and key[1]:
                seen.add(key)
                unique.append(job)

        _cache[cache_key] = (time.time(), unique)
        src_counts = {}
        for j in unique:
            s = j.get("source", "?")
            src_counts[s] = src_counts.get(s, 0) + 1
        logger.info("L64: %d unique jobs for '%s' — %s", len(unique), query, src_counts)

        return unique[:limit]

    async def _safe_fetch(self, fn, query, location, limit, source_name):
        try:
            return await fn(query, location, limit)
        except Exception as exc:
            logger.warning("L64: Source %s failed: %s", source_name, exc)
            return []

    # ════════════════════════════════════════════════════════════════════════
    #  Source 1: jobs.ch (public API — always works)
    # ════════════════════════════════════════════════════════════════════════

    async def _fetch_jobs_ch(self, query: str, location: str, limit: int) -> list[dict]:
        import httpx

        params = {"query": query, "rows": min(limit, 20)}
        if location:
            params["location"] = location

        async with httpx.AsyncClient(timeout=10.0) as client:
            resp = await client.get(
                self.JOBS_CH_API, params=params,
                headers={"User-Agent": self.USER_AGENT},
            )
            resp.raise_for_status()

        documents = resp.json().get("documents", [])
        return [
            {
                "id": self._make_id(doc),
                "title": doc.get("title", "Unknown"),
                "company": doc.get("company_name", "Unknown"),
                "location": doc.get("place", "Switzerland"),
                "published": (doc.get("publication_date", "") or "")[:10],
                "url": doc.get("url", ""),
                "source": "jobs.ch",
            }
            for doc in documents
        ]

    # ════════════════════════════════════════════════════════════════════════
    #  Source 2: LinkedIn (official REST API — OAuth2 client credentials)
    # ════════════════════════════════════════════════════════════════════════

    async def _get_linkedin_token(self) -> str:
        """Get or refresh LinkedIn OAuth2 access token."""
        if self._linkedin_token and time.time() < self._linkedin_token_exp:
            return self._linkedin_token

        import httpx

        async with httpx.AsyncClient(timeout=10.0) as client:
            resp = await client.post(
                "https://www.linkedin.com/oauth/v2/accessToken",
                data={
                    "grant_type": "client_credentials",
                    "client_id": LINKEDIN_CLIENT_ID,
                    "client_secret": LINKEDIN_CLIENT_SECRET,
                },
                headers={"Content-Type": "application/x-www-form-urlencoded"},
            )
            resp.raise_for_status()

        data = resp.json()
        self._linkedin_token = data["access_token"]
        self._linkedin_token_exp = time.time() + data.get("expires_in", 3600) - 60
        logger.info("L64: LinkedIn OAuth token acquired (expires in %ds)", data.get("expires_in", 0))
        return self._linkedin_token

    async def _fetch_linkedin(self, query: str, location: str, limit: int) -> list[dict]:
        """Fetch jobs from LinkedIn Jobs API.

        LinkedIn's Job Search API requires partner-level access.
        If the official API fails (403/401), fall back to Firecrawl
        scraping of LinkedIn's public job search pages.
        """
        import httpx

        # Try official API first
        try:
            token = await self._get_linkedin_token()
            async with httpx.AsyncClient(timeout=15.0) as client:
                resp = await client.get(
                    "https://api.linkedin.com/v2/jobSearch",
                    params={
                        "keywords": query,
                        "location": location or "Switzerland",
                        "count": min(limit, 25),
                    },
                    headers={"Authorization": f"Bearer {token}"},
                )
                if resp.status_code == 200:
                    data = resp.json()
                    jobs = []
                    for elem in data.get("elements", []):
                        jobs.append({
                            "id": self._make_id(elem),
                            "title": elem.get("title", "Unknown"),
                            "company": elem.get("companyName", "Unknown"),
                            "location": elem.get("formattedLocation", location or "Switzerland"),
                            "published": "",
                            "url": elem.get("jobPostingUrl", ""),
                            "source": "linkedin",
                        })
                    if jobs:
                        logger.info("L64: LinkedIn API returned %d jobs", len(jobs))
                        return jobs
                    # Empty result — fall through to Firecrawl
                else:
                    logger.info("L64: LinkedIn API returned %d — trying Firecrawl fallback", resp.status_code)
        except Exception as e:
            logger.info("L64: LinkedIn API unavailable (%s) — trying Firecrawl fallback", e)

        # Fallback: Firecrawl scrape of LinkedIn public job pages
        if not self._firecrawl_ok:
            return []

        # LinkedIn public job search (no login required for viewing)
        encoded_query = urllib.parse.quote(query)
        encoded_loc = urllib.parse.quote(location or "Switzerland")
        url = f"https://www.linkedin.com/jobs/search/?keywords={encoded_query}&location={encoded_loc}"

        return await self._firecrawl_scrape_source(url, "linkedin", limit, wait_ms=5000)

    # ════════════════════════════════════════════════════════════════════════
    #  Source 3: Indeed.ch (Firecrawl with source-specific parsing)
    # ════════════════════════════════════════════════════════════════════════

    async def _fetch_indeed(self, query: str, location: str, limit: int) -> list[dict]:
        encoded_q = urllib.parse.quote(query)
        encoded_l = urllib.parse.quote(location or "Switzerland")
        url = f"https://ch.indeed.com/jobs?q={encoded_q}&l={encoded_l}"
        return await self._firecrawl_scrape_source(url, "indeed", limit, wait_ms=4000)

    # ════════════════════════════════════════════════════════════════════════
    #  Source 4: Jobup.ch (Firecrawl with extended JS wait + scroll)
    # ════════════════════════════════════════════════════════════════════════

    async def _fetch_jobup(self, query: str, location: str, limit: int) -> list[dict]:
        encoded_q = urllib.parse.quote(query)
        url = f"https://www.jobup.ch/en/jobs/?term={encoded_q}"
        if location:
            url += f"&location={urllib.parse.quote(location)}"
        # Jobup.ch is heavily JS-rendered — need longer wait + scroll action
        return await self._firecrawl_scrape_source(url, "jobup.ch", limit, wait_ms=6000)

    # ════════════════════════════════════════════════════════════════════════
    #  Source 5: Glassdoor (Firecrawl with source-specific parsing)
    # ════════════════════════════════════════════════════════════════════════

    async def _fetch_glassdoor(self, query: str, location: str, limit: int) -> list[dict]:
        encoded_q = urllib.parse.quote(query)
        url = f"https://www.glassdoor.com/Job/switzerland-{query.replace(' ', '-')}-jobs-SRCH_IL.0,11_IN226.htm"
        return await self._firecrawl_scrape_source(url, "glassdoor", limit, wait_ms=4000)

    # ════════════════════════════════════════════════════════════════════════
    #  Firecrawl Engine (shared by Indeed, Jobup, Glassdoor, LinkedIn fallback)
    # ════════════════════════════════════════════════════════════════════════

    async def _firecrawl_scrape_source(
        self, url: str, source: str, limit: int, wait_ms: int = 3000
    ) -> list[dict]:
        """Scrape a job portal via Firecrawl and parse with source-specific logic."""
        import httpx

        headers = {
            "Authorization": f"Bearer {FIRECRAWL_API_KEY}",
            "Content-Type": "application/json",
        }

        payload = {
            "url": url,
            "formats": ["markdown"],
            "onlyMainContent": True,
            "waitFor": wait_ms,
            "timeout": 20000,
        }

        async with httpx.AsyncClient(timeout=25.0) as client:
            resp = await client.post(
                f"{FIRECRAWL_API_URL}/scrape",
                json=payload,
                headers=headers,
            )
            if resp.status_code == 403:
                logger.warning("L64: Firecrawl 403 for %s — site blocks scraping", source)
                return []
            resp.raise_for_status()

        data = resp.json()
        if not data.get("success"):
            logger.warning("L64: Firecrawl fail for %s: %s", source, data.get("error", "?"))
            return []

        markdown = data.get("data", {}).get("markdown", "")
        if not markdown or len(markdown) < 100:
            logger.warning("L64: Firecrawl returned too little content for %s (%d chars)", source, len(markdown))
            return []

        # Use source-specific parser
        parser = {
            "indeed": self._parse_indeed,
            "glassdoor": self._parse_glassdoor,
            "jobup.ch": self._parse_jobup_md,
            "linkedin": self._parse_linkedin_md,
        }.get(source, self._parse_generic)

        jobs = parser(markdown, limit)
        logger.info("L64: Parsed %d jobs from %s (%d chars markdown)", len(jobs), source, len(markdown))
        return jobs

    # ── Source-specific parsers ─────────────────────────────────────────────

    def _parse_indeed(self, markdown: str, limit: int) -> list[dict]:
        """Parse Indeed.ch markdown — jobs appear as linked titles followed by company + location."""
        jobs = []
        lines = markdown.split("\n")
        i = 0
        while i < len(lines) and len(jobs) < limit:
            line = lines[i].strip()
            # Indeed job titles are bold links: [**Title**](url) or **[Title](url)**
            match = re.search(r'\[([^\]]{10,120})\]\((https?://[^\)]+)\)', line)
            if match:
                title = re.sub(r'[*_]', '', match.group(1)).strip()
                url = match.group(2)

                if self._is_junk_title(title):
                    i += 1
                    continue

                # Next non-empty lines: company, location
                company = ""
                location = ""
                for j in range(i + 1, min(i + 5, len(lines))):
                    next_line = re.sub(r'[*_#\[\]()]', '', lines[j]).strip()
                    if not next_line:
                        continue
                    if not company and len(next_line) < 80 and not self._is_junk_title(next_line):
                        company = next_line
                    elif not location and self._looks_like_location(next_line):
                        location = next_line
                        break

                if company:
                    jobs.append({
                        "id": self._make_id({"title": title, "url": url}),
                        "title": title,
                        "company": company,
                        "location": location or "Switzerland",
                        "published": "",
                        "url": url if url.startswith("http") else f"https://ch.indeed.com{url}",
                        "source": "indeed",
                    })
            i += 1

        return jobs

    def _parse_glassdoor(self, markdown: str, limit: int) -> list[dict]:
        """Parse Glassdoor markdown.

        Actual Glassdoor structure (verified from scrape):
          L48: - ![CompanyName Logo](image_url)       ← company in alt text
          L56: CompanyName                             ← company plain text
          L58: 4.0                                     ← rating (skip)
          L66: [JobTitle](job-listing-url)             ← job title link
          L68: Location                                ← city
          L78: Description snippet                     ← description

        Company name appears ~10-18 lines BEFORE the job link.
        Also extractable from logo alt text: ![CompanyName Logo](...)
        """
        jobs = []
        lines = markdown.split("\n")
        i = 0
        while i < len(lines) and len(jobs) < limit:
            line = lines[i].strip()
            # Match job title links — Glassdoor uses de.glassdoor.ch, glassdoor.com
            match = re.search(r'\[([^\]]{10,150})\]\((https?://[^\)]*glassdoor[^\)]*job-listing[^\)]*)\)', line)
            if not match:
                match = re.search(r'\[([^\]]{10,150})\]\((https?://[^\)]*glassdoor[^\)]*jl=\d+[^\)]*)\)', line)
            if match:
                title = re.sub(r'[*_]', '', match.group(1)).strip()
                url = match.group(2)

                if self._is_junk_title(title):
                    i += 1
                    continue

                # Look backwards up to 20 lines for company name
                company = ""
                for j in range(max(0, i - 20), i):
                    candidate = lines[j].strip()

                    # Method 1: Extract from logo alt text ![CompanyName Logo](url)
                    logo_match = re.search(r'!\[([^\]]+?)\s*Logo\]', candidate)
                    if logo_match:
                        company = logo_match.group(1).strip()
                        continue

                    # Method 2: Plain company name line (non-empty, non-rating, non-junk)
                    cleaned = re.sub(r'[*_#\[\]()!]', '', candidate).strip()
                    cleaned = re.sub(r'https?://\S+', '', cleaned).strip()
                    if not cleaned or len(cleaned) < 3 or len(cleaned) > 80:
                        continue
                    # Skip ratings (e.g., "4.0", "3.5")
                    if re.match(r'^\d+\.\d+$', cleaned):
                        continue
                    # Skip junk
                    if self._is_junk_title(cleaned):
                        continue
                    # Skip bullet markers
                    if cleaned.startswith('-') and len(cleaned) < 5:
                        continue
                    # This could be the company name — keep the LAST valid one before the job link
                    company = cleaned

                # Look forward for location (usually 1-2 lines after)
                location = ""
                for j in range(i + 1, min(i + 4, len(lines))):
                    candidate = re.sub(r'[*_#\[\]()]', '', lines[j]).strip()
                    if candidate and len(candidate) > 2 and len(candidate) < 60:
                        if self._looks_like_location(candidate) or (len(candidate) < 30 and not self._is_junk_title(candidate)):
                            location = candidate
                            break

                if title:
                    # Clean company name: strip leading "- " from markdown lists
                    clean_company = re.sub(r'^[-•]\s*', '', company).strip() if company else "Unknown"
                    jobs.append({
                        "id": self._make_id({"title": title, "url": url}),
                        "title": title,
                        "company": clean_company or "Unknown",
                        "location": location or "Switzerland",
                        "published": "",
                        "url": url,
                        "source": "glassdoor",
                    })
            i += 1

        return jobs

    def _parse_jobup_md(self, markdown: str, limit: int) -> list[dict]:
        """Parse Jobup.ch markdown — structured cards with title, company, location."""
        jobs = []
        lines = markdown.split("\n")
        i = 0
        while i < len(lines) and len(jobs) < limit:
            line = lines[i].strip()
            match = re.search(r'\[([^\]]{10,120})\]\((https?://[^\)]*jobup[^\)]*)\)', line)
            if match:
                title = re.sub(r'[*_]', '', match.group(1)).strip()
                url = match.group(2)

                if self._is_junk_title(title):
                    i += 1
                    continue

                company = ""
                location = ""
                for j in range(i + 1, min(i + 5, len(lines))):
                    next_line = re.sub(r'[*_#\[\]()]', '', lines[j]).strip()
                    if not next_line:
                        continue
                    if not company and len(next_line) < 80 and not self._is_junk_title(next_line):
                        company = next_line
                    elif not location and self._looks_like_location(next_line):
                        location = next_line
                        break

                if title and len(title) > 10:
                    jobs.append({
                        "id": self._make_id({"title": title, "url": url}),
                        "title": title,
                        "company": company or "Unknown",
                        "location": location or "Switzerland",
                        "published": "",
                        "url": url if url.startswith("http") else f"https://www.jobup.ch{url}",
                        "source": "jobup.ch",
                    })
            i += 1

        return jobs

    def _parse_linkedin_md(self, markdown: str, limit: int) -> list[dict]:
        """Parse LinkedIn public job search markdown."""
        jobs = []
        lines = markdown.split("\n")
        i = 0
        while i < len(lines) and len(jobs) < limit:
            line = lines[i].strip()
            match = re.search(r'\[([^\]]{10,120})\]\((https?://[^\)]*linkedin[^\)]*)\)', line)
            if match:
                title = re.sub(r'[*_]', '', match.group(1)).strip()
                url = match.group(2)

                if self._is_junk_title(title):
                    i += 1
                    continue

                company = ""
                location = ""
                for j in range(i + 1, min(i + 5, len(lines))):
                    next_line = re.sub(r'[*_#\[\]()]', '', lines[j]).strip()
                    next_line = re.sub(r'https?://\S+', '', next_line).strip()
                    if not next_line:
                        continue
                    if not company and len(next_line) < 80 and not self._is_junk_title(next_line):
                        company = next_line
                    elif not location and self._looks_like_location(next_line):
                        location = next_line
                        break

                if title and len(title) > 10:
                    jobs.append({
                        "id": self._make_id({"title": title, "url": url}),
                        "title": title,
                        "company": company or "Unknown",
                        "location": location or "Switzerland",
                        "published": "",
                        "url": url,
                        "source": "linkedin",
                    })
            i += 1

        return jobs

    def _parse_generic(self, markdown: str, limit: int) -> list[dict]:
        """Fallback parser for unknown sources."""
        return self._parse_indeed(markdown, limit)  # Reuse Indeed parser as generic

    # ── Filtering helpers ───────────────────────────────────────────────────

    @staticmethod
    def _is_junk_title(text: str) -> bool:
        """Return True if text looks like navigation/UI element, not a job title."""
        if len(text) < 8 or len(text) > 150:
            return True
        return bool(_JUNK_TITLES.match(text))

    @staticmethod
    def _looks_like_location(text: str) -> bool:
        """Return True if text looks like a location string."""
        text_lower = text.lower()
        return any(loc in text_lower for loc in _SWISS_LOCATIONS) or "," in text

    # ── Utilities ───────────────────────────────────────────────────────────

    @staticmethod
    def _make_id(data: dict) -> str:
        raw = json.dumps(data, default=str, sort_keys=True)
        return hashlib.md5(raw.encode()).hexdigest()[:12]  # nosec B324

    @staticmethod
    def _cache_key(query: str, location: str, sources: list[str] | None = None) -> str:
        src_str = ",".join(sorted(sources)) if sources else "all"
        raw = f"{query.lower().strip()}|{location.lower().strip()}|{src_str}"
        return hashlib.md5(raw.encode()).hexdigest()  # nosec B324
