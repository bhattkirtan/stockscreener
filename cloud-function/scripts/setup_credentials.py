#!/usr/bin/env python3
"""
Quick credential helper - pulls from Cloud Function or prompts for manual entry
"""

import os
import json
import subprocess

def get_credentials_from_cloud_function():
    """Try to get credentials from deployed Cloud Function"""
    print("🔍 Attempting to fetch credentials from Cloud Function...")
    
    try:
        # Get the secret name from Cloud Function
        result = subprocess.run([
            'gcloud', 'functions', 'describe', 'marketServiceLive',
            '--region=us-central1',
            '--project=double-venture-442318-k8',
            '--format=json'
        ], capture_output=True, text=True, timeout=10)
        
        if result.returncode != 0:
            print(f"   ❌ Failed to describe function: {result.stderr}")
            return None
        
        func_data = json.loads(result.stdout)
        
        # Find the secret
        secret_vars = func_data.get('secretEnvironmentVariables', [])
        secret_name = None
        for var in secret_vars:
            if var.get('key') == 'apicredentials':
                secret_name = var.get('secret')
                break
        
        if not secret_name:
            print("   ❌ No apicredentials secret found in function")
            return None
        
        # Get the secret value
        result = subprocess.run([
            'gcloud', 'secrets', 'versions', 'access', 'latest',
            '--secret', secret_name,
            '--project=double-venture-442318-k8'
        ], capture_output=True, text=True, timeout=10)
        
        if result.returncode != 0:
            print(f"   ❌ Failed to access secret: {result.stderr}")
            return None
        
        credentials = json.loads(result.stdout.strip())
        print("   ✅ Successfully retrieved credentials from Cloud Function")
        return credentials
        
    except subprocess.TimeoutExpired:
        print("   ❌ gcloud command timed out")
        return None
    except Exception as e:
        print(f"   ❌ Error: {e}")
        return None


def create_env_file(credentials):
    """Create .env file with credentials"""
    env_content = f"""# Capital.com API Credentials
# Auto-generated from Cloud Function

apicredentials={json.dumps(credentials)}

# Optional: Enable debug logging
# DEBUG=true

# Optional: Use live environment (default is demo)
# CAPITAL_ENV=demo
"""
    
    with open('.env', 'w') as f:
        f.write(env_content)
    
    print("✅ Created .env file with credentials")


def main():
    print("\n" + "="*70)
    print("🔐 Credential Setup")
    print("="*70)
    
    # Check if .env already exists
    if os.path.exists('.env'):
        print("\n✅ .env file already exists")
        
        # Verify it has credentials
        from dotenv import load_dotenv
        load_dotenv()
        
        if os.getenv('apicredentials'):
            print("   Credentials found in .env")
            return True
        else:
            print("   ⚠️  No credentials in .env, will fetch new ones")
    
    # Try to get from Cloud Function
    credentials = get_credentials_from_cloud_function()
    
    if credentials:
        create_env_file(credentials)
        return True
    
    # Fallback to manual setup
    print("\n⚠️  Could not auto-fetch credentials")
    print("\n📝 Manual setup options:")
    print("   1. Run: python3 setup_local_env.py")
    print("   2. Or manually copy .env. example to .env and fill in credentials")
    
    return False


if __name__ == '__main__':
    import sys
    success = main()
    sys.exit(0 if success else 1)
