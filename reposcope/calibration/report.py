"""Render a study as one self-contained HTML file.

No CDN, no build step, no external fonts — the plots are inline SVG generated
from the data. The point is that the report survives being emailed as an
attachment and still renders in five years.
"""

from __future__ import annotations

import html
from datetime import datetime, timezone

from reposcope.calibration.dataset import QuestionStudy, Study

CSS = """
:root{--bg:#fbfbf9;--fg:#1a1a17;--mut:#6b6b63;--line:#e0e0d8;--acc:#2f5d50;
--warn:#8a5a1f;--bad:#9b3232;--card:#fff}
@media(prefers-color-scheme:dark){:root:not([data-theme=light]){--bg:#15150f;
--fg:#eceae1;--mut:#9a988d;--line:#32322a;--card:#1e1e17}}
*{box-sizing:border-box}
body{margin:0;background:var(--bg);color:var(--fg);font:15px/1.6 ui-sans-serif,
system-ui,-apple-system,Segoe UI,Roboto,sans-serif}
.wrap{max-width:920px;margin:0 auto;padding:40px 22px 90px}
h1{font-size:1.9rem;margin:0 0 6px;letter-spacing:-.02em}
h2{font-size:1.15rem;margin:44px 0 12px;padding-bottom:7px;border-bottom:1px solid var(--line)}
h3{font-size:.95rem;margin:26px 0 8px;font-weight:600}
.sub{color:var(--mut);margin:0 0 28px;font-size:.9rem}
.card{background:var(--card);border:1px solid var(--line);border-radius:9px;
padding:18px 20px;margin:14px 0}
table{width:100%;border-collapse:collapse;font-size:.87rem}
th,td{text-align:left;padding:7px 9px;border-bottom:1px solid var(--line)}
th{color:var(--mut);font-weight:600;font-size:.76rem;text-transform:uppercase;
letter-spacing:.04em}
td.num,th.num{text-align:right;font-variant-numeric:tabular-nums}
.scroll{overflow-x:auto}
.kpi{display:flex;flex-wrap:wrap;gap:26px;margin:14px 0 4px}
.kpi div{min-width:110px}
.kpi b{display:block;font-size:1.45rem;font-variant-numeric:tabular-nums;letter-spacing:-.02em}
.kpi span{color:var(--mut);font-size:.76rem;text-transform:uppercase;letter-spacing:.04em}
.note{border-left:3px solid var(--warn);padding:9px 14px;margin:12px 0;
background:color-mix(in srgb,var(--warn) 7%,transparent);font-size:.87rem;border-radius:0 6px 6px 0}
.ok{border-left-color:var(--acc);background:color-mix(in srgb,var(--acc) 7%,transparent)}
.bad{border-left-color:var(--bad);background:color-mix(in srgb,var(--bad) 8%,transparent)}
figure{margin:16px 0}figcaption{color:var(--mut);font-size:.8rem;margin-top:6px}
svg{max-width:100%;height:auto}
code{font:.85em ui-monospace,SFMono-Regular,Menlo,monospace;background:var(--line);
padding:1px 5px;border-radius:4px}
footer{margin-top:60px;color:var(--mut);font-size:.8rem;border-top:1px solid var(--line);
padding-top:16px}
"""


def _e(text: object) -> str:
    return html.escape(str(text))


def _reliability_svg(study: QuestionStudy, w: int = 460, h: int = 300) -> str:
    pad = 42
    pw, ph = w - pad - 14, h - pad - 26

    def px(v: float) -> float:
        return pad + v * pw

    def py(v: float) -> float:
        return pad + (1 - v) * ph

    parts = [
        f'<svg viewBox="0 0 {w} {h}" xmlns="http://www.w3.org/2000/svg" '
        f'role="img" aria-label="Reliability diagram">',
        f'<line x1="{px(0)}" y1="{py(0)}" x2="{px(1)}" y2="{py(1)}" '
        'stroke="currentColor" stroke-dasharray="4 4" opacity=".35"/>',
    ]
    for g in (0.0, 0.25, 0.5, 0.75, 1.0):
        parts.append(
            f'<line x1="{px(0)}" y1="{py(g)}" x2="{px(1)}" y2="{py(g)}" '
            'stroke="currentColor" opacity=".1"/>'
            f'<text x="{pad - 7}" y="{py(g) + 4}" font-size="10" text-anchor="end" '
            f'fill="currentColor" opacity=".55">{g:.2f}</text>'
            f'<text x="{px(g)}" y="{h - 8}" font-size="10" text-anchor="middle" '
            f'fill="currentColor" opacity=".55">{g:.2f}</text>'
        )

    total = max(1, sum(b.count for b in study.calibration.bins))
    for b in study.calibration.bins:
        # Bar width encodes bin mass, so sparse bins can't masquerade as evidence.
        bw = max(4.0, (b.count / total) * pw * 0.9)
        x = px(b.mean_confidence) - bw / 2
        y = py(b.accuracy)
        colour = "var(--bad)" if abs(b.gap) > 0.1 else "var(--acc)"
        parts.append(
            f'<rect x="{x:.1f}" y="{y:.1f}" width="{bw:.1f}" '
            f'height="{(py(0) - y):.1f}" fill="{colour}" opacity=".22"/>'
            f'<circle cx="{px(b.mean_confidence):.1f}" cy="{y:.1f}" r="3.5" fill="{colour}">'
            f"<title>conf {b.mean_confidence:.3f} / acc {b.accuracy:.3f} / n={b.count}</title>"
            "</circle>"
        )

    parts.append(
        f'<text x="{pad + pw / 2}" y="{h - 22}" font-size="10.5" text-anchor="middle" '
        'fill="currentColor" opacity=".7">stated confidence</text>'
        f'<text x="13" y="{pad + ph / 2}" font-size="10.5" text-anchor="middle" '
        f'fill="currentColor" opacity=".7" transform="rotate(-90 13 {pad + ph / 2})">'
        "observed accuracy</text></svg>"
    )
    return "".join(parts)


def _risk_coverage_svg(study: QuestionStudy, w: int = 460, h: int = 300) -> str:
    pad = 46
    pw, ph = w - pad - 14, h - pad - 26
    pts = [p for p in study.curve if p.n_covered > 0]
    if not pts:
        return ""
    max_risk = max(0.05, max(p.selective_risk for p in pts))

    def px(v: float) -> float:
        return pad + v * pw

    def py(v: float) -> float:
        return pad + (1 - v / max_risk) * ph

    path = " ".join(
        f"{'M' if i == 0 else 'L'}{px(p.coverage):.1f},{py(p.selective_risk):.1f}"
        for i, p in enumerate(sorted(pts, key=lambda q: q.coverage))
    )
    chosen = study.choice.point
    parts = [
        f'<svg viewBox="0 0 {w} {h}" xmlns="http://www.w3.org/2000/svg" '
        'role="img" aria-label="Risk-coverage curve">'
    ]
    for g in (0.0, 0.25, 0.5, 0.75, 1.0):
        parts.append(
            f'<line x1="{px(0)}" y1="{pad + (1 - g) * ph}" x2="{px(1)}" '
            f'y2="{pad + (1 - g) * ph}" stroke="currentColor" opacity=".1"/>'
            f'<text x="{pad - 7}" y="{pad + (1 - g) * ph + 4}" font-size="10" '
            f'text-anchor="end" fill="currentColor" opacity=".55">'
            f"{g * max_risk * 100:.1f}%</text>"
            f'<text x="{px(g)}" y="{h - 8}" font-size="10" text-anchor="middle" '
            f'fill="currentColor" opacity=".55">{g * 100:.0f}%</text>'
        )
    parts.append(f'<path d="{path}" fill="none" stroke="var(--acc)" stroke-width="2"/>')
    if chosen.n_covered:
        parts.append(
            f'<circle cx="{px(chosen.coverage):.1f}" cy="{py(chosen.selective_risk):.1f}" '
            'r="5" fill="var(--bad)"><title>chosen threshold</title></circle>'
            f'<text x="{px(chosen.coverage):.1f}" y="{py(chosen.selective_risk) - 11:.1f}" '
            'font-size="10" text-anchor="middle" fill="var(--bad)">'
            f"t={chosen.threshold:.2f}</text>"
        )
    parts.append(
        f'<text x="{pad + pw / 2}" y="{h - 22}" font-size="10.5" text-anchor="middle" '
        'fill="currentColor" opacity=".7">coverage (share auto-accepted)</text>'
        f'<text x="13" y="{pad + ph / 2}" font-size="10.5" text-anchor="middle" '
        f'fill="currentColor" opacity=".7" transform="rotate(-90 13 {pad + ph / 2})">'
        "error rate on accepted</text></svg>"
    )
    return "".join(parts)


def _question_section(s: QuestionStudy) -> str:
    cal = s.calibration
    over = cal.overconfidence
    if abs(over) < 0.02:
        verdict = (
            f'<div class="note ok">Stated confidence tracks observed accuracy to within '
            f"{abs(over) * 100:.1f} points. On this task the number means what it says.</div>"
        )
    elif over > 0:
        verdict = (
            f'<div class="note bad">Overconfident by {over * 100:.1f} points: it claims '
            f"{cal.mean_confidence * 100:.1f}% and delivers {cal.accuracy.point * 100:.1f}%. "
            "Thresholds set from the stated number will over-automate.</div>"
        )
    else:
        verdict = (
            f'<div class="note">Underconfident by {abs(over) * 100:.1f} points. Safe, but '
            "you are deferring work a threshold on true accuracy would automate.</div>"
        )

    gap = ""
    if s.mean_confidence_gap is not None and abs(s.mean_confidence_gap) > 0.03:
        gap = (
            f'<div class="note">The reported <code>confidence</code> field sits '
            f"{s.mean_confidence_gap:+.3f} from the margin of the returned distribution. "
            "They are not the same signal — pick one and threshold on it consistently.</div>"
        )

    c = s.choice
    at2 = s.coverage_at_2pct
    at2_sentence = (
        f"To hold errors under 2% you can automate {at2.coverage * 100:.0f}% of files "
        f"at t={at2.threshold:.2f}."
        if at2
        else "Holding errors under 2% is not reachable on this sample."
    )

    rows = "".join(
        f"<tr><td class='num'>{b.lower:.2f}–{b.upper:.2f}</td>"
        f"<td class='num'>{b.count}</td><td class='num'>{b.mean_confidence:.3f}</td>"
        f"<td class='num'>{b.accuracy:.3f}</td><td class='num'>{b.gap:+.3f}</td></tr>"
        for b in cal.bins
    )

    return f"""
<h2>{_e(s.question)} &middot; {_e(s.provider)} <span style="color:var(--mut);
font-weight:400">({_e(s.answer_type)}, n={s.n})</span></h2>
<div class="kpi">
  <div><b>{cal.accuracy.point * 100:.1f}%</b><span>accuracy</span></div>
  <div><b>{cal.ece.point:.3f}</b><span>ECE</span></div>
  <div><b>{s.aurc:.3f}</b><span>AURC</span></div>
  <div><b>{cal.brier.point:.3f}</b><span>Brier</span></div>
  <div><b>{c.threshold:.2f}</b><span>chosen threshold</span></div>
</div>
{verdict}{gap}
<div class="card">
  <h3>Reliability</h3>
  <figure>{_reliability_svg(s)}
  <figcaption>Equal-mass bins. Bar width is bin population — a dot far off the
  diagonal on a narrow bar is a handful of files, not a finding. Points on the
  dashed line are perfectly calibrated.</figcaption></figure>
  <div class="kpi" style="font-size:.9rem">
    <div><b style="font-size:1rem">{cal.ece}</b><span>ECE, 95% CI</span></div>
    <div><b style="font-size:1rem">{cal.accuracy}</b><span>accuracy, 95% CI</span></div>
    <div><b style="font-size:1rem">{cal.mce:.3f}</b><span>max bin gap</span></div>
  </div>
</div>
<div class="card">
  <h3>Where to set the threshold</h3>
  <figure>{_risk_coverage_svg(s)}
  <figcaption>Each point is one threshold: how much gets auto-accepted, and how
  often that is wrong. The marked point minimises expected cost under the model
  below.</figcaption></figure>
  <p style="font-size:.9rem">At <code>t={c.threshold:.2f}</code> the model handles
  <b>{c.point.coverage * 100:.0f}%</b> of files automatically with
  <b>{c.point.selective_risk * 100:.1f}%</b> errors among those, deferring
  {c.point.n_deferred} for review. That is
  <b>{c.savings_vs_manual * 100:.0f}%</b> cheaper than reviewing everything, and
  {"cheaper" if c.beats_full_automation else "<b>more expensive</b>"} than
  automating everything.<br>
  {at2_sentence}</p>
  <p class="sub" style="margin:8px 0 0">The threshold is fitted on this sample.
  Hold out a split before shipping it, or expect it to underperform in
  production.</p>
</div>
<div class="card scroll">
  <h3>Bins</h3>
  <table><thead><tr><th class="num">range</th><th class="num">n</th>
  <th class="num">mean conf</th><th class="num">accuracy</th>
  <th class="num">gap</th></tr></thead><tbody>{rows}</tbody></table>
</div>"""


def render(study: Study, title: str = "Jev Calibration Lab") -> str:
    warnings = "".join(f'<div class="note">{_e(w)}</div>' for w in study.warnings)

    comparisons = ""
    for question, mc, a, b in study.comparisons:
        comparisons += f"""
<div class="card">
  <h3>{_e(question)}</h3>
  <div class="scroll"><table>
    <thead><tr><th></th><th class="num">accuracy</th><th class="num">mean latency</th>
    <th class="num">p95 latency</th><th class="num">cost / 1k</th>
    <th class="num">cost / correct</th></tr></thead>
    <tbody>
      <tr><td><b>{_e(a.name)}</b></td><td class="num">{a.accuracy * 100:.1f}%</td>
      <td class="num">{a.mean_latency_ms:.0f} ms</td>
      <td class="num">{a.p95_latency_ms:.0f} ms</td>
      <td class="num">${a.cost_per_1k:.3f}</td>
      <td class="num">${a.cost_per_correct:.5f}</td></tr>
      <tr><td><b>{_e(b.name)}</b></td><td class="num">{b.accuracy * 100:.1f}%</td>
      <td class="num">{b.mean_latency_ms:.0f} ms</td>
      <td class="num">{b.p95_latency_ms:.0f} ms</td>
      <td class="num">${b.cost_per_1k:.3f}</td>
      <td class="num">${b.cost_per_correct:.5f}</td></tr>
    </tbody></table></div>
  <div class="note {'ok' if mc.significant else ''}">{_e(mc.verdict(a.name, b.name))}
  Agreed on {mc.both + mc.neither} of {a.n} items
  ({mc.a_only} only {_e(a.name)}, {mc.b_only} only {_e(b.name)}).</div>
</div>"""

    cm = study.cost_model
    body = "".join(_question_section(s) for s in study.per_question)
    now = datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M UTC")

    return f"""<!doctype html>
<html lang="en"><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width,initial-scale=1,viewport-fit=cover">
<title>{_e(title)}</title><style>{CSS}</style></head>
<body><div class="wrap">
<h1>{_e(title)}</h1>
<p class="sub">Is the confidence score worth thresholding on? Measured on
{sum(s.n for s in study.per_question)} hand-labelled file classifications from
real repositories. Generated {now} from <code>{_e(study.dataset)}</code>.</p>
{warnings}
<div class="card">
<h3>How to read this</h3>
<p style="font-size:.9rem;margin:0">Two independent properties are measured.
<b>Calibration</b> (ECE, reliability diagram) asks whether a stated 0.9 really
means 90%. <b>Discrimination</b> (AURC, risk-coverage) asks whether the
confidence ordering separates right answers from wrong ones. A model can have
either without the other, and routing needs both: discrimination decides
whether a threshold helps at all, calibration decides where to put it without
re-measuring.</p>
</div>
{body}
<h2>Head to head</h2>
<p class="sub">Paired on identical inputs, so McNemar's test applies. Accuracy
differences on small eval sets are usually noise; the discordant count is the
number to look at.</p>
{comparisons or '<div class="note">No paired items in this dataset.</div>'}
<h2>Cost model</h2>
<div class="card"><p style="margin:0;font-size:.9rem">One automated error costs
<b>{cm.cost_error:g}</b>; one human review costs <b>{cm.cost_review:g}</b>;
reviewers are assumed <b>{cm.review_accuracy * 100:.0f}%</b> accurate. Only the
ratio matters. Every threshold above is a consequence of these three numbers —
change them and re-run rather than arguing about the default.</p></div>
<footer>Calibration Lab &middot; part of RepoScope. Thresholds are fitted on the
evaluation sample and are optimistic by construction. Bootstrap intervals are
percentile intervals over 1,000 resamples.</footer>
</div></body></html>"""
