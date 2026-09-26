import os
import uuid
import json
import re
from datetime import datetime, date, timedelta
from flask import (Blueprint, render_template, redirect, url_for, flash,
                   request, session, jsonify)
from werkzeug.utils import secure_filename
from app import db
from app.forms import (RegistrationForm, LoginForm, AgentInteractionForm,
                       SavingsGoalForm, BudgetForm)
from app.models import (User, UserDocument, SavingsGoal, Budget,
                        StatementSummary, DebitOrder)
from werkzeug.security import generate_password_hash, check_password_hash
from flask_login import login_user, current_user, logout_user, login_required

from azure.identity import DefaultAzureCredential, ManagedIdentityCredential, get_bearer_token_provider
from openai import OpenAI

main_bp = Blueprint('main', __name__)
auth_bp = Blueprint('auth', __name__)
agent_bp = Blueprint('agent', __name__)

# ============================================
# AZURE CONFIG
# ============================================
AZURE_AGENT_NAME = os.environ.get('AZURE_AGENT_NAME', "Bank-Buddy-New")

BANK_BUDDY_ENDPOINT = (
    "https://bank-buddy2026-resource.services.ai.azure.com"
    "/api/projects/bank-buddy2026"
    "/applications/Bank-Buddy-New"
    "/protocols/openai"
)
AZURE_API_VERSION = "2025-11-15-preview"

if os.environ.get('WEBSITE_SITE_NAME'):
    UPLOAD_FOLDER = '/home/uploads'
else:
    UPLOAD_FOLDER = os.path.join(os.path.dirname(__file__), 'uploads')

ALLOWED_EXTENSIONS = {'pdf', 'png', 'jpg', 'jpeg', 'csv', 'txt', 'doc', 'docx', 'xlsx', 'xls'}


def allowed_file(filename):
    return '.' in filename and filename.rsplit('.', 1)[1].lower() in ALLOWED_EXTENSIONS


def extract_file_text(filepath, max_chars=8000):
    try:
        if not os.path.exists(filepath):
            return ""
        ext = filepath.rsplit('.', 1)[-1].lower()

        if ext in ('txt', 'csv'):
            with open(filepath, 'r', encoding='utf-8', errors='ignore') as f:
                return f.read(max_chars)

        if ext in ('xlsx', 'xls'):
            from openpyxl import load_workbook
            wb = load_workbook(filepath, read_only=True, data_only=True)
            ws = wb.active
            rows = []
            for i, row in enumerate(ws.iter_rows(values_only=True)):
                if i > 200:
                    rows.append("... (truncated)")
                    break
                rows.append(", ".join("" if c is None else str(c) for c in row))
            wb.close()
            return "\n".join(rows)[:max_chars]

        if ext == 'pdf':
            try:
                from pypdf import PdfReader
                reader = PdfReader(filepath)
                text = [page.extract_text() or '' for page in reader.pages[:10]]
                return "\n".join(text)[:max_chars]
            except Exception as e:
                print(f"pdf read error: {e}")
                return ""

        with open(filepath, 'r', encoding='utf-8', errors='ignore') as f:
            return f.read(max_chars)
    except Exception as e:
        print(f"extract_file_text error: {e}")
        return ""


# ============================================
# CREDENTIALS
# ============================================
def get_azure_credential():
    """
    - Azure App Service  → ManagedIdentityCredential (system-assigned)
    - Render / other     → DefaultAzureCredential (reads AZURE_CLIENT_ID,
                            AZURE_TENANT_ID, AZURE_CLIENT_SECRET env vars)
    - Local              → DefaultAzureCredential (reads `az login`)
    """
    if os.environ.get('WEBSITE_SITE_NAME'):
        print("Auth: Azure App Service — ManagedIdentityCredential")
        return ManagedIdentityCredential()

    print("Auth: DefaultAzureCredential (Render env vars or local az login)")
    return DefaultAzureCredential()


def get_azure_client():
    endpoint = os.environ.get('AZURE_PROJECT_ENDPOINT') or BANK_BUDDY_ENDPOINT
    token_provider = get_bearer_token_provider(
        get_azure_credential(),
        "https://ai.azure.com/.default"
    )
    return OpenAI(
        base_url=endpoint,
        api_key=token_provider,
        default_query={"api-version": AZURE_API_VERSION}
    )


def call_bank_buddy(message, conversation_id=None):
    client = get_azure_client()
    if not conversation_id:
        conversation = client.conversations.create()
        conversation_id = conversation.id
    response = client.responses.create(input=message, conversation=conversation_id)
    return response.output_text, conversation_id


# ============================================
# CONTEXT — dashboard awareness
# ============================================
def build_user_context():
    uid = current_user.id
    goals = SavingsGoal.query.filter_by(user_id=uid).all()
    budgets = Budget.query.filter_by(user_id=uid).all()
    summary = StatementSummary.query.filter_by(user_id=uid).first()
    debits = DebitOrder.query.filter_by(user_id=uid).order_by(DebitOrder.next_due.asc()).all()

    parts = ["===== USER DASHBOARD CONTEXT ====="]
    parts.append(f"User: {current_user.username}")

    if summary:
        parts.append(f"Total spent (all statements): R{summary.total_spent:.2f}")
        parts.append(f"Total received: R{summary.total_received:.2f}")
        parts.append(f"Balance: R{summary.balance:.2f}")
        try:
            cats = json.loads(summary.top_categories_json or "[]")
            if cats:
                cat_lines = ", ".join(f"{c['name']} (R{c['amount']:.2f})" for c in cats[:5])
                parts.append(f"Top spending categories: {cat_lines}")
        except Exception:
            pass
    else:
        parts.append("No statements analysed yet.")

    if budgets:
        blines = ", ".join(f"{b.category}: R{b.monthly_limit:.2f}/mo" for b in budgets)
        parts.append(f"User's monthly budgets: {blines}")

    if goals:
        glines = ", ".join(
            f"{g.name} (target R{g.target_amount:.2f}"
            + (f" by {g.target_date}" if g.target_date else "")
            + ")"
            for g in goals
        )
        parts.append(f"User's savings goals: {glines}")

    if debits:
        dlines = ", ".join(
            f"{d.name} R{d.amount:.2f}"
            + (f" — next on {d.next_due.isoformat()}" if d.next_due else "")
            for d in debits[:6]
        )
        parts.append(f"Detected debit orders / recurring payments: {dlines}")

    parts.append("===== END CONTEXT =====")
    return "\n".join(parts)


def ask_bank_buddy_with_context(user_message):
    context = build_user_context()
    full_prompt = f"{context}\n\nUser message: {user_message}"
    conv_id = session.get('conversation_id')
    response_text, conv_id = call_bank_buddy(full_prompt, conv_id)
    session['conversation_id'] = conv_id
    return response_text


# ============================================
# AUTH
# ============================================
@auth_bp.route("/register", methods=['GET', 'POST'])
def register():
    if current_user.is_authenticated:
        return redirect(url_for('main.home'))
    form = RegistrationForm()
    if form.validate_on_submit():
        if User.query.filter_by(email=form.email.data).first():
            flash('That email is already registered.', 'danger')
            return render_template('register.html', title='Register', form=form)
        if User.query.filter_by(username=form.username.data).first():
            flash('That username is already taken.', 'danger')
            return render_template('register.html', title='Register', form=form)

        user = User(
            username=form.username.data,
            email=form.email.data,
            password_hash=generate_password_hash(form.password.data),
            accepted_terms=form.accept_terms.data,
            accepted_terms_at=datetime.utcnow(),
            data_consent=form.data_consent.data
        )
        db.session.add(user)
        db.session.commit()
        flash('Your account has been created. You can now log in.', 'success')
        return redirect(url_for('auth.login'))
    return render_template('register.html', title='Register', form=form)


@auth_bp.route("/login", methods=['GET', 'POST'])
def login():
    if current_user.is_authenticated:
        return redirect(url_for('main.home'))
    form = LoginForm()
    if form.validate_on_submit():
        user = User.query.filter_by(email=form.email.data).first()
        if user and check_password_hash(user.password_hash, form.password.data):
            login_user(user, remember=form.remember.data)
            session['conversation_history'] = []
            session['conversation_id'] = None
            return redirect(url_for('agent.agent_dashboard'))
        flash('Login unsuccessful.', 'danger')
    return render_template('login.html', title='Login', form=form)


@auth_bp.route("/logout")
def logout():
    session.pop('conversation_history', None)
    session.pop('conversation_id', None)
    logout_user()
    return redirect(url_for('main.home'))


# ============================================
# MAIN
# ============================================
@main_bp.route("/")
@main_bp.route("/home")
def home():
    return render_template('home.html')


# ============================================
# DASHBOARD
# ============================================
@agent_bp.route("/agent", methods=['GET', 'POST'])
@login_required
def agent_dashboard():
    if 'conversation_history' not in session:
        session['conversation_history'] = []

    documents = UserDocument.query.filter_by(user_id=current_user.id).order_by(UserDocument.uploaded_at.desc()).all()
    goals = SavingsGoal.query.filter_by(user_id=current_user.id).order_by(SavingsGoal.created_at.desc()).all()
    budgets = Budget.query.filter_by(user_id=current_user.id).order_by(Budget.created_at.desc()).all()
    summary = StatementSummary.query.filter_by(user_id=current_user.id).first()
    debits = DebitOrder.query.filter_by(user_id=current_user.id).order_by(DebitOrder.next_due.asc()).all()

    today = date.today()
    debit_rows = []
    for d in debits:
        days_until = (d.next_due - today).days if d.next_due else None
        debit_rows.append({
            'id': d.id,
            'name': d.name,
            'amount': d.amount,
            'next_due': d.next_due,
            'days_until': days_until,
            'due_soon': days_until is not None and 0 <= days_until <= 7
        })

    return render_template(
        'agent_dashboard.html',
        documents=documents,
        goals=goals,
        budgets=budgets,
        summary=summary,
        debit_rows=debit_rows
    )


# ============================================
# CHAT + AGENT CALLS
# ============================================
@agent_bp.route("/agent/chat")
@login_required
def agent_chat():
    form = AgentInteractionForm()
    if 'conversation_history' not in session:
        session['conversation_history'] = []
    return render_template(
        'chat.html',
        form=form,
        conversation_history=session.get('conversation_history', [])
    )


@agent_bp.route("/agent/send", methods=['POST'])
def agent_send():
    if not current_user.is_authenticated:
        return jsonify({"error": "Not logged in."}), 401
    try:
        data = request.get_json(silent=True) or {}
        message = (data.get('message') or '').strip()
        if not message:
            return jsonify({"error": "Empty message"}), 400

        response_text = ask_bank_buddy_with_context(message)

        session.setdefault('conversation_history', []).append({
            'user': message, 'assistant': response_text
        })
        session.modified = True
        return jsonify({"status": "completed", "response": response_text})
    except Exception as e:
        print(f"agent_send error: {e}")
        return jsonify({"error": str(e), "type": type(e).__name__}), 500


@agent_bp.route("/agent/greet", methods=['POST'])
@login_required
def agent_greet():
    try:
        prompt = (
            "Greet me warmly as Bank Buddy. Introduce yourself briefly, "
            "then reference what you already know from my dashboard: my current "
            "balance, top spending categories if any, upcoming debit orders, "
            "and any savings goals or budgets I've set. Ask what I'd like help with. "
            "Keep it under 120 words."
        )
        response_text = ask_bank_buddy_with_context(prompt)

        session.setdefault('conversation_history', []).append({
            'user': '[greeting]', 'assistant': response_text
        })
        session.modified = True
        return jsonify({"status": "ok", "response": response_text})
    except Exception as e:
        print(f"greet error: {e}")
        fallback = ("Hello! I'm Bank Buddy, your supportive AI financial assistant. "
                    "What would you like help with today?")
        return jsonify({"status": "fallback", "response": fallback})


@agent_bp.route("/agent/reset", methods=['POST'])
@login_required
def agent_reset():
    session['conversation_id'] = None
    session['conversation_history'] = []
    return jsonify({"status": "ok"})


# ============================================
# PRESET TABS
# ============================================
PRESET_PROMPTS = {
    "budget": ("Help me create a personalised monthly budget in ZAR. Use my dashboard "
               "context — my current spending, budgets, and goals — to make it personal."),
    "expenses": ("Look at my recent spending from my dashboard context and tell me the "
                 "top 3 trends and where I can cut back."),
    "savings": ("Based on my income, spending, and existing goals, help me set a new "
                "savings goal with a realistic monthly plan."),
    "learn": ("Give me a short financial literacy lesson relevant to my situation based "
              "on my dashboard context. Pick something I'd benefit from."),
}


@agent_bp.route("/agent/preset/<preset_name>", methods=['POST'])
@login_required
def agent_preset(preset_name):
    prompt = PRESET_PROMPTS.get(preset_name)
    if not prompt:
        return jsonify({"error": "Unknown preset."}), 400
    try:
        response_text = ask_bank_buddy_with_context(prompt)
        session.setdefault('conversation_history', []).append({
            'user': f"[{preset_name.title()} tab]", 'assistant': response_text
        })
        session.modified = True
        return jsonify({"status": "ok", "response": response_text})
    except Exception as e:
        return jsonify({"error": str(e), "type": type(e).__name__}), 500


# ============================================
# DOCUMENTS + ANALYSIS
# ============================================
@agent_bp.route("/agent/upload", methods=['POST'])
@login_required
def agent_upload():
    if 'document' not in request.files:
        return jsonify({"error": "No file provided"}), 400
    file = request.files['document']
    if not file.filename:
        return jsonify({"error": "Empty filename"}), 400
    if not allowed_file(file.filename):
        return jsonify({"error": "File type not allowed"}), 400

    os.makedirs(UPLOAD_FOLDER, exist_ok=True)
    original_name = secure_filename(file.filename)
    stored_name = f"{uuid.uuid4().hex}_{original_name}"
    file.save(os.path.join(UPLOAD_FOLDER, stored_name))

    doc = UserDocument(filename=original_name, stored_name=stored_name, user_id=current_user.id)
    db.session.add(doc)
    db.session.commit()

    return jsonify({"status": "ok", "id": doc.id, "filename": original_name})


def parse_agent_json(text):
    m = re.search(r"```(?:json)?\s*(\{.*?\})\s*```", text, re.DOTALL)
    if m:
        try:
            return json.loads(m.group(1))
        except Exception:
            pass
    m = re.search(r"(\{.*\})", text, re.DOTALL)
    if m:
        try:
            return json.loads(m.group(1))
        except Exception:
            pass
    return None


@agent_bp.route("/agent/analyse-latest", methods=['POST'])
@login_required
def agent_analyse_latest():
    try:
        doc = (UserDocument.query
               .filter_by(user_id=current_user.id)
               .order_by(UserDocument.uploaded_at.desc())
               .first())
        if not doc:
            return jsonify({"error": "No statement found."}), 404

        file_path = os.path.join(UPLOAD_FOLDER, doc.stored_name)
        file_text = extract_file_text(file_path)

        if not file_text.strip():
            return jsonify({
                "status": "ok",
                "readable": False,
                "response": ("I could not read the file directly — it may be a scanned PDF. "
                             "Please paste a few key lines so I can still help you analyse it.")
            })

        extract_prompt = (
            "You are extracting structured data from a South African bank statement.\n"
            "Return ONLY valid JSON — no other text — in this exact shape:\n"
            "{\n"
            '  "total_spent": number,\n'
            '  "total_received": number,\n'
            '  "balance": number,\n'
            '  "top_categories": [{"name": string, "amount": number}],\n'
            '  "debit_orders": [{"name": string, "amount": number, "day_of_month": number}]\n'
            "}\n\n"
            "Rules:\n"
            "- All amounts in ZAR (positive numbers).\n"
            "- top_categories: at most 5, biggest first.\n"
            "- debit_orders: only recurring monthly payments you can identify by name.\n"
            "- If you cannot tell a value, use 0 (or [] for lists).\n\n"
            "STATEMENT TEXT:\n"
            f"{file_text}"
        )
        raw_json, _ = call_bank_buddy(extract_prompt, None)
        extracted = parse_agent_json(raw_json) or {}

        total_spent = float(extracted.get('total_spent') or 0)
        total_received = float(extracted.get('total_received') or 0)
        balance = float(extracted.get('balance') or (total_received - total_spent))
        top_categories = extracted.get('top_categories') or []
        debit_orders = extracted.get('debit_orders') or []

        summary = StatementSummary.query.filter_by(user_id=current_user.id).first()
        if not summary:
            summary = StatementSummary(user_id=current_user.id)
            db.session.add(summary)
        summary.total_spent = total_spent
        summary.total_received = total_received
        summary.balance = balance
        summary.top_categories_json = json.dumps(top_categories)
        summary.updated_at = datetime.utcnow()

        today = date.today()
        for d in debit_orders:
            name = (d.get('name') or '').strip()
            if not name:
                continue
            amount = float(d.get('amount') or 0)
            dom = d.get('day_of_month') or None

            existing = DebitOrder.query.filter_by(user_id=current_user.id, name=name).first()
            if dom:
                dom = int(dom)
                if dom < today.day:
                    next_due = date(today.year + (today.month // 12),
                                    (today.month % 12) + 1, min(dom, 28))
                else:
                    next_due = date(today.year, today.month, min(dom, 28))
            else:
                next_due = today + timedelta(days=30)

            if existing:
                existing.amount = amount
                existing.day_of_month = dom
                existing.next_due = next_due
                existing.last_seen = today
            else:
                db.session.add(DebitOrder(
                    name=name, amount=amount, day_of_month=dom,
                    next_due=next_due, last_seen=today, user_id=current_user.id
                ))

        db.session.commit()

        narrative_prompt = (
            "The user just uploaded a bank statement and I've extracted this summary:\n"
            f"- Total spent: R{total_spent:.2f}\n"
            f"- Total received: R{total_received:.2f}\n"
            f"- Balance: R{balance:.2f}\n"
            f"- Top categories: {json.dumps(top_categories)}\n"
            f"- Recurring debit orders detected: {json.dumps(debit_orders)}\n\n"
            "In under 160 words, in a warm and encouraging tone:\n"
            "1. Acknowledge the upload and reassure them about privacy.\n"
            "2. Highlight the 2 biggest trends or observations.\n"
            "3. If there are debit orders, mention the next one coming up.\n"
            "4. Give one practical tip.\n"
            "5. Ask what they'd like help with next."
        )
        conv_id = session.get('conversation_id')
        narrative_text, conv_id = call_bank_buddy(narrative_prompt, conv_id)
        session['conversation_id'] = conv_id

        session.setdefault('conversation_history', []).append({
            'user': f"[Uploaded: {doc.filename}]",
            'assistant': narrative_text
        })
        session.modified = True

        return jsonify({
            "status": "ok",
            "readable": True,
            "response": narrative_text,
            "filename": doc.filename
        })

    except Exception as e:
        print(f"analyse error: {e}")
        return jsonify({"error": str(e), "type": type(e).__name__}), 500


@agent_bp.route("/documents/<int:doc_id>/delete", methods=['POST'])
@login_required
def delete_document(doc_id):
    doc = UserDocument.query.get_or_404(doc_id)
    if doc.user_id != current_user.id:
        return jsonify({"error": "Not allowed."}), 403
    try:
        path = os.path.join(UPLOAD_FOLDER, doc.stored_name)
        if os.path.exists(path):
            os.remove(path)
    except Exception as e:
        print(f"file delete failed: {e}")
    db.session.delete(doc)
    db.session.commit()
    return jsonify({"status": "deleted", "id": doc_id})


@agent_bp.route("/debit-orders/<int:debit_id>/dismiss", methods=['POST'])
@login_required
def dismiss_debit(debit_id):
    d = DebitOrder.query.get_or_404(debit_id)
    if d.user_id != current_user.id:
        return jsonify({"error": "Not allowed."}), 403
    db.session.delete(d)
    db.session.commit()
    return jsonify({"status": "deleted", "id": debit_id})


# ============================================
# GOALS
# ============================================
@agent_bp.route("/goals/add", methods=['POST'])
@login_required
def add_goal():
    data = request.get_json(silent=True) or {}
    name = (data.get('name') or '').strip()
    amount = data.get('target_amount')
    target_date = (data.get('target_date') or '').strip()
    if not name or not amount:
        return jsonify({"error": "Name and amount required."}), 400
    try:
        amount = float(amount)
    except ValueError:
        return jsonify({"error": "Invalid amount."}), 400
    goal = SavingsGoal(name=name, target_amount=amount, target_date=target_date,
                       user_id=current_user.id)
    db.session.add(goal)
    db.session.commit()
    return jsonify({"status": "ok", "id": goal.id})


@agent_bp.route("/goals/<int:goal_id>/delete", methods=['POST'])
@login_required
def delete_goal(goal_id):
    goal = SavingsGoal.query.get_or_404(goal_id)
    if goal.user_id != current_user.id:
        return jsonify({"error": "Not allowed."}), 403
    db.session.delete(goal)
    db.session.commit()
    return jsonify({"status": "deleted", "id": goal_id})


# ============================================
# BUDGETS
# ============================================
@agent_bp.route("/budgets/add", methods=['POST'])
@login_required
def add_budget():
    data = request.get_json(silent=True) or {}
    category = (data.get('category') or '').strip()
    amount = data.get('monthly_limit')
    if not category or not amount:
        return jsonify({"error": "Category and amount required."}), 400
    try:
        amount = float(amount)
    except ValueError:
        return jsonify({"error": "Invalid amount."}), 400
    b = Budget(category=category, monthly_limit=amount, user_id=current_user.id)
    db.session.add(b)
    db.session.commit()
    return jsonify({"status": "ok", "id": b.id})


@agent_bp.route("/budgets/<int:budget_id>/delete", methods=['POST'])
@login_required
def delete_budget(budget_id):
    b = Budget.query.get_or_404(budget_id)
    if b.user_id != current_user.id:
        return jsonify({"error": "Not allowed."}), 403
    db.session.delete(b)
    db.session.commit()
    return jsonify({"status": "deleted", "id": budget_id})


# ============================================
# UTILITIES
# ============================================
@main_bp.route("/chat-test")
def chat_test():
    try:
        text, _ = call_bank_buddy("Hello Bank Buddy")
        return {"status": "ok", "response": text}
    except Exception as e:
        return {"status": "error", "type": type(e).__name__, "message": str(e)}, 500


@main_bp.route("/auth-debug")
def auth_debug():
    """Diagnostic endpoint — reports which credential path is being used."""
    env = {
        "WEBSITE_SITE_NAME": os.environ.get('WEBSITE_SITE_NAME'),
        "AZURE_CLIENT_ID": bool(os.environ.get('AZURE_CLIENT_ID')),
        "AZURE_TENANT_ID": bool(os.environ.get('AZURE_TENANT_ID')),
        "AZURE_CLIENT_SECRET": bool(os.environ.get('AZURE_CLIENT_SECRET')),
        "AZURE_PROJECT_ENDPOINT_set": bool(os.environ.get('AZURE_PROJECT_ENDPOINT')),
        "AZURE_AGENT_NAME": AZURE_AGENT_NAME,
    }
    return {
        "environment": env,
        "credential_chosen": type(get_azure_credential()).__name__,
    }


@main_bp.route("/health")
def health():
    return {"status": "healthy",
            "environment": "Azure App Service" if os.environ.get('WEBSITE_SITE_NAME') else "Local",
            "agent": "Bank Buddy New"}