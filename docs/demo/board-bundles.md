# Move the four demo boards to the deployed app

A bundle is one zip holding a finished board: its items and images, analyses, explorations,
agent runs and steps. You export it on the machine where the board was made and import it on the
deployed app. Nothing here is run for you; you run these steps, in this order.

Left out of a bundle: Vary runs, their candidates and decisions, plugin nodes and runs, and UI
events. A board with licensed corpus items refuses to export (`BOARD_HAS_LICENSED_ITEMS`); the
four demo boards have none.

## 1. Export the four boards (on your machine)

Each board's id is `board_id` in `reports/demo/<slug>/run.json` (the slugs are `car-3`, `ui`,
`room` and `outerwear-2`; `car-2` and `outerwear` are earlier runs of the same boards).
Run this with the local app's database and `data/` in place:

```
make board-export BOARD=<board_id> OUT=bundles/<slug>.zip
```

Each first prints `database <url>, files <dir>`: check it is the local app's database and
`data/`. Then it prints `exported <title> (<board_id>): <n> rows, <m> files -> <path>`. If it
also prints `note: <n> items are not finished and will be read again on the server (model
calls)`, some pictures were still being read when you exported; the deployed app reads them
again, which costs model calls there. Let the local app finish and export again to avoid that.
(`bundles/` is in `.gitignore`: the zips are never committed.)

## 2. Snapshot the volume (before touching the deployed data)

```
fly volumes list
fly volumes snapshots create <volume id>
```

The volume is named `muse_data` (`fly.toml`); take the id from `fly volumes list`.

## 3. Deploy the code first, with demo mode on

The landing page shows at `/` only in demo mode; with it off, `/` is the board list. `fly.toml`
has `DEMO_MODE = '0'` under `[env]`, and demo mode refuses to start without a passcode and a
signing secret. So set those two secrets first:

```
fly secrets set DEMO_PASSCODE=<a passcode for you> DEMO_SECRET=<32+ random characters>
```

(`openssl rand -hex 32` makes a secret.) Then change `DEMO_MODE = '0'` to `DEMO_MODE = '1'` in
`fly.toml` and deploy:

```
fly deploy --ha=false
```

The container's entrypoint runs `alembic upgrade head` on start, so the deployed database is
migrated to this version. The import refuses a bundle made on a different schema
(`SCHEMA_MISMATCH`), so the deployed code must be the same version as the code that exported:
export and deploy from the same commit.

Now check which database and data directory the app's shell sees, because the import uses
the same two variables:

```
fly ssh console -u user -C "printenv DATABASE_URL DATA_DIR"
```

It must print `sqlite:////data/dle.sqlite` and `/data`. The image's own defaults point at a
throwaway database inside the image (`/home/user/app/data`); importing there "succeeds" and the
live app never sees the board. If you see those, stop: the `[env]` of `fly.toml` is not reaching
the shell, and the import must be run with `DATABASE_URL` and `DATA_DIR` set by hand.

## 4. Upload the zips

```
fly ssh sftp shell
```

First make the upload directory, as the app user (the app runs as `user`, uid 1000, and
`fly ssh` connects as root unless told otherwise; root-owned files on `/data` can leave the app
unable to write its own database or images):

```
fly ssh console -u user -C "mkdir -p /data/bundles"
```

Then, at the `>>` prompt of `fly ssh sftp shell`, for each zip:

```
put bundles/car-3.zip /data/bundles/car-3.zip
put bundles/ui.zip /data/bundles/ui.zip
put bundles/room.zip /data/bundles/room.zip
put bundles/outerwear-2.zip /data/bundles/outerwear-2.zip
```

(`fly ssh sftp put <local> <remote>` does the same one file at a time.)

The upload writes the files as root. Hand them to the app user before importing, so nothing
under `/data` is left that `user` cannot read or replace:

```
fly ssh console -C "chown -R user:user /data/bundles"
```

## 5. Import each one

```
fly ssh console -u user -C "python -m app.bundle import /data/bundles/car-3.zip"
```

Its first line is `database <url>, files <dir>`: confirm it shows `sqlite:////data/dle.sqlite`
and `/data`, the same as the check in step 3. Run it as `user` (`-u user`), never as root: the import writes new image files and the sqlite
`-wal`/`-shm` files under `/data`, and root-owned ones there make the app fail with "attempt to
write a readonly database" or permission errors. Likewise for `ui`, `room` and `outerwear-2`. (The image puts its virtualenv on `PATH`, so
`python` is the app's; `uv run python` also works if you prefer it.) Each prints
`imported <title> (<board_id>): <n> rows, <m> new files`. On an error it prints
`error <CODE>: <message>` and exits 1, and nothing from that board is kept. `DB_NOT_MIGRATED`
means the database it opened is not at this code's schema: either it is the wrong database (see
the first line) or the deploy did not finish migrating.

Importing a board that is already there refuses (`BOARD_EXISTS`). To overwrite it, add
`--replace`. That deletes the board's rows and re-inserts them from the bundle, and it also
removes visitors' Vary runs, their decisions and other things made on that board on the
server; the command prints a line `removed from this server: ...` listing what went.

Once all four are in, delete the uploaded zips (as the app user, like everything under `/data`):

```
fly ssh console -u user -C "rm -r /data/bundles"
```

## 6. Check

Open the deployed landing page and each board: the replay should play and the pictures load.
If something is wrong, restore from the snapshot taken in step 2.
