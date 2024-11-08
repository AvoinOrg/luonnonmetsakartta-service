#!/usr/bin/env python3

import toml
import subprocess
import sys

def main():
    # Load the pyproject.toml file
    try:
        with open('pyproject.toml', 'r') as f:
            data = toml.load(f)
    except FileNotFoundError:
        print("Error: pyproject.toml not found in the current directory.")
        sys.exit(1)
    except toml.TomlDecodeError as e:
        print(f"Error parsing pyproject.toml: {e}")
        sys.exit(1)

    # Get the dependencies excluding 'python'
    dependencies = data.get('tool', {}).get('poetry', {}).get('dependencies', {})
    dev_dependencies = data.get('tool', {}).get('poetry', {}).get('dev-dependencies', {})

    # Function to update dependencies
    def update_packages(packages, dev=False):
        for package, value in packages.items():
            if package == 'python':
                continue  # Skip updating the Python version
            # Initialize package extras
            package_extras = []
            if isinstance(value, dict):
                # Check if the package has 'extras'
                package_extras = value.get('extras', [])
            # Construct the package name with extras
            if package_extras:
                package_name = f"{package}[{','.join(package_extras)}]"
            else:
                package_name = package
            # Construct the command to update the package
            cmd = ['poetry', 'add']
            if dev:
                cmd.append('--group dev')
            cmd.append(f'{package_name}@latest')
            # Run the command
            print(f"Updating {package_name} to the latest version...")
            result = subprocess.run(cmd)
            if result.returncode != 0:
                print(f"Failed to update {package}.")
                sys.exit(1)

    # Update main dependencies
    update_packages(dependencies)
    # Update development dependencies
    update_packages(dev_dependencies, dev=True)

    print("All dependencies have been updated to their latest versions.")

if __name__ == '__main__':
    main()
