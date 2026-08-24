from __future__ import annotations

import json
import os
import sys
from getpass import getpass
from pathlib import Path

import click
from rich.console import Console
from rich.table import Table

from novin import __version__
from novin.client.api_client import NovinClient
from novin.client import session as cli_session
from novin.install import update_local_install
from novin.ui.labels import ENV_HELP as _ENV_HELP
from novin.ui.verdict_card import render_verdict_card

console = Console()


def _emit_verdict(verdict: dict, *, out_format: str, wall_ms: float | None = None) -> None:
    if out_format == "json":
        sys.stdout.write(json.dumps(verdict) + "\n")
        return
    render_verdict_card(verdict, wall_time_ms=wall_ms)


def _env_api_key() -> str:
    return (os.environ.get("NOVIN_API_KEY") or "").strip()


def _client_from_session(
    *,
    api_url: str | None = None,
    api_key: str | None = None,
    brand_id: str | None = None,
) -> NovinClient:
    saved = cli_session.load_session() or {}
    return NovinClient(
        api_url=api_url
        or os.environ.get("NOVIN_API_URL")
        or saved.get("api_url")
        or cli_session.default_api_url(),
        api_key=api_key or _env_api_key() or saved.get("api_key") or "",
        brand_id=brand_id
        or os.environ.get("NOVIN_BRAND_ID")
        or saved.get("brand_id")
        or cli_session.saved_brand_id(),
    )


def prompt_line(message: str) -> str:
    console.print(message, end="")
    try:
        return input().strip()
    except (EOFError, KeyboardInterrupt):
        console.print()
        sys.exit(1)


def _login_interactive(*, first_time: bool, api_url: str, brand_id: str | None) -> NovinClient:
    console.print()
    if first_time:
        console.print("[bold]Welcome to Novin.[/bold]")
        console.print("Paste the [cyan]master key[/cyan] Novin gave you.")
        console.print("We'll create your brand and give you an API key for sending events.")
        prompt = "Master key: "
    else:
        brand = (brand_id or cli_session.saved_brand_id()).strip() or "default"
        console.print("[bold]Welcome back.[/bold]")
        console.print(f"Paste the [cyan]API key[/cyan] for [bold]{brand}[/bold].")
        prompt = "API key: "
    console.print()
    try:
        key = getpass(prompt).strip()
    except (EOFError, KeyboardInterrupt):
        console.print()
        sys.exit(1)
    if not key:
        console.print("[red]No key entered.[/red]")
        sys.exit(1)
    guessed = (brand_id or "").strip()
    if not guessed and not first_time:
        guessed = cli_session.saved_brand_id()
    client = NovinClient(api_url=api_url, api_key=key, brand_id=guessed or "default")
    kind_found, data = client.identify_key()
    if kind_found == "master":
        name = prompt_line("Brand name: ")
        if not name:
            console.print("[red]Brand name is required.[/red]")
            sys.exit(1)
        created = client.create_brand(name)
        brand = str(created.get("brand_id") or "")
        brand_name = str(created.get("brand_name") or name)
        api_key = str(created.get("api_key") or "")
        if not brand or not api_key:
            console.print("[red]Could not create the brand.[/red]")
            sys.exit(1)
        client = NovinClient(api_url=api_url, api_key=api_key, brand_id=brand)
        cli_session.save_session(
            api_url=api_url,
            api_key=api_key,
            brand_id=brand,
            kind="brand",
            brand_name=brand_name,
        )
        console.print()
        console.print(f"[green]Brand ready:[/green] [bold]{brand_name}[/bold]  ({brand})")
        console.print("Your [cyan]API key[/cyan] — save it. Use it to sign in and to send events:")
        console.print(f"  [bold]{api_key}[/bold]")
        console.print("[dim]Novin will not show this key again. This machine is signed in with it.[/dim]")
        return client
    if kind_found == "brand":
        brand = str(data.get("brand_id") or brand_id or client.brand_id)
        brand_name = str(data.get("brand_name") or brand)
        client.brand_id = brand
        cli_session.save_session(
            api_url=api_url,
            api_key=key,
            brand_id=brand,
            kind="brand",
            brand_name=brand_name,
        )
        console.print(f"[green]Signed in[/green] as [bold]{brand_name}[/bold].")
        return client
    console.print("[red]Could not sign in:[/red] that key was not accepted")
    sys.exit(1)


def ensure_logged_in(
    *,
    api_url: str | None,
    api_key: str | None,
    brand_id: str | None,
) -> NovinClient:
    url = api_url or os.environ.get("NOVIN_API_URL") or cli_session.default_api_url()
    flag_key = (api_key or _env_api_key() or "").strip()
    if flag_key:
        client = _client_from_session(api_url=url, api_key=flag_key, brand_id=brand_id)
        kind_found, data = client.identify_key()
        if kind_found != "brand":
            console.print("[red]Key was not accepted.[/red] Use your brand API key, not the master key.")
            sys.exit(1)
        if data.get("brand_id"):
            client.brand_id = str(data["brand_id"])
        cli_session.save_session(
            api_url=client.api_url,
            api_key=client.api_key,
            brand_id=client.brand_id,
            kind="brand",
            brand_name=str(data.get("brand_name") or client.brand_id),
        )
        return client
    saved = cli_session.load_session()
    if saved and saved.get("api_key"):
        return _client_from_session(api_url=url, brand_id=brand_id)
    return _login_interactive(
        first_time=not cli_session.has_brand_account(),
        api_url=url,
        brand_id=brand_id,
    )


def run_tui(client: NovinClient) -> None:
    """Open the local terminal UI. Textual is imported only when launched."""
    from novin.ui.app import run_tui as launch

    launch(client)


def _require_client(ctx: click.Context) -> NovinClient:
    ctx.ensure_object(dict)
    client = ctx.obj.get("client")
    if client is not None:
        return client
    client = ensure_logged_in(
        api_url=ctx.obj.get("api_url"),
        api_key=ctx.obj.get("api_key"),
        brand_id=ctx.obj.get("brand_id"),
    )
    ctx.obj["client"] = client
    return client


class _NovinGroup(click.Group):
    def list_commands(self, ctx: click.Context) -> list[str]:
        return list(self.commands)


@click.group(
    name="novin",
    cls=_NovinGroup,
    invoke_without_command=True,
    context_settings={"help_option_names": ["-h", "--help"]},
)
@click.version_option(__version__, prog_name="novin")
@click.option("--api-url", default=None, help="Novin API URL")
@click.option("--api-key", default=None, help="Key (skips the login prompt)")
@click.option("--brand-id", default=None, help="Brand id")
@click.pass_context
def cli(ctx: click.Context, api_url: str | None, api_key: str | None, brand_id: str | None):
    """Open the Novin terminal UI on this machine.

    Run `novin` with no arguments. First time: master key, then a brand name.
    We generate your API key. After that, this machine stays signed in.
    """
    ctx.ensure_object(dict)
    ctx.obj["api_url"] = api_url
    ctx.obj["api_key"] = api_key
    ctx.obj["brand_id"] = brand_id
    ctx.obj["client"] = None
    if ctx.invoked_subcommand is None:
        client = ensure_logged_in(api_url=api_url, api_key=api_key, brand_id=brand_id)
        ctx.obj["client"] = client
        run_tui(client)


@cli.command("login")
@click.pass_context
def login_cmd(ctx: click.Context):
    """Sign in (master key first time, API key after)."""
    url = ctx.obj.get("api_url") or os.environ.get("NOVIN_API_URL") or cli_session.default_api_url()
    client = _login_interactive(
        first_time=not cli_session.has_brand_account(),
        api_url=url,
        brand_id=ctx.obj.get("brand_id"),
    )
    ctx.obj["client"] = client


@cli.command("logout")
def logout_cmd():
    """Sign out (next time use your API key)."""
    cli_session.clear_session()
    if cli_session.has_brand_account():
        console.print(
            f"[green]Signed out.[/green] Run [bold]novin[/bold] and paste the "
            f"API key for brand [bold]{cli_session.saved_brand_id()}[/bold]."
        )
    else:
        console.print("[green]Signed out.[/green] Run [bold]novin[/bold] and paste your master key.")


@cli.command("update")
def update_cmd():
    """Install the latest terminal on this machine. Does not run unless you ask."""
    console.print("Updating the local Novin terminal...")
    try:
        result = update_local_install()
    except Exception as exc:
        console.print(f"[red]Could not update:[/red] {exc}")
        raise SystemExit(1) from exc
    console.print("[green]This machine now has the latest terminal.[/green]")
    console.print(f"  version {result['version']}")
    if not result["wrapper_written"]:
        console.print("[dim]Your existing novin command was left as-is.[/dim]")
    console.print("Run [bold]novin[/bold].")


# ─────────────────────────────────────────────────────────────────────────────
# novin setup
# ─────────────────────────────────────────────────────────────────────────────

@cli.group()
def setup():
    """Tenant provisioning and connectivity diagnostics."""
    pass


@setup.command("check")
@click.pass_context
def setup_check(ctx: click.Context):
    """Check Novin can be reached from this machine."""
    client = _require_client(ctx)
    try:
        res = client.ping()
        ok = (res.get("health") or {}).get("status") == "ok" and (res.get("ready") or {}).get("status") == "ready"
    except Exception:
        ok = False
    if ok:
        console.print(f"[green]Novin is reachable.[/green]  brand [bold]{client.brand_id}[/bold]")
    else:
        console.print("[red]Could not reach Novin from this machine.[/red]")


@setup.command("site")
@click.argument("site_id")
@click.option("--name", default="", help="Human-readable site name")
@click.option("--hours", default=None, help="Expected operating hours (optional; omit if none)")
@click.option("--camera", "cameras", multiple=True, help="Camera id this site owns (repeatable)")
@click.option("--environment", default="", help=_ENV_HELP)
@click.option("--brief", "--context", "brief", default="", help="Natural-language site context. What is normal here and what to watch for.")
@click.pass_context
def setup_site(ctx: click.Context, site_id: str, name: str, hours: str | None, cameras: tuple[str, ...], environment: str, brief: str):
    """Create or update a site (same fields as the terminal: id, name, world, hours, cameras, context)."""
    client = _require_client(ctx)
    console.print(f"[cyan]Provisioning site[/cyan] [bold]{site_id}[/bold]...")
    res = client.setup_site(
        site_id=site_id,
        site_name=name or site_id,
        expected_hours=hours,
        environment=environment or None,
        brief=brief or None,
        cameras=list(cameras) if cameras else None,
    )
    console.print(f"[bold green]✓ Site Registered:[/bold green] {res.get('site_id')} (Brand: {res.get('brand_id')})")
    if res.get("message"):
        console.print(f"[dim]{res.get('message')}[/dim]")


@setup.command("delete-site")
@click.argument("site_id")
@click.pass_context
def setup_delete_site(ctx: click.Context, site_id: str):
    """Delete one site for this brand."""
    client = _require_client(ctx)
    res = client.delete_site(site_id)
    console.print(f"[green]Deleted[/green] {res.get('site_id')} for brand {res.get('brand_id')}")


@setup.command("restore-site")
@click.argument("site_id")
@click.pass_context
def setup_restore_site(ctx: click.Context, site_id: str):
    """Restore a soft-deleted site for this brand."""
    client = _require_client(ctx)
    res = client.restore_site(site_id)
    console.print(f"[green]Restored[/green] {res.get('site_id') or site_id}")


@setup.command("wipe-sites")
@click.option("--yes", is_flag=True, help="Confirm wipe of every site for this brand")
@click.pass_context
def setup_wipe_sites(ctx: click.Context, yes: bool):
    """Delete every site for this brand."""
    if not yes:
        console.print("Pass --yes to delete every site for this brand.")
        raise SystemExit(1)
    client = _require_client(ctx)
    res = client.delete_all_sites()
    console.print(
        f"[green]Wiped[/green] {res.get('count', 0)} sites for brand {res.get('brand_id')}"
    )


@setup.command("brand")
@click.argument("brand_id", required=False, default="")
@click.option("--webhook-url", default=None, help="Standing webhook URL for alerts")
@click.option("--push-action", "push_actions", multiple=True, help="Actions that trigger webhook push (alert or suppress)")
@click.pass_context
def setup_brand(ctx: click.Context, brand_id: str, webhook_url: str | None, push_actions: tuple[str, ...]):
    """Configure tenant brand preferences, delivery targets, and webhooks."""
    client = _require_client(ctx)
    target_brand = brand_id or client.brand_id
    # Create or update client with target brand
    if target_brand != client.brand_id:
        client = NovinClient(api_url=client.api_url, api_key=client.api_key, brand_id=target_brand)
    
    console.print(f"[cyan]Configuring brand[/cyan] [bold]{target_brand}[/bold]...")
    mapped = []
    for action in push_actions:
        mapped.append("alert" if str(action).lower() == "review" else action)
    res: dict = {}
    if webhook_url:
        res = client.test_brand_webhook(webhook_url)
    if mapped:
        res = client.setup_brand(push_actions=mapped)
    if not webhook_url and not mapped:
        res = client.get_brand_setup()
    console.print(f"[bold green]✓ Brand Configured:[/bold green] {target_brand}")
    if res.get("webhook_url"):
        console.print(f"  [dim]Webhook URL:[/dim] {res.get('webhook_url')}")
    if res.get("push_actions"):
        console.print(f"  [dim]Push Actions:[/dim] {', '.join(res.get('push_actions', []))}")


# ─────────────────────────────────────────────────────────────────────────────
# novin destinations
# ─────────────────────────────────────────────────────────────────────────────

@cli.group()
def destinations():
    """Where alerts go: Slack or an API, for the whole brand or one site."""
    pass


def _dest_rows(row: dict) -> list[dict]:
    dests = row.get("destinations")
    if isinstance(dests, list) and dests:
        return [item for item in dests if isinstance(item, dict)]
    url = str(row.get("webhook_url") or "").strip()
    if url:
        return [{"url": url, "kind": "api", "auth_attached": bool(row.get("webhook_verified"))}]
    return []


def _kind_name(kind: str | None) -> str:
    key = str(kind or "json").strip().lower()
    if key in {"json", "api"}:
        return "JSON API"
    if key == "slack":
        return "Slack message"
    if key == "slack_api":
        return "Slack API"
    if key == "teams":
        return "Teams card"
    if key == "discord":
        return "Discord message"
    return key or "JSON API"


def _print_destinations(label: str, row: dict, *, covers: str) -> None:
    dests = _dest_rows(row)
    console.print(f"[bold]{label}[/bold]  [dim]{covers}[/dim]")
    if not dests:
        console.print("    [dim]no URLs[/dim]")
        return
    for item in dests:
        kind = _kind_name(item.get("kind"))
        if item.get("auth_attached"):
            auth = "API key attached — sent on every alert"
        elif str(item.get("kind") or "") in {"slack", "teams", "discord", "slack_api"}:
            auth = "secret is in the URL"
        else:
            auth = "no key"
        console.print(f"    [cyan]{kind}[/cyan]  {item.get('url')}")
        console.print(f"      [dim]{auth}[/dim]")


@destinations.command("list")
@click.pass_context
def destinations_list(ctx: click.Context):
    """Show where alerts go for this brand and each site."""
    client = _require_client(ctx)
    brand = client.get_brand_setup()
    console.print(f"[bold]Delivery[/bold]  brand [cyan]{client.brand_id}[/cyan]")
    console.print(
        "[dim]When Novin alerts, it POSTs to matching URLs.\n"
        "Brand URLs run for every site. A site's URLs run only for that site — never another site.[/dim]"
    )
    console.print()
    _print_destinations("brand", brand, covers="alerts from every site")
    push = brand.get("push_actions") or []
    if "suppress" in push:
        console.print("  [dim]when:[/dim] alerts and all-clears")
    else:
        console.print("  [dim]when:[/dim] alerts only — quiet scenes stay in Incidents")
    sites = client.list_sites()
    if not sites:
        console.print()
        console.print("[dim]No sites yet. Add one, then you can give it its own URLs.[/dim]")
        return
    console.print()
    for row in sites:
        sid = str(row.get("site_id") or "")
        name = str(row.get("site_name") or sid)
        label = sid if name == sid else f"{name} ({sid})"
        _print_destinations(label, row, covers="this site only")


@destinations.command("add")
@click.option("--url", "webhook_url", required=True, help="Slack incoming webhook, or any HTTPS API that should receive the verdict")
@click.option("--site", "site_id", default="", help="Site id. Omit to send alerts from every site (brand).")
@click.option("--key", "api_key", default="", help="If this is a private API, the key Novin sends on every alert. Slack webhooks do not need this.")
@click.option("--header", "auth_header", default="", help="How to send the key: Authorization (default) or X-API-Key")
@click.option("--kind", default="auto", help="auto (from URL), slack, or api (JSON verdict)")
@click.pass_context
def destinations_add(
    ctx: click.Context,
    webhook_url: str,
    site_id: str,
    api_key: str,
    auth_header: str,
    kind: str,
):
    """Add a URL that receives alerts. Slack is detected from the URL. APIs can carry a key."""
    client = _require_client(ctx)
    res = client.add_destination(
        webhook_url,
        site_id=site_id or None,
        kind=None if kind in {"", "auto"} else kind,
        api_key=api_key or None,
        auth_header=auth_header or None,
    )
    scope = f"site {site_id} only" if site_id else "every site"
    console.print(f"[green]This URL now receives alerts for {scope}.[/green]")
    dests = res.get("destinations") or []
    for item in dests:
        console.print(f"  {_kind_name(item.get('kind'))}  {item.get('url')}")


@destinations.command("set")
@click.option("--url", "webhook_url", required=True, help="Slack webhook or HTTPS API URL")
@click.option("--site", "site_id", default="", help="Site id. Omit for the brand default.")
@click.option("--key", "api_key", default="", help="API key sent on every push")
@click.pass_context
def destinations_set(ctx: click.Context, webhook_url: str, site_id: str, api_key: str):
    """Add a URL that receives alerts (same as destinations add)."""
    client = _require_client(ctx)
    client.add_destination(
        webhook_url,
        site_id=site_id or None,
        api_key=api_key or None,
    )
    scope = f"site {site_id} only" if site_id else "every site"
    console.print(f"[green]This URL now receives alerts for {scope}.[/green]")


@destinations.command("clear")
@click.option("--site", "site_id", default="", help="Site id. Omit to clear the brand default.")
@click.option("--url", "webhook_url", default="", help="Remove one URL. Omit to remove all for this scope.")
@click.pass_context
def destinations_clear(ctx: click.Context, site_id: str, webhook_url: str):
    """Stop sending alerts to one URL, or to every URL for the brand or a site."""
    client = _require_client(ctx)
    if webhook_url:
        client.remove_destination(webhook_url, site_id=site_id or None)
        console.print("[green]That URL will no longer receive alerts.[/green]")
        return
    if site_id:
        client.clear_site_webhook(site_id)
        console.print(
            f"[green]Cleared[/green] extra URLs for site [bold]{site_id}[/bold]. "
            "Brand URLs still fire."
        )
        return
    client.clear_brand_webhook()
    console.print(
        f"[green]Cleared[/green] brand URLs for [bold]{client.brand_id}[/bold]. "
        "Sites can still have their own."
    )


# ─────────────────────────────────────────────────────────────────────────────
# novin ingest
# ─────────────────────────────────────────────────────────────────────────────

@cli.group()
def ingest():
    """Media ingestion and AI inference commands."""
    pass


def _site_and_camera(client: NovinClient, site_id: str, camera_id: str) -> tuple[str, str]:
    """Use the saved site and its first camera so sending an event is one command."""
    cfg = client._get_active_site_config()
    sites = cfg.get("sites") or {}
    sid = (site_id or "").strip() or str(cfg.get("active_site_id") or "")
    if not sid and len(sites) == 1:
        sid = str(next(iter(sites)))
    if not sid:
        console.print("[red]Create a site first.[/red] Run [bold]novin[/bold] and add one on Sites.")
        raise SystemExit(1)
    cached = sites.get(sid) if isinstance(sites, dict) else {}
    cams: list[str] = []
    if isinstance(cached, dict):
        raw = cached.get("cameras") or []
        if isinstance(raw, list):
            cams = [str(item).strip() for item in raw if str(item).strip()]
        else:
            cams = [part.strip() for part in str(raw).split(",") if part.strip()]
    cam = (camera_id or "").strip() or (cams[0] if cams else "")
    if not cam:
        console.print("[red]Add cameras on the site, or pass --camera-id.[/red]")
        raise SystemExit(1)
    return sid, cam


@ingest.command("image")
@click.argument("image_path", type=str)
@click.option("--site-id", default="", help="Site. Defaults to the one on this machine.")
@click.option("--camera-id", default="", help="Camera. Defaults to the site's first camera.")
@click.option("--format", "out_format", type=click.Choice(["card", "json"]), default="card")
@click.pass_context
def ingest_image(ctx: click.Context, image_path: str, site_id: str, camera_id: str, out_format: str):
    """Ingest one image (file path or URL) and show the verdict."""
    client = _require_client(ctx)
    target_site_id, camera_id = _site_and_camera(client, site_id, camera_id)
    name_label = image_path if image_path.startswith(("http://", "https://")) else Path(image_path).name
    if out_format != "json":
        console.print(f"[dim]Sending {name_label} from {target_site_id}/{camera_id}...[/dim]")
    try:
        verdict, wall_ms = client.ingest_image(
            image_path_or_b64=image_path,
            site_id=target_site_id,
            camera_id=camera_id,
        )
        _emit_verdict(verdict, out_format=out_format, wall_ms=wall_ms)
    except Exception as exc:
        console.print(f"[bold red]Ingestion failed:[/bold red] {exc}")
        sys.exit(1)


@ingest.command("burst")
@click.argument("image_paths", nargs=-1, required=True, type=str)
@click.option("--site-id", default="", help="Site identifier (defaults to active site)")
@click.option("--camera-id", default="", help="Camera. Defaults to the site's first camera.")
@click.option("--format", "out_format", type=click.Choice(["card", "json"]), default="card")
@click.pass_context
def ingest_burst(ctx: click.Context, image_paths: tuple[str, ...], site_id: str, camera_id: str, out_format: str):
    """Submit a multi-frame burst (files or URLs) and poll until the verdict."""
    client = _require_client(ctx)
    target_site_id, camera_id = _site_and_camera(client, site_id, camera_id)
    if out_format != "json":
        console.print(f"[dim]Sending {len(image_paths)} frames from {target_site_id}/{camera_id}...[/dim]")
    try:
        verdict, submit_ms, total_ms = client.ingest_burst_and_poll(
            image_paths=list(image_paths),
            site_id=target_site_id,
            camera_id=camera_id,
        )
        if out_format != "json":
            console.print(f"[dim]Submit Ack: {submit_ms}ms  ·  Total Polling TTC: {total_ms}ms[/dim]")
        _emit_verdict(verdict, out_format=out_format, wall_ms=total_ms)
    except Exception as exc:
        console.print(f"[bold red]Burst ingestion failed:[/bold red] {exc}")
        sys.exit(1)


@ingest.command("video")
@click.argument("video_path", type=str)
@click.option("--site-id", default="", help="Site identifier (defaults to active site)")
@click.option("--camera-id", default="", help="Camera. Defaults to the site's first camera.")
@click.option("--format", "out_format", type=click.Choice(["card", "json"]), default="card")
@click.pass_context
def ingest_video(ctx: click.Context, video_path: str, site_id: str, camera_id: str, out_format: str):
    """Submit a video clip (file or URL) and poll until the verdict."""
    client = _require_client(ctx)
    target_site_id, camera_id = _site_and_camera(client, site_id, camera_id)
    name_label = video_path if video_path.startswith(("http://", "https://")) else Path(video_path).name
    if out_format != "json":
        console.print(f"[dim]Sending {name_label} from {target_site_id}/{camera_id}...[/dim]")
    try:
        verdict, submit_ms, total_ms = client.ingest_video_and_poll(
            video_path=video_path,
            site_id=target_site_id,
            camera_id=camera_id,
        )
        if out_format != "json":
            console.print(f"[dim]Submit Ack: {submit_ms}ms  ·  Total Polling TTC: {total_ms}ms[/dim]")
        _emit_verdict(verdict, out_format=out_format, wall_ms=total_ms)
    except Exception as exc:
        console.print(f"[bold red]Video ingestion failed:[/bold red] {exc}")
        sys.exit(1)


# ─────────────────────────────────────────────────────────────────────────────
# novin incidents
# ─────────────────────────────────────────────────────────────────────────────

@cli.group()
def incidents():
    """Historical incident query and audit inspection."""
    pass


@incidents.command("list")
@click.option("--limit", default=10, help="Number of incidents to return")
@click.pass_context
def incidents_list(ctx: click.Context, limit: int):
    """Query recent historical incidents for the brand."""
    client = _require_client(ctx)
    res = client.list_incidents(limit=limit)
    items = res.get("incidents") or res.get("events") or []

    table = Table(title=f"Recent Incidents (Brand: {client.brand_id})", border_style="cyan")
    table.add_column("Incident ID", style="bold")
    table.add_column("Action")
    table.add_column("Threat Level")
    table.add_column("Site / Camera")
    table.add_column("Summary", style="dim")

    for it in items:
        action = it.get("action") or it.get("response", {}).get("action") or "?"
        threat = it.get("threat_level") or it.get("response", {}).get("threat_level") or "none"
        style = "green" if action == "suppress" else "red"

        table.add_row(
            it.get("incident_id") or it.get("job_id", "")[:12],
            f"[{style}]{action.upper()}[/{style}]",
            threat.upper(),
            f"{it.get('site_id', '')} / {it.get('stream_id', '')}",
            (it.get("summary") or "")[:50],
        )

    console.print(table)


# ─────────────────────────────────────────────────────────────────────────────
# novin feedback
# ─────────────────────────────────────────────────────────────────────────────

@cli.group()
def feedback():
    """Operator learning and verdict correction."""
    pass


@feedback.command("submit")
@click.argument("incident_id")
@click.argument("notes")
@click.option("--action", "suggested_action", type=click.Choice(["alert", "suppress"]), default="suppress")
@click.pass_context
def feedback_submit(ctx: click.Context, incident_id: str, notes: str, suggested_action: str):
    """Submit natural-language operator feedback on an incident."""
    client = _require_client(ctx)
    console.print(f"[cyan]Submitting feedback for incident[/cyan] [bold]{incident_id}[/bold]...")
    res = client.submit_feedback(
        incident_or_job_id=incident_id,
        text=notes,
        suggested_action=suggested_action,
    )
    console.print(f"[bold green]✓ Feedback Acknowledged:[/bold green] {res.get('message')}")
    console.print(f"[dim]Tracking ID: {res.get('tracking_id')}[/dim]")


def main() -> None:
    cli(prog_name="novin")


if __name__ == "__main__":
    main()
