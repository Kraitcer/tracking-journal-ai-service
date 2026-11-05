FROM python:3.14.0-slim

WORKDIR /app

RUN python -m pip install --no-cache-dir pipenv

COPY Pipfile Pipfile.lock ./
RUN pipenv install --system --deploy --ignore-pipfile

COPY . .

EXPOSE 8000

CMD ["uvicorn", "main:app", "--host", "0.0.0.0", "--port", "8000"]
