# SkillForge v6 — put it on a .com

SkillForge is now deployment-ready for a real HTTPS domain, but a `.com` domain itself must be registered and DNS-connected outside this codebase.

## 1. Pick the domain

`skillforge.com` is already registered, so do not build your launch around that exact domain unless you negotiate to acquire it. Choose a distinct `.com` and verify it at a registrar before paying.

Examples to check (availability is not guaranteed):
- getskillforge.com
- myskillforge.com
- skillforgenow.com
- skillforgepractice.com

## 2. Put this project in GitHub

```bash
cd ~/skillforge_v6
git init
git add .
git commit -m "SkillForge v6"
# create an empty GitHub repository, then add its remote
git branch -M main
git push -u origin main
```

Never commit `.env`, credentials, or `skillforge.db`.

## 3. Deploy on Render

Create a new Render Blueprint/Web Service from the repository. The included `render.yaml` configures a Python web service, health check, environment variables, and a persistent disk for the current SQLite database.

Set `APP_ORIGIN` to your final HTTPS domain, for example `https://example.com`. Keep `COOKIE_SECURE=1` in production.

## 4. Connect the .com

In the Render service, add your custom domain. Render then shows the DNS configuration you need to add at the registrar. Render provisions TLS and redirects HTTP to HTTPS.

## 5. Payments and email

Set the Stripe payment link and webhook secret in Render. Configure your email provider before enabling password recovery for real customers.

## 6. Important scaling note

This v6 package keeps SQLite because it is the smallest path from your Chromebook prototype to a public launch. Render says its filesystem is ephemeral by default, so the Blueprint uses a persistent disk for the database. Persistent disks are single-instance and prevent horizontal scaling; when growth requires multiple instances, migrate the data layer to managed Postgres.
