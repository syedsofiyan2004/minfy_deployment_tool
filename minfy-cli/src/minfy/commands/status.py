import json, sys, re, hashlib, datetime
from pathlib import Path
import boto3, click
from rich import print as rprint
from rich.console import Console
from rich.table import Table
from ..commands.config_cmd import CFG_FILE

console = Console()
def _sha(url: str) -> str:
    return hashlib.sha1(url.encode()).hexdigest()[:6]

def _bucket_name(proj: dict) -> str:
    env  = proj.get("current_env", "dev")
    slug = re.sub(r"[^a-z0-9-]", "-", proj["app_subdir"].lower()).strip("-") or "app"
    return f"minfy-{env}-{slug}-{_sha(proj['repo'])}"

def _fmt_dt(dt) -> str:
    """2025‑07‑19 14:23 UTC"""
    return dt.strftime("%Y‑%m‑%d %H:%M UTC")

@click.command("status")
@click.option("--verbose", "-v", is_flag=True, help="Show raw S3 VersionId as well")
def status_cmd(verbose):
    if not CFG_FILE.exists():
        click.secho("Run inside a minfy project.", fg="red")
        sys.exit(1)

    proj   = json.loads(Path(CFG_FILE).read_text())
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
    ts  = _fmt_dt(cur_obj["LastModified"])
    url = f"http://{bucket}.s3-website-{region}.amazonaws.com"
    table = Table(show_header=False, box=None)
    table.add_row(":globe_with_meridians:", f"[bold cyan]{url}[/]")
    table.add_row(":package:",               f"[green]{tag}[/]  ({ts})")
    if verbose:
        table.add_row(":page_facing_up:", f"VersionId = {cur_vid}")
    console.print(table)
