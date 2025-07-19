import json, sys, re, hashlib
from pathlib import Path
import click, boto3
from ..commands.config_cmd import CFG_FILE

def _sha(url: str) -> str: return hashlib.sha1(url.encode()).hexdigest()[:6]

@click.command("rollback")
@click.option("--previous", is_flag=True, help="Rollback to the version before the current one")
def rollback_cmd(previous):
    if not CFG_FILE.exists():
        click.secho("Run inside a minfy project.", fg="red"); sys.exit(1)

    proj  = json.loads(Path(CFG_FILE).read_text())
    env   = proj.get("current_env", "dev")
    slug  = re.sub(r"[^a-z0-9-]", "-", proj["app_subdir"].lower()).strip("-") or "app"
    bucket = f"minfy-{env}-{slug}-{_sha(proj['repo'])}"

    s3 = boto3.client("s3")
    try:
        vers = s3.list_object_versions(Bucket=bucket, Prefix="index.html")["Versions"]
    except s3.exceptions.NoSuchBucket:
        click.secho(f"No bucket for env '{env}'. Nothing to roll back.", fg="yellow"); return

    vers_sorted = sorted(vers, key=lambda v: v["LastModified"], reverse=True)
    if len(vers_sorted) < 2:
        click.secho("Only one version found – nothing to roll back.", fg="yellow"); return

    target = vers_sorted[1] if previous else _choose(vers_sorted[:5])
    s3.copy_object(
        Bucket=bucket,
        CopySource={"Bucket": bucket, "Key": "index.html", "VersionId": target["VersionId"]},
        Key="index.html",
    )
    s3.put_object(Bucket=bucket, Key="__minfy_current.txt", Body=target["VersionId"])
    click.secho(f"Rolled back to {target['VersionId']}", fg="green")

def _choose(opts):
    click.echo("Select a version to serve:")
    for i, v in enumerate(opts, 1):
        click.echo(f"{i}. {v['VersionId']}  ({v['LastModified']:%Y‑%m‑%d %H:%M})")
    idx = click.prompt("Choice", type=click.IntRange(1, len(opts)))
    return opts[idx - 1]
