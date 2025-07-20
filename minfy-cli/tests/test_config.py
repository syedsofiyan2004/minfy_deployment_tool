import json
import pytest
from unittest.mock import patch, MagicMock
from click.testing import CliRunner

from minfy.commands.config_cmd import config_cmd

@pytest.fixture
def mock_config():
    """Fixture to mock config file operations"""
    with patch('pathlib.Path.write_text') as mock_write:
        yield mock_write

def test_config_list(mock_config):
    """Test listing config values"""
    runner = CliRunner()
    
    with runner.isolated_filesystem(), \
         patch('pathlib.Path.exists', return_value=True), \
         patch('pathlib.Path.read_text', return_value=json.dumps({
            "repo": "https://github.com/sreejavoma13/meme-gen",
            "local_path": "./test/path",
            "app_subdir": "frontend",
            "current_env": "dev",
            "envs": {
                "dev": {
                    "vars": {
                        "API_URL": "https://dev-api.example.com"
                    }
                },
                "prod": {
                    "vars": {}
                }
            }
        })):
        
        result = runner.invoke(config_cmd, ['list'])
        
        assert result.exit_code == 0
        assert "dev" in result.output
        assert "API_URL" in result.output

def test_config_get_var(mock_config):
    """Test getting a config variable"""
    runner = CliRunner()
    
    with runner.isolated_filesystem(), \
         patch('pathlib.Path.exists', return_value=True), \
         patch('pathlib.Path.read_text', return_value=json.dumps({
            "repo": "https://github.com/sreejavoma13/meme-gen",
            "local_path": "./test/path",
            "current_env": "dev",
            "envs": {
                "dev": {
                    "vars": {
                        "API_URL": "https://dev-api.example.com"
                    }
                }
            }
        })):
        
        result = runner.invoke(config_cmd, ['get', 'API_URL'])
        
        assert result.exit_code == 0
        assert "https://dev-api.example.com" in result.output

def test_config_set_var_invalid_format(mock_config):
    """Test setting a config variable with invalid format"""
    runner = CliRunner()
    
    with runner.isolated_filesystem(), \
         patch('pathlib.Path.exists', return_value=True), \
         patch('pathlib.Path.read_text', return_value=json.dumps({
            "repo": "https://github.com/sreejavoma13/meme-gen",
            "local_path": "./test/path",
            "current_env": "dev",
            "envs": {
                "dev": {
                    "vars": {}
                }
            }
        })), \
         patch('sys.exit') as mock_exit:
        
        # Instead of raising SystemExit directly, we'll patch sys.exit
        mock_exit.side_effect = Exception("Exited")
        
        try:
            # This should call sys.exit due to invalid format
            result = runner.invoke(config_cmd, ['set', 'INVALID_FORMAT'])
            assert "Error" in result.output or "Invalid" in result.output
        except Exception:
            # This is expected since we're patching sys.exit
            pass
        
        assert mock_exit.called

def test_config_set_var(mock_config):
    """Test setting a config variable"""
    runner = CliRunner()
    
    with runner.isolated_filesystem(), \
         patch('pathlib.Path.exists', return_value=True), \
         patch('pathlib.Path.read_text', return_value=json.dumps({
            "repo": "https://github.com/sreejavoma13/meme-gen",
            "local_path": "./test/path",
            "current_env": "dev",
            "envs": {
                "dev": {
                    "vars": {}
                }
            }
        })):
        
        result = runner.invoke(config_cmd, ['set', 'API_URL=https://new-api.example.com'])
        
        assert result.exit_code == 0
        assert mock_config.called
        
        # Check that the config was saved with new value
        config_json = json.loads(mock_config.call_args[0][0])
        assert config_json['envs']['dev']['vars']['API_URL'] == 'https://new-api.example.com'

def test_config_unset_var(mock_config):
    """Test unsetting a config variable"""
    runner = CliRunner()
    
    with runner.isolated_filesystem(), \
         patch('pathlib.Path.exists', return_value=True), \
         patch('pathlib.Path.read_text', return_value=json.dumps({
            "repo": "https://github.com/sreejavoma13/meme-gen",
            "local_path": "./test/path",
            "current_env": "dev",
            "envs": {
                "dev": {
                    "vars": {
                        "API_URL": "https://dev-api.example.com"
                    }
                }
            }
        })):
        
        result = runner.invoke(config_cmd, ['unset', 'API_URL'])
        
        assert result.exit_code == 0
        assert mock_config.called
        
        # Check that the config was saved without the variable
        config_json = json.loads(mock_config.call_args[0][0])
        assert 'API_URL' not in config_json['envs']['dev']['vars']

def test_config_add_env(mock_config):
    """Test adding a new environment"""
    runner = CliRunner()
    
    with runner.isolated_filesystem(), \
         patch('pathlib.Path.exists', return_value=True), \
         patch('pathlib.Path.read_text', return_value=json.dumps({
            "repo": "https://github.com/sreejavoma13/meme-gen",
            "local_path": "./test/path",
            "current_env": "dev",
            "envs": {
                "dev": {
                    "vars": {}
                }
            }
        })):
        
        result = runner.invoke(config_cmd, ['env', 'add', 'staging'])
        
        assert result.exit_code == 0
        assert mock_config.called
        
        # Check that the config was saved with new environment
        config_json = json.loads(mock_config.call_args[0][0])
        assert 'staging' in config_json['envs']

def test_config_switch_env(mock_config):
    """Test switching environment"""
    runner = CliRunner()
    
    with runner.isolated_filesystem(), \
         patch('pathlib.Path.exists', return_value=True), \
         patch('pathlib.Path.read_text', return_value=json.dumps({
            "repo": "https://github.com/sreejavoma13/meme-gen",
            "local_path": "./test/path",
            "current_env": "dev",
            "envs": {
                "dev": {
                    "vars": {}
                },
                "prod": {
                    "vars": {}
                }
            }
        })):
        
        result = runner.invoke(config_cmd, ['env', 'use', 'prod'])
        
        assert result.exit_code == 0
        assert mock_config.called
        
        # Check that the config was saved with new current environment
        config_json = json.loads(mock_config.call_args[0][0])
        assert config_json['current_env'] == 'prod'

def test_config_switch_env_invalid(mock_config):
    """Test switching to an invalid environment"""
    runner = CliRunner()
    
    with runner.isolated_filesystem(), \
         patch('pathlib.Path.exists', return_value=True), \
         patch('pathlib.Path.read_text', return_value=json.dumps({
            "repo": "https://github.com/sreejavoma13/meme-gen",
            "local_path": "./test/path",
            "current_env": "dev",
            "envs": {
                "dev": {
                    "vars": {}
                }
            }
        })), \
         patch('sys.exit') as mock_exit:
        
        # Instead of raising SystemExit directly, we'll patch sys.exit
        mock_exit.side_effect = Exception("Exited")
        
        try:
            # This should call sys.exit due to invalid environment
            result = runner.invoke(config_cmd, ['env', 'use', 'invalid'])
            assert "does not exist" in result.output or "Invalid" in result.output
        except Exception:
            # This is expected since we're patching sys.exit
            pass
        
        assert mock_exit.called
