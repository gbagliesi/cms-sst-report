#!/bin/bash
# update_and_publish.command
# Double-click from Finder: generates the report, opens it locally, and pushes to GitHub Pages.

set -e
cd "$(dirname "$0")"

echo "=== CMS SST Report — $(date) ==="
echo ""

# 1. Generate report
echo "[1/4] Generating report..."
python3 cms_site_report.py --days 3 --out docs/index.html
echo "      -> docs/index.html generated"
echo ""

# 2. Open local copy in browser
echo "[2/4] Opening local preview..."
open docs/index.html
echo ""

# 3. Git: pull + commit + push
echo "[3/4] Pushing to GitHub..."
git add docs/index.html

if git diff --cached --quiet; then
    echo "      -> No changes since last push, skipping commit."
else
    git commit -m "chore: manual report update $(date -u '+%Y-%m-%d %H:%M UTC')"
    git pull --rebase --autostash
    git push
    echo "      -> Pushed to GitHub."
fi
echo ""

# 4. Done
echo "[4/4] Done."
echo "      Local:  file://$(pwd)/docs/index.html"
echo "      GitHub: https://gbagliesi.github.io/cms-sst-report/"
echo ""
echo "GitHub Pages will update in ~1-2 minutes."
read -p "Press Enter to close..."
