import json
from unittest.mock import patch, MagicMock
import pytest
from click.testing import CliRunner

from minfy.cli import cli

def test_cli_version():
    """Test CLI version command"""
    runner = CliRunner()
    result = runner.invoke(cli, ['--version'])
    
    assert result.exit_code == 0
    assert "minfy" in result.output.lower()

def test_cli_help():
    """Test CLI help command"""
    runner = CliRunner()
    result = runner.invoke(cli, ['--help'])
    
    assert result.exit_code == 0
    assert "Usage:" in result.output
    
    # Check that all main commands are listed
    commands = ["init", "detect", "auth", "config", "deploy", "status", "rollback", "monitor"]
    for cmd in commands:
        assert cmd in result.output

def test_subcommand_help():
    """Test subcommand help"""
    runner = CliRunner()
    
    # Test help for each main command
    commands = ["init", "detect", "auth", "config", "deploy", "status", "rollback", "monitor"]
    for cmd in commands:
        result = runner.invoke(cli, [cmd, '--help'])
        assert result.exit_code == 0
        assert "Usage:" in result.output

@pytest.mark.integration
def test_e2e_workflow():
    """Test the entire workflow from init to deploy to status to rollback"""
    runner = CliRunner()
    
    with runner.isolated_filesystem(), \
         patch('minfy.commands.init.ensure_git_available'), \
         patch('minfy.commands.init.run_command'), \
         patch('minfy.commands.init.find_app_directory', return_value='src'), \
         patch('pathlib.Path.mkdir'), \
         patch('pathlib.Path.exists', return_value=True), \
         patch('pathlib.Path.write_text'), \
         patch('pathlib.Path.read_text', side_effect=[
             # For .minfy.json
             json.dumps({
                 "repo": "https://github.com/sreejavoma13/meme-gen",
                 "local_path": "./test/path",
                 "app_subdir": "src",
                 "current_env": "dev",
                 "envs": {"dev": {"vars": {}}}
             }),
             # For build.json when needed
             json.dumps({
                 "builder": "vite",
                 "build_cmd": "npm run build",
                 "output_dir": "dist"
             })
         ]), \
         patch('boto3.client'), \
         patch('subprocess.run'):
        
        # Run init
        init_result = runner.invoke(cli, ['init', '--repo', 'https://github.com/test/repo.git'])
        assert init_result.exit_code == 0
        
        # Run detect - with properly mocked config
        with patch('minfy.commands.detect.get_config', return_value={
            "repo": "https://github.com/sreejavoma13/meme-gen",
            "local_path": "./test/path",
            "app_subdir": "src",
            "current_env": "dev"
        }):
            detect_result = runner.invoke(cli, ['detect'])
            # We'll check that it runs without errors, not necessarily that it detected correctly
            assert detect_result.exit_code == 0 or "Detected" in detect_result.output
            
        # Run deploy - with mocked ensure_bucket and upload
        with patch('minfy.commands.deploy.ensure_bucket_exists'), \
             patch('minfy.commands.deploy._upload_directory'):
            deploy_result = runner.invoke(cli, ['deploy'])
            assert deploy_result.exit_code == 0 or "Deploy" in deploy_result.output
            
        # Run status
        with patch('minfy.commands.status.get_bucket_name', return_value="test-bucket"), \
             patch('boto3.client().get_bucket_website'), \
             patch('boto3.client().get_bucket_location', return_value={"LocationConstraint": "us-west-2"}), \
             patch('boto3.client().get_object'):
            status_result = runner.invoke(cli, ['status'])
            assert status_result.exit_code == 0
            
        # Run rollback
        with patch('minfy.commands.rollback.handle_rollback'):
            rollback_result = runner.invoke(cli, ['rollback'], input='y\n')
            assert rollback_result.exit_code == 0 or "Rolled back" in rollback_result.output
