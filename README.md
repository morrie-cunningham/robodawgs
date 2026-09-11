# RoboDawgs Record Book

All-time awards & competition stats for Grandville RoboDawgs robotics,
harvested from the RobotEvents API.

## Files
- `index.html` — the record book page (static, no backend)
- `robodawgs-data.js` — the dataset the page loads
- `robodawgs-data.json` — same data, used by `harvest.py` for merges
- `harvest.py` — data collector

## Updating after a competition
```
python3 harvest.py                  # full refresh (~30 min)
python3 harvest.py --only=244,288   # just these base numbers, merged (fast)
git add robodawgs-data.* && git commit -m "data refresh" && git push
```
Requires a `.re_token` file (RobotEvents API token) next to harvest.py.
The token is git-ignored — never commit it.
