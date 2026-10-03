# SkillForge v7 — .com launch checklist

A `.com` site is a deployment + domain configuration, not a setting inside the app. This build is prepared for a public HTTPS deployment, but the domain must be registered in an account you control.

## 1. Register a domain

`skillforge.com` is already registered, so choose a different name and confirm availability at the registrar immediately before purchase.

Examples to check:

- getskillforge.com
- myskillforge.com
- skillforgenow.com
- skillforgepractice.com

These are suggestions, not availability claims.

## 2. Push the code to GitHub

```bash
cd ~/SkillForge_v7
git init
git add .
git commit -m "SkillForge v7 public launch"
git branch -M main
git remote add origin https://github.com/YOUR-USERNAME/YOUR-REPO.git
git push -u origin main
```

Never commit `.env`, passwords, Stripe secrets, SMTP credentials, or `skillforge.db`.

## 3. Deploy the app

The repository includes `render.yaml`, `Procfile`, and a `Dockerfile`.

For Render:

1. Create a new web service from the GitHub repository.
2. Use the Blueprint in `render.yaml`, or configure the service to run `python3 server.py --host 0.0.0.0 --port $PORT`.
3. Set `APP_ORIGIN` to your eventual HTTPS origin, for example `https://example.com`.
4. Set `COOKIE_SECURE=1`.
5. Configure Stripe and SMTP secrets only through the hosting provider's secret environment variables.

## 4. Attach the .com

In Render, add your purchased domain to the service. Render will show the DNS records for that service. Add those records at the registrar, then verify the domain in Render.

Do not copy a DNS value from an old deployment. Use the exact records Render shows for the current service.

## 5. HTTPS

Keep the public site on HTTPS. Render provisions TLS for custom domains and redirects HTTP traffic to HTTPS.

## 6. Production requirements before taking payment

- Move SQLite to managed PostgreSQL before multi-instance scaling.
- Add real email verification and password-reset email delivery.
- Use durable Stripe customer/subscription IDs in the database.
- Turn off development recovery-token responses.
- Add rate limiting, bot protection, structured logging, backups, and monitoring.
- Test account deletion and data export.
- Publish privacy and terms pages with your real business/contact information.

## 7. Target architecture

```text
Your .com
   ↓
HTTPS
   ↓
Public app service
   ↓
SkillForge API
   ↓
PostgreSQL
   ↓
Stripe + email provider
   ↓
Analytics + backups + monitoring
```

The business target is not guaranteed by the software. Measure activation, week-1 retention, paid conversion, churn, and acquisition cost before treating the $1M/year goal as a forecast.
