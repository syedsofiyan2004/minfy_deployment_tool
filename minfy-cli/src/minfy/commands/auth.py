import getpass, sys
import click, boto3
from ..config import AWSAuth, save_global


@click.command("auth")
def auth_cmd():
    """
    Store or update AWS credentials used by all 'minfy' commands.
    We quickly validate by listing S3 buckets.
    """
    click.echo("Enter an IAM user Access Key with S3 permissions.")
    access = click.prompt("AWS Access Key ID")
    secret = getpass.getpass("AWS Secret Access Key: ")
    region = click.prompt("Default AWS region", default="ap-south-1")
    profile = (
        click.prompt("Profile name (optional)", default="", show_default=False) or None
    )
    try:
        boto3.client(
            "s3",
            aws_access_key_id=access,
            aws_secret_access_key=secret,
            region_name=region,
        ).list_buckets()
    except Exception as e:
        click.secho(f" Credentials test failed: {e}", fg="red")
        sys.exit(1)

    save_global(
        AWSAuth(
            aws_access_key_id=access,
            aws_secret_access_key=secret,
            region=region,
            profile=profile,
        )
    )
    click.secho("Credentials saved to ~/.minfy/config.yaml", fg="green")
