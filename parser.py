"""Command parser for Telegram messages.

Extracts intent, query, budget, and item numbers from text.

Examples:
    "search portable monitor 300"       → search, query="portable monitor", budget=300
    "find 4K monitor under 250"         → search, query="4K monitor", budget=250
    "add all"                           → add, items="all"
    "add 1 3 5"                         → add, items=[1, 3, 5]
    "cart"                              → cart
    "results"                           → results
    "status"                            → status
"""

import re


def parse_message(text):
    """Parse a text message into a command dict.

    Returns:
        dict with keys:
            intent: "search" | "add" | "cart" | "results" | "status" | "help" | "unknown"
            query: str (for search)
            budget: float (for search, default 300)
            items: "all" | list of ints (for add)
            raw: str (original message)
    """
    raw = text.strip()
    lower = raw.lower()

    # Strip leading / for slash commands
    if lower.startswith("/"):
        lower = lower[1:]
        raw = raw[1:]

    result = {"intent": "unknown", "query": "", "budget": 9999.0, "budget_specified": False, "items": [], "raw": text.strip()}

    # --- Help ---
    if lower in ("help", "start", "h"):
        result["intent"] = "help"
        return result

    # --- Status ---
    if lower in ("status", "ping"):
        result["intent"] = "status"
        return result

    # --- Cart ---
    if lower in ("cart", "showcart", "show cart", "view cart", "my cart"):
        result["intent"] = "cart"
        return result

    # --- Results ---
    if lower in ("results", "show results", "last", "last results"):
        result["intent"] = "results"
        return result

    # --- Add to cart ---
    if lower.startswith("add"):
        result["intent"] = "add"
        rest = lower[3:].strip()

        if not rest or rest == "all" or "all" in rest:
            result["items"] = "all"
        else:
            # Extract numbers: "add 1 3 5" or "add 1, 3, 5" or "add first three"
            nums = re.findall(r'\d+', rest)
            if nums:
                result["items"] = [int(n) for n in nums]
            else:
                # Word numbers
                word_map = {"one": 1, "two": 2, "three": 3, "four": 4, "five": 5,
                            "first": 1, "second": 2, "third": 3, "fourth": 4, "fifth": 5}
                for word, num in word_map.items():
                    if word in rest:
                        result["items"].append(num)
                if not result["items"]:
                    result["items"] = "all"
        return result

    # --- Search ---
    search_triggers = ["search", "find", "look for", "looking for", "get me", "find me",
                       "show me", "i want", "i need", "buy", "shop for"]
    is_search = False
    search_rest = lower

    for trigger in search_triggers:
        if lower.startswith(trigger):
            is_search = True
            search_rest = lower[len(trigger):].strip()
            break

    # If no trigger matched, treat any unrecognized message as a search
    if not is_search:
        is_search = True
        search_rest = lower

    if is_search:
        result["intent"] = "search"

        # Extract budget: "$300", "300 dollars", "under 300", "budget 300", "max 300"
        budget_patterns = [
            r'\$\s*(\d+(?:\.\d+)?)',
            r'(\d+(?:\.\d+)?)\s*(?:dollars?|bucks?|cad|\$)',
            r'(?:under|below|max|budget|less than|up to)\s*\$?\s*(\d+(?:\.\d+)?)',
            r'(\d+(?:\.\d+)?)\s*(?:max|budget|limit)',
        ]
        for pat in budget_patterns:
            m = re.search(pat, search_rest)
            if m:
                result["budget"] = float(m.group(1))
                result["budget_specified"] = True
                search_rest = re.sub(pat, '', search_rest).strip()
                break
        else:
            # Check if the last word is a number > 10 (assumed budget, not a product spec)
            words = search_rest.split()
            if words and re.match(r'^\d+$', words[-1]) and int(words[-1]) > 10:
                result["budget"] = float(words[-1])
                result["budget_specified"] = True
                search_rest = ' '.join(words[:-1])

        # Clean up query
        search_rest = re.sub(r'\b(a|an|the|me|for|on|amazon|please|good|best|nice|great)\b', '', search_rest)
        search_rest = re.sub(r'\s+', ' ', search_rest).strip()

        result["query"] = search_rest if search_rest else "portable monitor"
        return result

    return result
