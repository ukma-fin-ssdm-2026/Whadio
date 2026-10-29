from typing import Annotated, Final
from uuid import UUID

import typer

app = typer.Typer(no_args_is_help=True, help="Whadio runtime entry points.")
MIN_PASSWORD_LENGTH: Final = 12

# Each command imports its runtime inside the function, so `whadio web` never loads the ML stack
# and the workers never load FastAPI.


@app.command(help="Serve the Web API, the Capture API and MCP over HTTP.")
def web(
    host: Annotated[
        str, typer.Option(help="Interface to bind; use 0.0.0.0 inside a container")
    ] = "127.0.0.1",
    port: Annotated[int, typer.Option(help="Port to listen on")] = 3000,
) -> None:
    import asyncio

    import uvicorn

    config = uvicorn.Config("whadio.api.main:app", host=host, port=port)
    server = uvicorn.Server(config)
    asyncio.run(server.serve(), loop_factory=asyncio.SelectorEventLoop)


@app.command(help="Transcribe the recordings of the jobs of the transcription queue.")
def asr_worker() -> None:
    from .workers.asr.main import main

    main()


@app.command(help="Write meeting notes for the jobs of the notes queue.")
def notes_worker() -> None:
    from .workers.notes.main import main

    main()


@app.command(help="Write the OpenAPI specification to docs/api without starting the server.")
def openapi() -> None:
    from .api.app import create_app
    from .api.openapi_export import export_openapi

    for path in export_openapi(create_app()):
        typer.echo(f"Wrote {path}")


@app.command(
    help="Run recording retention and deleted-meeting cleanup; one instance per deployment."
)
def scheduler(
    *,
    once: Annotated[bool, typer.Option(help="Run one pass and exit.")] = False,
) -> None:
    from .scheduler.main import main

    if main(once=once):
        raise typer.Exit(code=1)


@app.command(help="Apply the packaged database migrations using the owner role.")
def db_upgrade(
    config: Annotated[str | None, typer.Option(help="Optional Alembic configuration file.")] = None,
) -> None:
    from alembic import command
    from alembic.config import Config

    configuration = Config(config)
    configuration.set_main_option("script_location", "whadio:migrations")
    command.upgrade(configuration, "head")


@app.command(help="Create or update a local development user and personal workspace.")
def dev_user(
    password: Annotated[
        str,
        typer.Option(
            prompt=True,
            hide_input=True,
            confirmation_prompt=True,
            help="Development account password (at least 12 characters).",
        ),
    ],
    email: Annotated[str, typer.Option(help="Development account email.")] = "margaret@whadio.dev",
    name: Annotated[
        str, typer.Option(help="Development account display name.")
    ] = "Margaret Hamilton",
) -> None:
    import asyncio

    from .dev_user import ensure_dev_user
    from .shared.database import Database, DatabaseSettings

    if len(password) < MIN_PASSWORD_LENGTH:
        raise typer.BadParameter(
            f"must contain at least {MIN_PASSWORD_LENGTH} characters",
            param_hint="--password",
        )

    async def create() -> bool:
        database = Database(DatabaseSettings.model_validate({}))
        try:
            async with database.transaction() as session:
                return await ensure_dev_user(
                    session,
                    email=email,
                    name=name,
                    password=password,
                )
        finally:
            await database.close()

    created = asyncio.run(create(), loop_factory=asyncio.SelectorEventLoop)
    action = "Created" if created else "Updated"
    typer.echo(f"{action} development user {email}")


admin_app = typer.Typer(
    help="Operator-only administrator grants; requires deployment database access."
)
app.add_typer(admin_app, name="admin")

AccountId = Annotated[UUID | None, typer.Option(help="Existing account UUID.")]
AccountEmail = Annotated[str | None, typer.Option(help="Existing account email; case is ignored.")]


def _account(user_id: UUID | None, email: str | None) -> UUID | str:
    if user_id is not None and email is None:
        return user_id
    if email is not None and user_id is None:
        return email.strip()
    raise typer.BadParameter("pass exactly one of the two", param_hint="--user-id / --email")


def _administrator(account: UUID | str, *, enabled: bool) -> None:
    import asyncio

    from pydantic import ValidationError
    from sqlalchemy.exc import SQLAlchemyError

    from .accounts.administrators import AdministratorRepository, AdministratorService
    from .shared.database import Database, DatabaseSettings
    from .shared.errors import UseCaseError

    async def change() -> None:
        database = Database(DatabaseSettings.model_validate({}))
        try:
            async with database.transaction() as session:
                service = AdministratorService(AdministratorRepository(session))
                if isinstance(account, UUID):
                    await service.set_enabled(account, enabled=enabled)
                else:
                    await service.set_enabled_by_email(account, enabled=enabled)
        finally:
            await database.close()

    try:
        asyncio.run(change(), loop_factory=asyncio.SelectorEventLoop)
    except UseCaseError:
        typer.echo("Account not found.", err=True)
        raise typer.Exit(code=1) from None
    except (SQLAlchemyError, ValidationError):
        typer.echo("Administrator database configuration or connection unavailable.", err=True)
        raise typer.Exit(code=1) from None
    typer.echo(
        "Administrator permission granted." if enabled else "Administrator permission revoked."
    )


@admin_app.command(help="Grant administrator permission to an existing account.")
def grant(user_id: AccountId = None, email: AccountEmail = None) -> None:
    _administrator(_account(user_id, email), enabled=True)


@admin_app.command(help="Revoke administrator permission; existing sessions remain signed in.")
def revoke(user_id: AccountId = None, email: AccountEmail = None) -> None:
    _administrator(_account(user_id, email), enabled=False)


links_app = typer.Typer(help="Operator-only account links; requires deployment database access.")
app.add_typer(links_app, name="links")


@links_app.command(help="Issue a registration link; a new link invalidates the earlier one.")
def registration(email: Annotated[str, typer.Option(help="Address of the new account.")]) -> None:
    import asyncio
    from datetime import UTC, datetime

    from pydantic import EmailStr, TypeAdapter, ValidationError
    from sqlalchemy.exc import SQLAlchemyError

    from .accounts.repositories import RegistrationRepository, SessionRepository
    from .accounts.services import AccountAlreadyExistsError, RegistrationIssuer
    from .shared.database import Database, DatabaseSettings
    from .shared.settings import PublicUrlSettings

    try:
        address = TypeAdapter(EmailStr).validate_python(email.strip())
    except ValidationError:
        raise typer.BadParameter("must be an email address", param_hint="--email") from None

    async def issue() -> str:
        settings = PublicUrlSettings.model_validate({})
        if settings.public_url is None:
            raise ValueError("Set WHADIO_PUBLIC_URL before issuing links.")
        database = Database(DatabaseSettings.model_validate({}))
        try:
            async with database.transaction() as session:
                link = await RegistrationIssuer(
                    RegistrationRepository(session), SessionRepository(session)
                ).issue(address, datetime.now(UTC))
            return link.url(str(settings.public_url))
        finally:
            await database.close()

    try:
        link = asyncio.run(issue(), loop_factory=asyncio.SelectorEventLoop)
    except AccountAlreadyExistsError:
        typer.echo("An account already exists for this address.", err=True)
        raise typer.Exit(code=1) from None
    except (SQLAlchemyError, ValidationError):
        typer.echo("Registration database or configuration unavailable.", err=True)
        raise typer.Exit(code=1) from None
    except ValueError as error:
        typer.echo(str(error), err=True)
        raise typer.Exit(code=1) from None
    typer.echo(link)


@links_app.command(help="Issue a password-reset link; a new link invalidates the earlier one.")
def password_reset(
    email: Annotated[str, typer.Option(help="Address of the existing account.")],
) -> None:
    import asyncio
    from datetime import UTC, datetime

    from pydantic import EmailStr, TypeAdapter, ValidationError
    from sqlalchemy.exc import SQLAlchemyError

    from .accounts.password_resets import PasswordResetService
    from .accounts.passwords import Argon2PasswordHasher
    from .accounts.reset_repository import PasswordResetRepository
    from .shared.database import Database, DatabaseSettings
    from .shared.errors import UseCaseError
    from .shared.settings import PublicUrlSettings

    try:
        address = TypeAdapter(EmailStr).validate_python(email.strip())
    except ValidationError:
        raise typer.BadParameter("must be an email address", param_hint="--email") from None

    async def issue() -> str:
        settings = PublicUrlSettings.model_validate({})
        if settings.public_url is None:
            raise ValueError("Set WHADIO_PUBLIC_URL before issuing links.")
        database = Database(DatabaseSettings.model_validate({}))
        try:
            async with database.transaction() as session:
                link = await PasswordResetService(
                    PasswordResetRepository(session), Argon2PasswordHasher()
                ).issue(address, datetime.now(UTC))
            return link.url(str(settings.public_url))
        finally:
            await database.close()

    try:
        link = asyncio.run(issue(), loop_factory=asyncio.SelectorEventLoop)
    except UseCaseError:
        typer.echo("Account not found; a reset requires an existing account.", err=True)
        raise typer.Exit(code=1) from None
    except (SQLAlchemyError, ValidationError):
        typer.echo("Password-reset database or configuration unavailable.", err=True)
        raise typer.Exit(code=1) from None
    except ValueError as error:
        typer.echo(str(error), err=True)
        raise typer.Exit(code=1) from None
    typer.echo(link)
