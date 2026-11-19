# Install and run the ITPEA landing page as a systemd service.
#
#   make up / make down         run locally with docker compose (no root)
#   sudo make install           copy to /opt/itpea-landing and install the unit
#   sudo make update            copy changed site/nginx files and reload
#   sudo make uninstall         stop, disable and remove the unit (keeps the env file)

SHELL := /bin/sh

NAME ?= itpea-landing
optdir ?= /opt/$(NAME)
etcdir ?= /etc/$(NAME)
unitdir ?= /etc/systemd/system

.PHONY: help up down logs copy-files install update uninstall status

help:
	@sed -n '3,7p' Makefile

up:
	docker compose up --detach

down:
	docker compose down

logs:
	docker compose logs -f landing

$(optdir):
	install -d -m 0755 $(optdir) $(optdir)/site $(optdir)/nginx/templates

copy-files: $(optdir)
	install -m 0644 docker-compose.yml $(optdir)/
	install -m 0644 site/* $(optdir)/site/
	install -m 0644 nginx/templates/*.template $(optdir)/nginx/templates/

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

status:
	-systemctl status --no-pager $(NAME)

uninstall:
	-systemctl disable --now $(NAME)
	rm -f $(unitdir)/$(NAME).service
	systemctl daemon-reload
	@echo "Left in place: $(optdir) and $(etcdir). Remove them by hand if no longer needed."
