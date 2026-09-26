from flask_wtf import FlaskForm
from flask_wtf.file import FileField, FileAllowed
from wtforms import StringField, PasswordField, SubmitField, BooleanField, FloatField, SelectField
from wtforms.validators import DataRequired, Email, Length, EqualTo, NumberRange


class RegistrationForm(FlaskForm):
    username = StringField('Username', validators=[DataRequired(), Length(min=2, max=20)])
    email = StringField('Email', validators=[DataRequired(), Email()])
    password = PasswordField('Password', validators=[DataRequired(), Length(min=6)])
    confirm_password = PasswordField('Confirm Password',
                                     validators=[DataRequired(), EqualTo('password')])
    accept_terms = BooleanField(
        'I agree to the Bank Buddy Terms & Conditions',
        validators=[DataRequired(message="You must accept the Terms & Conditions to register.")]
    )
    data_consent = BooleanField(
        'I consent to Bank Buddy processing my financial data to provide personalised guidance. '
        'I understand my data is stored securely, is never used to train the AI, and I can delete it at any time.',
        validators=[DataRequired(message="You must give data consent to register.")]
    )
    submit = SubmitField('Sign Up')


class LoginForm(FlaskForm):
    email = StringField('Email', validators=[DataRequired(), Email()])
    password = PasswordField('Password', validators=[DataRequired()])
    remember = BooleanField('Remember Me')
    submit = SubmitField('Login')


class AgentInteractionForm(FlaskForm):
    user_query = StringField('Your Question')
    document = FileField('Upload Document', validators=[
        FileAllowed(['pdf', 'png', 'jpg', 'jpeg', 'csv', 'txt', 'doc', 'docx'],
                    'Only PDF, images, CSV or text files allowed!')
    ])
    submit = SubmitField('Send')


class SavingsGoalForm(FlaskForm):
    name = StringField('Goal name', validators=[DataRequired(), Length(max=120)])
    target_amount = FloatField('Target amount (R)',
                               validators=[DataRequired(), NumberRange(min=1)])
    target_date = StringField('Target date (optional)')
    submit = SubmitField('Save Goal')


class BudgetForm(FlaskForm):
    category = SelectField('Category', choices=[
        ('Groceries', 'Groceries'),
        ('Transport', 'Transport'),
        ('Entertainment', 'Entertainment'),
        ('Rent', 'Rent'),
        ('Utilities', 'Utilities'),
        ('Other', 'Other'),
    ], validators=[DataRequired()])
    monthly_limit = FloatField('Monthly limit (R)',
                               validators=[DataRequired(), NumberRange(min=1)])
    submit = SubmitField('Save Budget')