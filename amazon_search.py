"""Amazon.ca search — importable module.

Usage:
    from amazon_search import search_amazon
    results = search_amazon(pw, query="portable monitor", budget=300)
    # results is a list of dicts: [{title, price, rating, reviews, screen_size, url, asin, score}, ...]
"""

import logging
import math
import os
import random
import re
import time

from browser import (
    AMAZON_CA, DEBUG_DIR, delay, is_real_captcha,
)

logger = logging.getLogger("search")


# --- Brand detection ---

def _extract_brand(query):
    """Try to detect a brand name in the query.

    Returns (brand, clean_query) — brand is None if not detected.
    Looks for capitalized words or known patterns that signal a brand.
    """
    words = query.split()
    # Look for words that are capitalized (or all-caps) in original query,
    # or common brand-like patterns (possessives like "Oakleys")
    # We'll pass all words to Amazon and then match against sidebar brands
    return query


def _get_sidebar_brands(page):
    """Extract available brand names from Amazon's left sidebar filters.

    Returns list of {name, element_index} dicts.
    """
    return page.evaluate("""
    () => {
        const brands = [];
        // Amazon brand filter section — multiple possible containers
        const sections = document.querySelectorAll(
            '#brandsRefinements, #p_89-title, [data-csa-c-slot-id="filter-p_89"]'
        );

        // Method 1: Brand refinement checkboxes
        const checkboxes = document.querySelectorAll(
            '#brandsRefinements li a, ' +
            '[id*="p_89"] li a, ' +
            'ul[aria-labelledby*="p_89"] li a'
        );
        checkboxes.forEach((a, idx) => {
            const span = a.querySelector('span.a-size-base');
            if (span) {
                brands.push({ name: span.textContent.trim(), index: idx });
            }
        });

        // Method 2: If no checkboxes found, look for brand links in left nav
        if (brands.length === 0) {
            const links = document.querySelectorAll(
                '#s-refinements .a-list-item a, ' +
                '.s-navigation-indent .a-list-item a'
            );
            links.forEach((a, idx) => {
                const text = a.textContent.trim();
                // Brand section links typically have short text
                if (text.length > 0 && text.length < 40) {
                    brands.push({ name: text, index: idx });
                }
            });
        }

        return brands;
    }
    """)


def _apply_brand_filter(page, query):
    """Match query words against Amazon sidebar brands and click the filter.

    Returns the brand name if a filter was applied, None otherwise.
    """
    sidebar_brands = _get_sidebar_brands(page)
    if not sidebar_brands:
        return None

    query_lower = query.lower()
    # Strip trailing 's' for possessives/plurals (e.g., "Oakleys" → "oakley")
    query_words = [w.rstrip("s").rstrip("'") for w in query_lower.split()]

    best_match = None
    best_score = 0

    for brand_info in sidebar_brands:
        brand_name = brand_info["name"]
        brand_lower = brand_name.lower()

        for word in query_words:
            if len(word) < 2:
                continue
            # Exact match or starts-with match
            if brand_lower == word or brand_lower.startswith(word) or word.startswith(brand_lower):
                score = len(word)  # Longer match = better
                if score > best_score:
                    best_match = brand_info
                    best_score = score

    if not best_match:
        return None

    # Click the brand filter
    try:
        brand_name = best_match["name"]
        # Find and click the matching checkbox/link
        brand_link = page.locator(
            f'#brandsRefinements li a:has(span:text-is("{brand_name}")), '
            f'[id*="p_89"] li a:has(span:text-is("{brand_name}"))'
        ).first

        if brand_link.is_visible(timeout=3000):
            brand_link.click()
            delay(3, 5)
            return brand_name

        # Fallback: try clicking by text content
        brand_link = page.locator(f'a:has(span:text-is("{brand_name}"))').first
        if brand_link.is_visible(timeout=2000):
            brand_link.click()
            delay(3, 5)
            return brand_name
    except Exception:
        pass

    return None


# --- Search and extraction ---

def _navigate_and_search(page, query):
    """Go to Amazon.ca and perform a search."""
    page.goto(AMAZON_CA, wait_until="domcontentloaded", timeout=30000)
    delay(3, 5)

    if is_real_captcha(page):
        time.sleep(30)
        if is_real_captcha(page):
            page.goto(AMAZON_CA, wait_until="domcontentloaded", timeout=30000)
            delay(3, 5)

    search_box = page.locator("#twotabsearchtextbox")
    if not search_box.is_visible(timeout=5000):
        search_box = page.locator("input[name='field-keywords']")

    search_box.click()
    delay(0.3, 0.8)
    search_box.fill("")
    delay(0.2, 0.4)
    search_box.press_sequentially(query, delay=random.uniform(0.04, 0.10) * 1000)
    delay(1.0, 2.5)
    page.keyboard.press("Enter")
    delay(3, 5)

    if is_real_captcha(page):
        time.sleep(30)


def _extract_results(page):
    """Extract product listings from search results via JS."""
    return page.evaluate("""
    () => {
        const products = [];
        const items = document.querySelectorAll('[data-component-type="s-search-result"]');
        items.forEach(item => {
            try {
                // Skip sponsored results — check multiple indicators
                const sponsoredEl = item.querySelector('.puis-sponsored-label-text');
                if (sponsoredEl) {
                    const txt = sponsoredEl.textContent.trim().toLowerCase();
                    if (txt === 'sponsored' || txt === 'commandité') return;
                }
                const adHolder = item.querySelector('[data-component-type="sp-sponsored-result"]');
                if (adHolder) return;
                const label = item.getAttribute('aria-label') || '';
                if (label.toLowerCase().includes('sponsored')) return;
                // Check image alt for "Sponsored Ad" prefix
                const imgCheck = item.querySelector('img.s-image');
                if (imgCheck && /^Sponsored\\s+Ad/i.test(imgCheck.alt || '')) return;

                // Title: try multiple sources — Amazon uses different layouts
                // 1. Product name in .a-size-medium (brand-filtered pages)
                // 2. Full title from h2 > a (standard search pages)
                // 3. Image alt text as fallback
                const productName = item.querySelector('.a-size-medium.a-color-base, .a-size-medium');
                const h2Link = item.querySelector('h2 a');
                const h2El = item.querySelector('h2');
                const imgEl = item.querySelector('img.s-image');
                const brand = h2El ? h2El.textContent.trim() : '';
                let title = '';
                if (productName) {
                    const pn = productName.textContent.trim();
                    // Combine brand + product name if brand isn't already in the product name
                    title = (brand && !pn.toLowerCase().startsWith(brand.toLowerCase()))
                        ? brand + ' ' + pn : pn;
                } else if (h2Link && h2Link.textContent.trim().length > brand.length) {
                    title = h2Link.textContent.trim();
                } else if (imgEl && imgEl.alt) {
                    // Strip "Sponsored Ad – " prefix from img alt
                    title = imgEl.alt.replace(/^Sponsored\s+Ad\s*[–—-]\s*/i, '').trim();
                } else {
                    title = brand;
                }
                const linkEl = item.querySelector('h2 a');
                const href = linkEl ? linkEl.getAttribute('href') : '';
                const asinMatch = item.getAttribute('data-asin') || '';

                let price = '';
                const priceWhole = item.querySelector('.a-price .a-price-whole');
                const priceFraction = item.querySelector('.a-price .a-price-fraction');
                if (priceWhole) {
                    price = priceWhole.textContent.replace(',', '').trim();
                    if (priceFraction) {
                        price = price.replace('.', '') + '.' + priceFraction.textContent.trim();
                    }
                }

                let ratingText = '';
                const ratingSels = [
                    'i.a-icon-star-small .a-icon-alt', 'i.a-icon-star .a-icon-alt',
                    '.a-icon-star-small .a-icon-alt', '.a-icon-star .a-icon-alt',
                    'span[aria-label*="out of 5"]', 'i[class*="a-star"] .a-icon-alt',
                ];
                for (const sel of ratingSels) {
                    const el = item.querySelector(sel);
                    if (el) {
                        const txt = el.textContent || el.getAttribute('aria-label') || '';
                        if (txt && txt.includes('5')) { ratingText = txt.trim(); break; }
                    }
                }
                if (!ratingText) {
                    const starIcon = item.querySelector('i[class*="a-star"]');
                    if (starIcon) {
                        const alt = starIcon.querySelector('.a-icon-alt');
                        if (alt) ratingText = alt.textContent.trim();
                    }
                }

                let reviewText = '';
                // Review count: look for links to reviews containing a number in parens like "(121)"
                const reviewLink = item.querySelector('a[href*="/dp/"] + a, a[href*="customerReviews"], a[href*="#customerReviews"]');
                // Broader: find any link whose text is a number in parens
                const allLinks = item.querySelectorAll('a');
                for (const a of allLinks) {
                    const txt = a.textContent.trim();
                    const m = txt.match(/^\(?([\d,]+)\)?$/);
                    if (m && parseInt(m[1].replace(',','')) > 0) {
                        const href = a.getAttribute('href') || '';
                        // Make sure it's a review link, not a price or offer link
                        if (href.includes('/dp/') || href.includes('customerReview') || href.includes('ref=sr_')) {
                            reviewText = m[1];
                            break;
                        }
                    }
                }
                // Fallback: original selectors
                if (!reviewText) {
                const reviewSels = [
                    '[data-cy="reviews-block"] span.a-size-base',
                    'span.a-size-base.s-underline-text',
                    'a[href*="customerReviews"] span',
                    'a[href*="#customerReviews"] span.a-size-base',
                ];
                for (const sel of reviewSels) {
                    const el = item.querySelector(sel);
                    if (el) {
                        const txt = el.textContent.trim();
                        if (txt && /[\\d,]+/.test(txt) && txt.length < 10) { reviewText = txt; break; }
                    }
                }
                }

                if (title) products.push({ title, price, rating: ratingText, reviews: reviewText, asin: asinMatch, href });
            } catch (e) {}
        });
        return products;
    }
    """)


# --- Parsing helpers ---

def _clean_title(title):
    """Clean up Amazon title quirks."""
    # Remove noise words first
    title = re.sub(r'\b(?:Unisex\s*-?\s*[Aa]dult|unisex-adult)\b\s*-?\s*', '', title, flags=re.IGNORECASE)
    title = re.sub(r'\b(?:mens|womens|unisex)\b\s*', '', title, flags=re.IGNORECASE)
    # Remove duplicate consecutive words: "Oakley Oakley" → "Oakley"
    title = re.sub(r'\b(\w+)\s+\1\b', r'\1', title)
    # Fix repeated word within concatenation: "GoggleGoggle" → "Goggle"
    title = re.sub(r'([A-Z][a-z]{2,})\1', r'\1', title)
    # Fix repeated phrase: "Snow GoggleSnow Goggles" → "Snow Goggles"
    title = re.sub(r'([A-Z][a-z]+(?:\s+[A-Z][a-z]+)*)\1s?', r'\1', title)
    # Fix lowercase→uppercase: "MtbMTB" → "Mtb MTB"
    title = re.sub(r'([a-z])([A-Z])', r'\1 \2', title)
    # Fix single uppercase letter jammed before capitalized word (only after space/start)
    title = re.sub(r'(?<=\s)([A-Z])([A-Z][a-z]{2,})', r'\1 \2', title)
    # Fix single letter before hyphenated word: "Mski-goggles" → "M ski-goggles"
    # Only match when preceded by space (avoid breaking "Large-Sized")
    title = re.sub(r'(?<=\s)([SMLX])([a-z]{1,3}-)', r'\1 \2', title)
    title = re.sub(r'\s+', ' ', title).strip()
    return title


def _parse_price(s):
    if not s:
        return None
    cleaned = re.sub(r'[^\d.]', '', s)
    try:
        return float(cleaned)
    except ValueError:
        return None


def _parse_rating(s):
    if not s:
        return None
    m = re.search(r'([\d.]+)\s*(?:out of|/)\s*5', s)
    if m:
        return float(m.group(1))
    m = re.search(r'([\d.]+)', s)
    if m:
        val = float(m.group(1))
        return val if val <= 5.0 else None
    return None


def _parse_reviews(s):
    if not s:
        return 0
    cleaned = s.replace(',', '').strip()
    m = re.search(r'([\d.]+)\s*[Kk]', cleaned)
    if m:
        return int(float(m.group(1)) * 1000)
    m = re.search(r'(\d+)', cleaned)
    return int(m.group(1)) if m else 0


def _parse_screen_size(title):
    for pat in [r'(\d+\.?\d*)\s*[-"]?\s*[Ii]nch', r'(\d+\.?\d*)\s*"', r'(\d+\.?\d*)["″]', r'(\d+\.?\d*)\s*[Ii]n\b']:
        m = re.search(pat, title)
        if m:
            size = float(m.group(1))
            if 10 <= size <= 30:
                return size
    return None


EXCLUDE_KEYWORDS = [
    "stand", "holder", "mount", "bracket", "case", "sleeve", "bag",
    "cable", "adapter", "hub", "dock", "charger", "stylus", "pen",
    "keyboard", "mouse", "arm", "riser", "protector", "film", "cleaning", "cover", "skin",
]


def _is_actual_monitor(title):
    lower = title.lower()
    monitor_terms = ["monitor", "display", "screen"]
    has_monitor = any(t in lower for t in monitor_terms)
    for kw in EXCLUDE_KEYWORDS:
        if lower.startswith(kw) or f" {kw} for " in lower or f" {kw}," in lower:
            return False
        if kw in lower and not has_monitor:
            return False
    return has_monitor


# --- Filter, rank, deduplicate ---

def _filter_and_parse(raw, budget, monitor_only=False):
    parsed = []
    for r in raw:
        if monitor_only and not _is_actual_monitor(r.get("title", "")):
            continue
        price = _parse_price(r.get("price", ""))
        if price is not None and price > budget:
            continue
        asin = r.get("asin", "")
        href = r.get("href", "")
        url = f"https://www.amazon.ca/dp/{asin}" if asin else (f"https://www.amazon.ca{href}" if href.startswith("/") else href)
        parsed.append({
            "title": _clean_title(r.get("title", "")),
            "price": price,
            "rating": _parse_rating(r.get("rating", "")),
            "reviews": _parse_reviews(r.get("reviews", "")),
            "screen_size": _parse_screen_size(r.get("title", "")),
            "url": url,
            "asin": asin,
        })
    return parsed


def _rank(products):
    # Find max reviews in this result set for relative scaling
    max_reviews = max((p["reviews"] for p in products if p["reviews"]), default=1)

    for p in products:
        score = 0.0
        reviews = p["reviews"] or 0
        rating = p["rating"]

        # Reviews: 45 points — heavily rewarded, scaled relative to best in results
        if reviews > 0:
            score += (reviews / max_reviews) * 45

        # Rating: 35 points — but penalize low review counts (rating is unreliable with few reviews)
        if rating:
            confidence = min(reviews / 50.0, 1.0)  # Full confidence at 50+ reviews
            score += (rating / 5.0) * 35 * confidence

        # Price: 10 points — slight bonus for lower prices
        if p["price"] and p["price"] > 0:
            score += max(0, 1 - (p["price"] / 1000.0)) * 10

        # Screen size (monitor searches): 10 points
        if p["screen_size"]:
            score += 10

        p["score"] = round(score, 1)
    products.sort(key=lambda x: x["score"], reverse=True)
    return products


def _deduplicate(products):
    seen_asins, seen_titles, unique = set(), set(), []
    for p in products:
        # Skip duplicate ASINs
        if p["asin"] and p["asin"] in seen_asins:
            continue
        # Skip duplicate titles — use full title for comparison, not truncated
        tk = re.sub(r'\s+', ' ', p["title"].lower().strip())
        if tk in seen_titles:
            continue
        if p["asin"]:
            seen_asins.add(p["asin"])
        seen_titles.add(tk)
        unique.append(p)
    return unique


# --- Public API ---

def search_amazon(context, query, budget=300.0):
    """Search Amazon.ca and return ranked results.

    Args:
        context: Playwright browser context (from browser.setup_browser)
        query: Search terms (e.g. "portable monitor")
        budget: Max price in CAD

    Returns:
        List of product dicts, ranked by score. Each has:
        title, price, rating, reviews, screen_size, url, asin, score
    """
    page = context.pages[0] if context.pages else context.new_page()

    _navigate_and_search(page, query)

    # Try to apply brand filter from sidebar if query contains a brand name
    applied_brand = _apply_brand_filter(page, query)
    if applied_brand:
        logger.info(f"Applied brand filter: {applied_brand}")

    raw = _extract_results(page)
    logger.info(f"Initial extraction: {len(raw)} results")

    # Scroll for more
    if len(raw) < 15:
        page.mouse.wheel(0, 2000)
        delay(3, 5)
        raw = _extract_results(page)
        logger.info(f"After scroll: {len(raw)} results")

    # Page 2 if needed
    if len(raw) < 10:
        try:
            next_btn = page.locator("a.s-pagination-next, a:has-text('Next')")
            if next_btn.is_visible(timeout=3000):
                next_btn.click()
                delay(3, 5)
                page2 = _extract_results(page)
                logger.info(f"Page 2: {len(page2)} results")
                raw.extend(page2)
        except Exception:
            pass

    logger.info(f"Total raw results: {len(raw)}")

    # Debug: log first 5 titles and ASINs to understand duplicates
    for i, r in enumerate(raw[:10]):
        logger.info(f"  raw[{i}]: asin={r.get('asin','')!r} title={r.get('title','')[:80]!r}")

    # Only apply monitor-specific filtering if searching for monitors
    monitor_terms = ["monitor", "display", "screen"]
    is_monitor_search = any(t in query.lower() for t in monitor_terms)
    filtered = _filter_and_parse(raw, budget, monitor_only=is_monitor_search)
    logger.info(f"After filter/parse: {len(filtered)} results")
    deduped = _deduplicate(filtered)
    logger.info(f"After dedup: {len(deduped)} results")
    ranked = _rank(deduped)
    return ranked[:10]
