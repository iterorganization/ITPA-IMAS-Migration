# itpa-imas-migration

This code was extracted from the migration workstream of a fork of IMAS `IDStools` (https://github.com/fionncur/IDStools)

## Layout

```
src/itpa_imas_migration/
    idsmigration.py        # the migration script (CSV -> summary IDS + SimDB manifest)
    generate_crosswalk.py  # authors/regenerates crosswalk workbooks with live DD lookups
docs/                      # migration.md (idsmigration reference), data logbook
resources/mappings/        # crosswalk workbooks (canonical) + csv/ projections
resources/input/           # source CSV databases (untracked)
notebooks/                 # analysis notebooks
```

## Installation

```bash
python -m venv .venv
.venv/Scripts/activate      # Windows
pip install -e .
```

The migration reference (crosswalk specification, SimDB ingestion) is in
[docs/migration.md](docs/migration.md).

## Ingesting into a SimDB server

`idsmigration --remote <name>` sends one entry per pulse straight to a SimDB server from your simdb
configuration (`simdb remote config list`), with no input files: single time-slice pulses as metadata
only, pulses with several time-slices also with their HDF5 files written under
`resources/results/<dataset>/` and uploaded:

```bash
idsmigration -e tc26 -d nfae39f2supp2.csv -m TC26_crosswalk.xlsx --remote itpa
```

Pulses already on the server are skipped; `--replace` deletes and re-sends them, which needs the
server's `admin` role. `--uploaded-by` sets the recorded uploader (default: your login name).

## Analysis notebooks

The notebooks fetch their data from a SimDB server, through its REST API
(`notebooks/_simdb_common.py`). Each notebook names its server in
its setup cell (`SIMDB_REMOTE = "itpa"`, a remote from `simdb remote config list`);

Each entry is one pulse. SimDB stores a numeric array only as `{min, max}`, which is exact for a single
time-slice pulse. For a pulse with several time-slices `_simdb_common` downloads its HDF5 files once
through the API into a cache (`~/.cache/itpa_simdb/`) and
uses the full per-slice arrays. `sc.report()` counts the pulses read from HDF5.

## License

LGPL-3.0-or-later. See [LICENSE.md](LICENSE.md).
