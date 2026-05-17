from flask import Blueprint, render_template, flash, redirect, url_for, request, jsonify
from flask_login import login_required, current_user
from datetime import date, timedelta
from collections import defaultdict
from decimal import Decimal
import math

# ----------------------------------------------------------------------
# Create Blueprint
# ----------------------------------------------------------------------
nutrition_bp = Blueprint('nutrition', __name__,
                         template_folder='templates',
                         static_folder='static',
                         static_url_path='/static/nutrition')

# ======================================================================
# RDA reference tables (NIH values for adults 19–50 years)
# ======================================================================
RDA_VITAMINS = {
    'male': {
        'vitamin_a': 900,      # mcg RAE
        'vitamin_b12': 2.4,    # mcg
        'vitamin_c': 90,       # mg
        'vitamin_d': 15,       # mcg
        'vitamin_e': 15,       # mg
        'vitamin_k': 120,      # mcg
    },
    'female': {
        'vitamin_a': 700,
        'vitamin_b12': 2.4,
        'vitamin_c': 75,
        'vitamin_d': 15,
        'vitamin_e': 15,
        'vitamin_k': 90,
    }
}

RDA_MINERALS = {
    'male': {
        'iron': 8,             # mg
        'zinc': 11,            # mg
        'calcium': 1000,       # mg
        'magnesium': 400,      # mg
        'potassium': 3400,     # mg
        'iodine': 150,         # mcg
    },
    'female': {
        'iron': 18,
        'zinc': 8,
        'calcium': 1000,
        'magnesium': 310,
        'potassium': 2600,
        'iodine': 150,
    }
}

# Food suggestions (filtered by diet type later)
FOOD_SOURCES = {
    # Macronutrients
    'calories': ['Nuts', 'Seeds', 'Avocado', 'Whole grains', 'Dried fruits', 'Olive oil'],
    'carbohydrates': ['Whole grains', 'Fruits', 'Vegetables', 'Legumes'],
    'protein': ['Legumes', 'Nuts', 'Soy', 'Dairy', 'Eggs', 'Tofu'],
    'fats': ['Nuts', 'Seeds', 'Oils', 'Avocado', 'Fatty fish'],
    'fiber': ['Oats', 'Beans', 'Berries', 'Broccoli', 'Lentils'],
    'water': ['Water', 'Herbal tea', 'Cucumber', 'Watermelon', 'Celery'],

    # Vitamins
    'vitamin_a': ['Carrots', 'Sweet potatoes', 'Spinach', 'Kale', 'Pumpkin'],
    'vitamin_b12': ['Fortified foods', 'Nutritional yeast', 'Supplements', 'Dairy'],
    'vitamin_c': ['Citrus fruits', 'Bell peppers', 'Strawberries', 'Kiwi', 'Broccoli'],
    'vitamin_d': ['Fortified foods', 'Mushrooms', 'Sunlight', 'Fatty fish'],
    'vitamin_e': ['Nuts', 'Seeds', 'Spinach', 'Avocado', 'Sunflower oil'],
    'vitamin_k': ['Leafy greens', 'Broccoli', 'Brussels sprouts', 'Cabbage', 'Prunes'],

    # Minerals
    'iron': ['Spinach', 'Lentils', 'Jaggery', 'Fortified cereals', 'Pumpkin seeds'],
    'zinc': ['Pumpkin seeds', 'Chickpeas', 'Cashews', 'Quinoa', 'Oysters'],
    'calcium': ['Dairy', 'Sesame seeds', 'Ragi', 'Fortified plant milk', 'Almonds'],
    'magnesium': ['Almonds', 'Bananas', 'Dark chocolate', 'Spinach', 'Pumpkin seeds'],
    'potassium': ['Bananas', 'Potatoes', 'Avocado', 'Spinach', 'Beans'],
    'iodine': ['Iodized salt', 'Seaweed', 'Fish', 'Cranberries', 'Yogurt'],
}

# ----------------------------------------------------------------------
# Helper: convert DB row tuple to dict
# ----------------------------------------------------------------------
def _row_to_dict(cursor, row):
    if row is None:
        return None
    columns = [col[0] for col in cursor.description]
    return dict(zip(columns, row))

# ----------------------------------------------------------------------
# Helper: get user profile with Decimal -> float conversion
# ----------------------------------------------------------------------
def get_user_profile(user_id):
    from app import get_cursor
    with get_cursor() as cursor:
        cursor.execute("SELECT * FROM user_profiles WHERE user_id = %s", (user_id,))
        row = cursor.fetchone()
        if row:
            if not isinstance(row, dict):
                row = _row_to_dict(cursor, row)
            # Convert Decimal to float
            for key, value in row.items():
                if isinstance(value, Decimal):
                    row[key] = float(value)
        return row

# ----------------------------------------------------------------------
# Helper: compute personalized daily targets (Mifflin‑St Jeor)
# ----------------------------------------------------------------------
def compute_daily_targets(profile):
    if profile['gender'] == 'male':
        bmr = 10 * profile['weight_kg'] + 6.25 * profile['height_cm'] - 5 * profile['age'] + 5
    else:
        bmr = 10 * profile['weight_kg'] + 6.25 * profile['height_cm'] - 5 * profile['age'] - 161

    activity_factors = {
        'sedentary': 1.2,
        'light': 1.375,
        'moderate': 1.55,
        'active': 1.725,
        'very_active': 1.9
    }
    tdee = bmr * activity_factors.get(profile['activity_level'], 1.2)

    if profile['goal'] == 'lose':
        calories = tdee - 500
    elif profile['goal'] == 'gain':
        calories = tdee + 500
    else:
        calories = tdee

    calories = max(calories, 1200)  # safety floor

    protein_cal = calories * 0.30
    fat_cal = calories * 0.30
    carbs_cal = calories * 0.40

    protein_g = protein_cal / 4
    fat_g = fat_cal / 9
    carbs_g = carbs_cal / 4

    fiber_g = 25
    water_ml = profile['weight_kg'] * 35

    gender = profile['gender'] if profile['gender'] in ['male','female'] else 'male'
    vitamins = RDA_VITAMINS[gender]
    minerals = RDA_MINERALS[gender]

    targets = {
        'calories': round(calories),
        'protein_grams': round(protein_g, 1),
        'carbs_grams': round(carbs_g, 1),
        'fat_grams': round(fat_g, 1),
        'fiber_grams': fiber_g,
        'water_ml': round(water_ml, 1),
        **vitamins,
        **minerals
    }
    return targets

# ----------------------------------------------------------------------
# Helper: get or create daily summary (aggregates from meal_logs)
# ----------------------------------------------------------------------
def get_daily_summary(user_id, target_date):
    from app import get_cursor, load_foods_json

    # 1. Try cached daily summary
    with get_cursor() as cursor:
        cursor.execute("SELECT * FROM daily_summaries WHERE user_id = %s AND date = %s",
                       (user_id, target_date))
        row = cursor.fetchone()
        if row:
            if isinstance(row, dict):
                for key, value in row.items():
                    if isinstance(value, Decimal):
                        row[key] = float(value)
                return row
            else:
                row_dict = _row_to_dict(cursor, row)
                for key, value in row_dict.items():
                    if isinstance(value, Decimal):
                        row_dict[key] = float(value)
                return row_dict

    # 2. Not cached – compute from meal_logs
    foods = load_foods_json()
    totals = defaultdict(float)

    with get_cursor() as cursor:
        cursor.execute("""
            SELECT food_name, weight, calories, protein, carbs, fats
            FROM meal_logs
            WHERE user_id = %s AND date = %s
        """, (user_id, target_date))
        rows = cursor.fetchall()

    for row in rows:
        if isinstance(row, dict):
            food_name = row['food_name'].strip().lower()
            weight = float(row['weight'] or 0)
            stored_cal = float(row['calories'] or 0)
            stored_prot = float(row['protein'] or 0)
            stored_carbs = float(row['carbs'] or 0)
            stored_fat = float(row['fats'] or 0)
        else:
            # fallback for old rows (should not happen)
            food_name = row[0].strip().lower()
            weight = float(row[1] or 0)
            stored_cal = float(row[2] or 0)
            stored_prot = float(row[3] or 0)
            stored_carbs = float(row[4] or 0)
            stored_fat = float(row[5] or 0)

        # Prefer food_data if available (gives full nutrient breakdown)
        food_data = foods.get(food_name)
        if food_data:
            factor = weight / 100.0 if weight > 0 else 1.0
            macros = food_data.get('macronutrients', {})
            # Add all macros (including fiber and water)
            totals['total_calories'] += macros.get('calories', 0) * factor
            totals['total_protein'] += macros.get('protein', 0) * factor
            totals['total_carbs'] += macros.get('carbohydrate', 0) * factor
            totals['total_fat'] += macros.get('total_fats', 0) * factor
            totals['total_fiber'] += macros.get('fiber', 0) * factor
            totals['total_water'] += macros.get('water', 0) * factor

            # Vitamins – support both 'vitamin_b12' and 'vitamin_b' keys
            vitamins = food_data.get('vitamins', {})
            b12 = vitamins.get('vitamin_b12')
            if b12 is None:
                b12 = vitamins.get('vitamin_b', 0)  # fallback for older JSON
            totals['total_vitamin_a'] += vitamins.get('vitamin_a', 0) * factor
            totals['total_vitamin_b12'] += b12 * factor
            totals['total_vitamin_c'] += vitamins.get('vitamin_c', 0) * factor
            totals['total_vitamin_d'] += vitamins.get('vitamin_d', 0) * factor
            totals['total_vitamin_e'] += vitamins.get('vitamin_e', 0) * factor
            totals['total_vitamin_k'] += vitamins.get('vitamin_k', 0) * factor

            # Minerals
            minerals = food_data.get('minerals_and_trace', {})
            totals['total_iron'] += minerals.get('iron', 0) * factor
            totals['total_zinc'] += minerals.get('zinc', 0) * factor
            totals['total_calcium'] += minerals.get('calcium', 0) * factor
            totals['total_magnesium'] += minerals.get('magnesium', 0) * factor
            totals['total_potassium'] += minerals.get('potassium', 0) * factor
            totals['total_iodine'] += minerals.get('iodine', 0) * factor

        else:
            # No food data – fall back to stored values (only macros)
            totals['total_calories'] += stored_cal
            totals['total_protein'] += stored_prot
            totals['total_carbs'] += stored_carbs
            totals['total_fat'] += stored_fat
            # fiber, water, vitamins remain 0 (or you could skip)

    # Build summary dict with all nutrients, zero for missing
    summary = {
        'total_calories': totals.get('total_calories', 0),
        'total_protein': totals.get('total_protein', 0),
        'total_carbs': totals.get('total_carbs', 0),
        'total_fat': totals.get('total_fat', 0),
        'total_fiber': totals.get('total_fiber', 0),
        'total_water': totals.get('total_water', 0),
        'total_vitamin_a': totals.get('total_vitamin_a', 0),
        'total_vitamin_b12': totals.get('total_vitamin_b12', 0),
        'total_vitamin_c': totals.get('total_vitamin_c', 0),
        'total_vitamin_d': totals.get('total_vitamin_d', 0),
        'total_vitamin_e': totals.get('total_vitamin_e', 0),
        'total_vitamin_k': totals.get('total_vitamin_k', 0),
        'total_iron': totals.get('total_iron', 0),
        'total_zinc': totals.get('total_zinc', 0),
        'total_calcium': totals.get('total_calcium', 0),
        'total_magnesium': totals.get('total_magnesium', 0),
        'total_potassium': totals.get('total_potassium', 0),
        'total_iodine': totals.get('total_iodine', 0),
    }
    summary = {k: round(v, 2) for k, v in summary.items()}

    # 3. Store in daily_summaries for future
    columns = ', '.join(summary.keys())
    placeholders = ', '.join(['%s'] * len(summary))
    values = [user_id, target_date] + list(summary.values())
    with get_cursor() as cursor:
        cursor.execute(f"""
            INSERT INTO daily_summaries (user_id, date, {columns})
            VALUES (%s, %s, {placeholders})
            ON DUPLICATE KEY UPDATE
            {', '.join([f"{col}=VALUES({col})" for col in summary.keys()])}
        """, values)

    summary['user_id'] = user_id
    summary['date'] = target_date
    return summary

# ----------------------------------------------------------------------
# Helper: get last 7 days summaries
# ----------------------------------------------------------------------
def get_last_7_days_summaries(user_id):
    today = date.today()
    summaries = []
    for i in range(7):
        day = today - timedelta(days=i)
        summary = get_daily_summary(user_id, day)
        summaries.append(summary)
    return summaries

# ----------------------------------------------------------------------
# Helper: improvement trend for a nutrient
# ----------------------------------------------------------------------
def calculate_improvement(user_id, nutrient='total_protein'):
    today = date.today()
    recent_days = [(today - timedelta(days=i)) for i in range(1, 4)]
    previous_days = [(today - timedelta(days=i)) for i in range(4, 7)]

    def avg_intake(days):
        values = []
        for d in days:
            summary = get_daily_summary(user_id, d)
            values.append(summary.get(nutrient, 0))
        return sum(values) / len(values) if values else 0

    recent_avg = avg_intake(recent_days)
    previous_avg = avg_intake(previous_days)

    if previous_avg == 0:
        return 0
    improvement = ((recent_avg - previous_avg) / previous_avg) * 100
    return round(improvement, 1)

# ----------------------------------------------------------------------
# Helper: generate simple string suggestions (for API)
# ----------------------------------------------------------------------
def generate_suggestions(progress, diet_type='omnivore'):
    suggestions = []
    for nutrient, pct in progress.items():
        if pct < 60:
            sources = FOOD_SOURCES.get(nutrient, ['a varied diet'])
            if diet_type == 'vegan':
                sources = [s for s in sources if s not in ['Dairy', 'Fish']]
            elif diet_type == 'vegetarian':
                sources = [s for s in sources if s not in ['Fish']]
            suggestion = f"Low {nutrient.replace('_', ' ').title()}: Eat {', '.join(sources[:3])}."
            suggestions.append(suggestion)
    return suggestions

# ----------------------------------------------------------------------
# Helper: generate structured suggestions with percentages (for template)
# ----------------------------------------------------------------------
def generate_suggestions_structured(progress, diet_type='omnivore'):
    """Return list of dicts with nutrient, percentage, message for visual bars."""
    suggestions_data = []
    
    templates = {
        'calories': "📈 Increase your calorie intake by adding {sources} to your meals.",
        'protein': "💪 Boost your protein with foods like {sources}.",
        'carbohydrates': "🌾 Add healthy carbs such as {sources}.",
        'fats': "🥑 Include healthy fats from {sources}.",
        'fiber': "🌿 Increase fiber by eating {sources}.",
        'water': "💧 Stay hydrated – drink more water or enjoy {sources}.",
        'vitamin_a': "🥕 Get more Vitamin A from {sources}.",
        'vitamin_b12': "🧀 Boost Vitamin B12 with {sources}.",
        'vitamin_c': "🍊 Add Vitamin C with {sources}.",
        'vitamin_d': "☀️ Increase Vitamin D through {sources} (or sunlight).",
        'vitamin_e': "🌰 Get more Vitamin E from {sources}.",
        'vitamin_k': "🥬 Add Vitamin K with {sources}.",
        'iron': "🔋 Boost iron with {sources}.",
        'zinc': "🦪 Increase zinc by eating {sources}.",
        'calcium': "🦴 Get more calcium from {sources}.",
        'magnesium': "🌿 Add magnesium with {sources}.",
        'potassium': "🍌 Boost potassium with {sources}.",
        'iodine': "🧂 Increase iodine with {sources}.",
    }
    
    for nutrient, pct in progress.items():
        if pct < 60:
            sources = FOOD_SOURCES.get(nutrient, ['a varied diet'])
            
            if diet_type == 'vegan':
                forbidden = ['Dairy', 'Fish', 'Eggs', 'Oysters', 'Honey']
                sources = [s for s in sources if s not in forbidden]
            elif diet_type == 'vegetarian':
                forbidden = ['Fish', 'Oysters']
                sources = [s for s in sources if s not in forbidden]
            
            if not sources:
                sources = ['a variety of plant‑based foods']
            
            source_list = ', '.join(sources[:3])
            template = templates.get(nutrient, "Low {nutrient}: Eat {sources}.")
            message = template.format(nutrient=nutrient.replace('_', ' ').title(),
                                     sources=source_list)
            
            suggestions_data.append({
                'nutrient': nutrient,
                'percentage': pct,
                'message': message
            })
    
    return suggestions_data

# ----------------------------------------------------------------------
# Helper: get unit for display
# ----------------------------------------------------------------------
def get_unit(nutrient):
    units = {
        'carbohydrates': 'g', 'protein': 'g', 'fats': 'g', 'fiber': 'g', 'water': 'ml',
        'vitamin_a': 'mcg', 'vitamin_b12': 'mcg', 'vitamin_c': 'mg', 'vitamin_d': 'mcg',
        'vitamin_e': 'mg', 'vitamin_k': 'mcg',
        'iron': 'mg', 'zinc': 'mg', 'calcium': 'mg', 'magnesium': 'mg',
        'potassium': 'mg', 'iodine': 'mcg',
    }
    return units.get(nutrient, '')

# ======================================================================
# ROUTES
# ======================================================================

@nutrition_bp.route('/profile', methods=['GET', 'POST'])
@login_required
def profile():
    from app import get_cursor, mysql

    if request.method == 'POST':
        try:
            age = request.form['age']
            weight = request.form['weight']
            height = request.form['height']
            gender = request.form['gender']
            activity = request.form.get('activity_level', 'sedentary')
            diet = request.form.get('diet_type', 'omnivore')
            goal = request.form.get('goal', 'maintain')

            with get_cursor() as cursor:
                cursor.execute("SELECT id FROM user_profiles WHERE user_id = %s", (current_user.id,))
                existing = cursor.fetchone()
                if existing:
                    cursor.execute("""
                        UPDATE user_profiles
                        SET age=%s, weight_kg=%s, height_cm=%s, gender=%s,
                            activity_level=%s, diet_type=%s, goal=%s, updated_at=NOW()
                        WHERE user_id=%s
                    """, (age, weight, height, gender, activity, diet, goal, current_user.id))
                else:
                    cursor.execute("""
                        INSERT INTO user_profiles
                        (user_id, age, weight_kg, height_cm, gender, activity_level, diet_type, goal)
                        VALUES (%s, %s, %s, %s, %s, %s, %s, %s)
                    """, (current_user.id, age, weight, height, gender, activity, diet, goal))

            mysql.connection.commit()
            flash('Profile saved successfully!', 'success')
            return redirect(url_for('nutrition.dashboard'))
        except Exception as e:
            mysql.connection.rollback()
            flash(f'Error saving profile: {str(e)}', 'danger')

    profile = get_user_profile(current_user.id)
    return render_template('profile_form.html', profile=profile)


@nutrition_bp.route('/dashboard')
@login_required
def dashboard():
    if not current_user.is_premium:
        flash("This feature requires an active premium subscription.", "warning")
        return redirect(url_for('plans'))

    profile = get_user_profile(current_user.id)
    if not profile:
        flash("Please complete your profile first.", "info")
        return redirect(url_for('nutrition.profile'))

    today = date.today()
    targets = compute_daily_targets(profile)
    today_summary = get_daily_summary(current_user.id, today)

    # Build nutrient list for the template
    nutrient_list = [
        ('carbohydrates', targets['carbs_grams'], today_summary.get('total_carbs', 0)),
        ('protein', targets['protein_grams'], today_summary.get('total_protein', 0)),
        ('fats', targets['fat_grams'], today_summary.get('total_fat', 0)),
        ('fiber', targets['fiber_grams'], today_summary.get('total_fiber', 0)),
        ('water', targets['water_ml'], today_summary.get('total_water', 0)),
        ('vitamin_a', targets['vitamin_a'], today_summary.get('total_vitamin_a', 0)),
        ('vitamin_b12', targets['vitamin_b12'], today_summary.get('total_vitamin_b12', 0)),
        ('vitamin_c', targets['vitamin_c'], today_summary.get('total_vitamin_c', 0)),
        ('vitamin_d', targets['vitamin_d'], today_summary.get('total_vitamin_d', 0)),
        ('vitamin_e', targets['vitamin_e'], today_summary.get('total_vitamin_e', 0)),
        ('vitamin_k', targets['vitamin_k'], today_summary.get('total_vitamin_k', 0)),
        ('iron', targets['iron'], today_summary.get('total_iron', 0)),
        ('zinc', targets['zinc'], today_summary.get('total_zinc', 0)),
        ('calcium', targets['calcium'], today_summary.get('total_calcium', 0)),
        ('magnesium', targets['magnesium'], today_summary.get('total_magnesium', 0)),
        ('potassium', targets['potassium'], today_summary.get('total_potassium', 0)),
        ('iodine', targets['iodine'], today_summary.get('total_iodine', 0)),
    ]

    categories = {
        'Macronutrients': ['carbohydrates', 'protein', 'fats', 'fiber', 'water'],
        'Vitamins': ['vitamin_a', 'vitamin_b12', 'vitamin_c', 'vitamin_d', 'vitamin_e', 'vitamin_k'],
        'Minerals': ['iron', 'zinc', 'calcium', 'magnesium', 'potassium', 'iodine'],
    }

    data = {}
    all_progress = {}
    for cat_name, nutrients in categories.items():
        cat_data = []
        for nutrient in nutrients:
            entry = next((item for item in nutrient_list if item[0] == nutrient), None)
            if not entry:
                continue
            required = entry[1]
            consumed = entry[2]
            percentage = (consumed / required * 100) if required > 0 else 0
            percentage = min(percentage, 100)
            cat_data.append({
                'name': nutrient.replace('_', ' ').title(),
                'required': required,
                'consumed': round(consumed, 1),
                'percentage': round(percentage, 1),
                'unit': get_unit(nutrient)
            })
            all_progress[nutrient] = percentage
        data[cat_name] = cat_data

    week_summaries = get_last_7_days_summaries(current_user.id)
    week_data = [{
        'date': s['date'].isoformat() if hasattr(s['date'], 'isoformat') else str(s['date']),
        'calories': s.get('total_calories', 0),
        'protein': s.get('total_protein', 0),
    } for s in week_summaries]

    improvement = calculate_improvement(current_user.id, nutrient='total_protein')
    suggestions_data = generate_suggestions_structured(all_progress, profile['diet_type'])

    return render_template(
        'nutrition_dashboard.html',
        data=data,
        suggestions_data=suggestions_data,
        today=today,
        profile=profile,
        targets=targets,
        week_data=week_data,
        improvement=improvement,
        today_intake=today_summary
    )


# ======================================================================
# API ENDPOINTS for planned meals (accept/deny)
# ======================================================================

@nutrition_bp.route('/planned-meals', methods=['GET'])
@login_required
def planned_meals():
    """Return all planned meals for today (status='planned')."""
    from app import get_cursor
    with get_cursor() as cursor:
        cursor.execute("""
            SELECT id, meal_type, food_name, weight, calories, protein, carbs, fats
            FROM meal_plans
            WHERE user_id = %s AND date = CURDATE() AND status = 'planned'
            ORDER BY FIELD(meal_type, 'Breakfast','Lunch','Dinner','Snacks')
        """, (current_user.id,))
        rows = cursor.fetchall()
    return jsonify(rows)


@nutrition_bp.route('/accept-meal/<int:plan_id>', methods=['POST'])
@login_required
def accept_meal(plan_id):
    """Accept a planned meal: insert into meal_logs and mark as eaten."""
    from app import get_cursor, mysql
    try:
        with get_cursor() as cursor:
            # Fetch the planned meal
            cursor.execute("""
                SELECT user_id, date, meal_type, food_name, weight, calories, protein, carbs, fats
                FROM meal_plans
                WHERE id = %s AND status = 'planned'
            """, (plan_id,))
            plan = cursor.fetchone()
            if not plan:
                return jsonify({'error': 'Planned meal not found or already processed'}), 404
            if plan['user_id'] != current_user.id:
                return jsonify({'error': 'Unauthorized'}), 403

            # Insert into meal_logs
            cursor.execute("""
                INSERT INTO meal_logs
                (user_id, date, meal_type, food_name, weight, calories, protein, carbs, fats)
                VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s)
            """, (
                plan['user_id'],
                plan['date'],
                plan['meal_type'],
                plan['food_name'],
                plan['weight'],
                plan['calories'],
                plan['protein'],
                plan['carbs'],
                plan['fats']
            ))

            # Mark plan as eaten
            cursor.execute("UPDATE meal_plans SET status = 'eaten' WHERE id = %s", (plan_id,))

            # Invalidate daily summary for that date (so it will be recomputed)
            cursor.execute("DELETE FROM daily_summaries WHERE user_id = %s AND date = %s",
                           (current_user.id, plan['date']))

        mysql.connection.commit()
        return jsonify({'status': 'success', 'message': 'Meal accepted'}), 200
    except Exception as e:
        mysql.connection.rollback()
        return jsonify({'error': str(e)}), 500


@nutrition_bp.route('/deny-meal/<int:plan_id>', methods=['POST'])
@login_required
def deny_meal(plan_id):
    """Deny a planned meal: delete it."""
    from app import get_cursor, mysql
    try:
        with get_cursor() as cursor:
            cursor.execute("DELETE FROM meal_plans WHERE id = %s AND user_id = %s AND status = 'planned'",
                           (plan_id, current_user.id))
            if cursor.rowcount == 0:
                return jsonify({'error': 'Not found or already processed'}), 404
        mysql.connection.commit()
        return jsonify({'status': 'success', 'message': 'Meal denied'}), 200
    except Exception as e:
        mysql.connection.rollback()
        return jsonify({'error': str(e)}), 500


# ======================================================================
# OPTIONAL: List eaten foods today (for dashboard display)
# ======================================================================
@nutrition_bp.route('/today-foods', methods=['GET'])
@login_required
def today_foods():
    """Return all foods logged today (eaten)."""
    from app import get_cursor
    with get_cursor() as cursor:
        cursor.execute("""
            SELECT id, food_name, weight, calories, protein, carbs, fats, meal_type
            FROM meal_logs
            WHERE user_id = %s AND date = CURDATE()
            ORDER BY created_at DESC
        """, (current_user.id,))
        rows = cursor.fetchall()
    return jsonify(rows)


@nutrition_bp.route('/delete-food/<int:log_id>', methods=['DELETE'])
@login_required
def delete_food(log_id):
    """Delete a specific eaten food log."""
    from app import get_cursor, mysql
    try:
        with get_cursor() as cursor:
            cursor.execute("DELETE FROM meal_logs WHERE id = %s AND user_id = %s", (log_id, current_user.id))
            if cursor.rowcount == 0:
                return jsonify({'error': 'Not found'}), 404
            # Invalidate daily summary for today
            cursor.execute("DELETE FROM daily_summaries WHERE user_id = %s AND date = CURDATE()",
                           (current_user.id,))
        mysql.connection.commit()
        return jsonify({'status': 'success'}), 200
    except Exception as e:
        mysql.connection.rollback()
        return jsonify({'error': str(e)}), 500


# ======================================================================
# API endpoint for AJAX dashboard updates
# ======================================================================
@nutrition_bp.route('/api/dashboard')
@login_required
def api_dashboard():
    profile = get_user_profile(current_user.id)
    if not profile:
        return jsonify({'error': 'Profile missing'}), 404

    today = date.today()
    targets = compute_daily_targets(profile)
    today_summary = get_daily_summary(current_user.id, today)
    week_summaries = get_last_7_days_summaries(current_user.id)
    improvement = calculate_improvement(current_user.id)

    progress = {}
    for nutrient, required, consumed in [
        ('calories', targets['calories'], today_summary.get('total_calories', 0)),
        ('protein', targets['protein_grams'], today_summary.get('total_protein', 0)),
    ]:
        pct = (consumed / required * 100) if required > 0 else 0
        progress[nutrient] = min(pct, 100)

    suggestions = generate_suggestions(progress, profile['diet_type'])

    return jsonify({
        'profile': {
            'age': profile['age'],
            'weight': float(profile['weight_kg']),
            'gender': profile['gender'],
        },
        'targets': targets,
        'today_intake': today_summary,
        'week': week_summaries,
        'improvement': improvement,
        'suggestions': suggestions
    })