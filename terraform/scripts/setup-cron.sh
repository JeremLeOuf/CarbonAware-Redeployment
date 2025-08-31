#!/bin/bash
# Setup cron jobs for automated monitoring and redeployment

# Add to crontab
(crontab -l 2>/dev/null; echo "
# CarbonAware Monitoring - Every 5 minutes
*/5 * * * * cd /path/to/carbon-aware && /usr/bin/python3 monitor.py

# Automated Carbon Check - Every hour
0 * * * * cd /path/to/carbon-aware && /usr/bin/python3 redeploy_auto.py

# Daily backup of Terraform state
0 2 * * * cd /path/to/carbon-aware && bash scripts/backup-state.sh
") | crontab -

echo "✅ Cron jobs configured for automated monitoring"