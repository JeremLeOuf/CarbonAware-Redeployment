#!/usr/bin/env python3
"""
Create a release package with all necessary files and configurations
"""

import os
import json
import shutil
import tarfile
import hashlib
from datetime import datetime, timezone
from pathlib import Path


def calculate_checksum(filepath):
    """Calculate SHA256 checksum of a file"""
    sha256_hash = hashlib.sha256()
    with open(filepath, "rb") as f:
        for byte_block in iter(lambda: f.read(4096), b""):
            sha256_hash.update(byte_block)
    return sha256_hash.hexdigest()


def create_release(release_version="1.0.0"):
    """Create a complete release package"""

    release_dir = Path(f"releases/v{release_version}")
    release_dir.mkdir(parents=True, exist_ok=True)

    # Files to include in release
    release_files = {
        'terraform': ['terraform/**/*.tf', 'terraform/**/*.tfvars.example'],
        'scripts': ['*.py', 'scripts/*.sh', 'requirements.txt'],
        'config': ['config/**/*.py', '.env.template'],
        'docs': ['README.md', 'LICENSE']
    }

    print(f"📦 Creating release package v{release_version}")

    # Copy files to release directory
    for category, patterns in release_files.items():
        category_dir = release_dir / category
        category_dir.mkdir(exist_ok=True)

        for pattern in patterns:
            for file in Path('.').glob(pattern):
                if file.is_file():
                    dest = category_dir / file.name
                    shutil.copy2(file, dest)
                    print(f"  ✓ Added {file}")

    # Create deployment manifest
    manifest = {
        "version": release_version,
        "created_at": datetime.now(timezone.utc).isoformat(),
        "requirements": {
            "terraform": ">=1.0.0",
            "python": ">=3.8",
            "aws_cli": ">=2.0",
            "docker": ">=20.10 (optional)",
        },
        "files": {},
        "deployment_steps": [
            "1. Extract package contents",
            "2. Run setup.sh for initial configuration",
            "3. Configure .env with your API tokens",
            "4. Run terraform init in terraform/ directory",
            "5. Execute python3 redeploy_interactive.py",
        ],
    }

    # Add file checksums
    for root, _, files in os.walk(release_dir):
        for file in files:
            filepath = Path(root) / file
            rel_path = filepath.relative_to(release_dir)
            manifest["files"][str(rel_path)] = {
                "size": filepath.stat().st_size,
                "checksum": calculate_checksum(filepath)
            }

    # Save manifest
    manifest_path = release_dir / "manifest.json"
    with open(manifest_path, 'w', encoding='utf-8') as f:
        json.dump(manifest, f, indent=2)

    # Create tarball
    tarball_name = f"carbon-aware-v{release_version}.tar.gz"
    with tarfile.open(tarball_name, "w:gz") as tar:
        tar.add(release_dir, arcname=f"carbon-aware-v{release_version}")

    print(f"\n✅ Release package created: {tarball_name}")
    print(f"📋 Total files: {len(manifest['files'])}")
    print(
        f"💾 Package size: {os.path.getsize(tarball_name) / 1024 / 1024:.2f} MB")

    return tarball_name


if __name__ == "__main__":
    import sys
    version = sys.argv[1] if len(sys.argv) > 1 else "1.0.0"
    create_release(version)
