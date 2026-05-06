SHELL := /bin/bash
DB_URL ?= postgres://gaymr:gaymr@localhost:5432/gaymr?sslmode=disable

.PHONY: up down logs migrate migrate-create sqlc run-api run-orch lint test build tidy

up:
	docker compose up -d

down:
	docker compose down

logs:
	docker compose logs -f

migrate:
	@command -v migrate >/dev/null || { echo "install: brew install golang-migrate"; exit 1; }
	migrate -path db/migrations -database "$(DB_URL)" up

migrate-create:
	@test -n "$(name)" || { echo "usage: make migrate-create name=add_foo"; exit 1; }
	migrate create -ext sql -dir db/migrations -seq $(name)

sqlc:
	@command -v sqlc >/dev/null || { echo "install: brew install sqlc"; exit 1; }
	sqlc generate

run-api:
	go run ./cmd/api

run-orch:
	go run ./cmd/orchestrator

lint:
	go vet ./...

test:
	go test ./...

build:
	go build ./...

tidy:
	go mod tidy
