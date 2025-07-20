import getpass
import sys
import click
import boto3
from ..config import AWSAuth, save_global

@click.command("auth")
def auth_cmd():
    click.echo("Enter IAM user credentials with S3 and EC2 permissions.")
    key_id = click.prompt("AWS Access Key ID")
    secret_key = getpass.getpass("AWS Secret Access Key: ")
    session_token = click.prompt("AWS Session Token (optional)", default="", show_default=False) or None
    region = click.prompt("Default AWS region", default="ap-south-1")
    profile = click.prompt("AWS Profile name (optional)", default="", show_default=False) or None
    try:
        test_creds = {
            "aws_access_key_id": key_id,
            "aws_secret_access_key": secret_key,
            "region_name": region,
        }
        if session_token:
            test_creds["aws_session_token"] = session_token
        boto3.client("s3", **test_creds).list_buckets()
    except Exception as err:
        click.secho(f"Credentials test failed: {err}", fg="red")
        sys.exit(1)
    save_global(
        AWSAuth(
            aws_access_key_id=key_id,
            aws_secret_access_key=secret_key,
            aws_session_token=session_token,
            region=region,
            profile=profile,
        )
    )
    click.secho("Credentials saved to .minfy/config.yaml", fg="green")
    click.echo('Next: Run minfy init to set up your project.')
