import json, subprocess, sys, mimetypes, shutil, uuid, tempfile, re, os, textwrap
from pathlib import Path
import boto3, click
from rich.progress import Progress
from ..commands.config_cmd import CFG_FILE

def _parse_env_file(path: Path) -> dict[str, str]:
    return {
        k.strip(): v.strip()
        for line in path.read_text().splitlines()
        if "=" in line and not line.lstrip().startswith("#")
        for k, v in [line.split("=", 1)]
    }

def _inject_env_into_dockerfile(src: Path, env_keys: list[str]) -> Path:
    """Return a temp Dockerfile path with ARG+ENV lines injected."""
    tmp_dir = Path(tempfile.mkdtemp())
    dst = tmp_dir / "Dockerfile.build"
    lines = src.read_text(encoding="utf-8").splitlines(keepends=True)

    for i, l in enumerate(lines):
        if l.lower().startswith("from") and " as build" in l.lower():
            inject_at = i + 1
            break
    else:
        inject_at = 1

    inject = [f"ARG {k}\nENV {k}=${k}\n" for k in env_keys]
    new_content = "".join(lines[:inject_at] + inject + lines[inject_at:])
    dst.write_text(new_content, encoding="utf-8")
    return dst

@click.command("deploy")
@click.option(
    "--env-file", "-e",
    type=click.Path(exists=True, dir_okay=False),
    help="Path to a .env file with build‑time variables",
)
def deploy_cmd(env_file):
    if not (CFG_FILE.exists() and Path("build.json").exists()):
        click.secho("Run 'minfy init' and 'minfy detect' first.", fg="red")
        sys.exit(1)

    proj  = json.loads(Path(CFG_FILE).read_text())
    build = json.loads(Path("build.json").read_text())
    app_dir = Path(proj["local_path"]) / proj["app_subdir"]
    out_dir_hint = app_dir / build["output_dir"]
    builder = build.get("builder", "custom")
    click.secho(f"Detected framework: {builder}", fg="cyan")

    env_vars = _parse_env_file(Path(env_file)) if env_file else {}

    npm_ok      = shutil.which("npm") is not None
    docker_ok   = shutil.which("docker") is not None
    need_docker = build.get("requires_docker", False)

    def docker_build() -> Path:
        tag = f"minfy-build-{uuid.uuid4().hex[:6]}"
        # create temp Dockerfile with ARG / ENV
        dockerfile_src = app_dir / "Dockerfile.build"
        dockerfile_use = _inject_env_into_dockerfile(dockerfile_src, list(env_vars))

        args = ["docker", "build"]
        for k, v in env_vars.items():
            args += ["--build-arg", f"{k}={v}"]
        args += ["-f", str(dockerfile_use), "-t", tag, str(app_dir)]

        subprocess.check_call(args)
        cid = subprocess.check_output(["docker", "create", tag]).decode().strip()
        tmp = Path(tempfile.mkdtemp())
        subprocess.check_call(["docker", "cp", f"{cid}:/static/.", str(tmp)])
        subprocess.check_call(["docker", "rm", cid])
        return tmp

    try:
        if not need_docker and npm_ok:
            click.secho("Building on host …", fg="cyan")
            env_host = os.environ.copy() | env_vars
            try:
                subprocess.check_call(build["build_cmd"].split(), cwd=app_dir, env=env_host)
            except subprocess.CalledProcessError:
                click.secho("npm run build failed → retrying with fresh npm install …", fg="yellow")
                subprocess.check_call(
                    ["npm", "install", "--legacy-peer-deps"], cwd=app_dir, env=env_host
                )
                subprocess.check_call(build["build_cmd"].split(), cwd=app_dir, env=env_host)
            build_out = out_dir_hint
        elif docker_ok:
            click.secho("Building inside Docker …", fg="cyan")
            build_out = docker_build()
        else:
            click.secho("Neither Node/npm nor Docker available.", fg="red")
            sys.exit(1)
    except subprocess.CalledProcessError:
        if docker_ok:
            click.secho("Host build failed → retrying in Docker …", fg="yellow")
            build_out = docker_build()
        else:
            click.secho("Build failed and Docker not available.", fg="red")
            sys.exit(1)

    if not build_out.exists():
        click.secho(f"Missing output folder {build_out}", fg="red")
        sys.exit(1)

    env = proj.get("current_env", "dev")
    slug_raw = proj["app_subdir"] if proj["app_subdir"] not in (".", "") else Path(
        proj["local_path"]).name
    slug = re.sub(r"[^a-z0-9-]", "-", slug_raw.lower())
    slug = re.sub(r"-{2,}", "-", slug).strip("-") or "app"
    bucket = f"minfy-{env}-{slug}-{hash(proj['repo']) & 0xFFFF:04x}"

    region = "ap-south-1"
    s3 = boto3.client("s3", region_name=region)

    try:
        s3.head_bucket(Bucket=bucket)
    except s3.exceptions.ClientError:
        click.echo(f"Creating bucket {bucket} …")
        s3.create_bucket(
            Bucket=bucket,
            CreateBucketConfiguration={"LocationConstraint": region},
        )
        s3.put_public_access_block(
            Bucket=bucket,
            PublicAccessBlockConfiguration={
                "BlockPublicAcls": False,
                "IgnorePublicAcls": False,
                "BlockPublicPolicy": False,
                "RestrictPublicBuckets": False,
            },
        )
        s3.put_bucket_policy(
            Bucket=bucket,
            Policy=json.dumps(
                {
                    "Version": "2012-10-17",
                    "Statement": [
                        {
                            "Sid": "PublicRead",
                            "Effect": "Allow",
                            "Principal": "*",
                            "Action": ["s3:GetObject"],
                            "Resource": [f"arn:aws:s3:::{bucket}/*"],
                        }
                    ],
                }
            ),
        )
        s3.put_bucket_website(
            Bucket=bucket,
            WebsiteConfiguration={
                "IndexDocument": {"Suffix": "index.html"},
                "ErrorDocument": {"Key": "index.html"},
            },
        )
        s3.put_bucket_versioning(
            Bucket=bucket, VersioningConfiguration={"Status": "Enabled"}
        )

    click.secho("Uploading files …", fg="cyan")
    total = sum(1 for _ in build_out.rglob("*") if _.is_file())
    with Progress() as prog:
        task = prog.add_task("upload", total=total)
        for file in build_out.rglob("*"):
            if file.is_file():
                key = str(file.relative_to(build_out)).replace("\\", "/")
                s3.upload_file(
                    Filename=str(file),
                    Bucket=bucket,
                    Key=key,
                    ExtraArgs={
                        "ContentType": mimetypes.guess_type(file.name)[0]
                        or "binary/octet-stream"
                    },
                )
                prog.advance(task)

    url = f"http://{bucket}.s3-website.{region}.amazonaws.com"
    click.secho(f" Deployed! → {url}", fg="green")
    click.echo("Next → 'minfy status' or 'minfy rollback'.")
