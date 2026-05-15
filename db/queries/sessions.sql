-- name: CreateSession :one
INSERT INTO sessions (id, user_id, sku, region, status)
VALUES ($1, $2, $3, $4, 'pending')
RETURNING *;

-- name: GetSession :one
SELECT * FROM sessions WHERE id = $1;

-- name: GetSessionForUser :one
SELECT * FROM sessions WHERE id = $1 AND user_id = $2;

-- name: ListSessionsForUser :many
SELECT * FROM sessions WHERE user_id = $1 ORDER BY created_at DESC LIMIT $2;

-- name: LockSession :one
SELECT * FROM sessions WHERE id = $1 FOR UPDATE;

-- name: SetSessionStatus :exec
UPDATE sessions
SET status = $2, updated_at = now()
WHERE id = $1;

-- name: SetSessionReady :exec
UPDATE sessions
SET status = 'ready', instance_id = $2, public_ip = $3, ready_at = now(), updated_at = now()
WHERE id = $1;

-- name: SetSessionError :exec
UPDATE sessions
SET status = 'error', error_reason = $2, updated_at = now()
WHERE id = $1;

-- name: SetSessionTerminated :exec
UPDATE sessions
SET status = 'terminated', terminated_at = now(), updated_at = now()
WHERE id = $1;
