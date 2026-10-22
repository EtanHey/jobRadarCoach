"""Explicit application deadlines; incomplete/ambiguous dates never close a job."""
from datetime import date, datetime, timedelta, timezone
import re


SOURCE = "jd-explicit-v1"
# Closed application frames, never a generic date/deadline search. Whole lines
# prevent negation, project milestones, and conditional tails becoming facts.
FRAME = re.compile(
    r"^(?:Applications? close(?: on)?\s+|Application deadline\s*:\s*|"
    r"Application deadline (?:has been )?(?P<extended>extended to)\s*:?\s*|"
    r"מועד אחרון להגשת מועמדות\s*:\s*|(?:ניתן )?להגיש מועמדות עד\s+|"
    r"המועד להגשת מועמדות (?P<he_extended>הוארך עד)\s+)(?P<date>.+)$", re.I,
)
MONTHS = {name.casefold(): i for i, names in enumerate((
    "January ינואר", "February פברואר", "March מרץ", "April אפריל", "May מאי", "June יוני",
    "July יולי", "August אוגוסט", "September ספטמבר", "October אוקטובר",
    "November נובמבר", "December דצמבר",
), 1) for name in names.split()}


def _parse(value):
    value = value.rstrip(".").strip()
    try:
        if re.fullmatch(r"\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}(?:Z|[+-]\d{2}:\d{2})", value):
            instant = datetime.fromisoformat(value.replace("Z", "+00:00"))
            return instant.astimezone(timezone.utc).isoformat().replace("+00:00", "Z")
        if re.fullmatch(r"\d{4}-\d{2}-\d{2}", value):
            day = date.fromisoformat(value)
        elif numeric := re.fullmatch(r"(\d{1,2})([./-])(\d{1,2})\2(\d{4})", value):
            d, _, m, y = numeric.groups()
            if int(d) <= 12 and int(m) <= 12 and d != m:
                return None
            if int(m) > 12 and int(d) <= 12:
                d, m = m, d
            day = date(int(y), int(m), int(d))
        else:
            english = re.fullmatch(r"([A-Za-z]+) (\d{1,2})(?:st|nd|rd|th)?[,]? (\d{4})", value, re.I)
            local = re.fullmatch(r"(\d{1,2}) ב?([א-ת]+|[A-Za-z]+) (\d{4})", value)
            if english:
                month, d, y = english.groups()
            elif local:
                d, month, y = local.groups()
            else:
                return None
            day = date(int(y), MONTHS[month.casefold()], int(d))
        # No employer timezone is inferred. A date-only deadline is definitely
        # past only after the day ends worldwide (UTC-12), with an inclusive bound.
        return (day + timedelta(days=1)).isoformat() + "T12:00:00Z"
    except (ValueError, KeyError, OverflowError):
        return None


def extract_deadline(raw_jd):
    result = {"application_deadline": None, "application_deadline_evidence_quote": None,
              "application_deadline_remark": None, "application_deadline_source": SOURCE}
    candidates = []
    for line in raw_jd.splitlines():
        quote = line.strip()
        match = FRAME.fullmatch(quote.strip("*").strip())
        if match:
            candidates.append((_parse(match["date"]), quote,
                               bool(match["extended"] or match["he_extended"])))
    if not candidates:
        return result
    extensions = [item for item in candidates if item[2]]
    selected = extensions or candidates
    values = {item[0] for item in selected}
    result["application_deadline_evidence_quote"] = selected[0][1]
    if len(values) == 1 and None not in values:
        result["application_deadline"] = selected[0][0]
    else:
        result["application_deadline_remark"] = "Incomplete, ambiguous, conditional or conflicting application deadline"
    return result
