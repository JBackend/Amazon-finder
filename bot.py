"""Telegram bot for Amazon.ca shopping.

Send text commands to search Amazon and add items to cart.

Usage:
    python bot.py

Commands:
    search portable monitor 300  — Search Amazon.ca, budget $300 CAD
    find USB-C monitor under 200 — Same, natural phrasing
    add all                      — Add all results to cart
    add 1 3                      — Add specific picks to cart
    cart                         — Screenshot your cart
    results                      — Show last search results
    status                       — Check bot/browser status
    help                         — Show commands
"""

import asyncio
import logging
import os
import sys
import threading

from dotenv import load_dotenv
load_dotenv(os.path.join(os.path.dirname(os.path.abspath(__file__)), ".env"))

from telegram import Update
from telegram.ext import Application, CommandHandler, MessageHandler, filters, ContextTypes

from parser import parse_message

logging.basicConfig(format="%(asctime)s [%(name)s] %(message)s", level=logging.INFO)
logger = logging.getLogger("bot")

TOKEN = os.environ.get("TELEGRAM_BOT_TOKEN")
if not TOKEN:
    print("ERROR: Set TELEGRAM_BOT_TOKEN in .env")
    sys.exit(1)

# --- State ---
last_results = []       # Last search results
browser_context = None  # Playwright browser context
pw_instance = None      # Playwright instance
browser_lock = threading.Lock()


# --- Browser management (runs in thread since Playwright is sync) ---

def _get_browser():
    """Get or create browser context. Must be called from a worker thread."""
    global browser_context, pw_instance
    if browser_context:
        return browser_context

    from playwright.sync_api import sync_playwright
    from browser import setup_browser

    pw_instance = sync_playwright().start()
    browser_context = setup_browser(pw_instance)
    return browser_context


def _close_browser():
    global browser_context, pw_instance
    if browser_context:
        try:
            browser_context.close()
        except Exception:
            pass
        browser_context = None
    if pw_instance:
        try:
            pw_instance.stop()
        except Exception:
            pass
        pw_instance = None


def _run_search(query, budget):
    """Run Amazon search in thread. Returns list of products."""
    from amazon_search import search_amazon
    with browser_lock:
        ctx = _get_browser()
        return search_amazon(ctx, query, budget)


def _run_add_to_cart(products):
    """Add products to cart in thread. Returns list of results."""
    from amazon_cart import add_to_cart
    with browser_lock:
        ctx = _get_browser()
        return add_to_cart(ctx, products)


def _run_cart_screenshot():
    """Take cart screenshot in thread. Returns file path."""
    from amazon_cart import get_cart_screenshot
    with browser_lock:
        ctx = _get_browser()
        return get_cart_screenshot(ctx)


# --- Telegram message formatting ---

def _esc(text):
    """Escape Telegram MarkdownV1 special characters in text."""
    for ch in ['*', '_', '`', '[']:
        text = text.replace(ch, '')
    return text


def format_results(products):
    """Format search results for Telegram."""
    if not products:
        return "No results found. Try a different search query or higher budget."

    lines = ["*Amazon.ca Search Results*\n"]
    for i, p in enumerate(products[:10], 1):
        price = f"${p['price']:.2f}" if p['price'] else "N/A"
        rating = f"{p['rating']:.1f}/5" if p['rating'] else "N/A"
        reviews = f"{p['reviews']:,}" if p['reviews'] else "0"
        title = _esc(p['title'][:60])

        lines.append(f"*#{i}* {title}")
        lines.append(f"  {price} CAD | {rating} ({reviews} reviews)")
        if p.get('url'):
            lines.append(f"  {p['url']}")
        lines.append("")

    lines.append("Reply `add all` or `add 1 3` to add to cart")
    return "\n".join(lines)


def format_cart_results(results):
    """Format add-to-cart results for Telegram."""
    lines = ["*Add to Cart Results*\n"]
    for r in results:
        status = "✅" if r["success"] else "❌"
        lines.append(f"{status} {_esc(r['name'])}")

    succeeded = sum(1 for r in results if r["success"])
    lines.append(f"\n*{succeeded}/{len(results)}* items added to cart")
    return "\n".join(lines)


HELP_TEXT = """*Amazon Shopping Bot* 🛒

*Commands:*
`search portable monitor 300` — Search Amazon.ca
`find USB-C monitor under 200` — Natural phrasing works too
`add all` — Add all search results to cart
`add 1 3 5` — Add specific picks
`cart` — Screenshot your current cart
`results` — Show last search results
`status` — Bot/browser status
`help` — This message

*Tips:*
• Last number in search = budget (CAD)
• Budget defaults to $300 if not specified
• Use Wispr Flow to dictate messages
"""


# --- Handlers ---

async def handle_message(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Handle all text messages."""
    global last_results

    text = update.message.text
    if not text:
        return

    parsed = parse_message(text)
    intent = parsed["intent"]
    logger.info(f"Message: '{text}' → intent={intent}, query='{parsed['query']}', budget={parsed['budget']}")

    if intent == "help":
        await update.message.reply_text(HELP_TEXT, parse_mode="Markdown")
        return

    if intent == "status":
        browser_status = "🟢 Running" if browser_context else "⚪ Not started (will launch on first search)"
        await update.message.reply_text(
            f"*Bot Status*\n\nBrowser: {browser_status}\nLast results: {len(last_results)} items",
            parse_mode="Markdown",
        )
        return

    if intent == "results":
        if last_results:
            await update.message.reply_text(format_results(last_results), parse_mode="Markdown")
        else:
            await update.message.reply_text("No recent results. Run a search first.")
        return

    if intent == "search":
        query = parsed["query"]
        budget = parsed["budget"]
        budget_msg = f" (budget: ${budget:.0f} CAD)" if parsed.get("budget_specified") else ""
        await update.message.reply_text(f"🔍 Searching Amazon.ca for *{query}*{budget_msg}...", parse_mode="Markdown")

        loop = asyncio.get_event_loop()
        try:
            results = await loop.run_in_executor(None, _run_search, query, budget)
            last_results = results
            await update.message.reply_text(format_results(results), parse_mode="Markdown")
        except Exception as e:
            logger.error(f"Search failed: {e}")
            await update.message.reply_text(f"❌ Search failed: {e}")
        return

    if intent == "add":
        if not last_results:
            await update.message.reply_text("No results to add. Run a search first.")
            return

        items = parsed["items"]
        if items == "all":
            to_add = last_results[:5]
        else:
            to_add = []
            for idx in items:
                if 1 <= idx <= len(last_results):
                    to_add.append(last_results[idx - 1])

        if not to_add:
            await update.message.reply_text("No valid items to add. Use `add all` or `add 1 3 5`.", parse_mode="Markdown")
            return

        names = ", ".join(f"#{i}" for i in (items if items != "all" else range(1, len(to_add) + 1)))
        await update.message.reply_text(f"🛒 Adding {len(to_add)} item(s) to cart...")

        products_to_add = [{"asin": p["asin"], "name": p["title"][:50]} for p in to_add]

        loop = asyncio.get_event_loop()
        try:
            results = await loop.run_in_executor(None, _run_add_to_cart, products_to_add)
            await update.message.reply_text(format_cart_results(results), parse_mode="Markdown")
        except Exception as e:
            logger.error(f"Add to cart failed: {e}")
            await update.message.reply_text(f"❌ Add to cart failed: {e}")
        return

    if intent == "cart":
        await update.message.reply_text("📸 Taking cart screenshot...")
        loop = asyncio.get_event_loop()
        try:
            path = await loop.run_in_executor(None, _run_cart_screenshot)
            await update.message.reply_photo(photo=open(path, "rb"), caption="Your Amazon.ca cart")
        except Exception as e:
            logger.error(f"Cart screenshot failed: {e}")
            await update.message.reply_text(f"❌ Failed: {e}")
        return

    # Unknown
    await update.message.reply_text(
        f"🤔 I didn't understand that. Try `help` for commands.",
        parse_mode="Markdown",
    )


async def cmd_start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text(HELP_TEXT, parse_mode="Markdown")


async def cmd_help(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text(HELP_TEXT, parse_mode="Markdown")


# --- Main ---

def main():
    print()
    print("=" * 45)
    print("  Amazon.ca Telegram Shopping Bot")
    print("=" * 45)
    print("  Bot is starting...")
    print("  Send a message on Telegram to begin.")
    print("  Press Ctrl+C to stop.\n")

    app = Application.builder().token(TOKEN).build()

    app.add_handler(CommandHandler("start", cmd_start))
    app.add_handler(CommandHandler("help", cmd_help))
    app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, handle_message))
    # Also handle slash commands as text (e.g., /search ...)
    app.add_handler(MessageHandler(filters.COMMAND, handle_message))

    try:
        app.run_polling(allowed_updates=Update.ALL_TYPES)
    except KeyboardInterrupt:
        pass
    finally:
        _close_browser()
        print("\n  Bot stopped. Browser closed.")


if __name__ == "__main__":
    main()
