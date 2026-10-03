# Security notes

This project is a launch candidate, not a certification or security guarantee.

Before taking real customer traffic, use HTTPS, keep secrets in the host's secret environment variables, rotate exposed credentials, add centralized rate limiting, monitor authentication failures, back up the database, and review the application with a security professional.

Never commit `.env`, `skillforge.db`, API keys, Stripe webhook secrets, SMTP passwords, or recovery tokens.
