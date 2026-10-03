# SkillForge v7

SkillForge is a consumer skill-building product prototype. v7 moves the project from a simple local dashboard toward a deployable service foundation.

## What's new

- Separate server-side user accounts and sessions
- Password hashing with PBKDF2-HMAC-SHA256
- CSRF protection on state-changing requests
- SQLite-backed per-user profiles, skills, practice events, proof, and challenges
- Custom skill creation/deletion
- Onboarding flow with daily practice target
- Server-side analytics event table
- Password recovery token flow
- Optional SMTP recovery email support
- Stripe Payment Link checkout integration point
- Stripe webhook signature verification and plan entitlement updates
- Security headers and a basic CSP
- JSON account export endpoint
- PWA manifest/service worker
- No fake successful payments

## Run locally

```bash
python3 server.py --port 3010
```

Open:

```text
http://127.0.0.1:3010
```

The server uses only Python's standard library.

## Demo account

Use **Try the demo account** on the login page.

## Optional recovery email configuration

Copy `.env.example` values into your shell environment. The server reads:

```bash
SMTP_HOST=smtp.example.com
SMTP_PORT=587
SMTP_USERNAME=...
SMTP_PASSWORD=...
SMTP_FROM=no-reply@example.com
APP_ORIGIN=https://your-domain.example
```

Without SMTP, development mode exposes a recovery token directly so the flow can be tested locally. Do not leave `SKILLFORGE_DEV=1` in a public deployment.

## Stripe

Configure a real Stripe Payment Link for checkout:

```bash
export STRIPE_PAYMENT_LINK='https://buy.stripe.com/REPLACE_ME'
```

For webhook-based entitlement updates, configure:

```bash
export STRIPE_WEBHOOK_SECRET='whsec_REPLACE_ME'
```

The webhook endpoint is:

```text
POST /api/stripe/webhook
```

The sample implementation maps common checkout/subscription events to an email-based account. A production integration should use Stripe customer/subscription IDs stored server-side rather than relying on email as the durable identity key.

## Production checklist

Before public launch, put the app behind HTTPS and a reverse proxy, add rate limiting and abuse protection, move SQLite to managed PostgreSQL, use a real email provider, add verified-email enforcement, rotate secrets securely, centralize structured logging, add database backups/migrations, store Stripe IDs and durable subscription state, and add monitoring.

## Product model

The commercial hypothesis is consumer subscription software. Example pricing can be tested around a monthly and annual plan, but revenue is not guaranteed. A $1M annualized gross-revenue target at $8.99/month would require roughly 9,268 continuously paying subscribers before fees, refunds, taxes, and churn effects.


## v6 public launch
The project now includes `render.yaml`, `Procfile`, `.gitignore`, production-safe host/port defaults, persistent SQLite configuration, and `DEPLOY_COM.md`. For a first public launch, deploy to Render and attach a custom `.com` domain. Later migrate SQLite to managed Postgres before multi-instance scaling.
