from datetime import datetime, date
from app import db, login_manager
from flask_login import UserMixin


@login_manager.user_loader
def load_user(user_id):
    return User.query.get(int(user_id))


class User(db.Model, UserMixin):
    id = db.Column(db.Integer, primary_key=True)
    username = db.Column(db.String(20), unique=True, nullable=False)
    email = db.Column(db.String(120), unique=True, nullable=False)
    password_hash = db.Column(db.String(255), nullable=False)

    accepted_terms = db.Column(db.Boolean, default=False, nullable=False)
    accepted_terms_at = db.Column(db.DateTime, nullable=True)
    data_consent = db.Column(db.Boolean, default=False, nullable=False)

    created_at = db.Column(db.DateTime, default=datetime.utcnow)

    documents = db.relationship('UserDocument', backref='owner', lazy=True, cascade="all, delete-orphan")
    goals = db.relationship('SavingsGoal', backref='owner', lazy=True, cascade="all, delete-orphan")
    budgets = db.relationship('Budget', backref='owner', lazy=True, cascade="all, delete-orphan")
    debit_orders = db.relationship('DebitOrder', backref='owner', lazy=True, cascade="all, delete-orphan")
    statement_summary = db.relationship('StatementSummary', backref='owner', uselist=False, cascade="all, delete-orphan")

    def __repr__(self):
        return f"User('{self.username}', '{self.email}')"


class UserDocument(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    filename = db.Column(db.String(255), nullable=False)
    stored_name = db.Column(db.String(255), nullable=False)
    uploaded_at = db.Column(db.DateTime, default=datetime.utcnow)
    user_id = db.Column(db.Integer, db.ForeignKey('user.id'), nullable=False)


class SavingsGoal(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    name = db.Column(db.String(120), nullable=False)
    target_amount = db.Column(db.Float, nullable=False)
    target_date = db.Column(db.String(20), nullable=True)
    created_at = db.Column(db.DateTime, default=datetime.utcnow)
    user_id = db.Column(db.Integer, db.ForeignKey('user.id'), nullable=False)


class Budget(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    category = db.Column(db.String(80), nullable=False)
    monthly_limit = db.Column(db.Float, nullable=False)
    created_at = db.Column(db.DateTime, default=datetime.utcnow)
    user_id = db.Column(db.Integer, db.ForeignKey('user.id'), nullable=False)


class StatementSummary(db.Model):
    """One row per user — the latest extracted summary of their statements."""
    id = db.Column(db.Integer, primary_key=True)
    total_spent = db.Column(db.Float, default=0.0)
    total_received = db.Column(db.Float, default=0.0)
    balance = db.Column(db.Float, default=0.0)
    top_categories_json = db.Column(db.Text, default="[]")  # JSON string
    updated_at = db.Column(db.DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)
    user_id = db.Column(db.Integer, db.ForeignKey('user.id'), nullable=False, unique=True)


class DebitOrder(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    name = db.Column(db.String(120), nullable=False)
    amount = db.Column(db.Float, nullable=False)
    day_of_month = db.Column(db.Integer, nullable=True)  # day of month it recurs
    next_due = db.Column(db.Date, nullable=True)
    last_seen = db.Column(db.Date, nullable=True)
    user_id = db.Column(db.Integer, db.ForeignKey('user.id'), nullable=False)