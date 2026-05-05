from __future__ import annotations

import json
import re
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from time import monotonic
from typing import Any
from urllib.parse import urlparse
from urllib.parse import quote
from urllib.parse import urlencode


_TIME_PATTERN = re.compile(r"\b(?:1[0-2]|[1-9])(?::[0-5]\d)?\s?(?:AM|PM)\b", re.IGNORECASE)
_LOGIN_WAIT_TIMEOUT_MS = 30_000
_LOGIN_INTERACTIVE_TIMEOUT_MS = 300_000
_HEADER_ACTION_POLL_MS = 750
_HEADER_ACTION_POLL_ATTEMPTS = 4


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
        session_profile_dir: str = ".resy_profile",
    ):
        self.headless = headless
        self.timeout_ms = timeout_ms
        self.base_url = base_url.rstrip("/")
        self.reuse_browser_session = reuse_browser_session
        self.session_profile_dir = session_profile_dir
        self._session_profile_path = Path(self.session_profile_dir).expanduser().resolve()
        self._storage_state_path = self._session_profile_path / "storage_state.json"
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

    def ensure_authenticated_session(self) -> dict[str, Any]:
        with self._open_page(self.base_url) as page:
            page = _switch_to_new_booking_page_if_present(page)
            auth_state = _collect_auth_state(page)
            if auth_state.get("logged_in"):
                return {
                    "status": "authenticated",
                    "debug": {"auth_state": auth_state},
                }

            if _page_looks_like_captcha(page):
                return {
                    "status": "captcha_required",
                    "prompt": "Complete CAPTCHA in browser and continue.",
                    "resume_token": None,
                    "debug": {"auth_state": auth_state},
                }

            if self.headless:
                return {
                    "status": "login_required",
                    "prompt": "Login is required. Re-run with --headed, log in to Resy, then continue.",
                    "resume_token": None,
                    "debug": {"auth_state": auth_state},
                }

            login_click = _click_login_button(page)
            wait_result = _wait_for_login_modal_or_authenticated_session(
                page,
                timeout_ms=_LOGIN_WAIT_TIMEOUT_MS,
                return_on_modal_open=True,
            )
            if wait_result.get("status") == "authenticated":
                return {
                    "status": "authenticated",
                    "debug": {
                        "auth_state": wait_result.get("auth_state"),
                        "login_modal_state": wait_result.get("login_modal_state"),
                        "login_click": login_click,
                    },
                }
            if wait_result.get("status") == "captcha_required":
                return {
                    "status": "captcha_required",
                    "prompt": "Complete CAPTCHA in browser and continue.",
                    "resume_token": None,
                    "debug": {
                        "auth_state": wait_result.get("auth_state"),
                        "login_modal_state": wait_result.get("login_modal_state"),
                        "login_click": login_click,
                    },
                }
            if wait_result.get("status") == "login_modal_opened":
                interactive_wait = _wait_for_login_modal_or_authenticated_session(
                    page,
                    timeout_ms=_LOGIN_INTERACTIVE_TIMEOUT_MS,
                    return_on_modal_open=False,
                )
                if interactive_wait.get("status") == "authenticated":
                    return {
                        "status": "authenticated",
                        "debug": {
                            "auth_state": interactive_wait.get("auth_state"),
                            "login_modal_state": interactive_wait.get("login_modal_state"),
                            "login_click": login_click,
                            "login_modal_opened": True,
                            "interactive_wait_completed": True,
                        },
                    }
                if interactive_wait.get("status") == "captcha_required":
                    return {
                        "status": "captcha_required",
                        "prompt": "Complete CAPTCHA in browser and continue.",
                        "resume_token": None,
                        "debug": {
                            "auth_state": interactive_wait.get("auth_state"),
                            "login_modal_state": interactive_wait.get("login_modal_state"),
                            "login_click": login_click,
                            "login_modal_opened": True,
                            "interactive_wait_completed": True,
                        },
                    }
                return {
                    "status": "login_required",
                    "prompt": "Log in to Resy in the opened browser, then re-run the reservation command.",
                    "resume_token": None,
                    "debug": {
                        "auth_state": interactive_wait.get("auth_state", auth_state),
                        "login_modal_state": interactive_wait.get("login_modal_state"),
                        "login_click": login_click,
                        "login_modal_opened": True,
                        "interactive_wait_timeout_ms": _LOGIN_INTERACTIVE_TIMEOUT_MS,
                        "interactive_wait_status": interactive_wait.get("status"),
                        "interactive_modal_seen": interactive_wait.get("modal_seen"),
                    },
                }
            return {
                "status": "login_required",
                "prompt": "Log in to Resy in the opened browser, then re-run the reservation command.",
                "resume_token": None,
                "debug": {
                    "auth_state": wait_result.get("auth_state", auth_state),
                    "login_modal_state": wait_result.get("login_modal_state"),
                    "login_click": login_click,
                },
            }

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
            auth_state = _collect_auth_state(page)
            if auth_state.get("needs_login"):
                prompt = "Log in to Resy in the opened browser, then resume booking."
                if self.headless:
                    prompt = "Login is required. Re-run with --headed, log in to Resy, then resume booking."
                return {
                    "status": "login_required",
                    "prompt": prompt,
                    "resume_token": _encode_resume_payload(
                        ResumePayload(url=str(getattr(page, "url", venue_url)), slot_time=slot_time)
                    ),
                    "debug": {"auth_state": auth_state},
                }

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
            transition_polls: list[dict[str, Any]] = []
            post_click_retries: list[dict[str, Any]] = []
            reserve_now_attempts: list[dict[str, Any]] = []
            confirm_attempts: list[dict[str, Any]] = []
            post_click_state = _collect_checkout_state(page)
            for poll_index in range(1, 7):
                reserve_now = _click_reserve_now_modal_button(page)
                reserve_now_attempts.append({"poll_index": poll_index, **reserve_now})
                confirm_click = _click_confirm_modal_button(page)
                confirm_attempts.append({"poll_index": poll_index, **confirm_click})
                if reserve_now.get("clicked"):
                    page.wait_for_timeout(1_000)
                    try:
                        page.wait_for_load_state("networkidle", timeout=1_500)
                    except Exception:
                        pass
                    page = _switch_to_new_booking_page_if_present(page)
                elif confirm_click.get("clicked"):
                    page.wait_for_timeout(1_000)
                    try:
                        page.wait_for_load_state("networkidle", timeout=1_500)
                    except Exception:
                        pass
                    page = _switch_to_new_booking_page_if_present(page)
                post_click_url = str(getattr(page, "url", ""))
                post_click_state = _collect_checkout_state(page)
                transition_polls.append(
                    {
                        "poll_index": poll_index,
                        "url": post_click_url,
                        "state": post_click_state,
                    }
                )
                if (
                    _page_looks_confirmed(page)
                    or _page_looks_like_captcha(page)
                    or _page_looks_checkout_opened(page)
                    or _checkout_state_indicates_opened(post_click_state)
                ):
                    break
                try:
                    page.wait_for_load_state("networkidle", timeout=1_500)
                except Exception:
                    pass
                page.wait_for_timeout(700)
                page = _switch_to_new_booking_page_if_present(page)

            if not (
                _page_looks_confirmed(page)
                or _page_looks_like_captcha(page)
                or _page_looks_checkout_opened(page)
                or _checkout_state_indicates_opened(post_click_state)
            ):
                for retry_index in range(1, 3):
                    _maybe_expand_all_times(page)
                    retry_click = _click_slot_button_once(page, slot_time)
                    retry_entry = {
                        "retry_index": retry_index,
                        "click": retry_click.diagnostics,
                        "clicked": retry_click.clicked,
                        "reserve_now_attempts": [],
                        "confirm_attempts": [],
                        "polls": [],
                    }
                    post_click_retries.append(retry_entry)
                    if not retry_click.clicked:
                        continue
                    page.wait_for_timeout(1_500)
                    for poll_index in range(1, 5):
                        retry_reserve_now = _click_reserve_now_modal_button(page)
                        retry_entry["reserve_now_attempts"].append(
                            {"poll_index": poll_index, **retry_reserve_now}
                        )
                        retry_confirm = _click_confirm_modal_button(page)
                        retry_entry["confirm_attempts"].append(
                            {"poll_index": poll_index, **retry_confirm}
                        )
                        if retry_reserve_now.get("clicked"):
                            page.wait_for_timeout(1_000)
                        elif retry_confirm.get("clicked"):
                            page.wait_for_timeout(1_000)
                        page = _switch_to_new_booking_page_if_present(page)
                        post_click_url = str(getattr(page, "url", ""))
                        post_click_state = _collect_checkout_state(page)
                        retry_entry["polls"].append(
                            {
                                "poll_index": poll_index,
                                "url": post_click_url,
                                "state": post_click_state,
                            }
                        )
                        if (
                            _page_looks_confirmed(page)
                            or _page_looks_like_captcha(page)
                            or _page_looks_checkout_opened(page)
                            or _checkout_state_indicates_opened(post_click_state)
                        ):
                            break
                        page.wait_for_timeout(700)
                    if (
                        _page_looks_confirmed(page)
                        or _page_looks_like_captcha(page)
                        or _page_looks_checkout_opened(page)
                        or _checkout_state_indicates_opened(post_click_state)
                    ):
                        break

            auth_state_after_click = _collect_auth_state(page)
            if auth_state_after_click.get("needs_login"):
                prompt = "Your Resy session appears expired. Log in again in browser and resume."
                if self.headless:
                    prompt = (
                        "Session refresh is required. Re-run with --headed, log in to Resy, then resume booking."
                    )
                return {
                    "status": "login_refresh_required",
                    "prompt": prompt,
                    "resume_token": _encode_resume_payload(
                        ResumePayload(url=str(getattr(page, "url", venue_url)), slot_time=slot_time)
                    ),
                    "debug": {"auth_state": auth_state_after_click},
                }

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

            if _page_looks_sms_verification(page):
                return {
                    "status": "sms_verification_required",
                    "prompt": "Enter the SMS verification code in browser, then resume booking.",
                    "resume_token": _encode_resume_payload(ResumePayload(url=page.url, slot_time=slot_time)),
                    "debug": {
                        "pre_click_url": pre_click_url,
                        "post_click_url": str(getattr(page, "url", "")),
                    },
                }

            if _page_looks_checkout_opened(page) or _checkout_state_indicates_opened(post_click_state):
                checkout_steps: list[dict[str, Any]] = []
                for step_index in range(1, 4):
                    step_before = _collect_checkout_state(page)
                    checkout_action = _attempt_checkout_autofill_and_submit(page, user_details)
                    page.wait_for_timeout(1_500)
                    page = _switch_to_new_booking_page_if_present(page)
                    step_after = _collect_checkout_state(page)
                    checkout_steps.append(
                        {
                            "step_index": step_index,
                            "before": step_before,
                            "action": checkout_action,
                            "after": step_after,
                        }
                    )

                    if _page_looks_like_captcha(page):
                        return {
                            "status": "captcha_required",
                            "prompt": "Complete CAPTCHA in browser and resume booking.",
                            "resume_token": _encode_resume_payload(
                                ResumePayload(url=str(getattr(page, "url", post_click_url)), slot_time=slot_time)
                            ),
                        }

                    if _page_looks_confirmed(page):
                        return {
                            "status": "success",
                            "confirmation_code": _extract_confirmation_code(page.content()),
                        }

                    if not checkout_action["clicked_buttons"] and not any(checkout_action["autofill"].values()):
                        break

                return {
                    "status": "checkout_opened",
                    "prompt": "Booking details opened. Complete remaining checkout steps in browser and resume.",
                    "resume_token": _encode_resume_payload(
                        ResumePayload(url=str(getattr(page, "url", post_click_url)), slot_time=slot_time)
                    ),
                    "debug": {
                        **click_attempt.diagnostics,
                        "checkout_state": _collect_checkout_state(page),
                        "checkout_steps": checkout_steps,
                        "pre_click_url": pre_click_url,
                        "post_click_url": str(getattr(page, "url", "")),
                        "transition_polls": transition_polls,
                        "post_click_retries": post_click_retries,
                        "reserve_now_attempts": reserve_now_attempts,
                        "confirm_attempts": confirm_attempts,
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
                        "post_click_state": post_click_state,
                        "transition_polls": transition_polls,
                        "post_click_retries": post_click_retries,
                        "reserve_now_attempts": reserve_now_attempts,
                        "confirm_attempts": confirm_attempts,
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
        page = self._existing_page_for_resume(payload.url)
        if page is not None:
            return _resume_result_from_page(page, payload)

        with self._open_page(payload.url) as opened_page:
            return _resume_result_from_page(opened_page, payload)

    def _existing_page_for_resume(self, url: str) -> Any | None:
        if not self.reuse_browser_session or self._page is None:
            return None

        try:
            if self._page.is_closed():
                return None
            page = _switch_to_new_booking_page_if_present(self._page)
            current_url = str(getattr(page, "url", "")).strip()
            if not current_url or current_url == "about:blank":
                page.goto(url, wait_until="domcontentloaded")
            return page
        except Exception:
            return None

    def _open_page(self, url: str):
        if self.reuse_browser_session:
            return _PersistentPageSession(client=self, url=url)
        return _PlaywrightPageSession(
            url=url,
            headless=self.headless,
            timeout_ms=self.timeout_ms,
        )

    def close(self) -> None:
        self._persist_session_state()
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
        if self._page is not None and not self._page.is_closed():
            return self._page

        try:
            from playwright.sync_api import sync_playwright
        except ImportError as error:
            raise RuntimeError(
                "Playwright is not installed. Run '.venv/bin/python -m playwright install'."
            ) from error

        self._playwright = sync_playwright().start()
        self._session_profile_path.mkdir(parents=True, exist_ok=True)
        self._browser = self._playwright.chromium.launch(headless=self.headless)
        context_kwargs: dict[str, Any] = {}
        if self._storage_state_path.exists():
            context_kwargs["storage_state"] = str(self._storage_state_path)
        self._context = self._browser.new_context(**context_kwargs)
        self._page = self._context.new_page()
        self._page.set_default_timeout(self.timeout_ms)
        return self._page

    def _persist_session_state(self) -> None:
        if self._context is None:
            return
        try:
            self._session_profile_path.mkdir(parents=True, exist_ok=True)
            self._context.storage_state(path=str(self._storage_state_path))
        except Exception:
            pass


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
    markers = [
        "reservation confirmed",
        "reservation booked",
        "booking confirmed",
        "you're all set",
        "you are all set",
    ]
    try:
        html_candidates = [page.content().lower()]
    except Exception:
        html_candidates = []

    try:
        for frame in list(page.frames)[1:]:
            try:
                html_candidates.append(frame.content().lower())
            except Exception:
                continue
    except Exception:
        pass

    return any(marker in html for html in html_candidates for marker in markers)


def _collect_auth_state(page: Any) -> dict[str, Any]:
    try:
        state = page.evaluate(
            """
            () => {
                const normalize = (value) => (value || "").replace(/\\s+/g, " ").trim().toLowerCase();
                const bodyText = normalize(document.body?.innerText || "");
                const hasLoginText = bodyText.includes("log in") || bodyText.includes("sign in");
                const accountSelectors = [
                  "[data-test-id*='account']",
                  "[data-testid*='account']",
                  "[aria-label*='account' i]",
                  "a[href*='/settings']",
                  "a[href*='/profile']",
                  "button[aria-label*='account' i]",
                ];
                const hasAccountElement = accountSelectors.some((selector) =>
                  document.querySelector(selector) instanceof HTMLElement
                );
                const hasLogoutText = bodyText.includes("log out") || bodyText.includes("sign out");
                const loginCtas = Array.from(document.querySelectorAll("a, button, [role='button']"))
                  .map((node) => normalize(node.textContent || node.getAttribute("aria-label") || ""))
                  .filter(Boolean);
                const hasLoginCta = loginCtas.some(
                  (text) => text === "log in" || text === "sign in" || text.includes("log in")
                );
                const inferredLoggedInFromMissingLoginCta = Boolean(
                  !hasLoginCta && !hasAccountElement && !hasLogoutText
                );
                const loggedIn = Boolean(hasAccountElement || hasLogoutText || inferredLoggedInFromMissingLoginCta);
                const needsLogin = Boolean(hasLoginCta && !loggedIn);
                return {
                  logged_in: loggedIn,
                  needs_login: needsLogin,
                  has_login_cta: hasLoginCta,
                  has_login_text: hasLoginText,
                  has_account_element: hasAccountElement,
                  has_logout_text: hasLogoutText,
                  inferred_logged_in_from_missing_login_cta: inferredLoggedInFromMissingLoginCta,
                  url: window.location.href,
                };
            }
            """
        )
    except Exception:
        return {"logged_in": False, "needs_login": False, "detection_error": True}

    if not isinstance(state, dict):
        return {"logged_in": False, "needs_login": False, "detection_error": True}
    return state


def _click_login_button(page: Any) -> dict[str, Any]:
    selectors = [
        (
            "css_resy_nav_login_button_exact_path",
            lambda: page.locator(
                "div.ResyNav__right-wrapper:nth-of-type(2) > resy-menu-container > "
                "div.MenuContainer.MenuContainer--desktop > button.Button.Button--login"
            ),
        ),
        (
            "css_resy_nav_login_button",
            lambda: page.locator(
                "div.ResyNav__right-wrapper > resy-menu-container button.Button.Button--login, "
                "div.ResyNav__right-wrapper button.Button.Button--login, "
                "button.Button.Button--login"
            ),
        ),
        (
            "css_button_login_lowercase",
            lambda: page.locator("button:has-text('Log in'), button:has-text('Sign in')"),
        ),
        (
            "role_link_exact_log_in",
            lambda: page.get_by_role("link", name=re.compile(r"^\s*log in\s*$", re.IGNORECASE)),
        ),
        (
            "role_button_exact_log_in",
            lambda: page.get_by_role("button", name=re.compile(r"^\s*log in\s*$", re.IGNORECASE)),
        ),
        (
            "role_link_contains_sign_in",
            lambda: page.get_by_role("link", name=re.compile(r"sign in|log in", re.IGNORECASE)),
        ),
        (
            "role_button_contains_sign_in",
            lambda: page.get_by_role("button", name=re.compile(r"sign in|log in", re.IGNORECASE)),
        ),
        ("css_link_text_log_in", lambda: page.locator("a:has-text('Log In'), a:has-text('Sign In')")),
        (
            "css_button_text_log_in",
            lambda: page.locator("button:has-text('Log In'), button:has-text('Sign In')"),
        ),
    ]
    attempted: list[str] = []
    selector_diagnostics: list[dict[str, Any]] = []
    menu_open_attempt = _open_resy_navigation_menu(page)
    if menu_open_attempt.get("opened"):
        attempted.append("open_resy_navigation_menu")
    for selector_name, locator_factory in selectors:
        attempted.append(selector_name)
        try:
            locator = locator_factory()
            candidate_count = locator.count()
            selector_info: dict[str, Any] = {
                "selector": selector_name,
                "candidate_count": candidate_count,
                "visible_candidates": [],
            }
            selector_diagnostics.append(selector_info)
            if candidate_count == 0:
                continue
            for index in range(candidate_count):
                candidate = locator.nth(index)
                try:
                    is_visible = bool(candidate.is_visible())
                    if not is_visible:
                        selector_info["visible_candidates"].append(
                            {
                                "index": index,
                                "visible": False,
                            }
                        )
                        continue
                except Exception:
                    selector_info["visible_candidates"].append(
                        {
                            "index": index,
                            "visible": None,
                            "visibility_error": True,
                        }
                    )
                    continue
                clicked_text = ""
                try:
                    clicked_text = str(candidate.inner_text(timeout=800)).strip()
                except Exception:
                    clicked_text = ""
                selector_info["visible_candidates"].append(
                    {
                        "index": index,
                        "visible": True,
                        "text": clicked_text,
                    }
                )
                try:
                    candidate.click(timeout=2_500)
                except Exception:
                    candidate.click(timeout=2_500, force=True)
                return {
                    "clicked": True,
                    "clicked_via": selector_name,
                    "clicked_text": clicked_text,
                    "clicked_index": index,
                    "candidate_count": candidate_count,
                    "attempted_selectors": attempted,
                    "selector_diagnostics": selector_diagnostics,
                    "menu_open_attempt": menu_open_attempt,
                }
            try:
                clicked_text = str(locator.first.inner_text(timeout=800)).strip()
            except Exception:
                clicked_text = ""
            try:
                locator.first.click(timeout=2_500, force=True)
                return {
                    "clicked": True,
                    "clicked_via": f"{selector_name}_force",
                    "clicked_text": clicked_text,
                    "candidate_count": candidate_count,
                    "attempted_selectors": attempted,
                    "selector_diagnostics": selector_diagnostics,
                    "menu_open_attempt": menu_open_attempt,
                }
            except Exception:
                pass
        except Exception as error:
            attempted.append(f"{selector_name}_error:{error.__class__.__name__}")
            selector_diagnostics.append(
                {
                    "selector": selector_name,
                    "error": error.__class__.__name__,
                }
            )

    try:
        fallback = page.evaluate(
            """
            () => {
                const normalize = (value) => (value || "").replace(/\\s+/g, " ").trim().toLowerCase();
                const exactNavSelectors = [
                  "div.ResyNav__right-wrapper:nth-of-type(2) > resy-menu-container > div.MenuContainer.MenuContainer--desktop > button.Button.Button--login",
                  "div.ResyNav__right-wrapper > resy-menu-container button.Button.Button--login",
                  "div.ResyNav__right-wrapper button.Button.Button--login",
                  "button.Button.Button--login",
                ];
                const summarize = (node, index) => {
                  if (!(node instanceof HTMLElement)) return null;
                  return {
                    index,
                    tag: node.tagName.toLowerCase(),
                    text: (node.textContent || node.getAttribute("aria-label") || "").trim(),
                    class_name: node.className || "",
                    role: node.getAttribute("role") || "",
                    visible: node.getClientRects().length > 0,
                  };
                };
                for (const selector of exactNavSelectors) {
                  const node = document.querySelector(selector);
                  if (!(node instanceof HTMLElement)) continue;
                  node.scrollIntoView({ block: "center", inline: "center" });
                  node.click();
                  return {
                    clicked: true,
                    clicked_via: "evaluate_exact_nav_login_button",
                    clicked_text: (node.textContent || node.getAttribute("aria-label") || "").trim(),
                    dom_candidates: exactNavSelectors.map((candidateSelector) => ({
                      selector: candidateSelector,
                      matched: Boolean(document.querySelector(candidateSelector)),
                    })),
                  };
                }
                const nodes = Array.from(document.querySelectorAll("button, a, [role='button']"));
                const samples = nodes
                  .map((node, index) => summarize(node, index))
                  .filter(Boolean)
                  .slice(0, 25);
                for (const node of nodes) {
                  if (!(node instanceof HTMLElement)) continue;
                  const text = normalize(node.textContent || node.getAttribute("aria-label") || "");
                  const cls = normalize(node.className || "");
                  if (
                    text === "log in" ||
                    text === "sign in" ||
                    text.includes("log in") ||
                    cls.includes("button--login")
                  ) {
                    node.scrollIntoView({ block: "center", inline: "center" });
                    node.click();
                    return {
                      clicked: true,
                      clicked_via: "evaluate_login_button_scan",
                      clicked_text: (node.textContent || node.getAttribute("aria-label") || "").trim(),
                      dom_candidates: samples,
                    };
                  }
                }
                return {
                  clicked: false,
                  dom_candidates: samples,
                  body_has_log_in: normalize(document.body?.innerText || "").includes("log in"),
                  exact_nav_selector_matches: exactNavSelectors.map((selector) => ({
                    selector,
                    matched: Boolean(document.querySelector(selector)),
                  })),
                };
            }
            """
        )
        if isinstance(fallback, dict) and fallback.get("clicked"):
            return {
                "clicked": True,
                "clicked_via": fallback.get("clicked_via", "evaluate_login_button_scan"),
                "clicked_text": fallback.get("clicked_text", ""),
                "attempted_selectors": attempted + ["evaluate_login_button_scan"],
                "selector_diagnostics": selector_diagnostics,
                "dom_candidates": fallback.get("dom_candidates", []),
                "menu_open_attempt": menu_open_attempt,
            }
        attempted.append("evaluate_login_button_scan")
        if isinstance(fallback, dict):
            return {
                "clicked": False,
                "attempted_selectors": attempted,
                "selector_diagnostics": selector_diagnostics,
                "dom_candidates": fallback.get("dom_candidates", []),
                "body_has_log_in": fallback.get("body_has_log_in"),
                "exact_nav_selector_matches": fallback.get("exact_nav_selector_matches", []),
                "menu_open_attempt": menu_open_attempt,
            }
    except Exception as error:
        attempted.append(f"evaluate_login_button_scan_error:{error.__class__.__name__}")

    return {
        "clicked": False,
        "attempted_selectors": attempted,
        "selector_diagnostics": selector_diagnostics,
        "menu_open_attempt": menu_open_attempt,
    }


def _wait_for_login_modal_or_authenticated_session(
    page: Any,
    timeout_ms: int,
    *,
    return_on_modal_open: bool = True,
) -> dict[str, Any]:
    deadline = monotonic() + (timeout_ms / 1000)
    latest_auth_state = _collect_auth_state(page)
    latest_login_modal_state = _collect_login_modal_state(page)
    modal_seen = bool(
        latest_login_modal_state.get("modal_visible") or latest_login_modal_state.get("has_auth_phrase")
    )
    while monotonic() < deadline:
        page = _switch_to_new_booking_page_if_present(page)
        latest_auth_state = _collect_auth_state(page)
        latest_login_modal_state = _collect_login_modal_state(page)
        if latest_login_modal_state.get("modal_visible") or latest_login_modal_state.get("has_auth_phrase"):
            modal_seen = True
        if latest_auth_state.get("logged_in"):
            return {
                "status": "authenticated",
                "auth_state": latest_auth_state,
                "login_modal_state": latest_login_modal_state,
                "modal_seen": modal_seen,
            }
        if (
            modal_seen
            and not latest_login_modal_state.get("modal_visible")
            and not latest_auth_state.get("needs_login")
        ):
            return {
                "status": "authenticated",
                "auth_state": {
                    **latest_auth_state,
                    "inferred_from_modal_completion": True,
                },
                "login_modal_state": latest_login_modal_state,
                "modal_seen": modal_seen,
            }
        if _page_looks_like_captcha(page):
            return {
                "status": "captcha_required",
                "auth_state": latest_auth_state,
                "login_modal_state": latest_login_modal_state,
                "modal_seen": modal_seen,
            }
        if return_on_modal_open and (
            latest_login_modal_state.get("modal_visible") or latest_login_modal_state.get("has_auth_phrase")
        ):
            return {
                "status": "login_modal_opened",
                "auth_state": latest_auth_state,
                "login_modal_state": latest_login_modal_state,
                "modal_seen": modal_seen,
            }
        page.wait_for_timeout(1_000)

    return {
        "status": "timeout",
        "auth_state": latest_auth_state,
        "login_modal_state": latest_login_modal_state,
        "modal_seen": modal_seen,
    }


def _collect_login_modal_state(page: Any) -> dict[str, Any]:
    try:
        state = page.evaluate(
            """
            () => {
                const normalize = (value) => (value || "").replace(/\\s+/g, " ").trim().toLowerCase();
                const bodyText = normalize(document.body?.innerText || "");
                const modalSelectors = [
                  "div.ReactModal__Content.ReactModal__Content--after-open",
                  "div.ReactModal__Content--after-open",
                  "div.AuthContainer",
                  "div.AuthView",
                ];
                const modalNode = modalSelectors
                  .map((selector) => document.querySelector(selector))
                  .find((node) => node instanceof HTMLElement && node.getClientRects().length > 0);
                const modalText = normalize(modalNode?.innerText || modalNode?.textContent || "");
                const strongPhrases = [
                  "please enter your mobile phone number",
                  "log in with email & password",
                  "log in with email & one-time code",
                  "enter your mobile phone number",
                  "verify or create an account",
                ];
                return {
                  modal_visible: Boolean(modalNode),
                  modal_text: modalText,
                  has_auth_phrase: strongPhrases.some((phrase) => bodyText.includes(phrase)),
                  has_phone_prompt: bodyText.includes("mobile phone number"),
                  has_email_password_link: bodyText.includes("log in with email & password"),
                  has_one_time_code_link: bodyText.includes("log in with email & one-time code"),
                  url: window.location.href,
                };
            }
            """
        )
    except Exception:
        return {"modal_visible": False, "detection_error": True}

    if not isinstance(state, dict):
        return {"modal_visible": False, "detection_error": True}
    return state


def _open_resy_navigation_menu(page: Any) -> dict[str, Any]:
    selectors = [
        (
            "banner_role_button_menu",
            lambda: page.get_by_role("banner").get_by_role("button", name="Menu", exact=True),
        ),
        ("role_button_menu", lambda: page.get_by_role("button", name="Menu", exact=True)),
        ("css_button_menu", lambda: page.locator("button:has-text('Menu')")),
        ("css_nav_button_aria_menu", lambda: page.locator("button[aria-label='Menu']")),
        (
            "css_button_menu_test_id_exact",
            lambda: page.locator(
                "[data-test-id='menu_container-button-menu'], [data-testid='menu_container-button-menu']"
            ),
        ),
    ]
    attempted: list[str] = []
    poll_diagnostics: list[dict[str, Any]] = []
    for poll_index in range(_HEADER_ACTION_POLL_ATTEMPTS):
        selector_diagnostics: list[dict[str, Any]] = []
        for selector_name, locator_factory in selectors:
            attempted.append(selector_name)
            try:
                locator = locator_factory()
                count = locator.count()
                info: dict[str, Any] = {
                    "selector": selector_name,
                    "candidate_count": count,
                }
                selector_diagnostics.append(info)
                if count != 1:
                    continue
                if not locator.is_visible():
                    info["visible"] = False
                    continue
                info["visible"] = True
                try:
                    text = str(locator.inner_text(timeout=800)).strip()
                except Exception:
                    text = "Menu"
                info["text"] = text
                normalized_text = text.lower()
                if "log in" in normalized_text or "sign in" in normalized_text:
                    info["skipped_reason"] = "menu_selector_matched_login_button"
                    continue
                locator.click(timeout=2_500)
                return {
                    "opened": True,
                    "opened_via": selector_name,
                    "button_text": text,
                    "attempted_selectors": attempted,
                    "poll_diagnostics": poll_diagnostics + [{"poll": poll_index, "selectors": selector_diagnostics}],
                }
            except Exception as error:
                attempted.append(f"{selector_name}_error:{error.__class__.__name__}")
                selector_diagnostics.append(
                    {
                        "selector": selector_name,
                        "error": error.__class__.__name__,
                    }
                )
        poll_diagnostics.append(
            {
                "poll": poll_index,
                "selectors": selector_diagnostics,
                "header_snapshot": _collect_header_action_snapshot(page),
            }
        )
        if poll_index < _HEADER_ACTION_POLL_ATTEMPTS - 1:
            _safe_wait_for_timeout(page, _HEADER_ACTION_POLL_MS)
    return {
        "opened": False,
        "attempted_selectors": attempted,
        "poll_diagnostics": poll_diagnostics,
    }


def _collect_header_action_snapshot(page: Any) -> dict[str, Any]:
    try:
        snapshot = page.evaluate(
            """
            () => {
                const normalize = (value) => (value || "").replace(/\\s+/g, " ").trim();
                const nodes = Array.from(
                  document.querySelectorAll(
                    "header button, [role='banner'] button, nav button, button, [role='button']"
                  )
                );
                const topButtons = nodes
                  .filter((node) => node instanceof HTMLElement)
                  .map((node, index) => {
                    const rect = node.getBoundingClientRect();
                    return {
                      index,
                      text: normalize(node.textContent || node.getAttribute("aria-label") || ""),
                      aria_label: normalize(node.getAttribute("aria-label") || ""),
                      class_name: node.className || "",
                      data_test_id: node.getAttribute("data-test-id") || "",
                      visible: node.getClientRects().length > 0,
                      top: Math.round(rect.top),
                      left: Math.round(rect.left),
                    };
                  })
                  .filter((node) => node.visible)
                  .sort((a, b) => a.top - b.top || a.left - b.left)
                  .slice(0, 12);
                const bodyText = normalize(document.body?.innerText || "").toLowerCase();
                return {
                  top_buttons: topButtons,
                  body_has_menu: bodyText.includes("menu"),
                  body_has_log_in: bodyText.includes("log in"),
                };
            }
            """
        )
    except Exception:
        return {"snapshot_error": True}
    if not isinstance(snapshot, dict):
        return {"snapshot_error": True}
    return snapshot


def _safe_wait_for_timeout(page: Any, timeout_ms: int) -> None:
    wait_for_timeout = getattr(page, "wait_for_timeout", None)
    if callable(wait_for_timeout):
        wait_for_timeout(timeout_ms)


def _page_looks_sms_verification(page: Any) -> bool:
    html = page.content().lower()
    markers = (
        "verification code",
        "enter code",
        "texted you a code",
        "text message",
        "one-time code",
        "otp",
    )
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
                      "reserve now",
                      "cancellation policy",
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


def _collect_checkout_state(page: Any) -> dict[str, Any]:
    try:
        snapshot = page.evaluate(
            """
            () => {
                const body = (document.body?.innerText || "").toLowerCase();
                const checkoutPhrases = [
                  "complete your reservation",
                  "reservation details",
                  "confirm reservation",
                  "booking details",
                  "contact information",
                  "payment",
                  "reserve now",
                  "cancellation policy",
                ];
                const visibility = (node) => {
                  if (!(node instanceof HTMLElement)) return false;
                  if (node.getClientRects().length === 0) return false;
                  const style = window.getComputedStyle(node);
                  return style.visibility !== "hidden" && style.display !== "none";
                };
                const hasVisibleCheckoutContainer = Array.from(
                  document.querySelectorAll(
                    "[role='dialog'], [aria-modal='true'], [data-test-id*='checkout'], [data-testid*='checkout'], [class*='checkout'], [class*='Checkout'], [class*='drawer'], [class*='Drawer']"
                  )
                ).some((node) => visibility(node));
                const buttonData = Array.from(
                  document.querySelectorAll("button, [role='button'], input[type='submit']")
                )
                  .map((node) => {
                    const text =
                      (node instanceof HTMLInputElement ? node.value : node.textContent || "").replace(/\\s+/g, " ").trim();
                    if (!text) return null;
                    const lowered = text.toLowerCase();
                    if (
                      !(
                        lowered.includes("continue") ||
                        lowered.includes("confirm") ||
                        lowered.includes("reserve") ||
                        lowered.includes("book") ||
                        lowered.includes("payment") ||
                        lowered.includes("checkout")
                      )
                    ) {
                      return null;
                    }
                    return {
                      text,
                      visible: visibility(node),
                      disabled:
                        node.hasAttribute("disabled") ||
                        node.getAttribute("aria-disabled") === "true",
                    };
                  })
                  .filter(Boolean)
                  .slice(0, 8);
                const readField = (selectors) => {
                  for (const selector of selectors) {
                    const node = document.querySelector(selector);
                    if (!(node instanceof HTMLInputElement) && !(node instanceof HTMLTextAreaElement)) continue;
                    return {
                      present: true,
                      visible: visibility(node),
                      filled: Boolean((node.value || "").trim()),
                      required: node.required || node.getAttribute("aria-required") === "true",
                    };
                  }
                  return { present: false, visible: false, filled: false, required: false };
                };
                const errors = Array.from(
                  document.querySelectorAll(
                    "[aria-invalid='true'], [role='alert'], .error, .Error, [data-test-id*='error'], [data-testid*='error']"
                  )
                )
                  .map((node) => (node.textContent || "").replace(/\\s+/g, " ").trim())
                  .filter(Boolean)
                  .slice(0, 8);
                const resourceEntries = performance
                  .getEntriesByType("resource")
                  .filter((entry) => {
                    const initiator = (entry.initiatorType || "").toLowerCase();
                    return initiator === "fetch" || initiator === "xmlhttprequest";
                  });
                return {
                  url: window.location.href,
                  has_checkout_phrase: checkoutPhrases.some((phrase) => body.includes(phrase)),
                  has_checkout_container: hasVisibleCheckoutContainer,
                  checkout_buttons: buttonData,
                  checkout_button_count: buttonData.length,
                  fields: {
                    name: readField(["input[autocomplete='name']", "input[name*='name' i]", "input[id*='name' i]"]),
                    email: readField(["input[type='email']", "input[name*='email' i]", "input[id*='email' i]"]),
                    phone: readField(["input[type='tel']", "input[name*='phone' i]", "input[id*='phone' i]"]),
                  },
                  validation_errors: errors,
                  network: {
                    xhr_fetch_count: resourceEntries.length,
                    recent_requests: resourceEntries.slice(-5).map((entry) => ({
                      initiator: entry.initiatorType || "",
                      duration_ms: Math.round(entry.duration || 0),
                      name: (entry.name || "").slice(0, 140),
                    })),
                  },
                };
            }
            """
        )
    except Exception:
        return {
            "snapshot_error": True,
            "url": str(getattr(page, "url", "")),
        }
    return snapshot if isinstance(snapshot, dict) else {"snapshot_error": True}


def _checkout_state_indicates_opened(state: dict[str, Any]) -> bool:
    if not isinstance(state, dict):
        return False
    if state.get("has_checkout_phrase") or state.get("has_checkout_container"):
        return True

    if state.get("checkout_button_count", 0):
        return True

    fields = state.get("fields")
    if not isinstance(fields, dict):
        return False

    for key in ("email", "phone", "name"):
        field = fields.get(key)
        if isinstance(field, dict) and field.get("present"):
            return True
    return False


def _click_reserve_now_modal_button(page: Any) -> dict[str, Any]:
    selectors = [
        ("role_button_exact_reserve_now", lambda: page.get_by_role("button", name=re.compile(r"^\s*reserve now\s*$", re.IGNORECASE)).first),
        ("role_button_contains_reserve_now", lambda: page.get_by_role("button", name=re.compile(r"reserve now", re.IGNORECASE)).first),
        ("css_button_text_reserve_now", lambda: page.locator("button:has-text('Reserve Now')").first),
        ("css_modal_button_reserve_now", lambda: page.locator("[role='dialog'] button:has-text('Reserve Now'), [aria-modal='true'] button:has-text('Reserve Now')").first),
    ]
    attempted: list[str] = []
    for selector_name, locator_factory in selectors:
        attempted.append(selector_name)
        try:
            locator = locator_factory()
            if locator.count() == 0:
                continue
            if not locator.is_visible():
                continue
            try:
                if hasattr(locator, "is_enabled") and not locator.is_enabled():
                    continue
            except Exception:
                pass
            label = ""
            try:
                label = str(locator.inner_text(timeout=800)).strip()
            except Exception:
                label = ""
            locator.click(timeout=2_500)
            return {
                "clicked": True,
                "clicked_via": selector_name,
                "clicked_text": label,
                "attempted_selectors": attempted,
            }
        except Exception as error:
            attempted.append(f"{selector_name}_error:{error.__class__.__name__}")

    try:
        fallback = page.evaluate(
            """
            () => {
                const normalize = (value) => (value || "").replace(/\\s+/g, " ").trim().toLowerCase();
                const isVisible = (node) => {
                  if (!(node instanceof HTMLElement)) return false;
                  if (node.getClientRects().length === 0) return false;
                  const style = window.getComputedStyle(node);
                  return style.display !== "none" && style.visibility !== "hidden";
                };
                const clickNode = (node) => {
                  node.scrollIntoView({ block: "center", inline: "center" });
                  try {
                    node.click();
                  } catch (error) {
                    const events = ["pointerdown", "mousedown", "pointerup", "mouseup", "click"];
                    for (const type of events) {
                      node.dispatchEvent(new MouseEvent(type, { bubbles: true, cancelable: true, view: window }));
                    }
                  }
                };
                const selectors = [
                  "button",
                  "[role='button']",
                  "a",
                  "[data-test-id*='reserve']",
                  "[data-testid*='reserve']",
                  "[class*='reserve']",
                ];
                const seen = new WeakSet();
                for (const selector of selectors) {
                  for (const node of document.querySelectorAll(selector)) {
                    if (!(node instanceof HTMLElement)) continue;
                    if (seen.has(node)) continue;
                    seen.add(node);
                    if (!isVisible(node)) continue;
                    const text = normalize(node.innerText || node.textContent || "");
                    const aria = normalize(node.getAttribute("aria-label") || "");
                    const value = normalize(node instanceof HTMLInputElement ? node.value : "");
                    if (text !== "reserve now" && !text.includes("reserve now") && aria !== "reserve now" && value !== "reserve now") {
                      continue;
                    }
                    clickNode(node);
                    return {
                      clicked: true,
                      clicked_via: "evaluate_text_scan_reserve_now",
                      clicked_text: (node.innerText || node.textContent || node.getAttribute("aria-label") || "").trim(),
                    };
                  }
                }
                return { clicked: false };
            }
            """
        )
        if isinstance(fallback, dict) and fallback.get("clicked"):
            return {
                "clicked": True,
                "clicked_via": fallback.get("clicked_via", "evaluate_text_scan_reserve_now"),
                "clicked_text": fallback.get("clicked_text", ""),
                "attempted_selectors": attempted + ["evaluate_text_scan_reserve_now"],
            }
        attempted.append("evaluate_text_scan_reserve_now")
    except Exception as error:
        attempted.append(f"evaluate_text_scan_reserve_now_error:{error.__class__.__name__}")

    try:
        for frame in list(page.frames)[1:]:
            for selector_name, locator_factory in [
                (
                    "frame_role_button_exact_reserve_now",
                    lambda: frame.get_by_role(
                        "button",
                        name=re.compile(r"^\s*reserve now\s*$", re.IGNORECASE),
                    ).first,
                ),
                (
                    "frame_css_button_text_reserve_now",
                    lambda: frame.locator("button:has-text('Reserve Now'), [role='button']:has-text('Reserve Now')").first,
                ),
            ]:
                attempted.append(selector_name)
                try:
                    locator = locator_factory()
                    if locator.count() == 0:
                        continue
                    if not locator.is_visible():
                        continue
                    locator.click(timeout=2_500)
                    return {
                        "clicked": True,
                        "clicked_via": selector_name,
                        "clicked_text": "Reserve Now",
                        "frame_url": str(getattr(frame, "url", "")),
                        "attempted_selectors": attempted,
                    }
                except Exception as error:
                    attempted.append(f"{selector_name}_error:{error.__class__.__name__}")
    except Exception as error:
        attempted.append(f"frame_scan_error:{error.__class__.__name__}")

    return {
        "clicked": False,
        "attempted_selectors": attempted,
    }


def _click_confirm_modal_button(page: Any) -> dict[str, Any]:
    selectors = [
        (
            "role_button_exact_confirm",
            lambda: page.get_by_role("button", name=re.compile(r"^\s*confirm\s*$", re.IGNORECASE)).first,
        ),
        (
            "role_button_contains_confirm",
            lambda: page.get_by_role("button", name=re.compile(r"confirm", re.IGNORECASE)).first,
        ),
        ("css_button_text_confirm", lambda: page.locator("button:has-text('Confirm')").first),
        (
            "css_modal_button_confirm",
            lambda: page.locator("[role='dialog'] button:has-text('Confirm'), [aria-modal='true'] button:has-text('Confirm')").first,
        ),
    ]
    attempted: list[str] = []
    for selector_name, locator_factory in selectors:
        attempted.append(selector_name)
        try:
            locator = locator_factory()
            if locator.count() == 0:
                continue
            if not locator.is_visible():
                continue
            label = ""
            try:
                label = str(locator.inner_text(timeout=800)).strip()
            except Exception:
                label = ""
            locator.click(timeout=2_500)
            return {
                "clicked": True,
                "clicked_via": selector_name,
                "clicked_text": label,
                "attempted_selectors": attempted,
            }
        except Exception as error:
            attempted.append(f"{selector_name}_error:{error.__class__.__name__}")

    try:
        for frame in list(page.frames)[1:]:
            for selector_name, locator_factory in [
                (
                    "frame_role_button_exact_confirm",
                    lambda: frame.get_by_role(
                        "button",
                        name=re.compile(r"^\s*confirm\s*$", re.IGNORECASE),
                    ).first,
                ),
                (
                    "frame_css_button_text_confirm",
                    lambda: frame.locator("button:has-text('Confirm'), [role='button']:has-text('Confirm')").first,
                ),
            ]:
                attempted.append(selector_name)
                try:
                    locator = locator_factory()
                    if locator.count() == 0:
                        continue
                    if not locator.is_visible():
                        continue
                    locator.click(timeout=2_500)
                    return {
                        "clicked": True,
                        "clicked_via": selector_name,
                        "clicked_text": "Confirm",
                        "frame_url": str(getattr(frame, "url", "")),
                        "attempted_selectors": attempted,
                    }
                except Exception as error:
                    attempted.append(f"{selector_name}_error:{error.__class__.__name__}")
    except Exception as error:
        attempted.append(f"frame_scan_error:{error.__class__.__name__}")

    return {
        "clicked": False,
        "attempted_selectors": attempted,
    }


def _attempt_checkout_autofill_and_submit(page: Any, user_details: dict[str, Any]) -> dict[str, Any]:
    name = str(user_details.get("name") or "").strip()
    email = str(user_details.get("email") or "").strip()
    phone = str(user_details.get("phone") or "").strip()
    name_parts = name.split()
    first_name = name_parts[0] if name_parts else ""
    last_name = " ".join(name_parts[1:]) if len(name_parts) > 1 else ""

    filled = {"name": False, "first_name": False, "last_name": False, "email": False, "phone": False}
    clicks: list[str] = []
    reserve_now_click = _click_reserve_now_modal_button(page)
    if reserve_now_click.get("clicked"):
        clicks.append("reserve_now_modal")
        page.wait_for_timeout(800)
    confirm_click = _click_confirm_modal_button(page)
    if confirm_click.get("clicked"):
        clicks.append("confirm_modal")
        page.wait_for_timeout(800)

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
            "input[autocomplete='given-name']",
            "input[name*='first' i]",
            "input[id*='first' i]",
        ],
        first_name,
        "first_name",
    )
    _fill_first(
        [
            "input[autocomplete='family-name']",
            "input[name*='last' i]",
            "input[id*='last' i]",
        ],
        last_name,
        "last_name",
    )
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
        (r"continue|next|proceed|review", "continue"),
        (r"confirm|reserve|book now|complete|submit|place", "confirm_or_book"),
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

    try:
        submit = page.locator("button[type='submit'], input[type='submit']").first
        if submit.count() > 0 and submit.is_visible():
            submit.click(timeout=2_000)
            clicks.append("submit")
            page.wait_for_timeout(1_000)
    except Exception:
        pass

    return {
        "autofill": filled,
        "clicked_buttons": clicks,
        "reserve_now_click": reserve_now_click,
        "confirm_click": confirm_click,
    }


def _resume_result_from_page(page: Any, payload: ResumePayload) -> dict[str, Any]:
    page.wait_for_timeout(2_000)
    page = _switch_to_new_booking_page_if_present(page)
    auth_state = _collect_auth_state(page)
    if auth_state.get("needs_login"):
        return {
            "status": "login_refresh_required",
            "prompt": "Your Resy session appears expired. Log in again in browser and resume.",
            "resume_token": _encode_resume_payload(
                ResumePayload(url=str(getattr(page, "url", payload.url)), slot_time=payload.slot_time)
            ),
            "debug": {"auth_state": auth_state},
        }

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

    if _page_looks_sms_verification(page):
        return {
            "status": "sms_verification_required",
            "prompt": "Enter the SMS verification code in browser, then resume booking.",
            "resume_token": _encode_resume_payload(
                ResumePayload(url=str(getattr(page, "url", payload.url)), slot_time=payload.slot_time)
            ),
            "debug": {"auth_state": auth_state},
        }

    checkout_state = _collect_checkout_state(page)
    if _page_looks_checkout_opened(page) or _checkout_state_indicates_opened(checkout_state):
        return {
            "status": "checkout_opened",
            "prompt": "Checkout is still open. Complete remaining steps in browser and resume.",
            "resume_token": _encode_resume_payload(
                ResumePayload(url=str(getattr(page, "url", payload.url)), slot_time=payload.slot_time)
            ),
            "debug": {"checkout_state": checkout_state},
        }

    return {
        "status": "failure",
        "reason": "resume_failed",
        "debug": {"checkout_state": checkout_state},
    }


def _extract_confirmation_code(html: str) -> str | None:
    text = re.sub(r"(?is)<(script|style)[^>]*>.*?</\\1>", " ", html or "")
    text = re.sub(r"(?is)<!DOCTYPE[^>]*>", " ", text)
    text = re.sub(r"(?is)<[^>]+>", "\n", text)
    text = re.sub(r"&nbsp;", " ", text, flags=re.IGNORECASE)
    text = re.sub(r"\s+", " ", text)
    normalized_text = text.strip()
    lowered = normalized_text.lower()

    summary_patterns = [
        r"(Reservation Booked\.?(?: Please check your inbox for a confirmation email\.)?)",
        r"(Reservation Confirmed\.?(?: Please check your inbox for a confirmation email\.)?)",
    ]
    for pattern in summary_patterns:
        match = re.search(pattern, normalized_text, re.IGNORECASE)
        if match is not None:
            return match.group(1).strip()

    reserved_tokens = {"DOCTYPE", "HTML", "HEAD", "BODY", "SCRIPT", "STYLE"}
    if "reservation booked" in lowered or "reservation confirmed" in lowered:
        tokens = re.findall(r"\b[A-Z0-9]{6,12}\b", normalized_text)
        for token in tokens:
            if token not in reserved_tokens:
                return token
        return "Reservation confirmed"

    match = re.search(r"\b[A-Z0-9]{6,12}\b", normalized_text)
    if match is None or match.group(0) in reserved_tokens:
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
