#!/usr/bin/env python3
from pathlib import Path
import json
import shutil
import subprocess
import sys
import click
import click

MINFY_WORKSPACE_PATH = Path('.') / '.minfy_workspace'
CONFIG_PATH = Path('.minfy.json')
DEFAULT_ENVIRONMENTS = {
    'dev': {'vars': {}, 'build_cmd': 'npm run build'},
    'staging': {'vars': {}, 'build_cmd': 'npm run build'},
    'prod': {'vars': {}, 'build_cmd': 'npm run build'},
}

def ensure_git_available():
    if shutil.which('git') is None:
        click.secho('ERROR: Git is required but not found.', fg='red')
        sys.exit(1)

def run_command(command, cwd=None):
    """Run a command and return the CompletedProcess instance"""
    import subprocess
    return subprocess.run(command, capture_output=True, text=True, cwd=cwd)
def get_repo_folder_name(repo_url: str) -> str:
    """Extract the folder name from a Git repository URL."""
    repo_name = repo_url.rstrip('/').split('/')[-1]
    return repo_name[:-4] if repo_name.endswith('.git') else repo_name

def find_app_directory(base_path: Path) -> str:
    manifest_files = ('package.json', 'angular.json')
    base = Path(base_path)

    for mf in manifest_files:
        if (base / mf).exists():
            click.secho('Found manifest in repo root.', fg='cyan')
            return '.'

    candidates = [d.name for d in base.iterdir()
                  if d.is_dir() and any((d / mf).exists() for mf in manifest_files)]
    if not candidates:
        click.secho('No manifest found; defaulting to root.', fg='yellow')
        return '.'
    if len(candidates) == 1:
        click.secho(f"Detected single app folder '{candidates[0]}'.", fg='cyan')
        return candidates[0]
    click.echo('Multiple app folders found:')
    for idx, name in enumerate(candidates, start=1):
        click.echo(f'  {idx}. {name}')
    choice = click.prompt('Select folder', type=click.IntRange(1, len(candidates)))
    return candidates[choice - 1]

@click.command('init')
@click.option(
    '--repo', '-r', 'repository_url', prompt='Git repository URL',
    help='URL of the Git repo to deploy (must end in .git)'
)
def init_cmd(repository_url: str):
    """Clone the repository and save initial project configuration."""
    ensure_git_available()
    MINFY_WORKSPACE_PATH.mkdir(exist_ok=True)
    repo_folder = get_repo_folder_name(repository_url)
    destination_path = MINFY_WORKSPACE_PATH / repo_folder

    if destination_path.exists():
        click.secho(f'Repository already exists at {destination_path}', fg='yellow')
    else:
        click.secho(f'Cloning into {destination_path}...', fg='cyan')
        result = run_command(['git', 'clone', '--depth', '1', repository_url, str(destination_path)])
        if result.returncode != 0 or not destination_path.exists():
            click.secho('ERROR: Invalid Git URL' \
            'Please Enter a valid Git repository URL', fg='red')
            sys.exit(1)

    app_folder = find_app_directory(destination_path)
    project_config = {
        'repo': repository_url,
        'local_path': str(destination_path),
        'app_subdir': app_folder,
        'current_env': 'dev',
        'envs': DEFAULT_ENVIRONMENTS,
    }
    CONFIG_PATH.write_text(json.dumps(project_config, indent=2), encoding='utf-8')
    click.secho(f'Configuration saved to {CONFIG_PATH}', fg='green')

    click.echo('Next: Run minfy detect to analyze and build.')
