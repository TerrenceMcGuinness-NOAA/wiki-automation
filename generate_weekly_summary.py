#!/usr/bin/env python3
"""
Generate a weekly activity summary (narrative style).

Environment variables:
    GH_TOKEN         PAT with repo read scope.
    GITHUB_ACTOR     GitHub organization/user to track (default: AntonMFernando-NOAA)
    WEEK_START       ISO date (YYYY-MM-DD). Defaults to last Monday.
"""

import os
import sys
import requests
from datetime import date, timedelta, timezone, datetime
from collections import defaultdict

# ── Config ───────────────────────────────────────────────────────────────────
TOKEN = os.environ.get("GH_TOKEN", "")
if not TOKEN:
    sys.exit("Error: GH_TOKEN is not set.")

GITHUB_ACTOR = os.environ.get("GITHUB_ACTOR", "AntonMFernando-NOAA")
WEEK_START_STR = os.environ.get("WEEK_START", "").strip()

# Calculate week start (last Monday) if not provided
if WEEK_START_STR:
    WEEK_START_DATE = date.fromisoformat(WEEK_START_STR)
else:
    today = date.today()
    days_since_monday = (today.weekday()) % 7
    WEEK_START_DATE = today - timedelta(days=days_since_monday)

WEEK_END_DATE = WEEK_START_DATE + timedelta(days=6)  # Sunday

WEEK_START = datetime(WEEK_START_DATE.year, WEEK_START_DATE.month, WEEK_START_DATE.day, 0, 0, 0, tzinfo=timezone.utc)
WEEK_END = datetime(WEEK_END_DATE.year, WEEK_END_DATE.month, WEEK_END_DATE.day, 23, 59, 59, tzinfo=timezone.utc)

HEADERS = {
    "Authorization": f"Bearer {TOKEN}",
    "Accept": "application/vnd.github+json",
    "X-GitHub-Api-Version": "2022-11-28",
}

# ── Helpers ───────────────────────────────────────────────────────────────────
def gh_get(url, params=None):
    """Paginated GitHub API GET request."""
    results, p = [], {"per_page": 100, **(params or {})}
    while url:
        r = requests.get(url, headers=HEADERS, params=p)
        r.raise_for_status()
        data = r.json()
        results.extend(data if isinstance(data, list) else [data])
        url, p = None, {}
        for part in r.headers.get("Link", "").split(","):
            if 'rel="next"' in part:
                url = part.split(";")[0].strip().strip("<>")
    return results

def discover_repos():
    """Auto-discover all repositories for the GitHub actor."""
    if "/" in GITHUB_ACTOR:
        org = GITHUB_ACTOR.split("/")[0]
        url = f"https://api.github.com/orgs/{org}/repos"
    else:
        url = f"https://api.github.com/users/{GITHUB_ACTOR}/repos"
    
    repos = gh_get(url, {"type": "all", "sort": "updated"})
    return [f"{r['owner']['login']}/{r['name']}" for r in repos if not r.get('archived', False)]

def parse_iso(ts_str):
    """Parse ISO8601 timestamp to datetime."""
    if not ts_str:
        return None
    ts_str = ts_str.replace("Z", "+00:00")
    return datetime.fromisoformat(ts_str)

# ── Data Collection ───────────────────────────────────────────────────────────
def collect_week_activity(repos):
    """Collect all activity for the week."""
    activity = {
        'commits': defaultdict(int),
        'prs_merged': 0,
        'prs_opened': 0,
        'issues_opened': 0,
        'issues_closed': 0,
        'highlights': []
    }
    
    for repo in repos:
        try:
            # Commits
            url = f"https://api.github.com/repos/{repo}/commits"
            commits = gh_get(url, {"since": WEEK_START.isoformat(), "until": WEEK_END.isoformat()})
            if commits:
                activity['commits'][repo] = len(commits)
            
            # PRs
            url = f"https://api.github.com/repos/{repo}/pulls"
            prs = gh_get(url, {"state": "all", "sort": "updated", "direction": "desc"})
            
            for pr in prs:
                created = parse_iso(pr['created_at'])
                if created and WEEK_START <= created <= WEEK_END:
                    activity['prs_opened'] += 1
                    
                if pr.get('merged_at'):
                    merged = parse_iso(pr['merged_at'])
                    if merged and WEEK_START <= merged <= WEEK_END:
                        activity['prs_merged'] += 1
                        activity['highlights'].append({
                            'type': 'PR',
                            'repo': repo.split('/')[-1],
                            'title': pr['title'],
                            'url': pr['html_url'],
                            'number': pr['number']
                        })
            
            # Issues
            url = f"https://api.github.com/repos/{repo}/issues"
            issues = gh_get(url, {"state": "all", "sort": "updated", "direction": "desc"})
            
            for issue in issues:
                if 'pull_request' in issue:
                    continue
                    
                created = parse_iso(issue['created_at'])
                if created and WEEK_START <= created <= WEEK_END:
                    activity['issues_opened'] += 1
                
                if issue.get('closed_at'):
                    closed = parse_iso(issue['closed_at'])
                    if closed and WEEK_START <= closed <= WEEK_END:
                        activity['issues_closed'] += 1
                        
        except Exception as e:
            print(f"Warning: Error processing {repo}: {e}", file=sys.stderr)
    
    return activity

# ── Summary Generation ────────────────────────────────────────────────────────
def generate_narrative(activity):
    """Generate narrative summary of the week."""
    parts = []
    
    total_commits = sum(activity['commits'].values())
    num_repos = len(activity['commits'])
    
    if total_commits > 0:
        repo_names = [r.split('/')[-1] for r in activity['commits'].keys()]
        parts.append(f"**{total_commits} commits** across {num_repos} {'repository' if num_repos == 1 else 'repositories'} ({', '.join(repo_names)})")
    
    if activity['prs_merged'] > 0:
        parts.append(f"**{activity['prs_merged']} PR{'s' if activity['prs_merged'] > 1 else ''} merged**")
    
    if activity['prs_opened'] > 0 and activity['prs_opened'] != activity['prs_merged']:
        parts.append(f"**{activity['prs_opened']} PR{'s' if activity['prs_opened'] > 1 else ''} opened**")
    
    if activity['issues_closed'] > 0:
        parts.append(f"**{activity['issues_closed']} issue{'s' if activity['issues_closed'] > 1 else ''} resolved**")
    
    if not parts:
        return "Minimal activity this week - focus on planning and design work."
    
    return ". ".join(parts) + "."

def write_summary(activity):
    """Write weekly summary to file."""
    output = []
    
    # Week header
    week_num = WEEK_START_DATE.isocalendar()[1]
    output.append(f"## Week of {WEEK_START_DATE.strftime('%B %d, %Y')} (Week {week_num})\n")
    
    # Narrative
    narrative = generate_narrative(activity)
    output.append(f"{narrative}\n")
    
    # Highlights if any
    if activity['highlights']:
        output.append("\n### Key Highlights\n")
        for item in activity['highlights'][:10]:  # Top 10
            output.append(f"- **[{item['repo']}#{item['number']}]({item['url']})**: {item['title']}\n")
    
    # Statistics
    if any([activity['commits'], activity['prs_merged'], activity['issues_closed']]):
        output.append("\n<details>\n<summary>Statistics</summary>\n\n")
        
        total_commits = sum(activity['commits'].values())
        if total_commits > 0:
            output.append(f"**Total Commits**: {total_commits}\n")
            for repo, count in sorted(activity['commits'].items(), key=lambda x: x[1], reverse=True):
                output.append(f"- {repo.split('/')[-1]}: {count}\n")
            output.append("\n")
        
        if activity['prs_merged'] or activity['prs_opened']:
            output.append(f"**Pull Requests**: {activity['prs_merged']} merged, {activity['prs_opened']} opened\n\n")
        
        if activity['issues_opened'] or activity['issues_closed']:
            output.append(f"**Issues**: {activity['issues_opened']} opened, {activity['issues_closed']} closed\n\n")
        
        output.append("</details>\n")
    
    output.append("\n---\n\n")
    
    with open("weekly_summary_patch.md", "w") as f:
        f.write("".join(output))
    
    print(f"✓ Weekly summary written for week {week_num} ({WEEK_START_DATE} to {WEEK_END_DATE})")

# ── Main ──────────────────────────────────────────────────────────────────────
def main():
    print(f"Discovering repositories for {GITHUB_ACTOR}...")
    repos = discover_repos()
    print(f"Found {len(repos)} repositories")
    
    print(f"Collecting activity for week of {WEEK_START_DATE} to {WEEK_END_DATE}...")
    activity = collect_week_activity(repos)
    
    print(f"Activity summary:")
    print(f"  Commits: {sum(activity['commits'].values())}")
    print(f"  PRs merged: {activity['prs_merged']}")
    print(f"  PRs opened: {activity['prs_opened']}")
    print(f"  Issues opened: {activity['issues_opened']}")
    print(f"  Issues closed: {activity['issues_closed']}")
    
    write_summary(activity)

if __name__ == "__main__":
    main()
