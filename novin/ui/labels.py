"""Environment labels shared by the CLI and the local terminal UI."""
from __future__ import annotations

ENVIRONMENT_LABELS = {
    "city_street": "City street / public CCTV",
    "transit": "Station / platform / bus",
    "industrial": "Plant / factory",
    "construction": "Construction site",
    "warehouse": "Warehouse / dock",
    "office": "Office / lobby",
    "school": "School",
    "retail": "Shop floor",
    "port_yard": "Port / trailer yard",
    "residential": "Home / driveway",
}
FOCUS_LABELS = {
    "access": "Doors and badges",
    "perimeter": "Fence / after-hours",
    "ppe": "Hard hats / high-vis",
    "weapons": "Weapons",
    "theft": "Theft",
    "safety": "Person down / blocked fire exit",
    "fire": "Fire / smoke",
}

ENV_HELP = "Camera world. " + ", ".join(f"{k} ({v})" for k, v in ENVIRONMENT_LABELS.items())
FOCUS_HELP = "Primary security job. " + ", ".join(f"{k} ({v})" for k, v in FOCUS_LABELS.items())

SITE_TYPES = tuple(ENVIRONMENT_LABELS.keys())

DELIVERY_KIND_LABELS = {
    "auto": "Detect from the URL",
    "slack": "Slack message",
    "slack_api": "Slack API",
    "teams": "Teams card",
    "discord": "Discord message",
    "json": "JSON API",
    "api": "JSON API",
}

DELIVERY_INTRO = (
    "[b]When Novin alerts, it POSTs the verdict to these URLs.[/b]\n"
    "[dim]Brand = every site. A site row = that site only — never another site.\n"
    "An alert for a site is sent to brand URLs and that site's URLs. Other sites stay out.\n"
    "Slack / Teams / Discord: paste the webhook (the secret is in the URL).\n"
    "Any other HTTPS API: paste the endpoint; attach a key only if that API needs one.[/dim]"
)
