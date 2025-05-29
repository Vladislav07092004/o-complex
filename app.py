from flask import Flask, render_template, request, jsonify, session
from flask_sqlalchemy import SQLAlchemy
import requests
from urllib.parse import quote
import uuid
import os

app = Flask(__name__)
app.secret_key = os.getenv('FLASK_SECRET_KEY', 'e6a3c422e4f64a9d91f80e3be3f6dc12')
app.config['SQLALCHEMY_DATABASE_URI'] = 'sqlite:///weather.db'
db = SQLAlchemy(app)


class City(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    name = db.Column(db.String(100), nullable=False)
    search_count = db.Column(db.Integer, default=1)

class User(db.Model):
    id = db.Column(db.String(36), primary_key=True)  # UUID в виде строки
    created_at = db.Column(db.DateTime, server_default=db.func.now())

class SearchHistory(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    user_id = db.Column(db.String(36), db.ForeignKey('user.id'), nullable=False)
    city_name = db.Column(db.String(100), nullable=False)
    searched_at = db.Column(db.DateTime, server_default=db.func.now())

    user = db.relationship('User', backref='search_history')



# Инициализация БД
with app.app_context():
    db.create_all()
    if not City.query.first():
        popular_cities = ['Москва', 'Санкт-Петербург', 'Новосибирск', 'Екатеринбург', 'Казань',
                         'New York', 'London', 'Paris', 'Tokyo']
        for city in popular_cities:
            db.session.add(City(name=city, search_count=5))
        db.session.commit()

@app.before_request
def before_request():
    if 'user_id' not in session:
        user_id = str(uuid.uuid4())
        session['user_id'] = user_id
        db.session.add(User(id=user_id))
        db.session.commit()


def get_coordinates(city_name):
    OPEN_CAGE_API_KEY = '03228847b1a04a3ebbd1e465e0d12d75'
    city_name = city_name.strip()
    if not city_name or len(city_name) < 2:
        print("Ошибка: слишком короткое или пустое название города для геокодирования")
        return None

    encoded_city = quote(city_name)
    url = f"https://api.opencagedata.com/geocode/v1/json?q={encoded_city}&key={OPEN_CAGE_API_KEY}&no_annotations=1"

    try:
        response = requests.get(url)
        response.raise_for_status()
        data = response.json()
        if data['results']:
            return data['results'][0]['geometry']['lat'], data['results'][0]['geometry']['lng']
        else:
            print("Город не найден в ответе API")
            return None
    except requests.exceptions.HTTPError as e:
        print(f"Ошибка геокодирования: {e} для запроса: {url}")
        return None
    except Exception as e:
        print(f"Неожиданная ошибка геокодирования: {e}")
        return None



def get_weather(lat, lng):
    url = "https://api.open-meteo.com/v1/forecast"
    params = {
        'latitude': lat,
        'longitude': lng,
        'current_weather': True,
        'hourly': 'temperature_2m,relativehumidity_2m,apparent_temperature,precipitation_probability,weathercode',
        'daily': 'weathercode,temperature_2m_max,temperature_2m_min,sunrise,sunset,precipitation_sum',
        'timezone': 'auto',
        'forecast_days': 7  # Получаем данные на 7 дней
    }

    try:
        response = requests.get(url, params=params)
        response.raise_for_status()
        data = response.json()

        if not data.get('current_weather') or not data.get('hourly') or not data.get('daily'):
            raise ValueError("Неполные данные от API погоды")

        return {
            'current': {
                'temperature': data['current_weather']['temperature'],
                'windspeed': data['current_weather']['windspeed'],
                'winddirection': data['current_weather']['winddirection'],
                'weathercode': data['current_weather']['weathercode'],
                'time': data['current_weather']['time']
            },
            'hourly': {
                'time': data['hourly']['time'],
                'temperature': data['hourly']['temperature_2m'],
                'humidity': data['hourly']['relativehumidity_2m'],
                'apparent_temp': data['hourly']['apparent_temperature'],
                'precipitation_prob': data['hourly']['precipitation_probability'],
                'weathercode': data['hourly']['weathercode']
            },
            'daily': {
                'time': data['daily']['time'],
                'temp_max': data['daily']['temperature_2m_max'],
                'temp_min': data['daily']['temperature_2m_min'],
                'weathercode': data['daily']['weathercode'],
                'sunrise': data['daily']['sunrise'],
                'sunset': data['daily']['sunset'],
                'precipitation': data['daily']['precipitation_sum']
            },
            'timezone': data['timezone'],
            'utc_offset': data['utc_offset_seconds']
        }
    except Exception as e:
        print(f"Ошибка получения погоды: {e}")
        return None


@app.route('/')
def index():
    popular_cities = City.query.order_by(City.search_count.desc()).limit(5).all()
    return render_template('index.html', popular_cities=popular_cities)


@app.route('/autocomplete')
def autocomplete():
    query = request.args.get('query', '').strip().lower()
    if not query or len(query) < 2:
        return jsonify([])


    popular_cities = City.query.order_by(City.search_count.desc()).limit(5).all()
    popular_names = {city.name for city in popular_cities}


    db_cities = City.query.filter(City.name.ilike(f'%{query}%')) \
        .order_by(City.search_count.desc()) \
        .limit(10).all()


    suggestions = []
    seen = set()

    # Сначала добавляем популярные города
    for city in popular_cities:
        if query in city.name.lower() and city.name not in seen:
            suggestions.append(city.name)
            seen.add(city.name)

    # Затем добавляем остальные совпадения
    for city in db_cities:
        if city.name not in seen:
            suggestions.append(city.name)
            seen.add(city.name)

    return jsonify(suggestions[:10])  # Не более 10 подсказок

@app.route('/get-weather', methods=['POST'])
def weather():
    city_name = request.form.get('city')
    if not city_name:
        return jsonify({'error': 'Город не указан'}), 400

    # Обновляем статистику
    city = City.query.filter_by(name=city_name).first()
    if city:
        city.search_count += 1
    else:
        city = City(name=city_name)
        db.session.add(city)
    db.session.commit()

    # Получаем координаты
    coords = get_coordinates(city_name)
    if not coords:
        # Здесь возвращаем понятную ошибку клиенту, прерывая дальнейшую обработку
        return jsonify({'error': 'Город не найден или некорректный запрос к геокодеру'}), 404

    # Получаем погоду
    weather_data = get_weather(*coords)
    if not weather_data:
        return jsonify({'error': 'Ошибка получения погоды'}), 500

    try:
        return jsonify({
            'city': city_name,
            'current': weather_data['current'],
            'hourly': weather_data['hourly'],
            'daily': weather_data['daily']
        })
    except KeyError as e:
        print(f"Ошибка формирования ответа: {e}")
        return jsonify({'error': 'Ошибка обработки данных погоды'}), 500



@app.route('/api/search-stats')
def search_stats():
    # Топ 10 самых популярных городов
    popular_cities = db.session.query(
        City.name,
        City.search_count
    ).order_by(City.search_count.desc()).limit(10).all()

    # Последние 10 поисков текущего пользователя
    user_history = []
    user_id = session.get('user_id')
    if user_id:
        user_history = db.session.query(
            SearchHistory.city_name,
            SearchHistory.searched_at
        ).filter_by(user_id=user_id) \
         .order_by(SearchHistory.searched_at.desc()) \
         .limit(10).all()

    return jsonify({
        'popular_cities': [{'name': c.name, 'count': c.search_count} for c in popular_cities],
        'user_history': [{'city': h.city_name, 'time': h.searched_at.isoformat()} for h in user_history]
    })

if __name__ == '__main__':
    app.run(host='0.0.0.0', port=5000, debug=True)