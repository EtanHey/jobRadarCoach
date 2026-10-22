"""Conservative structural JD defects. No match means unknown, never quality approval."""
import re


ROLE_HEAD = r"(?:engineer|developer|manager|designer)"
ROLE_INTRO = re.compile(
    r"(?:\A|\n\s*\n)As\s+(?:an?\s+|[\w-]+['’]s\s+(?:first\s+)?)"
    r"(?:[\w+-]+\s+){0,8}(?P<head>" + ROLE_HEAD + r")"
    r"(?:\s+at\s+[^,\n]{1,80})?,\s+you(?:['’]ll|\s+will)\b", re.I,
)
ROLE_SELECTOR = re.compile(r"^\s*What role are you interested in\?\s*[:*]?\s*$", re.I | re.M)
EXTERNAL_JD = re.compile(
    r"^(?:Read (?:the |full )?job description(?: here)?|Full job description)"
    r"\s*:\s*https?://\S+\s*$", re.I | re.M,
)
HIRING_SUMMARY = re.compile(
    r"[\w &.'’()-]+ is (?:looking for|seeking|hiring) an? (?:[\w-]+\s+){0,6}"
    + ROLE_HEAD + r" to join our team"
    r"(?:[,\s]+(?:full[ -]time|part[ -]time|on[ -]site|remote|hybrid|in\s+[\w'-]+(?:\s+[\w'-]+){0,3}))*[.!]"
    r"(?:\s+[^.!?\n]{1,100}\bare welcome to apply(?: and help build [^.!?\n]{1,80})?[.!])?"
    r"(?:\s+Interested\?\s+Apply[^.!?\n]{0,100}[.!])?", re.I,
)
LISTING_HEADING = re.compile(r"[#*\s]*(?:Open positions|Job openings|Careers)[*:\s]*", re.I)
ROLE_LINK = re.compile(
    r"(?:[-*]\s*)?\[(?:[\w+-]+\s+){0,8}" + ROLE_HEAD + r"\]\(https?://[^\s)]+\)", re.I,
)


def jd_quality_rule(raw_jd: str | None) -> str | None:
    """Return a specific rejection only when the stored body proves its structure."""
    if raw_jd is None or not raw_jd.strip():
        return "jd-quality-missing-body"
    text = raw_jd.strip()
    if re.search(
        r"\b(?:seeking|hiring|looking for)\b[^\n.!?]{0,80}\[job title\]\s+to join\b", text, re.I,
    ) and re.search(r"\[number\]\s+years\b", text, re.I):
        return "jd-quality-unfilled-template"
    # A role picker plus independent, different role-head introductions is not
    # merely a JD mentioning colleagues. Same-head or unsupported titles abstain.
    if ROLE_SELECTOR.search(text) and len({m["head"].lower() for m in ROLE_INTRO.finditer(text)}) >= 2:
        return "jd-quality-mixed-role"
    lines = [line.strip() for line in text.splitlines() if line.strip()]
    if (
        any(LISTING_HEADING.fullmatch(line) for line in lines)
        and sum(bool(ROLE_LINK.fullmatch(line)) for line in lines) >= 2
        and all(LISTING_HEADING.fullmatch(line) or ROLE_LINK.fullmatch(line) for line in lines)
    ):
        return "jd-quality-listing-only"
    pointer = EXTERNAL_JD.search(text)
    if pointer:
        before, after = text[:pointer.start()].strip(), text[pointer.end():].strip()
        # Account for the entire teaser using hiring/invitation frames. Extra
        # duties or requirements, even a short prose sentence, force abstention.
        if (
            HIRING_SUMMARY.fullmatch(before)
            and after in ("", "Application instructions are at the end of the document.")
        ):
            return "jd-quality-external-summary"
    return None
