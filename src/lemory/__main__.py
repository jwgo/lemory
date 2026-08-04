"""`python -m lemory` · the same CLI as the `lemory` entry point. The daemon
spawns the server through this module so it works from any install layout
(pipx, venv, editable) without resolving a console-script path."""
from lemory.interfaces.cli import app

if __name__ == "__main__":
    app()
