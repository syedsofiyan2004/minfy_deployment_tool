import json
import click
import boto3
from pathlib import Path
from ..commands.config_cmd import config_file
from ..commands.deploy import _bucket_name
from ..config import load_global

def _region():
    cfg = load_global()
    return getattr(cfg, "region", None) or "ap-south-1"

@click.command("cleanup")
def cleanup_cmd():
    """Delete all AWS S3 buckets created by minfy for this project."""
    if not config_file.exists():
        click.secho("No minfy project found. "
        "Run 'minfy init' to create a new project.", fg="red")
        return
    proj = json.loads(config_file.read_text())
    bucket = _bucket_name(proj)
    region = _region()
    s3 = boto3.resource('s3', region_name=region)
    bucket_obj = s3.Bucket(bucket)
    click.secho(f"Deleting all objects and versions in bucket: {bucket}", fg="yellow")
    try:
        bucket_obj.object_versions.delete()
        bucket_obj.delete()
        click.secho(f"Bucket {bucket} deleted.", fg="green")
    except Exception as e:
        click.secho(f"Error deleting bucket {bucket}: {e}", fg="red")
    click.secho("Monitor/EC2 resources are destroyed by 'minfy monitor disable'.", fg="cyan")
