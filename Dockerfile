# Используем официальный образ Python как базовый
FROM python:3.11-slim

# Устанавливаем рабочую директорию внутри контейнера
WORKDIR /app

# Копируем файлы проекта в контейнер
COPY . .

# Устанавливаем зависимости
RUN pip install --upgrade pip
RUN pip install -r requirements.txt

# Указываем порт, на котором будет работать приложение
EXPOSE 5000

# Указываем команду запуска
CMD ["python", "app.py"]
