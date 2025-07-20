import os
import sys
import json
import pytest

# Register the integration mark
pytest.mark.integration = pytest.mark.integration
from unittest.mock import patch, MagicMock
from pathlib import Path

# Example repo for testing: https://github.com/sreejavoma13/meme-gen

@pytest.fixture
def mock_aws_credentials():
    """Fixture for mocking AWS credentials."""
    with patch.dict(os.environ, {
        'AWS_ACCESS_KEY_ID': 'testing',
        'AWS_SECRET_ACCESS_KEY': 'testing',
        'AWS_SECURITY_TOKEN': 'testing',
        'AWS_SESSION_TOKEN': 'testing',
        'AWS_DEFAULT_REGION': 'us-east-1'
    }):
        yield

@pytest.fixture
def mock_project_config():
    """Fixture for creating a mock project config."""
    config = {
        "repo": "https://github.com/test/repo.git",
        "local_path": str(Path(".") / ".minfy_workspace" / "repo"),
        "app_subdir": "frontend",
        "current_env": "dev",
        "envs": {
            "dev": {"vars": {"API_URL": "https://dev-api.example.com"}, "build_cmd": "npm run build"},
            "staging": {"vars": {}, "build_cmd": "npm run build"},
            "prod": {"vars": {}, "build_cmd": "npm run build-prod"}
        }
    }
    return config

@pytest.fixture
def mock_build_config():
    """Fixture for creating a mock build config."""
    config = {
        "builder": "vite",
        "build_cmd": "npm run build",
        "output_dir": "dist",
        "requires_docker": True,
        "needs_env": False
    }
    return config

@pytest.fixture
def setup_project_files(mock_project_config, mock_build_config):
    """Fixture for setting up mock project files in a temporary directory."""
    with patch('pathlib.Path.exists', return_value=True), \
         patch('pathlib.Path.read_text', side_effect=[
            json.dumps(mock_project_config),
            json.dumps(mock_build_config)
         ]), \
         patch('pathlib.Path.write_text'):
        yield

@pytest.fixture
def mock_boto3():
    """Fixture for mocking boto3 AWS SDK."""
    with patch('boto3.client') as mock_client, \
         patch('boto3.resource') as mock_resource:
        
        # Create mock S3 client
        mock_s3 = MagicMock()
        mock_s3.exceptions.NoSuchBucket = type('NoSuchBucket', (Exception,), {})
        mock_s3.exceptions.ClientError = type('ClientError', (Exception,), {})
        
        # Create mock EC2 client
        mock_ec2 = MagicMock()
        
        # Configure client factory
        mock_client.side_effect = lambda service, **kwargs: {
            's3': mock_s3,
            'ec2': mock_ec2
        }.get(service, MagicMock())
        
        yield {
            'client': mock_client,
            's3': mock_s3,
            'ec2': mock_ec2,
            'resource': mock_resource
        }
