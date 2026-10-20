"""A look-around demo of the student area for people who haven't booked lessons yet.

A guest browses the real student pages, but every query goes to a separate,
made-up database that is rebuilt from this file the first time a guest looks
after each start - never to the real one, so no student's data can show up and
nothing a guest does can reach a real student or the tutor. Guests can't change
anything (student_routes refuses their writes) and never cost an AI call: the
hint helper answers them with the example replies below.
"""

import json
import re
import shutil
import sqlite3
import threading
from datetime import datetime, timedelta, timezone

from flask import session

import db
import homework_chat
import image_utils
import translations
from config import DATA_DIR

BOOK_URL = "https://www.tutorilya.com/#rec662371514"

DEMO_DIR = DATA_DIR / "demo"
SHEETS_DIR = DEMO_DIR / "sheets"
LANGUAGES = ("en", "ru")
# The same made-up student in each interface language, each in a database of its own
# with the same ids - so switching EN/RU on any page shows that page in the other one.
STUDENT_ID = 1

STUDENTS = {
    "en": {
        "name": "Alex",
        "schedule": "Tue and Thu, 17:00 (Lisbon) · Zoom + Miro",
        "narrative": "Alex has made steady progress over the last five weeks. Sequences, proportionality and "
                     "first-degree equations are solid, and the working is clear and well laid out. The one thing "
                     "that keeps costing points is signs: moving a term to the other side of an equation and "
                     "ordering negative numbers. That is the focus for the next lessons, together with powers.",
    },
    "ru": {
        "name": "Саша",
        "schedule": "Вт и Чт, 17:00 (Лиссабон) · Zoom + Miro",
        "narrative": "За последние пять недель Саша уверенно продвигается. Sequências, proporcionalidade direta и "
                     "equações do 1.º grau усвоены хорошо, решения записаны аккуратно и понятно. Баллы чаще всего "
                     "теряются на знаках: при переносе слагаемого через «=» и при сравнении отрицательных чисел. "
                     "На этом и сосредоточимся на ближайших уроках, а также на potências.",
    },
}


def _problem(label, text, answer, correct, verdict="correct", explanation=None):
    return {"problem_label": label, "problem_text": text, "student_answer": answer, "work": "",
            "correct_answer": correct, "verdict": verdict, "explanation": explanation or {}, "confidence": "high"}


# Oldest first. Titles are the Portuguese sheet titles; everything a student
# reads in their own language is given per language.
HOMEWORK = [
    {"title": "Sequências e regularidades", "topic": {"en": "Sequences", "ru": "Последовательности"},
     "assigned": 38, "submitted": 36, "reviewed": 35, "grade": "A",
     "comment": {"en": "Excellent - every term and the general rule are right.",
                 "ru": "Отлично — все члены и общая формула верны."},
     "problems": [_problem("1", "3, 7, 11, 15, ...", r"\(19, 23\)", r"\(19, 23\)"),
                  _problem("2", "3, 7, 11, 15, ...", r"\(4n - 1\)", r"\(4n - 1\)")]},
    {"title": "Números racionais", "topic": {"en": "Rational numbers", "ru": "Рациональные числа"},
     "assigned": 31, "submitted": 29, "reviewed": 28, "grade": "B",
     "comment": {"en": "Good. Check how you order negative numbers - see task 3.",
                 "ru": "Хорошо. Проверь, как ты сравниваешь отрицательные числа, — см. задание 3."},
     "problems": [
         _problem("1", r"\(\frac{2}{5} + \frac{1}{3}\)", r"\(\frac{11}{15}\)", r"\(\frac{11}{15}\)"),
         _problem("2", r"\(-\frac{3}{4} \times \frac{2}{9}\)", r"\(-\frac{1}{6}\)", r"\(-\frac{1}{6}\)"),
         _problem("3", r"Ordena: \(-\frac{3}{4}\), \(-\frac{2}{3}\), \(-0{,}7\)",
                  r"\(-\frac{2}{3} < -0{,}7 < -\frac{3}{4}\)", r"\(-\frac{3}{4} < -0{,}7 < -\frac{2}{3}\)",
                  "incorrect",
                  {"en": "With negative numbers, the bigger the absolute value, the smaller the number: "
                         "-0,75 < -0,7 < -0,67. Write each fraction as a decimal first, then order them.",
                   "ru": "У отрицательных чисел чем больше модуль, тем меньше число: -0,75 < -0,7 < -0,67. "
                         "Сначала переведи каждую дробь в десятичную, потом сравнивай."})]},
    {"title": "Proporcionalidade direta", "topic": {"en": "Direct proportion", "ru": "Прямая пропорциональность"},
     "assigned": 24, "submitted": 22, "reviewed": 21, "grade": "A",
     "comment": {"en": "Clear tables and the right constant of proportionality every time. Great!",
                 "ru": "Аккуратные таблицы и каждый раз верная constante de proporcionalidade. Супер!"},
     "problems": [_problem("1", "x: 2, 5, 8 | y: 6, 15, 24", r"\(k = 3\)", r"\(k = 3\)"),
                  _problem("2", "5 kg - 7,50 €; 8 kg?", "12 €", "12 €")]},
    {"title": "Equações do 1.º grau", "topic": {"en": "First-degree equations", "ru": "Линейные уравнения"},
     "assigned": 10, "submitted": 8, "reviewed": 7, "grade": "B",
     "sheet": ["Resolve as equações.", "1)   3x - 5 = 10", "2)   2(x + 1) = 8", "3)   x/4 + 2 = 5",
               "4)   5x - 3 = 2x + 9"],
     "comment": {"en": "Good work! Three out of four are spot on. In task 4, watch the sign when a number moves "
                       "to the other side of the equals sign - we'll practise this on Tuesday.",
                 "ru": "Хорошая работа! Три задачи из четырёх — без ошибок. В 4-й следи за знаком, когда число "
                       "переходит через «=», — потренируем это во вторник."},
     "problems": [
         _problem("1", r"\(3x - 5 = 10\)", r"\(x = 5\)", r"\(x = 5\)"),
         _problem("2", r"\(2(x + 1) = 8\)", r"\(x = 3\)", r"\(x = 3\)"),
         _problem("3", r"\(\frac{x}{4} + 2 = 5\)", r"\(x = 12\)", r"\(x = 12\)"),
         _problem("4", r"\(5x - 3 = 2x + 9\)", r"\(x = 2\)", r"\(x = 4\)", "incorrect",
                  {"en": "When -3 moves to the right side it becomes +3: 3x = 9 + 3 = 12, so x = 4. "
                         "You wrote 3x = 9 - 3.",
                   "ru": "При переносе в правую часть -3 становится +3: 3x = 9 + 3 = 12, значит x = 4. "
                         "У тебя получилось 3x = 9 - 3."})]},
    {"title": "Funções afins", "topic": {"en": "Linear functions", "ru": "Линейные функции"},
     "assigned": 3, "submitted": 1, "photos": 2,
     "sheet": ["1)  Indica o declive e a ordenada na origem", "      de f(x) = 2x - 3.",
               "2)  Determina a função afim cujo gráfico", "      passa por A(1, 4) e B(3, 8).",
               "3)  Representa graficamente g(x) = -x + 2."]},
    {"title": "Potências e raízes", "topic": {"en": "Powers and roots", "ru": "Степени и корни"},
     "assigned": 0, "used_hints": ["theory"],
     "sheet": ["Calcula e simplifica.", "1)   2^3 × 2^4", "2)   5^6 : 5^4", "3)   (3^2)^3", "4)   4^-2",
               "5)   raiz quadrada de 81"]},
]

# What the hint helper answers a guest - written like its real, short replies.
HINTS = {
    "Potências e raízes": {
        "theory": {
            "en": r"Powers with the same base: when you multiply, add the exponents - \(a^m \cdot a^n = a^{m+n}\); "
                  r"when you divide, subtract them - \(a^m : a^n = a^{m-n}\). A negative exponent means the "
                  r"reciprocal: \(a^{-n} = \frac{1}{a^n}\). Try task 1 with these rules first.",
            "ru": r"Степени с одинаковым основанием: при умножении показатели складываются — "
                  r"\(a^m \cdot a^n = a^{m+n}\), при делении вычитаются — \(a^m : a^n = a^{m-n}\). "
                  r"Отрицательный показатель — это обратное число: \(a^{-n} = \frac{1}{a^n}\). "
                  r"Попробуй сначала задание 1 по этим правилам.",
        },
        "task_help": {
            "en": r"Task {n}: first write every number as a power of the same base - for example \(8 = 2^3\) and "
                  r"\(\frac{1}{4} = 2^{-2}\). Then add the exponents when multiplying and subtract them when "
                  r"dividing. Which base fits all the numbers in this task?",
            "ru": r"Задание {n}: сначала запиши все числа как степени одного основания — например, \(8 = 2^3\) и "
                  r"\(\frac{1}{4} = 2^{-2}\). Потом при умножении складывай показатели, при делении вычитай. "
                  r"Какое основание подходит ко всем числам в этом задании?",
        },
    },
    "Funções afins": {
        "theory": {
            "en": r"A função afim is \(f(x) = ax + b\): a is the slope (how much y changes when x grows by 1) and "
                  r"b is where the graph crosses the y-axis. From two points: \(a = \frac{y_2 - y_1}{x_2 - x_1}\), "
                  r"then put one point into the equation to find b.",
            "ru": r"Função afim — это \(f(x) = ax + b\): a — угловой коэффициент (на сколько меняется y, когда "
                  r"x растёт на 1), b — точка пересечения с осью y. По двум точкам: "
                  r"\(a = \frac{y_2 - y_1}{x_2 - x_1}\), затем подставь одну точку в уравнение и найди b.",
        },
        "task_help": {
            "en": r"Task {n}: start with the slope from the two points in the task, "
                  r"\(a = \frac{y_2 - y_1}{x_2 - x_1}\). Write down what you get - b is the next step.",
            "ru": r"Задание {n}: начни с углового коэффициента по двум точкам из задания: "
                  r"\(a = \frac{y_2 - y_1}{x_2 - x_1}\). Запиши, что получилось, — b найдём следующим шагом.",
        },
    },
}

_lock = threading.Lock()
_built = False


def is_guest():
    return session.get("guest") is True and not session.get("student_id")


def student_id():
    return STUDENT_ID


def get_db(lang=None):
    """The demo database in the guest's language (built on first use after each
    start). Never the real one."""
    global _built
    with _lock:
        if not _built:
            _build()
            _built = True
    lang = lang if lang in LANGUAGES else translations.current_lang()
    conn = sqlite3.connect(DEMO_DIR / f"demo-{lang}.db")
    conn.row_factory = sqlite3.Row
    return conn


def notifications(limit=8):
    """(the guest's notifications, unread count), like the real bell."""
    conn = get_db()
    rows = conn.execute(
        "SELECT * FROM notifications WHERE recipient_type = 'student' AND recipient_id = ? "
        "ORDER BY created_at DESC LIMIT ?", (student_id(), limit)).fetchall()
    conn.close()
    return rows, sum(1 for r in rows if not r["is_read"])


def hint_reply(assignment_id, action, task_number, lang):
    """The example reply the hint helper gives a guest. Nothing is stored, so the
    hints left go back to where they were on the next page load."""
    conn = get_db(lang)
    assignment = conn.execute("SELECT title FROM homework_assignments WHERE id = ? AND student_id = ?",
                              (assignment_id, student_id())).fetchone()
    used = conn.execute("SELECT COUNT(*) FROM hint_chat_messages WHERE assignment_id = ? AND role = 'user'",
                        (assignment_id,)).fetchone()[0]
    conn.close()
    if not assignment or assignment["title"] not in HINTS:
        raise LookupError(assignment_id)
    task_number = re.sub(r"[^\w.,()-]", "", (task_number or ""))[:20]
    message = homework_chat.build_user_message(action, task_number, lang)  # ValueError on anything else
    reply = HINTS[assignment["title"]][action][lang].replace("{n}", task_number)
    return {"reply": reply, "message": message, "remaining": max(0, homework_chat.HINT_LIMIT - used - 1)}


def _build():
    shutil.rmtree(DEMO_DIR, ignore_errors=True)
    SHEETS_DIR.mkdir(parents=True)
    now = datetime.now(timezone.utc).replace(microsecond=0)

    def ago(days, hours=0):
        return (now - timedelta(days=days, hours=hours)).strftime("%Y-%m-%d %H:%M:%S")

    for lang in LANGUAGES:
        sid, person = STUDENT_ID, STUDENTS[lang]
        conn = sqlite3.connect(DEMO_DIR / f"demo-{lang}.db")
        db.create_schema(conn)
        conn.execute(
            "INSERT INTO students (id, name, username, password_hash, language, curriculum, school_year, "
            "schedule_text, performance_narrative, first_login_at) VALUES (?, ?, ?, '!', ?, 'pt', ?, ?, ?, ?)",
            (sid, person["name"], f"demo-{lang}", lang, "9.º ano", person["schedule"], person["narrative"], ago(60)))
        ids = {}
        for hw in HOMEWORK:
            aid = conn.execute(
                "INSERT INTO homework_assignments (student_id, title, topic, created_at) VALUES (?, ?, ?, ?)",
                (sid, hw["title"], hw["topic"][lang], ago(hw["assigned"]))).lastrowid
            ids[hw["title"]] = aid
            if hw.get("sheet"):
                folder = SHEETS_DIR / str(aid)  # the sheets are Portuguese - one copy for both languages
                if not folder.exists():
                    folder.mkdir()
                    _draw_sheet(folder / "sheet.png", hw["title"], hw["sheet"])
                conn.execute("UPDATE homework_assignments SET task_files = ? WHERE id = ?",
                             (json.dumps(["sheet.png"]), aid))
            if "submitted" in hw:
                photos = [f"{i:02d}_photo.jpg" for i in range(hw.get("photos", 3))]
                reviewed = "reviewed" in hw
                problems = [{**p, "explanation": p["explanation"].get(lang, "")} for p in hw.get("problems", [])]
                conn.execute(
                    "INSERT INTO student_submissions (assignment_id, student_id, files, ai_status, tutor_grade, "
                    "tutor_comment, tutor_result, feedback_published, submitted_at, reviewed_at) "
                    "VALUES (?, ?, ?, 'done', ?, ?, ?, ?, ?, ?)",
                    (aid, sid, json.dumps(photos), hw.get("grade"), hw.get("comment", {}).get(lang),
                     json.dumps(problems) if reviewed else None, int(reviewed), ago(hw["submitted"]),
                     ago(hw["reviewed"]) if reviewed else None))
            for action in hw.get("used_hints", []):
                conn.execute("INSERT INTO hint_chat_messages (assignment_id, student_id, role, content) "
                             "VALUES (?, ?, 'user', ?)", (aid, sid, homework_chat.build_user_message(action, "", lang)))
                conn.execute("INSERT INTO hint_chat_messages (assignment_id, student_id, role, content) "
                             "VALUES (?, ?, 'assistant', ?)", (aid, sid, HINTS[hw["title"]][action][lang]))

        def notify(type_, title, aid, days, read):
            conn.execute("INSERT INTO notifications (recipient_type, recipient_id, type, title, link, is_read, "
                         "created_at) VALUES ('student', ?, ?, ?, ?, ?, ?)",
                         (sid, type_, title, f"/me/homeworks/{aid}", int(read), ago(days)))

        notify("feedback_published", translations.render("notif.graded", lang, title="Proporcionalidade direta",
                                                         grade="A"), ids["Proporcionalidade direta"], 21, True)
        notify("feedback_published", translations.render("notif.graded", lang, title="Equações do 1.º grau",
                                                         grade="B"), ids["Equações do 1.º grau"], 7, False)
        notify("new_assignment", translations.render("notif.new_assignment", lang, title="Potências e raízes"),
               ids["Potências e raízes"], 0, False)
        conn.commit()
        conn.close()


def _draw_sheet(path, title, lines):
    """A plain printed worksheet, drawn here so the demo needs no files in the repo.
    PyMuPDF's Helvetica has the Portuguese letters (ç, õ, º) Pillow's built-in font lacks."""
    pymupdf = image_utils._fitz()
    ink, rule = (32 / 255, 44 / 255, 69 / 255), (201 / 255, 212 / 255, 234 / 255)
    doc = pymupdf.open()
    page = doc.new_page(width=520, height=110 + 30 * len(lines))
    page.insert_text((36, 46), title, fontsize=22, fontname="helv", color=ink)
    page.draw_line((36, 62), (484, 62), color=rule, width=1)
    for i, line in enumerate(lines):
        page.insert_text((36, 92 + 30 * i), line, fontsize=15, fontname="helv", color=ink)
    page.get_pixmap(dpi=150).save(path)
    doc.close()
