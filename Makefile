SHELL := /bin/bash

IMAGE_DEV ?= app:dev
IMAGE_PROD ?= app:prod

# Project name (used to detect compose-built containers/images). Defaults to current directory name.
PROJECT ?= $(notdir $(CURDIR))

.PHONY: run-tests compile-requirements run-bash run-bash-dev runserver migrations migrate superuser stop clean

build-dev:
	docker build -f docker/Dockerfile --target dev -t $(IMAGE_DEV) .

build-prod:
	docker build -f docker/Dockerfile --target prod -t $(IMAGE_PROD) .

tests:
	docker run --rm -it -v $(PWD):/app -w /app --entrypoint pytest $(IMAGE_DEV) -q

compile-requirements:
	docker run --rm -it -v $(PWD):/app -w /app --entrypoint sh $(IMAGE_DEV) -c "pip-compile requirements.in -o requirements.txt && pip-compile requirements-dev.in -o requirements-dev.txt && pip-compile requirements-prod.in -o requirements-prod.txt"

bash:
	docker run --rm -it -v $(PWD):/app -w /app $(IMAGE_PROD) bash

# Development shell: mounts only project `src` and the dev requirements file so
# repo-level files (docker-compose.yml, .env) aren't exposed inside the container.
bash-dev:
	docker compose run --rm --entrypoint bash web

runserver:
	docker compose up web

migrations:
	docker compose run --rm web python src/mustang/manage.py makemigrations

migrate:
	docker compose run --rm web python src/mustang/manage.py migrate

superuser:
	docker compose run --rm \
		-e DJANGO_SUPERUSER_USERNAME=admin \
		-e DJANGO_SUPERUSER_PASSWORD=admin \
		-e DJANGO_SUPERUSER_EMAIL=admin@example.com \
		web python src/mustang/manage.py createsuperuser --noinput

# Clean: stop and remove containers and remove images.
# This is destructive. To actually perform the removals set CONFIRM=1
# Example: make clean CONFIRM=1

# Stop project-related containers (built from app images, compose project, or mounting this repo)
stop:
	@echo "Locating project-related containers for project '$(PROJECT)'..."
	@containers_ancestor=$$(docker ps -a --filter "ancestor=$(IMAGE_DEV)" --filter "ancestor=$(IMAGE_PROD)" -q); \
	containers_compose=$$(docker ps -a --filter "label=com.docker.compose.project=$(PROJECT)" -q); \
	containers_mount=$$(for c in $$(docker ps -a -q); do docker inspect -f '{{range .Mounts}}{{.Source}} {{end}} {{.Id}}' $$c | grep -F "$(shell pwd)" >/dev/null 2>&1 && echo $$c || true; done); \
	all=$$(printf "%s\n%s\n%s\n" "$$containers_ancestor" "$$containers_compose" "$$containers_mount" | sort -u | sed '/^$$/d'); \
	if [ -z "$$all" ]; then \
		echo "No project-related containers found."; \
	else \
		echo "Stopping and removing containers: $$all"; \
		docker rm -f $$all || true; \
	fi

# Clean project images: remove images named for this project (app:dev/app:prod),
# images created by docker-compose for this project, and images used by compose containers.

clean:
	@echo "Stopping all containers (required to remove images)..."
	@containers=$$(docker ps -aq); \
	if [ -n "$$containers" ]; then docker rm -f $$containers || true; else echo "No containers to stop."; fi; \
	@images=$$(docker images -aq); \
	if [ -n "$$images" ]; then docker rmi -f $$images || true; else echo "No images to remove."; fi; \
	@echo "Pruning system (networks, volumes, build cache)..."; \
	docker system prune -af --volumes || true; \
	@echo "All images removed (where possible)."
