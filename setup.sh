#!/bin/bash
# setup.sh - Complete deployment setup

set -e  # Exit on error

echo "🌱 CarbonAware Redeployment Setup"
echo "=================================="

# Check prerequisites
command -v terraform >/dev/null 2>&1 || { echo "❌ Terraform not installed"; exit 1; }
command -v python3 >/dev/null 2>&1 || { echo "❌ Python 3 not installed"; exit 1; }
command -v aws >/dev/null 2>&1 || { echo "❌ AWS CLI not installed"; exit 1; }

# Create virtual environment
echo "📦 Setting up Python environment..."
python3 -m venv venv
source venv/bin/activate
pip install -r requirements.txt

# Check AWS credentials
echo "🔐 Verifying AWS credentials..."
aws sts get-caller-identity > /dev/null || { echo "❌ AWS credentials not configured"; exit 1; }

# Initialize Terraform
echo "🏗️ Initializing Terraform..."
cd terraform
terraform init
cd ..

# Create .env from template
if [ ! -f .env ]; then
    echo "📝 Creating .env file..."
    cp .env.template .env
    echo "⚠️  Please edit .env with your API tokens"
fi

echo "✅ Setup complete! Run 'python3 redeploy_interactive.py' to deploy"