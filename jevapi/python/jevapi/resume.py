"""Rule-based resume reader: no AI key needed.

It proposes every value it can find (contact details, summary, each job,
project, degree and skills line, with wrapped lines joined back together); Jev
then checks each value against the document. It never computes anything the
resume doesn't say (no "years of experience"). Same rules as the JS resume.js.
"""

from __future__ import annotations

import re
from typing import Optional

_HEADINGS = [
    ("summary", r"^(summary|professional summary|profile|professional profile|about|about me|objective|career objective)$"),
    ("experience", r"^(experience|work experience|professional experience|employment|employment history|work history|internships?)$"),
    ("projects", r"^(projects|selected projects|personal projects|key projects|academic projects)$"),
    ("education", r"^(education|academic background|academics|qualifications)$"),
    ("skills", r"^(skills|technical skills|core skills|key skills|tech stack|technologies|skills and tools)$"),
    ("certifications", r"^(certifications|certificates|licenses and certifications)$"),
    ("awards", r"^(awards|achievements|honors|honours|awards and achievements)$"),
    ("publications", r"^(publications|papers)$"),
    ("languages", r"^(languages|spoken languages)$"),
    ("interests", r"^(interests|hobbies)$"),
    ("activities", r"^(activities|leadership|volunteering|volunteer experience|extracurricular activities)$"),
]
_HEADINGS_RE = [(k, re.compile(p)) for k, p in _HEADINGS]
_MON = r"(?:jan|feb|mar|apr|may|jun|jul|aug|sep|sept|oct|nov|dec)[a-z]*\.?"
_DATE = rf"(?:{_MON}\s+\d{{4}}|\d{{1,2}}/\d{{4}}|\d{{4}})"
_RANGE = re.compile(rf"^(.*?)[\s|,(]*({_DATE}\s*(?:–|—|-|to)\s*(?:{_DATE}|present|current|now|ongoing|today)|{_DATE})\)?\s*$", re.I)
_BULLET = re.compile(r"^\s*[•●▪◦‣*·\-–]\s+")
_EMAIL = re.compile(r"[\w.+-]+@[\w-]+(?:\.[\w-]+)+")
_PHONE = re.compile(r"^\+?\d[\d\s().-]{7,}\d$")
_URL = re.compile(r"^(?:https?://)?(?:www\.)?(?:[\w-]+\.)+[a-z]{2,}(?:/\S*)?$", re.I)
_SUFFIX = re.compile(r"^(ing|ings|ed|er|ers|es|s|tion|tions|sion|sions|ment|ments|ness|ly|al|able|ible|ity|ities|ive|ize|ise|ized|ised|ful|less|ous|ance|ence|ation|ations)\b")
_NAME = re.compile(r"^[A-Za-z][A-Za-z.'\- ]{1,60}$")
_SKILL = re.compile(r"^\s*([A-Za-z][A-Za-z0-9 &/+.\-]{0,39}?)\s*:\s*(.+)$")
_ORG_SUFFIX = re.compile(r"^(inc|llc|ltd|pvt|co|corp|gmbh|plc|llp)\.?$", re.I)
MAX_RESUME_FIELDS = 80


def _squash(s: str) -> str:
    return re.sub(r"\s+", " ", str(s)).strip()


def join_wrapped(a: str, b: str) -> str:
    """Join a wrapped line onto the text before it ("schedul-" + "ing" -> "scheduling")."""
    a = a.rstrip()
    b = _squash(b)
    if not a:
        return b
    if not b:
        return a
    if a.endswith("-") and re.match(r"[a-z]", b):
        return a[:-1] + b if _SUFFIX.match(b) else a + b
    return f"{a} {b}"


def _heading_of(line: str) -> Optional[str]:
    t = re.sub(r"[:：]$", "", _squash(line)).lower()
    if not t or len(t) > 40:
        return None
    for key, rx in _HEADINGS_RE:
        if rx.match(t):
            return key
    return None


def is_resume(text: str) -> bool:
    """True when the text looks like a resume: 2+ resume section headings."""
    return len({h for h in (_heading_of(l) for l in str(text or "").splitlines()) if h}) >= 2


def _items(lines: list[str]) -> list[dict]:
    out: list[dict] = []
    for raw in lines:
        if not raw.strip():
            continue
        if _BULLET.match(raw):
            out.append({"bullet": True, "text": _squash(_BULLET.sub("", raw, count=1))})
            continue
        last = out[-1] if out else None
        if last and (re.match(r"\s", raw) or re.match(r"[a-z]", raw.strip()) or re.search(r"[,&(/-]$", last["text"])):
            last["text"] = join_wrapped(last["text"], raw)
            continue
        out.append({"bullet": False, "text": raw.rstrip()})
    return out


def _cols(s: str) -> list[str]:
    return [c for c in (_squash(x) for x in re.split(r"\s{2,}", s)) if c]



def resume_fields(text: str, limit: int = MAX_RESUME_FIELDS) -> list[dict]:
    """Every value a rule can find in a resume. Each is {name, label, value}."""
    lines = str(text or "").splitlines()
    out: list[dict] = []

    def has(name: str) -> bool:
        return any(f["name"] == name for f in out)

    def add(name: str, label: str, value: Optional[str]) -> None:
        v = re.sub(r"^[|,;:\s]+|[|,;:\s]+$", "", _squash(value or ""))
        if not v or len(v) > 1000 or has(name):
            return
        out.append({"name": name, "label": label, "value": v})

    sections: list[dict] = []
    header: list[str] = []
    cur: Optional[dict] = None
    for l in lines:
        h = _heading_of(l)
        if h:
            cur = {"key": h, "lines": []}
            sections.append(cur)
            continue
        (cur["lines"] if cur else header).append(l)

    head = [l for l in header if l.strip()]
    if head and _NAME.match(_squash(head[0])) and len(_squash(head[0]).split(" ")) <= 5 and not _EMAIL.search(head[0]):
        add("name", "Name", head[0])
        head.pop(0)
    parts: list[str] = []
    for l in head:
        parts.extend(p for p in (_squash(x) for x in re.split(r"\s*[|•·]\s*|\s{3,}", l)) if p)
    site = 0
    for p in parts:
        e = _EMAIL.search(p)
        if e and not has("email"):
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
        elif "," in p and len(p) <= 60 and not has("location"):
            add("location", "Location", p)
        elif len(p) <= 80:
            add("headline", "Headline", p)
    if not has("email"):
        e = _EMAIL.search(str(text or ""))
        if e:
            add("email", "Email", e.group(0))

    counters: dict[str, int] = {}

    def nxt(k: str) -> int:
        counters[k] = counters.get(k, 0) + 1
        return counters[k]

    for s in sections:
        its = _items(s["lines"])
        key = s["key"]
        if key == "summary":
            add("summary", "Summary", " ".join(i["text"] for i in its))
        elif key in ("experience", "education"):
            job = key == "experience"
            pre, cap = ("job", "Job") if job else ("education", "Education")
            n, stage, points = 0, 0, []

            def flush() -> None:
                if n and points:
                    add(f"{pre}_{n}_highlights", f"{cap} {n} highlights", "; ".join(points))
                points.clear()

            for it in its:
                m = None if it["bullet"] else _RANGE.match(it["text"])
                if m and _squash(m.group(1)):
                    flush()
                    n = nxt(key)
                    left = " ".join(_cols(m.group(1)))
                    at = re.match(r"^(.+?)\s+(?:\||@|at)\s+(.+)$", left) if job else None
                    add(f"{pre}_{n}_{'title' if job else 'degree'}", f"{cap} {n} {'title' if job else 'degree'}", at.group(1) if at else left)
                    if at:
                        add(f"job_{n}_company", f"Job {n} company", at.group(2))
                    add(f"{pre}_{n}_dates", f"{cap} {n} dates", m.group(2))
                    stage = 2 if at else 1
                elif not it["bullet"] and n and stage == 1:
                    org, *rest = _cols(it["text"])
                    cm = re.match(r"^(.*\S),\s*([^,]+)$", org)
                    keep = bool(cm and _ORG_SUFFIX.match(cm.group(2)))
                    what = "company" if job else "school"
                    add(f"{pre}_{n}_{what}", f"{cap} {n} {what}", cm.group(1) if cm and not keep else org)
                    if cm and not keep:
                        add(f"{pre}_{n}_location", f"{cap} {n} location", cm.group(2))
                    elif rest:
                        add(f"{pre}_{n}_location", f"{cap} {n} location", " ".join(rest))
                    stage = 2
                elif n:
                    points.append(it["text"])
                else:
                    add(f"{key}_{nxt(key + '_note')}", f"{key} note", it["text"])
            flush()
        elif key == "projects":
            n, points = 0, []

            def pflush() -> None:
                if n and points:
                    add(f"project_{n}_highlights", f"Project {n} highlights", "; ".join(points))
                points.clear()

            for it in its:
                if it["bullet"] and n:
                    points.append(it["text"])
                    continue
                if it["bullet"]:
                    n = nxt("project")
                    add(f"project_{n}_name", f"Project {n} name", it["text"])
                    continue
                pflush()
                n = nxt("project")
                left, *right = _cols(it["text"])
                nm, *sub = re.split(r"\s+[–—-]\s+|:\s+", left)
                add(f"project_{n}_name", f"Project {n} name", nm)
                if sub:
                    add(f"project_{n}_summary", f"Project {n} summary", " - ".join(sub))
                if right:
                    add(f"project_{n}_tech", f"Project {n} tech", ", ".join(right))
            pflush()
        elif key == "skills":
            for it in its:
                m = _SKILL.match(it["text"])
                if m:
                    slug = re.sub(r"^_|_$", "", re.sub(r"[^a-z0-9]+", "_", m.group(1).lower()))
                    add(f"skills_{slug}", f"Skills: {_squash(m.group(1))}", m.group(2))
                else:
                    add(f"skills_{nxt('skills')}", "Skills", it["text"])
        else:
            k = nxt(key)
            add(key if k == 1 else f"{key}_{k}", key[0].upper() + key[1:], "; ".join(i["text"] for i in its))
    return out[:limit]
