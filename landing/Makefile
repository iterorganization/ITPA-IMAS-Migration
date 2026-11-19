# Install and run the ITPEA landing page as a systemd service.
#
#   make up / make down         run locally with docker compose (no root)
#   sudo make install           copy to /opt/itpea-landing and install the unit
#   sudo make update            copy changed site/nginx files and reload
#   sudo make tls-selfsigned    create a self-signed cert in /etc/itpea-landing/tls (HTTPS listener)
#   sudo make uninstall         stop, disable and remove the unit (keeps the env file)

SHELL := /bin/sh

NAME ?= itpea-landing
optdir ?= /opt/$(NAME)
etcdir ?= /etc/$(NAME)
unitdir ?= /etc/systemd/system
tlsdir ?= $(etcdir)/tls
TLS_CN ?= itpea-db.iter.org
TLS_SAN ?= DNS:itpea-db.iter.org,IP:10.154.72.16

.PHONY: help up down logs copy-files install update uninstall status tls-selfsigned

help:
	@sed -n '3,8p' Makefile

up:
	docker compose up --detach

down:
	docker compose down

logs:
	docker compose logs -f landing

$(optdir):
	install -d -m 0755 $(optdir) $(optdir)/site $(optdir)/nginx/templates \
		$(optdir)/nginx/snippets $(optdir)/nginx/https

copy-files: $(optdir)
	install -d -m 0755 $(optdir)/nginx/snippets $(optdir)/nginx/https
	install -m 0644 docker-compose.yml docker-compose.https.yml $(optdir)/
	install -m 0644 site/* $(optdir)/site/
	install -m 0644 nginx/templates/*.template $(optdir)/nginx/templates/
	install -m 0644 nginx/snippets/*.conf $(optdir)/nginx/snippets/
	install -m 0644 nginx/https/*.conf $(optdir)/nginx/https/

install: copy-files
	install -d -m 0755 $(etcdir)
	@if [ ! -f $(etcdir)/$(NAME).env ]; then \
		install -m 0644 $(NAME).env.example $(etcdir)/$(NAME).env; \
	fi
	install -m 0644 $(NAME).service $(unitdir)/$(NAME).service
	systemctl daemon-reload
	systemctl enable $(NAME)
	@echo "Installed. Start with: sudo systemctl start $(NAME)"

update: copy-files
	systemctl reload $(NAME)

# Self-signed certificate for the HTTPS listener (the F5 terminates the public
# TLS; it normally does not verify the backend certificate). Kept if present.
tls-selfsigned:
	install -d -m 0755 $(tlsdir)
	@if [ -f $(tlsdir)/server.crt ]; then \
		echo "$(tlsdir)/server.crt exists, not overwriting"; \
	else \
		openssl req -x509 -newkey rsa:2048 -nodes -days 825 \
			-subj "/CN=$(TLS_CN)" -addext "subjectAltName=$(TLS_SAN)" \
			-keyout $(tlsdir)/server.key -out $(tlsdir)/server.crt && \
		chmod 0600 $(tlsdir)/server.key && chmod 0644 $(tlsdir)/server.crt; \
	fi

status:
	-systemctl status --no-pager $(NAME)

uninstall:
	-systemctl disable --now $(NAME)
	rm -f $(unitdir)/$(NAME).service
	systemctl daemon-reload
	@echo "Left in place: $(optdir) and $(etcdir). Remove them by hand if no longer needed."
