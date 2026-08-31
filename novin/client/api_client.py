from __future__ import annotations

import base64
import json
import logging
import os
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Literal

import httpx

logger = logging.getLogger(__name__)


@dataclass
class NovinClient:
    """HTTPS client for the Novin API."""

    api_url: str = "https://novin-api.fly.dev"
    api_key: str = ""
    brand_id: str = "default"
    timeout_sec: float = 45.0

    def _headers(self, custom_headers: dict[str, str] | None = None) -> dict[str, str]:
        headers = {
            "Content-Type": "application/json",
            "X-API-Key": self.api_key,
            "X-Novin-Brand": self.brand_id,
        }
        if custom_headers:
            headers.update(custom_headers)
        return headers

    def ping(self) -> dict[str, Any]:
        """Probe health and readiness endpoints."""
        with httpx.Client(timeout=10.0) as client:
            t0 = time.perf_counter()
            r_health = client.get(f"{self.api_url}/health")
            health_ms = (time.perf_counter() - t0) * 1000

            t1 = time.perf_counter()
            r_ready = client.get(f"{self.api_url}/ready")
            ready_ms = (time.perf_counter() - t1) * 1000

            return {
                "health": r_health.json() if r_health.status_code == 200 else {"status": "error", "code": r_health.status_code},
                "health_ms": round(health_ms, 1),
                "ready": r_ready.json() if r_ready.status_code == 200 else {"status": "error", "code": r_ready.status_code},
                "ready_ms": round(ready_ms, 1),
            }

    def verify_credentials(self) -> tuple[bool, str]:
        """Return (ok, detail). 200 on /me means the key belongs to a brand."""
        try:
            kind, data = self.identify_key()
            if kind == "brand":
                if data.get("brand_id"):
                    self.brand_id = str(data["brand_id"])
                return True, "ok"
            if kind == "master":
                return False, "master"
            return False, "that key was not accepted"
        except Exception as exc:
            return False, str(exc)[:160]

    def identify_key(self) -> tuple[str, dict[str, Any]]:
        """Classify this key: brand, master, or invalid."""
        with httpx.Client(timeout=10.0) as client:
            r = client.get(f"{self.api_url}/api/v1/me", headers=self._headers())
        if r.status_code == 200:
            data = r.json() if isinstance(r.json(), dict) else {}
            return "brand", data
        if r.status_code == 403:
            return "master", {}
        if r.status_code == 401:
            return "invalid", {}
        return "invalid", {"status": r.status_code}

    def create_brand(self, name: str) -> dict[str, Any]:
        """Master key only. Creates a brand and returns a one-time API key."""
        return self._request_json("POST", "/api/v1/account", json={"name": name})

    @staticmethod
    def _error_detail(response: httpx.Response) -> str:
        try:
            body = response.json()
            detail = body.get("detail", body) if isinstance(body, dict) else body
            if isinstance(detail, list):
                detail = "; ".join(str(item) for item in detail)
            return f"{response.status_code}: {detail}"
        except Exception:
            text = (response.text or "").strip()[:240]
            return f"{response.status_code}: {text or response.reason_phrase}"

    def _request_json(
        self,
        method: str,
        path: str,
        *,
        json: dict[str, Any] | None = None,
        params: dict[str, Any] | None = None,
        timeout: float | None = None,
    ) -> dict[str, Any]:
        with httpx.Client(timeout=timeout or self.timeout_sec) as client:
            response = client.request(
                method,
                f"{self.api_url}{path}",
                json=json,
                params=params,
                headers=self._headers(),
            )
        if response.is_error:
            raise RuntimeError(self._error_detail(response))
        if not response.content:
            return {}
        data = response.json()
        return data if isinstance(data, dict) else {"data": data}

    def get_brand_setup(self) -> dict[str, Any]:
        """Brand delivery settings: webhook URL, verification, push actions."""
        return self._request_json(
            "GET",
            "/api/v1/brand/setup",
            params={"brand_id": self.brand_id},
        )

    def setup_brand(
        self,
        webhook_url: str | None = None,
        push_actions: list[str] | None = None,
        clear_webhook_url: bool = False,
        destinations: list[dict[str, Any]] | None = None,
        clear_destinations: bool = False,
    ) -> dict[str, Any]:
        """Configure brand delivery settings and standing webhooks."""
        payload: dict[str, Any] = {"brand_id": self.brand_id}
        if webhook_url:
            payload["webhook_url"] = webhook_url
        if push_actions:
            payload["push_actions"] = push_actions
        if clear_webhook_url:
            payload["clear_webhook_url"] = True
        if destinations is not None:
            payload["destinations"] = destinations
        if clear_destinations:
            payload["clear_destinations"] = True
        return self._request_json("PUT", "/api/v1/brand/setup", json=payload)

    def test_brand_webhook(self, webhook_url: str) -> dict[str, Any]:
        """Challenge a brand destination and activate it after a verified 2xx."""
        return self._request_json(
            "POST",
            "/api/v1/brand/webhook/test",
            json={"brand_id": self.brand_id, "webhook_url": webhook_url},
        )

    def clear_brand_webhook(self) -> dict[str, Any]:
        return self.setup_brand(clear_webhook_url=True, clear_destinations=True)

    def set_destinations(
        self,
        destinations: list[dict[str, Any]],
        *,
        site_id: str | None = None,
    ) -> dict[str, Any]:
        """Replace standing outgest URLs for the brand, or one site."""
        if site_id:
            result = self._request_json(
                "PUT",
                f"/api/v1/sites/{site_id}",
                json={"destinations": destinations},
            )
            if result:
                self._save_local_site_config(site_id, result, make_active=True)
            return result
        return self.setup_brand(destinations=destinations)

    def list_destinations(self, *, site_id: str | None = None) -> list[dict[str, Any]]:
        if site_id:
            site = self.get_site(site_id)
            return list(site.get("destinations") or [])
        brand = self.get_brand_setup()
        return list(brand.get("destinations") or [])

    def add_destination(
        self,
        url: str,
        *,
        site_id: str | None = None,
        kind: str | None = None,
        api_key: str | None = None,
        auth_header: str | None = None,
    ) -> dict[str, Any]:
        current = self.list_destinations(site_id=site_id)
        item: dict[str, Any] = {"url": url}
        if kind:
            item["kind"] = kind
        if api_key:
            item["api_key"] = api_key
        if auth_header:
            item["auth_header"] = auth_header
        urls = {str(row.get("url") or "") for row in current}
        if url not in urls:
            current.append(item)
        else:
            current = [item if str(row.get("url")) == url else row for row in current]
        return self.set_destinations(current, site_id=site_id)

    def remove_destination(self, url: str, *, site_id: str | None = None) -> dict[str, Any]:
        current = [row for row in self.list_destinations(site_id=site_id) if str(row.get("url")) != url]
        return self.set_destinations(current, site_id=site_id)

    def test_site_webhook(self, site_id: str, webhook_url: str) -> dict[str, Any]:
        """Challenge a site destination and activate it after a verified 2xx."""
        result = self._request_json(
            "POST",
            f"/api/v1/sites/{site_id}/webhook/test",
            json={"webhook_url": webhook_url},
        )
        if result:
            self._save_local_site_config(site_id, result, make_active=True)
        return result

    def clear_site_webhook(self, site_id: str) -> dict[str, Any]:
        result = self._request_json(
            "PUT",
            f"/api/v1/sites/{site_id}",
            json={"clear_webhook_url": True, "clear_destinations": True},
        )
        if result:
            self._save_local_site_config(site_id, result, make_active=True)
        return result

    def _save_local_site_config(
        self, site_id: str, site_data: dict[str, Any], *, make_active: bool = True
    ) -> None:
        try:
            from novin.client import session as cli_session

            cfg = cli_session.load_config()
            if make_active:
                cfg["active_site_id"] = site_id
            if "sites" not in cfg:
                cfg["sites"] = {}
            existing = dict(cfg["sites"].get(site_id) or {})
            existing.update({k: v for k, v in site_data.items() if v not in (None, "", [])})
            cfg["sites"][site_id] = existing
            cli_session.save_config(cfg)
        except Exception as exc:
            logger.debug("Failed to write ~/.novin/config.json: %s", exc)

    def _get_active_site_config(self) -> dict[str, Any]:
        try:
            from novin.client import session as cli_session

            return cli_session.load_config()
        except Exception:
            return {}

    def _site_payload_for_ingest(
        self,
        site_id: str,
        *,
        camera_id: str | None = None,
        zone: str | None = None,
        site_type: str | None = None,
    ) -> dict[str, Any]:
        """Lean ingest site: id + camera. Server hydrates TUI harness from DigitalSite."""
        site: dict[str, Any] = {"site_id": site_id}
        if camera_id:
            site["camera_id"] = camera_id
            site["stream_id"] = camera_id
        return site

    def setup_site(
        self,
        site_id: str,
        site_name: str = "",
        site_type: str = "",
        environment_class: str | None = None,
        expected_hours: str | None = None,
        timezone: str | None = None,
        restricted_zones: list[str] | None = None,
        critical_assets: list[str] | None = None,
        known_benign_patterns: list[str] | None = None,
        temporary_notes: list[str] | None = None,
        policies: list[str] | None = None,
        environment: str | None = None,
        focus: str | None = None,
        secondary_focuses: list[str] | None = None,
        brief: str | None = None,
        cameras: list[str] | None = None,
        output_depth: str | None = None,
    ) -> dict[str, Any]:
        """Create or configure a TUI site: id, name, world, hours, cameras, brief."""
        payload: dict[str, Any] = {
            "site_name": site_name or site_id,
        }
        world = (environment or site_type or "").strip()
        if world:
            payload["environment"] = world
            payload["site_type"] = world
        if expected_hours is not None:
            payload["expected_hours"] = expected_hours.strip() or None
        if brief is not None:
            payload["brief"] = brief.strip()
        if cameras is not None:
            payload["cameras"] = [c.strip() for c in cameras if str(c).strip()]
        if policies is not None:
            payload["brand_metadata"] = {
                "policies": [p.strip() for p in policies if str(p).strip()]
            }
        self._save_local_site_config(site_id, payload)
        with httpx.Client(timeout=15.0) as client:
            r = client.put(
                f"{self.api_url}/api/v1/sites/{site_id}",
                json=payload,
                headers=self._headers(),
            )
            r.raise_for_status()
            res_data = r.json()
        return {
            "status": "active",
            "site_id": site_id,
            "brand_id": self.brand_id,
            "site_profile": res_data,
            "message": f"Site context for {site_id} registered and persisted in database",
        }

    def list_sites(self, limit: int = 50) -> list[dict[str, Any]]:
        """Sites for this brand. API first; local cache if the call fails."""
        remote: list[dict[str, Any]] = []
        try:
            with httpx.Client(timeout=15.0) as client:
                r = client.get(
                    f"{self.api_url}/api/v1/sites",
                    params={"limit": limit},
                    headers=self._headers(),
                )
                r.raise_for_status()
                data = r.json()
            if isinstance(data, list):
                remote = [row for row in data if isinstance(row, dict)]
            elif isinstance(data, dict):
                rows = data.get("sites") or data.get("items") or []
                if isinstance(rows, list):
                    remote = [row for row in rows if isinstance(row, dict)]
        except Exception as exc:
            logger.debug("list_sites remote failed: %s", exc)
            local = self._get_active_site_config().get("sites") or {}
            return [
                {"site_id": str(sid), **cached}
                for sid, cached in local.items()
                if isinstance(cached, dict)
            ]
        self._forget_all_local_sites()
        for row in remote:
            sid = str(row.get("site_id") or "")
            if not sid:
                continue
            self._save_local_site_config(sid, row, make_active=False)
        return remote

    def get_site(self, site_id: str) -> dict[str, Any]:
        """Load one site for this brand so it can be edited. API is source of truth."""
        try:
            with httpx.Client(timeout=15.0) as client:
                r = client.get(
                    f"{self.api_url}/api/v1/sites/{site_id}",
                    headers=self._headers(),
                )
                r.raise_for_status()
                remote = r.json()
            if isinstance(remote, dict):
                self._save_local_site_config(site_id, remote, make_active=True)
                return remote
        except Exception as exc:
            logger.debug("get_site %s failed: %s", site_id, exc)
        cached = dict((self._get_active_site_config().get("sites") or {}).get(site_id) or {})
        cached.setdefault("site_id", site_id)
        return cached

    def delete_site(self, site_id: str) -> dict[str, Any]:
        """Delete one site for this brand and drop it from the local cache."""
        with httpx.Client(timeout=15.0) as client:
            r = client.delete(
                f"{self.api_url}/api/v1/sites/{site_id}",
                headers=self._headers(),
            )
            r.raise_for_status()
            body = r.json()
        self._forget_local_site(site_id)
        return body

    def restore_site(self, site_id: str) -> dict[str, Any]:
        with httpx.Client(timeout=15.0) as client:
            r = client.post(
                f"{self.api_url}/api/v1/sites/{site_id}/restore",
                headers=self._headers(),
            )
            r.raise_for_status()
            body = r.json()
        if isinstance(body, dict):
            self._save_local_site_config(site_id, body, make_active=True)
        return body

    def delete_all_sites(self) -> dict[str, Any]:
        """Delete every site for this brand."""
        with httpx.Client(timeout=15.0) as client:
            r = client.delete(
                f"{self.api_url}/api/v1/sites",
                headers=self._headers(),
            )
            r.raise_for_status()
            body = r.json()
        self._forget_all_local_sites()
        return body

    def _forget_local_site(self, site_id: str) -> None:
        try:
            from novin.client import session as cli_session

            cfg = cli_session.load_config()
            sites = dict(cfg.get("sites") or {})
            sites.pop(site_id, None)
            cfg["sites"] = sites
            if cfg.get("active_site_id") == site_id:
                cfg["active_site_id"] = next(iter(sites), "")
            cli_session.save_config(cfg)
        except Exception as exc:
            logger.debug("Failed to drop site from ~/.novin/config.json: %s", exc)

    def _forget_all_local_sites(self) -> None:
        try:
            from novin.client import session as cli_session

            cfg = cli_session.load_config()
            cfg["sites"] = {}
            cfg["active_site_id"] = ""
            cli_session.save_config(cfg)
        except Exception as exc:
            logger.debug("Failed to clear ~/.novin/config.json sites: %s", exc)

    def ingest_image(
        self,
        image_path_or_b64: str | Path,
        site_id: str,
        camera_id: str,
        zone: str | None = None,
        site_type: str | None = None,
        external_ref: str | None = None,
        after_hours: bool = False,
        low_light: bool = False,
        deliver_to: list[str] | None = None,
        beta: bool = False,
    ) -> tuple[dict[str, Any], float]:
        """Synchronously ingest a single image (file, URL, or base64)."""
        raw_str = str(image_path_or_b64).strip()
        if raw_str.startswith(("http://", "https://")):
            media_val: dict[str, Any] = {"image_urls": [raw_str]}
        elif os.path.exists(raw_str):
            p = Path(raw_str)
            media_val = {"image_b64": [base64.b64encode(p.read_bytes()).decode("ascii")]}
        else:
            media_val = {"image_b64": [raw_str]}

        payload: dict[str, Any] = {
            "brand_id": self.brand_id,
            "external_ref": external_ref or f"ingest-{int(time.time())}",
            "site": self._site_payload_for_ingest(site_id, camera_id=camera_id),
            "media": media_val,
        }
        ctx_payload: dict[str, Any] = {}
        if after_hours:
            ctx_payload["after_hours"] = True
        if low_light:
            ctx_payload["low_light"] = True
        if beta:
            ctx_payload["beta_reasoning"] = True
        if ctx_payload:
            payload["context"] = ctx_payload

        if deliver_to:
            payload["deliver_to"] = deliver_to

        with httpx.Client(timeout=self.timeout_sec) as client:
            t0 = time.perf_counter()
            r = client.post(
                f"{self.api_url}/api/v1/ingest",
                json=payload,
                headers=self._headers(),
            )
            wall_ms = (time.perf_counter() - t0) * 1000
            r.raise_for_status()
            return r.json(), round(wall_ms, 1)

    def ingest_metadata(
        self,
        summary: str,
        detections: list[dict[str, Any]],
        site_id: str,
        camera_id: str,
        zone: str = "general",
        site_type: str = "warehouse",
        external_ref: str | None = None,
        after_hours: bool = False,
        low_light: bool = False,
        deliver_to: list[str] | None = None,
    ) -> tuple[dict[str, Any], float]:
        """Synchronously ingest metadata-only observations without pixels."""
        payload: dict[str, Any] = {
            "brand_id": self.brand_id,
            "external_ref": external_ref or f"meta-{int(time.time())}",
            "site": {
                "site_id": site_id,
                "camera_id": camera_id,
                "stream_id": camera_id,
                "site_type": site_type,
                "zone": zone,
            },
            "context": {
                "after_hours": after_hours,
                "low_light": low_light,
            },
            "upstream_observations": {
                "summary": summary,
                "detections": detections,
            },
        }
        if deliver_to:
            payload["deliver_to"] = deliver_to

        with httpx.Client(timeout=self.timeout_sec) as client:
            t0 = time.perf_counter()
            r = client.post(
                f"{self.api_url}/api/v1/ingest",
                json=payload,
                headers=self._headers(),
            )
            wall_ms = (time.perf_counter() - t0) * 1000
            r.raise_for_status()
            return r.json(), round(wall_ms, 1)

    def ingest_burst_and_poll(
        self,
        image_paths: list[str | Path],
        site_id: str,
        camera_id: str,
        zone: str | None = None,
        site_type: str | None = None,
        external_ref: str | None = None,
        max_poll_sec: float = 30.0,
    ) -> tuple[dict[str, Any], float, float]:
        """Submit multi-frame burst (HTTP 202) and execute zero-delay long-polling."""
        media_urls: list[str] = []
        b64_list: list[str] = []
        for img in image_paths:
            s_img = str(img).strip()
            if s_img.startswith(("http://", "https://")):
                media_urls.append(s_img)
            elif os.path.exists(s_img):
                b64_list.append(base64.b64encode(Path(s_img).read_bytes()).decode("ascii"))
            else:
                b64_list.append(s_img)
        media_payload: dict[str, Any] = {}
        if media_urls:
            media_payload["image_urls"] = media_urls
        if b64_list:
            media_payload["image_b64"] = b64_list

        payload = {
            "brand_id": self.brand_id,
            "external_ref": external_ref or f"burst-{int(time.time())}",
            "site": self._site_payload_for_ingest(site_id, camera_id=camera_id),
            "media": media_payload,
        }

        with httpx.Client(timeout=self.timeout_sec) as client:
            t0 = time.perf_counter()
            r = client.post(
                f"{self.api_url}/api/v1/ingest",
                json=payload,
                headers=self._headers(),
            )
            submit_wall_ms = (time.perf_counter() - t0) * 1000
            if r.status_code == 200:
                pdata = r.json()
                total_ttc_ms = (time.perf_counter() - t0) * 1000
                return pdata, round(submit_wall_ms, 1), round(total_ttc_ms, 1)
            if r.status_code != 202:
                r.raise_for_status()

            job_info = r.json()
            job_id = job_info.get("job_id") or job_info.get("event", {}).get("job_id")
            if not job_id:
                raise ValueError(f"Missing job_id in 202 response: {job_info}")

            poll_url = f"{self.api_url}/api/v1/incidents/{job_id}"
            deadline = time.time() + max_poll_sec

            while time.time() < deadline:
                pr = client.get(
                    f"{poll_url}?wait_ms=5000",
                    headers=self._headers(),
                    timeout=10.0,
                )
                if pr.status_code == 200:
                    pdata = pr.json()
                    if "response" in pdata or pdata.get("status") in {"completed", "failed"}:
                        total_ttc_ms = (time.perf_counter() - t0) * 1000
                        return pdata, round(submit_wall_ms, 1), round(total_ttc_ms, 1)

            raise TimeoutError(f"Job {job_id} did not complete within {max_poll_sec}s")

    def ingest_video_and_poll(
        self,
        video_path: str | Path,
        site_id: str,
        camera_id: str,
        zone: str | None = None,
        site_type: str | None = None,
        external_ref: str | None = None,
        max_poll_sec: float = 45.0,
    ) -> tuple[dict[str, Any], float, float]:
        """Submit video clip (HTTP 202) and execute zero-delay long-polling."""
        s_video = str(video_path).strip()
        if s_video.startswith(("http://", "https://")):
            media_payload: dict[str, Any] = {"video_url": s_video}
        elif os.path.exists(s_video):
            media_payload = {
                "video_file_b64": base64.b64encode(Path(s_video).read_bytes()).decode("ascii")
            }
        else:
            media_payload = {"video_file_b64": s_video}

        payload = {
            "brand_id": self.brand_id,
            "external_ref": external_ref or f"video-{int(time.time())}",
            "site": self._site_payload_for_ingest(site_id, camera_id=camera_id),
            "media": media_payload,
        }

        with httpx.Client(timeout=self.timeout_sec) as client:
            t0 = time.perf_counter()
            r = client.post(
                f"{self.api_url}/api/v1/ingest",
                json=payload,
                headers=self._headers(),
            )
            submit_wall_ms = (time.perf_counter() - t0) * 1000
            if r.status_code == 200:
                pdata = r.json()
                total_ttc_ms = (time.perf_counter() - t0) * 1000
                return pdata, round(submit_wall_ms, 1), round(total_ttc_ms, 1)
            if r.status_code != 202:
                r.raise_for_status()

            job_info = r.json()
            job_id = job_info.get("job_id") or job_info.get("event", {}).get("job_id")
            if not job_id:
                raise ValueError(f"Missing job_id in 202 response: {job_info}")

            poll_url = f"{self.api_url}/api/v1/incidents/{job_id}"
            deadline = time.time() + max_poll_sec

            while time.time() < deadline:
                pr = client.get(
                    f"{poll_url}?wait_ms=5000",
                    headers=self._headers(),
                    timeout=10.0,
                )
                if pr.status_code == 200:
                    pdata = pr.json()
                    if "response" in pdata or pdata.get("status") in {"completed", "failed"}:
                        total_ttc_ms = (time.perf_counter() - t0) * 1000
                        return pdata, round(submit_wall_ms, 1), round(total_ttc_ms, 1)

            raise TimeoutError(f"Video job {job_id} did not complete within {max_poll_sec}s")

    def submit_feedback(
        self,
        incident_or_job_id: str,
        text: str,
        suggested_action: Literal["alert", "suppress"] = "suppress",
        labels: list[str] | None = None,
    ) -> dict[str, Any]:
        """Submit natural-language operator feedback."""
        payload = {
            "text": text,
            "suggested_action": suggested_action,
            "labels": labels or [],
        }
        with httpx.Client(timeout=15.0) as client:
            r = client.post(
                f"{self.api_url}/api/v1/incidents/{incident_or_job_id}/feedback",
                json=payload,
                headers=self._headers(),
            )
            r.raise_for_status()
            return r.json()

    def list_incidents(self, limit: int = 10) -> dict[str, Any]:
        """Query historical brand incidents."""
        with httpx.Client(timeout=15.0) as client:
            r = client.get(
                f"{self.api_url}/api/v1/incidents",
                params={"brand_id": self.brand_id, "limit": limit},
                headers=self._headers(),
            )
            r.raise_for_status()
            return r.json()
