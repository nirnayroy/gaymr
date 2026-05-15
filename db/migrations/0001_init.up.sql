CREATE TABLE users (
    id              UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    clerk_subject   TEXT NOT NULL UNIQUE,
    email           TEXT,
    created_at      TIMESTAMPTZ NOT NULL DEFAULT now()
);

CREATE TYPE session_status AS ENUM (
    'pending', 'provisioning', 'ready', 'terminating', 'terminated', 'error'
);

CREATE TABLE sessions (
    id              TEXT PRIMARY KEY,
    user_id         UUID NOT NULL REFERENCES users(id) ON DELETE CASCADE,
    sku             TEXT NOT NULL,
    region          TEXT NOT NULL,
    status          session_status NOT NULL DEFAULT 'pending',
    instance_id     TEXT,
    public_ip       TEXT,
    error_reason    TEXT,
    created_at      TIMESTAMPTZ NOT NULL DEFAULT now(),
    updated_at      TIMESTAMPTZ NOT NULL DEFAULT now(),
    ready_at        TIMESTAMPTZ,
    terminated_at   TIMESTAMPTZ
);

CREATE INDEX sessions_user_id_idx ON sessions(user_id);
CREATE INDEX sessions_status_idx ON sessions(status) WHERE status NOT IN ('terminated', 'error');

CREATE TABLE gpu_skus (
    sku             TEXT NOT NULL,
    region          TEXT NOT NULL,
    family          TEXT NOT NULL,
    vcpu            INT NOT NULL,
    gpu             TEXT NOT NULL,
    hourly_cents    INT NOT NULL,
    PRIMARY KEY (sku, region)
);

INSERT INTO gpu_skus (sku, region, family, vcpu, gpu, hourly_cents) VALUES
    ('g4dn.xlarge', 'ap-south-1', 'g4dn', 4, 'Tesla T4', 53);
