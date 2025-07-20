# Fix Test Collection Errors
# Run this script to fix common test collection errors

import os
import re

def replace_in_file(file_path, old_str, new_str):
    """Replace old_str with new_str in file_path"""
    if not os.path.exists(file_path):
        print(f"Warning: File {file_path} does not exist. Skipping.")
        return False
    
    with open(file_path, 'r', encoding='utf-8') as file:
        content = file.read()
    
    if old_str not in content:
        print(f"Warning: String not found in {file_path}. Skipping.")
        return False
    
    content = content.replace(old_str, new_str)
    
    with open(file_path, 'w', encoding='utf-8') as file:
        file.write(content)
    
    print(f"Updated {file_path}")
    return True

def fix_test_files():
    """Fix common issues in test files"""
    base_path = os.path.dirname(os.path.abspath(__file__))
    tests_path = os.path.join(base_path, 'tests')
    
    test_files = [f for f in os.listdir(tests_path) if f.startswith('test_') and f.endswith('.py')]
    
    # Fix 1: Replace mock_aws_client with mock_boto3
    for file_name in test_files:
        file_path = os.path.join(tests_path, file_name)
        replace_in_file(file_path, 'mock_aws_client', 'mock_boto3')
        
        # Fix specific fixture definitions
        replace_in_file(file_path, 
                        '@pytest.fixture\ndef mock_s3(mock_aws_client):', 
                        '@pytest.fixture\ndef mock_s3(mock_boto3):')
        
        replace_in_file(file_path,
                        'return mock_aws_client[\'s3\']',
                        'return mock_boto3[\'s3\']')
        
        replace_in_file(file_path,
                        's3_client = mock_aws_client[\'s3\']',
                        's3_client = mock_boto3[\'s3\']')
    
    # Fix 2: Fix path handling
    for file_name in test_files:
        file_path = os.path.join(tests_path, file_name)
        with open(file_path, 'r', encoding='utf-8') as file:
            content = file.read()
        
        # Replace Unix-style paths
        if "'/tmp/test'" in content:
            content = content.replace("'/tmp/test'", "os.path.join(tempfile.gettempdir(), 'test')")
            
            # Ensure imports
            if 'import os' not in content:
                content = 'import os\n' + content
            if 'import tempfile' not in content:
                content = 'import tempfile\n' + content
                
            with open(file_path, 'w', encoding='utf-8') as file:
                file.write(content)
            print(f"Fixed path handling in {file_path}")
    
    print("All fixes applied! Now run: python -m pytest")

if __name__ == '__main__':
    fix_test_files()
