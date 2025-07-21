import click
from .commands.init import init_cmd
from .commands.deploy import deploy_cmd
from .commands.config_cmd import config_grp
from .commands.auth import auth_cmd
from .commands.detect import detect_cmd
from .commands.status import status_cmd
from .commands.rollback import rollback_cmd
from .commands.monitor import monitor_grp

@click.group()
def cli():
    """minfy – simple deploy helper created for Minfy By Syed Sofiyan"""
    pass


cli.add_command(init_cmd, name="init")
cli.add_command(deploy_cmd, name="deploy")
cli.add_command(status_cmd, name="status")
cli.add_command(rollback_cmd, name="rollback")
cli.add_command(config_grp, name="config")
cli.add_command(auth_cmd, name="auth")
cli.add_command(detect_cmd, name="detect")
cli.add_command(monitor_grp, name="monitor")

