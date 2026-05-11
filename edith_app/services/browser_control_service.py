from __future__ import annotations

import html
import re
import time
import urllib.parse
import webbrowser
from dataclasses import dataclass
from typing import Sequence

import requests

from edith_app.services.system_service import SystemService


@dataclass(slots=True)
class BrowserPurchasePlan:
    browser: str
    query: str
    domain: str
    product_url: str
    asin: str
    checkout_url: str
    place_order_url: str
    title: str
    rating: float
    reviews: int
    price: int
    price_currency: str
    score_note: str


class BrowserControlService:
    """Fast browser controls + guided e-commerce automation."""

    _BROWSER_ALIASES: dict[str, tuple[str, str]] = {
        "chrome": ("chrome", "Google Chrome"),
        "google chrome": ("chrome", "Google Chrome"),
        "edge": ("edge", "Microsoft Edge"),
        "microsoft edge": ("edge", "Microsoft Edge"),
        "firefox": ("firefox", "Mozilla Firefox"),
        "mozilla firefox": ("firefox", "Mozilla Firefox"),
    }

    _WINDOW_HINTS: dict[str, str] = {
        "chrome": "Google Chrome",
        "edge": "Microsoft Edge",
        "firefox": "Mozilla Firefox",
    }

    def __init__(self, system: SystemService) -> None:
        self._system = system
        self._session = requests.Session()
        self._session.headers.update(
            {
                "User-Agent": (
                    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
                    "AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36"
                )
            }
        )

    def can_handle(self, command: str) -> bool:
        lowered = command.lower().strip()
        if not lowered:
            return False
        markers = (
            "new tab",
            "close tab",
            "next tab",
            "previous tab",
            "reopen tab",
            "open amazon",
            "search amazon",
            "buy best",
            "buy the best",
            "open browser",
            "open in chrome",
            "open in edge",
            "open in firefox",
            "search in ",
        )
        return any(marker in lowered for marker in markers)

    def execute(self, command: str) -> tuple[str, BrowserPurchasePlan | None]:
        lowered = command.lower().strip()
        browser_key = self._detect_browser(lowered) or "chrome"

        if "new tab" in lowered:
            return self._send_hotkey(browser_key, ("ctrl", "t"), "Opened a new tab."), None
        if "close tab" in lowered:
            return self._send_hotkey(browser_key, ("ctrl", "w"), "Closed the current tab."), None
        if "next tab" in lowered:
            return self._send_hotkey(browser_key, ("ctrl", "tab"), "Switched to the next tab."), None
        if "previous tab" in lowered or "prev tab" in lowered:
            return self._send_hotkey(browser_key, ("ctrl", "shift", "tab"), "Switched to the previous tab."), None
        if "reopen tab" in lowered:
            return self._send_hotkey(browser_key, ("ctrl", "shift", "t"), "Reopened the last closed tab."), None

        buy_match = re.search(
            r"(?:buy\s+(?:the\s+)?best(?:\s+one)?(?:\s+for)?|open amazon and search for|search amazon for)\s+(.+)",
            lowered,
        )
        if buy_match:
            raw_query = buy_match.group(1).strip(" .")
            query, price_cap, brands = self._extract_buy_constraints(raw_query)
            plan = self._build_amazon_purchase_plan(
                query=query,
                browser=browser_key,
                price_cap=price_cap,
                brands=brands,
            )
            if plan is None:
                self._open_in_browser(browser_key, f"https://www.amazon.in/s?k={urllib.parse.quote_plus(query)}")
                return (
                    "I opened Amazon search, but I could not confidently rank a best product with those filters.",
                    None,
                )
            self._open_in_browser(plan.browser, plan.product_url)
            self._open_in_browser(plan.browser, f"https://www.amazon.{plan.domain}/gp/aws/cart/add.html?ASIN.1={plan.asin}&Quantity.1=1")
            self._open_in_browser(plan.browser, plan.checkout_url)
            summary = self.summarize_purchase_plan(plan)
            return (
                f"{summary}\n\n"
                "I moved it to checkout. Say 'approve summary' to unlock final order, then 'confirm place order'.",
                plan,
            )

        amazon_search_match = re.search(r"(?:open amazon(?: and)? search for|search amazon for)\s+(.+)", lowered)
        if amazon_search_match:
            query = amazon_search_match.group(1).strip(" .")
            encoded = urllib.parse.quote_plus(query)
            url = f"https://www.amazon.in/s?k={encoded}"
            self._open_in_browser(browser_key, url)
            return f"Opened Amazon and searched for {query}.", None

        in_browser_match = re.search(r"(?:open|search)\s+(.+?)\s+in\s+(chrome|edge|firefox)", lowered)
        if in_browser_match:
            target = in_browser_match.group(1).strip()
            browser_key = self._detect_browser(in_browser_match.group(2)) or browser_key
            if target.startswith(("http://", "https://")):
                self._open_in_browser(browser_key, target)
                return f"Opened {target} in {browser_key}.", None
            query = urllib.parse.quote_plus(target)
            self._open_in_browser(browser_key, f"https://www.google.com/search?q={query}")
            return f"Searched for {target} in {browser_key}.", None

        return "", None

    def summarize_purchase_plan(self, plan: BrowserPurchasePlan) -> str:
        price_text = f"{plan.price_currency}{plan.price}" if plan.price > 0 else "n/a"
        return (
            "Order summary:\n"
            f"- Product: {plan.title}\n"
            f"- Price: {price_text}\n"
            f"- Rating: {plan.rating} ({plan.reviews} reviews)\n"
            f"- Logic: {plan.score_note}"
        )

    def confirm_place_order(self, plan: BrowserPurchasePlan) -> str:
        self._open_in_browser(plan.browser, plan.place_order_url)
        pressed = self._press_enter_on_active_browser(plan.browser)
        if pressed:
            return (
                "Final order confirmation step executed. "
                "Please verify order success on the Amazon confirmation page."
            )
        return (
            "Opened the final place-order page. "
            "I couldn't reliably press confirm automatically, so please click Place your order once."
        )

    def _extract_buy_constraints(self, raw_query: str) -> tuple[str, int | None, list[str]]:
        price_cap: int | None = None
        brands: list[str] = []
        query = raw_query.strip()

        price_match = re.search(r"(?:under|below|less than|max)\s*₹?\$?\s*(\d[\d,]*)", query, flags=re.IGNORECASE)
        if price_match:
            try:
                price_cap = int(price_match.group(1).replace(",", ""))
            except Exception:
                price_cap = None

        brand_match = re.search(
            r"(?:from|by|brand)\s+([a-z0-9][a-z0-9\s,&]+)",
            query,
            flags=re.IGNORECASE,
        )
        if brand_match:
            raw_brands = brand_match.group(1)
            parts = re.split(r"\s*(?:,|/|&|\bor\b|\band\b)\s*", raw_brands, flags=re.IGNORECASE)
            brands = [part.strip().lower() for part in parts if part.strip()]

        query = re.sub(r"(?:under|below|less than|max)\s*₹?\$?\s*\d[\d,]*", "", query, flags=re.IGNORECASE)
        query = re.sub(r"(?:from|by|brand)\s+[a-z0-9][a-z0-9\s,&/]+", "", query, flags=re.IGNORECASE)
        query = re.sub(r"\s+", " ", query).strip(" ,.")
        return query or raw_query, price_cap, brands

    def _detect_browser(self, text: str) -> str | None:
        lowered = text.lower()
        for alias, (key, _) in self._BROWSER_ALIASES.items():
            if alias in lowered:
                return key
        return None

    def _open_in_browser(self, browser: str, url: str) -> None:
        executable = {
            "chrome": "chrome.exe",
            "edge": "msedge.exe",
            "firefox": "firefox.exe",
        }.get(browser, "chrome.exe")
        try:
            import subprocess

            subprocess.Popen([executable, url], shell=False)
        except Exception:
            webbrowser.open(url)

    def _send_hotkey(self, browser: str, keys: tuple[str, ...], success_message: str) -> str:
        try:
            import pygetwindow as gw
            import pyautogui

            hint = self._WINDOW_HINTS.get(browser, "Chrome")
            windows = gw.getWindowsWithTitle(hint)
            if windows:
                win = windows[0]
                if win.isMinimized:
                    win.restore()
                win.activate()
                time.sleep(0.2)
            pyautogui.FAILSAFE = False
            pyautogui.hotkey(*keys)
            return success_message
        except Exception:
            return f"I could not send the browser shortcut for {browser}. Install pyautogui and pygetwindow."

    def _press_enter_on_active_browser(self, browser: str) -> bool:
        try:
            import pygetwindow as gw
            import pyautogui

            hint = self._WINDOW_HINTS.get(browser, "Chrome")
            windows = gw.getWindowsWithTitle(hint)
            if windows:
                win = windows[0]
                if win.isMinimized:
                    win.restore()
                win.activate()
                time.sleep(0.2)
            pyautogui.press("enter")
            return True
        except Exception:
            return False

    def _build_amazon_purchase_plan(
        self,
        query: str,
        browser: str,
        price_cap: int | None = None,
        brands: Sequence[str] | None = None,
    ) -> BrowserPurchasePlan | None:
        html_doc, domain = self._search_with_retry(query)
        if not html_doc or not domain:
            return None

        candidates = self._extract_amazon_candidates(html_doc, domain=domain)
        if not candidates:
            return None

        brand_filters = [brand.lower() for brand in (brands or []) if brand.strip()]
        filtered: list[dict[str, object]] = []
        for item in candidates:
            title = str(item.get("title", "")).lower()
            price = int(item.get("price", 0) or 0)
            if brand_filters and not any(brand in title for brand in brand_filters):
                continue
            if price_cap is not None and price > 0 and price > price_cap:
                continue
            filtered.append(item)

        ranked_pool = filtered or candidates
        best = max(ranked_pool, key=lambda item: float(item.get("score", 0.0)))
        asin = str(best["asin"])
        product_url = str(best["url"])
        score_note = str(best["note"])
        checkout_url = f"https://www.amazon.{domain}/gp/cart/view.html"
        place_order_url = f"https://www.amazon.{domain}/gp/buy/spc/handlers/display.html?hasWorkingJavascript=1"
        return BrowserPurchasePlan(
            browser=browser,
            query=query,
            domain=domain,
            product_url=product_url,
            asin=asin,
            checkout_url=checkout_url,
            place_order_url=place_order_url,
            title=str(best.get("title", "Unknown product")),
            rating=float(best.get("rating", 0.0)),
            reviews=int(best.get("reviews", 0)),
            price=int(best.get("price", 0)),
            price_currency=str(best.get("currency", "Rs ")),
            score_note=score_note,
        )

    def _search_with_retry(self, query: str) -> tuple[str, str]:
        encoded = urllib.parse.quote_plus(query)
        for domain in ("in", "com"):
            url = f"https://www.amazon.{domain}/s?k={encoded}"
            html_doc = self._fetch(url)
            if not html_doc:
                continue
            if self._looks_like_amazon_blocked(html_doc):
                continue
            candidates = self._extract_amazon_candidates(html_doc, domain=domain)
            if candidates:
                return html_doc, domain
        return "", ""

    def _looks_like_amazon_blocked(self, html_doc: str) -> bool:
        lowered = html_doc.lower()
        block_markers = (
            "enter the characters you see below",
            "type the characters you see in this image",
            "sorry, we just need to make sure you're not a robot",
            "automated access to amazon data",
            "captcha",
        )
        return any(marker in lowered for marker in block_markers)

    def _fetch(self, url: str) -> str:
        try:
            response = self._session.get(url, timeout=10, allow_redirects=True)
            if response.ok:
                return response.text
        except Exception:
            return ""
        return ""

    def _extract_amazon_candidates(self, html_doc: str, domain: str) -> list[dict[str, object]]:
        blocks = re.findall(
            r'(<div[^>]+data-component-type="s-search-result"[^>]*>.*?</div>\s*</div>)',
            html_doc,
            flags=re.IGNORECASE | re.DOTALL,
        )
        if not blocks:
            raw_chunks = re.split(r'(?=data-asin="[A-Z0-9]{10}")', html_doc)
            blocks = [chunk[:4500] for chunk in raw_chunks if 'data-asin="' in chunk]

        candidates: list[dict[str, object]] = []
        for block in blocks[:50]:
            asin_match = re.search(r'data-asin="([A-Z0-9]{10})"', block)
            if not asin_match:
                continue
            asin = asin_match.group(1)
            if not asin:
                continue

            if "s-sponsored-label" in block.lower():
                continue

            title_match = re.search(r'<h2[^>]*>.*?<span[^>]*>(.*?)</span>', block, flags=re.IGNORECASE | re.DOTALL)
            title = html.unescape(re.sub(r"<[^>]+>", "", title_match.group(1))).strip() if title_match else ""
            if not title:
                continue

            rating_match = re.search(r'([0-5]\.?[0-9]?)\s*out of 5 stars', block, flags=re.IGNORECASE)
            rating = float(rating_match.group(1)) if rating_match else 0.0
            reviews_match = re.search(r'aria-label="([\d,]+)\s+ratings?"', block, flags=re.IGNORECASE)
            reviews = int(reviews_match.group(1).replace(",", "")) if reviews_match else 0
            price, currency = self._extract_price(block)

            score = (rating * 25.0) + min(reviews / 250.0, 20.0) + (5.0 if price > 0 else 0.0)
            url = f"https://www.amazon.{domain}/dp/{asin}"
            note = f"rating={rating}, reviews={reviews}, price={currency}{price if price else 'n/a'}"
            candidates.append(
                {
                    "asin": asin,
                    "url": url,
                    "title": title,
                    "rating": rating,
                    "reviews": reviews,
                    "price": price,
                    "currency": currency,
                    "score": score,
                    "note": note,
                }
            )
        return candidates

    def _extract_price(self, block: str) -> tuple[int, str]:
        patterns = (
            (r"₹\s?([\d,]+)", "Rs "),
            (r"Rs\.?\s?([\d,]+)", "Rs "),
            (r"\$\s?([\d,]+)", "$"),
        )
        for pattern, currency in patterns:
            match = re.search(pattern, block, flags=re.IGNORECASE)
            if not match:
                continue
            try:
                return int(match.group(1).replace(",", "")), currency
            except Exception:
                continue
        return 0, "Rs "

