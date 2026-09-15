-- C3-T15: application-owned background assets and explicitly saved bindings.
--
-- Images are candidates until a binding is saved.  The file bytes live under
-- the Chronicle background volume; these rows retain the immutable identity,
-- validation metadata and audit trail.  No row is a Loom Runtime/World/
-- Timeline/Work/Binding authority (Architecture Amendment 0006).

CREATE TABLE IF NOT EXISTS chronicle.background_assets (
    asset_id uuid PRIMARY KEY CHECK (uuid_extract_version(asset_id) = 7),
    source text,
    era text,
    prompt text,
    metadata jsonb NOT NULL DEFAULT '{}'::jsonb
        CHECK (jsonb_typeof(metadata) = 'object'),
    created_at timestamptz NOT NULL DEFAULT now()
);

CREATE TABLE IF NOT EXISTS chronicle.background_asset_versions (
    asset_version_id uuid PRIMARY KEY CHECK (uuid_extract_version(asset_version_id) = 7),
    asset_id uuid NOT NULL REFERENCES chronicle.background_assets(asset_id) ON DELETE RESTRICT,
    version_no integer NOT NULL CHECK (version_no >= 1),
    content_sha256 text NOT NULL CHECK (content_sha256 ~ '^[0-9a-f]{64}$'),
    media_type text NOT NULL CHECK (media_type IN ('image/png', 'image/jpeg', 'image/webp')),
    image_format text NOT NULL CHECK (image_format IN ('png', 'jpeg', 'webp')),
    original_filename text NOT NULL CHECK (original_filename <> ''),
    byte_size bigint NOT NULL CHECK (byte_size > 0),
    width integer NOT NULL CHECK (width > 0),
    height integer NOT NULL CHECK (height > 0),
    storage_key text NOT NULL UNIQUE CHECK (storage_key <> ''),
    created_at timestamptz NOT NULL DEFAULT now(),
    UNIQUE (asset_id, version_no)
);

CREATE INDEX IF NOT EXISTS background_asset_versions_asset_idx
    ON chronicle.background_asset_versions(asset_id, version_no DESC);
CREATE INDEX IF NOT EXISTS background_asset_versions_content_idx
    ON chronicle.background_asset_versions(content_sha256);

-- A binding is mutable only through the explicit replace/disable operations in
-- background_assets.py.  Every such mutation receives a monotonic revision,
-- etag and an immutable audit row.  Paragraph ordinals are denormalized here
-- solely to make the overlap invariant enforceable and queryable.
CREATE TABLE IF NOT EXISTS chronicle.background_bindings (
    binding_id uuid PRIMARY KEY CHECK (uuid_extract_version(binding_id) = 7),
    edition_version text NOT NULL
        REFERENCES chronicle.history_editions(edition_version) ON DELETE RESTRICT,
    start_paragraph_id text NOT NULL,
    end_paragraph_id text NOT NULL,
    start_ordinal integer NOT NULL CHECK (start_ordinal >= 0),
    end_ordinal integer NOT NULL CHECK (end_ordinal >= start_ordinal),
    asset_id uuid NOT NULL REFERENCES chronicle.background_assets(asset_id) ON DELETE RESTRICT,
    asset_version_id uuid NOT NULL
        REFERENCES chronicle.background_asset_versions(asset_version_id) ON DELETE RESTRICT,
    display jsonb NOT NULL CHECK (jsonb_typeof(display) = 'object'),
    status text NOT NULL CHECK (status IN ('active', 'disabled')),
    revision integer NOT NULL DEFAULT 1 CHECK (revision >= 1),
    etag text NOT NULL UNIQUE CHECK (etag <> ''),
    saved_by text NOT NULL CHECK (saved_by <> ''),
    created_at timestamptz NOT NULL DEFAULT now(),
    updated_at timestamptz NOT NULL DEFAULT now(),
    disabled_at timestamptz,
    FOREIGN KEY (edition_version, start_paragraph_id)
        REFERENCES chronicle.history_edition_paragraph_index(edition_version, paragraph_id)
        ON DELETE RESTRICT,
    FOREIGN KEY (edition_version, end_paragraph_id)
        REFERENCES chronicle.history_edition_paragraph_index(edition_version, paragraph_id)
        ON DELETE RESTRICT,
    CHECK ((status = 'active' AND disabled_at IS NULL)
        OR (status = 'disabled' AND disabled_at IS NOT NULL))
);

CREATE INDEX IF NOT EXISTS background_bindings_lookup_idx
    ON chronicle.background_bindings(edition_version, start_ordinal, end_ordinal)
    WHERE status = 'active';
CREATE INDEX IF NOT EXISTS background_bindings_asset_idx
    ON chronicle.background_bindings(asset_id, status);

CREATE TABLE IF NOT EXISTS chronicle.background_binding_audit (
    audit_id uuid PRIMARY KEY CHECK (uuid_extract_version(audit_id) = 7),
    binding_id uuid NOT NULL REFERENCES chronicle.background_bindings(binding_id) ON DELETE RESTRICT,
    action text NOT NULL CHECK (action IN ('created', 'replaced', 'disabled')),
    revision integer NOT NULL CHECK (revision >= 1),
    actor text NOT NULL CHECK (actor <> ''),
    previous_asset_version_id uuid
        REFERENCES chronicle.background_asset_versions(asset_version_id) ON DELETE RESTRICT,
    asset_version_id uuid NOT NULL
        REFERENCES chronicle.background_asset_versions(asset_version_id) ON DELETE RESTRICT,
    previous_start_paragraph_id text,
    previous_end_paragraph_id text,
    start_paragraph_id text NOT NULL,
    end_paragraph_id text NOT NULL,
    display jsonb NOT NULL CHECK (jsonb_typeof(display) = 'object'),
    created_at timestamptz NOT NULL DEFAULT now()
);

CREATE INDEX IF NOT EXISTS background_binding_audit_binding_idx
    ON chronicle.background_binding_audit(binding_id, revision);

CREATE OR REPLACE FUNCTION chronicle.forbid_background_asset_mutation()
RETURNS trigger AS $$
BEGIN
    RAISE EXCEPTION 'Chronicle background asset rows are immutable; upload a new asset version instead';
    RETURN NULL;
END;
$$ LANGUAGE plpgsql;

DROP TRIGGER IF EXISTS background_assets_immutable ON chronicle.background_assets;
CREATE TRIGGER background_assets_immutable
    BEFORE UPDATE OR DELETE ON chronicle.background_assets
    FOR EACH ROW EXECUTE FUNCTION chronicle.forbid_background_asset_mutation();

DROP TRIGGER IF EXISTS background_asset_versions_immutable ON chronicle.background_asset_versions;
CREATE TRIGGER background_asset_versions_immutable
    BEFORE UPDATE OR DELETE ON chronicle.background_asset_versions
    FOR EACH ROW EXECUTE FUNCTION chronicle.forbid_background_asset_mutation();

DROP TRIGGER IF EXISTS background_binding_audit_immutable ON chronicle.background_binding_audit;
CREATE TRIGGER background_binding_audit_immutable
    BEFORE UPDATE OR DELETE ON chronicle.background_binding_audit
    FOR EACH ROW EXECUTE FUNCTION chronicle.forbid_background_asset_mutation();

CREATE OR REPLACE FUNCTION chronicle.enforce_background_asset_version()
RETURNS trigger AS $$
DECLARE parent_asset uuid;
DECLARE expected_version integer;
BEGIN
    SELECT asset_id INTO parent_asset
      FROM chronicle.background_assets WHERE asset_id = NEW.asset_id;
    IF parent_asset IS NULL THEN
        RAISE EXCEPTION 'background asset % does not exist', NEW.asset_id;
    END IF;
    SELECT coalesce(max(version_no), 0) + 1 INTO expected_version
      FROM chronicle.background_asset_versions
      WHERE asset_id = NEW.asset_id;
    IF NEW.version_no <> expected_version THEN
        RAISE EXCEPTION 'background asset version is not the next immutable version';
    END IF;
    RETURN NEW;
END;
$$ LANGUAGE plpgsql;

DROP TRIGGER IF EXISTS enforce_background_asset_version ON chronicle.background_asset_versions;
CREATE TRIGGER enforce_background_asset_version
    BEFORE INSERT ON chronicle.background_asset_versions
    FOR EACH ROW EXECUTE FUNCTION chronicle.enforce_background_asset_version();

CREATE OR REPLACE FUNCTION chronicle.enforce_background_binding_asset()
RETURNS trigger AS $$
DECLARE version_asset uuid;
DECLARE start_value integer;
DECLARE end_value integer;
BEGIN
    SELECT asset_id INTO version_asset
      FROM chronicle.background_asset_versions
      WHERE asset_version_id = NEW.asset_version_id;
    IF version_asset IS NULL OR version_asset IS DISTINCT FROM NEW.asset_id THEN
        RAISE EXCEPTION 'background binding asset and asset version do not match';
    END IF;
    SELECT ordinal INTO start_value
      FROM chronicle.history_edition_paragraph_index
      WHERE edition_version = NEW.edition_version
        AND paragraph_id = NEW.start_paragraph_id;
    SELECT ordinal INTO end_value
      FROM chronicle.history_edition_paragraph_index
      WHERE edition_version = NEW.edition_version
        AND paragraph_id = NEW.end_paragraph_id;
    IF start_value IS NULL OR end_value IS NULL
       OR NEW.start_ordinal IS DISTINCT FROM start_value
       OR NEW.end_ordinal IS DISTINCT FROM end_value
       OR NEW.start_ordinal > NEW.end_ordinal THEN
        RAISE EXCEPTION 'background binding paragraph range is not in the selected edition';
    END IF;
    IF NEW.status = 'active' THEN
        PERFORM pg_advisory_xact_lock(hashtextextended(NEW.edition_version, 0));
        IF EXISTS (
            SELECT 1 FROM chronicle.background_bindings existing
            WHERE existing.edition_version = NEW.edition_version
              AND existing.status = 'active'
              AND existing.binding_id <> NEW.binding_id
              AND existing.start_ordinal <= NEW.end_ordinal
              AND existing.end_ordinal >= NEW.start_ordinal
            FOR UPDATE
        ) THEN
            RAISE EXCEPTION 'background binding overlaps an active binding in the selected edition';
        END IF;
    END IF;
    RETURN NEW;
END;
$$ LANGUAGE plpgsql;

DROP TRIGGER IF EXISTS enforce_background_binding_asset ON chronicle.background_bindings;
CREATE TRIGGER enforce_background_binding_asset
    BEFORE INSERT OR UPDATE ON chronicle.background_bindings
    FOR EACH ROW EXECUTE FUNCTION chronicle.enforce_background_binding_asset();
