import os
import datetime
from functools import wraps
from flask import Flask, render_template, request, redirect, url_for, session, flash
from flask_sqlalchemy import SQLAlchemy
from werkzeug.security import generate_password_hash, check_password_hash
from sqlalchemy import text

app = Flask(__name__)
app.secret_key = "dev-secret"  # Секретний ключ для сесій

# Підключення до локальної бази даних SQLite
BASE_DIR = os.path.abspath(os.path.dirname(__file__))
DB_PATH = os.path.join(BASE_DIR, "finance.db")
app.config["SQLALCHEMY_DATABASE_URI"] = f"sqlite:///{DB_PATH}"
app.config["SQLALCHEMY_TRACK_MODIFICATIONS"] = False

db = SQLAlchemy(app)

# ------------------ Моделі бази даних ------------------

# Модель користувача
class User(db.Model):
    __tablename__ = "users"
    id = db.Column(db.Integer, primary_key=True)
    name = db.Column(db.String(120), default="")
    username = db.Column(db.String(80), unique=True, nullable=False)
    password = db.Column(db.String(120), nullable=False)
    currency = db.Column(db.String(10), default="UAH")
    created = db.Column(db.String(20), default=lambda: str(datetime.date.today()))

# Модель транзакції (дохід або витрата)
class Transaction(db.Model):
    __tablename__ = "transactions"
    id = db.Column(db.Integer, primary_key=True)
    user_id = db.Column(db.Integer, db.ForeignKey("users.id"), nullable=False)
    type = db.Column(db.String(20), nullable=False)  # income або expense
    category = db.Column(db.String(120))
    amount = db.Column(db.Float, nullable=False, default=0.0)
    payment_method = db.Column(db.String(50))
    date = db.Column(db.String(20), nullable=False)  # формат YYYY-MM-DD
    description = db.Column(db.String(255))

# Модель бюджету (ліміти витрат за категоріями)
class Budget(db.Model):
    __tablename__ = "budgets"
    id = db.Column(db.Integer, primary_key=True)
    user_id = db.Column(db.Integer, db.ForeignKey("users.id"), nullable=False)
    category = db.Column(db.String(120), nullable=False)
    amount = db.Column(db.Float, nullable=False, default=0.0)

# Модель фінансової цілі (накопичення)
class Goal(db.Model):
    __tablename__ = "goals"
    id = db.Column(db.Integer, primary_key=True)
    user_id = db.Column(db.Integer, db.ForeignKey("users.id"), nullable=False)
    name = db.Column(db.String(120), nullable=False)
    target = db.Column(db.Float, nullable=False, default=0.0)
    current = db.Column(db.Float, nullable=False, default=0.0)
    deadline = db.Column(db.String(20))

# Створення таблиц
with app.app_context():
    db.create_all()

# ------------------ Допоміжні функції ------------------

# Українські назви місяців
MONTHS_UA = {
    1: "січень", 2: "лютий", 3: "березень", 4: "квітень",
    5: "травень", 6: "червень", 7: "липень", 8: "серпень",
    9: "вересень", 10: "жовтень", 11: "листопад", 12: "грудень"
}

# Отримання поточного користувача із сесії
def current_user():
    uname = session.get("username")
    return User.query.filter_by(username=uname).first() if uname else None

# Перетворити введене число з рядка у float
def parse_number(raw: str) -> float:
    raw = (raw or "").strip().replace(",", ".")
    return float(raw)

# Перевірка авторизації користувача
def login_required(view):
    @wraps(view)
    def wrapped(*args, **kwargs):
        if "username" not in session:
            return redirect(url_for("login"))
        return view(*args, **kwargs)
    return wrapped

# ------------------ Авторизація ------------------

# Сторінка входу в акаунт
@app.route("/", methods=["GET", "POST"])
def login():
    if request.method == "POST":
        username = request.form["username"]
        password = request.form["password"]

        user = User.query.filter_by(username=username).first()
        if user and check_password_hash(user.password, password):
            session["username"] = user.username
            flash("Вхід успішний!", "success")
            return redirect(url_for("dashboard"))

        flash("Невірний логін або пароль!", "danger")

    return render_template("login.html")

# Реєстрація нового користувача
@app.route("/register", methods=["POST"])
def register():
    name = request.form.get("name", "")
    username = request.form["username"]
    password = request.form["password"]
    currency = request.form.get("currency", "UAH")

    if User.query.filter_by(username=username).first():
        flash("Такий користувач уже існує!", "warning")
        return redirect(url_for("login"))

    user = User(
        name=name,
        username=username,
        password=generate_password_hash(password),
        currency=currency,
    )
    db.session.add(user)
    db.session.commit()

    flash("Реєстрація успішна! Тепер увійдіть.", "success")
    return redirect(url_for("login"))

# Вихід із акаунту
@app.route("/logout")
def logout():
    session.pop("username", None)
    flash("Ви вийшли із системи.", "info")
    return redirect(url_for("login"))

# ------------------ Панель користувача ------------------

# Головна сторінка з аналітикою
@app.route("/dashboard")
@login_required
def dashboard():
    user = current_user()
    today = datetime.date.today()

    # Отримати обраний місяць і рік або встановити поточний
    m_arg = request.args.get("month")
    y_arg = request.args.get("year")
    if m_arg and y_arg:
        try:
            sel_month = int(m_arg)
            sel_year = int(y_arg)
        except ValueError:
            sel_month, sel_year = today.month, today.year
    else:
        sel_month, sel_year = today.month, today.year

    month_prefix = f"{sel_year}-{sel_month:02d}"

    # Отримати всі транзакції користувача
    user_tr = Transaction.query.filter_by(user_id=user.id).all()
    month_tr = [t for t in user_tr if t.date.startswith(month_prefix)]

    # Розрахунок доходів, витрат і балансу
    income = sum(t.amount for t in month_tr if t.type == "income")
    expenses = sum(t.amount for t in month_tr if t.type == "expense")
    balance = income - expenses

    # Витрати за категоріями
    exp_by_cat = {}
    for t in month_tr:
        if t.type == "expense":
            c = t.category or "Інше"
            exp_by_cat[c] = exp_by_cat.get(c, 0.0) + t.amount

    # Денна динаміка руху коштів
    daily = {}
    for t in month_tr:
        sign = 1 if t.type == "income" else -1
        daily[t.date] = daily.get(t.date, 0.0) + sign * t.amount

    daily_labels = sorted(daily.keys())
    daily_values = [round(daily[d], 2) for d in daily_labels]

    # Мета накопичень та бюджети
    goals = Goal.query.filter_by(user_id=user.id).all()
    goals_savings = sum(g.current for g in goals)
    budgets = Budget.query.filter_by(user_id=user.id).all()
    budget_map = {b.category: b.amount for b in budgets}

    # Обчислення "фінансового здоров'я"
    if income > 0:
        spend_eff = max(0, min((balance / income) * 100, 100))
        total_budget = sum(budget_map.values())
        spent_vs_budget = 0.0
        for cat, b_amt in budget_map.items():
            spent_vs_budget += min(exp_by_cat.get(cat, 0.0), b_amt)
        budget_eff = (spent_vs_budget / total_budget * 100) if total_budget > 0 else 100.0
        saving_ratio = min((goals_savings / income) * 100, 100)
        health = (spend_eff * 0.5) + (budget_eff * 0.3) + (saving_ratio * 0.2)
    else:
        health = 0.0

    months_list = [(i, MONTHS_UA[i]) for i in range(1, 13)]
    years_list = list(range(2023, today.year + 2))

    # Відображення сторінки
    return render_template(
        "dashboard.html",
        month=f"{MONTHS_UA[sel_month]} {sel_year}",
        currency=user.currency,
        income=income,
        expenses=expenses,
        goals_savings=goals_savings,
        balance=balance,
        health=health,
        exp_labels=list(exp_by_cat.keys()),
        exp_values=list(exp_by_cat.values()),
        daily_labels=daily_labels,
        daily_values=daily_values,
        months=months_list,
        years=years_list,
        selected_month=sel_month,
        selected_year=sel_year,
    )
# ------------------ Транзакції ------------------

# Сторінка зі списком транзакцій
@app.route("/transactions")
@login_required
def transactions_view():
    user = current_user()
    # Отримуємо транзакції поточного користувача (новіші зверху)
    transactions = (
        Transaction.query
        .filter_by(user_id=user.id)
        .order_by(Transaction.date.desc())
        .all()
    )
    # Категорії з бюджету, щоб підставляти у форму
    categories = [b.category for b in Budget.query.filter_by(user_id=user.id).all()]
    today = datetime.date.today().strftime("%Y-%m-%d")
    return render_template(
        "transactions.html",
        transactions={t.id: t for t in transactions},
        currency=user.currency,
        today=today,
        categories=categories,
    )

# Додавання нової транзакції
@app.route("/add_transaction", methods=["POST"])
@login_required
def add_transaction():
    user = current_user()
    # Перевірка суми
    try:
        amount = parse_number(request.form["amount"])
    except ValueError:
        flash("Сума транзакції має бути числом!", "danger")
        return redirect(url_for("transactions_view"))

    # Категорія може бути обрана з випадаючого списку або введена вручну
    category = request.form.get("category_select") or request.form.get("category") or "Інше"

    tr = Transaction(
        user_id=user.id,
        type=request.form["type"],
        category=category,
        amount=amount,
        payment_method=request.form.get("payment", "Cash"),
        date=request.form.get("date") or str(datetime.date.today()),
        description=request.form.get("description") or "",
    )
    db.session.add(tr)
    db.session.commit()
    flash("Транзакцію додано!", "success")
    return redirect(url_for("transactions_view"))

# Видалення транзакції
@app.route("/delete_transaction/<int:tid>", methods=["POST"])
@login_required
def delete_transaction(tid):
    user = current_user()
    tr = Transaction.query.get(tid)
    # Видаляємо тільки свою транзакцію
    if tr and tr.user_id == user.id:
        db.session.delete(tr)
        db.session.commit()
        flash("Транзакцію видалено.", "info")
    return redirect(url_for("transactions_view"))


# ------------------ Бюджети ------------------

# Сторінка бюджетів
@app.route("/budget")
@login_required
def budget():
    user = current_user()
    budgets = Budget.query.filter_by(user_id=user.id).all()

    # Рахуємо витрати за поточний місяць, щоб показати "витрачено"
    today = datetime.date.today()
    month_prefix = today.strftime("%Y-%m")
    expenses = Transaction.query.filter_by(user_id=user.id, type="expense").all()

    spending = {}
    for t in expenses:
        if t.date.startswith(month_prefix):
            spending[t.category] = spending.get(t.category, 0.0) + t.amount

    return render_template(
        "budget.html",
        budgets={b.category: b.amount for b in budgets},
        spending_by_cat=spending,
        currency=user.currency,
    )

# Збереження нового бюджету або оновлення існуючого
@app.route("/save_budget", methods=["POST"])
@login_required
def save_budget_route():
    user = current_user()
    category = request.form["category"].strip()
    try:
        amount = parse_number(request.form["amount"])
    except ValueError:
        flash("Сума бюджету має бути числом!", "danger")
        return redirect(url_for("budget"))

    existing = Budget.query.filter_by(user_id=user.id, category=category).first()
    if existing:
        # Якщо категорія вже є — просто оновлюємо суму
        existing.amount = amount
    else:
        db.session.add(Budget(user_id=user.id, category=category, amount=amount))

    db.session.commit()
    flash("Бюджет збережено!", "success")
    return redirect(url_for("budget"))

# Оновлення існуючої категорії бюджету
@app.route("/update_budget", methods=["POST"])
@login_required
def update_budget():
    user = current_user()
    old_category = request.form["old_category"]
    new_category = request.form["category"].strip()
    try:
        amount = parse_number(request.form["amount"])
    except ValueError:
        flash("Сума бюджету має бути числом!", "danger")
        return redirect(url_for("budget"))

    b = Budget.query.filter_by(user_id=user.id, category=old_category).first()
    if not b:
        flash("Категорію не знайдено.", "danger")
        return redirect(url_for("budget"))

    b.category = new_category
    b.amount = amount
    db.session.commit()
    flash("Категорію оновлено!", "success")
    return redirect(url_for("budget"))

# Видалення категорії бюджету
@app.route("/delete_budget/<path:cat>", methods=["POST"])
@login_required
def delete_budget(cat):
    user = current_user()
    b = Budget.query.filter_by(user_id=user.id, category=cat).first()
    if b:
        db.session.delete(b)
        db.session.commit()
        flash("Категорію видалено.", "info")
    else:
        flash("Не вдалося видалити категорію.", "danger")
    return redirect(url_for("budget"))


# ------------------ Фінансові цілі ------------------

# Сторінка цілей
@app.route("/savings")
@login_required
def savings():
    user = current_user()
    goals = Goal.query.filter_by(user_id=user.id).all()
    processed = []
    # Рахуємо прогрес для кожної цілі
    for g in goals:
        target = g.target or 0.0
        current = g.current or 0.0
        percent = (current / target * 100) if target > 0 else 0
        processed.append((g.id, g, percent))
    return render_template("savings.html", goals=processed, currency=user.currency)

# Додавання нової фінансової цілі
@app.route("/add_savings", methods=["POST"])
@login_required
def add_savings():
    user = current_user()
    name = request.form["name"]
    deadline = request.form.get("deadline") or None
    try:
        target = parse_number(request.form["target"])
        current = parse_number(request.form.get("current", "0"))
    except ValueError:
        flash("Суми в цілі мають бути числами!", "danger")
        return redirect(url_for("savings"))

    g = Goal(
        user_id=user.id,
        name=name,
        target=target,
        current=current,
        deadline=deadline,
    )
    db.session.add(g)
    db.session.commit()
    flash("Ціль додано!", "success")
    return redirect(url_for("savings"))

# Оновлення існуючої цілі
@app.route("/update_goal/<int:gid>", methods=["POST"])
@login_required
def update_goal(gid):
    user = current_user()
    g = Goal.query.get(gid)
    # Не даємо редагувати чужі цілі
    if not g or g.user_id != user.id:
        flash("Ціль не знайдено.", "danger")
        return redirect(url_for("savings"))

    name = request.form.get("name", g.name)
    deadline = request.form.get("deadline") or None
    try:
        target = parse_number(request.form.get("target", g.target))
        current = parse_number(request.form.get("current", g.current))
    except ValueError:
        flash("Суми в цілі мають бути числами!", "danger")
        return redirect(url_for("savings"))

    g.name = name
    g.target = target
    g.current = current
    g.deadline = deadline
    db.session.commit()
    flash("Ціль оновлено!", "success")
    return redirect(url_for("savings"))

# Видалення цілі
@app.route("/delete_goal/<int:gid>", methods=["POST"])
@login_required
def delete_goal(gid):
    user = current_user()
    g = Goal.query.get(gid)
    if g and g.user_id == user.id:
        db.session.delete(g)
        db.session.commit()
        flash("Ціль видалено.", "info")
    else:
        flash("Не вдалося видалити ціль.", "danger")
    return redirect(url_for("savings"))


# ------------------ Перевірка БД ------------------

# Швидка перевірка, що SQLite працює
@app.route("/check_db")
def check_db():
    try:
        with db.engine.connect() as conn:
            conn.execute(text("SELECT 1"))
        return "SQLite: OK"
    except Exception as e:
        return f"DB error: {e}", 500


# ------------------ Точка входу ------------------

if __name__ == "__main__":
    app.run(debug=True)
