-- name: GetUserByClerkSubject :one
SELECT * FROM users WHERE clerk_subject = $1;

-- name: UpsertUser :one
INSERT INTO users (clerk_subject, email)
VALUES ($1, $2)
ON CONFLICT (clerk_subject) DO UPDATE SET email = EXCLUDED.email
RETURNING *;
