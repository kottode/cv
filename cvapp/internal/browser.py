from __future__ import annotations

import urllib.parse


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
        "button[type='submit']",
    ]

    try:
        with sync_playwright() as playwright:
            browser = playwright.chromium.launch(headless=True)
            page = browser.new_page()
            page.goto(url, wait_until="domcontentloaded", timeout=45000)
            page.wait_for_timeout(500)

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
                locator.first.click(timeout=7000)
                clicked = True
                click_note = f"clicked selector: {selector}"
                break

            if not clicked:
                href = page.evaluate(
                    """() => {
                        const targets = Array.from(document.querySelectorAll('a[href], button'));
                        for (const el of targets) {
                            const text = (el.textContent || '').toLowerCase();
                            if (text.includes('apply')) {
                                if (el.tagName.toLowerCase() === 'a') {
                                    return el.getAttribute('href') || '';
                                }
                                try { el.click(); return '__BUTTON_CLICKED__'; } catch (_) {}
                            }
                        }
                        return '';
                    }"""
                )

                if isinstance(href, str) and href:
                    if href == "__BUTTON_CLICKED__":
                        clicked = True
                        click_note = "clicked generic apply button"
                    else:
                        target = urllib.parse.urljoin(url, href)
                        page.goto(target, wait_until="domcontentloaded", timeout=45000)
                        clicked = True
                        click_note = f"navigated to apply link: {target}"

            browser.close()

        if clicked:
            return "applied", click_note or "apply interaction completed"
        return "manual-required", "could not find apply control"
    except PlaywrightTimeoutError as exc:
        return "failed", f"playwright timeout: {exc}"
    except Exception as exc:
        return "failed", f"playwright error: {exc}"
