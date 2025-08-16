import os
import subprocess
from pathlib import Path
import time
import sys
from itertools import cycle
import requests
import json
import getpass

class Spinner:
    def __init__(self):
        self.spinner = cycle(['⠋','⠙','⠹','⠸','⠼','⠴','⠦','⠧','⠇','⠏'])
    
    def spin(self, text):
        sys.stdout.write(f'\r{next(self.spinner)} {text}')
        sys.stdout.flush()

def run_git_command(command, check=True, show_spinner=True, retry_count=0, max_retries=3):
    spinner = Spinner()
    try:
        print(f"\nExecuting: git {' '.join(command[1:])}")
        if show_spinner:
            process = subprocess.Popen(command, stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True)
            while process.poll() is None:
                spinner.spin("Working...")
                time.sleep(0.1)
            stdout, stderr = process.communicate()
            result = subprocess.CompletedProcess(command, process.returncode, stdout, stderr)
        else:
            result = subprocess.run(command, check=check, capture_output=True, text=True)
        
        if result.returncode == 0:
            return result
        
        # Auto-retry on push failures with limit
        if 'push' in command and result.returncode != 0 and retry_count < max_retries:
            print(f"\nPush failed (attempt {retry_count + 1}/{max_retries + 1}), retrying...")
            print(f"Error: {result.stderr}")
            time.sleep(2)
            return run_git_command(command, check, show_spinner, retry_count + 1, max_retries)
            
        if result.stderr:
            print(f"\nError/Warning: {result.stderr}")
        return result
    except subprocess.CalledProcessError as e:
        print(f"\nError: {e.stderr}")
        return None
    except KeyboardInterrupt:
        print("\nOperation cancelled by user")
        return None

def setup_git():
    # Initialize git if not already initialized
    if not Path('.git').exists():
        subprocess.run(['git', 'init'])
        # Set default branch to main
        subprocess.run(['git', 'config', 'init.defaultBranch', 'main'])
        subprocess.run(['git', 'checkout', '-b', 'main'])
        # Add .gitignore if it doesn't exist
        if not Path('.gitignore').exists():
            Path('.gitignore').touch()
        # Force add all files including hidden ones
        subprocess.run(['git', 'add', '-f', '.'])
        subprocess.run(['git', 'commit', '-m', 'Initial commit'])
    else:
        # Check current branch and switch to main if needed
        result = subprocess.run(['git', 'branch', '--show-current'], capture_output=True, text=True)
        current_branch = result.stdout.strip()
        if current_branch != 'main':
            # Rename current branch to main
            subprocess.run(['git', 'branch', '-M', 'main'])

def check_repo_exists(username, repo_name, token):
    """Check if a GitHub repository exists"""
    url = f"https://api.github.com/repos/{username}/{repo_name}"
    headers = {
        'Authorization': f'token {token}',
        'Accept': 'application/vnd.github.v3+json'
    }
    
    try:
        response = requests.get(url, headers=headers)
        return response.status_code == 200
    except requests.RequestException:
        return False

def create_github_repo(username, repo_name, token):
    """Create a new GitHub repository"""
    url = "https://api.github.com/user/repos"
    headers = {
        'Authorization': f'token {token}',
        'Accept': 'application/vnd.github.v3+json',
        'Content-Type': 'application/json'
    }
    
    data = {
        'name': repo_name,
        'private': False,  # Set to True if you want private repos
        'description': f'Repository for {repo_name}',
        'auto_init': False
    }
    
    try:
        print(f"\nCreating repository '{repo_name}'...")
        response = requests.post(url, headers=headers, data=json.dumps(data))
        
        if response.status_code == 201:
            print(f"✅ Repository '{repo_name}' created successfully!")
            return True
        else:
            print(f"❌ Failed to create repository. Status: {response.status_code}")
            print(f"Response: {response.text}")
            return False
    except requests.RequestException as e:
        print(f"❌ Error creating repository: {e}")
        return False

def get_github_credentials():
    """Get GitHub username and token"""
    print("\n=== GitHub Authentication ===")
    username = input("Enter your GitHub username: ").strip()
    print("\nYou need a GitHub Personal Access Token with 'repo' permissions.")
    print("Create one at: https://github.com/settings/tokens")
    token = getpass.getpass("Enter your GitHub Personal Access Token: ").strip()
    
    return username, token

def setup_git_credentials(username, token):
    """Configure git credentials for GitHub authentication"""
    # Configure git user info
    run_git_command(['git', 'config', 'user.name', username])
    run_git_command(['git', 'config', 'user.email', f'{username}@users.noreply.github.com'])
    
    # Configure credential helper
    run_git_command(['git', 'config', 'credential.helper', 'store'])
    
    # Store credentials for this repository
    credentials_file = Path.home() / '.git-credentials'
    credential_line = f'https://{username}:{token}@github.com\n'
    
    # Read existing credentials
    existing_credentials = []
    if credentials_file.exists():
        with open(credentials_file, 'r') as f:
            existing_credentials = f.readlines()
    
    # Remove any existing GitHub credentials for this user
    filtered_credentials = [line for line in existing_credentials if not line.startswith(f'https://{username}:') or 'github.com' not in line]
    
    # Add new credentials
    filtered_credentials.append(credential_line)
    
    # Write back to file
    with open(credentials_file, 'w') as f:
        f.writelines(filtered_credentials)
    
    print(f"✅ Git credentials configured for {username}")

def sync_with_github(username, repo_name, token):
    repo_url = f"https://github.com/{username}/{repo_name}.git"
    print(f"\nSynchronizing with {repo_url}")
    
    # Check if repo exists, create if it doesn't
    if not check_repo_exists(username, repo_name, token):
        print(f"\nRepository '{repo_name}' not found.")
        create_choice = input("Would you like to create it? (y/n): ").strip().lower()
        
        if create_choice in ['y', 'yes']:
            if not create_github_repo(username, repo_name, token):
                print("❌ Failed to create repository. Exiting...")
                return
            # Wait a moment for repo to be fully created
            time.sleep(2)
        else:
            print("❌ Repository creation cancelled. Exiting...")
            return
    else:
        print(f"✅ Repository '{repo_name}' found!")
    
    # Setup git credentials
    setup_git_credentials(username, token)
    
    # Check if remote exists
    remote_exists = run_git_command(['git', 'remote', 'get-url', 'origin'], check=False)
    
    if remote_exists and remote_exists.returncode == 0:
        # Remove existing remote if URL is different
        current_url = remote_exists.stdout.strip()
        if current_url != repo_url:
            run_git_command(['git', 'remote', 'remove', 'origin'])
            run_git_command(['git', 'remote', 'add', 'origin', repo_url])
    else:
        # Add new remote
        run_git_command(['git', 'remote', 'add', 'origin', repo_url])
    
    # Force add all files including hidden ones
    run_git_command(['git', 'add', '-f', '.'])
    
    # Check if there are changes to commit
    status_result = run_git_command(['git', 'status', '--porcelain'], show_spinner=False)
    if status_result and status_result.stdout.strip():
        run_git_command(['git', 'commit', '-m', 'Update project files'])
    
    # Push to main branch
    result = run_git_command(['git', 'push', '-u', 'origin', 'main'])
    
    if result and result.returncode == 0:
        print("\n🎉 Successfully synchronized with GitHub!")
        print(f"📂 Repository URL: https://github.com/{username}/{repo_name}")
    else:
        print("\n❌ Sync failed. Please check the error messages above.")
        if result and result.stderr:
            print(f"Last error: {result.stderr}")
            # Suggest manual fix
            print(f"\n💡 You can try manually:")
            print(f"   git remote add origin {repo_url}")
            print(f"   git push -u origin main")

if __name__ == '__main__':
    print("🚀 GitHub Repository Sync Tool")
    print("=" * 40)
    
    # Get GitHub credentials
    username, token = get_github_credentials()
    
    # Get repository name
    print(f"\n=== Repository Setup ===")
    repo_name = input("Enter repository name (e.g., 'flashcardsproject'): ").strip()
    
    if not repo_name:
        print("❌ Repository name cannot be empty!")
        sys.exit(1)
    
    # Setup git first
    print("\n📁 Setting up local Git repository...")
    setup_git()
    
    # Then sync with GitHub
    sync_with_github(username, repo_name, token)