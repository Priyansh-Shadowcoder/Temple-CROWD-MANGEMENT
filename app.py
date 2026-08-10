from flask import Flask, render_template, request, redirect, url_for, session, flash
from flask_sqlalchemy import SQLAlchemy
from werkzeug.security import generate_password_hash, check_password_hash
import pandas as pd
from sklearn.ensemble import RandomForestRegressor
import random
from datetime import datetime, timedelta

app = Flask(__name__)
app.secret_key = 'super_secret_temple_key'
app.config['SQLALCHEMY_DATABASE_URI'] = 'sqlite:///temple.db'
app.config['SQLALCHEMY_TRACK_MODIFICATIONS'] = False
db = SQLAlchemy(app)

class User(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    role = db.Column(db.String(20), nullable=False)
    name = db.Column(db.String(100), nullable=False)
    email = db.Column(db.String(100), unique=True, nullable=False)
    password = db.Column(db.String(200), nullable=False)

class Pass(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    user_id = db.Column(db.Integer, db.ForeignKey('user.id'), nullable=False)
    date = db.Column(db.String(20), nullable=False)
    member_name = db.Column(db.String(100), nullable=False)
    entry_gate = db.Column(db.Integer, nullable=False)
    exit_gate = db.Column(db.Integer, nullable=False)

class DailyStats(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    date = db.Column(db.String(20), unique=True, nullable=False)
    total_capacity = db.Column(db.Integer, default=5000)

ml_model = RandomForestRegressor(n_estimators=50, random_state=42)

def train_model():
    data = []
    for _ in range(300):
        is_weekend = random.choice([0, 1])
        is_festival = random.choice([0, 1])
        base_crowd = 1000
        crowd = base_crowd + (is_weekend * 1500) + (is_festival * 3000) + random.randint(-200, 200)
        data.append([is_weekend, is_festival, crowd])
    
    df = pd.DataFrame(data, columns=['is_weekend', 'is_festival', 'crowd'])
    X = df[['is_weekend', 'is_festival']]
    y = df['crowd']
    ml_model.fit(X, y)

def predict_crowd(date_str):
    date_obj = datetime.strptime(date_str, '%Y-%m-%d')
    is_weekend = 1 if date_obj.weekday() >= 5 else 0
    is_festival = 1 if date_obj.day % 10 == 0 else 0
    prediction = ml_model.predict([[is_weekend, is_festival]])
    return int(prediction[0])

def assign_gates(date_str):
    passes = Pass.query.filter_by(date=date_str).all()
    entry_loads = {1: 0, 2: 0, 3: 0}
    exit_loads = {1: 0, 2: 0, 3: 0}
    
    for p in passes:
        entry_loads[p.entry_gate] += 1
        exit_loads[p.exit_gate] += 1
        
    best_entry = min(entry_loads, key=entry_loads.get)
    best_exit = min(exit_loads, key=exit_loads.get)
    
    return best_entry, best_exit

@app.route('/')
def index():
    if 'user_id' in session:
        return redirect(url_for('admin_dashboard' if session['role'] == 'admin' else 'pilgrim_dashboard'))
    return render_template('login.html')

@app.route('/login', methods=['POST'])
def login():
    email = request.form['email']
    password = request.form['password']
    
    # Strictly filter for pilgrims only
    user = User.query.filter_by(email=email, role='pilgrim').first()
    
    if user and check_password_hash(user.password, password):
        session['user_id'] = user.id
        session['role'] = user.role
        return redirect(url_for('pilgrim_dashboard'))
        
    flash("Invalid devotee credentials or account does not exist.")
    return redirect(url_for('index'))

@app.route('/admin_login', methods=['GET', 'POST'])
def admin_login():
    if request.method == 'GET':
        if 'user_id' in session and session.get('role') == 'admin':
            return redirect(url_for('admin_dashboard'))
        return render_template('admin_login.html')

    email = request.form['email']
    password = request.form['password']
    
    # Strictly filter for admins only
    user = User.query.filter_by(email=email, role='admin').first()

    if user and check_password_hash(user.password, password):
        session['user_id'] = user.id
        session['role'] = user.role
        return redirect(url_for('admin_dashboard'))
        
    flash("Access Denied: Invalid administrator credentials.")
    return redirect(url_for('admin_login'))

@app.route('/signup', methods=['GET', 'POST'])
def signup():
    if request.method == 'GET':
        return render_template('signup.html')
        
    name = request.form['name']
    email = request.form['email']
    password = generate_password_hash(request.form['password'])
    role = request.form['role']
    
    # Check if user already exists
    existing_user = User.query.filter_by(email=email).first()
    if existing_user:
        flash("Email already registered. Please login.")
        return redirect(url_for('index'))
        
    new_user = User(name=name, email=email, password=password, role=role)
    db.session.add(new_user)
    db.session.commit()
    
    flash("Account successfully created! Please login.")
    return redirect(url_for('index'))

@app.route('/logout')
def logout():
    session.clear()
    return redirect(url_for('index'))

@app.route('/pilgrim/dashboard')
def pilgrim_dashboard():
    if session.get('role') != 'pilgrim': return redirect(url_for('index'))
    
    dates = [(datetime.now() + timedelta(days=i)).strftime('%Y-%m-%d') for i in range(7)]
    predictions = [predict_crowd(d) for d in dates]
    user_passes = Pass.query.filter_by(user_id=session['user_id']).all()
    
    return render_template('pilgrim_dashboard.html', dates=dates, predictions=predictions, user_passes=user_passes)

@app.route('/pilgrim/book', methods=['POST'])
def book_pass():
    if session.get('role') != 'pilgrim': return redirect(url_for('index'))
    
    date = request.form['date']
    members = request.form.getlist('members[]')
    
    entry_gate, exit_gate = assign_gates(date)
    
    for member in members:
        if member.strip():
            new_pass = Pass(user_id=session['user_id'], date=date, member_name=member, 
                            entry_gate=entry_gate, exit_gate=exit_gate)
            db.session.add(new_pass)
    
    db.session.commit()
    flash(f"Passes booked successfully! Assigned Entry Gate: {entry_gate}, Exit Gate: {exit_gate}")
    return redirect(url_for('pilgrim_dashboard'))

@app.route('/admin/dashboard')
def admin_dashboard():
    if session.get('role') != 'admin': return redirect(url_for('index'))
    
    # Allows admin to check future/past dates. Defaults to today.
    selected_date = request.args.get('date', datetime.now().strftime('%Y-%m-%d'))
    passes_selected = Pass.query.filter_by(date=selected_date).all()
    
    entry_heat = {1: 0, 2: 0, 3: 0}
    exit_heat = {1: 0, 2: 0, 3: 0}
    for p in passes_selected:
        entry_heat[p.entry_gate] += 1
        exit_heat[p.exit_gate] += 1
        
    stats = DailyStats.query.filter_by(date=selected_date).first()
    capacity = stats.total_capacity if stats else 5000
        
    return render_template('admin_dashboard.html', entry_heat=entry_heat, exit_heat=exit_heat, capacity=capacity, passes=passes_selected, selected_date=selected_date)

@app.route('/admin/gate/<type>/<int:num>')
def gate_view(type, num):
    if session.get('role') != 'admin': return redirect(url_for('index'))
    
    # Retrieve the date from the query string to keep context
    selected_date = request.args.get('date', datetime.now().strftime('%Y-%m-%d'))
    
    if type == 'entry':
        passes = Pass.query.filter_by(date=selected_date, entry_gate=num).all()
    else:
        passes = Pass.query.filter_by(date=selected_date, exit_gate=num).all()
        
    return render_template('gate_view.html', passes=passes, type=type, num=num, selected_date=selected_date)

# 1. Initialize the database and model outside the main block
with app.app_context():
    db.create_all()
    train_model()

# 2. Keep the run command inside the main block for local testing
if __name__ == '__main__':
    app.run(debug=True)
