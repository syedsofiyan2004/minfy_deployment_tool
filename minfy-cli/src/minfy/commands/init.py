from pathlib import Path
import json, subprocess, sys, shutil
import click
from rich import print as rprint

WORKSPACE = Path(".") / ".minfy_workspace"
CFG_FILE = Path(".minfy.json")

DEFAULT_ENVS = {
    e: {"vars": {}, "build_cmd": "npm run build"} for e in ["dev", "staging", "prod"]
}


@click.command("init")
@click.option(
    "--repo",
    "-r",
    prompt="Git repository URL",
    help="URL of the Git repo to deploy (https://…/.git)",
)
def init_cmd(repo: str):
    """Clone repo locally and capture basic deploy settings."""
    _ensure_git()

    WORKSPACE.mkdir(exist_ok=True)
    repo_name = _repo_folder_name(repo)
    target_dir = WORKSPACE / repo_name

    if target_dir.exists():
        click.secho(f"Repo already cloned → {target_dir}", fg="yellow")
    else:
        click.secho(f"Cloning into {target_dir} …", fg="cyan")
        _run(["git", "clone", "--depth", "1", repo, str(target_dir)])

    if (target_dir / "package.json").exists() or (target_dir / "angular.json").exists():
        app_subdir = "."
        click.secho(
            "package.json found in repo root – using entire repo as app.", fg="cyan"
        )

    else:
        candidate_dirs = [
            d
            for d in target_dir.iterdir()
            if d.is_dir()
            and ((d / "package.json").exists() or (d / "angular.json").exists())
        ]

        if not candidate_dirs:
            app_subdir = "."
            click.secho(
                "No build manifest found – defaulting to repo root.", fg="yellow"
            )
        elif len(candidate_dirs) == 1:
            app_subdir = candidate_dirs[0].name
            click.secho(f"Single app folder '{app_subdir}' detected.", fg="cyan")
        else:
            click.echo("\nMultiple applications detected; choose one to deploy:")
            for idx, d in enumerate(candidate_dirs, 1):
                click.echo(f"  {idx}. {d.name}")
            choice = click.prompt(
                "Enter number", type=click.IntRange(1, len(candidate_dirs))
            )
            app_subdir = candidate_dirs[choice - 1].name
    cfg = {
        "repo": repo,
        "local_path": str(target_dir),
        "app_subdir": app_subdir,
        "current_env": "dev",
        "envs": DEFAULT_ENVS,
    }
    CFG_FILE.write_text(json.dumps(cfg, indent=2))
    click.secho("\n.minfy.json written", fg="green")

    rprint(
        "[bold]Next →[/bold] Run [cyan]minfy detect[/cyan] to analyse package.json "
        "and create the build plan."
    )


def _ensure_git():
    if shutil.which("git"):
        return
    click.secho("git is not installed or not on PATH.", fg="red")
    sys.exit(1)


def _run(cmd: list[str]):
    try:
        subprocess.check_call(cmd)
    except subprocess.CalledProcessError as e:
        click.secho(f"Command failed: {' '.join(cmd)}", fg="red")
        sys.exit(e.returncode)


def _repo_folder_name(url: str) -> str:
    name = url.rstrip("/").split("/")[-1]
    return name[:-4] if name.endswith(".git") else name
