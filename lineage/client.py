"""
Dremio REST API client — authentication, SQL job execution, catalog + lineage queries.
"""

import time
import logging
from typing import Optional

import requests

log = logging.getLogger(__name__)


class DremioConfig:
    def __init__(self, host: str, username: str, password: str):
        self.host = host.rstrip("/")
        self.username = username
        self.password = password
        self.token: Optional[str] = None
        self.session = requests.Session()
        self.session.headers.update({"Content-Type": "application/json"})

    def authenticate(self):
        """Log in and store bearer token."""
        url = f"{self.host}/apiv2/login"
        payload = {"userName": self.username, "password": self.password}
        resp = self.session.post(url, json=payload)
        resp.raise_for_status()
        self.token = resp.json()["token"]
        self.session.headers.update({"Authorization": f"_dremio{self.token}"})
        log.info("Authenticated successfully.")

    def sql(self, query: str) -> list[dict]:
        """Run a SQL query via Dremio REST API and return rows as list of dicts."""
        url = f"{self.host}/api/v3/sql"
        payload = {"sql": query}
        resp = self.session.post(url, json=payload)
        resp.raise_for_status()
        job_id = resp.json()["id"]
        return self._poll_job(job_id)

    def _poll_job(self, job_id: str, max_retries: int = 60) -> list[dict]:
        """Poll a job until completion and return results."""
        url = f"{self.host}/api/v3/job/{job_id}"
        for _ in range(max_retries):
            resp = self.session.get(url)
            resp.raise_for_status()
            status = resp.json().get("jobState")
            if status == "COMPLETED":
                return self._fetch_results(job_id)
            elif status in ("FAILED", "CANCELED"):
                raise RuntimeError(f"Job {job_id} ended with state: {status}")
            time.sleep(1)
        raise TimeoutError(f"Job {job_id} did not complete in time.")

    def _fetch_results(self, job_id: str) -> list[dict]:
        """Fetch paginated results for a completed job."""
        rows = []
        offset = 0
        limit = 500
        while True:
            url = f"{self.host}/api/v3/job/{job_id}/results?offset={offset}&limit={limit}"
            resp = self.session.get(url)
            resp.raise_for_status()
            data = resp.json()
            batch = data.get("rows", [])
            rows.extend(batch)
            if len(rows) >= data.get("rowCount", 0):
                break
            offset += limit
        return rows

    def get_catalog_entity(self, path: str) -> dict:
        """Fetch a catalog entity by path (slash-separated)."""
        encoded = requests.utils.quote(path, safe="")
        url = f"{self.host}/api/v3/catalog/by-path/{encoded}"
        resp = self.session.get(url)
        if resp.status_code == 404:
            return {}
        resp.raise_for_status()
        return resp.json()

    def get_lineage(self, dataset_id: str) -> dict:
        """Fetch native lineage graph for a dataset by its catalog ID."""
        url = f"{self.host}/api/v3/catalog/{dataset_id}/graph"
        resp = self.session.get(url)
        if resp.status_code in (404, 400):
            return {}
        resp.raise_for_status()
        return resp.json()
