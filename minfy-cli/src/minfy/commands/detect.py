import json
import sys
import re
from pathlib import Path
import click
from rich.table import Table
from rich import print as rprint
from ..commands.config_cmd import config_file

DOCKER_TEMPLATES = {
    "vite": """\
FROM node:20-alpine AS build
WORKDIR /app
COPY package*.json ./
RUN npm ci --legacy-peer-deps || npm install --legacy-peer-deps
COPY . .
RUN npm run build

FROM nginx:alpine
COPY --from=build /app/dist /usr/share/nginx/html
EXPOSE 80
CMD ["nginx", "-g", "daemon off;"]
""",
    "cra": """\
FROM node:20-alpine AS build
WORKDIR /app
COPY package*.json ./
RUN npm ci --legacy-peer-deps || npm install --legacy-peer-deps
COPY . .
RUN npm run build

FROM nginx:alpine
COPY --from=build /app/build /usr/share/nginx/html
EXPOSE 80
CMD ["nginx", "-g", "daemon off;"]
""",
    "angular": """\
FROM node:20-alpine AS build
ENV NODE_OPTIONS=--openssl-legacy-provider
WORKDIR /app
COPY package*.json ./
RUN npm ci --legacy-peer-deps || npm install --legacy-peer-deps
COPY . .
RUN npm run build -- --configuration production

FROM nginx:alpine
COPY --from=build /app/{output_dir} /usr/share/nginx/html
EXPOSE 80
CMD ["nginx", "-g", "daemon off;"]
""",
    "next": """\
FROM node:20-alpine AS build
WORKDIR /app
COPY package*.json ./
RUN npm ci --legacy-peer-deps || npm install --legacy-peer-deps
COPY . .
RUN {build_cmd}

FROM nginx:alpine
COPY --from=build /app/{output_dir} /usr/share/nginx/html
EXPOSE 80
CMD ["nginx", "-g", "daemon off;"]
""",
    "fallback": """\
FROM node:20-alpine AS build
WORKDIR /app
COPY package*.json ./
RUN npm ci --legacy-peer-deps || npm install --legacy-peer-deps
COPY . .
RUN {build_cmd}

FROM nginx:alpine
COPY --from=build /app/{output_dir} /usr/share/nginx/html
EXPOSE 80
CMD ["nginx", "-g", "daemon off;"]
""",
}

def _pretty(plan: dict):
    tbl = Table(title="Build Plan")
    tbl.add_column("Key", style="cyan")
    tbl.add_column("Value", style="magenta")
    for key, val in plan.items():
        tbl.add_row(key, str(val))
    click.echo(tbl)

def needs_docker(plan: dict) -> bool:
    builder_type = plan.get('builder', '')
    if builder_type in ('vite', 'cra', 'angular'):
        return True
        
    build_command = plan.get('build_cmd', '').lower()
    js_tools = ('npm', 'yarn', 'pnpm', 'ng ')
    
    for tool in js_tools:
        if tool in build_command:
            return True
    return False

def needs_env(app_dir: Path, pkg: dict | None) -> bool:
    gitignore = app_dir / '.gitignore'
    
    if (app_dir / '.env.example').exists() or (app_dir / '.env.template').exists():
        return True
        
    if gitignore.exists():
        try:
            content = gitignore.read_text(errors='ignore')
            if '.env' in content:
                return True
        except Exception:
            pass
            
    if pkg:
        all_deps = {**pkg.get('dependencies', {}), **pkg.get('devDependencies', {})}
        if 'dotenv' in all_deps:
            return True

    src_folder = app_dir / 'src'
    for js_file in src_folder.rglob('*.[jt]s*'):
        try:
            code = js_file.read_text(errors='ignore')
            if 'process.env.' in code:
                return True
        except Exception:
            pass
            
    return False

def _write_docker(app_dir: Path, plan: dict):
    if not plan["requires_docker"]:
        return
    dockerfile_path = app_dir / "Dockerfile.build"
    template = DOCKER_TEMPLATES.get(plan["builder"], DOCKER_TEMPLATES["fallback"])
    dockerfile = template.format(
        output_dir=plan["output_dir"],
        build_cmd=plan["build_cmd"]
    )
    dockerfile_path.write_text(dockerfile, encoding="utf-8")
    # Write a build.json with the static output path for nginx
    static_output_path = "/usr/share/nginx/html" if plan["requires_docker"] else plan["output_dir"]
    build_json = Path("build.json")
    plan["static_output_path"] = static_output_path
    build_json.write_text(json.dumps(plan, indent=2))
    click.secho("Dockerfile.build written", fg="green")

@click.command("detect")
def detect_cmd():
    if not config_file.exists():
        click.secho("Run 'minfy init' first.", fg="red")
        sys.exit(1)

    project_config = json.loads(config_file.read_text())
    app_dir = Path(project_config["local_path"]) / project_config["app_subdir"]

    if (app_dir / "angular.json").exists():
        config = json.loads((app_dir / "angular.json").read_text())
        project_name = config.get("defaultProject") 
        
        if not project_name:
            project_name = list(config["projects"])[0]
            
        plan = {
            "builder": "angular",
            "build_cmd": "npm run build -- --configuration production",
            "output_dir": f"dist/{project_name}"
        }
        pkg = None
    else:
        package_file = app_dir / "package.json"
        if not package_file.exists():
            click.secho(f"No package.json in {app_dir}", fg="red")
            sys.exit(1)
            
        pkg = json.loads(package_file.read_text())
        all_deps = {**pkg.get("dependencies", {}), **pkg.get("devDependencies", {})}
        build_scripts = pkg.get("scripts", {})
        
        if "react-scripts" in all_deps:
            plan = {
                "builder": "cra", 
                "build_cmd": "npm run build",
                "output_dir": "build"
            }
        elif "vite" in all_deps or re.search(r"\bvite\b", build_scripts.get("build", "")):
            plan = {
                "builder": "vite",
                "build_cmd": "npm run build",
                "output_dir": "dist" 
            }
        else:
            plan = {"builder": "custom"}
            plan["output_dir"] = click.prompt("Output directory?", default="build")
            plan["build_cmd"] = click.prompt("Build command?", default="npm run build")
    plan['requires_docker'] = needs_docker(plan)
    plan['needs_env'] = needs_env(app_dir, pkg)

    build_file = Path("build.json")
    build_file.write_text(json.dumps(plan, indent=2))
    _write_docker(app_dir, plan)
    click.secho("build.json created", fg="green")
    if plan['needs_env']:
        click.secho('You might need an .env file. Deploy with: minfy deploy --env-file path/to/.env', fg='yellow')
    rprint('[bold]Next[/bold] configure variables with [cyan]minfy config[/cyan] '
           'and then run [cyan]minfy deploy[/cyan].')

