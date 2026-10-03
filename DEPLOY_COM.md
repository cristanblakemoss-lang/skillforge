# SkillForge v8 — public launch checklist

## Current public service
The existing Render service is reachable at:

https://skillforge-yxyl.onrender.com

Before attaching a custom domain, verify `/api/health` returns the expected version and the homepage loads.

## Render settings

Use the GitHub `main` branch.

Build command:

```bash
python3 -m py_compile server.py
```

Start command:

```bash
python3 server.py --host 0.0.0.0 --port $PORT --db /var/data/skillforge.db
```

Health check:

```text
/api/health
```

Production environment variables:

```text
SKILLFORGE_DEV=0
COOKIE_SECURE=1
APP_ORIGIN=https://YOUR-DOMAIN.com
```

Do not commit Stripe or SMTP secrets to Git.

## Custom .com

1. Register a `.com` domain with a registrar you control.
2. In Render, open the SkillForge web service and add the domain under Custom Domains.
3. Render will show the exact DNS records for that service. Copy those values into the registrar's DNS panel.
4. Verify the domain in Render.
5. Render provisions TLS and redirects HTTP to HTTPS.

Do not copy DNS values from an old deployment; use the records Render shows for the current service.

## Production data

The smallest launch path uses SQLite on a persistent disk. For a growing multi-instance service, migrate to managed PostgreSQL. Keep backups and test restore procedures.

## Payments

Configure a real Stripe Payment Link and webhook secret only after the public domain and HTTPS are working. The webhook endpoint is:

```text
POST /api/stripe/webhook
```

The server stores Stripe customer/subscription identifiers when available.

## Email

Configure SMTP before enabling public password recovery and email verification. Until then, do not expose development tokens; keep `SKILLFORGE_DEV=0`.

## Launch gate

Before accepting real payments, verify:

- HTTPS works on the custom domain.
- Email verification works.
- Password recovery email works.
- Account deletion works.
- Data export works.
- Stripe checkout works.
- Stripe webhooks update plan state.
- Database backups exist.
- Privacy and Terms pages contain your actual business/contact information.
