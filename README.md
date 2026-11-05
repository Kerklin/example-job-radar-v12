# Job Radar V12 - complete setup

## Two repository files
- radar.py at repository root
- publish.yml saved as .github/workflows/publish.yml

## New repository, browser-only setup
1. Create a PUBLIC repository named job-radar-v12. Keep main as default branch.
2. Upload radar.py to the root and commit.
3. Add file > Create new file. Type .github/workflows/publish.yml.
4. Paste the full contents of supplied publish.yml and commit.
5. Settings > Pages > Source: GitHub Actions.
6. Actions > Job Radar V12 > Run workflow.
7. After build and deploy finish, Settings > Pages > Visit site. Bookmark that address.
Do not upload publish.yml at the root and expect it to run.
Do not copy old workflows from earlier versions into this new repository.

## UNDP addition
The official UNDP Oracle Careers portal is configured as an automatic HTML adapter
and as a permanent manual link. This replaces obsolete UNDP RSS feeds.
The adapter recognizes vacancy links under /jobs/preview/<number> and /job/<number>.
If the server returns only a JavaScript shell or blocks requests, source health
reports UNAVAILABLE. This version does NOT run a headless browser or invent an
undocumented Oracle API. Therefore automatic UNDP extraction is conditional on
server-visible vacancy links; it is not a verified full Oracle integration.
Only visible first-page listings are covered. No exhaustive-search claim.

## Sources
UNDP, UNICEF, UNOPS, UN Careers, UNjobs, Impactpool and UNJobsFeed are configured.
These are adapters, not a promise that every website permits automation.
robots.txt exclusions, CAPTCHA and access blocks are respected.
Manual links remain visible when automatic collection fails.

## Outputs
The script generates site/index.html and site/jobs.json. You upload neither.
The dashboard embeds data directly; no missing JOBS.md or browser JSON request.
Search and track filters, source health, known deadlines and retained-result labels.
Source failures retain previous results for at most seven days when the previous
published data is reachable. Expired labelled dates are removed. Unknown dates
remain unknown. Cross-site duplicate vacancies may remain under different URLs.

## Scoring
Six career tracks. A configured phrase scores 24 in the title or 8 in the description.
Strongest track wins; minimum technical score 16. Sarajevo/Bosnia/Western Balkans
adds 10 after that gate. Scores are priorities, not eligibility percentages.
UNDP Tier 0/1/2-only wording is screened conservatively; manually check the exact
vacancy restrictions. Internal AND external wording is not automatically excluded.

## Validation
28 unit/regression test methods passed twice, 0.039 seconds each.
Includes UNDP link extraction, JavaScript-shell recognition, tier-only exclusion,
external wording, XML repair, RSS, Atom, HTML, safety, retention and deduplication.
Workflow YAML parsed. No real GitHub deployment or UNDP live extraction verified.
Earlier live sandbox checks of external sources returned HTTP 403.
Run python3 radar.py test locally; the workflow also tests before building.
No promise of error-free operation or all-source coverage.

## Costs and limits
Use a public repository and standard GitHub-hosted runners. No AI, user secrets,
email service, paid API, or Python package installation. Schedules are best-effort
and can be delayed or disabled by GitHub after inactivity. No email configured.

## Full workflow (same as publish.yml)
```yaml
name: Job Radar V12
on:
  push:
    branches: [main]
  workflow_dispatch:
  schedule:
    - cron: '23 */6 * * *'
permissions:
  contents: read
  pages: write
  id-token: write
concurrency:
  group: job-radar-pages
  cancel-in-progress: false
jobs:
  build:
    runs-on: ubuntu-latest
    timeout-minutes: 6
    steps:
      - uses: actions/checkout@v6
      - name: Regression tests
        run: python3 radar.py test
      - name: Build dashboard
        run: python3 radar.py
        env:
          PREVIOUS_DATA_URL: https://${{ github.repository_owner }}.github.io/${{ github.event.repository.name }}/jobs.json
      - uses: actions/upload-pages-artifact@v5
        with:
          path: site
  deploy:
    needs: build
    runs-on: ubuntu-latest
    environment:
      name: github-pages
      url: ${{ steps.publish.outputs.page_url }}
    steps:
      - id: publish
        uses: actions/deploy-pages@v5
```
