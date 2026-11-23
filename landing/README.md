# Landing page for itpea-db.iter.org

A static page plus a small nginx reverse proxy that puts the whole service behind one host and port:

| Path | Served by |
|---|---|
| `/` | this landing page (`site/`) |
| `/dashboard/` | SimDB dashboard (default `host.docker.internal:80`) |
| `/scenarios/api/` (also `/api`, `/scenarios`, `/swaggerui`) | SimDB server (default `host.docker.internal:5000`), with the prefix stripped and passed as `X-Forwarded-Prefix` |

The API rules copy the SimDB dashboard's own proxy
(`docker/nginx/templates/snippets/location-simdb_proxy.conf.template` in SimDB-Dashboard),
so the API behaves the same as through `/dashboard/`.

## Layout

```
site/                           index.html, style.css (edit these to change the page)
nginx/templates/                upstreams + HTTP server, envsubst-processed at container start
nginx/snippets/locations.conf   routes (/, /dashboard/, /scenarios/api/), shared by HTTP and HTTPS
nginx/https/https.conf          optional HTTPS server (443)
docker-compose.yml              nginx:1.27-alpine, publishes LANDING_PORT (default 8081)
docker-compose.https.yml        optional overlay: publishes 443 and mounts the TLS certificate
itpea-landing.service           systemd unit (runs docker compose from /opt/itpea-landing)
itpea-landing.env.example       ports/hosts, installed as /etc/itpea-landing/itpea-landing.env
Makefile                        install / update / uninstall
```

## Install on the server VM

Prerequisites: the SimDB server (`simdb-server.service`, port 5000) and dashboard
(`simdb-dashboard.service`, port 80) are running. The landing page listens on port 8081, so open
it in the VM firewall and point the F5 for `itpea-db.iter.org` at `10.154.72.16:8081`.
(If the F5 points at port 80 instead, visitors land directly on the dashboard.)

```bash
git clone https://github.com/iterorganization/ITPA-IMAS-Migration.git
cd ITPA-IMAS-Migration/landing
sudo make install
sudo systemctl start itpea-landing
curl -s http://localhost:8081/healthz     # ok
sudo firewall-cmd --add-port=8081/tcp --permanent && sudo firewall-cmd --reload
```

If the dashboard or SimDB use other ports, set them in `/etc/itpea-landing/itpea-landing.env`
and run `sudo systemctl restart itpea-landing`.

## HTTPS listener (F5 forwarding to the backend on 443/TCP)

The F5 for `itpea-db.iter.org` forwards to the backend over HTTPS on port 443. Enable the
HTTPS listener next to the HTTP one:

```bash
sudo make -C landing update             # copies the https files to /opt/itpea-landing
sudo make -C landing tls-selfsigned     # /etc/itpea-landing/tls/server.{crt,key}, kept if present
echo 'COMPOSE_FILE=docker-compose.yml:docker-compose.https.yml' | sudo tee -a /etc/itpea-landing/itpea-landing.env
sudo systemctl restart itpea-landing
curl -sk https://localhost/healthz      # ok
sudo firewall-cmd --add-port=443/tcp --permanent && sudo firewall-cmd --reload
```

The F5 terminates the public TLS and normally does not verify the backend certificate, so a
self-signed one is enough; if IT requires a CA-signed certificate, put it in
`/etc/itpea-landing/tls/server.crt` and `server.key` instead.

## Update the page

Edit `site/`, commit, then on the VM:

```bash
git pull
sudo make -C landing update     # copies site/ and nginx/ to /opt/itpea-landing and reloads
```

## Run locally

```bash
cd landing
make up                         # http://localhost:8081/
make down
```
