# GooCampus HR Portal - Render Deployment Guide

## Step 1: Create a GitHub Repository

1. Go to https://github.com/new
2. Name it `goocampus-hr-portal` (private recommended)
3. Open Terminal on your Mac and run:

```bash
cd ~/Desktop/Employee\ Dashboard
git init
git add -A
git commit -m "Initial commit - GooCampus HR Portal"
git branch -M main
git remote add origin https://github.com/YOUR_USERNAME/goocampus-hr-portal.git
git push -u origin main
```

## Step 2: Deploy on Render

1. Go to https://render.com and sign up (use GitHub login)
2. Click "New" > "Web Service"
3. Connect your GitHub repo `goocampus-hr-portal`
4. Render will auto-detect the settings from `render.yaml`, but verify:
   - **Name:** goocampus-hr-portal
   - **Runtime:** Python
   - **Build Command:** `pip install -r requirements.txt`
   - **Start Command:** `gunicorn app:app --bind 0.0.0.0:$PORT --workers 2`
5. Click "Create Web Service"

## Step 3: Set Up the Database

1. In Render dashboard, go to "New" > "PostgreSQL"
2. Name it `goocampus-hr-db`, select the Free plan
3. Once created, copy the **Internal Database URL**
4. Go to your Web Service > Environment > add:
   - `DATABASE_URL` = (paste the Internal Database URL)
   - `SECRET_KEY` = (any random string, e.g. `goocampus-hr-2026-secure-key`)

## Step 4: Seed the Database

After the first deploy, you need to populate the database with employees and holidays.

1. In your Render Web Service dashboard, go to "Shell"
2. Run: `python seed_prod.py`
3. This creates all tables, adds the admin user, all 20 employees, and 2026 holidays

## Step 5: Upload Employee Photos

The `static/photos/` folder with employee photos is included in the repo. These will be deployed automatically with the code.

## Step 6: Connect Your Domain (Optional)

1. In Render, go to your Web Service > Settings > Custom Domains
2. Add your domain (e.g. `hr.goocampus.com`)
3. In your domain registrar (GoDaddy/others), add a CNAME record:
   - **Name:** `hr` (or `@` for root domain)
   - **Value:** `goocampus-hr-portal.onrender.com`
4. Wait for DNS propagation (usually 5-30 minutes)

## Login Credentials

- **Admin:** emp_code = `admin`, password = `admin`
- **Employees:** emp_code = first name (lowercase), password = same as emp_code

## Local Development

The app works with SQLite locally (no PostgreSQL needed):

```bash
cd ~/Desktop/Employee\ Dashboard
pip install -r requirements.txt
python seed_data.py    # Only first time, to create the database
python app.py          # Starts on http://localhost:8080
```
