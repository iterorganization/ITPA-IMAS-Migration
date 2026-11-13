"""Send idsmigration's SimDB entries to a remote SimDB server (`idsmigration --remote <name>`).

Each pulse becomes one entry, as with `idsmigration --simdb`: single time-slice pulses as metadata
only; pulses with several time-slices also with their HDF5 files (summary + temporary IDS), which
are uploaded, because SimDB keeps a numeric array only as {min, max}. No input files are uploaded.
Pulses whose alias already exists on the server are skipped, unless --replace is given, which
deletes and re-sends them; SimDB only lets the 'admin' role delete entries. Authentication works as
for the `simdb` CLI.
"""

import time
from typing import Any
from urllib.parse import quote

from simdb.checksum import hash_file
from simdb.cli.remote_api import RemoteAPI, _expand_directories_http
from simdb.cli.resumable_upload import resumable_upload
from simdb.config.config import Config
from simdb.database import DatabaseError
from simdb.enums import IngestionStatus
from simdb.remote.models import SimulationPostData

PAGE_SIZE = 1000


class SimDBServerUploader:
    """Receives idsmigration's SimDB entries (see `idsmigration.simdb_ingest`) and posts them to a server.

    Entries are posted without waiting for the server to finish each one; `wait()` then checks
    every posted entry's ingestion status. SimDB's own `push_simulation` waits about a second per
    entry, which would take hours for the larger ITPA datasets.
    """

    def __init__(self, api: RemoteAPI, dataset: str, replace: bool, uploaded_by: str) -> None:
        self.api = api
        self.replace = replace
        self.uploaded_by = uploaded_by
        self.existing = self._aliases(dataset)
        self.posted: dict[str, str] = {}  # alias -> uuid hex
        self.skipped: list[str] = []
        self.replaced: list[str] = []
        self.uploaded = 0  # entries whose HDF5 files were uploaded

    def _aliases(self, dataset: str) -> set[str]:
        """Aliases already on the server for this dataset."""
        aliases, page = set(), 1
        while True:
            headers = {"simdb-result-limit": str(PAGE_SIZE), "simdb-page": str(page)}
            data = self.api.get("simulations", {"dataset": dataset}, headers=headers).json()
            aliases.update(row["alias"] for row in data["results"])
            if page * PAGE_SIZE >= data["count"]:
                return aliases
            page += 1

    def delete_simulation(self, alias: str) -> None:
        """Called by simdb_ingest before every insert: deletes the server's entry only with --replace."""
        if alias in self.existing and self.replace:
            try:
                self.api.delete_simulation(alias)
            except Exception as exc:
                # SystemExit passes through simdb_ingest's `except Exception`: stop rather than fail every pulse.
                raise SystemExit(
                    f"--replace: the server refused to delete {alias} ({exc}). SimDB only lets the 'admin' "
                    "role delete entries; ask the server admin, or run without --replace to skip existing pulses."
                ) from exc
            self.existing.discard(alias)
            self.replaced.append(alias)
            return
        raise DatabaseError(f"{alias} not deleted")  # simdb_ingest treats this as "nothing to replace"

    def insert_simulation(self, simulation: Any) -> None:
        if simulation.alias in self.existing:
            self.skipped.append(simulation.alias)
            return
        sim_data = simulation.to_model(recurse=True)
        if sim_data.outputs.root:  # multi-slice pulse: upload its HDF5 files first
            sim_data.outputs.root = self._upload(sim_data.outputs.root, simulation.uuid)
            self.uploaded += 1
        post_data = SimulationPostData(
            simulation=sim_data,
            add_watcher=False,
            uploaded_by=self.uploaded_by,
        )
        self.api.post("simulations", data=post_data.model_dump(mode="json"))
        self.posted[simulation.alias] = simulation.uuid.hex

    def _upload(self, files: list, sim_uuid: Any) -> list:
        """Upload an entry's files and return them as the server-side file records.

        Same steps as SimDB's `RemoteAPI.push_simulation` (resumable HTTP upload into the server's
        `partition.http`, SHA-1 checksums), without its progress bars and per-entry wait.
        """
        expanded = _expand_directories_http(files, sim_uuid)
        auth = self.api._get_auth() if self.api._server_auth != "None" else None
        for file_data, local_path, target in expanded:
            file_data.checksum = hash_file(local_path)
            resumable_upload(
                f"{self.api._api_url}upload/{quote(target)}",
                local_path,
                auth=auth,
                cookies=self.api._cookies,
                headers={"User-Agent": "it_script_basic"},
            )
        return [file_data for file_data, _, _ in expanded]

    def wait(self, timeout: float = 600.0) -> dict[str, list[str]]:
        """Ingestion status of every posted entry, as {status: [aliases]}, waiting while any is pending.

        Servers before API v1.3 ingest synchronously and report no status: everything posted is done.
        """
        if self.api.version.major == 1 and self.api.version.minor < 3:
            return {IngestionStatus.COMPLETED.value: list(self.posted)}
        pending = dict(self.posted)
        final: dict[str, list[str]] = {}
        deadline = time.monotonic() + timeout
        while pending:
            for alias, uuid in list(pending.items()):
                status = self.api.get_ingestion_status(uuid)
                if status.is_terminal():
                    final.setdefault(status.value, []).append(alias)
                    del pending[alias]
            if pending:
                if time.monotonic() > deadline:
                    final["still pending after timeout"] = list(pending)
                    break
                time.sleep(2)
        return final


def connect(remote: str, dataset: str, replace: bool, uploaded_by: str) -> SimDBServerUploader:
    """A SimDBServerUploader for the simdb remote named `remote`, knowing the `dataset` entries already there."""
    config = Config()
    config.load()
    api = RemoteAPI(remote, None, None, config)
    uploader = SimDBServerUploader(api, dataset, replace, uploaded_by)
    print(f"Remote {remote} (API v{api.version}): {len(uploader.existing)} '{dataset}' entries already there")
    return uploader


def report(uploader: SimDBServerUploader) -> bool:
    """Print what was sent and each entry's ingestion status on the server; True if all completed."""
    print(f"Posted {len(uploader.posted)} ({uploader.uploaded} with HDF5 files), skipped {len(uploader.skipped)} already on the server"
          + (f", replaced {len(uploader.replaced)}" if uploader.replaced else ""))
    if uploader.skipped and not uploader.replace:
        print("  (use --replace to re-send them)")
    final = uploader.wait()
    for status, aliases in sorted(final.items()):
        print(f"  {status}: {len(aliases)}" + ("" if status == IngestionStatus.COMPLETED.value else f"  e.g. {aliases[:5]}"))
    return all(status == IngestionStatus.COMPLETED.value for status in final)
