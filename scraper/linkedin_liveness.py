"""Conservative, target-bound LinkedIn closure evidence from complete HTML."""

import re
from html.parser import HTMLParser


BODY_LIMIT = 512_000
CLOSED = re.compile(
    r"\b(?:no longer accepting applications|not currently accepting applications)\b", re.I
)
VOID_TAGS = set("area base br col embed hr img input link meta param source track wbr".split())
NON_RENDERED = {"script", "style", "template", "noscript", "head", "iframe"}
UNRELATED = {"aside", "nav", "footer"}
LOGIN_HEADING = re.compile(r"^(?:LinkedIn\s*[:|\-]\s*)?(?:sign in|log in|join LinkedIn)\b", re.I)


def _hidden(tag, attrs):
    if tag in NON_RENDERED or "hidden" in attrs or "inert" in attrs:
        return True
    if attrs.get("aria-hidden", "").strip().lower() == "true":
        return True
    for declaration in attrs.get("style", "").lower().split(";"):
        name, _, value = declaration.partition(":")
        value = value.split("!")[0].strip()
        if (name.strip(), value) in {
            ("display", "none"), ("visibility", "hidden"),
            ("visibility", "collapse"), ("content-visibility", "hidden"),
        }:
            return True
    return False


class _StatusParser(HTMLParser):
    def __init__(self, job_id):
        super().__init__(convert_charrefs=True)
        self.job_id = job_id
        self.stack = []
        self.phrases = []
        self.uncertain = False

    def handle_starttag(self, tag, attrs):
        attrs = {name: value or "" for name, value in attrs}
        parent = self.stack[-1] if self.stack else {}
        hidden = parent.get("hidden", False) or _hidden(tag, attrs)
        unrelated = parent.get("unrelated", False) or tag in UNRELATED
        identity = parent.get("identity")
        urn = attrs.get("data-entity-urn", "")
        if "jobPosting" in urn:
            match = re.fullmatch(r"urn:li:jobPosting:(\d+)", urn)
            identity = match.group(1) if match else "invalid"
        if "data-job-id" in attrs:
            numeric = attrs["data-job-id"]
            if identity and identity != numeric:
                self.uncertain = True
            identity = numeric if numeric.isdigit() else "invalid"
        if not hidden:
            if identity and identity != self.job_id:
                self.uncertain = True
            if tag == "form" and (
                re.search(r"/(?:uas/login|login|authwall|checkpoint)(?:/|$)", attrs.get("action", ""), re.I)
                or re.search(r"captcha|consent", attrs.get("id", ""), re.I)
            ):
                self.uncertain = True
            if tag == "input" and attrs.get("type", "").lower() == "password":
                self.uncertain = True
        if tag in VOID_TAGS:
            return
        self.stack.append({
            "tag": tag, "hidden": hidden, "unrelated": unrelated, "identity": identity,
            "status": "topcard__flavor--closed" in attrs.get("class", "").split(),
            "text": [],
        })

    def handle_startendtag(self, tag, attrs):
        self.handle_starttag(tag, attrs)
        if tag not in VOID_TAGS:
            self.handle_endtag(tag)

    def handle_endtag(self, tag):
        if tag in VOID_TAGS:
            return
        if not self.stack or self.stack[-1]["tag"] != tag:
            # Do not repair ambiguous trees into positive closure evidence.
            self.uncertain = True
            return
        frame = self.stack.pop()
        text = " ".join(" ".join(frame["text"]).split())
        if frame["tag"] in {"h1", "title"} and LOGIN_HEADING.search(text):
            self.uncertain = True
        if (frame["status"] and not frame["hidden"] and not frame["unrelated"]
                and frame["identity"] == self.job_id):
            match = CLOSED.search(text)
            if match:
                self.phrases.append(match.group(0).casefold())

    def handle_data(self, data):
        if self.stack and not self.stack[-1]["hidden"] and not self.stack[-1]["unrelated"]:
            for frame in self.stack:
                if frame["status"] or frame["tag"] in {"h1", "title"}:
                    frame["text"].append(data)


def closed_phrase(body: bytes, job_id: str) -> str | None:
    # Equality cannot prove EOF. Keep the original byte cap and fail closed
    # against closure evidence even if a complete status precedes a long tail.
    if len(body) >= BODY_LIMIT:
        return None
    parser = _StatusParser(job_id)
    try:
        parser.feed(body.decode("utf-8", errors="strict"))
        parser.close()
    except (UnicodeError, ValueError):
        return None
    if parser.uncertain or parser.stack or parser.rawdata:
        return None
    return parser.phrases[0] if parser.phrases else None
