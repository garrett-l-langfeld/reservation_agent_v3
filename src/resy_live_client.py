from __future__ import annotations

import json
import re
from dataclasses import dataclass
from datetime import datetime
from typing import Any
from urllib.parse import urlparse
from urllib.parse import quote
from urllib.parse import urlencode


_TIME_PATTERN = re.compile(r"\b(?:1[0-2]|[1-9])(?::[0-5]\d)?\s?(?:AM|PM)\b", re.IGNORECASE)


@dataclass(frozen=True)
class ResumePayload:
    url: str
    slot_time: str | None = None


@dataclass(frozen=True)
class SlotClickAttempt:
    clicked: bool
    diagnostics: dict[str, Any]


class ResyLiveClient:
    """Best-effort Playwright-backed client for live Resy interactions."""

    def __init__(
        self,
        *,
        headless: bool = True,
        timeout_ms: int = 20_000,
        base_url: str = "https://resy.com",
        reuse_browser_session: bool = True,
    ):
        self.headless = headless
        self.timeout_ms = timeout_ms
        self.base_url = base_url.rstrip("/")
        self.reuse_browser_session = reuse_browser_session
        self._playwright = None
        self._browser = None
        self._context = None
        self._page = None

    def search_restaurants(self, restaurant_name: str, location: str) -> list[dict[str, str]]:
        query = f"{restaurant_name} {location}".strip()
        for search_url in _build_search_urls(
            base_url=self.base_url,
            location=location,
            query=query,
        ):
            with self._open_page(search_url) as page:
                _wait_for_search_results(page)
                card_data = page.eval_on_selector_all(
                    "a[href*='/venues/']",
                    """
                    (anchors) => anchors.slice(0, 40).map((anchor) => ({
                        href: anchor.href || '',
                        text: (anchor.innerText || '').trim(),
                        label: (anchor.getAttribute('aria-label') || '').trim(),
                    }))
                    """,
                )

            results = _parse_restaurant_cards(
                card_data=card_data,
                fallback_name=restaurant_name,
                fallback_location=location,
            )
            if results:
                return results

        return []

    def fetch_availability(
        self,
        *,
        restaurant_id: str,
        date: str,
        party_size: int,
        time: str | None = None,
        time_range: dict[str, str] | None = None,
    ) -> list[dict[str, Any]]:
        _ = (time, time_range)
        venue_url = self.build_handoff_url(
            restaurant_id=restaurant_id,
            date=date,
            party_size=party_size,
            requested_time=None,
        )

        with self._open_page(venue_url) as page:
            _wait_for_availability_results(page)
            first_pass = _collect_time_text_candidates(page)
            if _extract_times(first_pass):
                chunks = first_pass
            else:
                page.wait_for_timeout(2_500)
                second_pass = _collect_time_text_candidates(page)
                chunks = first_pass + second_pass

        times = _extract_times(chunks)
        return [{"time": slot_time, "available": True} for slot_time in times]

    def book_slot(
        self,
        *,
        restaurant_id: str,
        date: str,
        party_size: int,
        slot_time: str,
        user_details: dict[str, Any],
    ) -> dict[str, Any]:
        venue_url = self.build_handoff_url(
            restaurant_id=restaurant_id,
            date=date,
            party_size=party_size,
            requested_time=slot_time,
        )

        with self._open_page(venue_url) as page:
            if _page_looks_like_captcha(page):
                return {
                    "status": "captcha_required",
                    "prompt": "Complete CAPTCHA in browser and resume booking.",
                    "resume_token": _encode_resume_payload(ResumePayload(url=page.url, slot_time=slot_time)),
                }

            pre_click_url = str(getattr(page, "url", ""))
            click_attempt = _click_slot_button(page, slot_time)
            if not click_attempt.clicked:
                return {
                    "status": "failure",
                    "reason": "slot_click_failed",
                    "debug": {
                        **click_attempt.diagnostics,
                        "pre_click_url": pre_click_url,
                        "post_click_url": str(getattr(page, "url", "")),
                    },
                }

            page.wait_for_timeout(2500)
            page = _switch_to_new_booking_page_if_present(page)
            post_click_url = str(getattr(page, "url", ""))

            if _page_looks_like_captcha(page):
                return {
                    "status": "captcha_required",
                    "prompt": "Complete CAPTCHA in browser and resume booking.",
                    "resume_token": _encode_resume_payload(ResumePayload(url=page.url, slot_time=slot_time)),
                }

            if _page_looks_confirmed(page):
                return {
                    "status": "success",
                    "confirmation_code": _extract_confirmation_code(page.content()),
                }

            if _page_looks_checkout_opened(page):
                checkout_debug = _attempt_checkout_autofill_and_submit(page, user_details)
                page.wait_for_timeout(2_000)

                if _page_looks_like_captcha(page):
                    return {
                        "status": "captcha_required",
                        "prompt": "Complete CAPTCHA in browser and resume booking.",
                        "resume_token": _encode_resume_payload(ResumePayload(url=page.url, slot_time=slot_time)),
                    }

                if _page_looks_confirmed(page):
                    return {
                        "status": "success",
                        "confirmation_code": _extract_confirmation_code(page.content()),
                    }

                return {
                    "status": "checkout_opened",
                    "prompt": "Booking details opened. Complete remaining checkout steps in browser and resume.",
                    "resume_token": _encode_resume_payload(ResumePayload(url=page.url, slot_time=slot_time)),
                    "debug": {
                        **click_attempt.diagnostics,
                        "checkout_action": checkout_debug,
                        "pre_click_url": pre_click_url,
                        "post_click_url": str(getattr(page, "url", "")),
                    },
                }

            return {
                "status": "checkout_opened",
                "prompt": "Slot selected. Complete remaining checkout steps in browser and resume.",
                "resume_token": _encode_resume_payload(ResumePayload(url=page.url, slot_time=slot_time)),
                "debug": {
                    **click_attempt.diagnostics,
                    "reason": "post_click_not_confirmed",
                    "pre_click_url": pre_click_url,
                    "post_click_url": post_click_url,
                    "url_changed_after_click": pre_click_url != post_click_url,
                },
            }

    def build_handoff_url(
        self,
        *,
        restaurant_id: str,
        date: str,
        party_size: int,
        requested_time: str | None = None,
    ) -> str:
        params: dict[str, str | int] = {
            "date": date,
            "seats": party_size,
        }
        if requested_time:
            params["time"] = requested_time

        query = urlencode(params)
        venue_base = _build_venue_base_url(
            base_url=self.base_url,
            restaurant_reference=restaurant_id,
        )
        return f"{venue_base}?{query}"

    def resume_booking(self, resume_token: str) -> dict[str, Any]:
        payload = _decode_resume_payload(resume_token)
        if payload is None:
            return {"status": "failure", "reason": "invalid_resume_token"}

        with self._open_page(payload.url) as page:
            page.wait_for_timeout(2500)

            if _page_looks_like_captcha(page):
                return {
                    "status": "failure",
                    "reason": "captcha_pending",
                }

            if _page_looks_confirmed(page):
                return {
                    "status": "success",
                    "confirmation_code": _extract_confirmation_code(page.content()),
                }

        return {"status": "failure", "reason": "resume_failed"}

    def _open_page(self, url: str):
        if self.reuse_browser_session:
            return _PersistentPageSession(client=self, url=url)
        return _PlaywrightPageSession(
            url=url,
            headless=self.headless,
            timeout_ms=self.timeout_ms,
        )

    def close(self) -> None:
        if self._context is not None:
            self._context.close()
        if self._browser is not None:
            self._browser.close()
        if self._playwright is not None:
            self._playwright.stop()

        self._context = None
        self._browser = None
        self._playwright = None
        self._page = None

    def _ensure_persistent_page(self) -> Any:
        if self._page is not None:
            return self._page

        try:
            from playwright.sync_api import sync_playwright
        except ImportError as error:
            raise RuntimeError(
                "Playwright is not installed. Run '.venv/bin/python -m playwright install'."
            ) from error

        self._playwright = sync_playwright().start()
        self._browser = self._playwright.chromium.launch(headless=self.headless)
        self._context = self._browser.new_context()
        self._page = self._context.new_page()
        self._page.set_default_timeout(self.timeout_ms)
        return self._page


class _PersistentPageSession:
    def __init__(self, *, client: ResyLiveClient, url: str):
        self.client = client
        self.url = url

    def __enter__(self):
        page = self.client._ensure_persistent_page()
        page.goto(self.url, wait_until="domcontentloaded")
        return page

    def __exit__(self, exc_type, exc, tb):
        return False


class _PlaywrightPageSession:
    def __init__(self, *, url: str, headless: bool, timeout_ms: int):
        self.url = url
        self.headless = headless
        self.timeout_ms = timeout_ms
        self._playwright = None
        self._browser = None
        self._context = None
        self._page = None

    def __enter__(self):
        try:
            from playwright.sync_api import sync_playwright
        except ImportError as error:
            raise RuntimeError(
                "Playwright is not installed. Run '.venv/bin/python -m playwright install'."
            ) from error

        self._playwright = sync_playwright().start()
        self._browser = self._playwright.chromium.launch(headless=self.headless)
        self._context = self._browser.new_context()
        self._page = self._context.new_page()
        self._page.set_default_timeout(self.timeout_ms)
        self._page.goto(self.url, wait_until="domcontentloaded")
        return self._page

    def __exit__(self, exc_type, exc, tb):
        if self._context is not None:
            self._context.close()
        if self._browser is not None:
            self._browser.close()
        if self._playwright is not None:
            self._playwright.stop()
        return False


def _extract_venue_id(href: str) -> str | None:
    return _extract_venue_reference(href)


def _extract_venue_reference(href: str) -> str | None:
    if not href:
        return None
    parsed = urlparse(href)
    path = parsed.path or ""
    marker = "/venues/"
    if marker not in path:
        return None

    prefix, tail = path.split(marker, maxsplit=1)
    slug = tail.strip("/").split("/", maxsplit=1)[0]
    if not slug:
        return None

    if prefix:
        return f"{prefix}{marker}{slug}"
    return f"/venues/{slug}"


def _location_to_city_slug(location: str) -> str:
    cleaned = re.sub(r"[^A-Za-z0-9]+", "-", location.strip().lower()).strip("-")
    return re.sub(r"-{2,}", "-", cleaned)


def _build_search_urls(*, base_url: str, location: str, query: str) -> list[str]:
    encoded_query = quote(query)
    city_slug = _location_to_city_slug(location)
    urls: list[str] = []
    if city_slug:
        urls.append(f"{base_url}/cities/{city_slug}/search?query={encoded_query}")
    urls.append(f"{base_url}/search?query={encoded_query}")
    return urls


def _build_venue_base_url(*, base_url: str, restaurant_reference: str) -> str:
    reference = (restaurant_reference or "").strip()
    if reference.startswith("http://") or reference.startswith("https://"):
        return reference.split("?", maxsplit=1)[0].split("#", maxsplit=1)[0]

    if reference.startswith("/"):
        path = reference
    elif "/venues/" in reference:
        path = f"/{reference.lstrip('/')}"
    else:
        path = f"/venues/{quote(reference)}"

    path = path.split("?", maxsplit=1)[0].split("#", maxsplit=1)[0]
    return f"{base_url}{path}"


def _wait_for_search_results(page: Any) -> None:
    try:
        page.wait_for_load_state("networkidle", timeout=5_000)
    except Exception:
        pass
    page.wait_for_timeout(2_500)


def _wait_for_availability_results(page: Any) -> None:
    try:
        page.wait_for_load_state("networkidle", timeout=7_000)
    except Exception:
        pass
    page.wait_for_timeout(2_000)


def _collect_time_text_candidates(page: Any) -> list[str]:
    return page.evaluate(
        """
        () => {
            const selectors = [
              "button",
              "[role='button']",
              "a[href*='book']",
              "a[href*='reserve']",
              "[data-test-id*='slot']",
              "[data-testid*='slot']",
              "[class*='slot'] button",
              "[class*='slot'] [role='button']",
            ];
            const out = new Set();
            const timeLike = /\\b(?:1[0-2]|[1-9])(?::[0-5]\\d)?\\s?(?:AM|PM)\\b/i;
            for (const selector of selectors) {
              const nodes = document.querySelectorAll(selector);
              for (const node of nodes) {
                if (!(node instanceof HTMLElement)) continue;
                if (node.getClientRects().length === 0) continue;
                const text = (node.innerText || "").trim();
                if (!text) continue;
                if (text.length > 60) continue;
                if (!timeLike.test(text)) continue;
                out.add(text);

                const aria = (node.getAttribute("aria-label") || "").trim();
                if (aria && aria.length <= 80 && timeLike.test(aria)) out.add(aria);
              }
            }
            return Array.from(out);
        }
        """
    )


def _parse_restaurant_cards(
    *,
    card_data: list[dict[str, str]],
    fallback_name: str,
    fallback_location: str,
) -> list[dict[str, str]]:
    results: list[dict[str, str]] = []
    seen_ids: set[str] = set()

    for item in card_data:
        href = item.get("href", "")
        venue_id = _extract_venue_id(href)
        if not venue_id or venue_id in seen_ids:
            continue

        name, parsed_location = _parse_card_text(item.get("text", ""), item.get("label", ""))
        if not name:
            name = fallback_name
        if not parsed_location:
            parsed_location = fallback_location

        results.append(
            {
                "id": venue_id,
                "name": name,
                "location": parsed_location,
            }
        )
        seen_ids.add(venue_id)

    return results


def _parse_card_text(text: str, label: str) -> tuple[str, str]:
    content = text or label
    if not content:
        return "", ""

    lines = [line.strip() for line in content.splitlines() if line.strip()]
    if not lines:
        return "", ""

    if len(lines) == 1:
        return lines[0], ""

    return lines[0], lines[-1]


def _normalize_time(value: str) -> str | None:
    cleaned = " ".join(value.strip().upper().split())
    for time_format in ("%I:%M %p", "%I %p"):
        try:
            parsed = datetime.strptime(cleaned, time_format)
            return parsed.strftime("%I:%M %p").lstrip("0")
        except ValueError:
            continue
    return None


def _extract_times(chunks: list[str]) -> list[str]:
    seen: set[str] = set()
    times: list[str] = []

    for chunk in chunks:
        for match in _TIME_PATTERN.findall(chunk):
            normalized = _normalize_time(match)
            if normalized and normalized not in seen:
                seen.add(normalized)
                times.append(normalized)

    return sorted(times, key=_time_sort_key)


def _time_sort_key(value: str) -> tuple[int, int]:
    parsed = datetime.strptime(value, "%I:%M %p")
    return parsed.hour % 24, parsed.minute


def _switch_to_new_booking_page_if_present(page: Any) -> Any:
    try:
        context = page.context
        pages = list(context.pages)
        if len(pages) <= 1:
            return page

        for candidate in reversed(pages):
            if candidate == page:
                continue
            if candidate.is_closed():
                continue
            try:
                candidate.wait_for_load_state("domcontentloaded", timeout=2_500)
            except Exception:
                pass
            return candidate
    except Exception:
        return page

    return page


def _click_slot_button(page: Any, slot_time: str) -> SlotClickAttempt:
    # Resy can hydrate slot buttons after initial DOMContentLoaded.
    # Wait briefly for known slot controls before first click attempt.
    try:
        page.wait_for_selector(
            "button.ReservationButton.Button, .ReservationButtonList button",
            timeout=4_000,
        )
    except Exception:
        pass

    # Retry a few times to tolerate delayed hydration/shift rendering.
    attempts: list[dict[str, Any]] = []
    for attempt_index in range(1, 5):
        attempt = _click_slot_button_once(page, slot_time)
        attempt_diag = {**attempt.diagnostics, "attempt_index": attempt_index}
        attempts.append(attempt_diag)
        if attempt.clicked:
            return SlotClickAttempt(
                clicked=True,
                diagnostics={**attempt_diag, "attempts": attempts},
            )
        if attempt_index < 4:
            _maybe_expand_all_times(page)
            page.wait_for_timeout(1_000)

    return SlotClickAttempt(
        clicked=False,
        diagnostics={
            **(attempts[-1] if attempts else {"target_time": slot_time, "reason": "no_attempts"}),
            "attempts": attempts,
        },
    )


def _click_slot_button_once(page: Any, slot_time: str) -> SlotClickAttempt:
    target = slot_time.strip()
    if not target:
        return SlotClickAttempt(
            clicked=False,
            diagnostics={"target_time": slot_time, "reason": "empty_slot_time"},
        )

    exact_name = re.compile(rf"^\s*{re.escape(target)}\s*$", re.IGNORECASE)
    contains_name = re.compile(re.escape(target), re.IGNORECASE)

    attempted_selectors: list[str] = []
    candidate_locators = [
        ("resy_reservation_button", page.locator("button.ReservationButton.Button").filter(has_text=contains_name).first),
        ("resy_reservation_list_button", page.locator(".ReservationButtonList button").filter(has_text=contains_name).first),
        (
            "slot_test_id_contains",
            page.locator("[data-test-id*='slot'], [data-testid*='slot']").filter(has_text=contains_name).first,
        ),
        ("role_button_exact", page.get_by_role("button", name=exact_name).first),
        ("role_button_contains", page.get_by_role("button", name=contains_name).first),
        ("role_link_exact", page.get_by_role("link", name=exact_name).first),
        ("role_link_contains", page.get_by_role("link", name=contains_name).first),
    ]

    for selector_name, locator in candidate_locators:
        attempted_selectors.append(selector_name)
        try:
            if locator.count() > 0:
                locator.click(timeout=2_500)
                clicked_text = ""
                try:
                    clicked_text = str(locator.inner_text(timeout=800)).strip()
                except Exception:
                    clicked_text = ""
                return SlotClickAttempt(
                    clicked=True,
                    diagnostics={
                        "target_time": target,
                        "clicked_via": selector_name,
                        "clicked_text": clicked_text,
                        "attempted_selectors": attempted_selectors,
                    },
                )
        except Exception as error:
            attempted_selectors.append(f"{selector_name}_error:{error.__class__.__name__}")

    # Fallback: click a visible interactive element whose text/aria contains
    # normalized time variants. This catches slot widgets without clear roles.
    variants = _slot_time_variants(target)
    try:
        fallback = page.evaluate(
                """
                ({ variants }) => {
                    const selectors = [
                      "button.ReservationButton.Button",
                      ".ReservationButtonList button",
                      "button",
                      "[role='button']",
                      "[role='option']",
                      "li[role='option']",
                      "a",
                      "[data-test-id*='slot']",
                      "[data-testid*='slot']",
                      "[data-test-id*='time']",
                      "[data-testid*='time']",
                      "[class*='slot']",
                      "[class*='time']",
                    ];
                    const seen = new WeakSet();
                    const normalize = (value) =>
                      (value || "")
                        .toLowerCase()
                        .replace(/\\s+/g, " ")
                        .replace(/\\./g, "")
                        .trim();
                    const preview = (value) => {
                      const cleaned = (value || "").replace(/\\s+/g, " ").trim();
                      return cleaned.length > 90 ? `${cleaned.slice(0, 90)}...` : cleaned;
                    };
                    const isDisabled = (el) =>
                      !!(
                        el.hasAttribute("disabled") ||
                        el.getAttribute("aria-disabled") === "true" ||
                        el.dataset?.disabled === "true"
                      );
                    const isObscured = (el) => {
                      const rect = el.getBoundingClientRect();
                      if (!rect || rect.width === 0 || rect.height === 0) return true;
                      const cx = rect.left + rect.width / 2;
                      const cy = rect.top + rect.height / 2;
                      const top = document.elementFromPoint(cx, cy);
                      return !!(top && top !== el && !el.contains(top));
                    };
                    const triggerClick = (el) => {
                      const events = ["pointerdown", "mousedown", "pointerup", "mouseup", "click"];
                      for (const type of events) {
                        el.dispatchEvent(new MouseEvent(type, { bubbles: true, cancelable: true, view: window }));
                      }
                    };
                    const normalizedVariants = variants.map(normalize).filter(Boolean);
                    let totalScanned = 0;
                    const matching = [];
                    for (const selector of selectors) {
                      for (const node of document.querySelectorAll(selector)) {
                        if (!(node instanceof HTMLElement)) continue;
                        if (seen.has(node)) continue;
                        seen.add(node);
                        totalScanned += 1;
                        if (node.getClientRects().length === 0) continue;
                        const rawText = node.innerText || "";
                        const rawAria = node.getAttribute("aria-label") || "";
                        const text = normalize(rawText);
                        const aria = normalize(rawAria);
                        if (!text && !aria) continue;
                        const matches = normalizedVariants.some(
                          (variant) => text.includes(variant) || aria.includes(variant)
                        );
                        if (!matches) continue;
                        const target =
                          node.closest("button, a, [role='button'], [role='link'], [role='option'], li, [tabindex]") ||
                          node;
                        if (!(target instanceof HTMLElement)) continue;
                        matching.push({
                          selector,
                          tag: target.tagName.toLowerCase(),
                          role: target.getAttribute("role") || "",
                          disabled: isDisabled(target),
                          obscured: isObscured(target),
                          text: preview(rawText),
                          aria: preview(rawAria),
                          element: target,
                        });
                      }
                    }
                    for (const candidate of matching) {
                      if (candidate.disabled) continue;
                      candidate.element.scrollIntoView({ block: "center", inline: "center" });
                      try {
                        candidate.element.click();
                      } catch (error) {
                        triggerClick(candidate.element);
                      }
                      return {
                        clicked: true,
                        clickedVia: "evaluate_interactive_scan",
                        totalScanned,
                        matchingCount: matching.length,
                        clickedCandidate: {
                          selector: candidate.selector,
                          tag: candidate.tag,
                          role: candidate.role,
                          disabled: candidate.disabled,
                          obscured: candidate.obscured,
                          text: candidate.text,
                          aria: candidate.aria,
                        },
                        topCandidates: matching.slice(0, 5).map((candidate) => ({
                          selector: candidate.selector,
                          tag: candidate.tag,
                          role: candidate.role,
                          disabled: candidate.disabled,
                          obscured: candidate.obscured,
                          text: candidate.text,
                          aria: candidate.aria,
                        })),
                      };
                    }
                    return {
                      clicked: false,
                      clickedVia: null,
                      totalScanned,
                      matchingCount: matching.length,
                      clickedCandidate: null,
                      topCandidates: matching.slice(0, 5).map((candidate) => ({
                        selector: candidate.selector,
                        tag: candidate.tag,
                        role: candidate.role,
                        disabled: candidate.disabled,
                        obscured: candidate.obscured,
                        text: candidate.text,
                        aria: candidate.aria,
                      })),
                    };
                }
                """,
                {"variants": variants},
            )
        if isinstance(fallback, dict):
            diagnostics = {
                "target_time": target,
                "variants": variants,
                "clicked_via": fallback.get("clickedVia"),
                "total_scanned": fallback.get("totalScanned"),
                "matching_count": fallback.get("matchingCount"),
                "clicked_candidate": fallback.get("clickedCandidate"),
                "top_candidates": fallback.get("topCandidates") or [],
                "attempted_selectors": attempted_selectors,
            }
            if bool(fallback.get("clicked")):
                return SlotClickAttempt(clicked=True, diagnostics=diagnostics)
            return SlotClickAttempt(clicked=False, diagnostics=diagnostics)
    except Exception:
        return SlotClickAttempt(
            clicked=False,
            diagnostics={
                "target_time": target,
                "variants": variants,
                "attempted_selectors": attempted_selectors,
                "reason": "evaluate_fallback_failed",
            },
        )

    return SlotClickAttempt(
        clicked=False,
        diagnostics={
            "target_time": target,
            "variants": variants,
            "attempted_selectors": attempted_selectors,
            "reason": "no_matching_clickable_slot",
        },
    )


def _maybe_expand_all_times(page: Any) -> None:
    try:
        toggles = page.get_by_role("button", name=re.compile(r"all\\s*times", re.IGNORECASE))
        count = min(toggles.count(), 3)
        for index in range(count):
            toggle = toggles.nth(index)
            try:
                if toggle.is_visible():
                    toggle.click(timeout=1_500)
                    page.wait_for_timeout(250)
            except Exception:
                continue
    except Exception:
        pass


def _slot_time_variants(slot_time: str) -> list[str]:
    normalized = _normalize_time(slot_time)
    if not normalized:
        return [slot_time.strip()]

    variants = {
        normalized,
        normalized.replace(" ", ""),
        normalized.lower(),
        normalized.lower().replace(" ", ""),
    }

    hour_minute, ampm = normalized.split(" ")
    variants.add(hour_minute)
    variants.add(f"{hour_minute} {ampm.lower()}")
    return [value for value in variants if value]


def _page_looks_like_captcha(page: Any) -> bool:
    url = str(getattr(page, "url", "")).lower()
    if _url_looks_like_captcha(url):
        return True

    try:
        has_visible_captcha = bool(
            page.evaluate(
                """
                () => {
                    const selectors = [
                      "iframe[src*='recaptcha']",
                      "iframe[src*='hcaptcha']",
                      "iframe[title*='captcha' i]",
                      "[id*='captcha' i]",
                      "[class*='captcha' i]",
                      "[data-testid*='captcha' i]",
                    ];
                    for (const selector of selectors) {
                        for (const node of document.querySelectorAll(selector)) {
                            if (!(node instanceof HTMLElement)) continue;
                            if (node.getClientRects().length === 0) continue;
                            return true;
                        }
                    }
                    const body = (document.body?.innerText || "").toLowerCase();
                    const phrases = [
                      "verify you are human",
                      "i'm not a robot",
                      "security check",
                      "complete the captcha",
                    ];
                    return phrases.some((phrase) => body.includes(phrase));
                }
                """
            )
        )
        if has_visible_captcha:
            return True
    except Exception:
        pass

    html = page.content()
    return _html_looks_like_captcha(html)


def _url_looks_like_captcha(url: str) -> bool:
    candidate = (url or "").lower()
    return any(
        marker in candidate
        for marker in (
            "/challenge",
            "cf_chl",
            "recaptcha",
            "hcaptcha",
            "/captcha",
        )
    )


def _html_looks_like_captcha(html: str) -> bool:
    content = (html or "").lower()
    strong_markers = (
        "g-recaptcha",
        "hcaptcha",
        "data-sitekey",
        "cf-turnstile",
    )
    if any(marker in content for marker in strong_markers):
        return True

    strong_phrases = (
        "verify you are human",
        "i'm not a robot",
        "security check",
        "complete the captcha",
        "enter the characters you see",
    )
    return any(phrase in content for phrase in strong_phrases)


def _page_looks_confirmed(page: Any) -> bool:
    html = page.content().lower()
    markers = [
        "reservation confirmed",
        "booking confirmed",
        "you're all set",
        "you are all set",
    ]
    return any(marker in html for marker in markers)


def _page_looks_checkout_opened(page: Any) -> bool:
    try:
        return bool(
            page.evaluate(
                """
                () => {
                    const body = (document.body?.innerText || "").toLowerCase();
                    const strongPhrases = [
                      "complete your reservation",
                      "reservation details",
                      "confirm reservation",
                      "booking details",
                      "contact information",
                      "payment",
                    ];
                    if (strongPhrases.some((phrase) => body.includes(phrase))) {
                      return true;
                    }

                    const hasFields = document.querySelectorAll(
                      "input[type='email'], input[type='tel'], input[name*='email' i], input[name*='phone' i]"
                    ).length > 0;
                    const hasSubmitLikeButton = Array.from(document.querySelectorAll("button, [role='button']"))
                      .some((node) => {
                        const text = (node.textContent || "").toLowerCase();
                        return (
                          text.includes("confirm") ||
                          text.includes("reserve") ||
                          text.includes("book now") ||
                          text.includes("continue")
                        );
                      });

                    return hasFields && hasSubmitLikeButton;
                }
                """
            )
        )
    except Exception:
        return False


def _attempt_checkout_autofill_and_submit(page: Any, user_details: dict[str, Any]) -> dict[str, Any]:
    name = str(user_details.get("name") or "").strip()
    email = str(user_details.get("email") or "").strip()
    phone = str(user_details.get("phone") or "").strip()

    filled = {"name": False, "email": False, "phone": False}
    clicks: list[str] = []

    def _fill_first(selectors: list[str], value: str, key: str) -> None:
        if not value:
            return
        for selector in selectors:
            try:
                locator = page.locator(selector).first
                if locator.count() == 0:
                    continue
                if not locator.is_visible():
                    continue
                locator.fill(value, timeout=1_500)
                filled[key] = True
                return
            except Exception:
                continue

    _fill_first(
        [
            "input[autocomplete='name']",
            "input[name*='name' i]",
            "input[id*='name' i]",
        ],
        name,
        "name",
    )
    _fill_first(
        [
            "input[type='email']",
            "input[autocomplete='email']",
            "input[name*='email' i]",
            "input[id*='email' i]",
        ],
        email,
        "email",
    )
    _fill_first(
        [
            "input[type='tel']",
            "input[autocomplete='tel']",
            "input[name*='phone' i]",
            "input[id*='phone' i]",
        ],
        phone,
        "phone",
    )

    for pattern, label in [
        (r"continue", "continue"),
        (r"confirm|reserve|book now|complete", "confirm_or_book"),
    ]:
        try:
            button = page.get_by_role("button", name=re.compile(pattern, re.IGNORECASE)).first
            if button.count() > 0 and button.is_visible():
                button.click(timeout=2_000)
                clicks.append(label)
                page.wait_for_timeout(1_000)
                if _page_looks_confirmed(page):
                    break
        except Exception:
            continue

    return {
        "autofill": filled,
        "clicked_buttons": clicks,
    }


def _extract_confirmation_code(html: str) -> str | None:
    match = re.search(r"\b[A-Z0-9]{6,12}\b", html)
    if match is None:
        return None
    return match.group(0)


def _encode_resume_payload(payload: ResumePayload) -> str:
    return json.dumps({"url": payload.url, "slot_time": payload.slot_time})


def _decode_resume_payload(value: str) -> ResumePayload | None:
    try:
        data = json.loads(value)
    except json.JSONDecodeError:
        return None

    if not isinstance(data, dict):
        return None
    url = data.get("url")
    slot_time = data.get("slot_time")
    if not isinstance(url, str):
        return None
    if slot_time is not None and not isinstance(slot_time, str):
        return None

    return ResumePayload(url=url, slot_time=slot_time)
