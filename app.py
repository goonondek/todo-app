import os
from flask import Flask, render_template, redirect, url_for, flash, request, jsonify
from flask_login import LoginManager, login_user, logout_user, login_required, current_user
from werkzeug.security import generate_password_hash, check_password_hash
from models import db, User, Task
from forms import RegistrationForm, LoginForm, TaskForm, UpdateProfileForm, ChangePasswordForm
from datetime import datetime, timedelta

app = Flask(__name__)
app.config['SECRET_KEY'] = os.environ.get('SECRET_KEY', 'dev-secret-key-change-in-production')
app.config['SQLALCHEMY_DATABASE_URI'] = 'sqlite:///todo.db'
app.config['SQLALCHEMY_TRACK_MODIFICATIONS'] = False

# Session Configuration
app.config['SESSION_COOKIE_SECURE'] = True  # Only send over HTTPS in production
app.config['SESSION_COOKIE_HTTPONLY'] = True  # Prevent JavaScript access
app.config['SESSION_COOKIE_SAMESITE'] = 'Lax'  # CSRF protection
app.config['PERMANENT_SESSION_LIFETIME'] = timedelta(days=7)  # Session expires after 7 days

db.init_app(app)
login_manager = LoginManager(app)
login_manager.login_view = 'login'

@login_manager.user_loader
def load_user(user_id):
    return User.query.get(int(user_id))

# Create tables / perform simple migrations
with app.app_context():
    # basic schema creation
    db.create_all()
    # perform small, safe sqlite migrations: add missing columns with defaults
    from sqlalchemy import inspect, text
    engine = db.get_engine()
    insp = inspect(engine)

    def _add_column_safe(conn, table_name: str, column_def: str):
        try:
            conn.execute(text(f'ALTER TABLE {table_name} ADD COLUMN {column_def}'))
        except Exception:
            # If ALTER fails (e.g. column exists or unsupported), ignore and continue
            pass

    # Only attempt migration when tables exist
    with engine.begin() as conn:
        tables = insp.get_table_names()
        if 'user' in tables:
            cols = [c['name'] for c in insp.get_columns('user')]
            if 'created_at' not in cols:
                # add column with CURRENT_TIMESTAMP default so existing rows get a value
                _add_column_safe(conn, 'user', "created_at DATETIME DEFAULT (CURRENT_TIMESTAMP)")

        if 'task' in tables:
            cols = [c['name'] for c in insp.get_columns('task')]
            if 'created_at' not in cols:
                _add_column_safe(conn, 'task', "created_at DATETIME DEFAULT (CURRENT_TIMESTAMP)")
            if 'updated_at' not in cols:
                _add_column_safe(conn, 'task', "updated_at DATETIME DEFAULT (CURRENT_TIMESTAMP)")


@app.route('/')
def index():
    if current_user.is_authenticated:
        tasks = Task.query.filter_by(user_id=current_user.id).all()
        return render_template('index.html', tasks=tasks)
    return redirect(url_for('login'))

@app.route('/register', methods=['GET', 'POST'])
def register():
    if current_user.is_authenticated:
        return redirect(url_for('index'))
    form = RegistrationForm()
    if form.validate_on_submit():
        hashed_pw = generate_password_hash(form.password.data)
        user = User(username=form.username.data, password_hash=hashed_pw)
        db.session.add(user)
        db.session.commit()
        flash('Account created! You can now log in.', 'success')
        return redirect(url_for('login'))
    return render_template('register.html', form=form)

@app.route('/login', methods=['GET', 'POST'])
def login():
    if current_user.is_authenticated:
        return redirect(url_for('index'))
    form = LoginForm()
    if form.validate_on_submit():
        user = User.query.filter_by(username=form.username.data).first()
        if user and check_password_hash(user.password_hash, form.password.data):
            login_user(user, remember=form.remember_me.data)
            return redirect(url_for('index'))
        else:
            flash('Login unsuccessful. Check username and password.', 'danger')
    return render_template('login.html', form=form)

@app.route('/logout')
@login_required
def logout():
    logout_user()
    return redirect(url_for('login'))

@app.route('/task/new', methods=['GET', 'POST'])
@login_required
def new_task():
    form = TaskForm()
    if form.validate_on_submit():
        task = Task(
            title=form.title.data,
            description=form.description.data,
            due_date=form.due_date.data,
            priority=form.priority.data,
            user_id=current_user.id
        )
        db.session.add(task)
        db.session.commit()
        flash('Task added!', 'success')
        return redirect(url_for('index'))
    return render_template('edit_task.html', form=form, legend='New Task')

@app.route('/task/<int:task_id>/edit', methods=['GET', 'POST'])
@login_required
def edit_task(task_id):
    task = Task.query.get_or_404(task_id)
    if task.user_id != current_user.id:
        flash('You do not have permission to edit this task.', 'danger')
        return redirect(url_for('index'))
    form = TaskForm(obj=task)  # pre-populate with existing task
    if form.validate_on_submit():
        task.title = form.title.data
        task.description = form.description.data
        task.due_date = form.due_date.data
        task.priority = form.priority.data
        db.session.commit()
        flash('Task updated!', 'success')
        return redirect(url_for('index'))
    return render_template('edit_task.html', form=form, legend='Edit Task')

@app.route('/task/<int:task_id>/delete', methods=['POST'])
@login_required
def delete_task(task_id):
    task = Task.query.get_or_404(task_id)
    if task.user_id != current_user.id:
        return jsonify({'error': 'Unauthorized'}), 403
    db.session.delete(task)
    db.session.commit()
    flash('Task deleted.', 'info')
    return redirect(url_for('index'))

@app.route('/task/<int:task_id>/toggle', methods=['POST'])
@login_required
def toggle_task(task_id):
    task = Task.query.get_or_404(task_id)
    if task.user_id != current_user.id:
        return jsonify({'error': 'Unauthorized'}), 403
    task.completed = not task.completed
    db.session.commit()
    return jsonify({'completed': task.completed})

@app.route('/profile', methods=['GET', 'POST'])
@login_required
def profile():
    update_form = UpdateProfileForm()
    password_form = ChangePasswordForm()
    
    # Handle username update
    if update_form.validate_on_submit() and 'submit' in request.form and update_form.submit.data:
        if update_form.username.data != current_user.username:
            # Check if username is taken
            existing_user = User.query.filter_by(username=update_form.username.data).first()
            if existing_user:
                flash('Username already taken.', 'danger')
            else:
                current_user.username = update_form.username.data
                db.session.commit()
                flash('Your username has been updated!', 'success')
        return redirect(url_for('profile'))
    
    # Handle password change
    if password_form.validate_on_submit() and 'submit' in request.form and password_form.submit.data:
        if check_password_hash(current_user.password_hash, password_form.current_password.data):
            current_user.password_hash = generate_password_hash(password_form.new_password.data)
            db.session.commit()
            flash('Your password has been updated!', 'success')
        else:
            flash('Current password is incorrect.', 'danger')
        return redirect(url_for('profile'))
    
    # Pre-populate username field
    update_form.username.data = current_user.username
    
    return render_template('profile.html', 
                         update_form=update_form, 
                         password_form=password_form)

if __name__ == '__main__':
    app.run(debug=True)