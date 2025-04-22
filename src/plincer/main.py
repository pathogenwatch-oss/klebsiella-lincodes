import typer

from plincer.build import app as build_app
from plincer.classify import app as classify_app

app = typer.Typer()

app.add_typer(build_app)
app.add_typer(classify_app)


if __name__ == "__main__":
    app()
