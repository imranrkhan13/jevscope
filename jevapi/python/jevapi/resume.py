"""Rule-based resume reader: no AI key needed.

It proposes every value it can find (contact details, summary, each job,
project and degree with its own dates, one field per bullet, each skills line,
any other section), joining wrapped lines back together. Jev then checks each
value against the document. It never computes anything the resume doesn't say
(no "years of experience"). Same rules as the JS resume.js.
"""

from __future__ import annotations

import re
import unicodedata
from typing import Optional

_A = re.ASCII
_PRE = r"(?:selected|relevant|key|other|additional|recent|professional|technical|core|personal|academic|side|work)\s+"
_AW = r"(?:awards|honors|honours|achievements)"
_HEADINGS = [
    ("summary", r"^(summary|professional summary|profile|professional profile|about|about me|objective|career objective)$"),
    ("experience", rf"^({_PRE})?(experience|employment|employment history|work history|internships?|research experience)$"),
    # "Projects", "Additional Engineering Projects", "Selected AI Infrastructure Project".
    ("projects", rf"^(({_PRE})?(projects|open source|open-source projects)|({_PRE})?([a-z&/-]+\s+){{1,2}}projects|{_PRE}([a-z&/-]+\s+){{0,2}}project)$"),
    ("education", r"^(education|academic background|academics|qualifications)$"),
    ("skills", rf"^({_PRE})?(skills|skills and tools|tech stack|technologies)$"),
    ("certifications", r"^(certifications|certificates|licenses and certifications|licenses & certifications)$"),
    ("awards", rf"^({_PRE})?(awards|achievements|honors|honours|{_AW}\s+(?:and|&)\s+{_AW})$"),
    ("publications", rf"^({_PRE})?(publications|papers)$"),
    ("patents", r"^patents$"),
    ("talks", r"^(invited talks|talks|presentations)$"),
    ("languages", r"^(languages|spoken languages)$"),
    ("interests", r"^(interests|hobbies)$"),
    ("activities", r"^(activities|leadership|volunteering|volunteer experience|extracurricular activities|community|community involvement)$"),
]
_HEADINGS_RE = [(k, re.compile(p)) for k, p in _HEADINGS]
_MON = r"(?:jan|feb|mar|apr|may|jun|jul|aug|sep|sept|oct|nov|dec)[a-z]*\.?"
_ONE = rf"(?:{_MON}\s+\d{{4}}|\d{{1,2}}/\d{{4}}|(?:19|20)\d{{2}})"
_SPAN = rf"{_ONE}(?:\s*(?:–|—|-|\u00ad|to)\s*(?:{_ONE}|present|current|now|ongoing|today))?"
_DATES = re.compile(rf"(^|[\s|,(])({_SPAN})\)?(?=$|[\s|,])", re.I)
_DATE_ONLY = re.compile(rf"^\(?{_SPAN}\)?$", re.I)
_LEAD_DATE = re.compile(rf"^{_SPAN}\s+(?=\S)", re.I)
_DURATION = re.compile(r"^(\d+\s+(years?|yrs?|months?|mos?)\s*)+$", re.I)
_NOISE = re.compile(r"^(\d{1,3}|last updated\b.*|page \d+( of \d+)?|.{1,60}\s[–—-]\s\d{1,2}/\d{1,2}|.*(?<![A-Za-z])(r[ée]sum[ée]|cv|curriculum vitae)(?![A-Za-z]).*\s\d{1,2})$", re.I)
_BULLET = re.compile(r"^(\s*)([•●▪◦‣*·\-–]|\d{1,2}[.)])\s+")
_EMAIL = re.compile(r"[\w.+-]+@[\w-]+(?:\.[\w-]+)+", _A)
_PHONE = re.compile(r"^\+?\d[\d\s().-]{7,}\d$")
_URL = re.compile(r"^(?:https?://)?(?:www\.)?(?:[\w-]+\.)+[a-z]{2,}(?:/\S*)?$", re.I | _A)
_SUFFIX = re.compile(r"^(ing|ings|ed|er|ers|es|s|tion|tions|sion|sions|ment|ments|ness|ly|al|able|ible|ity|ities|ive|ize|ise|ized|ised|ful|less|ous|ance|ence|ation|ations)\b", _A)
_NAME = re.compile(r"^[A-Za-z][A-Za-z.'\- ]{1,60}$")
_TITLE = re.compile(r"\b(engineer|developer|programmer|intern|internship|manager|founder|co-founder|cto|ceo|cfo|coo|vp|president|analyst|scientist|designer|lead|director|consultant|researcher|associate|architect|head|officer|specialist|assistant|fellow|professor|lecturer|student|administrator|technician|coordinator|executive|trainee|apprentice|contractor|freelancer|owner|partner|advisor|editor|writer|tutor|teacher|volunteer|member)\b", re.I | _A)
_DEGREE = re.compile(r"^(b\.?\s?sc|b\.?\s?s|b\.?\s?a|b\.?\s?e|b\.?\s?tech|b\.?\s?com|bca|m\.?\s?sc|m\.?\s?s|m\.?\s?a|m\.?\s?e|m\.?\s?tech|mca|mba|ph\.?\s?d|md|jd|llb|llm|bachelor|master|doctor|diploma|associate|certificate|high school|hsc|ssc)\b", re.I | _A)
_SCHOOL = re.compile(r"\b(university|college|institute|school|academy|polytechnic|iit|nit|iiit|conservatory)\b", re.I | _A)
# A place, not a product: "Pune, India", "Remote", or a well-known city or country.
_PLACE = re.compile(r"^(.*,.*|\(?(remote|hybrid|on-?site|work from home)\)?.*|(mumbai|bombay|bengaluru|bangalore|pune|delhi|new delhi|ncr|hyderabad|chennai|kolkata|gurgaon|gurugram|noida|ahmedabad|jaipur|kochi|london|paris|berlin|munich|amsterdam|dublin|madrid|lisbon|zurich|new york|nyc|san francisco|sf|bay area|seattle|austin|boston|chicago|los angeles|toronto|vancouver|singapore|dubai|sydney|melbourne|tokyo|india|usa|us|uk|united states|united kingdom|germany|france|canada|netherlands|ireland|spain|australia|uae)\.?)$", re.I)
# A word that cannot end a bullet, so the next line continues it ("... OpenRouter, and" + "LiteLLM.").
_OPEN_END = re.compile(r"\b(and|or|of|the|to|with|for|in|on|a|an|by|from|across|using|via|into|at|as)$", re.I)
_PROJECT_START = re.compile(r"^[^\s•].{0,60}?\s(\||[–—])\s+\S")
_CORP = re.compile(r"^(inc|llc|ltd|pvt|co|corp|gmbh|plc|llp|pvt ltd|private limited)\.?$", re.I)
_SKILL = re.compile(r"^\s*([A-Za-z][A-Za-z0-9 &/+.\-]{0,39}?)\s*:\s*(.+)$")
MAX_RESUME_FIELDS = 120


def _squash(s: str) -> str:
    s = re.sub(r"[\ue000-\uf8ff\u200b-\u200d\ufeff]", " ", str(s))
    return re.sub(r"\s+", " ", s).strip()


def _indent(s: str) -> int:
    return len(s) - len(s.lstrip())


def _slug(s: str) -> str:
    t = unicodedata.normalize("NFKD", s.lower())
    return re.sub(r"[^a-z0-9]+", "_", t).strip("_")[:30] or "section"


def join_wrapped(a: str, b: str) -> str:
    """Join a wrapped line onto the text before it ("schedul-" + "ing" -> "scheduling")."""
    a = a.rstrip()
    b = _squash(b)
    if not a:
        return b
    if not b:
        return a
    if a.endswith("\u00ad"):
        return a[:-1] + b
    if a.endswith("-") and re.match(r"[a-z]", b):
        return a[:-1] + b if _SUFFIX.match(b) else a + b
    return f"{a} {b}"


def _looks_tech(s: str) -> bool:
    """A line of technologies: "Python, FastAPI, Next.js" (short comma-separated items)."""
    return "," in s and all(x and len(x.split()) <= 3 for x in re.split(r"\s*,\s*", s))


def _title_of(line: str) -> str:
    # A subtitle after a bar is ignored: "Selected Projects | Applied AI & Backend Systems".
    return re.sub(r"[:：]$", "", re.sub(r"\s+\|\s+.*$", "", _squash(line)))


def _heading_of(line: str) -> Optional[str]:
    t = _title_of(line).lower()
    if not t or len(t) > 40:
        return None
    for key, rx in _HEADINGS_RE:
        if rx.match(t):
            return key
    return None


def is_resume(text: str) -> bool:
    """True when the text looks like a resume: 2+ resume section headings."""
    found = {h for h in (_heading_of(l) for l in str(text or "").splitlines()) if h}
    return len(found) >= 2


def _take_dates(s: str) -> tuple[str, str]:
    m = _DATES.search(s)
    if not m:
        return s, ""
    at = m.start() + len(m.group(1))
    rest = s[:at] + " " * len(m.group(2)) + s[at + len(m.group(2)):]
    rest = re.sub(r"\(\s*\)", "", rest, count=1)
    return re.sub(r"[\s|,(]+$", "", rest), _squash(m.group(2))


def _cols(s: str) -> list[str]:
    return [c for c in (_squash(x) for x in re.split(r"\s{2,}", s)) if c]


def _entries(lines: list[str], starts_entry=None) -> list[dict]:
    """Group a section's lines into entries: {head, bullets, dates}."""
    out: list[dict] = []
    cur: Optional[dict] = None
    last: Optional[dict] = None
    blank = False

    def start() -> dict:
        e = {"head": [], "bullets": [], "dates": ""}
        out.append(e)
        return e

    for raw in lines:
        if not raw.strip():
            blank = True
            continue
        b = _BULLET.match(raw)
        body = raw[len(b.group(0)):] if b else raw
        # Right-column dates and durations are split off.
        keep: list[str] = []
        dates = ""
        for p in re.split(r"\s{3,}", body):
            q = _squash(p)
            if not q:
                keep.append(p)
                continue
            if _DURATION.match(q):
                continue
            if keep and _DATE_ONLY.match(q) and not dates:
                dates = re.sub(r"^\(|\)$", "", q)
                continue
            keep.append(p)
        body = "   ".join(keep)
        text = _squash(body)
        # Some sections mark each entry by its own first line ("Name – what it is").
        opens = bool(starts_entry and not b and starts_entry.search(text))
        if b:
            if cur is None:
                cur = start()
            last = {"entry": cur, "bullet": True, "indent": len(b.group(0)), "text": text, "long": False}
            cur["bullets"].append(text)
        elif text and last and not blank and not opens and (
            (last["bullet"] and (_OPEN_END.search(last["text"]) or (re.match(r"\d", text) and not re.search(r"[.!?:;]$", last["text"]) and not _take_dates(body)[1])))
            or (last["bullet"] and _indent(raw) >= last["indent"] - 1 and not _DATE_ONLY.match(_squash((_cols(raw) or [""])[0])))
            or re.match(r"[a-z]", text)
            or re.search(r"[,&(/\u00ad-]$", last["text"])
            or (last["long"] and len(text.split(" ")) <= 3 and not re.search(r"[.:;!?]$", last["text"]))
        ):
            e = last["entry"]
            if last["bullet"]:
                last["text"] = join_wrapped(last["text"], text)
                e["bullets"][-1] = last["text"]
            else:
                last["text"] = join_wrapped(e["head"][-1], body)
                e["head"][-1] = last["text"]
        elif text:
            _, d = _take_dates(body)
            if cur is None or blank or opens or cur["bullets"] or (d and (cur["dates"] or dates)):
                cur = start()
            cur["head"].append(body.rstrip())
            # A long line that lost a right-hand date was likely cut short.
            last = {"entry": cur, "bullet": False, "indent": _indent(raw), "text": text, "long": bool(dates) and len(text) >= 65}
        if dates and cur is not None and not cur["dates"]:
            cur["dates"] = dates
        blank = False
    return out


def _org_place(s: str) -> tuple[str, str]:
    m = re.match(r"^(.*\S),\s*([^,]+)$", s)
    if not m or _CORP.match(m.group(2).strip()):
        return s, ""
    return m.group(1), m.group(2)


def _dash_place(s: str) -> tuple[str, str]:
    m = re.match(r"^(.*\S)\s+[–—]\s+([^–—]+)$", s)
    return (m.group(1), m.group(2)) if m and not _TITLE.search(m.group(2)) else (s, "")


def _rows(e: dict) -> tuple[list[list[str]], str]:
    dates = e["dates"]
    rows = []
    for h in e["head"]:
        rest, d = _take_dates(h)
        if d and not dates:
            dates = d
        c = _cols(rest)
        if c:
            rows.append(c)
    return rows, dates


def resume_fields(text: str, limit: int = MAX_RESUME_FIELDS) -> list[dict]:
    """Every value a rule can find in a resume. Each is {name, label, value, description}."""
    lines = [l for l in str(text or "").splitlines() if not _NOISE.match(_squash(l))]
    out: list[dict] = []
    names: set[str] = set()

    def add(name: str, label: str, value, description: str = "") -> None:
        value = re.sub(r"^[|,;:\s\u00ad–—]+|[|,;:\s]+$", "", _squash(value or ""))
        if not re.search(r"[^\W_]", value) or len(value) > 1000 or name in names:
            return
        names.add(name)
        f = {"name": name, "label": label, "value": value}
        if description:
            f["description"] = description
        out.append(f)

    sections: list[dict] = []
    header: list[str] = []
    cur: Optional[dict] = None
    for l in lines:
        h = _heading_of(l)
        if h:
            cur = {"key": h, "title": _title_of(l), "lines": []}
            sections.append(cur)
            continue
        (cur["lines"] if cur else header).append(l)

    head = [l for l in header if l.strip()]
    if head and _NAME.match(_squash(head[0])) and len(_squash(head[0]).split(" ")) <= 5 and not _EMAIL.search(head[0]):
        add("name", "Name", head[0])
        head.pop(0)
    site = 0
    for i, l in enumerate(head):
        parts = [p for p in (_squash(x) for x in re.split(r"\s*[|•·]\s*|\s{3,}", l)) if p]
        contact = any(_EMAIL.search(p) or _PHONE.match(p) or _URL.match(p) for p in parts)
        if not contact and i + 1 < len(head) and len(parts) == 1 and len(_squash(l).split(" ")) <= 6 and not re.search(r"[.,]$", _squash(l)) and "email" in names:
            sections.insert(0, {"key": _slug(_squash(l)), "title": _squash(l), "lines": head[i + 1:]})
            break
        for p in parts:
            e = _EMAIL.search(p)
            if e and "email" not in names:
                add("email", "Email", e.group(0))
            elif _PHONE.match(p):
                add("phone", "Phone", p)
            elif _URL.match(p) and re.search(r"linkedin\.", p, re.I):
                add("linkedin", "LinkedIn", p)
            elif _URL.match(p) and re.search(r"github\.", p, re.I):
                add("github", "GitHub", p)
            elif _URL.match(p):
                site += 1
                add("website" if site == 1 else f"website_{site}", "Website" if site == 1 else f"Website {site}", p)
            elif "," in p and len(p) <= 60 and "location" not in names:
                add("location", "Location", p)
            elif len(p) <= 80 and re.search(r"\s", p):
                add("headline", "Headline", p)
    if "email" not in names:
        e = _EMAIL.search(str(text))
        if e:
            add("email", "Email", e.group(0))

    counters: dict[str, int] = {}

    def nxt(k: str) -> int:
        counters[k] = counters.get(k, 0) + 1
        return counters[k]

    def points(p: str, P: str, what: str, e: dict) -> None:
        for k, b in enumerate(e["bullets"], 1):
            add(f"{p}_highlight_{k}", f"{P} highlight {k}", b, f"bullet point {k} under {what}")

    for s in sections:
        es = _entries(s["lines"], _PROJECT_START if s["key"] == "projects" else None)
        key = s["key"]
        if key == "summary":
            add("summary", "Summary", " ".join(x for e in es for x in e["head"] + e["bullets"]))
        elif key == "experience":
            for e in es:
                n = nxt("job")
                p, P = f"job_{n}", f"Job {n}"
                rows, dates = _rows(e)
                title = company = place = product = ""
                used = 2
                first = rows[0] if rows else []
                second = rows[1] if len(rows) > 1 else []
                if len(first) > 1 and not _TITLE.search(first[-1]):
                    place = first.pop()
                line = " ".join(first)
                at = re.match(r"^(.+?)\s+(?:\||@|at)\s+(.+)$", line)
                comma = re.match(r"^(.+?),\s+(.+)$", line)
                if at:
                    title, company = at.group(1), at.group(2)
                elif comma and not second:
                    a, b2 = comma.group(1), comma.group(2)
                    if not place:
                        b2, place = _dash_place(b2)
                    if _TITLE.search(b2) and not _TITLE.search(a):
                        title, company = b2, a
                    else:
                        title, company = a, b2
                elif second and not _TITLE.search(line) and _TITLE.search(second[0]):
                    co, pl = (line, "") if place else _org_place(line)
                    company, title = co, second[0]
                    # "Title    ShipIt": beside the title is a place only if it looks like one; otherwise the product or team.
                    side = " ".join(second[1:])
                    if side and not place and not pl and not _PLACE.match(side):
                        product = side
                    else:
                        place = place or pl or side
                else:
                    title = line
                    if second:
                        org, right = second[0], second[1:]
                        co, pl = (org, "") if place else _org_place(org)
                        company = co
                        place = place or pl or " ".join(right)
                if at or (comma and not second):
                    used = 1
                # Any other line under the title ("Tracking for small shops") describes the job.
                about = " ".join(" ".join(r) for r in rows[used:])
                if not title and not company:
                    for b in e["bullets"]:
                        add(f"experience_{nxt('experience_note')}", "Experience note", b)
                    continue
                what = "the " + (f'"{title}" ' if title else "") + "job" + (f' at "{company}"' if company else "")
                add(f"{p}_title", f"{P} title", title, f"job title of job {n}" + (f', the one at "{company}"' if company else ""))
                add(f"{p}_company", f"{P} company", company, f"company or employer of job {n}" + (f', the "{title}" job' if title else ""))
                add(f"{p}_location", f"{P} location", place, f"location of {what}")
                add(f"{p}_product", f"{P} product or team", product, f"product, team or client named with {what}")
                add(f"{p}_dates", f"{P} dates", dates, f"dates of {what}")
                add(f"{p}_about", f"{P} about", about, f"short description given under {what}")
                points(p, P, what, e)
        elif key == "education":
            for e in es:
                n = nxt("education")
                p, P = f"education_{n}", f"Education {n}"
                rows, dates = _rows(e)
                degree = school = area = place = ""
                first = rows[0] if rows else []
                second = rows[1] if len(rows) > 1 else []
                if len(first) > 1 and not _DEGREE.match(first[-1]) and not _SCHOOL.search(first[-1]):
                    place = first.pop()
                if len(first) > 1 and _DEGREE.match(first[0]):
                    degree = first[0]
                    rest, pl = _dash_place(" ".join(first[1:]))
                    place = place or pl
                    sc, ar = _org_place(rest)
                    if ar and _DEGREE.match(ar):
                        school, degree = sc, ar
                    else:
                        school, area = (sc, ar) if _SCHOOL.search(sc) else (rest, "")
                else:
                    line = " ".join(first)
                    if not place:
                        line, place = _dash_place(line)
                    comma = re.match(r"^(.+?),\s+(.+)$", line)
                    if comma and _SCHOOL.search(comma.group(1)) and _DEGREE.match(comma.group(2)):
                        school, degree = comma.group(1), comma.group(2)
                    elif comma and _DEGREE.match(comma.group(1)) and _SCHOOL.search(comma.group(2)):
                        degree, school = comma.group(1), comma.group(2)
                    elif _SCHOOL.search(line) and not _DEGREE.match(line) and second:
                        school, degree = line, " ".join(second)
                    else:
                        degree = line
                        if second:
                            org, right = second[0], second[1:]
                            if place:
                                school = org
                            else:
                                school, place = _org_place(org)
                            if not place and right:
                                place = " ".join(right)
                what = "the " + (f'"{degree}" ' if degree else "") + "degree" + (f' at "{school}"' if school else "")
                add(f"{p}_degree", f"{P} degree", degree, f"degree of education entry {n}" + (f', the one at "{school}"' if school else ""))
                add(f"{p}_field", f"{P} field of study", area, f"field of study of {what}")
                add(f"{p}_school", f"{P} school", school, f"school or university of education entry {n}" + (f', the "{degree}" degree' if degree else ""))
                add(f"{p}_location", f"{P} location", place, f"location of {what}")
                add(f"{p}_dates", f"{P} dates", dates, f"dates of {what}")
                points(p, P, what, e)
        elif key == "projects":
            for e in es:
                if not e["head"]:
                    for b in e["bullets"]:
                        n = nxt("project")
                        add(f"project_{n}_name", f"Project {n} name", b)
                    continue
                n = nxt("project")
                p, P = f"project_{n}", f"Project {n}"
                dates = e["dates"]
                h0, d0 = _take_dates(e["head"][0])
                if d0 and not dates:
                    dates = d0
                c = _cols(h0)
                left, right = (c[0], c[1:]) if c else ("", [])
                nm, *sub = re.split(r"\s+[–—-]\s+|:\s+", left)
                if right and re.match(r"[–—-]\s", right[0]):
                    # "Name   – what it is" with a wide gap before the dash.
                    sub = sub + [re.sub(r"^[–—-]\s+", "", " ".join(right))]
                    right = []
                if re.search(r"\s\|\s", _squash(h0)):
                    # "Name | tagline | tech" or "Name | tagline".
                    bits = [x for x in re.split(r"\s*\|\s*", _squash(h0)) if x]
                    nm, right, sub = bits[0], [], bits[1:]
                    if len(sub) > 1 or (sub and _looks_tech(sub[-1])):
                        right = [sub.pop()]
                    sub = [" | ".join(sub)]
                summary = " ".join(x for x in [" - ".join(sub)] + [_squash(_take_dates(h)[0]) for h in e["head"][1:]] if x)
                what = f'the project "{_squash(nm)}"'
                add(f"{p}_name", f"{P} name", nm, f"name of project {n} in the {s['title']} section")
                add(f"{p}_summary", f"{P} summary", summary, f"tagline or short description given with {what}")
                add(f"{p}_tech", f"{P} tech", ", ".join(right), f"technologies listed for {what}")
                add(f"{p}_dates", f"{P} dates", dates, f"dates of {what}")
                points(p, P, what, e)
        elif key == "skills":
            for e in es:
                for t in [_squash(h) for h in e["head"]] + e["bullets"]:
                    m = _SKILL.match(t)
                    if m:
                        add(f"skills_{_slug(m.group(1))}", f"Skills: {_squash(m.group(1))}", m.group(2), f'skills listed as "{_squash(m.group(1))}"')
                    else:
                        add(f"skills_{nxt('skills')}", "Skills", t)
        else:
            # Any other section: one field per bullet or line.
            title = s["title"]
            Title = title[:1].upper() + title[1:]
            vals = [x for e in es for x in [_LEAD_DATE.sub("", _squash(h)) for h in e["head"]] + e["bullets"]]
            for v in vals:
                k = nxt(key)
                one = len(vals) == 1
                add(key if k == 1 and one else f"{key}_{k}", Title if one else f"{Title} {k}", v, f'the "{title}" section' if one else f'item {k} in the "{title}" section')
    return out[:limit]
