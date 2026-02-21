"""Shared Playwright browser setup and utilities for Amazon.ca."""

import os
import random
import time

AMAZON_CA = "https://www.amazon.ca"
BROWSER_PROFILE_DIR = os.path.join(os.path.dirname(os.path.abspath(__file__)), ".browser-profile")
DEBUG_DIR = os.path.join(os.path.dirname(os.path.abspath(__file__)), "debug")
os.makedirs(DEBUG_DIR, exist_ok=True)


def delay(lo=1.5, hi=3.0):
    time.sleep(random.uniform(lo, hi))


def setup_browser(playwright):
    return playwright.chromium.launch_persistent_context(
        BROWSER_PROFILE_DIR,
        headless=False,
        viewport={"width": random.randint(1280, 1440), "height": random.randint(800, 900)},
        user_agent=(
            "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
            "AppleWebKit/537.36 (KHTML, like Gecko) "
            "Chrome/122.0.0.0 Safari/537.36"
        ),
        locale="en-CA",
        timezone_id="America/Toronto",
        args=["--disable-blink-features=AutomationControlled"],
    )


def is_signed_in(page):
    """Check if currently signed into Amazon."""
    try:
        nav_text = page.locator("#nav-link-accountList-nav-line-1").text_content(timeout=3000)
        return nav_text and "sign in" not in nav_text.lower() and "hello" in nav_text.lower()
    except Exception:
        return False


def ensure_signed_in(page, timeout_seconds=90):
    """Navigate to Amazon and wait for sign-in. Returns True if signed in."""
    page.goto(f"{AMAZON_CA}/gp/css/homepage.html", wait_until="domcontentloaded", timeout=30000)
    delay(3, 5)

    start = time.time()
    while time.time() - start < timeout_seconds:
        if is_signed_in(page):
            return True
        time.sleep(3)
    return False


def is_real_captcha(page):
    try:
        captcha_form = page.locator("form[action*='validateCaptcha'], #captchacharacters")
        return captcha_form.is_visible(timeout=2000)
    except Exception:
        return False


def remove_zoom_overlay(page):
    page.evaluate("""
    () => {
        document.querySelectorAll('[id*="zoom"], [class*="zoom"], [id*="magnifier"]').forEach(
            el => { el.style.display = 'none'; el.style.pointerEvents = 'none'; }
        );
        const di = document.querySelector('#detailImg');
        if (di) di.style.pointerEvents = 'none';
        const iw = document.querySelector('#imgTagWrapperId');
        if (iw) iw.style.pointerEvents = 'none';
    }
    """)


def dismiss_popups(page):
    """Dismiss protection plan and other popups. Returns True if something was dismissed."""
    selectors = [
        "span:has-text('No thanks')",
        "button:has-text('No thanks')",
        "button:has-text('No Thanks')",
        "#attachSiNoCov498702",
        "a:has-text('No thanks')",
        "#abb-intl-decline",
        "#attach-close_sideSheet-link",
        "button[data-action='a-popover-close']",
        "button.a-button-close",
    ]
    for sel in selectors:
        try:
            el = page.locator(sel).first
            if el.is_visible(timeout=1500):
                el.click(force=True)
                delay(1, 2)
                return True
        except Exception:
            continue

    result = page.evaluate("""
    () => {
        const els = document.querySelectorAll('button, a, span, input');
        for (const el of els) {
            if (el.textContent.trim().toLowerCase().includes('no thanks')) {
                el.click();
                return 'dismissed';
            }
        }
        const close = document.querySelector('#attach-close_sideSheet-link, .a-popover-close');
        if (close) { close.click(); return 'closed'; }
        return 'none';
    }
    """)
    if result != 'none':
        delay(1, 2)
        return True
    return False


def get_cart_count(page):
    """Read the cart item count from the nav bar."""
    try:
        text = page.locator("#nav-cart-count").text_content(timeout=3000)
        return int(text.strip()) if text else 0
    except Exception:
        return -1
