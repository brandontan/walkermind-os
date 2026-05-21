"""MVP v1 keyboards (InlineKeyboardMarkup only, blueprint section 7).

Each module exposes pure builder functions named `kb_<screen>` returning a
telegram.InlineKeyboardMarkup. Callback prefixes follow blueprint 20.1:

    dashboard:   home | refresh
    auto:        home | quick_start | configure[:strategy|capital|risk|review]
                 | start | pause | resume
    copy:        home | add_wallet | wallet[:verify|configure|start]
                 | wallets | pause | resume
    portfolio:   home | positions | history | performance | balance
    markets:     home | trending | new | insights | watchlist | search | detail
    settings:    home | mode | risk | notifications | account | advanced
    help:        home | quick_start | auto | copy_wallet | safety | faq | support

Plus shared navigation prefix `nav:` (back / home / refresh / noop / cancel).
"""
from . import _common, onboarding, autotrade, copy_wallet, portfolio, markets, settings, help as help_kb

__all__ = [
    "_common",
    "onboarding",
    "autotrade",
    "copy_wallet",
    "portfolio",
    "markets",
    "settings",
    "help_kb",
]
