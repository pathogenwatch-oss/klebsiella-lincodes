import typer

from plincer.build import app as build_app
from plincer.classify import app as classify_app

# Build failures may involve OAuth credentials.  Do not render local variables
# in Rich tracebacks, as Docker/CI logs are commonly retained and shared.
app = typer.Typer(pretty_exceptions_show_locals=False)

app.add_typer(build_app)
app.add_typer(classify_app)


if __name__ == "__main__":
    app()
