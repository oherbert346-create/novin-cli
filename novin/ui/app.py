"""Local terminal UI. Runs on the operator's machine; talks to the Novin API."""
from __future__ import annotations

from typing import Any

from textual import work
from textual.app import App, ComposeResult
from textual.binding import Binding
from textual.containers import Horizontal, Vertical, VerticalScroll
from textual.widgets import (
    Button,
    DataTable,
    Footer,
    Header,
    Input,
    Label,
    Select,
    Static,
    TabbedContent,
    TabPane,
    TextArea,
)

from novin.client.api_client import NovinClient
from novin.client import session as cli_session
from novin.ui.labels import DELIVERY_INTRO, DELIVERY_KIND_LABELS, ENVIRONMENT_LABELS, SITE_TYPES


def _host(client: NovinClient) -> str:
    return client.api_url.replace("https://", "").replace("http://", "")


def _active_site_id() -> str:
    cfg = cli_session.load_config()
    return str(cfg.get("active_site_id") or next(iter(cfg.get("sites") or {}), "") or "")


def _camera_list(raw: object) -> list[str]:
    if isinstance(raw, list):
        values = [str(item).strip() for item in raw]
    else:
        values = [part.strip() for part in str(raw or "").replace("\n", ",").split(",")]
    out: list[str] = []
    for item in values:
        if item and item not in out:
            out.append(item)
    return out


BRAND_SCOPE = "__brand__"


def _cached_sites() -> list[dict[str, Any]]:
    cfg = cli_session.load_config()
    out: list[dict[str, Any]] = []
    for sid, data in (cfg.get("sites") or {}).items():
        if not isinstance(data, dict):
            continue
        row = {"site_id": str(sid), **data}
        row["site_id"] = str(sid)
        out.append(row)
    return out


def _destinations_of(row: dict[str, Any] | None) -> list[dict[str, Any]]:
    data = row or {}
    dests = data.get("destinations")
    if isinstance(dests, list):
        items = [item for item in dests if isinstance(item, dict) and item.get("url")]
        if items:
            return items
    url = str(data.get("webhook_url") or "").strip()
    if url:
        return [{"url": url, "kind": "json", "auth_attached": bool(data.get("webhook_verified"))}]
    return []


def _kind_label(kind: str | None) -> str:
    key = str(kind or "json").strip().lower()
    if key == "api":
        key = "json"
    return DELIVERY_KIND_LABELS.get(key, key or "JSON API")


def _dest_summary(row: dict[str, Any], *, is_brand: bool = False) -> str:
    dests = _destinations_of(row)
    if not dests:
        return "no URLs yet" if is_brand else "brand URLs only"
    labels: list[str] = []
    for item in dests:
        label = _kind_label(item.get("kind"))
        if label not in labels:
            labels.append(label)
    count = len(dests)
    joined = " + ".join(labels)
    extra = "" if is_brand else " + brand"
    return f"{count} · {joined}{extra}"


class HomePane(Vertical):
    def compose(self) -> ComposeResult:
        yield Static(id="home-banner")
        yield Static(id="home-status")
        yield Static(
            "[dim]This brand's sites. Highlight a row and press Enter, or click it, to edit.[/dim]",
            id="home-hint",
        )
        yield Horizontal(
            Button("Refresh sites", id="refresh-sites", variant="primary"),
            Button("New site", id="new-site"),
            Button("Sign out", id="logout", variant="warning"),
            id="home-actions",
        )
        table = DataTable(id="sites-table", cursor_type="row", zebra_stripes=True)
        table.add_columns("Site", "Name", "World", "Cameras", "Context")
        yield table

    def on_mount(self) -> None:
        app = self.app
        assert isinstance(app, NovinApp)
        self.query_one("#home-banner", Static).update(
            f"[b]Novin[/b]  ·  brand [cyan]{app.novin.brand_id}[/cyan]  ·  {_host(app.novin)}"
        )
        app.refresh_status()
        app.load_sites()

    def on_button_pressed(self, event: Button.Pressed) -> None:
        app = self.app
        assert isinstance(app, NovinApp)
        if event.button.id == "refresh-sites":
            app.load_sites()
        elif event.button.id == "new-site":
            app.start_new_site()
        elif event.button.id == "logout":
            app.action_logout()

    def on_data_table_row_selected(self, event: DataTable.RowSelected) -> None:
        if event.data_table.id != "sites-table":
            return
        site_id = str(event.row_key.value) if event.row_key else ""
        if not site_id or site_id in {"error", "empty"}:
            return
        app = self.app
        assert isinstance(app, NovinApp)
        app.edit_site(site_id)


class SitePane(VerticalScroll):
    def compose(self) -> ComposeResult:
        yield Static("New site for this brand", id="site-mode")
        yield Label("Site id")
        yield Input("", id="site-id", placeholder="warehouse-south")
        yield Label("Name")
        yield Input(id="site-name", placeholder="South dock")
        yield Label("Camera world")
        yield Select(
            tuple((label, key) for key, label in ENVIRONMENT_LABELS.items()),
            prompt="Infer from how the site is used",
            allow_blank=True,
            id="environment",
        )
        yield Label("Hours (optional)")
        yield Input("", id="hours", placeholder="e.g. 08:00-18:00 — leave blank if none")
        yield Label("Cameras on this site")
        yield Input("", id="cameras", placeholder="cam_dock, cam_gate — ids this site owns")
        yield Label("What Novin should know about this site")
        yield TextArea(
            "",
            id="brief",
            show_line_numbers=False,
            tab_behavior="focus",
        )
        yield Static(
            "[dim]In your words: what is normal here, what to watch for, who belongs. "
            "Save writes this site for this brand. Open it from Home to edit later.[/dim]",
            id="brief-hint",
        )
        yield Horizontal(
            Button("Save site", id="save-site", variant="primary"),
            Button("Reload", id="reload-site"),
            Button("Delete site", id="delete-site", variant="error"),
            id="site-actions",
        )
        yield Static(id="site-result")

    def on_button_pressed(self, event: Button.Pressed) -> None:
        app = self.app
        assert isinstance(app, NovinApp)
        if event.button.id == "save-site":
            app.start_save_site()
        elif event.button.id == "reload-site":
            site_id = self.query_one("#site-id", Input).value.strip()
            if site_id:
                app.edit_site(site_id)
            else:
                app.start_new_site()
        elif event.button.id == "delete-site":
            app.start_delete_site()


class DeliveryPane(Vertical):
    def compose(self) -> ComposeResult:
        yield Static(DELIVERY_INTRO, id="delivery-hint")
        table = DataTable(id="delivery-table", cursor_type="row", zebra_stripes=True)
        table.add_columns("Who", "Alerts for", "Sends")
        yield table
        yield Static("Brand — every site", id="delivery-selected")
        yield Static(
            "[dim]URLs for the row above. Click one to remove it. Slack needs no key; a private API might.[/dim]",
            id="delivery-urls-hint",
        )
        urls = DataTable(id="dest-urls-table", cursor_type="row", zebra_stripes=True)
        urls.add_columns("Format", "Address", "Auth")
        yield urls
        yield Label("Where to send (HTTPS URL)")
        yield Input(
            "",
            id="dest-url",
            placeholder="Slack: hooks.slack.com/services/…   API: https://your-service/events",
        )
        yield Label("What they receive")
        yield Select(
            (
                ("Detect from the URL (Slack/Teams/Discord vs JSON)", "auto"),
                ("Slack / Teams / Discord chat message", "slack"),
                ("JSON API (the Novin verdict body)", "json"),
            ),
            value="auto",
            allow_blank=False,
            id="dest-kind",
        )
        yield Label("API key — only for a private API, not a Slack webhook")
        yield Input(
            "",
            id="dest-key",
            password=True,
            placeholder="optional · stored with this URL · sent on every alert",
        )
        yield Horizontal(
            Button("Add this URL", id="add-dest", variant="primary"),
            Button("Remove selected", id="remove-dest", variant="error"),
            Button("Refresh", id="refresh-delivery"),
            id="site-dest-actions",
        )
        yield Static(id="site-dest-result")
        yield Label("When to send")
        yield Horizontal(
            Select(
                (
                    ("Alerts only — threats. Quiet scenes stay in Incidents.", "alerts"),
                    ("Alerts and all-clears — every verdict is posted.", "all"),
                ),
                value="alerts",
                allow_blank=False,
                id="push-mode",
            ),
            Button("Save when-to-send", id="save-push"),
            id="brand-actions",
        )

    def on_mount(self) -> None:
        app = self.app
        assert isinstance(app, NovinApp)
        app.paint_delivery_now()
        app.load_delivery()

    def on_button_pressed(self, event: Button.Pressed) -> None:
        app = self.app
        assert isinstance(app, NovinApp)
        if event.button.id == "add-dest":
            app.start_add_destination()
        elif event.button.id == "remove-dest":
            app.start_remove_destination()
        elif event.button.id == "refresh-delivery":
            app.load_delivery()
        elif event.button.id == "save-push":
            app.start_save_push()

    def on_data_table_row_selected(self, event: DataTable.RowSelected) -> None:
        app = self.app
        assert isinstance(app, NovinApp)
        if event.data_table.id == "delivery-table":
            site_id = str(event.row_key.value) if event.row_key else ""
            if not site_id or site_id in {"error", "empty"}:
                return
            app.select_delivery_site(site_id)
        elif event.data_table.id == "dest-urls-table":
            url = str(event.row_key.value) if event.row_key else ""
            if url and url not in {"error", "empty"}:
                app.delivery_url = url
                try:
                    self.query_one("#dest-url", Input).value = url
                except Exception:
                    pass


class IncidentsPane(Vertical):
    def compose(self) -> ComposeResult:
        yield Horizontal(Button("Refresh", id="refresh-incidents", variant="primary"), id="inc-actions")
        table = DataTable(id="incidents-table")
        table.add_columns("Incident", "Action", "Summary")
        yield table

    def on_mount(self) -> None:
        app = self.app
        assert isinstance(app, NovinApp)
        app.load_incidents()

    def on_button_pressed(self, event: Button.Pressed) -> None:
        if event.button.id == "refresh-incidents":
            app = self.app
            assert isinstance(app, NovinApp)
            app.load_incidents()


class NovinApp(App[None]):
    """Full-screen terminal UI. Nothing is served in a browser."""

    TITLE = "Novin"
    CSS = """
    Screen {
        background: #161412;
        color: #ece6dc;
    }
    Header { background: #1c1916; }
    Footer { background: #1c1916; }
    #home-banner { padding: 1 1 0 1; }
    #home-status { padding: 1; color: #b7b0a6; }
    #home-hint { padding: 0 1 1 1; color: #8a837a; height: auto; }
    #home-actions, #inc-actions, #site-actions, #brand-actions, #site-dest-actions {
        padding: 1;
        height: auto;
    }
    #sites-table { height: 1fr; margin: 0 1 1 1; }
    #site-mode { padding: 0 0 1 0; color: #ece6dc; }
    SitePane, DeliveryPane { padding: 1 2; }
    DeliveryPane { height: 1fr; }
    Input, Select { margin-bottom: 1; }
    #brief { height: 10; margin-bottom: 1; }
    #brief-hint, #delivery-hint, #delivery-urls-hint {
        color: #8a837a;
        margin-bottom: 1;
        height: auto;
    }
    #delivery-hint { color: #ece6dc; }
    #delivery-selected { padding: 1 0 0 0; height: auto; }
    #delivery-table { height: 1fr; min-height: 8; margin: 0 0 1 0; }
    #dest-urls-table { height: 8; margin: 0 0 1 0; }
    #site-dest-result, #site-result { height: auto; margin-bottom: 1; }
    Label { color: #b7b0a6; }
    """
    BINDINGS = [
        Binding("ctrl+q", "quit", "Quit"),
        Binding("f5", "refresh", "Refresh"),
    ]

    def __init__(self, client: NovinClient, **kwargs: Any) -> None:
        super().__init__(**kwargs)
        self.novin = client
        self.sites: list[dict[str, Any]] = []
        self.brand_setup: dict[str, Any] = {}
        self.delivery_site_id = BRAND_SCOPE
        self.delivery_url = ""
        self.sub_title = f"brand {client.brand_id}  ·  {_host(client)}"

    def compose(self) -> ComposeResult:
        yield Header()
        with TabbedContent(initial="home", id="tabs"):
            with TabPane("Home", id="home"):
                yield HomePane()
            with TabPane("Sites", id="sites"):
                yield SitePane()
            with TabPane("Delivery", id="delivery"):
                yield DeliveryPane()
            with TabPane("Incidents", id="incidents"):
                yield IncidentsPane()
        yield Footer()

    def action_refresh(self) -> None:
        self.refresh_status()
        self.load_sites()
        self.load_delivery()
        self.load_incidents()

    def action_logout(self) -> None:
        cli_session.clear_session()
        self.notify("Signed out. Run novin and paste your API key.")
        self.exit()

    @work(thread=True, exclusive=True, group="status")
    def refresh_status(self) -> None:
        try:
            res = self.novin.ping()
            health = (res.get("health") or {}).get("status", "?")
            ready = (res.get("ready") or {}).get("status", "?")
            text = f"API  health={health}  ready={ready}"
        except Exception as exc:
            text = f"[red]API unreachable[/red]  {exc}"
        self.call_from_thread(self._set_status, text)

    def _set_status(self, text: str) -> None:
        try:
            self.query_one("#home-status", Static).update(text)
        except Exception:
            return

    def start_new_site(self) -> None:
        self.apply_site_to_form({})
        try:
            self.query_one("#tabs", TabbedContent).active = "sites"
            self.query_one("#site-id", Input).focus()
        except Exception:
            return

    def edit_site(self, site_id: str) -> None:
        self._load_site_work(site_id)

    @work(thread=True, exclusive=True, group="sites")
    def load_sites(self) -> None:
        try:
            sites = self.novin.list_sites()
            err = ""
        except Exception as exc:
            sites, err = [], str(exc)
        self.call_from_thread(self._on_sites_loaded, sites, err)

    def _on_sites_loaded(self, sites: list[dict[str, Any]], err: str) -> None:
        self.sites = sites
        try:
            table = self.query_one("#sites-table", DataTable)
        except Exception:
            return
        table.clear()
        if err:
            table.add_row("—", err, "", "", "", key="error")
            return
        if not sites:
            table.add_row("—", "No sites for this brand yet. New site.", "", "", "", key="empty")
            return
        active = _active_site_id()
        for row in sites:
            sid = str(row.get("site_id") or "")
            if not sid:
                continue
            mark = sid if sid != active else f"• {sid}"
            env = str(row.get("environment") or "")
            brief = str(row.get("brief") or "").split("\n", 1)[0][:48]
            cams = ", ".join(_camera_list(row.get("cameras")))
            table.add_row(
                mark,
                str(row.get("site_name") or sid),
                ENVIRONMENT_LABELS.get(env, env),
                cams,
                brief,
                key=sid,
            )
        self._fill_delivery_table(sites)

    @work(thread=True, exclusive=True, group="site")
    def _load_site_work(self, site_id: str) -> None:
        try:
            profile = self.novin.get_site(site_id)
        except Exception as exc:
            profile = {"site_id": site_id, "error": str(exc)}
        self.call_from_thread(self._open_site_editor, profile)

    def _open_site_editor(self, profile: dict[str, Any]) -> None:
        self.apply_site_to_form(profile)
        try:
            self.query_one("#tabs", TabbedContent).active = "sites"
        except Exception:
            return
        err = profile.get("error")
        if err:
            self._set_site_result(f"[red]Could not load[/red]  {err}")

    def apply_site_to_form(self, profile: dict[str, Any]) -> None:
        site_id = str(profile.get("site_id") or "")
        try:
            self.query_one("#site-id", Input).value = site_id
            self.query_one("#site-name", Input).value = str(profile.get("site_name") or "")
            self.query_one("#hours", Input).value = str(profile.get("expected_hours") or "")
            self.query_one("#cameras", Input).value = ", ".join(_camera_list(profile.get("cameras")))
            self.query_one("#brief", TextArea).text = str(profile.get("brief") or "")
            env = profile.get("environment") or Select.BLANK
            select = self.query_one("#environment", Select)
            try:
                select.value = env if env in ENVIRONMENT_LABELS or env is Select.BLANK else Select.BLANK
            except Exception:
                select.value = Select.BLANK
            if site_id:
                self.query_one("#site-mode", Static).update(
                    f"Editing [b]{site_id}[/b]  ·  brand [cyan]{self.novin.brand_id}[/cyan]"
                )
                self._set_site_result("")
            else:
                self.query_one("#site-mode", Static).update(
                    f"New site  ·  brand [cyan]{self.novin.brand_id}[/cyan]"
                )
                self._set_site_result("Give it an id, write what Novin should know, save.")
        except Exception:
            return

    def start_save_site(self) -> None:
        site_id = self.query_one("#site-id", Input).value.strip()
        if not site_id:
            self._set_site_result("[red]Site id is required.[/red]")
            return
        name = self.query_one("#site-name", Input).value.strip() or site_id
        hours = self.query_one("#hours", Input).value.strip()
        env_val = self.query_one("#environment", Select).value
        environment = None if env_val is Select.BLANK else str(env_val)
        brief = self.query_one("#brief", TextArea).text.strip()
        cameras = _camera_list(self.query_one("#cameras", Input).value)
        self._save_site_work(site_id, name, hours or None, environment, brief, cameras)

    def start_delete_site(self) -> None:
        site_id = self.query_one("#site-id", Input).value.strip()
        if not site_id:
            self._set_site_result("[red]Open a site before deleting it.[/red]")
            return
        self._delete_site_work(site_id)

    @work(thread=True, exclusive=True, group="site")
    def _delete_site_work(self, site_id: str) -> None:
        try:
            self.novin.delete_site(site_id)
            msg = f"[green]Deleted[/green] {site_id}"
        except Exception as exc:
            msg = f"[red]Could not delete[/red]  {exc}"
            site_id = ""
        self.call_from_thread(self._after_delete, site_id, msg)

    def _after_delete(self, site_id: str, msg: str) -> None:
        self._set_site_result(msg)
        if site_id:
            self.start_new_site()
        self.load_sites()
        self.load_delivery()

    @work(thread=True, exclusive=True, group="site")
    def _save_site_work(
        self,
        site_id: str,
        name: str,
        hours: str | None,
        environment: str | None,
        brief: str,
        cameras: list[str],
    ) -> None:
        site_type = environment if environment in SITE_TYPES else "office_retail"
        try:
            res = self.novin.setup_site(
                site_id=site_id,
                site_name=name,
                site_type=site_type,
                expected_hours=hours,
                environment=environment,
                brief=brief,
                cameras=cameras,
            )
            msg = f"[green]Saved[/green] {res.get('site_id') or site_id} for brand {self.novin.brand_id}"
        except Exception as exc:
            msg = f"[red]Could not save[/red]  {exc}"
        self.call_from_thread(self._after_save, site_id, msg)

    def _after_save(self, site_id: str, msg: str) -> None:
        self._set_site_result(msg)
        try:
            self.query_one("#site-mode", Static).update(
                f"Editing [b]{site_id}[/b]  ·  brand [cyan]{self.novin.brand_id}[/cyan]"
            )
        except Exception:
            pass
        self.load_sites()
        self.load_delivery()

    def _set_site_result(self, text: str) -> None:
        try:
            self.query_one("#site-result", Static).update(text)
        except Exception:
            return

    def paint_delivery_now(self) -> None:
        """Show sites immediately from memory/cache, then the API refresh fills keys."""
        sites = list(self.sites) or _cached_sites()
        self._fill_delivery_table(sites, self.brand_setup)
        self.select_delivery_site(self.delivery_site_id or BRAND_SCOPE)

    @work(thread=True, exclusive=True, group="delivery")
    def load_delivery(self) -> None:
        try:
            brand = self.novin.get_brand_setup()
            err = ""
        except Exception as exc:
            brand, err = {}, str(exc)
        try:
            sites = self.novin.list_sites()
        except Exception:
            sites = list(self.sites) or _cached_sites()
        self.call_from_thread(self._on_delivery_loaded, brand, sites, err)

    def _on_delivery_loaded(
        self, brand: dict[str, Any], sites: list[dict[str, Any]], err: str
    ) -> None:
        self.brand_setup = brand or {}
        if sites:
            self.sites = sites
        try:
            push = brand.get("push_actions") or []
            self.query_one("#push-mode", Select).value = "all" if "suppress" in push else "alerts"
        except Exception:
            pass
        self._fill_delivery_table(sites if sites else self.sites, brand)
        self.select_delivery_site(self.delivery_site_id or BRAND_SCOPE)
        if err:
            self._set_site_dest_result(f"[red]Could not load[/red]  {err}")

    def _fill_delivery_table(
        self, sites: list[dict[str, Any]], brand: dict[str, Any] | None = None
    ) -> None:
        try:
            table = self.query_one("#delivery-table", DataTable)
        except Exception:
            return
        table.clear()
        brand = brand if brand is not None else self.brand_setup
        table.add_row(
            "brand",
            "every site",
            _dest_summary(brand, is_brand=True),
            key=BRAND_SCOPE,
        )
        if not sites:
            table.add_row("—", "No sites yet. Add one on Sites.", "", key="empty")
            return
        for row in sites:
            sid = str(row.get("site_id") or "")
            if not sid:
                continue
            name = str(row.get("site_name") or sid)
            who = name if name == sid else f"{name}  ({sid})"
            table.add_row(
                who,
                "this site only",
                _dest_summary(row),
                key=sid,
            )

    def _scope_destinations(self) -> list[dict[str, Any]]:
        if self.delivery_site_id == BRAND_SCOPE:
            return _destinations_of(self.brand_setup)
        match = next(
            (row for row in self.sites if str(row.get("site_id")) == self.delivery_site_id),
            {},
        )
        return _destinations_of(match)

    def select_delivery_site(self, site_id: str) -> None:
        self.delivery_site_id = site_id or BRAND_SCOPE
        is_brand = self.delivery_site_id == BRAND_SCOPE
        if is_brand:
            label = "[b]Brand[/b] — these URLs get alerts from every site"
        else:
            name = next(
                (str(row.get("site_name") or "") for row in self.sites if str(row.get("site_id")) == self.delivery_site_id),
                "",
            )
            shown = name or self.delivery_site_id
            label = (
                f"[b]{shown}[/b] — these URLs get alerts from this site only. "
                "Brand URLs still fire too."
            )
        try:
            self.query_one("#delivery-selected", Static).update(label)
        except Exception:
            pass
        dests = self._scope_destinations()
        try:
            table = self.query_one("#dest-urls-table", DataTable)
        except Exception:
            return
        table.clear()
        if not dests:
            empty = (
                "None yet. Alerts stay in Incidents until you add a URL."
                if is_brand
                else "None yet. This site still uses brand URLs."
            )
            table.add_row("—", empty, "", key="empty")
        for item in dests:
            url = str(item.get("url") or "")
            kind = str(item.get("kind") or "json")
            if item.get("auth_attached") or item.get("api_key"):
                auth = "API key attached"
            elif kind in {"slack", "teams", "discord", "slack_api"}:
                auth = "in the URL"
            else:
                auth = "none"
            table.add_row(_kind_label(kind), url, auth, key=url)
        if is_brand:
            status = (
                f"{len(dests)} URL(s) for every site. Each alert POSTs to all of them at once."
                if dests
                else "No brand URLs. Add one, or set URLs on each site."
            )
        else:
            status = (
                f"{len(dests)} URL(s) for this site, plus brand. All of them POST in parallel."
                if dests
                else "No extra URLs on this site. Alerts still go to brand URLs."
            )
        self._set_site_dest_result(status)

    def start_add_destination(self) -> None:
        url = self.query_one("#dest-url", Input).value.strip()
        if not url:
            self._set_site_dest_result("[red]Paste a Slack or API URL first.[/red]")
            return
        kind = str(self.query_one("#dest-kind", Select).value or "auto")
        key = self.query_one("#dest-key", Input).value.strip()
        site_id = None if self.delivery_site_id == BRAND_SCOPE else self.delivery_site_id
        self._add_dest_work(url, site_id, kind, key)

    def start_remove_destination(self) -> None:
        url = self.delivery_url.strip() or self.query_one("#dest-url", Input).value.strip()
        if not url:
            self._set_site_dest_result("[red]Click a destination URL to remove.[/red]")
            return
        site_id = None if self.delivery_site_id == BRAND_SCOPE else self.delivery_site_id
        self._remove_dest_work(url, site_id)

    def start_save_push(self) -> None:
        mode = str(self.query_one("#push-mode", Select).value or "alerts")
        actions = ["alert", "review", "suppress"] if mode == "all" else ["alert", "review"]
        self._save_push_work(actions)

    @work(thread=True, exclusive=True, group="delivery")
    def _add_dest_work(self, url: str, site_id: str | None, kind: str, api_key: str) -> None:
        try:
            self.novin.add_destination(
                url,
                site_id=site_id,
                kind=None if kind == "auto" else kind,
                api_key=api_key or None,
            )
            scope = "every site" if site_id is None else f"site {site_id}"
            msg = f"[green]This URL now receives alerts for {scope}.[/green]"
        except Exception as exc:
            msg = f"[red]Could not add[/red]  {exc}"
        self.call_from_thread(self._after_dest_change, msg, True)

    @work(thread=True, exclusive=True, group="delivery")
    def _remove_dest_work(self, url: str, site_id: str | None) -> None:
        try:
            self.novin.remove_destination(url, site_id=site_id)
            msg = "[green]That URL will no longer receive alerts.[/green]"
        except Exception as exc:
            msg = f"[red]Could not remove[/red]  {exc}"
        self.call_from_thread(self._after_dest_change, msg, True)

    @work(thread=True, exclusive=True, group="delivery")
    def _save_push_work(self, actions: list[str]) -> None:
        try:
            self.novin.setup_brand(push_actions=actions)
            msg = "[green]Saved what Novin sends.[/green] Alerts always go out; all-clears only if you chose that."
        except Exception as exc:
            msg = f"[red]Could not save push[/red]  {exc}"
        self.call_from_thread(self._after_dest_change, msg, False)

    def _after_dest_change(self, msg: str, clear_inputs: bool = False) -> None:
        if clear_inputs:
            try:
                self.query_one("#dest-url", Input).value = ""
                self.query_one("#dest-key", Input).value = ""
            except Exception:
                pass
            self.delivery_url = ""
        self._set_site_dest_result(msg)
        self.load_delivery()

    def _set_site_dest_result(self, text: str) -> None:
        try:
            self.query_one("#site-dest-result", Static).update(text)
        except Exception:
            return

    @work(thread=True, exclusive=True, group="incidents")
    def load_incidents(self) -> None:
        try:
            res = self.novin.list_incidents(limit=20)
            items = res.get("incidents") or res.get("events") or []
        except Exception as exc:
            items = [{"incident_id": "error", "action": "?", "summary": str(exc)}]
        self.call_from_thread(self._fill_incidents, items)

    def _fill_incidents(self, items: list[dict[str, Any]]) -> None:
        try:
            table = self.query_one("#incidents-table", DataTable)
        except Exception:
            return
        table.clear()
        for it in items:
            action = it.get("action") or (it.get("response") or {}).get("action") or "?"
            table.add_row(
                str(it.get("incident_id") or it.get("job_id") or "")[:18],
                str(action).upper(),
                (it.get("summary") or (it.get("response") or {}).get("summary") or "")[:70],
            )


def run_tui(client: NovinClient) -> None:
    NovinApp(client).run()
