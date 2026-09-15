from flask import (
    Flask,
    render_template,
    request,
    redirect,
    session,
    flash,
    url_for
)

import os
import json
import sqlite3
import random
import string

from dotenv import load_dotenv
from werkzeug.security import generate_password_hash, check_password_hash
from werkzeug.utils import secure_filename

from groq import Groq
from PyPDF2 import PdfReader
from docx import Document


# =========================================================
# APP CONFIG
# =========================================================

app = Flask(__name__)

app.secret_key = "quizgen-secret-key"

UPLOAD_FOLDER = "uploads"

app.config["UPLOAD_FOLDER"] = UPLOAD_FOLDER

os.makedirs(UPLOAD_FOLDER, exist_ok=True)


# =========================================================
# ENV + GROQ
# =========================================================

load_dotenv()

GROQ_API_KEY = os.getenv("GROQ_API_KEY")

client = Groq(
    api_key=GROQ_API_KEY
)


# =========================================================
# DATABASE
# =========================================================

def get_db():

    conn = sqlite3.connect("database.db")

    conn.row_factory = sqlite3.Row

    return conn


def create_tables():

    conn = get_db()

    conn.execute("""
        CREATE TABLE IF NOT EXISTS users (

            id INTEGER PRIMARY KEY AUTOINCREMENT,

            name TEXT NOT NULL,

            email TEXT UNIQUE NOT NULL,

            password TEXT NOT NULL

        )
    """)


    conn.execute("""
        CREATE TABLE IF NOT EXISTS quizzes (

            id INTEGER PRIMARY KEY AUTOINCREMENT,

            user_id INTEGER,

            title TEXT,

            difficulty TEXT,

            total_questions INTEGER,

            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP

        )
    """)


    conn.execute("""
        CREATE TABLE IF NOT EXISTS questions (

            id INTEGER PRIMARY KEY AUTOINCREMENT,

            quiz_id INTEGER,

            question TEXT,

            option_a TEXT,

            option_b TEXT,

            option_c TEXT,

            option_d TEXT,

            correct_answer TEXT,

            explanation TEXT

        )
    """)


    conn.execute("""
        CREATE TABLE IF NOT EXISTS results (

            id INTEGER PRIMARY KEY AUTOINCREMENT,

            user_id INTEGER,

            quiz_id INTEGER,

            score INTEGER,

            total INTEGER,

            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP

        )
    """)


    conn.execute("""
        CREATE TABLE IF NOT EXISTS quiz_rooms (

            id INTEGER PRIMARY KEY AUTOINCREMENT,

            quiz_id INTEGER,

            room_code TEXT UNIQUE,

            created_by INTEGER,

            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP

        )
    """)


    conn.execute("""
        CREATE TABLE IF NOT EXISTS room_players (

            id INTEGER PRIMARY KEY AUTOINCREMENT,

            room_id INTEGER,

            player_name TEXT,

            score INTEGER DEFAULT 0,

            total INTEGER DEFAULT 0

        )
    """)

    conn.commit()

    conn.close()


create_tables()


# =========================================================
# DOCUMENT TEXT EXTRACTION
# =========================================================

def extract_pdf_text(file_path):

    text = ""

    reader = PdfReader(file_path)

    for page in reader.pages:

        page_text = page.extract_text()

        if page_text:

            text += page_text + "\n"

    return text


def extract_docx_text(file_path):

    document = Document(file_path)

    text = ""

    for paragraph in document.paragraphs:

        text += paragraph.text + "\n"

    return text


def extract_txt_text(file_path):

    with open(
        file_path,
        "r",
        encoding="utf-8",
        errors="ignore"
    ) as file:

        return file.read()


def extract_document_text(file_path):

    extension = file_path.rsplit(".", 1)[-1].lower()

    if extension == "pdf":

        return extract_pdf_text(file_path)

    elif extension == "docx":

        return extract_docx_text(file_path)

    elif extension == "txt":

        return extract_txt_text(file_path)

    return ""


# =========================================================
# GROQ QUIZ GENERATOR
# =========================================================

def generate_quiz_with_groq(
    text,
    difficulty,
    question_count
):

    # Prevent sending extremely large documents
    text = text[:45000]

    prompt = f"""
Create exactly {question_count} multiple-choice questions
using ONLY the study material provided below.

Difficulty:
{difficulty}

Each question must contain:

question
option_a
option_b
option_c
option_d
correct_answer
explanation

The value of correct_answer MUST be exactly one of:

A
B
C
D

Return JSON only.

Use this exact JSON structure:

{{
    "questions": [
        {{
            "question": "Question text",
            "option_a": "First option",
            "option_b": "Second option",
            "option_c": "Third option",
            "option_d": "Fourth option",
            "correct_answer": "A",
            "explanation": "Short explanation"
        }}
    ]
}}

Study material:

{text}
"""

    response = client.chat.completions.create(

        model="openai/gpt-oss-120b",

        messages=[

            {
                "role": "system",
                "content":
                "You are an educational quiz generator. "
                "Return accurate JSON only."
            },

            {
                "role": "user",
                "content": prompt
            }

        ],

        temperature=0.3,

        response_format={
            "type": "json_object"
        }

    )

    quiz_text = response.choices[0].message.content

    data = json.loads(quiz_text)

    return data["questions"]
# =========================================================
# HOME
# =========================================================

@app.route("/")
def home():

    return render_template("index.html")


# =========================================================
# REGISTER
# =========================================================

@app.route(
    "/register",
    methods=["GET", "POST"]
)
def register():

    if request.method == "POST":

        name = request.form["name"].strip()

        email = request.form["email"].strip()

        password = request.form["password"]

        conn = get_db()

        existing_user = conn.execute(
            "SELECT * FROM users WHERE email = ?",
            (email,)
        ).fetchone()

        if existing_user:

            conn.close()

            flash("Email already registered.")

            return redirect("/register")

        hashed_password = generate_password_hash(
            password
        )

        conn.execute(
            """
            INSERT INTO users
            (name, email, password)
            VALUES (?, ?, ?)
            """,
            (
                name,
                email,
                hashed_password
            )
        )

        conn.commit()

        conn.close()

        flash(
            "Registration successful. Please login."
        )

        return redirect("/login")

    return render_template(
        "register.html"
    )


# =========================================================
# LOGIN
# =========================================================

@app.route(
    "/login",
    methods=["GET", "POST"]
)
def login():

    if request.method == "POST":

        email = request.form["email"]

        password = request.form["password"]

        conn = get_db()

        user = conn.execute(
            """
            SELECT *
            FROM users
            WHERE email = ?
            """,
            (email,)
        ).fetchone()

        conn.close()

        if user and check_password_hash(
            user["password"],
            password
        ):

            session["user_id"] = user["id"]

            session["user_name"] = user["name"]

            return redirect("/dashboard")

        flash(
            "Invalid email or password."
        )

    return render_template(
        "login.html"
    )


# =========================================================
# LOGOUT
# =========================================================

@app.route("/logout")
def logout():

    session.clear()

    return redirect("/")


# =========================================================
# DASHBOARD
# =========================================================

@app.route("/dashboard")
def dashboard():

    if "user_id" not in session:

        return redirect("/login")

    return render_template(
        "dashboard.html",
        name=session["user_name"]
    )


# =========================================================
# GENERATE QUIZ
# =========================================================

@app.route(
    "/generate",
    methods=["GET", "POST"]
)
def generate():

    if "user_id" not in session:

        return redirect("/login")

    if request.method == "POST":

        uploaded_file = request.files.get("document")

        difficulty = request.form.get(
            "difficulty",
            "Medium"
        )

        question_count = request.form.get(
            "question_count",
            5
        )

        try:

            question_count = int(
                question_count
            )

        except:

            question_count = 5


        if not uploaded_file:

            flash(
                "Please select a document."
            )

            return redirect("/generate")


        filename = secure_filename(
            uploaded_file.filename
        )


        if filename == "":

            flash(
                "Please select a valid file."
            )

            return redirect("/generate")


        extension = filename.rsplit(
            ".",
            1
        )[-1].lower()


        if extension not in [
            "pdf",
            "docx",
            "txt"
        ]:

            flash(
                "Only PDF, DOCX and TXT files are allowed."
            )

            return redirect("/generate")


        file_path = os.path.join(
            app.config["UPLOAD_FOLDER"],
            filename
        )


        uploaded_file.save(
            file_path
        )


        document_text = extract_document_text(
            file_path
        )


        if not document_text.strip():

            flash(
                "Could not read text from this document."
            )

            return redirect("/generate")


        try:

            questions = generate_quiz_with_groq(
                document_text,
                difficulty,
                question_count
            )

        except Exception as error:

            print("GROQ ERROR:", error)

            flash(
                "Could not generate quiz. Check your Groq API key or try again."
            )

            return redirect("/generate")


        conn = get_db()


        cursor = conn.execute(
            """
            INSERT INTO quizzes
            (
                user_id,
                title,
                difficulty,
                total_questions
            )

            VALUES (?, ?, ?, ?)
            """,
            (
                session["user_id"],
                filename,
                difficulty,
                len(questions)
            )
        )


        quiz_id = cursor.lastrowid


        for question in questions:

            conn.execute(
                """
                INSERT INTO questions
                (
                    quiz_id,
                    question,
                    option_a,
                    option_b,
                    option_c,
                    option_d,
                    correct_answer,
                    explanation
                )

                VALUES
                (?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    quiz_id,
                    question.get(
                        "question",
                        ""
                    ),

                    question.get(
                        "option_a",
                        ""
                    ),

                    question.get(
                        "option_b",
                        ""
                    ),

                    question.get(
                        "option_c",
                        ""
                    ),

                    question.get(
                        "option_d",
                        ""
                    ),

                    question.get(
                        "correct_answer",
                        ""
                    ).upper(),

                    question.get(
                        "explanation",
                        ""
                    )
                )
            )


        conn.commit()

        conn.close()


        return redirect(
            url_for(
                "quiz",
                quiz_id=quiz_id
            )
        )


    return render_template(
        "upload.html"
    )


# =========================================================
# QUIZ
# =========================================================

@app.route(
    "/quiz/<int:quiz_id>",
    methods=["GET", "POST"]
)
def quiz(quiz_id):

    if "user_id" not in session:

        return redirect("/login")


    conn = get_db()


    quiz_data = conn.execute(
        """
        SELECT *
        FROM quizzes
        WHERE id = ?
        """,
        (quiz_id,)
    ).fetchone()


    questions = conn.execute(
        """
        SELECT *
        FROM questions
        WHERE quiz_id = ?
        """,
        (quiz_id,)
    ).fetchall()


    if not quiz_data:

        conn.close()

        return "Quiz not found."


    if request.method == "POST":

        score = 0


        for question in questions:

            selected_answer = request.form.get(
                f"question_{question['id']}"
            )


            if selected_answer == question[
                "correct_answer"
            ]:

                score += 1


        cursor = conn.execute(
            """
            INSERT INTO results
            (
                user_id,
                quiz_id,
                score,
                total
            )

            VALUES (?, ?, ?, ?)
            """,
            (
                session["user_id"],
                quiz_id,
                score,
                len(questions)
            )
        )


        result_id = cursor.lastrowid


        conn.commit()

        conn.close()


        session[
            f"answers_{result_id}"
        ] = {

            str(question["id"]):
            request.form.get(
                f"question_{question['id']}",
                ""
            )

            for question in questions

        }


        return redirect(
            url_for(
                "result",
                result_id=result_id
            )
        )


    conn.close()


    return render_template(
        "quiz.html",
        quiz=quiz_data,
        questions=questions
    )


# =========================================================
# RESULT
# =========================================================

@app.route(
    "/result/<int:result_id>"
)
def result(result_id):

    if "user_id" not in session:

        return redirect("/login")


    conn = get_db()


    result_data = conn.execute(
        """
        SELECT
            results.*,
            quizzes.title

        FROM results

        JOIN quizzes
        ON results.quiz_id = quizzes.id

        WHERE results.id = ?
        """,
        (result_id,)
    ).fetchone()


    conn.close()


    if not result_data:

        return "Result not found."


    percentage = 0


    if result_data["total"] > 0:

        percentage = round(
            (
                result_data["score"]
                /
                result_data["total"]
            ) * 100,
            2
        )


    return render_template(
        "result.html",
        result=result_data,
        percentage=percentage
    )


# =========================================================
# REVIEW
# =========================================================

@app.route(
    "/review/<int:result_id>"
)
def review(result_id):

    if "user_id" not in session:

        return redirect("/login")


    conn = get_db()


    result_data = conn.execute(
        """
        SELECT *
        FROM results
        WHERE id = ?
        """,
        (result_id,)
    ).fetchone()


    if not result_data:

        conn.close()

        return "Result not found."


    questions = conn.execute(
        """
        SELECT *
        FROM questions
        WHERE quiz_id = ?
        """,
        (
            result_data[
                "quiz_id"
            ],
        )
    ).fetchall()


    conn.close()


    answers = session.get(
        f"answers_{result_id}",
        {}
    )


    return render_template(
        "review.html",
        questions=questions,
        answers=answers
    )


# =========================================================
# HISTORY
# =========================================================

@app.route("/history")
def history():

    if "user_id" not in session:

        return redirect("/login")


    conn = get_db()


    history_data = conn.execute(
        """
        SELECT
            results.id,
            quizzes.title,
            quizzes.difficulty,
            results.score,
            results.total,
            results.created_at

        FROM results

        JOIN quizzes
        ON results.quiz_id = quizzes.id

        WHERE results.user_id = ?

        ORDER BY results.id DESC
        """,
        (
            session["user_id"],
        )
    ).fetchall()


    conn.close()


    return render_template(
        "history.html",
        history=history_data
    )


# =========================================================
# CREATE ROOM
# =========================================================

def generate_room_code():

    characters = (
        string.ascii_uppercase
        +
        string.digits
    )

    return "".join(
        random.choices(
            characters,
            k=6
        )
    )


@app.route(
    "/create-room",
    methods=["GET", "POST"]
)
def create_room():

    if "user_id" not in session:

        return redirect("/login")


    conn = get_db()


    quizzes = conn.execute(
        """
        SELECT *
        FROM quizzes
        WHERE user_id = ?
        ORDER BY id DESC
        """,
        (
            session["user_id"],
        )
    ).fetchall()


    if request.method == "POST":

        quiz_id = request.form.get(
            "quiz_id"
        )


        if not quiz_id:

            conn.close()

            flash(
                "Please select a quiz."
            )

            return redirect(
                "/create-room"
            )


        room_code = generate_room_code()


        conn.execute(
            """
            INSERT INTO quiz_rooms
            (
                quiz_id,
                room_code,
                created_by
            )

            VALUES (?, ?, ?)
            """,
            (
                quiz_id,
                room_code,
                session["user_id"]
            )
        )


        conn.commit()

        conn.close()


        return render_template(
            "create_room.html",
            quizzes=quizzes,
            room_code=room_code
        )


    conn.close()


    return render_template(
        "create_room.html",
        quizzes=quizzes
    )


# =========================================================
# JOIN ROOM
# =========================================================

@app.route(
    "/join-room",
    methods=["GET", "POST"]
)
def join_room():

    if request.method == "POST":

        player_name = request.form.get(
            "player_name"
        )

        room_code = request.form.get(
            "room_code",
            ""
        ).upper()


        conn = get_db()


        room = conn.execute(
            """
            SELECT *
            FROM quiz_rooms
            WHERE room_code = ?
            """,
            (room_code,)
        ).fetchone()


        if not room:

            conn.close()

            flash(
                "Invalid room code."
            )

            return redirect(
                "/join-room"
            )


        cursor = conn.execute(
            """
            INSERT INTO room_players
            (
                room_id,
                player_name
            )

            VALUES (?, ?)
            """,
            (
                room["id"],
                player_name
            )
        )


        player_id = cursor.lastrowid


        conn.commit()

        conn.close()


        session["room_player_id"] = player_id


        return redirect(
            url_for(
                "room_quiz",
                room_code=room_code
            )
        )


    return render_template(
        "join_room.html"
    )


# =========================================================
# ROOM QUIZ
# =========================================================

@app.route(
    "/room/<room_code>",
    methods=["GET", "POST"]
)
def room_quiz(room_code):

    conn = get_db()


    room = conn.execute(
        """
        SELECT *
        FROM quiz_rooms
        WHERE room_code = ?
        """,
        (
            room_code.upper(),
        )
    ).fetchone()


    if not room:

        conn.close()

        return "Room not found."


    questions = conn.execute(
        """
        SELECT *
        FROM questions
        WHERE quiz_id = ?
        """,
        (
            room["quiz_id"],
        )
    ).fetchall()


    if request.method == "POST":

        score = 0


        for question in questions:

            selected = request.form.get(
                f"question_{question['id']}"
            )


            if selected == question[
                "correct_answer"
            ]:

                score += 1


        player_id = session.get(
            "room_player_id"
        )


        if player_id:

            conn.execute(
                """
                UPDATE room_players

                SET
                    score = ?,
                    total = ?

                WHERE id = ?
                """,
                (
                    score,
                    len(questions),
                    player_id
                )
            )


            conn.commit()


        conn.close()


        return redirect(
            url_for(
                "leaderboard",
                room_code=room_code
            )
        )


    conn.close()


    return render_template(
        "quiz.html",
        questions=questions,
        room_mode=True,
        room_code=room_code
    )


# =========================================================
# LEADERBOARD
# =========================================================

@app.route(
    "/leaderboard/<room_code>"
)
def leaderboard(room_code):

    conn = get_db()


    room = conn.execute(
        """
        SELECT *
        FROM quiz_rooms
        WHERE room_code = ?
        """,
        (
            room_code.upper(),
        )
    ).fetchone()


    if not room:

        conn.close()

        return "Room not found."


    players = conn.execute(
        """
        SELECT *
        FROM room_players
        WHERE room_id = ?
        ORDER BY score DESC
        """,
        (
            room["id"],
        )
    ).fetchall()


    conn.close()


    return render_template(
        "leaderboard.html",
        players=players,
        room_code=room_code
    )


@app.route("/leaderboard")
def leaderboard_home():

    return render_template(
        "leaderboard.html",
        players=[]
    )


# =========================================================
# PROFILE
# =========================================================

@app.route("/profile")
def profile():

    if "user_id" not in session:

        return redirect("/login")


    conn = get_db()


    user = conn.execute(
        """
        SELECT *
        FROM users
        WHERE id = ?
        """,
        (
            session["user_id"],
        )
    ).fetchone()


    stats = conn.execute(
        """
        SELECT

            COUNT(*) AS total_quizzes,

            COALESCE(
                AVG(
                    CAST(score AS FLOAT)
                    /
                    NULLIF(total, 0)
                    *
                    100
                ),
                0
            ) AS average_score,

            COALESCE(
                MAX(
                    CAST(score AS FLOAT)
                    /
                    NULLIF(total, 0)
                    *
                    100
                ),
                0
            ) AS best_score

        FROM results

        WHERE user_id = ?
        """,
        (
            session["user_id"],
        )
    ).fetchone()


    conn.close()


    return render_template(
        "profile.html",
        user=user,
        stats=stats
    )


# =========================================================
# RUN
# =========================================================

if __name__ == "__main__":

    app.run(
        debug=True
    )
