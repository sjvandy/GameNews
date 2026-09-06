"""Entry point shim - kept so `python bot.py` still works.

The bot now lives in the gamenews/ package; see gamenews/bot.py.
"""

from gamenews.bot import main

if __name__ == "__main__":
    main()
