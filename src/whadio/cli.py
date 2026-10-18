from typing import Annotated, Final

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
