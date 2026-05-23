"""Static HTML renderer for Phase 0.

Two-column parchment view: each event is one row with both agents' takes
side by side. Pure Python — no templating engine — to keep deps minimal.

Language: pass `language="zh"` or `"en"` to render that language's
chronicles. Headers / labels respect the current i18n locale via the
`_()` helper. If both languages are stored and you want a side-by-side
EN/中文 page, render twice into two HTML files.
"""

from __future__ import annotations

import html
from collections.abc import Iterable
from pathlib import Path

from ..i18n import _, set_locale
from ..schema import ChronicleEvent
from ..storage import Store

PAGE_CSS = """
:root {
  --parchment: #f3e7c9;
  --parchment-dark: #e6d3a3;
  --ink: #2b1d10;
  --ink-soft: #5b4326;
  --rule: #b69963;
  --accent: #7a1f1f;
}
* { box-sizing: border-box; }
body {
  margin: 0;
  font-family: 'Cormorant Garamond', 'EB Garamond', 'Noto Serif SC', 'Source Han Serif SC', 'Georgia', serif;
  background: var(--parchment);
  color: var(--ink);
  line-height: 1.7;
}
header {
  padding: 3rem 2rem 1rem;
  border-bottom: 1px solid var(--rule);
  text-align: center;
}
header h1 {
  font-size: 2.4rem;
  font-weight: 600;
  margin: 0;
  letter-spacing: 0.02em;
}
header .subtitle {
  color: var(--ink-soft);
  font-style: italic;
  margin-top: 0.3rem;
}
header .stats {
  margin-top: 0.8rem;
  font-size: 0.85rem;
  color: var(--ink-soft);
}
main {
  max-width: 1200px;
  margin: 0 auto;
  padding: 2rem;
}
.event {
  margin: 2.5rem 0;
  padding: 1.5rem;
  background: rgba(255,255,255,0.18);
  border: 1px solid var(--rule);
  border-radius: 4px;
}
.event-meta {
  font-size: 0.85rem;
  color: var(--ink-soft);
  border-bottom: 1px solid var(--rule);
  padding-bottom: 0.6rem;
  margin-bottom: 1rem;
  display: flex;
  justify-content: space-between;
  flex-wrap: wrap;
  gap: 0.5rem;
}
.event-meta .year {
  font-weight: 600;
  color: var(--accent);
  font-size: 1rem;
}
.columns {
  display: grid;
  grid-template-columns: 1fr 1fr;
  gap: 1.5rem;
}
@media (max-width: 760px) {
  .columns { grid-template-columns: 1fr; }
}
.col {
  padding: 0.5rem 0.2rem;
}
.col h3 {
  margin: 0 0 0.2rem;
  font-size: 0.78rem;
  letter-spacing: 0.18em;
  text-transform: uppercase;
  color: var(--ink-soft);
  font-weight: 600;
}
.col h2 {
  margin: 0.3rem 0 0.8rem;
  font-size: 1.2rem;
  color: var(--accent);
  font-style: italic;
}
.col .body p {
  margin: 0 0 0.6em;
}
.col.empty .body {
  color: #999;
  font-style: italic;
}
footer {
  text-align: center;
  padding: 2rem;
  color: var(--ink-soft);
  font-size: 0.8rem;
  border-top: 1px solid var(--rule);
}
"""


PAGE_TEMPLATE = """<!doctype html>
<html lang="{html_lang}">
<head>
<meta charset="utf-8" />
<title>{title}</title>
<meta name="viewport" content="width=device-width, initial-scale=1" />
<style>{css}</style>
</head>
<body>
<header>
  <h1>{title}</h1>
  <div class="subtitle">{subtitle}</div>
  <div class="stats">{stats}</div>
</header>
<main>
{events_html}
</main>
<footer>
  {footer}
</footer>
</body>
</html>
"""


def render_html(
    store: Store,
    output_path: str | Path,
    *,
    title: str | None = None,
    subtitle: str | None = None,
    language: str = "en",
    events: Iterable[ChronicleEvent] | None = None,
) -> Path:
    """Render chronicles into a static HTML page.

    `language` selects which stored chronicles to show. Page chrome
    (headers, labels, footer) is also rendered in that language.
    """
    # Headers + labels follow the chronicle language.
    set_locale("zh" if language == "zh" else "en")

    title = title or _("html.title.default")
    subtitle = subtitle or _("html.subtitle.default")

    events_list = list(events) if events is not None else store.list_events()
    parts: list[str] = []
    total_cost = store.total_cost()
    for event in events_list:
        rows = store.list_chronicles_for_event(event.event_id, language=language)
        by_agent = {r["agent"]: r for r in rows}
        primary = event.primary_actors[0]
        meta = (
            '<div class="event-meta">'
            f'<span><span class="year">AD {event.year}</span> · {html.escape(event.type.value)}</span>'
            f"<span>{html.escape(primary.name)}"
            + (f' · {html.escape(primary.dynasty)}' if primary.dynasty else "")
            + "</span>"
            "</div>"
        )
        cols = []
        for agent_name, label_key in (
            ("court_historian", "html.col.court_historian"),
            ("peasant_ballad", "html.col.peasant_ballad"),
        ):
            row = by_agent.get(agent_name)
            label = _(label_key)
            if row:
                cols.append(_col_html(label, row["title"], row["body"]))
            else:
                cols.append(_col_empty_html(label))
        parts.append(
            f'<section class="event">{meta}<div class="columns">{"".join(cols)}</div></section>'
        )
    stats = _("html.stats.line", n=len(events_list), cost=f"{total_cost:.4f}")
    out = Path(output_path)
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(
        PAGE_TEMPLATE.format(
            html_lang="zh-CN" if language == "zh" else "en",
            title=html.escape(title),
            subtitle=html.escape(subtitle),
            stats=html.escape(stats),
            css=PAGE_CSS,
            events_html="\n".join(parts) if parts else f"<p><em>{html.escape(_('html.no_events'))}</em></p>",
            footer=html.escape(_("html.footer")),
        ),
        encoding="utf-8",
    )
    return out


def _col_html(label: str, title: str, body: str) -> str:
    paragraphs = "".join(
        f"<p>{html.escape(p.strip())}</p>" for p in body.split("\n\n") if p.strip()
    ) or f"<p>{html.escape(body)}</p>"
    return (
        f'<div class="col">'
        f"<h3>{html.escape(label)}</h3>"
        f"<h2>{html.escape(title)}</h2>"
        f'<div class="body">{paragraphs}</div>'
        f"</div>"
    )


def _col_empty_html(label: str) -> str:
    return (
        f'<div class="col empty">'
        f"<h3>{html.escape(label)}</h3>"
        f'<div class="body">{html.escape(_("html.col.empty"))}</div>'
        f"</div>"
    )
