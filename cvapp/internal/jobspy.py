from __future__ import annotations

import importlib
from typing import Any

from ..errors import CVError, die, warn
from .web import normalize_url


DEFAULT_JOB_SITES = ["linkedin", "indeed", "zip_recruiter"]


def _load_jobspy_scraper():
    try:
        module = importlib.import_module("jobspy")
    except Exception:
        die("JobSpy is not installed. Run: python3 -m pip install -r requirements.txt")
    scraper = getattr(module, "scrape_jobs", None)
    if not callable(scraper):
        die("JobSpy installation is missing scrape_jobs(). Reinstall requirements.")
    return scraper


def _normalize_sites(sites: list[str]) -> list[str]:
    if not sites:
        return list(DEFAULT_JOB_SITES)
    cleaned: list[str] = []
    seen: set[str] = set()
    for item in sites:
        token = str(item or "").strip().lower()
        if not token or token in seen:
            continue
        seen.add(token)
        cleaned.append(token)
    return cleaned or list(DEFAULT_JOB_SITES)


def fetch_jobs(search_terms: list[str], sites: list[str], location: str, results_wanted: int, hours_old: int = 168) -> list[dict[str, Any]]:
    scraper = _load_jobspy_scraper()

    terms = [str(term).strip() for term in search_terms if str(term).strip()]
    if not terms:
        die("No AUTO_SEARCH_TERMS configured. Set terms in .cv/auto.env.")

    normalized_sites = _normalize_sites(sites)
    location_value = (location or "remote").strip() or "remote"
    rows: list[dict[str, Any]] = []
    seen_urls: set[str] = set()

    per_site_results = max(1, int(results_wanted / max(1, len(normalized_sites))))
    last_error = ""

    for term in terms:
        for site in normalized_sites:
            try:
                dataframe = scraper(
                    site_name=[site],
                    search_term=term,
                    location=location_value,
                    results_wanted=per_site_results,
                    hours_old=hours_old,
                    country_indeed="USA",
                    linkedin_fetch_description=True,
                )
            except KeyboardInterrupt:
                raise
            except Exception as exc:
                last_error = str(exc)
                warn(f"posts: JobSpy failed for site={site} term='{term}': {exc}")
                continue

            if dataframe is None:
                continue

            try:
                records: list[dict[str, Any]] = dataframe.to_dict("records")
            except Exception as exc:
                last_error = str(exc)
                warn(f"posts: JobSpy payload unreadable for site={site} term='{term}': {exc}")
                continue

            for item in records:
                raw_url = str(item.get("job_url") or item.get("url") or "").strip()
                normalized_url = normalize_url(raw_url)
                identity = normalized_url or str(item.get("id") or "").strip()
                if not identity or identity in seen_urls:
                    continue
                seen_urls.add(identity)

                description = str(item.get("description") or item.get("job_description") or "").strip()
                title = str(item.get("title") or "").strip()
                company = str(item.get("company") or "").strip()

                rows.append(
                    {
                        "external_id": str(item.get("id") or "").strip(),
                        "url": normalized_url,
                        "company": company,
                        "title": title,
                        "location": str(item.get("location") or "").strip(),
                        "description": description,
                        "source_site": str(item.get("site") or site).strip(),
                        "search_term": term,
                    }
                )

    if not rows and last_error:
        raise CVError(f"JobSpy fetch failed across all configured sites: {last_error}")

    return rows
