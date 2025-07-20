import json, sys, re, hashlib
from pathlib import Path
import click, boto3
from ..commands.config_cmd import config_file
import datetime 

def short_sha(url: str) -> str:
    return hashlib.sha1(url.encode()).hexdigest()[:6]

@click.command('rollback')
@click.option('--previous', is_flag=True, help='Rollback to the version before the current one')
def rollback_cmd(previous):
    """Revert deployment to a previous version."""
    if not config_file.exists():
        click.secho('Not a minfy project. Run minfy init first.', fg='red')
        sys.exit(1)

    proj = json.loads(config_file.read_text())
    def _bucket_name(proj: dict) -> str:
        env  = proj.get("current_env", "dev")
        raw  = proj["app_subdir"] if "app_subdir" in proj else "app"
        slug = re.sub(r"[^a-z0-9-]", "-", raw.lower()).strip("-") or "app"
        repo_url = proj.get('repo', '')
        repo_name = repo_url.rstrip('/').split('/')[-1]
        repo_name = repo_name[:-4] if repo_name.endswith('.git') else repo_name
        repo_slug = re.sub(r"[^a-z0-9-]", "-", repo_name.lower()).strip("-") or "repo"
        return f"minfy-{env}-{repo_slug}-{slug}"

    bucket = _bucket_name(proj)
    s3 = boto3.client('s3')
    # Check if bucket exists
    try:
        s3.head_bucket(Bucket=bucket)
    except s3.exceptions.ClientError:
        click.secho(f"No bucket for env '{proj.get('current_env','dev')}'. Deploy first.", fg="yellow")
        return

    versions = s3.list_object_versions(Bucket=bucket, Prefix='index.html').get('Versions', [])
    if len(versions) < 2:
        click.secho('No previous version to roll back to.', fg='yellow')
        return

    sorted_versions = sorted(versions, key=lambda v: v['LastModified'], reverse=True)
    if previous:
        target = sorted_versions[1]
        version_number = 2
    else:
        target, version_number = prompt_version(sorted_versions[:5])

    s3.copy_object(
        Bucket=bucket,
        CopySource={'Bucket': bucket, 'Key': 'index.html', 'VersionId': target['VersionId']},
        Key='index.html'
    )
    s3.put_object(Bucket=bucket, Key='__minfy_current.txt', Body=target['VersionId'])
    click.secho(f"Rolled back to Version {version_number}", fg='green')
    click.secho('Next: run minfy status to check deployment status.', fg='cyan')

def prompt_version(options):
    click.echo('Select a version to roll back to:')
    # show oldest first
    latest = options[:5]
    ordered = list(reversed(latest))
    for i, v in enumerate(ordered, start=1):
        dt = v['LastModified']
        try:
            ist = datetime.timezone(datetime.timedelta(hours=5, minutes=30))
            dt = dt.astimezone(ist)
        except Exception:
            pass
        ts = dt.strftime('%d-%m-%Y %H:%M')
        version_label = f"Version {i}: {v['VersionId']}"
        click.echo(f"  {i}. {version_label}  ({click.style(ts, fg='blue')})")
    choice = click.prompt('Choice', type=click.IntRange(1, len(ordered)))
    return ordered[choice - 1], choice


def handle_rollback(s3, bucket_name):
    """Handle the rollback logic"""
    print(f"Rolling back deployment in bucket: {bucket_name}")
    return True
