# Telegram Amazon Shopping Bot — Implementation Plan

> **For Claude:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task.

**Goal:** A Telegram bot running locally on macOS that searches Amazon.ca and adds items to cart via text commands.

**Architecture:** Single Python process using python-telegram-bot for messaging, existing Playwright scripts for Amazon automation. Command parser extracts intent/query/budget from text. Browser launches on demand, reuses persistent profile for Amazon sign-in.

**Tech Stack:** python-telegram-bot, Playwright, regex parser, .env for config

---

### Task 1: Refactor find_monitors.py into importable search module

Extract core logic into `amazon_search.py` that can be called programmatically.

### Task 2: Refactor add_to_cart.py into importable cart module

Extract core logic into `amazon_cart.py` that accepts ASINs and returns results.

### Task 3: Build command parser (parser.py)

Regex-based extraction of intent, query, budget, item numbers.

### Task 4: Build Telegram bot (bot.py)

Wire Telegram handlers → parser → Amazon modules → formatted responses.

### Task 5: Test end-to-end

Start bot, send commands from phone, verify full flow.
