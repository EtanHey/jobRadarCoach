"""Same-company spellings/divisions reviewed in the frozen 58-row audit."""
ALIASES = {
    'Alice (Formerly ActiveFence)': ['Alice'],
    'BMC Software': ['BMC'],
    'EyeContact Dx': ['EyeContact'],
    'IAI - Israel Aerospace Industries': ['Israel Aerospace Industries Aviation Division'],
    'Ness Technologies | נס טכנולוגיות': ['NESS FORCE', 'Ness'],
    'Nova Ltd.': ['Nova'],
    'Parsons Corporation': ['Parsons'],
    'Ripple Analytics': ['Ripple'],
    'SWAKIO™': ['SWAKIO'],
}


def is_alias(publisher: str, employer: str) -> bool:
    return any(publisher.casefold() == name.casefold()
               and employer.casefold() in {alias.casefold() for alias in aliases}
               for name, aliases in ALIASES.items())
