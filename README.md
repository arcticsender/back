# ArcticSender Stripe Connect Build

This build is patched for the Stripe Connect setup you chose in the Stripe Dashboard:

- Marketplace business model
- Stripe-hosted onboarding
- Express Dashboard for creators
- Destination charges through Stripe Checkout
- ArcticSender application fee, default `2%`
- Creator payouts handled by Stripe Express
- Sender privacy kept intact: creators only see the optional public username/message, not the supporter's email or billing info

## Local install

```bash
cd Arc
python -m venv venv
venv\Scripts\activate
pip install -r requirements.txt
python app.py
```

Open:

```text
http://127.0.0.1:5000
```

The first registered user becomes admin while `AUTO_ADMIN_FIRST_USER=true`.

## Required Stripe environment variables

Add your Stripe test keys first:

```env
APP_ENV=development
SITE_URL=http://127.0.0.1:5000
STRIPE_SECRET_KEY=sk_test_...
STRIPE_PUBLISHABLE_KEY=pk_test_...
STRIPE_WEBHOOK_SECRET=whsec_...
STRIPE_CONNECT_DIRECT_PAYOUTS=true
STRIPE_DEFAULT_COUNTRY=CA
PLATFORM_FEE_PERCENT=2
REQUIRE_STRIPE_PAYMENTS=false
```

For production:

```env
APP_ENV=production
SITE_URL=https://yourdomain.com
SECRET_KEY=use-a-long-random-secret
STRIPE_SECRET_KEY=sk_live_...
STRIPE_PUBLISHABLE_KEY=pk_live_...
STRIPE_WEBHOOK_SECRET=whsec_...
STRIPE_CONNECT_DIRECT_PAYOUTS=true
STRIPE_DEFAULT_COUNTRY=CA
PLATFORM_FEE_PERCENT=2
REQUIRE_STRIPE_PAYMENTS=true
AUTO_ADMIN_FIRST_USER=false
SESSION_COOKIE_SECURE=true
ENABLE_MANUAL_STRIPE_ACCOUNT_ENTRY=false
```


## Stripe troubleshooting built into Settings

The Settings page now shows a full Stripe diagnostics panel:

- live/test/restricted key mode
- the exact Connect return URL being sent to Stripe
- the exact webhook URL to add in Stripe
- whether payments and payouts are enabled
- missing Stripe requirements such as bank account, legal name, business URL, address, or verification
- direct Stripe error messages with the likely fix

For live mode through ngrok, set:

```env
SITE_URL=https://your-ngrok-url.ngrok-free.app
STRIPE_SECRET_KEY=sk_live_...
STRIPE_PUBLISHABLE_KEY=pk_live_...
STRIPE_WEBHOOK_SECRET=whsec_...
```

Then restart Flask. The Connect onboarding URL must never be localhost in live mode.

If an incomplete Stripe account gets stuck, Settings now includes a safe reset button. It only resets accounts that do not have payments or payouts enabled.

## Stripe Connect flow

Creators go to:

```text
/settings
```

Then click:

```text
Connect Stripe
```

The app creates a Stripe Express connected account and redirects the creator to Stripe-hosted onboarding. After they return, the app syncs these Stripe fields:

- `stripe_account_id`
- `stripe_onboarding_complete`
- `stripe_charges_enabled`
- `stripe_payouts_enabled`
- `stripe_country`

Creators can also open their Stripe Express Dashboard from Settings or Dashboard.

## Checkout payout flow

When a supporter checks out:

1. The supporter pays through Stripe Checkout.
2. ArcticSender creates a destination charge.
3. Stripe sends the payout to the creator's connected Express account.
4. ArcticSender keeps `PLATFORM_FEE_PERCENT`, default `2%`.
5. The webhook confirms the payment and marks the order/contributions as paid.
6. The app updates wishlist progress and lifetime received totals.

Because Stripe Connect now handles payouts directly, the app does **not** add paid Stripe Connect gifts to the old manual cashout balance. That prevents duplicate payouts.

## Webhook setup

In Stripe Dashboard, add this webhook endpoint:

```text
https://yourdomain.com/stripe/webhook
```

For local testing with Stripe CLI:

```bash
stripe listen --forward-to localhost:5000/stripe/webhook
```

Subscribe to these events:

```text
checkout.session.completed
account.updated
```

Optional but useful later:

```text
payment_intent.payment_failed
charge.refunded
charge.dispute.created
```

Copy the webhook signing secret into:

```env
STRIPE_WEBHOOK_SECRET=whsec_...
```

## Testing checklist

1. Start the Flask app.
2. Register a creator account.
3. Go to Settings and connect Stripe.
4. Finish test onboarding.
5. Add a cash gift item.
6. Open the public creator page in another browser/session.
7. Add a gift to cart and pay with a Stripe test card.
8. Confirm the webhook receives `checkout.session.completed`.
9. Confirm the gift becomes paid and wishlist progress updates.
10. Confirm the creator can access the Stripe Express Dashboard.

Stripe test card:

```text
4242 4242 4242 4242
Any future date
Any CVC
Any postal code
```

## Notes

- `PLATFORM_FEE_PERCENT=2` is the early creator fee. You can change it to `5` later for your standard fee.
- `STRIPE_DEFAULT_COUNTRY=CA` matches your current Canada-first setup.
- If you later enable the United States, test onboarding and payout eligibility carefully in Stripe first.
- Keep `REQUIRE_STRIPE_PAYMENTS=true` in production so fake/demo payments cannot mark gifts paid.
- Do not show `supporter_email` in creator-facing templates. It is stored only for receipts/support.

## Existing features kept

- Creator signup/login
- Public creator pages at `/@username`
- Cart-based gifting
- Crowdfund goals
- Single cash gift items
- Custom profile donations
- Gift leaderboard using optional public username
- Image upload processing and cropping
- Basic CSRF protection
- SQLite by default, env-based database URL for production
- Optional email notifications

## Production admin account

This build seeds an admin account from `.env` on startup:

```env
ADMIN_EMAIL=support@arcticsender.com
ADMIN_PASSWORD=your-secure-password
ADMIN_USERNAME=admin
ADMIN_DISPLAY_NAME=ArcticSender Support
AUTO_ADMIN_FIRST_USER=false
```

Change the admin password after the first successful login, or replace it in your server environment variables and restart.

## Auto email setup

The app now sends polished branded emails for:

- welcome after registration
- creator gift received
- supporter gift receipt

Set these values in production:

```env
SMTP_HOST=smtp.your-provider.com
SMTP_PORT=587
SMTP_USER=support@arcticsender.com
SMTP_PASSWORD=your-smtp-app-password
MAIL_FROM=support@arcticsender.com
MAIL_REPLY_TO=support@arcticsender.com
```

Use an SMTP/app password from your email host. The normal website admin password is not always the same as the mailbox SMTP password.

## MongoDB backup mirror

The main app still uses SQLAlchemy/SQLite locally so the existing site keeps working, but this build adds a MongoDB Atlas backup mirror for crash recovery. Paid sends, users, items, orders, and cashout records are mirrored to MongoDB when they change, and admins can force a full sync from the Admin page.

Set:

```env
MONGO_URI=mongodb+srv://USER:PASSWORD@cluster.mongodb.net/?retryWrites=true&w=majority
MONGO_DB_NAME=arcticsender
MONGO_BACKUP_ENABLED=true
```

Recommended MongoDB Atlas setup:

1. Create a free M0 cluster.
2. Create a database user.
3. Add your VPS IP to Network Access, or temporarily allow `0.0.0.0/0` if your host IP changes.
4. Copy the Python connection string into `MONGO_URI`.
5. Restart the app and click **Run backup sync** in Admin.

## Production run

Do not run public traffic with Flask debug mode. Use:

```bash
pip install -r requirements.txt
gunicorn app:app
```

Included `Procfile`:

```text
web: gunicorn app:app
```

For production, use HTTPS and set:

```env
APP_ENV=production
SITE_URL=https://yourdomain.com
SESSION_COOKIE_SECURE=true
REQUIRE_STRIPE_PAYMENTS=true
```

## Public page updates

- Homepage cards are smaller, cleaner, and have hover interactions.
- Profile pages no longer carry a big leaderboard panel.
- `/@username/leaderboard` now has the named leaderboard and recent sends.
- Leaderboard only counts named public sends.
- Recent sends can show named or anonymous support while keeping emails private.

## New in this build

### Email OTP for signup and login

This version can require a 6-digit email OTP after signup and after password login. Enable it with:

```env
EMAIL_OTP_ENABLED=true
OTP_EXPIRY_MINUTES=10
MAIL_REQUIRED_FOR_AUTH=true
```

SMTP now supports either naming style:

```env
SMTP_HOST=smtp.your-provider.com
SMTP_PORT=587
SMTP_USER=support@arcticsender.com
SMTP_USERNAME=support@arcticsender.com
SMTP_PASSWORD=your-app-password
SMTP_USE_TLS=true
SMTP_USE_SSL=false
MAIL_FROM=support@arcticsender.com
MAIL_FROM_NAME=ArcticSender
MAIL_REPLY_TO=support@arcticsender.com
```

For port `465`, use:

```env
SMTP_USE_TLS=false
SMTP_USE_SSL=true
```

The Admin dashboard includes a **Send test** email button so you can verify SMTP from the site.

### Self-ping keepalive

The app now includes a health endpoint and optional self-ping thread:

```env
SELF_PING_ENABLED=true
SELF_PING_INTERVAL_SECONDS=60
SELF_PING_URL=
```

Leave `SELF_PING_URL` blank to ping `SITE_URL/healthz`. Use your deployed HTTPS domain in production.

### Advanced admin tools

Admin now includes:

- full account list with email, verification, suspension, Stripe readiness, balances, and last login
- per-user detail pages
- suspend / unsuspend
- verify email manually
- reset password with a temporary password email
- make/remove admin
- toggle creator status
- private admin notes
- user Stripe Connect requirements summary
- recent private support details for helping creators

Passwords are never displayed because the app stores password hashes only. Use the reset password action when an account needs recovery.

## Security hardening included

This build includes production security improvements for auth and admin routes:

- CSRF protection on all POST forms except Stripe webhooks
- Secure session cookie defaults with `HttpOnly`, `SameSite=Lax`, and production HTTPS-only cookies
- Security headers: `X-Frame-Options`, `X-Content-Type-Options`, `Referrer-Policy`, `Permissions-Policy`, and HSTS in production
- Login rate limiting by IP/email
- Account lockout after repeated failed password attempts
- OTP attempt limiting and OTP resend limiting
- Forgot-password reset request limiting
- Password reset tokens are hashed in the database, expire, and are single-use
- Stronger password policy: minimum 10 characters with uppercase, lowercase, number, and symbol
- Admin routes are hidden behind a 404 for non-admin users and also rate-limited
- Admin temporary password resets are emailed only and are no longer displayed in the dashboard flash message

Recommended production values:

```env
APP_ENV=production
SESSION_COOKIE_SECURE=true
SECURITY_HEADERS_ENABLED=true
PASSWORD_MIN_LENGTH=10
LOGIN_MAX_ATTEMPTS=8
LOGIN_WINDOW_SECONDS=900
LOGIN_LOCKOUT_MINUTES=15
OTP_MAX_ATTEMPTS=6
OTP_WINDOW_SECONDS=600
FORGOT_PASSWORD_MAX_ATTEMPTS=5
FORGOT_PASSWORD_WINDOW_SECONDS=3600
ADMIN_MAX_ATTEMPTS=20
ADMIN_WINDOW_SECONDS=600
SESSION_LIFETIME_HOURS=12
```

Important: never commit or upload a real `.env` with live Stripe keys, MongoDB passwords, SMTP passwords, or admin passwords. Use `.env.production.example` as a template and keep the real `.env` only on your server.
