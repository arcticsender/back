import os
import re
import secrets
import threading
import time
import json
import urllib.error
import urllib.request

try:
    import requests
except ImportError:
    requests = None
from html import escape
from datetime import datetime, UTC, timedelta
from functools import wraps
from decimal import Decimal, ROUND_HALF_UP

try:
    import stripe
except ImportError:  # allows the app to boot before dependencies are installed
    stripe = None
try:
    from pymongo import MongoClient, ASCENDING
except ImportError:  # Mongo backup is optional until pymongo is installed/configured
    MongoClient = None
    ASCENDING = None
try:
    import certifi
except ImportError:
    certifi = None
from dotenv import load_dotenv
from flask import Flask, render_template, request, redirect, url_for, flash, session, abort, jsonify, Response
from flask_sqlalchemy import SQLAlchemy
from werkzeug.security import generate_password_hash, check_password_hash
from werkzeug.utils import secure_filename
try:
    from PIL import Image, ImageOps
except ImportError:
    Image = None
    ImageOps = None

load_dotenv()

BASE_DIR = os.path.abspath(os.path.dirname(__file__))
INSTANCE_DIR = os.path.join(BASE_DIR, 'instance')
UPLOAD_FOLDER = os.path.join(BASE_DIR, 'static', 'img', 'uploads')
os.makedirs(INSTANCE_DIR, exist_ok=True)
os.makedirs(UPLOAD_FOLDER, exist_ok=True)

app = Flask(__name__)
app.config['SECRET_KEY'] = os.getenv('SECRET_KEY', 'dev-change-this-secret')
app.config.update(
    SESSION_COOKIE_HTTPONLY=True,
    SESSION_COOKIE_SAMESITE=os.getenv('SESSION_COOKIE_SAMESITE', 'Lax'),
    PERMANENT_SESSION_LIFETIME=timedelta(hours=int(os.getenv('SESSION_LIFETIME_HOURS', '12'))),
)

# Database setup
# By default, store SQLite safely inside ./instance/arcticsender.db.
# If DATABASE_URL is provided in .env, relative SQLite paths are expanded from the project folder
# and their parent folders are created automatically to avoid "unable to open database file".
def build_database_uri():
    database_url = os.getenv('DATABASE_URL', '').strip()
    default_db_path = os.path.join(INSTANCE_DIR, 'arcticsender.db')

    if not database_url:
        return 'sqlite:///' + default_db_path.replace('\\', '/')

    if database_url.startswith('sqlite:///'):
        raw_path = database_url.replace('sqlite:///', '', 1)
        # Keep Windows absolute paths like C:/Users/... as absolute.
        is_windows_abs = re.match(r'^[A-Za-z]:[\\/]', raw_path) is not None
        if not os.path.isabs(raw_path) and not is_windows_abs:
            raw_path = os.path.join(BASE_DIR, raw_path)
        os.makedirs(os.path.dirname(os.path.abspath(raw_path)), exist_ok=True)
        return 'sqlite:///' + os.path.abspath(raw_path).replace('\\', '/')

    return database_url

app.config['SQLALCHEMY_DATABASE_URI'] = build_database_uri()
app.config['SQLALCHEMY_TRACK_MODIFICATIONS'] = False
app.config['UPLOAD_FOLDER'] = UPLOAD_FOLDER
app.config['MAX_CONTENT_LENGTH'] = 8 * 1024 * 1024
if os.getenv('SESSION_COOKIE_SECURE', 'true' if os.getenv('APP_ENV', '').lower() == 'production' else 'false').lower() == 'true':
    app.config.update(SESSION_COOKIE_SECURE=True)

SITE_NAME = os.getenv('SITE_NAME', 'ArcticSender')
BASE_URL = (os.getenv('SITE_URL') or os.getenv('BASE_URL') or 'http://127.0.0.1:5000').rstrip('/')
STRIPE_SECRET_KEY = os.getenv('STRIPE_SECRET_KEY', '')
STRIPE_PUBLISHABLE_KEY = os.getenv('STRIPE_PUBLISHABLE_KEY', '')
STRIPE_WEBHOOK_SECRET = os.getenv('STRIPE_WEBHOOK_SECRET', '')
STRIPE_AUTO_TRANSFERS = os.getenv('STRIPE_AUTO_TRANSFERS', 'false').lower() == 'true'
# IMPORTANT: keep this false for the ArcticSender wallet model.
# False = supporter payments land in the platform Stripe balance, then the creator's
# website balance is credited after the webhook confirms payment. Creators only use
# Stripe Express when they cash out.
# True is the old destination-charge mode where money goes to the creator's
# connected Stripe balance immediately.
STRIPE_CONNECT_DIRECT_PAYOUTS = os.getenv('STRIPE_CONNECT_DIRECT_PAYOUTS', 'false').lower() == 'true'
STRIPE_DEFAULT_COUNTRY = os.getenv('STRIPE_DEFAULT_COUNTRY', 'CA').upper().strip() or 'CA'
PLATFORM_FEE_PERCENT = Decimal(os.getenv('PLATFORM_FEE_PERCENT', '2'))
AUTO_ADMIN_FIRST_USER = os.getenv('AUTO_ADMIN_FIRST_USER', 'true').lower() == 'true'
APP_ENV = os.getenv('APP_ENV', 'development').lower()
REQUIRE_STRIPE_PAYMENTS = os.getenv('REQUIRE_STRIPE_PAYMENTS', 'true' if APP_ENV == 'production' else 'false').lower() == 'true'
ENABLE_MANUAL_STRIPE_ACCOUNT_ENTRY = os.getenv('ENABLE_MANUAL_STRIPE_ACCOUNT_ENTRY', 'false').lower() == 'true'
# Email setup
# Render blocks many outbound SMTP ports on common plans, so this app sends mail
# through Resend's HTTPS API instead of smtplib/SMTP.
RESEND_API_KEY = (os.getenv('RESEND_API_KEY') or '').strip()
RESEND_API_URL = (os.getenv('RESEND_API_URL') or 'https://api.resend.com/emails').strip()
MAIL_FROM = os.getenv('MAIL_FROM') or 'ArcticSender <onboarding@resend.dev>'
MAIL_FROM_NAME = os.getenv('MAIL_FROM_NAME') or SITE_NAME
MAIL_REPLY_TO = os.getenv('MAIL_REPLY_TO', 'support@arcticsender.com')
EMAIL_LOGO_URL = (os.getenv('EMAIL_LOGO_URL') or '').strip()
EMAIL_OTP_ENABLED = os.getenv('EMAIL_OTP_ENABLED', 'true').lower() == 'true'
OTP_EXPIRY_MINUTES = int(os.getenv('OTP_EXPIRY_MINUTES', '10'))
MAIL_REQUIRED_FOR_AUTH = os.getenv('MAIL_REQUIRED_FOR_AUTH', 'true').lower() == 'true'
SELF_PING_ENABLED = os.getenv('SELF_PING_ENABLED', 'false').lower() == 'true'
SELF_PING_URL = (os.getenv('SELF_PING_URL') or f'{BASE_URL}/healthz').strip()
SELF_PING_INTERVAL_SECONDS = max(30, int(os.getenv('SELF_PING_INTERVAL_SECONDS', '60')))
ADMIN_EMAIL = os.getenv('ADMIN_EMAIL', '').lower().strip()
ADMIN_PASSWORD = os.getenv('ADMIN_PASSWORD', '')
ADMIN_USERNAME = os.getenv('ADMIN_USERNAME', 'admin')
ADMIN_DISPLAY_NAME = os.getenv('ADMIN_DISPLAY_NAME', 'ArcticSender Support')
MONGO_URI = os.getenv('MONGO_URI', '').strip()
MONGO_URI_PLACEHOLDERS = ('cluster.mongodb.net', '<cluster>', 'your_real_cluster', 'user:password@')
MONGO_DB_NAME = os.getenv('MONGO_DB_NAME', 'arcticsender')
MONGO_BACKUP_ENABLED = os.getenv('MONGO_BACKUP_ENABLED', 'true').lower() == 'true'
PASSWORD_MIN_LENGTH = max(10, int(os.getenv('PASSWORD_MIN_LENGTH', '10')))
LOGIN_MAX_ATTEMPTS = max(3, int(os.getenv('LOGIN_MAX_ATTEMPTS', '8')))
LOGIN_WINDOW_SECONDS = max(60, int(os.getenv('LOGIN_WINDOW_SECONDS', '900')))
LOGIN_LOCKOUT_MINUTES = max(5, int(os.getenv('LOGIN_LOCKOUT_MINUTES', '15')))
OTP_MAX_ATTEMPTS = max(3, int(os.getenv('OTP_MAX_ATTEMPTS', '6')))
OTP_WINDOW_SECONDS = max(60, int(os.getenv('OTP_WINDOW_SECONDS', '600')))
FORGOT_PASSWORD_MAX_ATTEMPTS = max(3, int(os.getenv('FORGOT_PASSWORD_MAX_ATTEMPTS', '5')))
FORGOT_PASSWORD_WINDOW_SECONDS = max(300, int(os.getenv('FORGOT_PASSWORD_WINDOW_SECONDS', '3600')))
ADMIN_MAX_ATTEMPTS = max(5, int(os.getenv('ADMIN_MAX_ATTEMPTS', '20')))
ADMIN_WINDOW_SECONDS = max(60, int(os.getenv('ADMIN_WINDOW_SECONDS', '600')))
SECURITY_HEADERS_ENABLED = os.getenv('SECURITY_HEADERS_ENABLED', 'true').lower() == 'true'

if STRIPE_SECRET_KEY and stripe:
    stripe.api_key = STRIPE_SECRET_KEY

db = SQLAlchemy(app)
_mongo_client = None

MIN_CASHOUT_CENTS = 1000
SMALL_CASHOUT_LIMIT_CENTS = 3500
SMALL_CASHOUT_FEE_CENTS = 350
MIN_GIFT_CENTS = 100

def validate_production_config():
    if APP_ENV != 'production':
        return
    missing = []
    if not os.getenv('SECRET_KEY') or app.config['SECRET_KEY'] == 'dev-change-this-secret':
        missing.append('SECRET_KEY')
    if not STRIPE_SECRET_KEY:
        missing.append('STRIPE_SECRET_KEY')
    if not STRIPE_PUBLISHABLE_KEY:
        missing.append('STRIPE_PUBLISHABLE_KEY')
    if not STRIPE_WEBHOOK_SECRET:
        missing.append('STRIPE_WEBHOOK_SECRET')
    if not BASE_URL.startswith('https://'):
        missing.append('BASE_URL must be https:// in production')
    if missing:
        raise RuntimeError('Production config incomplete: ' + ', '.join(missing))


validate_production_config()

SUPPORTED_CURRENCIES = {
    'usd': {'label': 'USD $', 'symbol': '$', 'rate': Decimal('1.00')},
    'cad': {'label': 'CAD C$', 'symbol': 'C$', 'rate': Decimal('1.37')},
    'eur': {'label': 'EUR €', 'symbol': '€', 'rate': Decimal('0.92')},
    'gbp': {'label': 'GBP £', 'symbol': '£', 'rate': Decimal('0.79')},
    'aud': {'label': 'AUD A$', 'symbol': 'A$', 'rate': Decimal('1.52')},
}


class User(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    username = db.Column(db.String(32), unique=True, nullable=False, index=True)
    display_name = db.Column(db.String(80), nullable=False)
    email = db.Column(db.String(140), unique=True, nullable=False, index=True)
    password_hash = db.Column(db.String(255), nullable=False)
    bio = db.Column(db.Text, default='')
    avatar_url = db.Column(db.String(300), default='')
    banner_url = db.Column(db.String(300), default='')
    socials = db.Column(db.String(500), default='')
    stripe_account_id = db.Column(db.String(100), default='')
    stripe_onboarding_complete = db.Column(db.Boolean, default=False)
    stripe_charges_enabled = db.Column(db.Boolean, default=False)
    stripe_payouts_enabled = db.Column(db.Boolean, default=False)
    stripe_country = db.Column(db.String(2), default='CA')
    balance_cents = db.Column(db.Integer, nullable=False, default=0)
    lifetime_earned_cents = db.Column(db.Integer, nullable=False, default=0)
    pending_cashout_cents = db.Column(db.Integer, nullable=False, default=0)
    is_creator = db.Column(db.Boolean, default=True)
    is_admin = db.Column(db.Boolean, default=False)
    is_suspended = db.Column(db.Boolean, default=False)
    email_verified = db.Column(db.Boolean, default=False)
    signup_otp_hash = db.Column(db.String(255), default='')
    signup_otp_expires_at = db.Column(db.DateTime, nullable=True)
    login_otp_hash = db.Column(db.String(255), default='')
    login_otp_expires_at = db.Column(db.DateTime, nullable=True)
    password_changed_at = db.Column(db.DateTime, nullable=True)
    last_login_at = db.Column(db.DateTime, nullable=True)
    last_seen_at = db.Column(db.DateTime, nullable=True)
    failed_login_count = db.Column(db.Integer, nullable=False, default=0)
    locked_until = db.Column(db.DateTime, nullable=True)
    last_failed_login_at = db.Column(db.DateTime, nullable=True)
    admin_note = db.Column(db.Text, default='')
    created_at = db.Column(db.DateTime, default=lambda: datetime.now(UTC).replace(tzinfo=None))

    wishlist_items = db.relationship('WishlistItem', backref='creator', lazy=True, cascade='all, delete-orphan')

    @property
    def balance(self):
        return self.balance_cents / 100

    @property
    def lifetime_earned(self):
        return self.lifetime_earned_cents / 100


class WishlistItem(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    creator_id = db.Column(db.Integer, db.ForeignKey('user.id'), nullable=False)
    title = db.Column(db.String(120), nullable=False)
    description = db.Column(db.Text, default='')
    image_url = db.Column(db.String(300), default='')
    product_url = db.Column(db.String(500), default='')
    price_cents = db.Column(db.Integer, nullable=False, default=0)
    funded_cents = db.Column(db.Integer, nullable=False, default=0)
    gift_type = db.Column(db.String(20), default='single')  # single or goal
    stock_count = db.Column(db.Integer, nullable=False, default=1)  # single purchase quantity, 1-99
    display_order = db.Column(db.Integer, nullable=False, default=0)
    priority = db.Column(db.String(20), default='normal')
    is_active = db.Column(db.Boolean, default=True)
    created_at = db.Column(db.DateTime, default=lambda: datetime.now(UTC).replace(tzinfo=None))

    @property
    def price(self):
        return self.price_cents / 100

    @property
    def funded(self):
        return self.funded_cents / 100

    @property
    def stock_limit(self):
        if self.gift_type != 'single':
            return 1
        try:
            return min(99, max(1, int(self.stock_count or 1)))
        except Exception:
            return 1

    @property
    def sold_count(self):
        if self.gift_type != 'single' or self.price_cents <= 0:
            return 0
        return min(self.stock_limit, max(0, self.funded_cents // self.price_cents))

    @property
    def remaining_stock(self):
        if self.gift_type != 'single':
            return 0
        return max(0, self.stock_limit - self.sold_count)

    @property
    def remaining_cents(self):
        if self.gift_type == 'single':
            return self.price_cents if self.remaining_stock > 0 else 0
        return max(0, self.price_cents - self.funded_cents)

    @property
    def progress(self):
        if self.gift_type != 'goal' or self.price_cents <= 0:
            return 0
        return min(100, round((self.funded_cents / self.price_cents) * 100))

    @property
    def is_funded(self):
        if self.gift_type == 'single':
            return self.remaining_stock <= 0
        return self.price_cents > 0 and self.funded_cents >= self.price_cents

    @property
    def type_label(self):
        return 'Crowdfund goal' if self.gift_type == 'goal' else 'Single cash gift'


class Contribution(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    creator_id = db.Column(db.Integer, db.ForeignKey('user.id'), nullable=False)
    item_id = db.Column(db.Integer, db.ForeignKey('wishlist_item.id'), nullable=True)
    support_type = db.Column(db.String(20), nullable=False, default='custom')  # custom, single, goal
    supporter_name = db.Column(db.String(80), default='Anonymous')
    supporter_email = db.Column(db.String(140), default='')
    message = db.Column(db.Text, default='')
    amount_cents = db.Column(db.Integer, nullable=False)
    status = db.Column(db.String(30), default='pending')
    stripe_session_id = db.Column(db.String(255), default='', index=True)
    stripe_payment_intent = db.Column(db.String(255), default='')
    order_id = db.Column(db.Integer, db.ForeignKey('checkout_order.id'), nullable=True, index=True)
    currency = db.Column(db.String(10), default='usd')
    charged_amount_cents = db.Column(db.Integer, nullable=False, default=0)
    platform_fee_cents = db.Column(db.Integer, nullable=False, default=0)
    created_at = db.Column(db.DateTime, default=lambda: datetime.now(UTC).replace(tzinfo=None))
    paid_at = db.Column(db.DateTime, nullable=True)

    creator = db.relationship('User', backref='contributions')
    item = db.relationship('WishlistItem', backref='contributions')
    order = db.relationship('CheckoutOrder', backref='contributions')



class CheckoutOrder(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    token = db.Column(db.String(64), unique=True, nullable=False, index=True)
    creator_id = db.Column(db.Integer, db.ForeignKey('user.id'), nullable=False)
    supporter_name = db.Column(db.String(80), default='Anonymous')  # public display only
    supporter_email = db.Column(db.String(140), default='')  # private receipt/support only
    message = db.Column(db.Text, default='')
    total_amount_cents = db.Column(db.Integer, nullable=False, default=0)  # USD ledger value
    charged_amount_cents = db.Column(db.Integer, nullable=False, default=0)
    platform_fee_cents = db.Column(db.Integer, nullable=False, default=0)
    currency = db.Column(db.String(10), default='usd')
    status = db.Column(db.String(30), default='pending')
    stripe_session_id = db.Column(db.String(255), default='', index=True)
    created_at = db.Column(db.DateTime, default=lambda: datetime.now(UTC).replace(tzinfo=None))
    paid_at = db.Column(db.DateTime, nullable=True)

    creator = db.relationship('User', backref='checkout_orders')


class CashoutRequest(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    creator_id = db.Column(db.Integer, db.ForeignKey('user.id'), nullable=False)
    gross_cents = db.Column(db.Integer, nullable=False)
    fee_cents = db.Column(db.Integer, nullable=False, default=0)
    net_cents = db.Column(db.Integer, nullable=False)
    status = db.Column(db.String(30), default='pending')
    stripe_transfer_id = db.Column(db.String(255), default='')
    admin_note = db.Column(db.Text, default='')
    created_at = db.Column(db.DateTime, default=lambda: datetime.now(UTC).replace(tzinfo=None))
    completed_at = db.Column(db.DateTime, nullable=True)

    creator = db.relationship('User', backref='cashout_requests')


class PasswordResetToken(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    user_id = db.Column(db.Integer, db.ForeignKey('user.id'), nullable=False, index=True)
    token_hash = db.Column(db.String(255), nullable=False)
    expires_at = db.Column(db.DateTime, nullable=False)
    used_at = db.Column(db.DateTime, nullable=True)
    created_at = db.Column(db.DateTime, default=lambda: datetime.now(UTC).replace(tzinfo=None))

    user = db.relationship('User', backref='password_reset_tokens')

    @property
    def is_active(self):
        return self.used_at is None and self.expires_at >= datetime.now(UTC).replace(tzinfo=None)


def money(cents):
    return f"${cents / 100:,.2f}"


def display_money(cents, currency='usd'):
    meta = SUPPORTED_CURRENCIES.get((currency or 'usd').lower(), SUPPORTED_CURRENCIES['usd'])
    return f"{meta['symbol']}{cents / 100:,.2f} {currency.upper()}"


def normalize_currency(value):
    value = (value or 'usd').lower().strip()
    return value if value in SUPPORTED_CURRENCIES else 'usd'


def convert_usd_to_currency_cents(usd_cents, currency):
    currency = normalize_currency(currency)
    rate = SUPPORTED_CURRENCIES[currency]['rate']
    return max(1, int((Decimal(usd_cents) * rate).quantize(Decimal('1'), rounding=ROUND_HALF_UP)))


def platform_fee_for_cents(amount_cents):
    try:
        fee = (Decimal(max(0, int(amount_cents))) * (PLATFORM_FEE_PERCENT / Decimal('100'))).quantize(Decimal('1'), rounding=ROUND_HALF_UP)
        return max(0, int(fee))
    except Exception:
        return 0


def creator_stripe_ready(user):
    if not user or not user.stripe_account_id:
        return False
    # In wallet mode creators only need payouts enabled for cashouts.
    # In legacy direct-payout mode Stripe also needs charges enabled because Checkout
    # creates destination charges on the connected account.
    if STRIPE_CONNECT_DIRECT_PAYOUTS:
        return bool(user.stripe_payouts_enabled and user.stripe_charges_enabled)
    return bool(user.stripe_payouts_enabled)


def stripe_key_mode():
    if STRIPE_SECRET_KEY.startswith('sk_live_'):
        return 'live'
    if STRIPE_SECRET_KEY.startswith('sk_test_'):
        return 'test'
    if STRIPE_SECRET_KEY.startswith('rk_'):
        return 'restricted'
    return 'missing' if not STRIPE_SECRET_KEY else 'unknown'


def stripe_config_status():
    mode = stripe_key_mode()
    issues = []
    warnings = []
    if not stripe:
        issues.append('The stripe Python package is not installed. Run: pip install stripe')
    if not STRIPE_SECRET_KEY:
        issues.append('Missing STRIPE_SECRET_KEY in .env.')
    elif mode == 'restricted':
        issues.append('STRIPE_SECRET_KEY is a restricted key (rk_...). Use a standard secret key that starts with sk_test_ or sk_live_.')
    elif mode == 'unknown':
        issues.append('STRIPE_SECRET_KEY has an unknown format. It should start with sk_test_ or sk_live_.')
    if not STRIPE_PUBLISHABLE_KEY:
        warnings.append('Missing STRIPE_PUBLISHABLE_KEY in .env. Checkout can still be created server-side, but frontend Stripe features may not work.')
    if mode == 'live' and not BASE_URL.startswith('https://'):
        issues.append('Live Stripe Connect requires SITE_URL/BASE_URL to be an HTTPS URL. Localhost and http:// are blocked by Stripe.')
    if mode == 'live' and ('localhost' in BASE_URL or '127.0.0.1' in BASE_URL):
        issues.append('Live Stripe Connect cannot redirect to localhost. Use your deployed HTTPS domain or an HTTPS ngrok URL for testing.')
    if not STRIPE_WEBHOOK_SECRET:
        warnings.append('Missing STRIPE_WEBHOOK_SECRET. Payments may complete, but your site cannot securely receive Stripe payment/account updates.')
    return {
        'mode': mode,
        'base_url': BASE_URL,
        'issues': issues,
        'warnings': warnings,
        'webhook_url': f'{BASE_URL}/stripe/webhook',
        'connect_return_url': f'{BASE_URL}/stripe/connect/return',
        'connect_refresh_url': f'{BASE_URL}/stripe/connect/refresh',
    }


def stripe_exception_message(exc):
    """Return a safe, useful Stripe error message without exposing secret keys."""
    raw = getattr(exc, 'user_message', None) or getattr(exc, 'message', None) or str(exc)
    raw = str(raw)
    # Hide key material if Stripe echoes a key in the exception text.
    raw = re.sub(r'\b[rs]k_(live|test)_[A-Za-z0-9_]+', r'***_\1_hidden', raw)
    code = getattr(exc, 'code', None)
    http_status = getattr(exc, 'http_status', None)
    parts = [raw]
    if code:
        parts.append(f'Code: {code}')
    if http_status:
        parts.append(f'HTTP: {http_status}')
    # Add the most common fix in plain language.
    lower = raw.lower()
    if 'localhost' in lower or 'https' in lower:
        parts.append('Fix: set SITE_URL in .env to a real HTTPS URL, such as your ngrok HTTPS URL or your deployed domain, then restart Flask.')
    if 'restricted' in lower or 'required permissions' in lower or STRIPE_SECRET_KEY.startswith('rk_'):
        parts.append('Fix: replace the restricted rk_ key with a normal Stripe secret key starting with sk_live_ or sk_test_.')
    if 'not completed onboarding' in lower:
        parts.append('Fix: click Continue Stripe Onboarding first. The Express Dashboard only works after onboarding is complete.')
    return ' | '.join(parts)


def format_requirement_key(key):
    labels = {
        'external_account': 'Bank account / debit card for payouts',
        'business_profile.url': 'Business/profile URL',
        'business_profile.mcc': 'Business category',
        'individual.first_name': 'Legal first name',
        'individual.last_name': 'Legal last name',
        'individual.dob.day': 'Date of birth',
        'individual.dob.month': 'Date of birth',
        'individual.dob.year': 'Date of birth',
        'individual.email': 'Email address',
        'individual.phone': 'Phone number',
        'individual.address.line1': 'Address',
        'individual.address.city': 'City',
        'individual.address.postal_code': 'Postal code',
        'individual.address.state': 'Province/state',
        'tos_acceptance.date': 'Stripe terms acceptance',
        'tos_acceptance.ip': 'Stripe terms acceptance',
    }
    return labels.get(key, key.replace('_', ' ').replace('.', ' → '))


def stripe_account_details(user):
    """Fetch connected-account status for the settings page."""
    data = {
        'account': None,
        'error': '',
        'currently_due': [],
        'eventually_due': [],
        'past_due': [],
        'pending_verification': [],
        'disabled_reason': '',
        'details_submitted': False,
        'charges_enabled': False,
        'payouts_enabled': False,
        'requirements_count': 0,
    }
    if not user or not user.stripe_account_id or not STRIPE_SECRET_KEY or not stripe:
        return data
    try:
        account = stripe.Account.retrieve(user.stripe_account_id)
        reqs = account.get('requirements') or {}
        data.update({
            'account': account,
            'currently_due': [format_requirement_key(x) for x in (reqs.get('currently_due') or [])],
            'eventually_due': [format_requirement_key(x) for x in (reqs.get('eventually_due') or [])],
            'past_due': [format_requirement_key(x) for x in (reqs.get('past_due') or [])],
            'pending_verification': [format_requirement_key(x) for x in (reqs.get('pending_verification') or [])],
            'disabled_reason': reqs.get('disabled_reason') or '',
            'details_submitted': bool(account.get('details_submitted', False)),
            'charges_enabled': bool(account.get('charges_enabled', False)),
            'payouts_enabled': bool(account.get('payouts_enabled', False)),
        })
        data['requirements_count'] = len(data['currently_due']) + len(data['past_due'])
        user.stripe_onboarding_complete = data['details_submitted']
        user.stripe_charges_enabled = data['charges_enabled']
        user.stripe_payouts_enabled = data['payouts_enabled']
        if account.get('country'):
            user.stripe_country = account.get('country')
        db.session.commit()
    except Exception as exc:
        data['error'] = stripe_exception_message(exc)
        app.logger.warning('Could not retrieve Stripe account status for user %s: %s', user.id, data['error'])
    return data


def sync_stripe_account_status(user):
    stripe_account_details(user)
    return user


def stripe_payout_status_label(user):
    if not user or not user.stripe_account_id:
        return 'Not connected'
    if STRIPE_CONNECT_DIRECT_PAYOUTS:
        if user.stripe_payouts_enabled and user.stripe_charges_enabled:
            return 'Ready for direct Stripe payouts'
        if user.stripe_payouts_enabled and not user.stripe_charges_enabled:
            return 'Payouts enabled, payments not fully enabled'
    else:
        if user.stripe_payouts_enabled:
            return 'Ready for balance cashouts'
    if user.stripe_onboarding_complete:
        return 'Submitted, waiting on Stripe verification'
    return 'Onboarding incomplete'



def get_cart():
    return session.setdefault('gift_cart', {'creator_id': None, 'items': []})


def save_cart(cart):
    session['gift_cart'] = cart
    session.modified = True


def clear_cart():
    session.pop('gift_cart', None)
    session.modified = True


def cart_count():
    cart = session.get('gift_cart') or {}
    return len(cart.get('items', []))


def cart_total_cents():
    cart = session.get('gift_cart') or {}
    return sum(max(0, int(entry.get('amount_cents', 0))) for entry in cart.get('items', []))


def cart_creator_username():
    cart = session.get('gift_cart') or {}
    creator_id = cart.get('creator_id')
    if not creator_id:
        return None
    user = db.session.get(User, creator_id)
    return user.username if user else None


def cart_url():
    username = cart_creator_username()
    if username:
        return url_for('cart', username=username)
    return url_for('global_cart')


def clear_session_keep_cart():
    saved_cart = session.get('gift_cart')
    session.clear()
    if saved_cart:
        session['gift_cart'] = saved_cart
    session.modified = True


def cart_entries_for_creator(creator):
    cart = session.get('gift_cart') or {'creator_id': None, 'items': []}
    if cart.get('creator_id') != creator.id:
        return []
    entries = []
    changed = False
    for idx, entry in enumerate(cart.get('items', [])):
        amount_cents = max(0, int(entry.get('amount_cents', 0)))
        if entry.get('kind') == 'item':
            item = db.session.get(WishlistItem, int(entry.get('item_id') or 0))
            if not item or item.creator_id != creator.id or not item.is_active or item.is_funded:
                changed = True
                continue
            if item.gift_type == 'single':
                amount_cents = item.price_cents
            else:
                amount_cents = min(amount_cents, item.remaining_cents)
            if amount_cents < MIN_GIFT_CENTS:
                changed = True
                continue
            entries.append({'idx': idx, 'kind': 'item', 'item': item, 'title': item.title, 'type_label': item.type_label, 'amount_cents': amount_cents})
        elif entry.get('kind') == 'custom':
            if amount_cents < MIN_GIFT_CENTS:
                changed = True
                continue
            entries.append({'idx': idx, 'kind': 'custom', 'item': None, 'title': 'Custom profile donation', 'type_label': 'Custom donation', 'amount_cents': amount_cents})
    if changed:
        cart['items'] = [cart['items'][e['idx']] for e in entries]
        save_cart(cart)
    return entries


def safe_public_sender(value):
    value = (value or '').strip()[:80]
    value = re.sub(r'[^A-Za-z0-9_\.\- ]+', '', value).strip()
    return value or 'Anonymous'


def slugify_username(value):
    value = (value or '').lower().strip()
    value = re.sub(r'[^a-z0-9_\.]+', '', value)
    return value[:32]


def cents_from_price(value):
    try:
        cents = (Decimal(str(value)) * Decimal('100')).quantize(Decimal('1'), rounding=ROUND_HALF_UP)
        return max(0, int(cents))
    except Exception:
        return 0


def stock_from_form(value):
    try:
        return min(99, max(1, int(value or 1)))
    except Exception:
        return 1


def next_item_order(user_id):
    max_order = db.session.query(db.func.max(WishlistItem.display_order)).filter_by(creator_id=user_id).scalar()
    return int(max_order or 0) + 10


def item_order_query(query):
    return query.order_by(WishlistItem.display_order.asc(), WishlistItem.created_at.desc())


def redirect_after_item_save(default_endpoint='dashboard', **values):
    next_url = request.form.get('next') or request.args.get('next')
    if next_url and next_url.startswith('/') and not next_url.startswith('//'):
        return redirect(next_url)
    return redirect(url_for(default_endpoint, **values))


def single_item_count_in_cart(cart, item_id):
    count = 0
    for entry in (cart or {}).get('items', []):
        if entry.get('kind') == 'item' and int(entry.get('item_id') or 0) == int(item_id):
            count += 1
    return count


def current_user():
    uid = session.get('user_id')
    if not uid:
        return None
    return db.session.get(User, uid)


_rate_limit_buckets = {}


def client_key():
    # Use remote_addr instead of trusting spoofable headers. Your reverse proxy can be configured
    # to pass the real client IP to Flask at the server layer when deployed.
    return request.remote_addr or 'unknown'


def rate_limit_key(scope, subject=''):
    subject = (subject or '').lower().strip()[:160]
    return f'{scope}:{client_key()}:{subject}'


def is_rate_limited(scope, limit, window_seconds, subject=''):
    now = time.time()
    key = rate_limit_key(scope, subject)
    hits = [t for t in _rate_limit_buckets.get(key, []) if now - t < window_seconds]
    if len(hits) >= limit:
        _rate_limit_buckets[key] = hits
        return True
    hits.append(now)
    _rate_limit_buckets[key] = hits
    # Opportunistic cleanup so the dict does not grow forever.
    if len(_rate_limit_buckets) > 5000:
        cutoff = now - max(LOGIN_WINDOW_SECONDS, FORGOT_PASSWORD_WINDOW_SECONDS, ADMIN_WINDOW_SECONDS, OTP_WINDOW_SECONDS)
        for bucket_key in list(_rate_limit_buckets.keys())[:1000]:
            _rate_limit_buckets[bucket_key] = [t for t in _rate_limit_buckets[bucket_key] if t >= cutoff]
            if not _rate_limit_buckets[bucket_key]:
                _rate_limit_buckets.pop(bucket_key, None)
    return False


def validate_password_strength(password):
    errors = []
    if len(password or '') < PASSWORD_MIN_LENGTH:
        errors.append(f'Password must be at least {PASSWORD_MIN_LENGTH} characters.')
    if not re.search(r'[A-Z]', password or ''):
        errors.append('Password must include an uppercase letter.')
    if not re.search(r'[a-z]', password or ''):
        errors.append('Password must include a lowercase letter.')
    if not re.search(r'\d', password or ''):
        errors.append('Password must include a number.')
    if not re.search(r'[^A-Za-z0-9]', password or ''):
        errors.append('Password must include a symbol.')
    return errors


def is_user_locked(user):
    return bool(user and user.locked_until and user.locked_until > datetime.now(UTC).replace(tzinfo=None))


def record_failed_login(user):
    if not user:
        return
    now = datetime.now(UTC).replace(tzinfo=None)
    if user.last_failed_login_at and user.last_failed_login_at < now - timedelta(minutes=LOGIN_LOCKOUT_MINUTES):
        user.failed_login_count = 0
    user.failed_login_count = (user.failed_login_count or 0) + 1
    user.last_failed_login_at = now
    if user.failed_login_count >= LOGIN_MAX_ATTEMPTS:
        user.locked_until = now + timedelta(minutes=LOGIN_LOCKOUT_MINUTES)
    db.session.commit()


def clear_failed_logins(user):
    if not user:
        return
    user.failed_login_count = 0
    user.locked_until = None
    user.last_failed_login_at = None


@app.after_request
def apply_security_headers(response):
    if SECURITY_HEADERS_ENABLED:
        response.headers.setdefault('X-Content-Type-Options', 'nosniff')
        response.headers.setdefault('X-Frame-Options', 'DENY')
        response.headers.setdefault('Referrer-Policy', 'strict-origin-when-cross-origin')
        response.headers.setdefault('Permissions-Policy', 'camera=(), microphone=(), geolocation=(), payment=()')
        if APP_ENV == 'production' and BASE_URL.startswith('https://'):
            response.headers.setdefault('Strict-Transport-Security', 'max-age=31536000; includeSubDomains')
    return response


def csrf_token():
    token = session.get('_csrf_token')
    if not token:
        token = secrets.token_urlsafe(32)
        session['_csrf_token'] = token
    return token


@app.before_request
def protect_admin_paths():
    if request.path.startswith('/admin') and is_rate_limited('admin-path', ADMIN_MAX_ATTEMPTS, ADMIN_WINDOW_SECONDS):
        abort(429)


@app.before_request
def protect_post_requests():
    if request.method != 'POST' or request.endpoint == 'stripe_webhook':
        return
    sent = request.form.get('_csrf_token') or request.headers.get('X-CSRF-Token')
    if not sent or sent != session.get('_csrf_token'):
        abort(403)


@app.context_processor
def inject_globals():
    return {
        'current_user': current_user(),
        'site_name': SITE_NAME,
        'stripe_publishable_key': STRIPE_PUBLISHABLE_KEY,
        'money': money,
        'min_cashout_cents': MIN_CASHOUT_CENTS,
        'small_cashout_limit_cents': SMALL_CASHOUT_LIMIT_CENTS,
        'small_cashout_fee_cents': SMALL_CASHOUT_FEE_CENTS,
        'min_gift_cents': MIN_GIFT_CENTS,
        'supported_currencies': SUPPORTED_CURRENCIES,
        'enable_manual_stripe_account_entry': ENABLE_MANUAL_STRIPE_ACCOUNT_ENTRY,
        'display_money': display_money,
        'cart_count': cart_count(),
        'cart_total_cents': cart_total_cents(),
        'cart_creator_username': cart_creator_username(),
        'cart_url': cart_url(),
        'platform_fee_percent': PLATFORM_FEE_PERCENT,
        'stripe_connect_direct_payouts': STRIPE_CONNECT_DIRECT_PAYOUTS,
        'stripe_payout_status_label': stripe_payout_status_label,
        'email_config_status': email_config_status,
        'mongo_config_status': mongo_config_status,
        'request': request,
        'csrf_token': csrf_token,
    }


def login_required(view):
    @wraps(view)
    def wrapped(*args, **kwargs):
        user = current_user()
        if not user:
            flash('Please log in first.', 'warning')
            return redirect(url_for('login'))
        if user.is_suspended:
            clear_session_keep_cart()
            flash('This account is currently suspended. Contact support if you think this is wrong.', 'danger')
            return redirect(url_for('login'))
        if EMAIL_OTP_ENABLED and not user.email_verified:
            session['pending_signup_user_id'] = user.id
            flash('Verify your email before continuing.', 'warning')
            return redirect(url_for('verify_email'))
        user.last_seen_at = datetime.now(UTC).replace(tzinfo=None)
        db.session.commit()
        return view(*args, **kwargs)
    return wrapped


def admin_required(view):
    @wraps(view)
    def wrapped(*args, **kwargs):
        user = current_user()
        if not user or not user.is_admin or user.is_suspended:
            # Hide the admin surface from people who are not already authorized.
            abort(404)
        user.last_seen_at = datetime.now(UTC).replace(tzinfo=None)
        db.session.commit()
        return view(*args, **kwargs)
    return wrapped


IMAGE_UPLOAD_SPECS = {
    # Stored dimensions are intentionally fixed so creator images always look clean
    # and the server never keeps massive original phone photos.
    'avatar': {'size': (512, 512), 'mode': 'cover', 'quality': 88},
    'banner': {'size': (2400, 800), 'mode': 'cover', 'quality': 84},
    # Gift images are cropped once at upload time to match every public card/page.
    # 4:3 is the safest ratio for products, wishlists, and mobile cards.
    'item': {'size': (1200, 900), 'mode': 'cover', 'quality': 82},
    'generic': {'size': (1400, 1400), 'mode': 'contain', 'quality': 84},
}


def is_local_upload(url):
    return bool(url and url.startswith('/static/img/uploads/'))


def delete_local_upload(url):
    """Delete an old locally-hosted upload after a replacement is saved."""
    if not is_local_upload(url):
        return
    filename = os.path.basename(url)
    if not filename:
        return
    path = os.path.join(app.config['UPLOAD_FOLDER'], filename)
    try:
        if os.path.isfile(path):
            os.remove(path)
        mongo_delete_upload(filename)
    except OSError as exc:
        app.logger.warning('Could not remove old upload %s: %s', filename, exc)


def save_upload(file, image_kind='generic'):
    if not file or not file.filename:
        return ''

    allowed = {'png', 'jpg', 'jpeg', 'webp', 'gif'}
    ext = file.filename.rsplit('.', 1)[-1].lower() if '.' in file.filename else ''
    if ext not in allowed:
        flash('Image must be PNG, JPG, JPEG, WEBP, or GIF.', 'danger')
        return ''

    spec = IMAGE_UPLOAD_SPECS.get(image_kind, IMAGE_UPLOAD_SPECS['generic'])
    filename = secure_filename(f"{datetime.now(UTC).strftime('%Y%m%d%H%M%S')}_{secrets.token_hex(8)}_{image_kind}.webp")
    path = os.path.join(app.config['UPLOAD_FOLDER'], filename)

    if not Image or not ImageOps:
        flash('Image optimization is not available. Run pip install -r requirements.txt so Pillow is installed.', 'danger')
        return ''

    try:
        # Read the whole file once so weird browser streams do not break Pillow.
        file.stream.seek(0)
        image = Image.open(file.stream)
        image.load()
        image = ImageOps.exif_transpose(image)

        # Animated GIF/WebP uploads are flattened to the first frame. That keeps storage sane
        # and avoids broken card aspect ratios.
        if getattr(image, 'is_animated', False):
            image.seek(0)

        # Flatten transparent PNGs/WebPs onto white before WEBP export so product photos
        # do not get black boxes in some browsers.
        if image.mode in ('RGBA', 'LA') or ('transparency' in getattr(image, 'info', {})):
            rgba = image.convert('RGBA')
            canvas = Image.new('RGBA', rgba.size, (255, 255, 255, 255))
            canvas.alpha_composite(rgba)
            image = canvas.convert('RGB')
        else:
            image = image.convert('RGB')

        target_size = spec['size']
        resample = getattr(Image, 'Resampling', Image).LANCZOS

        if spec['mode'] == 'cover':
            # This is the important part for gifts: every uploaded gift image becomes
            # exactly 1200x900, centered and cropped to 4:3. No stretching later.
            image = ImageOps.fit(image, target_size, method=resample, centering=(0.5, 0.5))
        else:
            image.thumbnail(target_size, resample)

        image.save(path, 'WEBP', quality=spec['quality'], method=6, optimize=True)
        mongo_backup_upload_file(path)
        return url_for('static', filename=f'img/uploads/{filename}')
    except Exception as exc:
        app.logger.warning('Image processing failed: %s', exc)
        flash('That image could not be processed. Try a normal PNG, JPG, JPEG, or WEBP image.', 'danger')
        return ''


def cashout_fee_for(amount_cents):
    return SMALL_CASHOUT_FEE_CENTS if amount_cents < SMALL_CASHOUT_LIMIT_CENTS else 0


def email_config_status():
    missing = []
    if not RESEND_API_KEY:
        missing.append('RESEND_API_KEY')
    if not MAIL_FROM:
        missing.append('MAIL_FROM')
    return {
        'enabled': not missing,
        'missing': missing,
        'provider': 'Resend',
        'api_url': RESEND_API_URL,
        'from': MAIL_FROM,
        'from_name': MAIL_FROM_NAME,
        'reply_to': MAIL_REPLY_TO,
        'otp_enabled': EMAIL_OTP_ENABLED,
    }



def public_asset_url(url):
    if not url:
        return ''
    url = str(url).strip()
    if url.startswith(('http://', 'https://')):
        return url
    if url.startswith('/'):
        return f'{BASE_URL}{url}'
    return f'{BASE_URL}/{url.lstrip('/')}'


def gift_email_image(contribution):
    if contribution and contribution.item and contribution.item.image_url:
        return public_asset_url(contribution.item.image_url)
    creator = contribution.creator if contribution else None
    if creator and creator.banner_url:
        return public_asset_url(creator.banner_url)
    if creator and creator.avatar_url:
        return public_asset_url(creator.avatar_url)
    return public_asset_url(url_for('static', filename='img/logo-banner.png'))


def render_email_shell(title, preview, body_html, button_text=None, button_url=None, image_url=None):
    logo_url = EMAIL_LOGO_URL or f'{BASE_URL}{url_for("static", filename="img/logo-horizontal.png")}'
    hero_image = image_url or logo_url
    button = ''
    if button_text and button_url:
        button = f"""<p style='margin:26px 0 0'><a href='{escape(button_url)}' style='display:inline-block;background:linear-gradient(135deg,#9ee8ff,#36b7ff);color:#03101d;text-decoration:none;padding:13px 18px;border-radius:14px;font-weight:900;box-shadow:0 12px 28px rgba(54,183,255,.24)'>{escape(button_text)}</a></p>"""
    return f"""<!doctype html><html><head><meta name='viewport' content='width=device-width,initial-scale=1'><meta charset='utf-8'></head><body style='margin:0;background:#06111f;color:#eafaff;font-family:Inter,Arial,sans-serif'>
    <div style='display:none;max-height:0;overflow:hidden;color:transparent'>{escape(preview)}</div>
    <div style='padding:32px 16px;background:radial-gradient(circle at 20% 0,rgba(54,183,255,.22),transparent 35%),radial-gradient(circle at 85% 10%,rgba(158,232,255,.12),transparent 30%),#06111f'>
      <div style='max-width:640px;margin:0 auto;background:#0b1e35;border:1px solid #1e5b88;border-radius:26px;overflow:hidden;box-shadow:0 24px 80px rgba(0,0,0,.30)'>
        <div style='height:150px;background:linear-gradient(135deg,rgba(54,183,255,.20),rgba(22,107,255,.12));text-align:center;overflow:hidden'>
          <img src='{escape(hero_image)}' alt='{escape(SITE_NAME)}' style='width:100%;height:150px;object-fit:cover;display:block;opacity:.92'>
        </div>
        <div style='padding:20px 26px 18px;border-bottom:1px solid rgba(158,232,255,.16);background:linear-gradient(135deg,rgba(54,183,255,.13),rgba(22,107,255,.06))'>
          <img src='{escape(logo_url)}' alt='{escape(SITE_NAME)}' style='max-width:190px;height:auto;display:block;margin:0 0 8px'>
          <div style='font-weight:900;letter-spacing:.08em;font-size:11px;text-transform:uppercase;color:#9ee8ff'>Secure creator gifting</div>
        </div>
        <div style='padding:28px 26px'>
          <h1 style='margin:0 0 14px;color:#9ee8ff;font-size:28px;line-height:1.1'>{escape(title)}</h1>
          <div style='color:#d9f6ff;line-height:1.65;font-size:15px'>{body_html}</div>
          {button}
          <p style='margin:28px 0 0;color:#8fb8c9;font-size:13px;line-height:1.6'>Need help? Reply to this email or contact support@arcticsender.com.</p>
        </div>
      </div>
      <p style='max-width:640px;margin:14px auto 0;color:#6f9aad;font-size:12px;text-align:center'>This email was sent by {escape(SITE_NAME)}.</p>
    </div></body></html>"""


def send_email_safe(to_email, subject, body):
    if not to_email:
        return False

    status = email_config_status()
    if not status['enabled']:
        app.logger.info('Email skipped; missing Resend settings: %s', ', '.join(status['missing']))
        return False

    if requests is None:
        app.logger.warning('Email skipped: the requests package is missing. Run pip install -r requirements.txt.')
        return False

    payload = {
        'from': MAIL_FROM,
        'to': [to_email],
        'subject': subject,
        'html': body,
    }
    if MAIL_REPLY_TO:
        payload['reply_to'] = [MAIL_REPLY_TO]

    headers = {
        'Authorization': f'Bearer {RESEND_API_KEY}',
        'Content-Type': 'application/json',
        'Accept': 'application/json',
        # Important: Resend sits behind Cloudflare. python-urllib's default signature can trigger
        # Cloudflare 1010 on some networks/hosts, so use a normal, explicit application UA.
        'User-Agent': f'{SITE_NAME}/1.0 (+https://arcticsender.com; support@arcticsender.com)',
    }

    try:
        response = requests.post(RESEND_API_URL, headers=headers, json=payload, timeout=30)
        if 200 <= response.status_code < 300:
            app.logger.info('Email sent to %s through Resend: %s', to_email, response.text)
            return True
        app.logger.warning('Resend email failed to %s: HTTP %s %s', to_email, response.status_code, response.text)
        return False
    except requests.RequestException as exc:
        app.logger.warning('Resend email failed to %s: %s', to_email, exc)
        return False


def make_otp_code():
    return f"{secrets.randbelow(1000000):06d}"


def generate_user_otp(user, purpose):
    code = make_otp_code()
    code_hash = generate_password_hash(code)
    expires = datetime.now(UTC).replace(tzinfo=None) + timedelta(minutes=OTP_EXPIRY_MINUTES)
    if purpose == 'signup':
        user.signup_otp_hash = code_hash
        user.signup_otp_expires_at = expires
    else:
        user.login_otp_hash = code_hash
        user.login_otp_expires_at = expires
    db.session.commit()
    mongo_backup_model(user)
    return code


def verify_user_otp(user, purpose, code):
    code = (code or '').strip().replace(' ', '')
    if not re.fullmatch(r'\d{6}', code):
        return False, 'Enter the 6-digit code we emailed you.'
    if purpose == 'signup':
        code_hash = user.signup_otp_hash or ''
        expires = user.signup_otp_expires_at
    else:
        code_hash = user.login_otp_hash or ''
        expires = user.login_otp_expires_at
    if not code_hash or not expires:
        return False, 'No active code was found. Request a new code.'
    if expires < datetime.now(UTC).replace(tzinfo=None):
        return False, 'That code expired. Request a new code.'
    if not check_password_hash(code_hash, code):
        return False, 'That code is not correct.'
    if purpose == 'signup':
        user.signup_otp_hash = ''
        user.signup_otp_expires_at = None
        user.email_verified = True
    else:
        user.login_otp_hash = ''
        user.login_otp_expires_at = None
    db.session.commit()
    mongo_backup_model(user)
    return True, ''


def send_otp_email(user, code, purpose):
    if purpose == 'signup':
        title = 'Verify your ArcticSender email'
        preview = 'Use your 6-digit code to finish creating your ArcticSender account.'
        intro = 'Finish creating your ArcticSender account with this verification code.'
    else:
        title = 'Your ArcticSender login code'
        preview = 'Use your 6-digit code to sign in to ArcticSender.'
        intro = 'Use this one-time code to finish signing in.'
    body = f"""
      <p>{escape(intro)}</p>
      <div style='margin:22px 0;padding:18px 20px;border-radius:18px;background:#06111f;border:1px solid rgba(158,232,255,.22);text-align:center'>
        <div style='font-size:34px;letter-spacing:8px;font-weight:950;color:#9ee8ff'>{escape(code)}</div>
      </div>
      <p>This code expires in {OTP_EXPIRY_MINUTES} minutes. If you did not request it, you can ignore this email.</p>
    """
    return send_email_safe(user.email, title, render_email_shell(title, preview, body))


def send_password_reset_email(user, temp_password):
    body = f"""
      <p>An ArcticSender admin reset your password to help recover your account.</p>
      <p>Your temporary password is:</p>
      <div style='margin:18px 0;padding:16px;border-radius:16px;background:#06111f;border:1px solid rgba(158,232,255,.22);font-weight:950;color:#9ee8ff'>{escape(temp_password)}</div>
      <p>Sign in and change it after you regain access.</p>
    """
    return send_email_safe(user.email, f'{SITE_NAME} password reset', render_email_shell('Password reset', 'Your ArcticSender password was reset.', body, 'Login', f'{BASE_URL}{url_for("login")}'))


def send_user_password_reset_link(user, raw_token):
    reset_url = f'{BASE_URL}{url_for("reset_password", token=raw_token)}'
    body = f"""
      <p>We received a request to reset the password for your {escape(SITE_NAME)} account.</p>
      <p>Click the button below to set a new password. This link expires in {OTP_EXPIRY_MINUTES} minutes and can only be used once.</p>
      <p style='color:#b9d8e7'>If you did not request this, you can safely ignore this email. Your current password will keep working.</p>
    """
    return send_email_safe(user.email, f'Reset your {SITE_NAME} password', render_email_shell('Reset your password', 'Use this secure link to reset your ArcticSender password.', body, 'Reset password', reset_url))


def create_password_reset_token(user):
    raw_token = secrets.token_urlsafe(38)
    token = PasswordResetToken(
        user_id=user.id,
        token_hash=generate_password_hash(raw_token),
        expires_at=datetime.now(UTC).replace(tzinfo=None) + timedelta(minutes=OTP_EXPIRY_MINUTES),
    )
    db.session.add(token)
    db.session.commit()
    mongo_backup_model(token)
    return raw_token


def find_password_reset_token(raw_token):
    raw_token = (raw_token or '').strip()
    if not raw_token:
        return None
    cutoff = datetime.now(UTC).replace(tzinfo=None)
    candidates = PasswordResetToken.query.filter(PasswordResetToken.used_at.is_(None), PasswordResetToken.expires_at >= cutoff).order_by(PasswordResetToken.created_at.desc()).limit(25).all()
    for token in candidates:
        if check_password_hash(token.token_hash, raw_token):
            return token
    return None


def send_account_notice_email(user, title, message):
    body = f"<p>{escape(message)}</p>"
    return send_email_safe(user.email, title, render_email_shell(title, message, body, 'Open ArcticSender', f'{BASE_URL}{url_for("home")}'))

def send_welcome_email(user):
    body = f"""<p>Welcome to <b>{escape(SITE_NAME)}</b>, {escape(user.display_name)}.</p>
    <p>Your creator page is ready. Add a few cash gifts, connect Stripe in settings, then share your page anywhere.</p>"""
    return send_email_safe(
        user.email,
        f'Welcome to {SITE_NAME}',
        render_email_shell('Your creator page is ready', 'Your ArcticSender page is ready.', body, 'Open dashboard', f'{BASE_URL}{url_for("dashboard")}')
    )


def send_gift_emails(contribution):
    creator = contribution.creator
    item_title_raw = contribution.item.title if contribution.item else 'Custom gift'
    item_title = escape(item_title_raw)
    amount = money(contribution.amount_cents)
    is_named = contribution.supporter_name and contribution.supporter_name != 'Anonymous'
    sender = escape(contribution.supporter_name if is_named else 'Anonymous supporter')
    creator_name = escape(creator.display_name)
    image_url = gift_email_image(contribution)
    creator_body = f"""<p><b>{sender}</b> sent <b>{amount}</b> for <b>{item_title}</b>.</p>
    <div style='margin:18px 0;padding:14px;border-radius:18px;background:#06111f;border:1px solid rgba(158,232,255,.20)'>
      <div style='font-size:12px;letter-spacing:.08em;text-transform:uppercase;color:#9ee8ff;font-weight:900'>Gift</div>
      <div style='margin-top:4px;color:#eafaff;font-weight:900'>{item_title}</div>
      <div style='margin-top:4px;color:#b9d8e7'>{amount} has been added to your ArcticSender balance.</div>
    </div>
    <p>The supporter email and private receipt details stay hidden from creator views.</p>"""
    send_email_safe(
        creator.email,
        f'You received {amount} on {SITE_NAME}',
        render_email_shell('You received a gift', f'You received {amount} on {SITE_NAME}', creator_body, 'Open dashboard', f'{BASE_URL}{url_for("dashboard")}', image_url=image_url)
    )
    if contribution.supporter_email:
        sender_body = f"""<p>Your <b>{amount}</b> gift to <b>{creator_name}</b> was received.</p>
        <div style='margin:18px 0;padding:14px;border-radius:18px;background:#06111f;border:1px solid rgba(158,232,255,.20)'>
          <div style='font-size:12px;letter-spacing:.08em;text-transform:uppercase;color:#9ee8ff;font-weight:900'>Gift</div>
          <div style='margin-top:4px;color:#eafaff;font-weight:900'>{item_title}</div>
        </div>
        <p>Thanks for supporting creators through {escape(SITE_NAME)}.</p>"""
        send_email_safe(
            contribution.supporter_email,
            f'Your gift to {creator.display_name} was sent',
            render_email_shell('Gift sent successfully', f'Your gift to {creator.display_name} was sent.', sender_body, 'View creator page', f'{BASE_URL}{url_for("profile", username=creator.username)}', image_url=image_url)
        )


def mongo_uri_is_placeholder(uri):
    if not uri:
        return False
    return any(token in uri for token in MONGO_URI_PLACEHOLDERS)


def mongo_config_status():
    missing = []
    if not MONGO_BACKUP_ENABLED:
        return {'enabled': False, 'missing': [], 'db': MONGO_DB_NAME, 'disabled': True}
    if not MONGO_URI:
        missing.append('MONGO_URI')
    if MONGO_URI and mongo_uri_is_placeholder(MONGO_URI):
        missing.append('real MongoDB Atlas URI')
    if MONGO_URI and not MongoClient:
        missing.append('pymongo package')
    return {
        'enabled': bool(MONGO_URI and MongoClient and MONGO_BACKUP_ENABLED and not mongo_uri_is_placeholder(MONGO_URI)),
        'missing': missing,
        'db': MONGO_DB_NAME,
        'disabled': False,
    }


def mongo_database():
    """Return the configured Mongo database, reusing one client for speed.

    SQLite is still the live SQLAlchemy database, but Mongo is treated as the
    durable mirror on hosts where ./instance can be wiped during restarts.
    """
    global _mongo_client
    status = mongo_config_status()
    if not status['enabled']:
        return None
    try:
        if _mongo_client is None:
            mongo_kwargs = {'serverSelectionTimeoutMS': 2500}
            if certifi:
                mongo_kwargs.update({'tls': True, 'tlsCAFile': certifi.where()})
            _mongo_client = MongoClient(MONGO_URI, **mongo_kwargs)
            _mongo_client.admin.command('ping')
        return _mongo_client[MONGO_DB_NAME]
    except Exception as exc:
        app.logger.warning('MongoDB backup unavailable: %s', exc)
        _mongo_client = None
        return None


def mongo_backup_upload_file(path):
    database = mongo_database()
    if database is None or not path or not os.path.isfile(path):
        return False
    try:
        filename = os.path.basename(path)
        with open(path, 'rb') as handle:
            data = handle.read()
        database['uploaded_files'].update_one(
            {'filename': filename},
            {'$set': {
                'filename': filename,
                'content_type': 'image/webp',
                'data': data,
                'size': len(data),
                '_synced_at': datetime.now(UTC).isoformat(),
            }},
            upsert=True,
        )
        return True
    except Exception as exc:
        app.logger.warning('MongoDB upload backup failed: %s', exc)
        return False


def mongo_delete_upload(filename):
    database = mongo_database()
    if database is None or not filename:
        return False
    try:
        database['uploaded_files'].delete_one({'filename': os.path.basename(filename)})
        return True
    except Exception as exc:
        app.logger.warning('MongoDB upload delete failed: %s', exc)
        return False


def mongo_backup_uploads_all():
    database = mongo_database()
    if database is None or not os.path.isdir(app.config['UPLOAD_FOLDER']):
        return False
    saved = 0
    for name in os.listdir(app.config['UPLOAD_FOLDER']):
        path = os.path.join(app.config['UPLOAD_FOLDER'], name)
        if os.path.isfile(path) and mongo_backup_upload_file(path):
            saved += 1
    if saved:
        app.logger.info('Backed up %s uploaded image files to MongoDB.', saved)
    return bool(saved)


def mongo_restore_uploads():
    database = mongo_database()
    if database is None:
        return 0
    restored = 0
    try:
        os.makedirs(app.config['UPLOAD_FOLDER'], exist_ok=True)
        for doc in database['uploaded_files'].find({}):
            filename = secure_filename(doc.get('filename') or '')
            data = doc.get('data')
            if not filename or data is None:
                continue
            path = os.path.join(app.config['UPLOAD_FOLDER'], filename)
            if os.path.isfile(path):
                continue
            with open(path, 'wb') as handle:
                handle.write(bytes(data))
            restored += 1
    except Exception as exc:
        app.logger.warning('MongoDB upload restore failed: %s', exc)
        return 0
    if restored:
        app.logger.info('Restored %s uploaded image files from MongoDB.', restored)
    return restored


def mongo_models():
    return [User, WishlistItem, CheckoutOrder, Contribution, CashoutRequest, PasswordResetToken]


def parse_mongo_value(column, value):
    if value is None:
        return None
    try:
        python_type = column.type.python_type
    except Exception:
        python_type = None
    if isinstance(value, str) and python_type is datetime:
        try:
            return datetime.fromisoformat(value.replace('Z', '+00:00')).replace(tzinfo=None)
        except ValueError:
            return None
    return value


def serialize_model(obj):
    data = {}
    for column in obj.__table__.columns:
        value = getattr(obj, column.name)
        if isinstance(value, datetime):
            value = value.isoformat()
        data[column.name] = value
    return data


def mongo_backup_model(obj):
    database = mongo_database()
    if database is None or obj is None:
        return False
    try:
        doc = serialize_model(obj)
        doc['_sql_id'] = obj.id
        doc['_model'] = obj.__class__.__name__
        doc['_synced_at'] = datetime.now(UTC).isoformat()
        database[obj.__tablename__].update_one({'_sql_id': obj.id}, {'$set': doc}, upsert=True)
        return True
    except Exception as exc:
        app.logger.warning('MongoDB backup write failed: %s', exc)
        return False


def mongo_backup_all():
    database = mongo_database()
    if database is None:
        return False
    try:
        for model in mongo_models():
            if ASCENDING:
                database[model.__tablename__].create_index([('_sql_id', ASCENDING)], unique=True)
            for obj in model.query.all():
                doc = serialize_model(obj)
                doc['_sql_id'] = obj.id
                doc['_model'] = model.__name__
                doc['_synced_at'] = datetime.now(UTC).isoformat()
                database[model.__tablename__].update_one({'_sql_id': obj.id}, {'$set': doc}, upsert=True)
        return True
    except Exception as exc:
        app.logger.warning('MongoDB full backup failed: %s', exc)
        return False


def mongo_restore_model(model):
    database = mongo_database()
    if database is None:
        return 0
    restored = 0
    try:
        for doc in database[model.__tablename__].find({}).sort('_sql_id', 1):
            sql_id = doc.get('_sql_id') or doc.get('id')
            if not sql_id:
                continue
            obj = db.session.get(model, int(sql_id))
            if obj is None:
                obj = model()
                obj.id = int(sql_id)
                db.session.add(obj)
            for column in model.__table__.columns:
                if column.name in doc:
                    setattr(obj, column.name, parse_mongo_value(column, doc[column.name]))
            restored += 1
        db.session.commit()
    except Exception as exc:
        db.session.rollback()
        app.logger.warning('MongoDB restore failed for %s: %s', model.__name__, exc)
        return 0
    return restored


def mongo_restore_all_if_empty():
    """Rebuild local SQLite from Mongo after a deploy/restart wiped instance data."""
    if not mongo_config_status()['enabled']:
        return False
    try:
        has_local_data = any(model.query.first() for model in mongo_models())
    except Exception as exc:
        app.logger.warning('Could not check local database before Mongo restore: %s', exc)
        return False
    if has_local_data:
        return False
    total = 0
    # Parents first, children after, so foreign keys/relationships stay sane.
    for model in mongo_models():
        total += mongo_restore_model(model)
    if total:
        app.logger.info('Restored %s records from MongoDB into local SQLite.', total)
    return bool(total)

def credit_contribution(contribution, commit=True, send_email=True):
    if contribution.status == 'paid':
        return
    contribution.status = 'paid'
    contribution.paid_at = datetime.now(UTC).replace(tzinfo=None)
    creator = contribution.creator
    creator.lifetime_earned_cents += contribution.amount_cents

    # If Stripe Connect destination charges are enabled, Stripe sends the creator
    # payout through their connected Express account automatically. Do not also
    # add the money to the internal cashout balance, or the creator could be paid twice.
    if not (STRIPE_CONNECT_DIRECT_PAYOUTS and contribution.stripe_session_id and creator.stripe_account_id):
        creator.balance_cents += contribution.amount_cents

    if contribution.item:
        if contribution.item.gift_type == 'single':
            max_funded = contribution.item.price_cents * contribution.item.stock_limit
            contribution.item.funded_cents = min(max_funded, contribution.item.funded_cents + contribution.amount_cents)
        else:
            contribution.item.funded_cents = min(contribution.item.price_cents, contribution.item.funded_cents + contribution.amount_cents)
    if commit:
        db.session.commit()
    mongo_backup_model(contribution)
    mongo_backup_model(creator)
    if contribution.item:
        mongo_backup_model(contribution.item)
    if send_email:
        send_gift_emails(contribution)


def credit_order(order):
    if order.status == 'paid':
        return
    for contribution in order.contributions:
        credit_contribution(contribution, commit=False, send_email=False)
    order.status = 'paid'
    order.paid_at = datetime.now(UTC).replace(tzinfo=None)
    db.session.commit()
    mongo_backup_model(order)
    for contribution in order.contributions:
        mongo_backup_model(contribution)
        send_gift_emails(contribution)
    mongo_backup_model(order.creator)


def create_checkout_session(contribution, title, success_url, cancel_url):
    if not STRIPE_SECRET_KEY or not stripe:
        return None
    creator = contribution.creator
    charged_cents = contribution.charged_amount_cents or contribution.amount_cents
    payment_intent_data = {
        'metadata': {
            'contribution_id': str(contribution.id),
            'creator_id': str(contribution.creator_id),
            'support_type': contribution.support_type,
            'item_id': str(contribution.item_id or ''),
        }
    }
    if STRIPE_CONNECT_DIRECT_PAYOUTS and creator.stripe_account_id:
        platform_fee_cents = platform_fee_for_cents(charged_cents)
        contribution.platform_fee_cents = platform_fee_cents
        payment_intent_data.update({
            'application_fee_amount': platform_fee_cents,
            'transfer_data': {'destination': creator.stripe_account_id},
        })

    session_obj = stripe.checkout.Session.create(
        mode='payment',
        payment_method_types=['card'],
        customer_email=contribution.supporter_email or None,
        line_items=[{
            'quantity': 1,
            'price_data': {
                'currency': contribution.currency or 'usd',
                'unit_amount': charged_cents,
                'product_data': {'name': title, 'description': f'{SITE_NAME} cash gift to @{creator.username}'[:500]},
            },
        }],
        payment_intent_data=payment_intent_data,
        metadata={
            'contribution_id': str(contribution.id),
            'creator_id': str(contribution.creator_id),
            'support_type': contribution.support_type,
            'item_id': str(contribution.item_id or ''),
        },
        success_url=success_url,
        cancel_url=cancel_url,
    )
    contribution.stripe_session_id = session_obj.id
    db.session.commit()
    return session_obj


def create_cart_checkout_session(order, entries, success_url, cancel_url):
    if not STRIPE_SECRET_KEY or not stripe:
        return None
    line_items = []
    for entry in entries:
        charged_cents = convert_usd_to_currency_cents(entry['amount_cents'], order.currency)
        line_items.append({
            'quantity': 1,
            'price_data': {
                'currency': order.currency,
                'unit_amount': charged_cents,
                'product_data': {
                    'name': entry['title'][:120],
                    'description': f'{SITE_NAME} cash gift to @{order.creator.username}'[:500],
                },
            },
        })

    payment_intent_data = {'metadata': {'order_id': str(order.id), 'creator_id': str(order.creator_id)}}
    if STRIPE_CONNECT_DIRECT_PAYOUTS and order.creator.stripe_account_id:
        order.platform_fee_cents = platform_fee_for_cents(order.charged_amount_cents)
        payment_intent_data.update({
            'application_fee_amount': order.platform_fee_cents,
            'transfer_data': {'destination': order.creator.stripe_account_id},
        })

    session_obj = stripe.checkout.Session.create(
        mode='payment',
        payment_method_types=['card'],
        customer_email=order.supporter_email or None,
        line_items=line_items,
        payment_intent_data=payment_intent_data,
        metadata={'order_id': str(order.id), 'creator_id': str(order.creator_id)},
        success_url=success_url,
        cancel_url=cancel_url,
    )
    order.stripe_session_id = session_obj.id
    for contribution in order.contributions:
        contribution.stripe_session_id = session_obj.id
        contribution.platform_fee_cents = platform_fee_for_cents(contribution.charged_amount_cents or contribution.amount_cents)
    db.session.commit()
    return session_obj


@app.route('/healthz')
def healthz():
    return jsonify({'ok': True, 'site': SITE_NAME, 'time': datetime.now(UTC).isoformat()})




@app.route('/robots.txt')
def robots_txt():
    sitemap_url = f"{BASE_URL}{url_for('sitemap_xml')}"
    body = f"User-agent: *\nAllow: /\nSitemap: {sitemap_url}\n"
    return Response(body, mimetype='text/plain')


@app.route('/sitemap.xml')
def sitemap_xml():
    urls = [
        (f"{BASE_URL}{url_for('home')}", 'daily', '1.0'),
        (f"{BASE_URL}{url_for('register')}", 'weekly', '0.8'),
        (f"{BASE_URL}{url_for('login')}", 'monthly', '0.4'),
        (f"{BASE_URL}{url_for('faq')}", 'weekly', '0.7'),
    ]
    for user in User.query.filter_by(is_suspended=False).order_by(User.created_at.desc()).limit(500).all():
        urls.append((f"{BASE_URL}{url_for('profile', username=user.username)}", 'daily', '0.9'))
        urls.append((f"{BASE_URL}{url_for('public_leaderboard', username=user.username)}", 'daily', '0.7'))
        urls.append((f"{BASE_URL}{url_for('donate', username=user.username)}", 'weekly', '0.7'))
    for item in item_order_query(WishlistItem.query.filter_by(is_active=True)).limit(1000).all():
        urls.append((f"{BASE_URL}{url_for('support_item', item_id=item.id)}", 'daily', '0.8'))
    rows = []
    for loc, changefreq, priority in urls:
        rows.append(f"  <url><loc>{escape(loc)}</loc><changefreq>{changefreq}</changefreq><priority>{priority}</priority></url>")
    xml = "<?xml version=\"1.0\" encoding=\"UTF-8\"?>\n<urlset xmlns=\"http://www.sitemaps.org/schemas/sitemap/0.9\">\n" + "\n".join(rows) + "\n</urlset>\n"
    return Response(xml, mimetype='application/xml')


@app.route('/')
def home():
    return render_template('home.html')


@app.route('/register', methods=['GET', 'POST'])
def register():
    if request.method == 'POST':
        username = slugify_username(request.form.get('username', ''))
        display_name = request.form.get('display_name', '').strip()[:80]
        email = request.form.get('email', '').lower().strip()
        password = request.form.get('password', '')
        if is_rate_limited('register', 8, 900, email):
            flash('Too many signup attempts. Try again in a few minutes.', 'danger')
            return redirect(url_for('register'))
        password_errors = validate_password_strength(password)
        if not username or not display_name or not email or password_errors:
            flash('Fill everything out. ' + (' '.join(password_errors) if password_errors else 'Check your username, name, and email.'), 'danger')
            return redirect(url_for('register'))
        if User.query.filter((User.username == username) | (User.email == email)).first():
            flash('Username or email already exists.', 'danger')
            return redirect(url_for('register'))
        user = User(username=username, display_name=display_name, email=email, password_hash=generate_password_hash(password))
        if AUTO_ADMIN_FIRST_USER and User.query.count() == 0:
            user.is_admin = True
            user.email_verified = True
        elif not EMAIL_OTP_ENABLED:
            user.email_verified = True
        db.session.add(user)
        db.session.commit()
        mongo_backup_model(user)
        if EMAIL_OTP_ENABLED and not user.email_verified:
            code = generate_user_otp(user, 'signup')
            sent = send_otp_email(user, code, 'signup')
            session['pending_signup_user_id'] = user.id
            if not sent and MAIL_REQUIRED_FOR_AUTH:
                flash('Account created, but the verification email could not send. Check Resend settings or contact support.', 'danger')
            else:
                flash('We sent a 6-digit verification code to your email.', 'success')
            return redirect(url_for('verify_email'))
        send_welcome_email(user)
        clear_session_keep_cart()
        session.permanent = True
        session['user_id'] = user.id
        user.last_login_at = datetime.now(UTC).replace(tzinfo=None)
        db.session.commit()
        flash('Your ArcticSender creator page is ready.', 'success')
        return redirect(url_for('dashboard'))
    return render_template('register.html')


@app.route('/verify-email', methods=['GET', 'POST'])
def verify_email():
    user = db.session.get(User, session.get('pending_signup_user_id') or 0)
    if not user:
        flash('Start signup again to verify your email.', 'warning')
        return redirect(url_for('register'))
    if request.method == 'POST':
        if is_rate_limited('otp-signup', OTP_MAX_ATTEMPTS, OTP_WINDOW_SECONDS, str(user.id)):
            flash('Too many code attempts. Request a new code or try again later.', 'danger')
            return redirect(url_for('verify_email'))
        ok, error = verify_user_otp(user, 'signup', request.form.get('code'))
        if not ok:
            flash(error, 'danger')
            return redirect(url_for('verify_email'))
        clear_session_keep_cart()
        session.permanent = True
        session['user_id'] = user.id
        user.last_login_at = datetime.now(UTC).replace(tzinfo=None)
        db.session.commit()
        mongo_backup_model(user)
        send_welcome_email(user)
        flash('Email verified. Your creator page is ready.', 'success')
        return redirect(url_for('dashboard'))
    return render_template('verify_otp.html', purpose='signup', email=user.email, title='Verify your email')


@app.route('/login', methods=['GET', 'POST'])
def login():
    if request.method == 'POST':
        email = request.form.get('email', '').lower().strip()
        password = request.form.get('password', '')
        if is_rate_limited('login', LOGIN_MAX_ATTEMPTS, LOGIN_WINDOW_SECONDS, email):
            flash('Too many login attempts. Wait a few minutes and try again.', 'danger')
            return redirect(url_for('login'))
        user = User.query.filter_by(email=email).first()
        if is_user_locked(user):
            flash('This account is temporarily locked after too many failed attempts. Try again later or reset your password.', 'danger')
            return redirect(url_for('login'))
        if not user or not check_password_hash(user.password_hash, password):
            record_failed_login(user)
            flash('Invalid login.', 'danger')
            return redirect(url_for('login'))
        clear_failed_logins(user)
        if user.is_suspended:
            flash('This account is suspended. Contact support@arcticsender.com for help.', 'danger')
            return redirect(url_for('login'))
        if EMAIL_OTP_ENABLED:
            purpose = 'login' if user.email_verified else 'signup'
            code = generate_user_otp(user, purpose)
            sent = send_otp_email(user, code, purpose)
            if purpose == 'signup':
                session['pending_signup_user_id'] = user.id
                flash('Verify your email before signing in. We sent you a new code.', 'warning')
                return redirect(url_for('verify_email'))
            session['pending_login_user_id'] = user.id
            if not sent and MAIL_REQUIRED_FOR_AUTH:
                flash('Login code could not be sent. Check Resend settings or contact support.', 'danger')
                return redirect(url_for('login'))
            flash('We sent a 6-digit login code to your email.', 'success')
            return redirect(url_for('verify_login'))
        session['user_id'] = user.id
        user.last_login_at = datetime.now(UTC).replace(tzinfo=None)
        db.session.commit()
        mongo_backup_model(user)
        flash('Welcome back.', 'success')
        return redirect(url_for('dashboard'))
    return render_template('login.html')


@app.route('/forgot-password', methods=['GET', 'POST'])
def forgot_password():
    if request.method == 'POST':
        email = request.form.get('email', '').lower().strip()
        if is_rate_limited('forgot-password', FORGOT_PASSWORD_MAX_ATTEMPTS, FORGOT_PASSWORD_WINDOW_SECONDS, email):
            flash('Too many reset requests. Wait a while before trying again.', 'danger')
            return redirect(url_for('forgot_password'))
        user = User.query.filter_by(email=email).first() if email else None
        if user and not user.is_suspended:
            token = create_password_reset_token(user)
            sent = send_user_password_reset_link(user, token)
            if not sent and MAIL_REQUIRED_FOR_AUTH:
                app.logger.warning('Password reset email failed for %s', email)
        flash('If that email belongs to an account, a password reset link has been sent.', 'success')
        return redirect(url_for('login'))
    return render_template('forgot_password.html')


@app.route('/reset-password/<token>', methods=['GET', 'POST'])
def reset_password(token):
    reset_token = find_password_reset_token(token)
    if not reset_token:
        flash('That reset link is invalid or expired. Request a new one.', 'danger')
        return redirect(url_for('forgot_password'))
    user = reset_token.user
    if user.is_suspended:
        flash('This account is suspended. Contact support@arcticsender.com for help.', 'danger')
        return redirect(url_for('login'))
    if request.method == 'POST':
        password = request.form.get('password', '')
        confirm = request.form.get('confirm_password', '')
        password_errors = validate_password_strength(password)
        if password_errors:
            flash(' '.join(password_errors), 'danger')
            return redirect(url_for('reset_password', token=token))
        if password != confirm:
            flash('Passwords do not match.', 'danger')
            return redirect(url_for('reset_password', token=token))
        user.password_hash = generate_password_hash(password)
        user.password_changed_at = datetime.now(UTC).replace(tzinfo=None)
        user.email_verified = True
        user.login_otp_hash = ''
        user.login_otp_expires_at = None
        clear_failed_logins(user)
        reset_token.used_at = datetime.now(UTC).replace(tzinfo=None)
        db.session.commit()
        mongo_backup_model(user)
        mongo_backup_model(reset_token)
        send_account_notice_email(user, f'{SITE_NAME} password changed', 'Your password was changed successfully. If this was not you, reply to this email immediately.')
        flash('Password updated. You can sign in now.', 'success')
        return redirect(url_for('login'))
    return render_template('reset_password.html')


@app.route('/verify-login', methods=['GET', 'POST'])
def verify_login():
    user = db.session.get(User, session.get('pending_login_user_id') or 0)
    if not user:
        flash('Login again to request a new code.', 'warning')
        return redirect(url_for('login'))
    if request.method == 'POST':
        if is_rate_limited('otp-login', OTP_MAX_ATTEMPTS, OTP_WINDOW_SECONDS, str(user.id)):
            flash('Too many code attempts. Login again to request a fresh code.', 'danger')
            return redirect(url_for('login'))
        ok, error = verify_user_otp(user, 'login', request.form.get('code'))
        if not ok:
            flash(error, 'danger')
            return redirect(url_for('verify_login'))
        clear_session_keep_cart()
        session.permanent = True
        session['user_id'] = user.id
        user.last_login_at = datetime.now(UTC).replace(tzinfo=None)
        db.session.commit()
        mongo_backup_model(user)
        flash('Welcome back.', 'success')
        return redirect(url_for('dashboard'))
    return render_template('verify_otp.html', purpose='login', email=user.email, title='Enter your login code')


@app.route('/auth/resend-otp/<purpose>', methods=['POST'])
def resend_otp(purpose):
    if purpose not in {'signup', 'login'}:
        abort(404)
    if is_rate_limited('resend-otp', 3, 600, purpose):
        flash('Too many resend requests. Wait a few minutes before trying again.', 'danger')
        return redirect(url_for('login'))
    session_key = 'pending_signup_user_id' if purpose == 'signup' else 'pending_login_user_id'
    user = db.session.get(User, session.get(session_key) or 0)
    if not user:
        flash('No pending verification was found.', 'warning')
        return redirect(url_for('login'))
    code = generate_user_otp(user, purpose)
    if send_otp_email(user, code, purpose):
        flash('A new code was sent.', 'success')
    else:
        flash('The email could not be sent. Check Resend settings or contact support.', 'danger')
    return redirect(url_for('verify_email' if purpose == 'signup' else 'verify_login'))


@app.route('/logout')
def logout():
    clear_session_keep_cart()
    flash('Logged out.', 'info')
    return redirect(url_for('home'))


@app.route('/dashboard')
@login_required
def dashboard():
    user = current_user()
    items = item_order_query(WishlistItem.query.filter_by(creator_id=user.id)).all()
    contributions = Contribution.query.filter_by(creator_id=user.id).order_by(Contribution.created_at.desc()).limit(30).all()
    cashouts = CashoutRequest.query.filter_by(creator_id=user.id).order_by(CashoutRequest.created_at.desc()).limit(10).all()
    return render_template('dashboard.html', items=items, contributions=contributions, cashouts=cashouts)


@app.route('/profile-settings', methods=['GET', 'POST'])
@login_required
def profile_settings():
    user = current_user()
    if request.method == 'POST':
        username = slugify_username(request.form.get('username', user.username))
        if username != user.username and User.query.filter_by(username=username).first():
            flash('That username is taken.', 'danger')
            return redirect(url_for('profile_settings'))
        user.username = username
        user.display_name = request.form.get('display_name', user.display_name).strip()[:80]
        user.bio = request.form.get('bio', '').strip()[:700]
        user.socials = request.form.get('socials', '').strip()[:500]
        avatar = save_upload(request.files.get('avatar'), 'avatar')
        banner = save_upload(request.files.get('banner'), 'banner')
        if avatar:
            delete_local_upload(user.avatar_url)
            user.avatar_url = avatar
        if banner:
            delete_local_upload(user.banner_url)
            user.banner_url = banner
        db.session.commit()
        mongo_backup_model(user)
        flash('Profile updated.', 'success')
        return redirect(url_for('profile', username=user.username))
    return render_template('profile_settings.html')


@app.route('/settings', methods=['GET', 'POST'])
@login_required
def settings():
    user = current_user()
    if request.method == 'POST':
        if ENABLE_MANUAL_STRIPE_ACCOUNT_ENTRY:
            stripe_account_id = request.form.get('stripe_account_id', '').strip()[:100]
            if stripe_account_id and not stripe_account_id.startswith('acct_'):
                flash('Stripe connected account ID must start with acct_.', 'danger')
                return redirect(url_for('settings'))
            user.stripe_account_id = stripe_account_id
            db.session.commit()
            mongo_backup_model(user)
            flash('Payout settings updated.', 'success')
        return redirect(url_for('settings'))
    stripe_status = stripe_account_details(user)
    stripe_config = stripe_config_status()
    return render_template('settings.html', stripe_status=stripe_status, stripe_config=stripe_config)


@app.route('/account/close', methods=['POST'])
@login_required
def close_account():
    user = current_user()
    if request.form.get('confirm', '').strip().upper() != 'CLOSE':
        flash('Type CLOSE to confirm account closure.', 'danger')
        return redirect(url_for('settings'))
    if user.balance_cents > 0 or user.pending_cashout_cents > 0:
        flash('Cash out your balance before closing your account.', 'warning')
        return redirect(url_for('settings'))
    user.is_suspended = True
    db.session.commit()
    mongo_backup_model(user)
    clear_session_keep_cart()
    flash('Your account has been closed.', 'info')
    return redirect(url_for('home'))


@app.route('/wishlist/new', methods=['GET', 'POST'])
@login_required
def new_item():
    if request.method == 'POST':
        title = request.form.get('title', '').strip()[:120]
        price_cents = cents_from_price(request.form.get('price', '0'))
        gift_type = request.form.get('gift_type', 'single')
        if gift_type not in {'single', 'goal'}:
            gift_type = 'single'
        if not title or price_cents < MIN_GIFT_CENTS:
            flash('Gift title and minimum $1.00 USD cash amount are required.', 'danger')
            return redirect(url_for('new_item'))
        image_url = request.form.get('image_url', '').strip()[:300]
        if image_url and not image_url.startswith(('http://', 'https://', '/static/')):
            flash('Image URL must start with http://, https://, or /static/.', 'danger')
            return redirect(url_for('new_item'))
        image = save_upload(request.files.get('image'), 'item') or image_url
        item = WishlistItem(
            creator_id=current_user().id,
            title=title,
            description=request.form.get('description', '').strip()[:1200],
            image_url=image,
            product_url=request.form.get('product_url', '').strip()[:500],
            price_cents=price_cents,
            gift_type=gift_type,
            stock_count=stock_from_form(request.form.get('stock_count')) if gift_type == 'single' else 1,
            display_order=next_item_order(current_user().id),
            priority=request.form.get('priority', 'normal')
        )
        db.session.add(item)
        db.session.commit()
        mongo_backup_model(item)
        flash('Cash gift added.', 'success')
        return redirect_after_item_save('profile', username=current_user().username)
    return render_template('item_form.html', item=None)


@app.route('/wishlist/<int:item_id>/edit', methods=['GET', 'POST'])
@login_required
def edit_item(item_id):
    item = db.session.get(WishlistItem, item_id) or abort(404)
    if item.creator_id != current_user().id and not current_user().is_admin:
        abort(403)
    if request.method == 'POST':
        item.title = request.form.get('title', item.title).strip()[:120]
        item.description = request.form.get('description', '').strip()[:1200]
        item.product_url = request.form.get('product_url', '').strip()[:500]
        new_price_cents = cents_from_price(request.form.get('price', item.price))
        if new_price_cents < MIN_GIFT_CENTS:
            flash('Minimum cash gift amount is $1.00 USD.', 'danger')
            return redirect(url_for('edit_item', item_id=item.id))
        item.price_cents = new_price_cents
        item.gift_type = request.form.get('gift_type', item.gift_type) if request.form.get('gift_type') in {'single', 'goal'} else item.gift_type
        item.stock_count = stock_from_form(request.form.get('stock_count')) if item.gift_type == 'single' else 1
        item.priority = request.form.get('priority', item.priority)
        if request.form.get('display_order') not in (None, ''):
            try:
                item.display_order = int(request.form.get('display_order'))
            except Exception:
                pass
        item.is_active = bool(request.form.get('is_active'))
        image_url = request.form.get('image_url', '').strip()[:300]
        if image_url and not image_url.startswith(('http://', 'https://', '/static/')):
            flash('Image URL must start with http://, https://, or /static/.', 'danger')
            return redirect(url_for('edit_item', item_id=item.id))
        remove_image = bool(request.form.get('remove_image'))
        uploaded_image = save_upload(request.files.get('image'), 'item')
        image = uploaded_image or image_url
        if remove_image and not image:
            delete_local_upload(item.image_url)
            item.image_url = ''
        elif image:
            if image != item.image_url:
                delete_local_upload(item.image_url)
            item.image_url = image
        db.session.commit()
        mongo_backup_model(item)
        flash('Cash gift updated.', 'success')
        return redirect_after_item_save('profile', username=current_user().username)
    return render_template('item_form.html', item=item)


@app.route('/wishlist/<int:item_id>/move', methods=['POST'])
@login_required
def move_item(item_id):
    item = db.session.get(WishlistItem, item_id) or abort(404)
    user = current_user()
    if item.creator_id != user.id and not user.is_admin:
        abort(403)
    direction = request.form.get('direction', '')
    siblings = item_order_query(WishlistItem.query.filter_by(creator_id=item.creator_id)).all()
    index = next((i for i, sibling in enumerate(siblings) if sibling.id == item.id), None)
    if index is None:
        return redirect_after_item_save('profile', username=item.creator.username)
    swap_index = index - 1 if direction == 'up' else index + 1 if direction == 'down' else None
    if swap_index is not None and 0 <= swap_index < len(siblings):
        other = siblings[swap_index]
        item.display_order, other.display_order = other.display_order, item.display_order
        db.session.commit()
        mongo_backup_model(item)
        mongo_backup_model(other)
        flash('Gift order updated.', 'success')
    return redirect_after_item_save('profile', username=item.creator.username)


@app.route('/wishlist/<int:item_id>/delete', methods=['POST'])
@login_required
def delete_item(item_id):
    item = db.session.get(WishlistItem, item_id) or abort(404)
    if item.creator_id != current_user().id and not current_user().is_admin:
        abort(403)
    db.session.delete(item)
    db.session.commit()
    flash('Cash gift removed.', 'info')
    return redirect_after_item_save('profile', username=current_user().username)


def creator_leaderboard_rows(user, limit=25):
    paid_gifts = Contribution.query.filter(
        Contribution.creator_id == user.id,
        Contribution.status == 'paid',
        Contribution.supporter_name.isnot(None),
        Contribution.supporter_name != '',
        Contribution.supporter_name != 'Anonymous',
    ).order_by(Contribution.amount_cents.desc()).all()
    leaderboard_map = {}
    for gift in paid_gifts:
        public_name = safe_public_sender(gift.supporter_name)
        if public_name == 'Anonymous':
            continue
        key = public_name.lower()
        row = leaderboard_map.setdefault(key, {'name': public_name, 'amount_cents': 0, 'count': 0, 'last_sent_at': gift.paid_at or gift.created_at})
        row['amount_cents'] += gift.amount_cents
        row['count'] += 1
        row['last_sent_at'] = max(row['last_sent_at'], gift.paid_at or gift.created_at)
    return sorted(leaderboard_map.values(), key=lambda r: r['amount_cents'], reverse=True)[:limit]


def creator_recent_sends(user, limit=30):
    return Contribution.query.filter_by(creator_id=user.id, status='paid').order_by(Contribution.paid_at.desc().nullslast(), Contribution.created_at.desc()).limit(limit).all()



@app.route('/faq')
def faq():
    return render_template('faq.html')

@app.route('/@<username>')
def profile(username):
    user = User.query.filter_by(username=username).first_or_404()
    viewer = current_user()
    owns_page = bool(viewer and (viewer.id == user.id or viewer.is_admin))
    item_query = WishlistItem.query.filter_by(creator_id=user.id) if owns_page else WishlistItem.query.filter_by(creator_id=user.id, is_active=True)
    items = item_order_query(item_query).all()
    recent_sends = creator_recent_sends(user, 4)
    named_count = len(creator_leaderboard_rows(user, 1000))
    return render_template('profile.html', creator=user, items=items, recent_sends=recent_sends, named_count=named_count)


@app.route('/@<username>/leaderboard')
def public_leaderboard(username):
    user = User.query.filter_by(username=username).first_or_404()
    leaderboard = creator_leaderboard_rows(user, 50)
    recent_sends = creator_recent_sends(user, 40)
    return render_template('leaderboard.html', creator=user, leaderboard=leaderboard, recent_sends=recent_sends)


@app.route('/@<username>/donate', methods=['GET', 'POST'])
def donate(username):
    creator = User.query.filter_by(username=username).first_or_404()
    if request.method == 'POST':
        amount_cents = cents_from_price(request.form.get('amount', '0'))
        if amount_cents < MIN_GIFT_CENTS:
            flash('Minimum custom donation is $1.00 USD.', 'danger')
            return redirect(url_for('donate', username=creator.username))
        cart = get_cart()
        if cart.get('creator_id') and cart.get('creator_id') != creator.id:
            clear_cart()
            cart = get_cart()
            flash('Your cart was reset because gifts can only be checked out for one creator at a time.', 'info')
        cart['creator_id'] = creator.id
        cart.setdefault('items', []).append({'kind': 'custom', 'amount_cents': amount_cents})
        save_cart(cart)
        flash('Custom donation added to cart.', 'success')
        return redirect(url_for('cart', username=creator.username))
    return render_template('donate.html', creator=creator)


@app.route('/support/<int:item_id>', methods=['GET', 'POST'])
def support_item(item_id):
    item = db.session.get(WishlistItem, item_id) or abort(404)
    if not item.is_active:
        abort(404)
    if item.is_funded:
        flash('This cash gift is already fully funded.', 'info')
        return redirect(url_for('profile', username=item.creator.username))
    if request.method == 'POST':
        if item.gift_type == 'single':
            amount_cents = item.price_cents
        else:
            amount_cents = cents_from_price(request.form.get('amount', item.remaining_cents / 100))
            amount_cents = min(max(amount_cents, MIN_GIFT_CENTS), item.remaining_cents)
        if amount_cents < MIN_GIFT_CENTS:
            flash('Minimum gift amount is $1.00 USD.', 'danger')
            return redirect(url_for('support_item', item_id=item.id))
        cart = get_cart()
        if cart.get('creator_id') and cart.get('creator_id') != item.creator_id:
            clear_cart()
            cart = get_cart()
            flash('Your cart was reset because gifts can only be checked out for one creator at a time.', 'info')
        if item.gift_type == 'single' and single_item_count_in_cart(cart, item.id) >= item.remaining_stock:
            flash('No more stock is available for this cash gift.', 'warning')
            return redirect(url_for('profile', username=item.creator.username))
        cart['creator_id'] = item.creator_id
        cart.setdefault('items', []).append({'kind': 'item', 'item_id': item.id, 'amount_cents': amount_cents})
        save_cart(cart)
        flash('Gift added to cart.', 'success')
        return redirect(url_for('cart', username=item.creator.username))
    return render_template('support.html', item=item)


@app.route('/cart')
def global_cart():
    username = cart_creator_username()
    if username:
        return redirect(url_for('cart', username=username))
    return render_template('global_cart.html')


@app.route('/cart/<username>')
def cart(username):
    creator = User.query.filter_by(username=username).first_or_404()
    entries = cart_entries_for_creator(creator)
    return render_template('cart.html', creator=creator, entries=entries, total_cents=sum(e['amount_cents'] for e in entries))


@app.route('/checkout/<username>', methods=['GET', 'POST'])
def checkout(username):
    creator = User.query.filter_by(username=username).first_or_404()
    entries = cart_entries_for_creator(creator)
    total_cents = sum(e['amount_cents'] for e in entries)
    if not entries:
        flash('Your cart is empty. Add a gift before checkout.', 'warning')
        return redirect(url_for('cart', username=creator.username))
    if request.method == 'POST':
        public_name = safe_public_sender(request.form.get('supporter_name', ''))
        supporter_email = request.form.get('supporter_email', '').strip()[:140]
        message = request.form.get('message', '').strip()[:500]
        currency = normalize_currency(request.form.get('currency', 'usd'))
        if total_cents < MIN_GIFT_CENTS:
            flash('Minimum gift amount is $1.00 USD.', 'danger')
            return redirect(url_for('cart', username=creator.username))
        if STRIPE_SECRET_KEY and stripe and STRIPE_CONNECT_DIRECT_PAYOUTS:
            sync_stripe_account_status(creator)
            if not creator_stripe_ready(creator):
                flash('This creator has not finished Stripe payout setup yet, so checkout is not available.', 'danger')
                return redirect(url_for('profile', username=creator.username))
        requested_single_counts = {}
        for entry in entries:
            item = entry.get('item')
            if item and item.gift_type == 'single':
                requested_single_counts[item.id] = requested_single_counts.get(item.id, 0) + 1
        for item_id, requested_count in requested_single_counts.items():
            item = db.session.get(WishlistItem, item_id)
            if not item or item.remaining_stock < requested_count:
                flash('One of the single purchase gifts just sold out. Please review your cart.', 'warning')
                return redirect(url_for('cart', username=creator.username))
        charged_total = convert_usd_to_currency_cents(total_cents, currency)
        order = CheckoutOrder(
            token=secrets.token_urlsafe(18),
            creator_id=creator.id,
            supporter_name=public_name,
            supporter_email=supporter_email,
            message=message,
            total_amount_cents=total_cents,
            charged_amount_cents=charged_total,
            platform_fee_cents=platform_fee_for_cents(charged_total),
            currency=currency,
        )
        db.session.add(order)
        db.session.flush()
        for e in entries:
            charged_amount = convert_usd_to_currency_cents(e['amount_cents'], currency)
            contribution = Contribution(
                creator_id=creator.id,
                item_id=e['item'].id if e.get('item') else None,
                order_id=order.id,
                support_type=e['item'].gift_type if e.get('item') else 'custom',
                supporter_name=public_name,
                supporter_email=supporter_email,
                message=message,
                amount_cents=e['amount_cents'],
                currency=currency,
                charged_amount_cents=charged_amount,
                platform_fee_cents=platform_fee_for_cents(charged_amount),
            )
            db.session.add(contribution)
        db.session.commit()
        mongo_backup_model(order)
        for contribution in order.contributions:
            mongo_backup_model(contribution)
        if STRIPE_SECRET_KEY and stripe:
            checkout_session = create_cart_checkout_session(
                order,
                entries,
                f'{BASE_URL}{url_for("cart_success", token=order.token)}',
                f'{BASE_URL}{url_for("checkout", username=creator.username)}'
            )
            clear_cart()
            return redirect(checkout_session.url, code=303)
        if REQUIRE_STRIPE_PAYMENTS:
            for contribution in list(order.contributions):
                db.session.delete(contribution)
            db.session.delete(order)
            db.session.commit()
            flash('Payments are temporarily unavailable. Please try again later.', 'danger')
            return redirect(url_for('checkout', username=creator.username))
        credit_order(order)
        clear_cart()
        flash('Demo cart payment complete. Add Stripe keys before going live.', 'success')
        return redirect(url_for('cart_success', token=order.token))
    return render_template('checkout.html', creator=creator, entries=entries, total_cents=total_cents)


@app.route('/cart/<username>/remove/<int:index>', methods=['POST'])
def cart_remove(username, index):
    creator = User.query.filter_by(username=username).first_or_404()
    cart_data = get_cart()
    if cart_data.get('creator_id') == creator.id and 0 <= index < len(cart_data.get('items', [])):
        cart_data['items'].pop(index)
        save_cart(cart_data)
        flash('Removed from cart.', 'info')
    return redirect(url_for('cart', username=creator.username))


@app.route('/cart/<username>/clear', methods=['POST'])
def cart_clear(username):
    creator = User.query.filter_by(username=username).first_or_404()
    clear_cart()
    flash('Cart cleared.', 'info')
    return redirect(url_for('profile', username=creator.username))


@app.route('/payment/success/<int:contribution_id>')
def payment_success(contribution_id):
    contribution = db.session.get(Contribution, contribution_id) or abort(404)
    if contribution.order:
        return redirect(url_for('cart_success', token=contribution.order.token))
    if not STRIPE_SECRET_KEY:
        credit_contribution(contribution)
    return render_template('success.html', contribution=contribution, order=None, contributions=[contribution])


@app.route('/cart/success/<token>')
def cart_success(token):
    order = CheckoutOrder.query.filter_by(token=token).first_or_404()
    if not STRIPE_SECRET_KEY:
        credit_order(order)
    return render_template('success.html', contribution=None, order=order, contributions=order.contributions)


@app.route('/stripe/webhook', methods=['POST'])
def stripe_webhook():
    payload = request.data
    sig_header = request.headers.get('Stripe-Signature')
    try:
        if STRIPE_WEBHOOK_SECRET and stripe:
            event = stripe.Webhook.construct_event(payload, sig_header, STRIPE_WEBHOOK_SECRET)
        else:
            event = request.get_json(force=True)
    except Exception as exc:
        return jsonify({'error': str(exc)}), 400

    if event.get('type') == 'checkout.session.completed':
        session_obj = event['data']['object']
        metadata = session_obj.get('metadata', {}) or {}
        order_id = metadata.get('order_id')
        if order_id:
            order = db.session.get(CheckoutOrder, int(order_id))
            if order and order.status != 'paid':
                order.stripe_session_id = session_obj.get('id') or order.stripe_session_id
                for contribution in order.contributions:
                    contribution.stripe_payment_intent = session_obj.get('payment_intent') or ''
                credit_order(order)
        else:
            contribution_id = metadata.get('contribution_id')
            contribution = db.session.get(Contribution, int(contribution_id)) if contribution_id else None
            if contribution and contribution.status != 'paid':
                contribution.stripe_payment_intent = session_obj.get('payment_intent') or ''
                credit_contribution(contribution)
    elif event.get('type') == 'account.updated':
        account = event['data']['object']
        user = User.query.filter_by(stripe_account_id=account.get('id')).first()
        if user:
            user.stripe_onboarding_complete = bool(account.get('details_submitted', False))
            user.stripe_charges_enabled = bool(account.get('charges_enabled', False))
            user.stripe_payouts_enabled = bool(account.get('payouts_enabled', False))
            if account.get('country'):
                user.stripe_country = account.get('country')
            db.session.commit()
            mongo_backup_model(user)
    return jsonify({'ok': True})



@app.route('/stripe/connect')
@login_required
def stripe_connect():
    user = current_user()
    cfg = stripe_config_status()
    if cfg['issues']:
        for issue in cfg['issues']:
            flash(issue, 'danger')
        return redirect(url_for('settings'))
    try:
        if not user.stripe_account_id:
            account = stripe.Account.create(
                type='express',
                country=user.stripe_country or STRIPE_DEFAULT_COUNTRY,
                email=user.email,
                business_type='individual',
                capabilities=({'transfers': {'requested': True}} if not STRIPE_CONNECT_DIRECT_PAYOUTS else {
                    'card_payments': {'requested': True},
                    'transfers': {'requested': True},
                }),
                business_profile={
                    'url': f'{BASE_URL}{url_for("profile", username=user.username)}'
                },
                metadata={'creator_id': str(user.id), 'username': user.username}
            )
            user.stripe_account_id = account.id
            user.stripe_country = account.get('country') or user.stripe_country or STRIPE_DEFAULT_COUNTRY
            db.session.commit()
            flash('Stripe payout account created. Finish onboarding so you can cash out website balance.', 'info')
        else:
            # Refresh status first so the settings page/button states stay honest.
            stripe_account_details(user)
        link = stripe.AccountLink.create(
            account=user.stripe_account_id,
            refresh_url=cfg['connect_refresh_url'],
            return_url=cfg['connect_return_url'],
            type='account_onboarding'
        )
        return redirect(link.url, code=303)
    except Exception as exc:
        message = stripe_exception_message(exc)
        app.logger.warning('Stripe Connect onboarding failed: %s', message)
        flash(message, 'danger')
        return redirect(url_for('settings'))


@app.route('/stripe/connect/return')
@login_required
def stripe_connect_return():
    user = current_user()
    details = stripe_account_details(user)
    if details.get('error'):
        flash(details['error'], 'danger')
    elif creator_stripe_ready(user):
        if STRIPE_CONNECT_DIRECT_PAYOUTS:
            flash('Stripe direct payouts and payments are ready. Supporters can now check out on your page.', 'success')
        else:
            flash('Stripe payouts are ready. Supporter payments will still sit in your ArcticSender balance until you cash out.', 'success')
    elif details.get('currently_due') or details.get('past_due'):
        flash('Stripe still needs more information. Click Continue Stripe Onboarding to finish: ' + ', '.join((details.get('currently_due') or details.get('past_due'))[:4]), 'warning')
    elif user.stripe_onboarding_complete:
        flash('Stripe details were submitted. Stripe may still be reviewing your account before payouts are ready.', 'info')
    else:
        flash('Stripe onboarding is not finished yet. Click Continue Stripe Onboarding to resume.', 'warning')
    return redirect(url_for('settings'))


@app.route('/stripe/connect/refresh')
@login_required
def stripe_connect_refresh():
    return redirect(url_for('stripe_connect'))


@app.route('/stripe/connect/dashboard')
@login_required
def stripe_express_dashboard():
    flash('Stripe is used for payout setup only. Manage your ArcticSender balance and cashouts from Settings.', 'info')
    return redirect(url_for('settings'))


@app.route('/stripe/connect/reset', methods=['POST'])
@login_required
def stripe_connect_reset():
    user = current_user()
    if not user.stripe_account_id:
        flash('There is no Stripe account to reset.', 'info')
        return redirect(url_for('settings'))
    if user.stripe_payouts_enabled or user.stripe_charges_enabled:
        flash('This Stripe account already has payouts enabled, so it was not reset. Use Settings to update your payout setup.', 'warning')
        return redirect(url_for('settings'))
    old_account = user.stripe_account_id
    user.stripe_account_id = ''
    user.stripe_onboarding_complete = False
    user.stripe_charges_enabled = False
    user.stripe_payouts_enabled = False
    db.session.commit()
    mongo_backup_model(user)
    app.logger.warning('User %s reset incomplete Stripe connected account %s', user.id, old_account)
    flash('Incomplete Stripe setup was reset. You can start onboarding again now.', 'success')
    return redirect(url_for('settings'))

@app.route('/cashout', methods=['POST'])
@login_required
def cashout():
    user = current_user()
    if STRIPE_CONNECT_DIRECT_PAYOUTS:
        flash('This site is in legacy direct-payout mode. Turn STRIPE_CONNECT_DIRECT_PAYOUTS=false to use website balance cashouts.', 'info')
        return redirect(url_for('dashboard'))
    if user.balance_cents <= 0:
        flash('Your balance is $0.00, so there is nothing to cash out yet.', 'warning')
        return redirect(url_for('dashboard'))
    if not user.stripe_account_id:
        flash('Connect your Stripe account in settings before cashing out.', 'danger')
        return redirect(url_for('settings'))
    amount_cents = cents_from_price(request.form.get('amount', '0'))
    fee_cents = cashout_fee_for(amount_cents)
    total_needed = amount_cents + fee_cents
    if amount_cents < MIN_CASHOUT_CENTS:
        flash('Minimum cashout is $10.00.', 'danger')
        return redirect(url_for('dashboard'))
    if user.balance_cents < total_needed:
        flash(f'Not enough balance. This cashout needs {money(total_needed)} including fees.', 'danger')
        return redirect(url_for('dashboard'))
    request_obj = CashoutRequest(
        creator_id=user.id,
        gross_cents=amount_cents,
        fee_cents=fee_cents,
        net_cents=amount_cents,
        status='pending'
    )
    user.balance_cents -= total_needed
    user.pending_cashout_cents += amount_cents
    db.session.add(request_obj)
    db.session.commit()
    mongo_backup_model(user)
    mongo_backup_model(request_obj)
    flash(f'Cashout request created for {money(amount_cents)}. Fee: {money(fee_cents)}.', 'success')
    return redirect(url_for('dashboard'))


@app.route('/admin')
@admin_required
def admin():
    users = User.query.order_by(User.created_at.desc()).all()
    items = item_order_query(WishlistItem.query).all()
    contributions = Contribution.query.order_by(Contribution.created_at.desc()).limit(120).all()
    cashouts = CashoutRequest.query.order_by(CashoutRequest.created_at.desc()).limit(80).all()
    totals = {
        'paid_cents': sum(c.amount_cents for c in Contribution.query.filter_by(status='paid').all()),
        'pending_cents': sum(c.amount_cents for c in Contribution.query.filter_by(status='pending').all()),
        'verified_users': User.query.filter_by(email_verified=True).count(),
        'stripe_ready': User.query.filter_by(stripe_payouts_enabled=True).count(),
        'suspended': User.query.filter_by(is_suspended=True).count(),
    }
    return render_template('admin.html', users=users, items=items, contributions=contributions, cashouts=cashouts, totals=totals)


@app.route('/admin/user/<int:user_id>')
@admin_required
def admin_user_detail(user_id):
    user = db.session.get(User, user_id) or abort(404)
    items = item_order_query(WishlistItem.query.filter_by(creator_id=user.id)).all()
    contributions = Contribution.query.filter_by(creator_id=user.id).order_by(Contribution.created_at.desc()).limit(80).all()
    orders = CheckoutOrder.query.filter_by(creator_id=user.id).order_by(CheckoutOrder.created_at.desc()).limit(40).all()
    cashouts = CashoutRequest.query.filter_by(creator_id=user.id).order_by(CashoutRequest.created_at.desc()).limit(40).all()
    stripe_status = stripe_account_details(user) if user.stripe_account_id else None
    return render_template('admin_user.html', managed_user=user, items=items, contributions=contributions, orders=orders, cashouts=cashouts, stripe_status=stripe_status)


@app.route('/admin/user/<int:user_id>/action', methods=['POST'])
@admin_required
def admin_user_action(user_id):
    admin_user = current_user()
    user = db.session.get(User, user_id) or abort(404)
    action = request.form.get('action', '')
    admin_user.last_seen_at = datetime.now(UTC).replace(tzinfo=None)
    note = request.form.get('admin_note', '').strip()[:2000]
    if note or action == 'save_note':
        user.admin_note = note
    if action == 'suspend':
        if user.id == admin_user.id:
            flash('You cannot suspend your own admin account.', 'danger')
            return redirect(url_for('admin_user_detail', user_id=user.id))
        user.is_suspended = True
        send_account_notice_email(user, f'{SITE_NAME} account paused', 'Your ArcticSender account was paused by support. Reply to this email if you need help.')
        flash('Account suspended.', 'warning')
    elif action == 'unsuspend':
        user.is_suspended = False
        send_account_notice_email(user, f'{SITE_NAME} account restored', 'Your ArcticSender account access has been restored.')
        flash('Account unsuspended.', 'success')
    elif action == 'verify_email':
        user.email_verified = True
        user.signup_otp_hash = ''
        user.signup_otp_expires_at = None
        flash('Email marked verified.', 'success')
    elif action == 'toggle_creator':
        user.is_creator = not user.is_creator
        flash('Creator status updated.', 'success')
    elif action == 'make_admin':
        user.is_admin = True
        flash('Admin role granted.', 'success')
    elif action == 'remove_admin':
        if user.id == admin_user.id:
            flash('You cannot remove your own admin role.', 'danger')
            return redirect(url_for('admin_user_detail', user_id=user.id))
        user.is_admin = False
        flash('Admin role removed.', 'info')
    elif action == 'reset_password':
        temp = secrets.token_urlsafe(14) + 'A1!'
        user.password_hash = generate_password_hash(temp)
        user.password_changed_at = datetime.now(UTC).replace(tzinfo=None)
        user.login_otp_hash = ''
        user.login_otp_expires_at = None
        clear_failed_logins(user)
        sent = send_password_reset_email(user, temp)
        if sent:
            flash('Temporary password generated and emailed to the user. It was not shown on-screen for security.', 'warning')
        else:
            flash('Temporary password was generated, but the email failed. Fix Resend and use reset again.', 'danger')
    elif action == 'resend_welcome':
        if send_welcome_email(user):
            flash('Welcome/setup email sent.', 'success')
        else:
            flash('Email failed. Check Resend settings.', 'danger')
    elif action == 'save_note':
        flash('Admin note saved.', 'success')
    else:
        flash('Unknown admin action.', 'danger')
    db.session.commit()
    mongo_backup_model(user)
    return redirect(url_for('admin_user_detail', user_id=user.id))


@app.route('/admin/test-email', methods=['POST'])
@admin_required
def admin_test_email():
    to_email = request.form.get('to_email', '').strip() or current_user().email
    body = '<p>This is a test email from your ArcticSender Resend setup. If you received this, auto emails are working.</p>'
    if send_email_safe(to_email, f'{SITE_NAME} Resend test', render_email_shell('Resend test successful', 'ArcticSender email sending is working.', body, 'Open admin', f'{BASE_URL}{url_for("admin")}')):
        flash(f'Test email sent to {to_email}.', 'success')
    else:
        flash('Test email failed. Check RESEND_API_KEY and MAIL_FROM/domain verification.', 'danger')
    return redirect(url_for('admin'))


@app.route('/admin/mongo-sync', methods=['POST'])
@admin_required
def admin_mongo_sync():
    if mongo_backup_all():
        flash('MongoDB backup sync completed.', 'success')
    else:
        status = mongo_config_status()
        if status['missing']:
            flash('MongoDB sync is not configured yet: ' + ', '.join(status['missing']), 'warning')
        else:
            flash('MongoDB sync failed. Check your VPS logs for the exact MongoDB connection error.', 'danger')
    return redirect(url_for('admin'))


@app.route('/admin/cashout/<int:cashout_id>/<action>', methods=['POST'])
@admin_required
def admin_cashout_action(cashout_id, action):
    cashout_obj = db.session.get(CashoutRequest, cashout_id) or abort(404)
    creator = cashout_obj.creator
    if cashout_obj.status != 'pending':
        flash('That cashout has already been processed.', 'warning')
        return redirect(url_for('admin'))
    if action == 'approve':
        if not creator.stripe_account_id:
            flash('Creator must connect Stripe before this cashout can be approved.', 'danger')
            return redirect(url_for('admin'))
        if STRIPE_AUTO_TRANSFERS and STRIPE_SECRET_KEY and stripe:
            try:
                transfer = stripe.Transfer.create(
                    amount=cashout_obj.net_cents,
                    currency='usd',
                    destination=creator.stripe_account_id,
                    metadata={'cashout_id': str(cashout_obj.id), 'creator_id': str(creator.id)}
                )
                cashout_obj.stripe_transfer_id = transfer.id
            except Exception as exc:
                app.logger.warning('Stripe transfer failed: %s', exc)
                flash('Stripe transfer failed. The cashout stayed pending and no balance was lost.', 'danger')
                return redirect(url_for('admin'))
        cashout_obj.status = 'approved'
        cashout_obj.completed_at = datetime.now(UTC).replace(tzinfo=None)
        creator.pending_cashout_cents = max(0, creator.pending_cashout_cents - cashout_obj.gross_cents)
        flash('Cashout approved.', 'success')
    elif action == 'reject':
        cashout_obj.status = 'rejected'
        cashout_obj.completed_at = datetime.now(UTC).replace(tzinfo=None)
        creator.balance_cents += cashout_obj.gross_cents + cashout_obj.fee_cents
        creator.pending_cashout_cents = max(0, creator.pending_cashout_cents - cashout_obj.gross_cents)
        flash('Cashout rejected and funds returned.', 'info')
    else:
        abort(404)
    db.session.commit()
    mongo_backup_model(cashout_obj)
    mongo_backup_model(creator)
    return redirect(url_for('admin'))


@app.errorhandler(429)
def too_many_requests(e):
    return render_template('error.html', code=429, message='Too many attempts. Please wait a few minutes and try again.'), 429


@app.errorhandler(403)
def forbidden(e):
    return render_template('error.html', code=403, message='You do not have permission to view this page.'), 403


@app.errorhandler(404)
def missing(e):
    return render_template('error.html', code=404, message='That page does not exist.'), 404



def ensure_admin_account():
    if not ADMIN_EMAIL or not ADMIN_PASSWORD:
        return
    username = slugify_username(ADMIN_USERNAME or 'admin') or 'admin'
    admin = User.query.filter_by(email=ADMIN_EMAIL).first()
    if not admin:
        if User.query.filter_by(username=username).first():
            username = f'admin{secrets.token_hex(3)}'
        admin = User(
            username=username,
            display_name=ADMIN_DISPLAY_NAME or 'ArcticSender Support',
            email=ADMIN_EMAIL,
            password_hash=generate_password_hash(ADMIN_PASSWORD),
            is_admin=True,
            email_verified=True,
            password_changed_at=datetime.now(UTC).replace(tzinfo=None),
        )
        db.session.add(admin)
        db.session.commit()
        mongo_backup_model(admin)
        app.logger.info('Seeded production admin account for %s', ADMIN_EMAIL)
        return
    changed = False
    if not admin.is_admin:
        admin.is_admin = True
        changed = True
    if ADMIN_PASSWORD:
        admin.password_hash = generate_password_hash(ADMIN_PASSWORD)
        admin.password_changed_at = datetime.now(UTC).replace(tzinfo=None)
        changed = True
    if not admin.email_verified:
        admin.email_verified = True
        changed = True
    if changed:
        db.session.commit()
        mongo_backup_model(admin)
        app.logger.info('Updated admin account for %s', ADMIN_EMAIL)


def migrate_sqlite_columns():
    if not app.config['SQLALCHEMY_DATABASE_URI'].startswith('sqlite:///'):
        return
    with db.engine.connect() as conn:
        tables = [row[0] for row in conn.exec_driver_sql("SELECT name FROM sqlite_master WHERE type='table'").fetchall()]
        if 'user' in tables:
            columns = [row[1] for row in conn.exec_driver_sql('PRAGMA table_info(user)').fetchall()]
            if 'stripe_onboarding_complete' not in columns:
                conn.exec_driver_sql("ALTER TABLE user ADD COLUMN stripe_onboarding_complete BOOLEAN DEFAULT 0")
            if 'stripe_charges_enabled' not in columns:
                conn.exec_driver_sql("ALTER TABLE user ADD COLUMN stripe_charges_enabled BOOLEAN DEFAULT 0")
            if 'stripe_payouts_enabled' not in columns:
                conn.exec_driver_sql("ALTER TABLE user ADD COLUMN stripe_payouts_enabled BOOLEAN DEFAULT 0")
            if 'stripe_country' not in columns:
                conn.exec_driver_sql("ALTER TABLE user ADD COLUMN stripe_country VARCHAR(2) DEFAULT 'CA'")
            extra_user_columns = {
                'is_suspended': "ALTER TABLE user ADD COLUMN is_suspended BOOLEAN DEFAULT 0",
                'email_verified': "ALTER TABLE user ADD COLUMN email_verified BOOLEAN DEFAULT 0",
                'signup_otp_hash': "ALTER TABLE user ADD COLUMN signup_otp_hash VARCHAR(255) DEFAULT ''",
                'signup_otp_expires_at': "ALTER TABLE user ADD COLUMN signup_otp_expires_at DATETIME",
                'login_otp_hash': "ALTER TABLE user ADD COLUMN login_otp_hash VARCHAR(255) DEFAULT ''",
                'login_otp_expires_at': "ALTER TABLE user ADD COLUMN login_otp_expires_at DATETIME",
                'password_changed_at': "ALTER TABLE user ADD COLUMN password_changed_at DATETIME",
                'last_login_at': "ALTER TABLE user ADD COLUMN last_login_at DATETIME",
                'last_seen_at': "ALTER TABLE user ADD COLUMN last_seen_at DATETIME",
                'failed_login_count': "ALTER TABLE user ADD COLUMN failed_login_count INTEGER DEFAULT 0 NOT NULL",
                'locked_until': "ALTER TABLE user ADD COLUMN locked_until DATETIME",
                'last_failed_login_at': "ALTER TABLE user ADD COLUMN last_failed_login_at DATETIME",
                'admin_note': "ALTER TABLE user ADD COLUMN admin_note TEXT DEFAULT ''",
            }
            for column_name, sql in extra_user_columns.items():
                if column_name not in columns:
                    conn.exec_driver_sql(sql)
        if 'wishlist_item' in tables:
            columns = [row[1] for row in conn.exec_driver_sql('PRAGMA table_info(wishlist_item)').fetchall()]
            if 'stock_count' not in columns:
                conn.exec_driver_sql("ALTER TABLE wishlist_item ADD COLUMN stock_count INTEGER DEFAULT 1 NOT NULL")
            if 'display_order' not in columns:
                conn.exec_driver_sql("ALTER TABLE wishlist_item ADD COLUMN display_order INTEGER DEFAULT 0 NOT NULL")
                conn.exec_driver_sql("UPDATE wishlist_item SET display_order = id * 10 WHERE display_order = 0")
        if 'checkout_order' in tables:
            columns = [row[1] for row in conn.exec_driver_sql('PRAGMA table_info(checkout_order)').fetchall()]
            if 'platform_fee_cents' not in columns:
                conn.exec_driver_sql("ALTER TABLE checkout_order ADD COLUMN platform_fee_cents INTEGER DEFAULT 0 NOT NULL")
        if 'contribution' in tables:
            columns = [row[1] for row in conn.exec_driver_sql('PRAGMA table_info(contribution)').fetchall()]
            if 'currency' not in columns:
                conn.exec_driver_sql("ALTER TABLE contribution ADD COLUMN currency VARCHAR(10) DEFAULT 'usd'")
            if 'charged_amount_cents' not in columns:
                conn.exec_driver_sql("ALTER TABLE contribution ADD COLUMN charged_amount_cents INTEGER DEFAULT 0 NOT NULL")
            if 'platform_fee_cents' not in columns:
                conn.exec_driver_sql("ALTER TABLE contribution ADD COLUMN platform_fee_cents INTEGER DEFAULT 0 NOT NULL")
            if 'order_id' not in columns:
                conn.exec_driver_sql("ALTER TABLE contribution ADD COLUMN order_id INTEGER")
        conn.commit()



def self_ping_loop():
    if not SELF_PING_URL:
        return
    app.logger.info('Self-ping enabled: %s every %ss', SELF_PING_URL, SELF_PING_INTERVAL_SECONDS)
    while True:
        try:
            with urllib.request.urlopen(SELF_PING_URL, timeout=12) as response:
                app.logger.debug('Self-ping %s -> %s', SELF_PING_URL, response.status)
        except Exception as exc:
            app.logger.debug('Self-ping failed: %s', exc)
        time.sleep(SELF_PING_INTERVAL_SECONDS)


_self_ping_started = False


def start_self_ping_thread():
    global _self_ping_started
    if _self_ping_started or not SELF_PING_ENABLED:
        return
    if APP_ENV != 'production' and os.environ.get('WERKZEUG_RUN_MAIN') != 'true':
        return
    _self_ping_started = True
    thread = threading.Thread(target=self_ping_loop, daemon=True, name='arcticsender-self-ping')
    thread.start()


with app.app_context():
    db.create_all()
    migrate_sqlite_columns()
    mongo_restore_uploads()
    restored_from_mongo = mongo_restore_all_if_empty()
    ensure_admin_account()
    if mongo_config_status()['enabled'] and not restored_from_mongo:
        mongo_backup_all()
        mongo_backup_uploads_all()

start_self_ping_thread()


if __name__ == '__main__':
    port = int(os.getenv('PORT', '10000'))
    app.run(
        host='0.0.0.0',
        port=port,
        debug=(APP_ENV != 'production')
    )
