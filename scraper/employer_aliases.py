"""Structural same-company names plus reviewed spellings/divisions."""
import re


SUFFIX = re.compile(r'(?:^| )(?:private limited|pvt ltd|inc|ltd|llc|corp|corporation|company|co|group|holdings|lab|labs|gmbh|ag|sa|bv|ai|technologies|systems)$')


def _core(name: str) -> str:
    name = re.sub(r'\([A-Z][A-Z0-9&.]{1,}\)', ' ', name)
    core = ' '.join(re.findall(r'[^\W_]+', name.casefold()))
    while (shorter := SUFFIX.sub('', core)) != core:
        core = shorter
    return core


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
    left, right = _core(publisher), _core(employer)
    # Suffix stripping only establishes an alias when nonempty cores agree.
    if left and right and (left == right or left.startswith(right + ' ') or right.startswith(left + ' ')):
        return True
    return any(publisher.casefold() == name.casefold()
               and employer.casefold() in {alias.casefold() for alias in aliases}
               for name, aliases in ALIASES.items())
