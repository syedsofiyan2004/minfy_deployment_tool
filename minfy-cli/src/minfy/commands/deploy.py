import json, subprocess, sys, mimetypes, shutil, uuid, tempfile, re, os, hashlib
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
    dst = Path(tempfile.mkdtemp()) / "Dockerfile.build"
    lines = src.read_text(encoding="utf-8").splitlines(keepends=True)
    inject_at = next(
        (i + 1 for i, l in enumerate(lines) if l.lower().startswith("from") and " as build" in l.lower()),
        1,
    )
    inject = [f"ARG {k}\nENV {k}=${k}\n" for k in env_keys]
    dst.write_text("".join(lines[:inject_at] + inject + lines[inject_at:]), encoding="utf-8")
    return dst

def _sha(url: str) -> str:              
    return hashlib.sha1(url.encode()).hexdigest()[:6]

def _bucket_name(proj: dict) -> str:
    env  = proj.get("current_env", "dev")
    raw  = proj["app_subdir"] or Path(proj["local_path"]).name
    slug = re.sub(r"[^a-z0-9-]", "-", raw.lower()).strip("-") or "app"
    return f"minfy-{env}-{slug}-{_sha(proj['repo'])}"

@click.command("deploy")
@click.option("--env-file", "-e", type=click.Path(exists=True, dir_okay=False),
              help="Path to a .env file with build‑time variables")
def deploy_cmd(env_file):
    if not (CFG_FILE.exists() and Path("build.json").exists()):
        click.secho("Run 'minfy init' and 'minfy detect' first.", fg="red"); sys.exit(1)

    proj   = json.loads(Path(CFG_FILE).read_text())
    build  = json.loads(Path("build.json").read_text())
    appdir = Path(proj["local_path"]) / proj["app_subdir"]
    outdir_hint = appdir / build["output_dir"]
    envvars = _parse_env_file(Path(env_file)) if env_file else {}

    click.secho(f"Detected framework: {build.get('builder','custom')}", fg="cyan")

    docker_ok = shutil.which("docker")
    npm_ok    = shutil.which("npm")
    need_docker = build.get("requires_docker", False)
    builder     = build.get("builder", "custom")
    if builder == "angular" and "NODE_OPTIONS" not in envvars:
        envvars["NODE_OPTIONS"] = "--openssl-legacy-provider"
    def _docker_build() -> Path:
        tag = f"minfy-build-{uuid.uuid4().hex[:6]}"
        df  = _inject_env_into_dockerfile(appdir / "Dockerfile.build", list(envvars))
        cmd = ["docker", "build", "-f", str(df), "-t", tag]
        for k, v in envvars.items():
            cmd += ["--build-arg", f"{k}={v}"]
        cmd.append(str(appdir))
        subprocess.check_call(cmd)
        cid = subprocess.check_output(["docker", "create", tag]).decode().strip()
        tmp = Path(tempfile.mkdtemp())
        subprocess.check_call(["docker", "cp", f"{cid}:/static/.", str(tmp)])
        subprocess.check_call(["docker", "rm", cid])
        return tmp
    try:
        if not need_docker and npm_ok:
            click.secho("Building on host …", fg="cyan")
            env_host = os.environ | envvars
            subprocess.check_call(build["build_cmd"].split(), cwd=appdir, env=env_host)
            build_out = outdir_hint
        elif docker_ok:
            click.secho("Building inside Docker …", fg="cyan")
            build_out = _docker_build()
        else:
            click.secho("Neither Node/npm nor Docker available.", fg="red"); sys.exit(1)
    except subprocess.CalledProcessError:
        if docker_ok:
            click.secho("Host build failed → retrying in Docker …", fg="yellow")
            build_out = _docker_build()
        else:
            click.secho("Build failed and Docker not available.", fg="red"); sys.exit(1)

    if not build_out.exists():
        click.secho(f"Missing output folder {build_out}", fg="red"); sys.exit(1)

    bucket = _bucket_name(proj)
    region = "ap-south-1"
    s3 = boto3.client("s3", region_name=region)

    try:
        s3.head_bucket(Bucket=bucket)
    except s3.exceptions.ClientError:
        click.echo(f"Creating bucket {bucket} …")
        s3.create_bucket(Bucket=bucket, CreateBucketConfiguration={"LocationConstraint": region})
        s3.put_public_access_block(
            Bucket=bucket,
            PublicAccessBlockConfiguration={k: False for k in (
                "BlockPublicAcls","IgnorePublicAcls","BlockPublicPolicy","RestrictPublicBuckets")}
        )
        s3.put_bucket_policy(
            Bucket=bucket,
            Policy=json.dumps({
                "Version":"2012-10-17",
                "Statement":[{"Sid":"PublicRead","Effect":"Allow","Principal":"*",
                              "Action":["s3:GetObject"],"Resource":[f"arn:aws:s3:::{bucket}/*"]}]
            }),
        )
        s3.put_bucket_website(
            Bucket=bucket,
            WebsiteConfiguration={"IndexDocument":{"Suffix":"index.html"},
                                  "ErrorDocument":{"Key":"index.html"}},
        )
        s3.put_bucket_versioning(Bucket=bucket,VersioningConfiguration={"Status":"Enabled"})

    click.secho("Uploading files …", fg="cyan")
    total = sum(1 for _ in build_out.rglob("*") if _.is_file())
    with Progress() as prog:
        task = prog.add_task("upload", total=total)
        for f in build_out.rglob("*"):
            if f.is_file():
                key = str(f.relative_to(build_out)).replace("\\", "/")
                s3.upload_file(
                    str(f), bucket, key,
                    ExtraArgs={"ContentType": mimetypes.guess_type(f.name)[0] or "binary/octet-stream"},
                )
                prog.advance(task)
    head_ver = s3.head_object(Bucket=bucket, Key="index.html")["VersionId"]
    s3.put_object(Bucket=bucket, Key="__minfy_current.txt", Body=head_ver)
    url = f"http://{bucket}.s3-website.{region}.amazonaws.com"
    click.secho(f" Deployed → {url}", fg="green")
    click.echo("Next → 'minfy status' or 'minfy rollback'.")
