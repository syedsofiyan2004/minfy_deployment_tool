import json
from pathlib import Path
import click
from rich import print as rprint

CFG_FILE = Path(".minfy.json")
DEFAULT_ENV = "dev"
DEFAULT_ENVS = {
    e: {"vars": {}, "build_cmd": "npm run build"} for e in ["dev", "staging", "prod"]
}


def _load() -> dict:
    cfg = {}
    if CFG_FILE.exists():
        cfg = json.loads(CFG_FILE.read_text())

    cfg.setdefault("current_env", DEFAULT_ENV)
    cfg.setdefault("envs", DEFAULT_ENVS.copy())
    return cfg


def _save(cfg: dict):
    CFG_FILE.write_text(json.dumps(cfg, indent=2))


@click.group("config")
def config_grp():
    """Manage per‑project config (env vars, build settings, environments)."""
    pass


@config_grp.command("set")
@click.argument("pair")
def set_var(pair):
    """Add or update an environment variable:  KEY=VALUE"""
    if "=" not in pair:
        click.secho("Use KEY=VALUE syntax.", fg="red")
        raise click.Abort()

    key, val = pair.split("=", 1)
    cfg = _load()
    env = cfg["current_env"]
    cfg["envs"][env]["vars"][key] = val
    _save(cfg)
    click.secho(f"✓ {key} set for [{env}]", fg="green")
    rprint("[bold]Next →[/bold] Run [cyan]minfy deploy[/cyan] when ready.")


@config_grp.command("list")
def list_vars():
    """Show variables & build cmd for the active environment."""
    cfg = _load()
    env = cfg["current_env"]
    data = cfg["envs"][env]
    rprint(f"[bold cyan]Environment → {env}[/bold cyan]")
    rprint(f"Build command : {data['build_cmd']}")
    rprint("Vars:")
    for k, v in data["vars"].items():
        rprint(f"  {k} = {v}")
    rprint(
        "[bold]Next →[/bold] Use [cyan]minfy config env NAME[/cyan] "
        "to switch environments."
    )


@config_grp.command("env")
@click.argument("name")
def switch_env(name):
    """Switch active environment (dev / staging / prod)."""
    cfg = _load()
    if name not in cfg["envs"]:
        click.secho(
            f"Unknown env '{name}'. Available: {', '.join(cfg['envs'].keys())}",
            fg="red",
        )
        raise click.Abort()

    cfg["current_env"] = name
    _save(cfg)
    click.secho(f"Current environment set to {name}", fg="green")
    rprint(
        "[bold]Next →[/bold] Set variables with "
        "[cyan]minfy config set KEY=VALUE[/cyan] or run [cyan]minfy deploy[/cyan]."
    )
