-- Existing originals are sealed; their creation transaction must never be inferred from xmin.
ALTER TABLE transcript_revision ADD COLUMN initialization_xid text NOT NULL DEFAULT '0';
ALTER TABLE transcript_revision ALTER COLUMN initialization_xid
    SET DEFAULT pg_current_xact_id()::text;

CREATE FUNCTION initialize_revision_transaction() RETURNS trigger
LANGUAGE plpgsql SET search_path = public, pg_temp AS $$
BEGIN
    NEW.initialization_xid := pg_current_xact_id()::text;
    RETURN NEW;
END $$;
CREATE TRIGGER original_revision_initialize BEFORE INSERT ON transcript_revision
FOR EACH ROW EXECUTE FUNCTION initialize_revision_transaction();

CREATE OR REPLACE FUNCTION protect_original_revision() RETURNS trigger
LANGUAGE plpgsql SET search_path = public, pg_temp AS $$
BEGIN
    IF TG_TABLE_NAME = 'transcript_revision' THEN
        IF (OLD.revision_type = 'original' AND EXISTS (
            SELECT 1 FROM transcript WHERE transcript_id = OLD.transcript_id
        )) OR (TG_OP = 'UPDATE' AND NEW.revision_type = 'original') THEN
            RAISE EXCEPTION 'Original revision is immutable' USING ERRCODE = '23514';
        END IF;
    ELSE
        IF TG_OP <> 'INSERT' AND EXISTS (
            SELECT 1 FROM transcript_revision
            WHERE revision_id = OLD.revision_id AND revision_type = 'original'
        ) THEN
            RAISE EXCEPTION 'Original content is immutable' USING ERRCODE = '23514';
        END IF;
        IF TG_OP <> 'DELETE' AND EXISTS (
            SELECT 1 FROM transcript_revision
            WHERE revision_id = NEW.revision_id AND revision_type = 'original'
              AND initialization_xid <> pg_current_xact_id()::text
        ) THEN
            RAISE EXCEPTION 'Original content is immutable' USING ERRCODE = '23514';
        END IF;
    END IF;
    IF TG_OP = 'DELETE' THEN RETURN OLD; END IF;
    RETURN NEW;
END $$;

DROP TRIGGER original_segment_immutable ON transcript_segment;
DROP TRIGGER original_speaker_immutable ON speaker;
CREATE TRIGGER original_segment_immutable BEFORE INSERT OR UPDATE OR DELETE ON transcript_segment
FOR EACH ROW EXECUTE FUNCTION protect_original_revision();
CREATE TRIGGER original_speaker_immutable BEFORE INSERT OR UPDATE OR DELETE ON speaker
FOR EACH ROW EXECUTE FUNCTION protect_original_revision();
