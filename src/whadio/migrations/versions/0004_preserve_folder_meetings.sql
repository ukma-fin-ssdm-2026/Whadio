-- Duplicate names abort the migration rather than silently renaming user data.
CREATE UNIQUE INDEX uq_folder_workspace_name ON folder (workspace_id, lower(name));

CREATE FUNCTION preserve_folder_meetings() RETURNS trigger
LANGUAGE plpgsql SET search_path = public, pg_temp AS $$
DECLARE destination uuid;
BEGIN
    PERFORM 1 FROM workspace WHERE workspace_id = OLD.workspace_id FOR UPDATE;
    -- A workspace cascade has already removed the parent and must remove its meetings too.
    IF NOT FOUND THEN RETURN OLD; END IF;
    IF OLD.is_default THEN
        RAISE EXCEPTION 'Default folder cannot be deleted' USING ERRCODE = '23514';
    END IF;
    SELECT folder_id INTO destination FROM folder
    WHERE workspace_id = OLD.workspace_id AND is_default FOR KEY SHARE;
    IF NOT FOUND THEN
        RAISE EXCEPTION 'Workspace requires a default folder before deleting folders'
            USING ERRCODE = '23514';
    END IF;
    UPDATE meeting SET folder_id = destination WHERE folder_id = OLD.folder_id;
    RETURN OLD;
END $$;
CREATE TRIGGER folder_preserve_meetings BEFORE DELETE ON folder
FOR EACH ROW EXECUTE FUNCTION preserve_folder_meetings();
