"""Amazon.ca add-to-cart — importable module.

Usage:
    from amazon_cart import add_to_cart
    results = add_to_cart(context, [
        {"asin": "B0B9GLG86C", "name": "InnoView Monitor"},
        {"asin": "B08MXKVCKF", "name": "ZSCMALLS Monitor"},
    ])
    # results: [{"asin": ..., "name": ..., "success": True/False}, ...]
"""

import os

from browser import (
    AMAZON_CA, DEBUG_DIR, delay,
    remove_zoom_overlay, dismiss_popups, get_cart_count,
)


def _add_one(page, asin, name):
    """Add a single product to cart. Returns True on success."""
    url = f"{AMAZON_CA}/dp/{asin}"
    page.goto(url, wait_until="domcontentloaded", timeout=30000)
    delay(3, 5)

    remove_zoom_overlay(page)

    # Try multiple button selectors — Amazon uses different layouts
    button_selectors = [
        "#add-to-cart-button",
        "input[name='submit.add-to-cart']",
        "#buy-now-button",
        "#one-click-button",
        "input#add-to-cart-button-ubb",
        "span#submit\\.add-to-cart > input",
        "input[value='Add to Cart']",
        "input[value='Add to cart']",
    ]

    btn = None
    for sel in button_selectors:
        try:
            # Scroll to it first
            page.evaluate(f"document.querySelector('{sel}')?.scrollIntoView({{block: 'center'}})")
            delay(0.5, 1.0)
            candidate = page.locator(sel).first
            if candidate.is_visible(timeout=2000):
                btn = candidate
                break
        except Exception:
            continue

    if not btn:
        page.screenshot(path=os.path.join(DEBUG_DIR, f"no_btn_{asin}.png"))
        return False

    btn.click(force=True)
    delay(4, 6)

    dismiss_popups(page)
    delay(1, 2)

    # Verify
    cart_count = get_cart_count(page)
    if cart_count > 0:
        return True

    page_text = (page.text_content("body") or "").lower()
    if "added to cart" in page_text or "added to your" in page_text:
        return True

    page.screenshot(path=os.path.join(DEBUG_DIR, f"uncertain_{asin}.png"))
    return False


def add_to_cart(context, products):
    """Add multiple products to cart.

    Args:
        context: Playwright browser context
        products: List of dicts with 'asin' and 'name' keys

    Returns:
        List of dicts with 'asin', 'name', 'success' keys
    """
    page = context.pages[0] if context.pages else context.new_page()
    results = []

    for product in products:
        asin = product["asin"]
        name = product.get("name", asin)
        try:
            success = _add_one(page, asin, name)
        except Exception:
            page.screenshot(path=os.path.join(DEBUG_DIR, f"error_{asin}.png"))
            success = False
        results.append({"asin": asin, "name": name, "success": success})
        if len(results) < len(products):
            delay(2, 4)

    return results


def get_cart_screenshot(context):
    """Navigate to cart and take a screenshot. Returns the file path."""
    page = context.pages[0] if context.pages else context.new_page()
    page.goto(f"{AMAZON_CA}/gp/cart/view.html", wait_until="domcontentloaded", timeout=30000)
    delay(3, 5)
    path = os.path.join(DEBUG_DIR, "cart_screenshot.png")
    page.screenshot(path=path)
    return path
