import json
import subprocess
import sys
import mimetypes
import shutil
import uuid
import tempfile
import re
import os
import hashlib
from pathlib import Path
import boto3
import click
from rich.progress import Progress
from ..commands.config_cmd import config_file

def _parse_env_file(path: Path) -> dict[str, str]:
    env_vars = {}
    for line in path.read_text().splitlines():
        if "=" in line and not line.lstrip().startswith("#"):
            k, v = line.split("=", 1)
            env_vars[k.strip()] = v.strip()
    return env_vars

def _inject_env_into_dockerfile(src: Path, env_keys: list[str]) -> Path:
    dst = Path(tempfile.mkdtemp()) / "Dockerfile.build"
    lines = src.read_text(encoding="utf-8").splitlines(keepends=True)
    inject_at = 1
    for i, l in enumerate(lines):
        if l.lower().startswith("from") and " as build" in l.lower():
            inject_at = i + 1
            break
    inject = [f"ARG {k}\nENV {k}=${k}\n" for k in env_keys]
    dst.write_text("".join(lines[:inject_at] + inject + lines[inject_at:]), encoding="utf-8")
    return dst

def _upload_directory(s3, bucket: str, source: Path):
    files = [f for f in source.rglob('*') if f.is_file()]
    total = len(files)
    with Progress() as prog:
        task = prog.add_task('upload', total=total)
        for f in files:
            key = f.relative_to(source).as_posix()
            s3.upload_file(
                str(f), bucket, key,
                ExtraArgs={'ContentType': mimetypes.guess_type(f.name)[0] or 'application/octet-stream'}
            )
            prog.advance(task)

def _sha(url: str) -> str:
    return hashlib.sha1(url.encode()).hexdigest()[:6]

def _bucket_name(proj: dict) -> str:
    env = proj.get("current_env", "dev")
    raw = proj["app_subdir"] or Path(proj["local_path"]).name
    slug = re.sub(r"[^a-z0-9-]", "-", raw.lower()).strip("-") or "app"
    repo_url = proj.get('repo', '')
    repo_name = repo_url.rstrip('/').split('/')[-1]
    if repo_name.endswith('.git'):
        repo_name = repo_name[:-4]
    repo_slug = re.sub(r"[^a-z0-9-]", "-", repo_name.lower()).strip("-") or "repo"
    return f"minfy-{env}-{repo_slug}-{slug}"

def ensure_bucket_exists(s3, bucket: str, region: str):
    try:
        s3.head_bucket(Bucket=bucket)
    except s3.exceptions.ClientError:
        click.echo(f"Creating bucket {bucket} …")
        s3.create_bucket(
            Bucket=bucket,
            CreateBucketConfiguration={'LocationConstraint': region}
        )
        s3.put_public_access_block(
            Bucket=bucket,
            PublicAccessBlockConfiguration={k: False for k in (
                'BlockPublicAcls','IgnorePublicAcls',
                'BlockPublicPolicy','RestrictPublicBuckets')}
        )
        s3.put_bucket_policy(
            Bucket=bucket,
            Policy=json.dumps({
                'Version': '2012-10-17',
                'Statement': [{
                    'Sid': 'PublicRead',
                    'Effect': 'Allow',
                    'Principal': '*',
                    'Action': ['s3:GetObject'],
                    'Resource': [f'arn:aws:s3:::{bucket}/*']
                }]
            })
        )
        s3.put_bucket_website(
            Bucket=bucket,
            WebsiteConfiguration={
                'IndexDocument': {'Suffix': 'index.html'},
                'ErrorDocument': {'Key': 'index.html'}
            }
        )
        s3.put_bucket_versioning(
            Bucket=bucket,
            VersioningConfiguration={'Status': 'Enabled'}
        )

@click.command("deploy")
@click.option("--env-file", "-e", type=click.Path(exists=True, dir_okay=False),
              help="Path to a .env file with build-time variables")
def deploy_cmd(env_file):
    if not (config_file.exists() and Path("build.json").exists()):
        click.secho("Run 'minfy init' and 'minfy detect' first.", fg="red")
        sys.exit(1)

    project_info = json.loads(config_file.read_text())
    build_plan = json.loads(Path("build.json").read_text())
    if build_plan.get('builder') == 'next':
        build_plan['build_cmd'] = 'npm ci --legacy-peer_deps && npx next build'
    project_path = Path(project_info["local_path"]) / project_info["app_subdir"]
    output_dir = project_path / build_plan["output_dir"]
    env_vars = _parse_env_file(Path(env_file)) if env_file else {}

    click.secho(f"Detected framework: {build_plan.get('builder','custom')}", fg="cyan")

    docker_installed = shutil.which("docker")
    npm_installed = shutil.which("npm")
    framework = build_plan.get("builder", "custom")
    use_docker = True if framework == 'next' else build_plan.get("requires_docker", False)
    if framework == "angular" and "NODE_OPTIONS" not in env_vars:
        env_vars["NODE_OPTIONS"] = "--openssl-legacy-provider"

    def _docker_build() -> Path:
        tag = f"minfy-build-{uuid.uuid4().hex[:6]}"
        df = _inject_env_into_dockerfile(project_path / "Dockerfile.build", list(env_vars))
        cmd = ["docker", "build", "-f", str(df), "-t", tag]
        for k, v in env_vars.items():
            cmd += ["--build-arg", f"{k}={v}"]
        cmd.append(str(project_path))
        subprocess.check_call(cmd)
        cid = subprocess.check_output(["docker", "create", tag]).decode().strip()
        tmp = Path(tempfile.mkdtemp())
        subprocess.check_call(["docker", "cp", f"{cid}:/static/.", str(tmp)])
        subprocess.check_call(["docker", "rm", cid])
        return tmp

    try:
        if not use_docker and npm_installed:
            click.secho("Building on host …", fg="cyan")
            host_env = os.environ | env_vars
            subprocess.check_call(build_plan["build_cmd"], cwd=project_path, env=host_env, shell=True)
            deployment_folder = output_dir
        elif docker_installed:
            click.secho("Building inside Docker …", fg="cyan")
            deployment_folder = _docker_build()
        else:
            click.secho("Docker is required for builds; install Docker and retry.", fg="red")
            sys.exit(1)
    except Exception as err:
        click.secho(f"Build failed: {err}", fg="red")
        sys.exit(1)

    if not deployment_folder.exists():
        click.secho(f"Missing output folder {deployment_folder}", fg="red")
        sys.exit(1)

    index_paths = list(deployment_folder.rglob('index.html'))
    if index_paths:
        index_paths.sort(key=lambda p: len(p.relative_to(deployment_folder).parts))
        index_path = index_paths[0]
    else:
        click.secho("Error: No index.html found anywhere in the build output", fg="red")
        click.secho("Deployment cannot continue without index.html", fg="red")
        sys.exit(1)

    bucket = _bucket_name(project_info)
    region = "ap-south-1"
    s3 = boto3.client("s3", region_name=region)

    click.secho(f"Build output directory: {deployment_folder}", fg="cyan")
    click.secho(f"Files in output directory: {[f.name for f in deployment_folder.iterdir() if f.is_file()]}", fg="cyan")

    ensure_bucket_exists(s3, bucket, region)
    _upload_directory(s3, bucket, deployment_folder)

    if index_path != deployment_folder / 'index.html':
        s3.upload_file(str(index_path), bucket, 'index.html',
            ExtraArgs={'ContentType': 'text/html'})
    try:
        head_ver = s3.head_object(Bucket=bucket, Key='index.html')['VersionId']
        s3.put_object(Bucket=bucket, Key='__minfy_current.txt', Body=head_ver)
    except Exception as err:
        click.secho(f"Warning: unable to set version marker for index.html: {err}", fg='yellow')
    click.secho(f'Deployed: http://{bucket}.s3-website.{region}.amazonaws.com', fg='green')
    click.echo("Next: run minfy status or minfy rollback to manage deployments.")
