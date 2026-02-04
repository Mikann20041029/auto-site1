# AutoRSS Lite (One-Shot) — GitHub Pages Demo

## 1) What this does
This repository contains a beginner-friendly tool that:
- fetches **one** item from **one** RSS feed,
- uses **DeepSeek** to generate a short HTML write-up,
- outputs a tiny static website into the **repository root**,
- so you can view it on **GitHub Pages** (Branch: `main` / Folder: `/(root)`).

Important: this is a **LITE one-shot** package. It will run **only once** by design.

---

## 2) Quick start (GitHub only)
You can set this up using only the GitHub website (no local PC required).

You will do:
1. Upload these files to your repository (or use a template repo).
2. Create `config.json` from `config.example.json`.
3. Add a GitHub Actions secret: `DEEPSEEK_API_KEY`.
4. Enable GitHub Pages (main / root).
5. Run the workflow once.

---

## 3) GitHub Pages setup
1. Open your repository on GitHub
2. Click **Settings**
3. In the left sidebar, click **Pages**
4. Under **Build and deployment**:
   - **Source**: Deploy from a branch
   - **Branch**: `main`
   - **Folder**: `/(root)`
5. Click **Save**

After this, GitHub will show your Pages URL. It looks like:
`https://YOURNAME.github.io/YOURREPO/`

---

## 4) GitHub Actions setup
### 4-1) Create the workflow file
Hard rule for this ZIP: it does NOT include a `.github/` folder.
So you must create the workflow file yourself.

1. Go to your repository **Code** tab
2. Click **Add file** → **Create new file**
3. For the file name, type exactly:
   `.github/workflows/WORKFLOW.yml`
4. Copy-paste the YAML below into the editor
5. Click **Commit changes** (commit to `main`)

### 4-2) Workflow YAML (copy-paste)
```yaml
name: Generate site (Lite)

on:
  workflow_dispatch:

permissions:
  contents: write

jobs:
  build:
    runs-on: ubuntu-latest
    steps:
      - name: Checkout
        uses: actions/checkout@v4

      - name: Set up Python
        uses: actions/setup-python@v5
        with:
          python-version: "3.11"

      - name: Install deps
        run: |
          python -m pip install --upgrade pip
          pip install -r requirements.txt || true

      - name: Self test
        run: python main.py --selftest

      - name: Generate site
        env:
          DEEPSEEK_API_KEY: ${{ secrets.DEEPSEEK_API_KEY }}
        run: python main.py

      - name: Commit & push (generated files only)
        run: |
          set -euo pipefail
          git config user.name "github-actions[bot]"
          git config user.email "github-actions[bot]@users.noreply.github.com"

          # Add ONLY generated files (minimum set + posts folder)
          git add index.html sitemap.xml robots.txt assets/style.css assets/app.js posts || true

          if git diff --cached --quiet; then
            echo "No changes to commit."
            exit 0
          fi

          git commit -m "Generate site (Lite)"
          git push
```

---

## 5) How to run (Run workflow)
1. Go to the **Actions** tab
2. Click **Generate site (Lite)** in the left sidebar
3. Click **Run workflow**
4. Click the green **Run workflow** button

Lite runs only once. A file named `.lite_lock.json` will be created after the first success.

---

## 6) Where to see the site (Pages URL)
After the workflow finishes:
- Open **Settings → Pages**
- You will see your site URL

You can also open:
- `https://YOURNAME.github.io/YOURREPO/`
- or `https://YOURNAME.github.io/YOURREPO/index.html`

---

## 7) Troubleshooting

### 7-1) No “Run workflow” button
- Make sure the workflow file is committed to `main`:
  `.github/workflows/WORKFLOW.yml`
- Make sure you are on the repository’s **Actions** tab, and you selected the workflow.

### 7-2) Pages not updated
- Check **Settings → Pages** is set to:
  - Branch: `main`
  - Folder: `/(root)`
- Wait 1–2 minutes and hard refresh the page (mobile browsers cache aggressively).

### 7-3) Commit/push failed
- Confirm your workflow has:
  ```yaml
  permissions:
    contents: write
  ```
- If the repo is protected (branch protection rules), disable protection or allow GitHub Actions to push.

### 7-4) “Copy config.example.json to config.json”
This is expected if you did not create `config.json`.

Fix:
1. Open `config.example.json`
2. Copy it to a new file named `config.json`
3. Edit `site.base_url` and `rss_url`
4. Commit changes

### 7-5) “Missing DEEPSEEK_API_KEY”
You must add a GitHub Actions secret:

Repository → **Settings** → **Secrets and variables** → **Actions** → **New repository secret**
- Name: `DEEPSEEK_API_KEY`
- Value: your DeepSeek API key
