# Amazon.ca Telegram Shopping Bot

Search Amazon.ca and add items to cart from your phone via Telegram.

## Setup

```bash
git clone https://github.com/JBackend/Amazon-finder.git
cd Amazon-finder

# Create virtual environment and install dependencies
python3 -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
playwright install chromium

# Add your Telegram bot token
cp .env.example .env
```

Edit `.env` and replace `your_token_here` with your bot token from [@BotFather](https://t.me/BotFather).

## Run

```bash
source .venv/bin/activate && python3 bot.py
```

A Chrome window will open on first search (stays open for the session). Sign into Amazon.ca in that window if needed — the session persists in `.browser-profile/`.

## Telegram Commands

| Command | Example |
|---------|---------|
| Search | `snowboarding goggles Oakley` |
| Search with budget | `portable monitor 200` |
| Add all to cart | `add all` |
| Add specific items | `add 1 3 5` |
| View cart | `cart` |
| Show last results | `results` |
| Bot status | `status` |
| Help | `help` |

## Features

- Brand filtering — include a brand name and it auto-selects the brand filter on Amazon
- Sponsored results are excluded
- Results ranked by review count and rating
- Up to 10 results per search
- Protection plan popups auto-declined
- Voice input works via Wispr Flow on iPhone

## Stop

Press `Ctrl+C` in the terminal, or close the terminal window.
