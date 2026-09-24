// Rule-based resume reader: no AI key needed. It proposes every value it can
// find (contact details, summary, each job, project and degree with its own
// dates, one field per bullet, each skills line, any other section), joining
// wrapped lines back together. Jev then checks each value against the document.
// It never computes anything the resume doesn't say (no "years of experience").
// Same rules as the Python resume.py.

const PRE = "(?:selected|relevant|key|other|additional|recent|professional|technical|core|personal|academic|side|work)\\s+";
const HEADINGS = [
  ["summary", /^(summary|professional summary|profile|professional profile|about|about me|objective|career objective)$/],
  ["experience", new RegExp(`^(${PRE})?(experience|employment|employment history|work history|internships?|research experience)$`)],
  // "Projects", "Additional Engineering Projects", "Selected AI Infrastructure Project".
  ["projects", new RegExp(`^((${PRE})?(projects|open source|open-source projects)|(${PRE})?([a-z&/-]+\\s+){1,2}projects|${PRE}([a-z&/-]+\\s+){0,2}project)$`)],
  ["education", /^(education|academic background|academics|qualifications)$/],
  ["skills", new RegExp(`^(${PRE})?(skills|skills and tools|tech stack|technologies)$`)],
  ["certifications", /^(certifications|certificates|licenses and certifications|licenses & certifications)$/],
  ["awards", new RegExp(`^(${PRE})?(awards|achievements|honors|honours|(?:awards|honors|honours|achievements)\\s+(?:and|&)\\s+(?:awards|honors|honours|achievements))$`)],
  ["publications", new RegExp(`^(${PRE})?(publications|papers)$`)],
  ["patents", /^patents$/],
  ["talks", /^(invited talks|talks|presentations)$/],
  ["languages", /^(languages|spoken languages)$/],
  ["interests", /^(interests|hobbies)$/],
  ["activities", /^(activities|leadership|volunteering|volunteer experience|extracurricular activities|community|community involvement)$/],
];
const MON = "(?:jan|feb|mar|apr|may|jun|jul|aug|sep|sept|oct|nov|dec)[a-z]*\\.?";
const ONE = `(?:${MON}\\s+\\d{4}|\\d{1,2}\\/\\d{4}|(?:19|20)\\d{2})`;
const SPAN = `${ONE}(?:\\s*(?:–|—|-|\u00ad|to)\\s*(?:${ONE}|present|current|now|ongoing|today))?`;
const DATES = new RegExp(`(^|[\\s|,(])(${SPAN})\\)?(?=$|[\\s|,])`, "i");
const DATE_ONLY = new RegExp(`^\\(?${SPAN}\\)?$`, "i");
const DURATION = /^(\d+\s+(years?|yrs?|months?|mos?)\s*)+$/i;
const NOISE = /^(\d{1,3}|last updated\b.*|page \d+( of \d+)?|.{1,60}\s[–—-]\s\d{1,2}\/\d{1,2}|.*(?<![A-Za-z])(r[ée]sum[ée]|cv|curriculum vitae)(?![A-Za-z]).*\s\d{1,2})$/i;
const BULLET = /^(\s*)([•●▪◦‣*·\-–]|\d{1,2}[.)])\s+/;
const EMAIL = /[\w.+-]+@[\w-]+(?:\.[\w-]+)+/;
const PHONE = /^\+?\d[\d\s().-]{7,}\d$/;
const URL = /^(?:https?:\/\/)?(?:www\.)?(?:[\w-]+\.)+[a-z]{2,}(?:\/\S*)?$/i;
const SUFFIX = /^(ing|ings|ed|er|ers|es|s|tion|tions|sion|sions|ment|ments|ness|ly|al|able|ible|ity|ities|ive|ize|ise|ized|ised|ful|less|ous|ance|ence|ation|ations)\b/;
const NAME = /^[A-Za-z][A-Za-z.'\- ]{1,60}$/;
const TITLE = /\b(engineer|developer|programmer|intern|internship|manager|founder|co-founder|cto|ceo|cfo|coo|vp|president|analyst|scientist|designer|lead|director|consultant|researcher|associate|architect|head|officer|specialist|assistant|fellow|professor|lecturer|student|administrator|technician|coordinator|executive|trainee|apprentice|contractor|freelancer|owner|partner|advisor|editor|writer|tutor|teacher|volunteer|member)\b/i;
const DEGREE = /^(b\.?\s?sc|b\.?\s?s|b\.?\s?a|b\.?\s?e|b\.?\s?tech|b\.?\s?com|bca|m\.?\s?sc|m\.?\s?s|m\.?\s?a|m\.?\s?e|m\.?\s?tech|mca|mba|ph\.?\s?d|md|jd|llb|llm|bachelor|master|doctor|diploma|associate|certificate|high school|hsc|ssc)\b/i;
const SCHOOL = /\b(university|college|institute|school|academy|polytechnic|iit|nit|iiit|conservatory)\b/i;
// A place, not a product: "Pune, India", "Remote", or a well-known city or country.
const PLACE = /^(.*,.*|\(?(remote|hybrid|on-?site|work from home)\)?.*|(mumbai|bombay|bengaluru|bangalore|pune|delhi|new delhi|ncr|hyderabad|chennai|kolkata|gurgaon|gurugram|noida|ahmedabad|jaipur|kochi|london|paris|berlin|munich|amsterdam|dublin|madrid|lisbon|zurich|new york|nyc|san francisco|sf|bay area|seattle|austin|boston|chicago|los angeles|toronto|vancouver|singapore|dubai|sydney|melbourne|tokyo|india|usa|us|uk|united states|united kingdom|germany|france|canada|netherlands|ireland|spain|australia|uae)\.?)$/i;
// A line of technologies: "Python, FastAPI, Next.js" (short comma-separated items).
const looksTech = (s) => /,/.test(s) && s.split(/\s*,\s*/).every((x) => x && x.split(/\s+/).length <= 3);
// A word that cannot end a bullet, so the next line continues it ("... OpenRouter, and" + "LiteLLM.").
const OPEN_END = /\b(and|or|of|the|to|with|for|in|on|a|an|by|from|across|using|via|into|at|as)$/i;
const CORP = /^(inc|llc|ltd|pvt|co|corp|gmbh|plc|llp|pvt ltd|private limited)\.?$/i;
const PROJECT_START = /^[^\s•].{0,60}?\s(\||[–—])\s+\S/;
export const MAX_RESUME_FIELDS = 120;

const squash = (s) => String(s).replace(/[\uE000-\uF8FF\u200B-\u200D\uFEFF]/g, " ").replace(/\s+/g, " ").trim();
const indent = (s) => s.match(/^\s*/)[0].length;
const slug = (s) => s.toLowerCase().normalize("NFKD").replace(/[^a-z0-9]+/g, "_").replace(/^_|_$/g, "").slice(0, 30) || "section";

/** Join a wrapped line onto the text before it ("schedul-" + "ing" -> "scheduling"). */
export function joinWrapped(a, b) {
  a = a.replace(/\s+$/, "");
  b = squash(b);
  if (!a) return b;
  if (!b) return a;
  if (a.endsWith("\u00ad")) return a.slice(0, -1) + b;
  if (a.endsWith("-") && /^[a-z]/.test(b)) return SUFFIX.test(b) ? a.slice(0, -1) + b : a + b;
  return `${a} ${b}`;
}

function headingOf(line) {
  // A subtitle after a bar is ignored: "Selected Projects | Applied AI & Backend Systems".
  const t = squash(line).replace(/\s+\|\s+.*$/, "").replace(/[:：]$/, "").toLowerCase();
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

// Pull a date or date range out of a line: [line without it, dates or ""].
function takeDates(s) {
  const m = s.match(DATES);
  if (!m) return [s, ""];
  const at = m.index + m[1].length;
  const rest = (s.slice(0, at) + " ".repeat(m[2].length) + s.slice(at + m[2].length)).replace(/\(\s*\)/, "");
  return [rest.replace(/[\s|,(]+$/, ""), squash(m[2])];
}

const cols = (s) => s.split(/\s{2,}/).map(squash).filter(Boolean);

// Group a section's lines into entries: { head: [lines], bullets: [text], dates }.
// Bullets (and numbered items) belong to the entry above; a non-bullet line after
// bullets or after a blank line starts a new entry; wrapped lines are joined.
function entries(lines, startsEntry = null) {
  const out = [];
  let cur = null, last = null, blank = false;
  const start = () => { cur = { head: [], bullets: [], dates: "" }; out.push(cur); return cur; };
  for (const raw of lines) {
    if (!raw.trim()) { blank = true; continue; }
    const b = raw.match(BULLET);
    let body = b ? raw.slice(b[0].length) : raw;
    // Right-column dates and durations ("May 2020 – Aug 2020", "4 months") are split off.
    const parts = body.split(/\s{3,}/);
    const keep = [];
    let dates = "";
    for (const p of parts) {
      const q = squash(p);
      if (!q) { keep.push(p); continue; }
      if (DURATION.test(q)) continue;
      if (keep.length && DATE_ONLY.test(q) && !dates) { dates = q.replace(/^\(|\)$/g, ""); continue; }
      keep.push(p);
    }
    body = keep.join("   ");
    const text = squash(body);
    // Some sections mark each entry by its own first line ("Name – what it is"), with no bullets or blank lines between.
    const opens = Boolean(startsEntry && !b && startsEntry.test(text));
    if (b) {
      if (!cur) start();
      last = { entry: cur, bullet: true, indent: b[0].length, text };
      cur.bullets.push(text);
    } else if (text && last && !blank && !opens && ((last.bullet && (OPEN_END.test(last.text) || (/^\d/.test(text) && !/[.!?:;]$/.test(last.text) && !takeDates(body)[1]))) || (last.bullet && indent(raw) >= last.indent - 1 && !DATE_ONLY.test(squash(cols(raw)[0] || ""))) || /^[a-z]/.test(text) || /[,&(\/\u00ad-]$/.test(last.text) || (last.long && text.split(" ").length <= 3 && !/[.:;!?]$/.test(last.text)))) {
      // A wrapped line: join it onto the bullet or header line above.
      const e = last.entry;
      if (last.bullet) e.bullets[e.bullets.length - 1] = last.text = joinWrapped(last.text, text);
      else e.head[e.head.length - 1] = last.text = joinWrapped(e.head[e.head.length - 1], body);
    } else if (text) {
      const [, d] = takeDates(body);
      if (!cur || blank || opens || cur.bullets.length || (d && (cur.dates || dates))) start();
      cur.head.push(body.replace(/\s+$/, ""));
      // A long line that lost a right-hand date was likely cut short, so a 1-3 word line after it continues it.
      last = { entry: cur, bullet: false, indent: indent(raw), text, long: Boolean(dates) && text.length >= 65 };
    }
    if (dates && !cur.dates) cur.dates = dates;
    blank = false;
  }
  return out;
}

// "Company, City" -> [company, city], keeping "Acme, Inc".
function orgPlace(s) {
  const m = s.match(/^(.*\S),\s*([^,]+)$/);
  if (!m || CORP.test(m[2].trim())) return [s, ""];
  return [m[1], m[2]];
}

// Split "X – Location" when the dash tail looks like a place.
function dashPlace(s) {
  const m = s.match(/^(.*\S)\s+[–—]\s+([^–—]+)$/);
  return m && !TITLE.test(m[2]) ? [m[1], m[2]] : [s, ""];
}

/** Every value a rule can find in a resume. Each is { name, label, value, description }. */
export function resumeFields(text, limit = MAX_RESUME_FIELDS) {
  const lines = String(text || "").split(/\r?\n/).filter((l) => !NOISE.test(squash(l)));
  const out = [];
  const add = (name, label, value, description) => {
    value = squash(value || "").replace(/^[|,;:\s\u00ad–—]+|[|,;:\s]+$/g, "");
    if (!/[\p{L}\p{N}]/u.test(value) || value.length > 1000 || out.some((f) => f.name === name)) return;
    out.push(description ? { name, label, value, description } : { name, label, value });
  };
  // Split into the header block and sections.
  const sections = [];
  const header = [];
  let cur = null;
  for (const l of lines) {
    const h = headingOf(l);
    if (h) { cur = { key: h, title: squash(l).replace(/\s+\|\s+.*$/, "").replace(/[:：]$/, ""), lines: [] }; sections.push(cur); continue; }
    (cur ? cur.lines : header).push(l);
  }
  // Header: name, then contact parts split on | • · and wide gaps. A short titled
  // block after the contact lines ("Welcome to ...") becomes its own section.
  const head = header.filter((l) => l.trim());
  if (head.length && NAME.test(squash(head[0])) && squash(head[0]).split(" ").length <= 5 && !EMAIL.test(head[0])) {
    add("name", "Name", head[0]);
    head.shift();
  }
  let site = 0;
  for (let i = 0; i < head.length; i++) {
    const l = head[i];
    const parts = l.split(/\s*[|•·]\s*|\s{3,}/).map(squash).filter(Boolean);
    const contact = parts.some((p) => EMAIL.test(p) || PHONE.test(p) || URL.test(p));
    if (!contact && i + 1 < head.length && parts.length === 1 && squash(l).split(" ").length <= 6 && !/[.,]$/.test(squash(l)) && out.some((f) => f.name === "email")) {
      sections.unshift({ key: slug(squash(l)), title: squash(l), lines: head.slice(i + 1) });
      break;
    }
    for (const p of parts) {
      const e = p.match(EMAIL);
      if (e && !out.some((f) => f.name === "email")) add("email", "Email", e[0]);
      else if (PHONE.test(p)) add("phone", "Phone", p);
      else if (URL.test(p) && /linkedin\./i.test(p)) add("linkedin", "LinkedIn", p);
      else if (URL.test(p) && /github\./i.test(p)) add("github", "GitHub", p);
      else if (URL.test(p)) { site += 1; add(site === 1 ? "website" : `website_${site}`, site === 1 ? "Website" : `Website ${site}`, p); }
      else if (/,/.test(p) && p.length <= 60 && !out.some((f) => f.name === "location")) add("location", "Location", p);
      else if (p.length <= 80 && /\s/.test(p)) add("headline", "Headline", p);
    }
  }
  if (!out.some((f) => f.name === "email")) { const e = String(text).match(EMAIL); if (e) add("email", "Email", e[0]); }

  const counters = {};
  const next = (k) => (counters[k] = (counters[k] || 0) + 1);
  const points = (p, P, what, e) => e.bullets.forEach((b, k) => add(`${p}_highlight_${k + 1}`, `${P} highlight ${k + 1}`, b, `bullet point ${k + 1} under ${what}`));
  for (const s of sections) {
    const es = entries(s.lines, s.key === "projects" ? PROJECT_START : null);
    if (s.key === "summary") {
      add("summary", "Summary", es.flatMap((e) => [...e.head, ...e.bullets]).join(" "));
    } else if (s.key === "experience") {
      for (const e of es) {
        const n = next("job"), p = `job_${n}`, P = `Job ${n}`;
        let dates = e.dates, rows = [];
        for (const h of e.head) {
          const [rest, d] = takeDates(h);
          if (d && !dates) dates = d;
          const c = cols(rest);
          if (c.length) rows.push(c);
        }
        let title = "", company = "", place = "", product = "", used = 2;
        const first = rows[0] || [];
        const second = rows[1] || [];
        if (first.length > 1 && !TITLE.test(first[first.length - 1])) place = first.pop();
        const line = first.join(" ");
        const at = line.match(/^(.+?)\s+(?:\||@|at)\s+(.+)$/);
        const comma = line.match(/^(.+?),\s+(.+)$/);
        if (at) [title, company] = [at[1], at[2]];
        else if (comma && !second.length) {
          // "Title, Company – Place" or "Company, Title".
          let [a, b] = [comma[1], comma[2]];
          if (!place) [b, place] = dashPlace(b);
          if (TITLE.test(b) && !TITLE.test(a)) [title, company] = [b, a];
          else [title, company] = [a, b];
        } else if (second.length && !TITLE.test(line) && TITLE.test(second[0])) {
          // "Company" on one line, "Title" under it.
          const [co, pl] = place ? [line, ""] : orgPlace(line);
          [company, title] = [co, second[0]];
          // "Title    ShipIt": the text beside the title is a place only if it looks like one; otherwise it is the product or team.
          const side = second.slice(1).join(" ");
          if (side && !place && !pl && !PLACE.test(side)) product = side;
          else place = place || pl || side;
        } else {
          title = line;
          if (second.length) {
            const [org, ...right] = second;
            const [co, pl] = place ? [org, ""] : orgPlace(org);
            company = co;
            place = place || pl || right.join(" ");
          }
        }
        if (at || (comma && !second.length)) used = 1;
        // Any other line under the title ("Tracking for small shops") describes the job.
        const about = rows.slice(used).map((r) => r.join(" ")).join(" ");
        if (!title && !company) { e.bullets.forEach((b) => add(`experience_${next("experience_note")}`, "Experience note", b)); continue; }
        const what = `the ${title ? `"${title}"` : ""} job${company ? ` at "${company}"` : ""}`.replace("the  job", "the job");
        add(`${p}_title`, `${P} title`, title, `job title of job ${n}${company ? `, the one at "${company}"` : ""}`);
        add(`${p}_company`, `${P} company`, company, `company or employer of job ${n}${title ? `, the "${title}" job` : ""}`);
        add(`${p}_location`, `${P} location`, place, `location of ${what}`);
        add(`${p}_product`, `${P} product or team`, product, `product, team or client named with ${what}`);
        add(`${p}_dates`, `${P} dates`, dates, `dates of ${what}`);
        add(`${p}_about`, `${P} about`, about, `short description given under ${what}`);
        points(p, P, what, e);
      }
    } else if (s.key === "education") {
      for (const e of es) {
        const n = next("education"), p = `education_${n}`, P = `Education ${n}`;
        let dates = e.dates, rows = [];
        for (const h of e.head) {
          const [rest, d] = takeDates(h);
          if (d && !dates) dates = d;
          const c = cols(rest);
          if (c.length) rows.push(c);
        }
        let degree = "", school = "", area = "", place = "";
        const first = rows[0] || [];
        const second = rows[1] || [];
        if (first.length > 1 && !DEGREE.test(first[first.length - 1]) && !SCHOOL.test(first[first.length - 1])) place = first.pop();
        if (first.length > 1 && DEGREE.test(first[0])) {
          // "PhD    Princeton University, Computer Science"
          degree = first[0];
          let [rest, pl] = dashPlace(first.slice(1).join(" "));
          place = place || pl;
          const [sc, ar] = orgPlace(rest);
          if (ar && DEGREE.test(ar)) [school, degree] = [sc, ar];
          else [school, area] = SCHOOL.test(sc) ? [sc, ar] : [rest, ""];
        } else {
          let line = first.join(" ");
          if (!place) [line, place] = dashPlace(line);
          const comma = line.match(/^(.+?),\s+(.+)$/);
          if (comma && SCHOOL.test(comma[1]) && DEGREE.test(comma[2])) [school, degree] = [comma[1], comma[2]];
          else if (comma && DEGREE.test(comma[1]) && SCHOOL.test(comma[2])) [degree, school] = [comma[1], comma[2]];
          else if (SCHOOL.test(line) && !DEGREE.test(line) && second.length) { school = line; degree = second.join(" "); }
          else {
            degree = line;
            if (second.length) {
              const [org, ...right] = second;
              [school, place] = place ? [org, place] : orgPlace(org);
              if (!place && right.length) place = right.join(" ");
            }
          }
        }
        const what = `the ${degree ? `"${degree}" ` : ""}degree${school ? ` at "${school}"` : ""}`;
        add(`${p}_degree`, `${P} degree`, degree, `degree of education entry ${n}${school ? `, the one at "${school}"` : ""}`);
        add(`${p}_field`, `${P} field of study`, area, `field of study of ${what}`);
        add(`${p}_school`, `${P} school`, school, `school or university of education entry ${n}${degree ? `, the "${degree}" degree` : ""}`);
        add(`${p}_location`, `${P} location`, place, `location of ${what}`);
        add(`${p}_dates`, `${P} dates`, dates, `dates of ${what}`);
        points(p, P, what, e);
      }
    } else if (s.key === "projects") {
      for (const e of es) {
        if (!e.head.length) { e.bullets.forEach((b) => { const n = next("project"); add(`project_${n}_name`, `Project ${n} name`, b); }); continue; }
        const n = next("project"), p = `project_${n}`, P = `Project ${n}`;
        let dates = e.dates;
        const [h0, d0] = takeDates(e.head[0]);
        if (d0 && !dates) dates = d0;
        let [left, ...right] = cols(h0);
        let [nm, ...sub] = (left || "").split(/\s+[–—-]\s+|:\s+/);
        if (right.length && /^[–—-]\s/.test(right[0])) {
          // "Name   – what it is" with a wide gap before the dash.
          sub = [...sub, right.join(" ").replace(/^[–—-]\s+/, "")]; right = [];
        }
        if (/\s\|\s/.test(squash(h0))) {
          // "Name | tagline | tech" or "Name | tagline".
          const bits = squash(h0).split(/\s*\|\s*/).filter(Boolean);
          nm = bits[0]; right = []; sub = bits.slice(1);
          if (sub.length > 1 || (sub.length && looksTech(sub[sub.length - 1]))) right = [sub.pop()];
          sub = [sub.join(" | ")];
        }
        const summary = [sub.join(" - "), ...e.head.slice(1).map((h) => squash(takeDates(h)[0]))].filter(Boolean).join(" ");
        const what = `the project "${squash(nm)}"`;
        add(`${p}_name`, `${P} name`, nm, `name of project ${n} in the ${s.title} section`);
        add(`${p}_summary`, `${P} summary`, summary, `tagline or short description given with ${what}`);
        add(`${p}_tech`, `${P} tech`, right.join(", "), `technologies listed for ${what}`);
        add(`${p}_dates`, `${P} dates`, dates, `dates of ${what}`);
        points(p, P, what, e);
      }
    } else if (s.key === "skills") {
      for (const e of es) for (const t of [...e.head.map(squash), ...e.bullets]) {
        const m = t.match(/^\s*([A-Za-z][A-Za-z0-9 &/+.\-]{0,39}?)\s*:\s*(.+)$/);
        if (m) add(`skills_${slug(m[1])}`, `Skills: ${squash(m[1])}`, m[2], `skills listed as "${squash(m[1])}"`);
        else { const k = next("skills"); add(`skills_${k}`, "Skills", t); }
      }
    } else {
      // Any other section: one field per bullet or line.
      const Title = s.title[0].toUpperCase() + s.title.slice(1);
      const vals = es.flatMap((e) => [...e.head.map((h) => squash(h).replace(new RegExp(`^${SPAN}\\s+(?=\\S)`, "i"), "")), ...e.bullets]);
      for (const v of vals) {
        const k = next(s.key);
        add(k === 1 && vals.length === 1 ? s.key : `${s.key}_${k}`, vals.length === 1 ? Title : `${Title} ${k}`, v, vals.length === 1 ? `the "${s.title}" section` : `item ${k} in the "${s.title}" section`);
      }
    }
  }
  return out.slice(0, limit);
}
