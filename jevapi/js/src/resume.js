// Rule-based resume reader: no AI key needed. It proposes every value it can
// find (contact details, summary, each job, project, degree and skills line,
// with wrapped lines joined back together); Jev then checks each value against
// the document. It never computes anything the resume doesn't say (no "years of
// experience"). Same rules as the Python resume.py.

const HEADINGS = [
  ["summary", /^(summary|professional summary|profile|professional profile|about|about me|objective|career objective)$/],
  ["experience", /^(experience|work experience|professional experience|employment|employment history|work history|internships?)$/],
  ["projects", /^(projects|selected projects|personal projects|key projects|academic projects)$/],
  ["education", /^(education|academic background|academics|qualifications)$/],
  ["skills", /^(skills|technical skills|core skills|key skills|tech stack|technologies|skills and tools)$/],
  ["certifications", /^(certifications|certificates|licenses and certifications)$/],
  ["awards", /^(awards|achievements|honors|honours|awards and achievements)$/],
  ["publications", /^(publications|papers)$/],
  ["languages", /^(languages|spoken languages)$/],
  ["interests", /^(interests|hobbies)$/],
  ["activities", /^(activities|leadership|volunteering|volunteer experience|extracurricular activities)$/],
];
const MON = "(?:jan|feb|mar|apr|may|jun|jul|aug|sep|sept|oct|nov|dec)[a-z]*\\.?";
const DATE = `(?:${MON}\\s+\\d{4}|\\d{1,2}\\/\\d{4}|\\d{4})`;
const RANGE = new RegExp(`^(.*?)[\\s|,(]*(${DATE}\\s*(?:–|—|-|to)\\s*(?:${DATE}|present|current|now|ongoing|today)|${DATE})\\)?\\s*$`, "i");
const BULLET = /^\s*[•●▪◦‣*·\-–]\s+/;
const EMAIL = /[\w.+-]+@[\w-]+(?:\.[\w-]+)+/;
const PHONE = /^\+?\d[\d\s().-]{7,}\d$/;
const URL = /^(?:https?:\/\/)?(?:www\.)?(?:[\w-]+\.)+[a-z]{2,}(?:\/\S*)?$/i;
const SUFFIX = /^(ing|ings|ed|er|ers|es|s|tion|tions|sion|sions|ment|ments|ness|ly|al|able|ible|ity|ities|ive|ize|ise|ized|ised|ful|less|ous|ance|ence|ation|ations)\b/;
const NAME = /^[A-Za-z][A-Za-z.'\- ]{1,60}$/;
export const MAX_RESUME_FIELDS = 80;

const squash = (s) => String(s).replace(/\s+/g, " ").trim();

/** Join a wrapped line onto the text before it ("schedul-" + "ing" -> "scheduling"). */
export function joinWrapped(a, b) {
  a = a.replace(/\s+$/, "");
  b = squash(b);
  if (!a) return b;
  if (!b) return a;
  if (a.endsWith("-") && /^[a-z]/.test(b)) return SUFFIX.test(b) ? a.slice(0, -1) + b : a + b;
  return `${a} ${b}`;
}

function headingOf(line) {
  const t = squash(line).replace(/[:：]$/, "").toLowerCase();
  if (!t || t.length > 40) return null;
  for (const [key, re] of HEADINGS) if (re.test(t)) return key;
  return null;
}

/** True when the text looks like a resume: 2+ resume section headings. */
export function isResume(text) {
  const found = new Set();
  for (const l of String(text || "").split(/\r?\n/)) {
    const h = headingOf(l);
    if (h) found.add(h);
  }
  return found.size >= 2;
}

// Group a section's lines into items: a bullet starts an item, indented or
// lowercase lines continue the one before, anything else starts a new header item.
function items(lines) {
  const out = [];
  for (const raw of lines) {
    if (!raw.trim()) continue;
    if (BULLET.test(raw)) { out.push({ bullet: true, text: squash(raw.replace(BULLET, "")) }); continue; }
    const last = out[out.length - 1];
    if (last && (/^\s/.test(raw) || /^[a-z]/.test(raw.trim()) || /[,&(\/-]$/.test(last.text))) { last.text = joinWrapped(last.text, raw); continue; }
    out.push({ bullet: false, text: raw.replace(/\s+$/, ""), raw });
  }
  return out;
}

const cols = (s) => s.split(/\s{2,}/).map(squash).filter(Boolean);

/** Every value a rule can find in a resume. Each is { name, label, value }. */
export function resumeFields(text, limit = MAX_RESUME_FIELDS) {
  const lines = String(text || "").split(/\r?\n/);
  const out = [];
  const add = (name, label, value) => {
    value = squash(value || "").replace(/^[|,;:\s]+|[|,;:\s]+$/g, "");
    if (!value || value.length > 1000 || out.some((f) => f.name === name)) return;
    out.push({ name, label, value });
  };
  // Split into the header block and sections.
  const sections = [];
  const header = [];
  let cur = null;
  for (const l of lines) {
    const h = headingOf(l);
    if (h) { cur = { key: h, lines: [] }; sections.push(cur); continue; }
    (cur ? cur.lines : header).push(l);
  }
  // Header: name, then contact parts split on | • · and wide gaps.
  const head = header.filter((l) => l.trim());
  let parts = [];
  if (head.length && NAME.test(squash(head[0])) && squash(head[0]).split(" ").length <= 5 && !EMAIL.test(head[0])) {
    add("name", "Name", head[0]);
    head.shift();
  }
  for (const l of head) parts.push(...l.split(/\s*[|•·]\s*|\s{3,}/).map(squash).filter(Boolean));
  let site = 0;
  for (const p of parts) {
    const e = p.match(EMAIL);
    if (e && !out.some((f) => f.name === "email")) add("email", "Email", e[0]);
    else if (PHONE.test(p)) add("phone", "Phone", p);
    else if (URL.test(p) && /linkedin\./i.test(p)) add("linkedin", "LinkedIn", p);
    else if (URL.test(p) && /github\./i.test(p)) add("github", "GitHub", p);
    else if (URL.test(p)) { site += 1; add(site === 1 ? "website" : `website_${site}`, site === 1 ? "Website" : `Website ${site}`, p); }
    else if (/,/.test(p) && p.length <= 60 && !out.some((f) => f.name === "location")) add("location", "Location", p);
    else if (p.length <= 80) add("headline", "Headline", p);
  }
  if (!out.some((f) => f.name === "email")) { const e = String(text).match(EMAIL); if (e) add("email", "Email", e[0]); }

  const counters = {};
  const next = (k) => (counters[k] = (counters[k] || 0) + 1);
  for (const s of sections) {
    const its = items(s.lines);
    if (s.key === "summary") {
      add("summary", "Summary", its.map((i) => i.text).join(" "));
    } else if (s.key === "experience" || s.key === "education") {
      const job = s.key === "experience";
      let n = 0, stage = 0, points = [];
      const flush = () => { if (n && points.length) add(`${job ? "job" : "education"}_${n}_highlights`, `${job ? "Job" : "Education"} ${n} highlights`, points.join("; ")); points = []; };
      for (const it of its) {
        const m = !it.bullet && it.text.match(RANGE);
        if (m && squash(m[1])) {
          flush();
          n = next(s.key);
          const left = cols(m[1]).join(" ");
          const at = job ? left.match(/^(.+?)\s+(?:\||@|at)\s+(.+)$/) : null;
          add(`${job ? "job" : "education"}_${n}_${job ? "title" : "degree"}`, `${job ? "Job" : "Education"} ${n} ${job ? "title" : "degree"}`, at ? at[1] : left);
          if (at) add(`job_${n}_company`, `Job ${n} company`, at[2]);
          add(`${job ? "job" : "education"}_${n}_dates`, `${job ? "Job" : "Education"} ${n} dates`, m[2]);
          stage = at ? 2 : 1;
        } else if (!it.bullet && n && stage === 1) {
          const [org, ...rest] = cols(it.text);
          const cm = org.match(/^(.*\S),\s*([^,]+)$/);
          const keep = cm && /^(inc|llc|ltd|pvt|co|corp|gmbh|plc|llp)\.?$/i.test(cm[2]);
          add(`${job ? "job" : "education"}_${n}_${job ? "company" : "school"}`, `${job ? "Job" : "Education"} ${n} ${job ? "company" : "school"}`, cm && !keep ? cm[1] : org);
          if (cm && !keep) add(`${job ? "job" : "education"}_${n}_location`, `${job ? "Job" : "Education"} ${n} location`, cm[2]);
          else if (rest.length) add(`${job ? "job" : "education"}_${n}_location`, `${job ? "Job" : "Education"} ${n} location`, rest.join(" "));
          stage = 2;
        } else if (n) {
          points.push(it.text);
        } else {
          add(`${s.key}_${next(s.key + "_note")}`, `${s.key} note`, it.text);
        }
      }
      flush();
    } else if (s.key === "projects") {
      let n = 0, points = [];
      const flush = () => { if (n && points.length) add(`project_${n}_highlights`, `Project ${n} highlights`, points.join("; ")); points = []; };
      for (const it of its) {
        if (it.bullet && n) { points.push(it.text); continue; }
        if (it.bullet) { n = next("project"); add(`project_${n}_name`, `Project ${n} name`, it.text); continue; }
        flush();
        n = next("project");
        const [left, ...right] = cols(it.text);
        const [nm, ...sub] = left.split(/\s+[–—-]\s+|:\s+/);
        add(`project_${n}_name`, `Project ${n} name`, nm);
        if (sub.length) add(`project_${n}_summary`, `Project ${n} summary`, sub.join(" - "));
        if (right.length) add(`project_${n}_tech`, `Project ${n} tech`, right.join(", "));
      }
      flush();
    } else if (s.key === "skills") {
      for (const it of its) {
        const m = it.text.match(/^\s*([A-Za-z][A-Za-z0-9 &/+.\-]{0,39}?)\s*:\s*(.+)$/);
        if (m) add(`skills_${m[1].toLowerCase().replace(/[^a-z0-9]+/g, "_").replace(/^_|_$/g, "")}`, `Skills: ${squash(m[1])}`, m[2]);
        else add(`skills_${next("skills")}`, "Skills", it.text);
      }
    } else {
      const k = next(s.key);
      add(k === 1 ? s.key : `${s.key}_${k}`, s.key[0].toUpperCase() + s.key.slice(1), its.map((i) => i.text).join("; "));
    }
  }
  return out.slice(0, limit);
}
