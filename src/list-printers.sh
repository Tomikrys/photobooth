#!/usr/bin/env bash
# Lists all printers known to CUPS. Copy the exact name (first column, no "printer" prefix)
# and paste it into PRINTER_NAME in your .env file.
set -e
echo "Available printers (use the name exactly as shown):"
echo "---"
lpstat -p 2>/dev/null | awk '/^printer/ {print $2}'
echo "---"
echo "Default printer:"
lpstat -d 2>/dev/null || echo "  (none set)"
