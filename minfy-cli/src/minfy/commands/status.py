import json, sys, re, hashlib
import datetime
from pathlib import Path
import boto3, click
from rich.console import Console
from rich.table import Table
from ..commands.config_cmd import config_file

console = Console()
def _sha(url: str) -> str:
    return hashlib.sha1(url.encode()).hexdigest()[:6]

def _bucket_name(proj: dict) -> str:
    env  = proj.get("current_env", "dev")
    raw  = proj["app_subdir"] if "app_subdir" in proj else "app"
    slug = re.sub(r"[^a-z0-9-]", "-", raw.lower()).strip("-") or "app"
    repo_url = proj.get('repo', '')
    repo_name = repo_url.rstrip('/').split('/')[-1]
    repo_name = repo_name[:-4] if repo_name.endswith('.git') else repo_name
    repo_slug = re.sub(r"[^a-z0-9-]", "-", repo_name.lower()).strip("-") or "repo"
    return f"minfy-{env}-{repo_slug}-{slug}"

def format_time(dt) -> str:
    try:
        ist = datetime.timezone(datetime.timedelta(hours=5, minutes=30))
        dt = dt.astimezone(ist)
    except Exception:
        pass
    return click.style(dt.strftime('%d-%m-%Y %H:%M'), fg='blue')

@click.command("status")
@click.option("--verbose", "-v", is_flag=True, help="Show raw S3 VersionId as well")
def status_cmd(verbose):
    """Show current deployment URL and version history."""
    if not config_file.exists():
        click.secho("Run inside a minfy project.", fg="red")
        sys.exit(1)

    proj   = json.loads(Path(config_file).read_text())
    bucket = _bucket_name(proj)
    region = "ap-south-1"
    s3     = boto3.client("s3", region_name=region)
    try:
        cur_vid = s3.get_object(Bucket=bucket, Key="__minfy_current.txt")["Body"].read().decode()
    except s3.exceptions.NoSuchBucket:
        click.secho(f"No bucket for env '{proj.get('current_env','dev')}'. Deploy first.", fg="yellow")
        return
    except s3.exceptions.NoSuchKey:
        click.secho("Bucket exists but no deploy marker found. Deploy first.", fg="yellow")
        return

    vers = s3.list_object_versions(Bucket=bucket, Prefix="index.html")["Versions"]
    vers_sorted = sorted(vers, key=lambda v: v["LastModified"], reverse=True)
    idx = next((i for i, v in enumerate(vers_sorted) if v["VersionId"] == cur_vid), None)
    cur_obj = vers_sorted[idx] if idx is not None else vers_sorted[0]
    tag = f"deployment #{len(vers_sorted) - idx}" if idx is not None else "(unknown)"
    ts  = format_time(cur_obj['LastModified'])
    url = f"http://{bucket}.s3-website.{region}.amazonaws.com"
    table = Table(show_header=False, box=None)
    table.add_row("URL:", f"[bold cyan]{url}[/]")
    table.add_row("Current:", f"[green]{tag}[/]  ({ts})")
    if verbose:
        table.add_row("Version:", f"VersionId = {cur_vid}")
    console.print(table)