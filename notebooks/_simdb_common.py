"""Shared SimDB data-access helpers for the notebooks."""


import hashlib
import logging
import pathlib
import shutil
from typing import Any, Optional

import imas
import numpy as np
import numpy.typing as npt
from imas.ids_defs import EMPTY_FLOAT, EMPTY_INT
from imas.ids_struct_array import IDSStructArray
from imas.ids_structure import IDSStructure

from simdb.cli.remote_api import RemoteAPI
from simdb.config.config import Config
from simdb.database.models.utils import unflatten_dict

# Keys per GET request: every key is sent as a query parameter, so this bounds the URL length.
KEYS_PER_REQUEST = 40
# Entries per page (simdb-result-limit header).
PAGE_SIZE = 2000

_from_hdf5: set[str] = set()  # aliases of pulses read from their HDF5 files
_downloaded: set[str] = set()  # ... of which downloaded in this session (not cached)


def cache_root() -> pathlib.Path:
    """Where downloaded HDF5 files are kept: ~/.cache/itpa_simdb (also on Windows, under the user profile)."""
    return pathlib.Path.home() / ".cache" / "itpa_simdb"


class RemoteSimulation:
    """One SimDB entry as returned by the server: `alias`, `uuid` and its metadata."""

    def __init__(self, alias: str, uuid: str, metadata: dict[str, Any], db: "RemoteDB") -> None:
        self.alias = alias
        self.uuid = uuid
        self._metadata = metadata
        self._db = db
        self._md: Optional[dict] = None

    @property
    def has_files(self) -> bool:
        """Whether the entry has IMAS output files (SimDB records their IDSs as `ids` metadata)."""
        return bool(self._metadata.get("ids"))

    def meta_dict(self) -> dict:
        """Nested dict of the pulse's values (e.g. md["global_quantities"]["ip"]["value"]): from its
        HDF5 files if it has any, else from its metadata (see module docstring). Built once per entry."""
        if self._md is None:
            self._md = self._read_hdf5() if self.has_files else self._read_metadata()
        return self._md

    def _read_metadata(self) -> dict:
        return unflatten_dict({key: _convert(self.alias, key, value) for key, value in self._metadata.items() if key != "ids"})

    def _read_hdf5(self) -> dict:
        directory = self._db.fetch_files(self)
        imas_log = logging.getLogger("imas")
        level = imas_log.level
        imas_log.setLevel(logging.WARNING)  # keep IMAS-Python's info messages out of the notebook output
        try:
            with imas.DBEntry(f"imas:hdf5?path={directory.as_posix()}", "r") as entry:  # forward slashes, also on Windows
                md = _to_dict(entry.get("summary", autoconvert=False))
                names = entry.list_all_occurrences("temporary")
                variables = _temporary_variables(entry.get("temporary", autoconvert=False)) if len(names) else {}
        finally:
            imas_log.setLevel(level)
        for name, value in variables.items():  # same split as the SimDB metadata
            bucket = "standard_name" if f"standard_name.{name}" in self._metadata else "db_variable"
            md.setdefault(bucket, {})[name] = value
        # Add the SimDB metadata the files do not provide (dataset, description, status, ...). Numeric
        # quantities are stored there only as {min, max} (or null): their values come from the files.
        labels = {k: v for k, v in self._metadata.items() if k != "ids" and v is not None and not _is_range(v)}
        _merge_missing(md, unflatten_dict(labels))
        _from_hdf5.add(self.alias)
        return md

    def __repr__(self) -> str:
        return f"RemoteSimulation({self.alias!r})"


class RemoteDB:
    """Connection to a SimDB server."""

    def __init__(self, remote: Optional[str] = None) -> None:
        config = Config()
        config.load()
        self.remote = remote or config.default_remote
        self.api = RemoteAPI(self.remote, None, None, config)
        self._keys: Optional[list[str]] = None
        self.cache = cache_root() / "".join(c if c.isalnum() or c in "-_." else "_" for c in self.remote)

    def metadata_keys(self) -> list[str]:
        """Every metadata key stored on the server (GET /metadata)."""
        if self._keys is None:
            self._keys = sorted(item["name"] for item in self.api.get("metadata").json())
        return self._keys

    def query(self, **filters: str) -> list[RemoteSimulation]:
        """Entries matching every `key=value` filter (equality), with all their metadata.

        Filters are sent as query parameters. The metadata keys to return are sent as bare
        parameters (`?key=`), which the server treats as columns to include, not as filters; they
        are split over several requests to keep URLs short, and merged per entry.
        """
        merged: dict[str, dict] = {}
        aliases: dict[str, str] = {}
        # A bare `?dataset=` would replace the `dataset=tc26` filter; filtered keys are returned anyway.
        keys = [key for key in self.metadata_keys() if key not in filters]
        for start in range(0, len(keys), KEYS_PER_REQUEST):
            params = {**filters, **{key: "" for key in keys[start : start + KEYS_PER_REQUEST]}}
            for row in self._pages(params):
                uuid = row["uuid"]["hex"] if isinstance(row["uuid"], dict) else str(row["uuid"])
                aliases[uuid] = row["alias"]
                merged.setdefault(uuid, {}).update({m["element"]: m["value"] for m in row.get("metadata", [])})
        return sorted(
            (RemoteSimulation(aliases[u], u, meta, self) for u, meta in merged.items()), key=lambda s: s.alias or ""
        )

    def fetch_files(self, sim: RemoteSimulation) -> pathlib.Path:
        """The entry's IMAS output files in the local cache, downloaded through the API if missing.

        Same steps as SimDB's `RemoteAPI.pull_simulation` (file list from GET /file/<uuid>, bytes
        from GET /file/download/<uuid>/<index>, SHA-1 check), without its per-file progress bars.
        """
        directory = self.cache / sim.uuid
        if (directory / ".complete").exists():
            return directory
        partial = directory.with_name(sim.uuid + ".partial")
        shutil.rmtree(partial, ignore_errors=True)
        partial.mkdir(parents=True)
        record = self.api.get(f"simulation/{sim.uuid}").json()
        for output in record.get("outputs", []):
            if output.get("type") != "IMAS":
                continue
            file_uuid = output["uuid"]["hex"] if isinstance(output["uuid"], dict) else str(output["uuid"])
            for index, info in enumerate(self.api.get(f"file/{file_uuid}").json()["files"]):
                target = partial / info["path"].replace("\\", "/").rsplit("/", 1)[-1]  # server path, any OS
                digest = hashlib.sha1()
                response = self.api.get(f"file/download/{file_uuid}/{index}", stream=True)
                with target.open("wb") as f:
                    for chunk in response.iter_content(chunk_size=1 << 20):
                        digest.update(chunk)
                        f.write(chunk)
                if digest.hexdigest() != info["checksum"]:
                    raise IOError(f"{sim.alias}: checksum mismatch for {target.name}")
        (partial / ".complete").touch()
        shutil.rmtree(directory, ignore_errors=True)
        partial.rename(directory)
        _downloaded.add(sim.alias)
        return directory

    def _pages(self, params: dict) -> Any:
        page = 1
        while True:
            headers = {"simdb-result-limit": str(PAGE_SIZE), "simdb-page": str(page)}
            data = self.api.get("simulations", params, headers=headers).json()
            yield from data["results"]
            if page * PAGE_SIZE >= data["count"]:
                return
            page += 1


def _convert(alias: str, key: str, value: Any) -> Any:
    """A stored metadata value of a single time-slice pulse as the notebooks use it: [value]."""
    if value is None:  # SimDB stores an array with no valid value as null
        return np.array([np.nan])
    if isinstance(value, dict) and set(value) == {"min", "max"}:
        if value["min"] != value["max"]:
            raise ValueError(
                f"{alias}: {key} is a range {value} but the entry has no HDF5 files, so its per-slice "
                "values are not available. Re-ingest this dataset with the current idsmigration (--remote)."
            )
        return np.array([value["min"]], dtype=float)
    if isinstance(value, list) and value and all(v == value[0] for v in value):
        return [value[0]]
    return value


def report() -> None:
    """Print how many multi-slice pulses were read from HDF5, and how many of them were downloaded now."""
    print(f"{len(_from_hdf5)} multi-slice pulses read from their HDF5 files "
          f"({len(_downloaded)} downloaded now, the rest from the cache)")


def _is_range(value: Any) -> bool:
    """A numeric metadata value as SimDB stores it: {"min": ..., "max": ...}."""
    return isinstance(value, dict) and set(value) == {"min", "max"}


def _merge_missing(target: dict, source: dict) -> None:
    """Copy into `target` every entry of `source` it does not already have (recursing into dicts)."""
    for key, value in source.items():
        if key not in target:
            target[key] = value
        elif isinstance(target[key], dict) and isinstance(value, dict):
            _merge_missing(target[key], value)


def _to_dict(node: IDSStructure) -> dict:
    """Filled leaves of an IDS (sub)tree as a nested dict: arrays as np.ndarray, 0D as scalars."""
    out: dict[str, Any] = {}
    for child in node.iter_nonempty_():
        name = child.metadata.name
        if isinstance(child, IDSStructArray):
            out[name] = [_to_dict(el) for el in child]
        elif isinstance(child, IDSStructure):
            out[name] = _to_dict(child)
        elif child.metadata.ndim:
            out[name] = np.asarray(child.value)
        else:
            out[name] = child.value
    return out


def _temporary_variables(temp_ids: IDSStructure) -> dict:
    """{identifier/name: value} for every filled entry of the temporary IDS buckets.

    constant_* entries hold `value` directly, dynamic_* entries in `value/data`; per-slice string
    series (constant_string1d) are returned as lists, like SimDB returns string arrays.
    """
    result: dict[str, Any] = {}
    for bucket in temp_ids.iter_nonempty_():
        if not isinstance(bucket, IDSStructArray):
            continue
        dynamic = bucket.metadata.name.startswith("dynamic_")
        for el in bucket:
            name = str(el.identifier.name)
            leaf = el.value.data if dynamic else el.value
            if not name or not leaf.has_value:
                continue
            if bucket.metadata.name == "constant_string1d":
                result[name] = [str(v) for v in leaf.value]
            else:
                result[name] = np.asarray(leaf.value) if leaf.metadata.ndim else leaf.value
    return result


def get_db(remote: Optional[str] = None) -> RemoteDB:
    """Connect to the SimDB server named `remote` in your simdb configuration (else its default remote)."""
    return RemoteDB(remote)


def guard(x: npt.ArrayLike) -> np.ndarray:
    """Replace the IMAS empty-float/empty-int sentinels with NaN."""
    a = np.asarray(x, dtype=float)
    is_empty = (np.abs(a) >= abs(EMPTY_FLOAT)) | (a == EMPTY_INT)
    return np.where(is_empty, np.nan, a)


def path(md: dict, *keys: str, n: int) -> np.ndarray:
    """Walk a nested meta_dict path"""
    node = md
    for k in keys:
        if not isinstance(node, dict) or k not in node:
            return np.full(n, np.nan)
        node = node[k]
    return guard(node)


def temp(md: dict, *names: str, n: int) -> np.ndarray:
    """First matching temporary-IDS quantity: db_variable.<name> or standard_name.<name>."""
    for bucket in ("db_variable", "standard_name"):
        for name in names:
            v = md.get(bucket, {}).get(name)
            if v is not None:
                return guard(v)
    return np.full(n, np.nan)


def temp_str(md: dict, *names: str, n: int) -> np.ndarray:
    """Like temp(), but for string-valued temporary-IDS quantities."""
    for bucket in ("db_variable", "standard_name"):
        for name in names:
            v = md.get(bucket, {}).get(name)
            if v is not None:
                return np.asarray(v, dtype=object)
    return np.full(n, "", dtype=object)


def path_str(md: dict, *keys: str, n: int) -> np.ndarray:
    """Like path(), but for string-valued quantities. Broadcasts a shot-scalar to length n."""
    node = md
    for k in keys:
        if not isinstance(node, dict) or k not in node:
            return np.full(n, "", dtype=object)
        node = node[k]
    arr = np.asarray(node, dtype=object)
    if arr.ndim == 0:
        return np.full(n, arr.item(), dtype=object)
    return arr


def query_selected(db: RemoteDB, dataset: str, selec_key: str, machine: Optional[str] = None, value: str = "1") -> list[Any]:
    """Simulations for `dataset` (optionally restricted to `machine`) where db_variable.<selec_key>
    equals `value` in at least one time-slice."""
    target = float(value)
    return [
        sim for sim in query_dataset(db, dataset, machine)
        if np.any(temp(sim.meta_dict(), selec_key, n=0) == target)
    ]


def query_dataset(db: RemoteDB, dataset: str, machine: Optional[str] = None) -> list[Any]:
    """All simulations for `dataset` (optionally restricted to `machine`), unfiltered by any
    selection flag."""
    filters = {"dataset": dataset}
    if machine is not None:
        filters["machine"] = machine
    return db.query(**filters)
