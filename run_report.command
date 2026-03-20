#!/bin/bash
cd "$(dirname "$0")"
python3 cms_site_report.py --out cms_report.html && open cms_report.html
