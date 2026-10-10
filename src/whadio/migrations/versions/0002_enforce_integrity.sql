REVOKE ALL ON audit_event FROM whadio_app;
GRANT SELECT, INSERT ON audit_event TO whadio_app;

-- Deferred checks allow a workspace, its Owner and its default folder to be created together.
CREATE FUNCTION check_workspace_integrity() RETURNS trigger
LANGUAGE plpgsql SET search_path = public, pg_temp AS $$
DECLARE
    target uuid;
    old_id uuid;
    new_id uuid;
BEGIN
    IF TG_OP <> 'INSERT' THEN old_id := OLD.workspace_id; END IF;
    IF TG_OP <> 'DELETE' THEN new_id := NEW.workspace_id; END IF;
    FOR target IN SELECT DISTINCT id FROM unnest(ARRAY[old_id, new_id]) AS ids(id)
                  WHERE id IS NOT NULL ORDER BY id LOOP
        PERFORM 1 FROM workspace WHERE workspace_id = target FOR UPDATE;
        IF NOT FOUND THEN CONTINUE; END IF;
        IF (SELECT count(*) FROM workspace_membership
            WHERE workspace_id = target AND role = 'Owner') <> 1 THEN
            RAISE EXCEPTION 'Workspace requires exactly one Owner' USING ERRCODE = '23514';
        END IF;
        IF (SELECT count(*) FROM folder WHERE workspace_id = target AND is_default) <> 1 THEN
            RAISE EXCEPTION 'Workspace requires exactly one default folder' USING ERRCODE = '23514';
        END IF;
    END LOOP;
    RETURN NULL;
END $$;

CREATE CONSTRAINT TRIGGER workspace_integrity AFTER INSERT OR UPDATE OR DELETE ON workspace
DEFERRABLE INITIALLY DEFERRED FOR EACH ROW EXECUTE FUNCTION check_workspace_integrity();
CREATE CONSTRAINT TRIGGER workspace_membership_integrity
AFTER INSERT OR UPDATE OR DELETE ON workspace_membership
DEFERRABLE INITIALLY DEFERRED FOR EACH ROW EXECUTE FUNCTION check_workspace_integrity();
CREATE CONSTRAINT TRIGGER folder_integrity AFTER INSERT OR UPDATE OR DELETE ON folder
DEFERRABLE INITIALLY DEFERRED FOR EACH ROW EXECUTE FUNCTION check_workspace_integrity();

CREATE FUNCTION assert_meeting_access(target uuid) RETURNS void
LANGUAGE plpgsql SET search_path = public, pg_temp AS $$
DECLARE
    scope uuid;
    mode text;
    member uuid;
BEGIN
    SELECT f.workspace_id, m.access_mode INTO scope, mode
    FROM meeting m JOIN folder f USING (folder_id)
    WHERE m.meeting_id = target FOR UPDATE OF m;
    IF NOT FOUND THEN RETURN; END IF;
    IF mode = 'restricted' AND NOT EXISTS (
        SELECT 1 FROM meeting_access_grant WHERE meeting_id = target
    ) THEN
        RAISE EXCEPTION 'Restricted meeting requires an access grant' USING ERRCODE = '23514';
    END IF;
    FOR member IN SELECT user_id FROM meeting_access_grant
                  WHERE meeting_id = target ORDER BY user_id LOOP
        PERFORM 1 FROM workspace_membership
        WHERE workspace_id = scope AND user_id = member FOR KEY SHARE;
        IF NOT FOUND THEN
            RAISE EXCEPTION 'Access grant requires workspace membership' USING ERRCODE = '23514';
        END IF;
    END LOOP;
END $$;

CREATE FUNCTION check_meeting_access() RETURNS trigger
LANGUAGE plpgsql SET search_path = public, pg_temp AS $$
BEGIN
    IF TG_OP <> 'INSERT' THEN PERFORM assert_meeting_access(OLD.meeting_id); END IF;
    IF TG_OP <> 'DELETE' THEN PERFORM assert_meeting_access(NEW.meeting_id); END IF;
    RETURN NULL;
END $$;
CREATE CONSTRAINT TRIGGER meeting_access_integrity AFTER INSERT OR UPDATE OR DELETE ON meeting
DEFERRABLE INITIALLY DEFERRED FOR EACH ROW EXECUTE FUNCTION check_meeting_access();
CREATE CONSTRAINT TRIGGER grant_integrity AFTER INSERT OR UPDATE OR DELETE ON meeting_access_grant
DEFERRABLE INITIALLY DEFERRED FOR EACH ROW EXECUTE FUNCTION check_meeting_access();

CREATE FUNCTION check_membership_access() RETURNS trigger
LANGUAGE plpgsql SET search_path = public, pg_temp AS $$
DECLARE target uuid;
BEGIN
    FOR target IN SELECT g.meeting_id FROM meeting_access_grant g
        JOIN meeting m USING (meeting_id) JOIN folder f USING (folder_id)
        WHERE g.user_id = OLD.user_id AND f.workspace_id = OLD.workspace_id
        ORDER BY g.meeting_id LOOP
        PERFORM assert_meeting_access(target);
    END LOOP;
    RETURN NULL;
END $$;
CREATE CONSTRAINT TRIGGER membership_access_integrity AFTER UPDATE OR DELETE ON workspace_membership
DEFERRABLE INITIALLY DEFERRED FOR EACH ROW EXECUTE FUNCTION check_membership_access();

CREATE FUNCTION prevent_cross_workspace_move() RETURNS trigger
LANGUAGE plpgsql SET search_path = public, pg_temp AS $$
BEGIN
    IF TG_TABLE_NAME = 'folder' THEN
        IF NEW.workspace_id IS DISTINCT FROM OLD.workspace_id THEN
            RAISE EXCEPTION 'Folders cannot move between workspaces' USING ERRCODE = '23514';
        END IF;
    ELSIF (SELECT workspace_id FROM folder WHERE folder_id = NEW.folder_id)
          IS DISTINCT FROM (SELECT workspace_id FROM folder WHERE folder_id = OLD.folder_id) THEN
        RAISE EXCEPTION 'Meetings cannot move between workspaces' USING ERRCODE = '23514';
    END IF;
    RETURN NEW;
END $$;
CREATE TRIGGER meeting_workspace BEFORE UPDATE OF folder_id ON meeting
FOR EACH ROW EXECUTE FUNCTION prevent_cross_workspace_move();
CREATE TRIGGER folder_workspace BEFORE UPDATE OF workspace_id ON folder
FOR EACH ROW EXECUTE FUNCTION prevent_cross_workspace_move();

CREATE FUNCTION check_transcript_original() RETURNS trigger
LANGUAGE plpgsql SET search_path = public, pg_temp AS $$
DECLARE
    target uuid;
    old_id uuid;
    new_id uuid;
BEGIN
    IF TG_OP <> 'INSERT' THEN old_id := OLD.transcript_id; END IF;
    IF TG_OP <> 'DELETE' THEN new_id := NEW.transcript_id; END IF;
    FOR target IN SELECT DISTINCT id FROM unnest(ARRAY[old_id, new_id]) AS ids(id)
                  WHERE id IS NOT NULL ORDER BY id LOOP
        PERFORM 1 FROM transcript WHERE transcript_id = target FOR UPDATE;
        IF NOT FOUND THEN CONTINUE; END IF;
        IF (SELECT count(*) FROM transcript_revision
            WHERE transcript_id = target AND revision_type = 'original') <> 1 THEN
            RAISE EXCEPTION 'Transcript requires one original revision' USING ERRCODE = '23514';
        END IF;
    END LOOP;
    RETURN NULL;
END $$;
CREATE CONSTRAINT TRIGGER transcript_original AFTER INSERT OR UPDATE OR DELETE ON transcript
DEFERRABLE INITIALLY DEFERRED FOR EACH ROW EXECUTE FUNCTION check_transcript_original();
CREATE CONSTRAINT TRIGGER revision_original AFTER INSERT OR UPDATE OR DELETE ON transcript_revision
DEFERRABLE INITIALLY DEFERRED FOR EACH ROW EXECUTE FUNCTION check_transcript_original();

-- Cascading deletion is allowed only when the containing transcript has already gone.
CREATE FUNCTION protect_original_revision() RETURNS trigger
LANGUAGE plpgsql SET search_path = public, pg_temp AS $$
BEGIN
    IF TG_TABLE_NAME = 'transcript_revision' THEN
        IF OLD.revision_type = 'original' AND EXISTS (
            SELECT 1 FROM transcript WHERE transcript_id = OLD.transcript_id
        ) THEN
            RAISE EXCEPTION 'Original revision is immutable' USING ERRCODE = '23514';
        END IF;
    ELSIF EXISTS (SELECT 1 FROM transcript_revision
                  WHERE revision_id = OLD.revision_id AND revision_type = 'original') THEN
        RAISE EXCEPTION 'Original content is immutable' USING ERRCODE = '23514';
    END IF;
    IF TG_OP = 'DELETE' THEN RETURN OLD; END IF;
    RETURN NEW;
END $$;
CREATE TRIGGER original_revision_immutable BEFORE UPDATE OR DELETE ON transcript_revision
FOR EACH ROW EXECUTE FUNCTION protect_original_revision();
CREATE TRIGGER original_segment_immutable BEFORE UPDATE OR DELETE ON transcript_segment
FOR EACH ROW EXECUTE FUNCTION protect_original_revision();
CREATE TRIGGER original_speaker_immutable BEFORE UPDATE OR DELETE ON speaker
FOR EACH ROW EXECUTE FUNCTION protect_original_revision();

CREATE FUNCTION reject_personal_invitation() RETURNS trigger
LANGUAGE plpgsql SET search_path = public, pg_temp AS $$
BEGIN
    IF EXISTS (SELECT 1 FROM workspace WHERE workspace_id = NEW.workspace_id AND is_personal) THEN
        RAISE EXCEPTION 'Personal workspace cannot have invitations' USING ERRCODE = '23514';
    END IF;
    RETURN NEW;
END $$;
CREATE TRIGGER invitation_workspace BEFORE INSERT OR UPDATE ON invitation
FOR EACH ROW EXECUTE FUNCTION reject_personal_invitation();
