# Makefile - Simplified operations without CI/CD

.PHONY: help setup test deploy-dev deploy-prod package clean validate

help:
	@echo "Available commands:"
	@echo "  make setup        - Initial project setup"
	@echo "  make test         - Run all tests"
	@echo "  make validate     - Validate Terraform and Python code"
	@echo "  make deploy-dev   - Deploy to development"
	@echo "  make deploy-prod  - Deploy to production"
	@echo "  make package      - Create release package"
	@echo "  make clean        - Clean temporary files"

setup:
	@bash scripts/setup.sh

test:
	python3 full_test_suite.py

validate:
	@echo "🔍 Validating Terraform..."
	cd terraform && terraform fmt -check && terraform validate
	@echo "🔍 Validating Python..."
	python3 -m pylint *.py

deploy-dev:
	DEPLOY_ENV=dev python3 redeploy_interactive.py

deploy-prod:
	@echo "⚠️  Production deployment - are you sure? [y/N]"
	@read ans && [ $${ans:-N} = y ]
	DEPLOY_ENV=production python3 redeploy_interactive.py

package:
	python3 scripts/create_release_package.py $(VERSION)

clean:
	rm -rf logs/*.log
	rm -rf __pycache__ **/__pycache__
	rm -rf .terraform
	find . -name "*.pyc" -delete