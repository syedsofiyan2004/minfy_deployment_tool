import json
import os
import tempfile
from pathlib import Path
from unittest.mock import patch, MagicMock

import pytest
from click.testing import CliRunner

from minfy.commands.deploy import deploy_cmd, ensure_bucket_exists, _upload_directory

@pytest.fixture
def mock_s3(mock_boto3):
    """Fixture for S3 client"""
    return mock_boto3['s3']

@pytest.fixture
def mock_config_file():
    """Fixture to mock config file"""
    with patch('pathlib.Path.read_text') as mock_read:
        mock_read.return_value = json.dumps({
            "repo": "https://github.com/sreejavoma13/meme-gen",
            "local_path": "/test/path",
            "app_subdir": "frontend",
            "current_env": "dev",
            "envs": {
                "dev": {
                    "vars": {"API_URL": "https://dev-api.example.com"},
                    "build_cmd": "npm run build"
                },
                "prod": {
                    "vars": {"API_URL": "https://api.example.com"},
                    "build_cmd": "npm run build:prod"
                }
            }
        })
        yield mock_read

@pytest.fixture
def mock_build_json():
    """Fixture to mock build.json"""
    with patch('pathlib.Path.read_text') as mock_read:
        mock_read.return_value = json.dumps({
            "builder": "vite",
            "build_cmd": "npm run build",
            "output_dir": "dist",
            "requires_docker": False,
            "needs_env": False
        })
        yield mock_read

def test_ensure_bucket_exists_handles_existing_bucket(mock_s3):
    """Test ensure_bucket_exists with an existing bucket"""
    # Mock that the bucket exists
    ensure_bucket_exists(mock_s3, "test-bucket", "us-west-2")
    
    # Verify head_bucket was called but not create_bucket
    mock_s3.head_bucket.assert_called_once_with(Bucket="test-bucket")
    mock_s3.create_bucket.assert_not_called()

def test_ensure_bucket_exists_creates_bucket(mock_s3):
    """Test bucket creation when it doesn't exist"""
    # Mock that the bucket doesn't exist
    mock_s3.head_bucket.side_effect = mock_s3.exceptions.ClientError(
        {"Error": {"Code": "NoSuchBucket"}}, "HeadBucket"
    )
    
    ensure_bucket_exists(mock_s3, "test-bucket", "us-west-2")
    
    # Verify both methods were called
    mock_s3.head_bucket.assert_called_once_with(Bucket="test-bucket")
    mock_s3.create_bucket.assert_called_once_with(
        Bucket="test-bucket",
        CreateBucketConfiguration={"LocationConstraint": "us-west-2"}
    )
    mock_s3.put_public_access_block.assert_called_once()

@patch('subprocess.run')
@patch('tempfile.mkdtemp', return_value=os.path.join(tempfile.gettempdir(), 'test'))
def test_deploy_with_docker(mock_mkdtemp, mock_subprocess, mock_config_file, mock_build_json, mock_s3):
    """Test deployment with Docker build"""
    runner = CliRunner()
    
    with runner.isolated_filesystem(), \
         patch('pathlib.Path.exists', return_value=True), \
         patch('minfy.commands.deploy.ensure_bucket_exists') as mock_ensure_bucket, \
         patch('minfy.commands.deploy._upload_directory') as mock_upload:
        
        # Mock Docker build and cp operations
        mock_subprocess.return_value.returncode = 0
        
        # Mock the build.json to require Docker
        with patch('pathlib.Path.read_text', side_effect=[
            # For config file
            json.dumps({
                "repo": "https://github.com/sreejavoma13/meme-gen",
                "local_path": "./test/path",  # Using relative path to avoid Windows issues
                "app_subdir": "frontend",
                "current_env": "dev"
            }),
            # For build.json
            json.dumps({
                "builder": "vite",
                "build_cmd": "npm run build",
                "output_dir": "dist",
                "requires_docker": True,
                "needs_env": False
            }),
            # For Dockerfile
            "FROM node:20-alpine AS build\nWORKDIR /app"
        ]):
            
            result = runner.invoke(deploy_cmd)
            
            assert result.exit_code == 0
            mock_ensure_bucket.assert_called_once()
            mock_upload.assert_called_once()

@patch('subprocess.run')
def test_deploy_with_env_file(mock_subprocess, mock_config_file, mock_s3):
    """Test deployment with environment variables file"""
    runner = CliRunner()
    
    # Create temporary .env file
    env_content = "API_KEY=test123\nBACKEND_URL=https://api.example.com"
    env_file = os.path.join(tempfile.gettempdir(), 'test.env')
    
    with open(env_file, 'w') as f:
        f.write(env_content)
    
    try:
        with runner.isolated_filesystem(), \
             patch('pathlib.Path.exists', return_value=True), \
             patch('pathlib.Path.read_text', side_effect=[
                 # For config file
                 json.dumps({
                     "repo": "https://github.com/sreejavoma13/meme-gen",
                     "local_path": "./test/path",
                     "app_subdir": "frontend",
                     "current_env": "dev"
                 }),
                 # For build.json
                 json.dumps({
                     "builder": "vite",
                     "build_cmd": "npm run build",
                     "output_dir": "dist",
                     "requires_docker": True,
                     "needs_env": True
                 }),
                 # For Dockerfile
                 "FROM node:20-alpine AS build\nWORKDIR /app"
             ]), \
             patch('minfy.commands.deploy.ensure_bucket_exists'), \
             patch('minfy.commands.deploy._upload_directory'), \
             patch('minfy.commands.deploy._inject_env_into_dockerfile') as mock_inject, \
             patch('minfy.commands.deploy._parse_env_file', return_value={"API_KEY": "test123", "BACKEND_URL": "https://api.example.com"}):
            
            mock_subprocess.return_value.returncode = 0
            
            result = runner.invoke(deploy_cmd, ['--env-file', env_file])
            
            assert result.exit_code == 0
            mock_inject.assert_called_once()
    finally:
        if os.path.exists(env_file):
            os.remove(env_file)

def test_upload_directory(mock_s3):
    """Test the _upload_directory function"""
    with tempfile.TemporaryDirectory() as tmp_dir:
        # Create some test files
        test_file = Path(tmp_dir) / "index.html"
        test_file.write_text("<html>Test</html>")
        
        nested_dir = Path(tmp_dir) / "css"
        nested_dir.mkdir()
        css_file = nested_dir / "style.css"
        css_file.write_text("body { color: black; }")
        
        # Test upload
        _upload_directory(mock_s3, "test-bucket", tmp_dir, "dev")
        
        # Check if put_object was called for both files
        assert mock_s3.put_object.call_count >= 2
