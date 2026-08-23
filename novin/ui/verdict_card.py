from __future__ import annotations

from typing import Any
from rich.console import Console
from rich.panel import Panel
from rich.table import Table
from rich.text import Text

from novin.client.card_action import public_card_action


def format_verdict_text(data: dict[str, Any], wall_time_ms: float | None = None) -> str:
    """Plain-text verdict for the local terminal UI."""
    event = data.get("event", {}) or {}
    response = data.get("response", {}) or {}
    reasoning = data.get("reasoning", {}) or {}
    quality = data.get("quality", {}) or {}
    action = public_card_action(response, fallback=str(data.get("action") or ""))
    threat = (response.get("threat_level") or data.get("threat_level") or "none").upper()
    summary = response.get("summary") or data.get("summary") or "No summary available."
    explanation = reasoning.get("explanation") or ""
    observations = reasoning.get("observations") or quality.get("observed_facts") or []
    incident_id = event.get("incident_id") or data.get("incident_id") or ""
    site_id = event.get("site_id") or ""
    stream_id = event.get("stream_id") or ""
    lines = [f"{action}  {threat}"]
    meta = "  ·  ".join(p for p in (site_id, stream_id, incident_id) if p)
    if wall_time_ms is not None:
        meta = (meta + "  ·  " if meta else "") + f"{wall_time_ms:.0f} ms"
    if meta:
        lines.append(meta)
    lines += ["", "SUMMARY", f"  {summary}"]
    if explanation:
        lines += ["", "REASONING", f"  {explanation}"]
    if observations:
        lines += ["", "OBSERVATIONS"]
        for obs in list(observations)[:6]:
            lines.append(f"  • {obs}")
    return "\n".join(lines)


def render_verdict_card(data: dict[str, Any], wall_time_ms: float | None = None) -> None:
    """Render canonical 5-section Novin AI verdict into a rich terminal card."""
    console = Console()

    event = data.get("event", {})
    response = data.get("response", {})
    reasoning = data.get("reasoning", {})
    quality = data.get("quality", {})
    delivery = data.get("delivery", {})

    action = public_card_action(response, fallback=str(data.get("action") or ""))
    threat_level = (response.get("threat_level") or data.get("threat_level") or "none").upper()
    summary = response.get("summary") or data.get("summary") or "No summary available."
    explanation = reasoning.get("explanation") or ""
    decision_basis = reasoning.get("decision_basis") or ""
    observations = reasoning.get("observations") or quality.get("observed_facts") or []

    incident_id = event.get("incident_id") or data.get("incident_id") or "UNKNOWN-INCIDENT"
    site_id = event.get("site_id") or "default-site"
    stream_id = event.get("stream_id") or "camera-01"
    card_url = event.get("links", {}).get("card") or ""
    trace_id = event.get("trace_id") or ""

    # Style by action
    if action == "ALERT":
        style_color = "red"
        badge = f"[bold white on red] ALERT [/bold white on red] [bold red]{threat_level}[/bold red]"
    elif action == "SUPPRESS":
        style_color = "green"
        badge = f"[bold white on green] SUPPRESS [/bold white on green] [bold green]{threat_level}[/bold green]"
    else:
        style_color = "green"
        badge = f"[bold white on green] SUPPRESS [/bold white on green] [bold green]{threat_level}[/bold green]"

    card_content = []

    # Header Row
    header_text = Text()
    header_text.append(f"Site: {site_id}  ·  Camera: {stream_id}", style="cyan")
    if wall_time_ms is not None:
        header_text.append(f"  ·  TTC: {wall_time_ms:.1f}ms", style="bold magenta")
    card_content.append(header_text)
    card_content.append(Text(""))

    # 1. Summary Headline
    card_content.append(Text("1. SUMMARY", style="bold underline " + style_color))
    card_content.append(Text(f"   {summary}", style="bold white"))
    card_content.append(Text(""))

    # 2. Analyst Reasoning
    if explanation:
        card_content.append(Text("2. REASONING EXPLANATION", style="bold underline cyan"))
        card_content.append(Text(f"   {explanation}", style="white"))
        card_content.append(Text(""))

    # 3. Grounded Observations
    if observations:
        card_content.append(Text("3. KEY OBSERVATIONS", style="bold underline yellow"))
        for obs in observations[:4]:
            card_content.append(Text(f"   • {obs}", style="dim white"))
        card_content.append(Text(""))

    # 4. Links & Traceability
    footer_table = Table.grid(padding=(0, 2))
    footer_table.add_column("Field", style="bold dim")
    footer_table.add_column("Value", style="dim")
    if trace_id:
        footer_table.add_row("Trace ID:", trace_id)
    if card_url:
        footer_table.add_row("Signed Card:", card_url)

    panel = Panel(
        Text("\n").join([c if isinstance(c, Text) else Text(str(c)) for c in card_content]) if not footer_table.rows else Panel.fit(
            "\n".join([str(c) for c in card_content]),
            title=f"{badge} · {incident_id}",
            border_style=style_color,
            subtitle=f"Trace: {trace_id[:16]}..." if trace_id else None,
        ),
        title=f"{badge} · {incident_id}",
        border_style=style_color,
        expand=False,
    )
    console.print(panel)
