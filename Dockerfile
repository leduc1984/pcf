FROM python:3.8
ADD . /code
WORKDIR /code
RUN pip install -r requirements_unix.txt
RUN if [ ! -e "/code/configuration/database.sqlite3" ]; then echo 'DELETE_ALL' | python new_initiation.py; fi;
CMD python app.py