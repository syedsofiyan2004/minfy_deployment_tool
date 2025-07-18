import json, subprocess, sys, mimetypes, shutil, uuid, tempfile, re
from pathlib import Path
import boto3, click
from rich.progress import Progress
from ..commands.config_cmd import CFG_FILE


@click.command("deploy")
def deploy_cmd():
    if not CFG_FILE.exists() or not Path("build.json").exists():
        click.secho("Run 'minfy init' and 'minfy detect' first.", fg="red")
        sys.exit(1)

    proj = json.loads(CFG_FILE.read_text())
    build = json.loads(Path("build.json").read_text())

    builder = build.get("builder", "custom")
    app_dir = Path(proj["local_path"]) / proj["app_subdir"]
    out_dir = app_dir / build["output_dir"]

    click.secho(f"Detected framework: {builder}", fg="cyan")

    npm_available = shutil.which("npm") is not None
    docker_available = shutil.which("docker") is not None
    requires_docker = build.get("requires_docker", False)

    def _docker_build() -> Path:
        tag = f"minfy-build-{uuid.uuid4().hex[:6]}"
        dockerfile = app_dir / "Dockerfile.build"
        click.secho("Building inside Docker …", fg="cyan")
        subprocess.check_call(
            ["docker", "build", "-f", str(dockerfile), "-t", tag, str(app_dir)]
        )
        cid = subprocess.check_output(["docker", "create", tag]).decode().strip()
        tmp = Path(tempfile.mkdtemp())
        subprocess.check_call(["docker", "cp", f"{cid}:/static/.", str(tmp)])
        subprocess.check_call(["docker", "rm", cid])
        return tmp

    try:
        if not requires_docker and npm_available:
            click.secho("Building on host …", fg="cyan")
            subprocess.check_call(build["build_cmd"].split(), cwd=app_dir)
            build_output = out_dir
        elif docker_available:
            build_output = _docker_build()
        else:
            click.secho("Neither Node/npm nor Docker available.", fg="red")
            sys.exit(1)
    except subprocess.CalledProcessError:
        if docker_available:
            click.secho("Host build failed → retrying in Docker …", fg="yellow")
            build_output = _docker_build()
        else:
            click.secho("Build failed and Docker not available.", fg="red")
            sys.exit(1)

    if not build_output.exists():
        click.secho(f"Missing output folder {build_output}", fg="red")
        sys.exit(1)

    env = proj.get("current_env", "dev")
    raw_slug = proj["app_subdir"]
    if raw_slug in (".", "", None):
        raw_slug = Path(proj["local_path"]).name
    slug = re.sub(r"[^a-z0-9-]", "-", raw_slug.lower())
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
            Bucket=bucket,
            VersioningConfiguration={"Status": "Enabled"},
        )

    click.secho("Uploading files …", fg="cyan")
    total = sum(1 for _ in build_output.rglob("*") if _.is_file())
    with Progress() as prog:
        task = prog.add_task("upload", total=total)
        for file in build_output.rglob("*"):
            if file.is_file():
                key = str(file.relative_to(build_output)).replace("\\", "/")
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
    click.secho(f"Deployed! → {url}", fg="green")
    click.echo(
        "Next → Check status with 'minfy status' or rollback with 'minfy rollback'."
    )
