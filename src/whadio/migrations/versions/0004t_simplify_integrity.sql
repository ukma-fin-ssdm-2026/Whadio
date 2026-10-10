CREATE FUNCTION prevent_folder_workspace_move() RETURNS trigger
LANGUAGE plpgsql SET search_path = public, pg_temp AS $$
BEGIN
    IF NEW.workspace_id IS DISTINCT FROM OLD.workspace_id THEN
        RAISE EXCEPTION 'Folders cannot move between workspaces' USING ERRCODE = '23514';
    END IF;
    RETURN NEW;
END $$;

CREATE FUNCTION prevent_meeting_workspace_move() RETURNS trigger
LANGUAGE plpgsql SET search_path = public, pg_temp AS $$
BEGIN
    IF (SELECT workspace_id FROM folder WHERE folder_id = NEW.folder_id)
       IS DISTINCT FROM (SELECT workspace_id FROM folder WHERE folder_id = OLD.folder_id) THEN
        RAISE EXCEPTION 'Meetings cannot move between workspaces' USING ERRCODE = '23514';
    END IF;
    RETURN NEW;
END $$;

CREATE FUNCTION protect_original_revision_row() RETURNS trigger
LANGUAGE plpgsql SET search_path = public, pg_temp AS $$
BEGIN
    IF (OLD.revision_type = 'original' AND EXISTS (
        SELECT 1 FROM transcript WHERE transcript_id = OLD.transcript_id
    )) OR (TG_OP = 'UPDATE' AND NEW.revision_type = 'original') THEN
        RAISE EXCEPTION 'Original revision is immutable' USING ERRCODE = '23514';
    END IF;
    IF TG_OP = 'DELETE' THEN RETURN OLD; END IF;
    RETURN NEW;
END $$;

CREATE FUNCTION protect_original_segment() RETURNS trigger
LANGUAGE plpgsql SET search_path = public, pg_temp AS $$
BEGIN
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
    IF TG_OP = 'DELETE' THEN RETURN OLD; END IF;
    RETURN NEW;
END $$;

CREATE FUNCTION protect_original_speaker() RETURNS trigger
LANGUAGE plpgsql SET search_path = public, pg_temp AS $$
BEGIN
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
    IF TG_OP = 'DELETE' THEN RETURN OLD; END IF;
    RETURN NEW;
END $$;
