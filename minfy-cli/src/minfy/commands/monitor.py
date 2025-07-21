from __future__ import annotations
import json, os, shutil, socket, subprocess, sys, textwrap, time, webbrowser
import base64
import urllib.request
from pathlib import Path
import boto3
import click
from ..commands.config_cmd import config_file  
from ..commands.deploy import _bucket_name
import datetime
from rich import print as rprint
from ..config import load_global

"""
Monitoring commands: provision, status, dashboard, and teardown for Prometheus/Grafana stack.
All metrics shown in Grafana are real—Prometheus scrapes the blackbox-exporter
to probe your site every 15 seconds (see static_configs in prometheus.yml).
"""

MON_DIR        = Path(".") / ".minfy_monitor"
TF_DIR         = MON_DIR / "terraform"
MON_KEY        = MON_DIR / "minfy_monitor.pem"
TFVARS_JSON    = TF_DIR / "terraform.tfvars.json"

MON_SG_NAME    = "minfy-monitor-sg"
MON_KP_NAME    = "minfy-monitor-key"
DEFAULT_REGION = "ap-south-1"
DEFAULT_AMI_ID = "ami-0a1235697f4afa8a4"
_COMPOSE_TPL = """\
version: "3.8"
services:
  blackbox:
    image: prom/blackbox-exporter:latest
    restart: unless-stopped
    ports: [ "9115:9115" ]

  node-exporter:
    image: prom/node-exporter:latest
    restart: unless-stopped
    ports: [ "9100:9100" ]

  prometheus:
    image: prom/prometheus:latest
    restart: unless-stopped
    command: ["--config.file=/etc/prometheus/prometheus.yml", "--storage.tsdb.retention.time=1h", "--storage.tsdb.path=/prometheus"]
    volumes:
      - "./prometheus.yml:/etc/prometheus/prometheus.yml"
      - "./prometheus_data:/prometheus"
    ports: [ "9090:9090" ]
    depends_on: [ blackbox, node-exporter ]

  grafana:
    image: grafana/grafana:latest
    restart: unless-stopped
    environment: [ GF_SECURITY_ADMIN_PASSWORD=admin ]
    ports: [ "3000:3000" ]
    depends_on: [ prometheus ]
"""
_PROM_TPL = """\
global:
  scrape_interval: 15s

scrape_configs:
  - job_name: uptime
    metrics_path: /probe
    params:
      module: [http_2xx]
    static_configs:
      - targets: [{url!r}]
    relabel_configs:
      - source_labels: [__address__]
        target_label: __param_target
      - source_labels: [__param_target]
        target_label: instance
      - target_label: __address__
        replacement: blackbox:9115

  - job_name: 'node'
    static_configs:
      - targets: ['node-exporter:9100']
"""

_USER_DATA_SH = """#!/bin/bash -xe
exec > /var/log/minfy-monitor-user-data.log 2>&1
if command -v apt-get >/dev/null 2>&1; then
  apt-get update -y && apt-get install -y docker.io
  USERNAME=ubuntu
else
  yum -y update || true && yum -y install docker
  USERNAME=ec2-user
fi
systemctl enable --now docker
usermod -aG docker $USERNAME || true
if command -v apt-get >/dev/null 2>&1; then
  # Install classic docker-compose binary
  apt-get install -y docker-compose
elif command -v yum >/dev/null 2>&1; then
  ARCH=$(uname -m)
  mkdir -p /usr/local/lib/docker/cli-plugins
  curl -fsSL https://github.com/docker/compose/releases/download/v2.27.0/docker-compose-linux-${ARCH} \
    -o /usr/local/lib/docker/cli-plugins/docker-compose
  chmod +x /usr/local/lib/docker/cli-plugins/docker-compose
  ln -s /usr/local/lib/docker/cli-plugins/docker-compose /usr/local/bin/docker-compose
fi

mkdir -p /opt/monitor/prometheus_data
sudo chown -R 65534:65534 /opt/monitor/prometheus_data

for i in $(seq 1 30); do docker info >/dev/null 2>&1 && break; sleep 2; done
# ECR login using instance role
mkdir -p /opt/monitor
cat >/opt/monitor/docker-compose.yml <<'EOF_CMP'
{compose}
EOF_CMP
cat >/opt/monitor/prometheus.yml <<'EOF_PRM'
{prom}
EOF_PRM
mkdir -p /opt/monitor/provisioning/datasources
mkdir -p /opt/monitor/provisioning/dashboards
cat >/opt/monitor/provisioning/datasources/all.yml <<'EOF_DS'
apiVersion: 1
datasources:
  - name: Prometheus
    type: prometheus
    access: proxy
    url: http://prometheus:9090
    isDefault: true
EOF_DS
cat >/opt/monitor/provisioning/dashboards/all.yml <<'EOF_DB'
apiVersion: 1
providers:
  - name: default
    folder: Minfy
    options:
      path: /etc/grafana/provisioning/dashboards
EOF_DB
cat >/opt/monitor/provisioning/dashboards/uptime.json <<'EOF_JSON'
{
  "id": null,
  "uid": "minfy-uptime",
  "title": "Website uptime / latency",
  "tags": ["minfy"],
  "timezone": "browser",
  "panels": [/* define panels... */]
}
EOF_JSON

cd /opt/monitor
# Use docker-compose if available, else docker compose
if command -v docker-compose >/dev/null 2>&1; then
  docker-compose pull && docker-compose up -d
else
  docker compose pull && docker compose up -d
fi
"""

_MAIN_TF = """\
terraform {
  required_version = ">= 1.4.0"
  required_providers {
    aws = { source = "hashicorp/aws", version = "~> 6.3.0" }
    tls = { source = "hashicorp/tls", version = "~> 4.1.0" }
  }
}

provider "aws" { region = var.region }

resource "tls_private_key" "this" {
  algorithm = "RSA"
  rsa_bits  = 4096
}

resource "aws_key_pair" "this" {
  key_name   = var.key_name
  public_key = tls_private_key.this.public_key_openssh
}

data "aws_vpc" "default"        { default = true }
data "aws_subnets" "default" {
  filter {
    name   = "vpc-id"
    values = [data.aws_vpc.default.id]
  }
}

resource "aws_security_group" "this" {
  name        = var.sg_name
  description = "minfy-monitor ports 22/9090/3000"
  vpc_id      = data.aws_vpc.default.id

  ingress {
    from_port   = 22
    to_port     = 22
    protocol    = "tcp"
    cidr_blocks = ["0.0.0.0/0"]
  }
  ingress {
    from_port   = 9090
    to_port     = 9090
    protocol    = "tcp"
    cidr_blocks = ["0.0.0.0/0"]
  }
  ingress {
    from_port   = 3000
    to_port     = 3000
    protocol    = "tcp"
    cidr_blocks = ["0.0.0.0/0"]
  }
  ingress {
    from_port   = 9115
    to_port     = 9115
    protocol    = "tcp"
    cidr_blocks = ["0.0.0.0/0"]
  }
  ingress {
    from_port   = 9100
    to_port     = 9100
    protocol    = "tcp"
    cidr_blocks = ["0.0.0.0/0"]
  }
  egress {
    from_port   = 0
    to_port     = 0
    protocol    = "-1"
    cidr_blocks = ["0.0.0.0/0"]
  }
}
data "local_file" "user_data" { filename = "${path.module}/user_data_rendered.sh" }
resource "aws_instance" "this" {
  ami                    = var.ami_id
  instance_type          = var.instance_type
  key_name               = aws_key_pair.this.key_name
  subnet_id              = element(data.aws_subnets.default.ids, 0)
  vpc_security_group_ids = [aws_security_group.this.id]
  user_data              = data.local_file.user_data.content
  iam_instance_profile   = "ECRDeployRoleInstanceProfile"

  tags = { Name = "minfy-monitor", MinfyMonitor = "yes" }
}

output "public_ip"      { value = aws_instance.this.public_ip }
output "grafana_url"    { value = "http://${aws_instance.this.public_ip}:3000" }
output "prometheus_url" { value = "http://${aws_instance.this.public_ip}:9090" }
  output "private_key_pem" {
    value     = tls_private_key.this.private_key_pem
    sensitive = true
  }
"""

_VARIABLES_TF = """\
variable "region"         { type = string }
variable "ami_id"         { type = string }
variable "instance_type" {
  type    = string
  default = "t3.micro"
}
variable "key_name"       { type = string }
variable "sg_name"        { type = string }
"""

def _region() -> str:
    cfg = load_global()
    return getattr(cfg, "region", None) or DEFAULT_REGION

def _site_url() -> str:
    if not config_file.exists():
        click.secho("Run ‘minfy deploy’ first.", fg="red"); sys.exit(1)
    proj = json.loads(config_file.read_text())
    bucket = _bucket_name(proj)
    return f"http://{bucket}.s3-website.{_region()}.amazonaws.com"

def _ensure_terraform():
    if not shutil.which("terraform"):
        click.secho("Terraform CLI not found in PATH.", fg="red"); sys.exit(1)

def _run_tf(args: list[str]):
    full = ["terraform", f"-chdir={TF_DIR}"] + args
    proc = subprocess.Popen(full, stdout=subprocess.PIPE,
                            stderr=subprocess.STDOUT, text=True)
    error_detected = False
    for line in proc.stdout:
        print(line, end="")
        if "InvalidGroup.Duplicate" in line or "already exists" in line:
            error_detected = True
    proc.wait()
    if proc.returncode:
        if error_detected:
            rprint("[bold red]A named resource already exists in your AWS Console. Please delete it to move further.[/]")
            sys.exit(1)
        raise subprocess.CalledProcessError(proc.returncode, full)

def _tf_output() -> dict:
    out = subprocess.check_output(
        ["terraform", f"-chdir={TF_DIR}", "output", "-json"], stderr=subprocess.STDOUT, text=True
    )
    return json.loads(out)

def _wait(ip:str, port:int, sec:int=300)->bool:
    t0=time.time()
    while time.time()-t0<sec:
        try: socket.create_connection((ip,port),3).close(); return True
        except OSError: time.sleep(4)
    return False

def _write_files(site:str):
    MON_DIR.mkdir(exist_ok=True)
    (MON_DIR / "prometheus_data").mkdir(exist_ok=True)
    compose = _COMPOSE_TPL
    prom    = _PROM_TPL.format(url=site)
    (MON_DIR / "docker-compose.yml").write_text(compose)
    (MON_DIR / "prometheus.yml").write_text(prom)

    TF_DIR.mkdir(parents=True, exist_ok=True)
    (TF_DIR / "main.tf").write_text(_MAIN_TF)
    (TF_DIR / "variables.tf").write_text(_VARIABLES_TF)
    user_data = _USER_DATA_SH.replace('{compose}', compose).replace('{prom}', prom)
    (TF_DIR / "user_data_rendered.sh").write_text(user_data, encoding="utf-8")
    TFVARS_JSON.write_text(json.dumps({
        "region": _region(),
        "ami_id": DEFAULT_AMI_ID,
        "key_name": MON_KP_NAME,
        "sg_name": MON_SG_NAME,
    }, indent=2))

@click.group("monitor")
def monitor_grp():
    """Group for all monitoring subcommands."""
    pass

@monitor_grp.command("enable")
def enable():
    """Enable monitoring stack on AWS via Terraform."""
    _ensure_terraform()
    site = _site_url()
    prom_data_dir = MON_DIR / "prometheus_data"
    if prom_data_dir.exists():
        for item in prom_data_dir.iterdir():
            if item.is_file() or item.is_symlink():
                item.unlink()
            elif item.is_dir():
                shutil.rmtree(item)
    _write_files(site)
    rprint(f"Probing {site} every 15 seconds via blackbox-exporter")

    rprint("Running terraform init…")
    try:
        _run_tf(["init","-upgrade"])
    except subprocess.CalledProcessError:
        click.secho("Error initializing Terraform – please check your Terraform configuration.", fg="red")
        sys.exit(1)
    rprint("Running terraform apply…")
    try:
        _run_tf(["apply","-auto-approve"])
    except subprocess.CalledProcessError:
        click.secho("Error applying Terraform – please check your AWS configuration and permissions.", fg="red")
        sys.exit(1)

    out = _tf_output()
    (MON_DIR / "id_rsa").write_text(out["private_key_pem"]["value"])
    try: (MON_DIR / "id_rsa").chmod(0o600)
    except: pass

    ip = out["public_ip"]["value"]
    rprint("Waiting for Grafana on port 3000…")
    if _wait(ip,3000):
        rprint("[bold green]Monitoring ready![/]")
    else:
        click.secho("Grafana not reachable in time.", fg="red")

    rprint(f"Prometheus URL: {out['prometheus_url']['value']}")
    rprint(f"Grafana URL: {out['grafana_url']['value']} (admin/admin)")
    rprint("Next → Run [cyan]minfy monitor status[/cyan] to view your stack or [cyan]minfy monitor dashboard[/cyan] to view your dashboards.")

@monitor_grp.command("status")
def status():
    """Show monitoring stack endpoints and prompt for next actions."""
    try:
        out = _tf_output()
    except Exception:
        click.secho("No monitoring stack – run ‘minfy monitor enable’.", fg="yellow")
        return
    rprint(f"Prometheus URL: {out['prometheus_url']['value']}")
    rprint(f"Grafana URL: {out['grafana_url']['value']}")
    try:
        proj_cfg = json.loads(config_file.read_text())
        bucket = _bucket_name(proj_cfg)
        region = _region()
        s3 = boto3.client('s3', region_name=region)
        cur_vid = s3.get_object(Bucket=bucket, Key='__minfy_current.txt')['Body'].read().decode()
        vers = s3.list_object_versions(Bucket=bucket, Prefix='index.html')['Versions']
        deploy = next((v for v in vers if v['VersionId'] == cur_vid), None)
        if deploy:
            iso = deploy['LastModified'].astimezone(datetime.timezone.utc)
            start = iso.strftime('%Y-%m-%d %H:%M:%SZ')
            rprint(f"Site deployed at: {start} UTC")
    except Exception:
        pass
    rprint("Next → Run [cyan]minfy monitor dashboard[/cyan] to view your dashboards.")
  
@monitor_grp.command("init")
def init():
    """Create local docker-compose and Prometheus config files."""
    try:
        site = _site_url()
    except Exception:
        click.secho("Run ‘minfy deploy’ first.", fg="red")
        sys.exit(1)
    MON_DIR.mkdir(exist_ok=True)
    prom_data_dir = MON_DIR / "prometheus_data"
    if prom_data_dir.exists():
        import shutil
        shutil.rmtree(prom_data_dir)
    prom_data_dir.mkdir(exist_ok=True)
    (MON_DIR / "docker-compose.yml").write_text(_COMPOSE_TPL)
    (MON_DIR / "prometheus.yml").write_text(_PROM_TPL.format(url=site))
    rprint("Local monitoring files created in .minfy_monitor")
    rprint("Next → [cyan]minfy monitor enable[/cyan] to provision on AWS .")

@monitor_grp.command("dashboard")
def dashboard():
    """Import and open Grafana dashboards in default browser."""
    if not TF_DIR.exists():
        click.secho("No monitoring stack – run ‘minfy monitor enable’ first.", fg="yellow")
        return
    try:
        outputs = _tf_output()
        url = outputs['grafana_url']['value']
        prom_url = outputs['prometheus_url']['value']
        auth = base64.b64encode(b"admin:admin").decode()
        ds_payload = {
            "name": "Prometheus",
            "type": "prometheus",
            "access": "proxy",
            "url": prom_url,
            "isDefault": True
        }
        ds_req = urllib.request.Request(
            f"{url}/api/datasources",
            data=json.dumps(ds_payload).encode('utf-8'),
            headers={
                'Content-Type': 'application/json',
                'Authorization': f"Basic {auth}"
            }
        )
        try:
            urllib.request.urlopen(ds_req)
            rprint("Configured Prometheus datasource in Grafana")
        except Exception as e:
            if not (hasattr(e, 'code') and getattr(e, 'code', None) == 409):
                click.secho(f"Warning: failed to configure datasource: {e}", fg="yellow")
        try:
            info_req = urllib.request.Request(
                f"{url}/api/datasources/name/Prometheus",
                headers={'Authorization': f"Basic {auth}"}
            )
            with urllib.request.urlopen(info_req) as resp:
                ds_info = json.loads(resp.read().decode())
                ds_uid = ds_info.get('uid')
        except Exception:
            ds_uid = None
    except Exception:
        click.secho("No monitoring stack – run ‘enable’ first.", fg="yellow"); return
    proj_cfg = json.loads(config_file.read_text())
    repo_url = proj_cfg.get('repo', '')
    repo_name = repo_url.rstrip('/').split('/')[-1]
    repo_name = repo_name[:-4] if repo_name.endswith('.git') else repo_name
    site = _site_url()
    db_dir = MON_DIR / "provisioning" / "dashboards"
    db_dir.mkdir(parents=True, exist_ok=True)
    for old in db_dir.glob('*.json'):
        old.unlink()
    bucket = _bucket_name(proj_cfg)
    region = _region()
    s3 = boto3.client('s3', region_name=region)
    try:
        cur_vid = s3.get_object(Bucket=bucket, Key='__minfy_current.txt')['Body'].read().decode()
        vers = s3.list_object_versions(Bucket=bucket, Prefix='index.html')['Versions']
        deploy = next((v for v in vers if v['VersionId'] == cur_vid), None)
        if deploy:
            iso = deploy['LastModified'].astimezone(datetime.timezone.utc)
            start = iso.strftime('%Y-%m-%dT%H:%M:%SZ')
        else:
            now_utc = datetime.datetime.now(datetime.timezone.utc)
            start = (now_utc - datetime.timedelta(hours=1)).strftime('%Y-%m-%dT%H:%M:%SZ')
    except Exception:
        now_utc = datetime.datetime.now(datetime.timezone.utc)
        start = (now_utc - datetime.timedelta(hours=1)).strftime('%Y-%m-%dT%H:%M:%SZ')
    uid = f"{repo_name}-monitoring"
    title = f"{repo_name} Monitoring"
    default_dash = {
        "id": None,
        "uid": uid,
        "title": title,
        "timezone": "browser",
        "timepicker": {
            "refresh_intervals": ["5s","10s","30s","1m","5m"],
            "time_options": ["5m","15m","1h","6h","12h","24h"]
        },
        "time": {"from": start, "to": "now"},
        "panels": []
    }
    panel_defs = [
        {"type": "timeseries", "title": "Uptime (%)", "gridPos": {"h":8,"w":12,"x":0,"y":0},
         "expr": f"avg_over_time(probe_success{{instance='{site}'}}[5m]) * 100", "field_defaults": {"nullValueMode": "null"}},
        {"type": "timeseries", "title": "Latency (avg 5m) (s)", "gridPos": {"h":8,"w":12,"x":12,"y":0},
         "expr": f"avg_over_time(probe_duration_seconds{{instance='{site}'}}[5m])", "field_defaults": {"nullValueMode": "null"}},
        {"type": "timeseries", "title": "Redirects/sec", "gridPos": {"h":8,"w":12,"x":0,"y":8},
         "expr": f"rate(probe_http_redirects{{instance='{site}'}}[5m])", "field_defaults": {"nullValueMode": "null"}},
        {"type": "timeseries", "title": "Avg Content Size (bytes)", "gridPos": {"h":8,"w":12,"x":12,"y":8},
         "expr": f"avg_over_time(probe_http_content_length{{instance='{site}'}}[5m])", "field_defaults": {"nullValueMode": "null"}},
        {"type": "gauge", "title": "Node CPU Usage (%)", "gridPos": {"h":8,"w":12,"x":0,"y":16},
         "expr": "100 - avg(irate(node_cpu_seconds_total{mode='idle'}[5m])) * 100", "field_defaults": {"unit": "percent"}},
        {"type": "gauge", "title": "Node Memory Usage (MB)", "gridPos": {"h":8,"w":12,"x":12,"y":16},
         "expr": "(node_memory_MemTotal_bytes - node_memory_MemAvailable_bytes) / (1024*1024)", "field_defaults": {"unit": "decbytes"}},
        {"type": "gauge", "title": "Node Disk Usage (%)", "gridPos": {"h":8,"w":12,"x":0,"y":24},
         "expr": "max by(instance) (100 * (node_filesystem_size_bytes - node_filesystem_free_bytes) / node_filesystem_size_bytes)", "field_defaults": {"unit": "percent"}},
    ]
    panels = []
    for pd in panel_defs:
        panels.append({
            "type": pd["type"],
            "title": pd["title"],
            "datasource": {"type": "prometheus", "uid": ds_uid},
            "gridPos": pd["gridPos"],
            "targets": [{"expr": pd["expr"]}],
            "fieldConfig": {"defaults": pd["field_defaults"]}
        })
    default_dash["panels"] = panels
    file = db_dir / f"{uid}.json"
    file.write_text(json.dumps(default_dash, indent=2))
    prov = MON_DIR / "provisioning" / "dashboards"
    if prov.exists():
        for json_file in prov.glob('*.json'):
            with open(json_file, encoding='utf-8') as f:
                dash = json.load(f)
            payload = {"dashboard": dash, "overwrite": True}
            auth = base64.b64encode(b"admin:admin").decode()
            req = urllib.request.Request(
                f"{url}/api/dashboards/db",
                data=json.dumps(payload).encode('utf-8'),
                headers={
                    'Content-Type': 'application/json',
                    'Authorization': f"Basic {auth}"
                }
            )
            try:
                urllib.request.urlopen(req)
                rprint(f"Imported dashboard {json_file.name}")
            except Exception as e:
                click.secho(f"Failed to import {json_file.name}: {e}", fg="red")

    dash_uids = []
    prov = MON_DIR / "provisioning" / "dashboards"
    for json_file in prov.glob('*.json'):
        try:
            dash = json.loads(json_file.read_text())
            dash_uids.append(dash.get('uid'))
        except: pass
    if dash_uids:
        dash_url = f"{url}/d/{dash_uids[0]}?from={start}&to=now"
    else:
        dash_url = url
    webbrowser.open(dash_url)
    rprint(f"Opening dashboard at {dash_url}")
    rprint("Next → Run [cyan]minfy monitor disable[/cyan] to remove monitoring stack.")

@monitor_grp.command("disable")
def disable():
    """Destroy monitoring stack and clean up local files."""
    _ensure_terraform()
    if TF_DIR.exists():
        rprint("Running terraform destroy…")
        try:
            _run_tf(["destroy","-auto-approve"])
        except subprocess.CalledProcessError:
            click.secho("Destroy errored – check AWS console.", fg="red")
        shutil.rmtree(MON_DIR, ignore_errors=True)
        rprint("[bold green]Monitoring stack removed.[/]")
    else:
        rprint("[yellow]No monitoring stack found to remove.[/]")

def generate_terraform_files(app_name, region):
    """Generate Terraform files for monitoring setup"""
    print(f"Generating Terraform files for {app_name} in {region}")
    return True

def run_terraform_command(command, cwd=None):
    """Run a Terraform command"""
    import subprocess
    print(f"Running Terraform command: {command}")
    return subprocess.run(command, shell=True, cwd=cwd)

def open_dashboard(region):
    """Open the CloudWatch dashboard in a browser"""
    import webbrowser
    dashboard_url = f"https://{region}.console.aws.amazon.com/cloudwatch/home?region={region}#dashboards:"
    print(f"Opening dashboard: {dashboard_url}")
    webbrowser.open(dashboard_url)
    return True
