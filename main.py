from string import ascii_uppercase
import json
import random
import sqlite3
from hashlib import sha256
from flask import Flask, render_template, url_for
from flask import request, flash, redirect, session, send_from_directory
from flask_socketio import SocketIO, send, emit, join_room, leave_room
import zipfile

app = Flask(__name__)
app.config['SECRET_KEY'] = '21d6t3yfuyhrewoi1en3kqw'
app.config['UPLOAD_FOLDER'] = ''
socketio = SocketIO(app, cors_allowed_origins='*')
rooms = {}
cur_que = {}


def generate_unique_code(length):
    while True:
        code = ""
        for _ in range(length):
            code += random.choice(ascii_uppercase)
        if code not in rooms:
            break
    return code


def generate_qs(theme):
    db = sqlite3.connect('users_data.db')
    c = db.cursor()
    sel_query = 'SELECT * FROM questions WHERE theme=?;'
    c.execute(sel_query, (theme,))
    qs = c.fetchall()
    tmp = []
    used_ids = []
    for _ in range(20):
        while (i := random.choice(qs))[1] in used_ids:
            pass
        tmp.append(i)
        used_ids.append(i[1])
    tmp = [{'question': i[2],
            'answers': [i[3], i[4], i[5], i[6]],
            'correct': i[7],
            'time': i[8]} for i in tmp]
    return tmp.copy()


def get_themes_old():
    with open("questions.json", 'r', encoding='UTF-8') as f:
        questions: dict = json.load(f)['questions']
    return list(questions.keys())


def get_themes():
    db = sqlite3.connect('users_data.db')
    c = db.cursor()
    sel_query = 'SELECT theme FROM questions;'
    c.execute(sel_query)
    th = set(c.fetchall())
    th = [i[0] for i in th]
    return th



def add_rating_db(rating: dict):
    connection = sqlite3.connect('users_data.db')
    cursor = connection.cursor()
    sel_query = "SELECT rating FROM users WHERE name = ?"
    upd_query = 'UPDATE users SET rating = ? WHERE name = ?'
    for user in rating:
        cursor.execute(sel_query, (user,))
        usr_psw = cursor.fetchall()
        cursor.execute(upd_query, (rating[user] + usr_psw[0][0],
                                   user))
    connection.commit()
    connection.close()


@socketio.on('connect', namespace='/room')
def handle_connect(_):
    name = session['username']
    room = session.get('room')
    if name is None or room is None:
        return
    if room not in rooms:
        leave_room(room)
    join_room(room)
    send(f"{name} заходит в чат", to=room)
    session['coop_progress'] = 0
    rooms[room]["members"] += 1
    rooms[room]["result"][name] = 0
    rooms[room]["ready"][name] = False
    emit("pcount", rooms[room]['members'], to=room)
    emit("themes", rooms[room]["themes"])


@socketio.on('start', namespace='/room')
def handle_start(theme):
    room = session["room"]
    questions = generate_qs(theme)
    rooms[room]['questions'] = questions
    emit("question", rooms[room]['questions'][0], to=room)


@socketio.on('answer', namespace='/room')
def handle_answer(answer):
    room = rooms[session["room"]]
    name = session["username"]
    if answer == 'corr':
        room['result'][name] += 1
    session['coop_progress'] += 1
    if session['coop_progress'] >= len(room['questions']):
        room['ready'][name] = True
        emit('wait')
        flag = True
        for n in room['ready']:
            flag = flag and room['ready'][n]
        if flag:
            emit("end", room["result"], to=session['room'])
            add_rating_db(room["result"])
    else:
        emit("question", room['questions'][session['coop_progress']])


@socketio.on('message', namespace='/room')
def handle_chat_message(message):
    result = session['username'] + " : " + message
    print("Received message: " + result)
    send(result, to=session["room"])


@socketio.on('disconnect', namespace='/room')
def handle_disconnect():
    room = session.get("room")
    name = session.get("username")
    leave_room(room)
    if room in rooms:
        rooms[room]["members"] -= 1
        rooms[room]['ready'].pop(name)
        emit("pcount", rooms[room]['members'], to=room)
        if rooms[room]["members"] <= 0:
            del rooms[room]
        send(f"{name} покинул(а) чат", to=room)


@socketio.on('connect', namespace='/single')
def handle_single_connect(_):
    session['progress'] = 0
    session['correct'] = 0
    emit("themes", get_themes())


@socketio.on('start', namespace='/single')
def handle_single_start(theme):
    questions = generate_qs(theme)
    session['questions'] = questions
    emit("question", session['questions'][0])


@socketio.on('answer', namespace='/single')
def handle_single_answer(answer):
    name = session["username"]
    if answer == 'corr':
        session['correct'] += 1
    session['progress'] += 1
    if session['progress'] >= len(session['questions']):
        emit("end", {name: session['correct']})
        add_rating_db({name: session['correct']})
    else:
        emit("question", session['questions'][session['progress']])


@app.route("/single")
def single():
    return render_template('single.html', name=session.get('username'))


@app.route('/coop', methods=['POST', 'GET'])
def createroom():
    if request.method == "POST":
        # session['name'] = request.form.get("name_room")
        code = request.form.get("code")
        join = request.form.get("join", False)
        create = request.form.get("create", False)
        if join is not False and not code:
            return render_template("joinroom.html",
                                   error="Please enter a room code.",
                                   code=code)
        room = code
        if create is not False:
            room = generate_unique_code(4)
            rooms[room] = {"members": 0,
                           'result': {},
                           'themes': get_themes(),
                           'ready': {}}
        elif code not in rooms:
            return render_template("joinroom.html",
                                   error="Room does not exist.",
                                   code=code)
        session["room"] = room
        return redirect("/room")
    return render_template("joinroom.html", rooms=rooms)


@app.route("/room")
def show_room():
    return render_template('room.html', code=session.get('room'))


@app.route('/rating')
def show_rating():
    connection = sqlite3.connect('users_data.db')
    cursor = connection.cursor()
    cursor.execute("SELECT * FROM users")
    ids = [(row[0], row[2]) for row in cursor]
    ids = sorted(ids, reverse=True, key=lambda x: x[1])
    session['users_rating'] = ids.copy()
    return render_template("rating.html", rows=ids)


@app.route('/mode')
def quiz():
    return render_template('main.html',
                           title="Выбор режима",
                           name=session['username'])


@app.route('/')
@app.route('/authorization', methods=['POST', 'GET'])
def authorize():
    if 'username' in session.keys() and not session['username'] is None:
        redirect(url_for('quiz'))
    if request.method == 'POST':
        db = sqlite3.connect('users_data.db')
        c = db.cursor()
        # c.execute("""CREATE TABLE users (
        # name text,
        # password text
        # )""")
        username = request.form['username']
        password = request.form['password']
        p_and_u = password + username
        crypto_password = sha256(p_and_u.encode('utf-8')).hexdigest()
        query = "SELECT * FROM users WHERE name = ?"
        c.execute(query, (username,))
        usr_psw = c.fetchall()
        if len(usr_psw) != 0:
            usr_psw = usr_psw[0]
            if usr_psw[0] == username and usr_psw[1] == crypto_password:
                flash('вы вошли в аккаунт')
                session['username'] = username
                render_template('authorize.html', title="Вход")
                return redirect(url_for('quiz'))
            else:
                flash('ошибка')
        else:
            flash('такого аккаунта нет')
        # query = "SELECT * FROM users"
        # c.execute(query)
        # print(c.fetchall())
        db.commit()
        db.close()
    return render_template('authorize.html', title="Вход")


@app.route('/registration', methods=['POST', 'GET'])
def registration():
    if request.method == 'POST':
        db = sqlite3.connect('users_data.db')
        c = db.cursor()
        # c.execute("""CREATE TABLE users (
        # name text,
        # password text
        # )""")
        correct_mail = True
        error = False
        username = request.form['username']
        if username == "":
            error = True
            flash('введите никнейм')
        password = request.form['password']
        if password == "":
            error = True
            flash('введите пароль')

        # mail + test of loyalty
        mail = request.form['mail']
        if '@' not in mail:
            correct_mail = False
        rating = 0
        p_and_u = password + username
        crypto_password = sha256(p_and_u.encode('utf-8')).hexdigest()
        query = "SELECT * FROM users WHERE name = ?"
        c.execute(query, (username,))
        finded = c.fetchall()
        print(finded)
        if len(finded) == 0 and correct_mail is True and error is False:
            query = "INSERT INTO users VALUES (?, ?, ?, ?)"
            c.execute(query, (username, crypto_password, rating, mail))
            c.execute("SELECT * FROM users")

            flash('аккаунт создан')
            db.commit()
        elif correct_mail is False and len(finded) == 0:
            flash('неверно указан адрес электронной почты')
        if len(finded) == 1 and error is False:
            flash('такой аккаунт уже существует')
        db.close()
    return render_template('registration.html', title="Регистрация")


@app.route('/create_quiz', methods=['POST', 'GET'])
def create_quiz():
    session['create'] = {}
    global cur_que
    if request.method == 'POST':
        session['create']['name'] = request.form['name_quiz']
        session['create']['amount'] = int(request.form['amount'])
        cur_que = {}
        cur_que[session['create']['name']] = []
        return redirect('/make_quiz/0')
    return render_template('create_quiz.html')


@app.route('/make_quiz/<i>', methods=['POST', 'GET'])
def make_quiz(i):
    if request.method == 'POST':
        tmp = {}
        tmp['question'] = request.form['ans']
        tmp['answers'] = [request.form['cor']]
        for j in range(3):
            tmp['answers'].append(request.form['0' + '/' + str(j)])
        tmp['correct'] = 0
        tmp['time'] = 30
        print(tmp)
        cur_que[session['create']['name']] += [tmp]
        print(session['create'])
        if int(i)+1 >= session['create']['amount']:
            return redirect('/get_zip')
        else:
            return redirect(f'/make_quiz/{int(i)+1}')
    return render_template('make_quiz.html', theme=session['create']['name'],
                           number=int(i))


def add_new_que_to_bd():
    db = sqlite3.connect('users_data.db')
    c = db.cursor()
    query = "INSERT INTO questions VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)"
    with open("uploaded_quiz/temp.json", 'r', encoding='UTF-8') as f:
        questions: dict = json.load(f)
        print(questions)
        for i in questions.keys():
            theme = i
            for j in range(len(questions[i])):
                que = questions[i][j]['question']
                ans_1 = questions[i][j]['answers'][0]
                ans_2 = questions[i][j]['answers'][1]
                ans_3 = questions[i][j]['answers'][2]
                ans_4 = questions[i][j]['answers'][3]
                cor = questions[i][j]['correct']
                time = questions[i][j]['time']
                # print(theme, j, que, ans_1, ans_2, ans_3, ans_4, cor, time)
                c.execute(query, (theme, j, que, ans_1, ans_2, ans_3, ans_4, int(cor), int(time)))
                c.execute("SELECT * FROM questions")
                db.commit()


@app.route('/get_zip', methods=['POST', 'GET'])
def get_zip():
    print(session['create'])
    json_data = cur_que.copy()
    # перемешиваем варианты ответов
    for i in json_data[session['create']['name']]:
        shift = random.randint(0, 4)
        i['correct'] = shift % 4
        temp_ans = [0] * 4
        for j in range(len(i['answers'])):
            temp_ans[(j + shift) % 4] = i['answers'][j]
        i['answers'] = temp_ans
    json_loaded = json.dumps(json_data, ensure_ascii=False, indent=2)
    with open('temp.json', 'w', encoding="UTF-8") as f:
        f.write(json_loaded)
    # в зип
    with zipfile.ZipFile('questions.que', "w", compression=zipfile.ZIP_DEFLATED) as ziphelper:
        ziphelper.write('temp.json')

    return render_template('get_zip.html')


@app.route('/questions.que')
def download_archive():
    return send_from_directory(app.config['UPLOAD_FOLDER'], 'questions.que', as_attachment=True)


@app.route('/add_quiz', methods=['POST', 'GET'])
def add_quiz():
    if request.method == 'POST':
        file = request.files['file']
        with zipfile.ZipFile(file, 'r') as zip_ref:
            # Извлечение всех файлов в указанную директорию
            zip_ref.extractall('uploaded_quiz')
        add_new_que_to_bd()
    return render_template('add_quiz.html')


# временная функция для создания дб по жсонке(потом удалить)
def create_table():
    db = sqlite3.connect('users_data.db')
    c = db.cursor()
    # c.execute("DROP TABLE questions")
    # c.execute("""CREATE TABLE questions (
    #     theme text,
    #     number int,
    #     question text,
    #     answer_1 text,
    #     answer_2 text,
    #     answer_3 text,
    #     answer_4 text,
    #     correct int,
    #     time int
    #     )""")
    query = "INSERT INTO questions VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)"
    with open("questions.json", 'r', encoding='UTF-8') as f:
        questions: dict = json.load(f)
        print(questions)
        for i in questions['questions'].keys():
            theme = i
            for j in range(len(questions['questions'][i])):
                que = questions['questions'][i][j]['question']
                ans_1 = questions['questions'][i][j]['answers'][0]
                ans_2 = questions['questions'][i][j]['answers'][1]
                ans_3 = questions['questions'][i][j]['answers'][2]
                ans_4 = questions['questions'][i][j]['answers'][3]
                cor = questions['questions'][i][j]['correct']
                time = questions['questions'][i][j]['time']
                # print(theme, j, que, ans_1, ans_2, ans_3, ans_4, cor, time)
                c.execute(query, (theme, j, que, ans_1, ans_2, ans_3, ans_4, int(cor), int(time)))
                c.execute("SELECT * FROM questions")
                db.commit()


if __name__ == '__main__':
    # app.run(debug=True)
    socketio.run(app, host="localhost", allow_unsafe_werkzeug=True, debug=True)
