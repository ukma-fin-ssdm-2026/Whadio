from alembic import context

from whadio.access_policy import models as access_models
from whadio.accounts import models as account_models
from whadio.audit import models as audit_models
from whadio.capture import models as capture_models
from whadio.meetings import models as meeting_models
from whadio.notifications import models as notification_models
from whadio.processing import models as processing_models
from whadio.shared.database import Base, MigrationSettings, create_migration_engine

# Import each owner's models only at this composition root to populate migration metadata.
model_modules = (
    access_models,
    account_models,
    audit_models,
    capture_models,
    meeting_models,
    notification_models,
    processing_models,
)


def run_migrations() -> None:
    if context.is_offline_mode():
        context.configure(
            dialect_name="postgresql",
            target_metadata=Base.metadata,
            literal_binds=True,
        )
        with context.begin_transaction():
            context.run_migrations()
        return

    settings = MigrationSettings.model_validate({})
    engine = create_migration_engine(settings)
    try:
        with engine.connect() as connection:
            context.configure(connection=connection, target_metadata=Base.metadata)
            with context.begin_transaction():
                context.run_migrations()
    finally:
        engine.dispose()


run_migrations()
