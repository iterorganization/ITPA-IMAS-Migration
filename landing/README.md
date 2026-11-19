# Landing page for itpea-db.iter.org

A static page plus a small nginx reverse proxy that puts the whole service behind one host and port:

| Path | Served by |
|---|---|
| `/` | this landing page (`site/`) |
| `/dashboard/` | SimDB dashboard (default `host.docker.internal:8080`) |
| `/scenarios/api/` (also `/api`, `/scenarios`, `/swaggerui`) | SimDB server (default `host.docker.internal:5000`), with the prefix stripped and passed as `X-Forwarded-Prefix` |

The API rules copy the SimDB dashboard's own proxy
(`docker/nginx/templates/snippets/location-simdb_proxy.conf.template` in SimDB-Dashboard),
so the API behaves the same as through `/dashboard/`.

## Layout

```
site/                           index.html, style.css (edit these to change the page)
nginx/templates/                nginx config, envsubst-processed at container start
docker-compose.yml              nginx:1.27-alpine, publishes LANDING_PORT (default 80)
itpea-landing.service           systemd unit (runs docker compose from /opt/itpea-landing)
itpea-landing.env.example       ports/hosts, installed as /etc/itpea-landing/itpea-landing.env
Makefile                        install / update / uninstall
```

## Install on the server VM

Prerequisites: the SimDB server (`simdb-server.service`, port 5000) and dashboard
(`simdb-dashboard.service`) are running. Port 80 must be free, so move the dashboard off it
(`DASHBOARD_PORT=8080` in `/etc/simdb-dashboard/simdb-dashboard.env`) and stop any other
dashboard container still holding port 80.

```bash
git clone https://github.com/iterorganization/ITPA-IMAS-Migration.git
cd ITPA-IMAS-Migration/landing
sudo make install
sudo systemctl start itpea-landing
curl -s http://localhost/healthz          # ok
```

If the dashboard or SimDB use other ports, set them in `/etc/itpea-landing/itpea-landing.env`
and run `sudo systemctl restart itpea-landing`.

## Update the page

Edit `site/`, commit, then on the VM:

```bash
git pull
sudo make -C landing update     # copies site/ and nginx/ to /opt/itpea-landing and reloads
```

## Run locally

```bash
cd landing
LANDING_PORT=8090 make up       # http://localhost:8090/
make down
```
