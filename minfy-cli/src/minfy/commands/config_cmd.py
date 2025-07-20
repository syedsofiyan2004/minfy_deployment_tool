import json
from pathlib import Path
import click

config_file = Path('.minfy.json')
DEFAULT_ENV_NAME = 'dev'
DEFAULT_ENVIRONMENTS = {
    'dev': {'vars': {}, 'build_cmd': 'npm run build'},
    'staging': {'vars': {}, 'build_cmd': 'npm run build'},
    'prod': {'vars': {}, 'build_cmd': 'npm run build'},
}
def load_config() -> dict:
    if config_file.exists():
        data = json.loads(config_file.read_text())
    else:
        data = {}
    if 'current_env' not in data:
        data['current_env'] = DEFAULT_ENV_NAME
    if 'envs' not in data:
        data['envs'] = DEFAULT_ENVIRONMENTS.copy()
    return data

def save_config(settings: dict):
    config_file.write_text(json.dumps(settings, indent=2))

@click.group('config')
def config_grp():
    pass
@config_grp.command('set')
@click.argument('pair')
def set_var(pair):
    if '=' not in pair:
        click.secho('Invalid format, use KEY=VALUE.', fg='red')
        raise click.Abort()
    k, v = pair.split('=', 1)
    settings = load_config()
    env = settings['current_env']
    settings['envs'][env]['vars'][k] = v
    save_config(settings)
    click.secho(f'{k} set in environment [{env}]', fg='green')
    click.echo('Next, run minfy deploy when ready.')

@config_grp.command('list')
def list_vars():
    settings = load_config()
    env = settings['current_env']
    data = settings['envs'][env]
    click.echo(f'Environment: {env}')
    click.echo(f"Build command: {data['build_cmd']}")
    if data['vars']:
        click.echo('Variables:')
        for k, v in data['vars'].items():
            click.echo(f'  {k} = {v}')
    else:
        click.echo('No variables set.')
    click.echo('To change environment, run: minfy config env NAME')

@config_grp.command('env')
@click.argument('name')
def switch_env(name):
    settings = load_config()
    if name not in settings['envs']:
        click.secho(f"Unknown environment: {name}", fg='red')
        click.echo(f"Available environments: {', '.join(settings['envs'].keys())}")
        raise click.Abort()
    settings['current_env'] = name
    save_config(settings)
    click.secho(f'Environment changed to {name}', fg='green')
    click.echo('Now set variables or run minfy deploy.')
