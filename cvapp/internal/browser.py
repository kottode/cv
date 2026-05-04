from __future__ import annotations

import ipaddress
import random
import time
import urllib.parse


_SAFE_EXTERNAL_APPLY_SUFFIXES = (
    "greenhouse.io",
    "lever.co",
    "myworkdayjobs.com",
    "workday.com",
    "ashbyhq.com",
    "smartrecruiters.com",
    "workable.com",
    "icims.com",
)

_MIN_PRE_NAV_DELAY_MS = 350
_MAX_PRE_NAV_DELAY_MS = 1800
_MIN_POST_NAV_DELAY_MS = 800
_MAX_POST_NAV_DELAY_MS = 2600


def _sleep_jitter(min_ms: int, max_ms: int) -> None:
    if max_ms <= min_ms:
        time.sleep(max(0.0, min_ms / 1000.0))
        return
    time.sleep(random.uniform(min_ms / 1000.0, max_ms / 1000.0))


def _random_viewport() -> dict[str, int]:
    width = random.randint(1260, 1820)
    height = random.randint(760, 1100)
    return {"width": width, "height": height}


def _mouse_roam(page) -> None:
    viewport = page.viewport_size or {"width": 1366, "height": 900}
    width = max(320, int(viewport.get("width", 1366)))
    height = max(240, int(viewport.get("height", 900)))
    start_x = random.randint(15, max(16, width - 15))
    start_y = random.randint(15, max(16, height - 15))
    page.mouse.move(start_x, start_y, steps=random.randint(8, 20))


def _human_reading_activity(page) -> None:
    _mouse_roam(page)
    loops = random.randint(1, 3)
    for _ in range(loops):
        page.mouse.wheel(0, random.randint(120, 520))
        _sleep_jitter(140, 620)
        if random.random() < 0.7:
            page.keyboard.press(random.choice(["ArrowDown", "PageDown", "Space"]))
            _sleep_jitter(100, 450)


def _move_mouse_to_locator(page, locator) -> bool:
    try:
        box = locator.bounding_box()
    except Exception:
        return False
    if not box:
        return False

    target_x = int(box["x"] + (box["width"] / 2) + random.uniform(-6.0, 6.0))
    target_y = int(box["y"] + (box["height"] / 2) + random.uniform(-4.0, 4.0))

    page.mouse.move(target_x, target_y, steps=random.randint(9, 28))
    return True


def _human_click(page, locator, *, timeout_ms: int) -> bool:
    try:
        locator.scroll_into_view_if_needed(timeout=timeout_ms)
    except Exception:
        return False

    _sleep_jitter(180, 740)
    _mouse_roam(page)
    moved = _move_mouse_to_locator(page, locator)
    _sleep_jitter(80, 360)

    try:
        if moved:
            locator.click(timeout=timeout_ms, delay=random.randint(35, 165))
        else:
            locator.click(timeout=timeout_ms, delay=random.randint(40, 180))
    except Exception:
        return False

    _sleep_jitter(140, 760)
    return True


def _base_domain(hostname: str) -> str:
    parts = [part for part in (hostname or "").lower().split(".") if part]
    if len(parts) >= 2:
        return ".".join(parts[-2:])
    return hostname.lower()


def _is_private_or_local_host(hostname: str) -> bool:
    host = (hostname or "").lower().strip()
    if not host:
        return True
    if host in {"localhost", "127.0.0.1", "0.0.0.0", "::1"}:
        return True
    try:
        ip_value = ipaddress.ip_address(host)
    except ValueError:
        return False
    return bool(
        ip_value.is_private
        or ip_value.is_loopback
        or ip_value.is_link_local
        or ip_value.is_reserved
        or ip_value.is_multicast
    )


def _is_allowed_apply_target(source_url: str, target_url: str) -> tuple[bool, str]:
    parsed = urllib.parse.urlparse(target_url)
    scheme = parsed.scheme.lower()
    if scheme not in {"http", "https"}:
        return False, "unsafe scheme"

    target_host = (parsed.hostname or "").lower()
    if _is_private_or_local_host(target_host):
        return False, "unsafe host"

    source_host = (urllib.parse.urlparse(source_url).hostname or "").lower()
    if source_host and target_host == source_host:
        return True, "same host"

    source_base = _base_domain(source_host)
    target_base = _base_domain(target_host)
    if source_base and target_base and source_base == target_base:
        return True, "same base domain"

    if any(target_host.endswith(suffix) for suffix in _SAFE_EXTERNAL_APPLY_SUFFIXES):
        return True, "known ATS domain"

    return False, "untrusted cross-domain target"


def attempt_auto_apply(url: str) -> tuple[str, str]:
    try:
        from playwright.sync_api import TimeoutError as PlaywrightTimeoutError  # type: ignore
        from playwright.sync_api import sync_playwright  # type: ignore
    except Exception as exc:
        return "manual-required", f"playwright unavailable: {exc}"

    selectors = [
        "button:has-text('Easy Apply')",
        "a:has-text('Easy Apply')",
        "button:has-text('Apply Now')",
        "a:has-text('Apply Now')",
        "button:has-text('Apply')",
        "a:has-text('Apply')",
        "a[href*='apply']",
    ]

    allowed_start, reason_start = _is_allowed_apply_target(url, url)
    if not allowed_start:
        return "manual-required", f"blocked unsafe apply url: {reason_start}"

    try:
        with sync_playwright() as playwright:
            browser = playwright.chromium.launch(
                headless=True,
                slow_mo=random.randint(20, 90),
            )
            context = browser.new_context(viewport=_random_viewport())
            page = context.new_page()

            _sleep_jitter(_MIN_PRE_NAV_DELAY_MS, _MAX_PRE_NAV_DELAY_MS)
            page.goto(url, wait_until="domcontentloaded", timeout=45000)
            _sleep_jitter(_MIN_POST_NAV_DELAY_MS, _MAX_POST_NAV_DELAY_MS)
            _human_reading_activity(page)

            clicked = False
            click_note = ""

            for selector in selectors:
                locator = page.locator(selector)
                try:
                    count = locator.count()
                except Exception:
                    count = 0
                if count <= 0:
                    continue
                if not _human_click(page, locator.first, timeout_ms=7000):
                    continue
                clicked = True
                click_note = f"clicked selector: {selector}"
                allowed_after_click, reason_after_click = _is_allowed_apply_target(url, page.url)
                if not allowed_after_click:
                    return "manual-required", f"blocked unsafe redirect after click: {reason_after_click}"
                break

            if not clicked:
                fallback = page.locator("a[href*='apply'], a:has-text('Apply'), button:has-text('Apply')")
                try:
                    fallback_count = fallback.count()
                except Exception:
                    fallback_count = 0

                if fallback_count > 0:
                    first = fallback.first
                    href_attr = ""
                    try:
                        href_attr = str(first.get_attribute("href") or "").strip()
                    except Exception:
                        href_attr = ""

                    if href_attr:
                        target = urllib.parse.urljoin(url, href_attr)
                        allowed_target, reason_target = _is_allowed_apply_target(url, target)
                        if not allowed_target:
                            return "manual-required", f"blocked unsafe apply link: {reason_target}"

                    if _human_click(page, first, timeout_ms=7000):
                        _sleep_jitter(350, 1450)
                        allowed_after_click, reason_after_click = _is_allowed_apply_target(url, page.url)
                        if not allowed_after_click:
                            return "manual-required", f"blocked unsafe redirect after click: {reason_after_click}"
                        clicked = True
                        click_note = "clicked fallback apply control"

            context.close()
            browser.close()

        if clicked:
            return "applied", click_note or "apply interaction completed"
        return "manual-required", "could not find apply control"
    except PlaywrightTimeoutError as exc:
        return "failed", f"playwright timeout: {exc}"
    except Exception as exc:
        return "failed", f"playwright error: {exc}"
