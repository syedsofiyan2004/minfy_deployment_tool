# Test Collection Error Fixes

This document provides instructions to fix the test collection errors across all test files.

## Common Issues

1. **Fixture Name Mismatch**: Using `mock_aws_client` instead of the `mock_boto3` fixture defined in conftest.py
2. **Import Issues**: Missing or incorrect imports
3. **Path Handling**: Inconsistent path handling between Windows and Unix
4. **Mock Parameter Issues**: Mock functions with incorrect parameters

## Step-by-Step Fix Instructions

### 1. Update Fixture References 

Change all references from `mock_aws_client` to `mock_boto3`:

- In `test_deploy.py` and `test_deploy_fixed.py`:
  ```python
  @pytest.fixture
  def mock_s3(mock_boto3):
      """Fixture for S3 client"""
      return mock_boto3['s3']
  ```

- In `test_status_rollback.py` and `test_status_rollback_fixed.py`:
  ```python
  @pytest.fixture
  def mock_s3_status(mock_boto3):
      """Fixture for S3 client with status data"""
      s3_client = mock_boto3['s3']
  ```
  
  ```python
  @pytest.fixture
  def mock_s3_rollback(mock_boto3):
      """Fixture for S3 client with rollback data"""
      s3_client = mock_boto3['s3']
  ```

- In `test_monitor.py` and `test_monitor_fixed.py`:
  - Remove the custom `mock_aws_client` fixture and use `mock_boto3` instead
  - Update all test functions to use `mock_boto3` instead of `mock_aws_client`

### 2. Add Missing Imports

Ensure each test file has all necessary imports:

```python
import os
import sys
import json
import tempfile
from pathlib import Path
from unittest.mock import patch, MagicMock
import pytest
from click.testing import CliRunner
```

### 3. Fix Path Handling

Replace Unix-style paths with platform-independent paths:

```python
# Instead of:
'/tmp/test'

# Use:
os.path.join(tempfile.gettempdir(), 'test')
```

### 4. Fix Lambda Function Parameters

Ensure lambda functions correctly handle all expected parameters:

```python
# Instead of:
mock_exists.side_effect = lambda p: 'angular.json' not in str(p)

# Use a proper function:
def path_exists_side_effect(p):
    return 'angular.json' not in str(p)

mock_exists.side_effect = path_exists_side_effect
```

### 5. Update SystemExit Tests

For tests expecting SystemExit, patch sys.exit instead:

```python
# Instead of:
with pytest.raises(SystemExit):
    result = runner.invoke(cmd)

# Use:
with patch('sys.exit') as mock_exit:
    mock_exit.side_effect = Exception("Exited")
    try:
        result = runner.invoke(cmd)
    except Exception:
        pass
    assert mock_exit.called
```

## Running the Tests

After applying these fixes, run the tests with:

```powershell
cd d:\Capstone_Projects\capstone-cli\minfy-cli
python -m pytest
```

## Troubleshooting

If you still encounter collection errors:

1. Check for syntax errors in the test files
2. Ensure all fixtures are properly defined
3. Check that all imports are correct
4. Look for missing parentheses or indentation issues
