from typing import Annotated

import typer

app = typer.Typer(no_args_is_help=True, help="Whadio runtime entry points.")

# Each command imports its runtime inside the function, so `whadio web` never loads the ML stack
# and the workers never load FastAPI.


@app.command(help="Serve the Web API, the Capture API and MCP over HTTP.")
def web(
    host: Annotated[
        str, typer.Option(help="Interface to bind; use 0.0.0.0 inside a container")
    ] = "127.0.0.1",
    port: Annotated[int, typer.Option(help="Port to listen on")] = 3000,
) -> None:
    import uvicorn

    uvicorn.run("whadio.api.main:app", host=host, port=port)


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
