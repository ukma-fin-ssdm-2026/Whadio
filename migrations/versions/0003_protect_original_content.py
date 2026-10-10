"""Seal original transcript content when its creation transaction ends."""

from pathlib import Path

from alembic import op

revision: str = "0003"
down_revision: str | None = "0002"
branch_labels: tuple[str, ...] | None = None
depends_on: str | None = None


def upgrade() -> None:
    op.execute(Path(__file__).with_suffix(".sql").read_text(encoding="utf-8"))


def downgrade() -> None:
    op.execute("DROP TRIGGER original_revision_initialize ON transcript_revision")
    op.execute("DROP FUNCTION initialize_revision_transaction()")
    op.execute("DROP TRIGGER original_segment_immutable ON transcript_segment")
    op.execute("DROP TRIGGER original_speaker_immutable ON speaker")
    original_sql = (
        Path(__file__).with_name("0002_enforce_integrity.sql").read_text(encoding="utf-8")
    )
    protection = original_sql.split("CREATE FUNCTION protect_original_revision()", 1)[1]
    protection = protection.split("CREATE TRIGGER original_revision_immutable", 1)[0]
    op.execute("CREATE OR REPLACE FUNCTION protect_original_revision()" + protection)
    for table, trigger in (
        ("transcript_segment", "original_segment_immutable"),
        ("speaker", "original_speaker_immutable"),
    ):
        op.execute(
            f"CREATE TRIGGER {trigger} BEFORE UPDATE OR DELETE ON {table} "
            "FOR EACH ROW EXECUTE FUNCTION protect_original_revision()"
        )
    op.drop_column("transcript_revision", "initialization_xid")
