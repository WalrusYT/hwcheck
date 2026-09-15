"""Hint-only chatbot scoped to one homework assignment.

Gives guidance, not answers: it can explain concepts, ask guiding
questions, name a relevant formula or first step, and check the student's
own reasoning, but must never state a final answer to an assigned problem
or solve one end-to-end.
"""

import os

from openai import OpenAI

from image_utils import file_to_image_data_urls

MODEL = os.environ.get("OPENAI_MODEL", "gpt-4o")
HISTORY_LIMIT = 20

# Per-assignment cap on how many hint requests a student can make - the chat
# isn't free-form (see build_user_message below), so each request is one of
# a small set of fixed actions, and each one costs one "coin."
HINT_LIMIT = 3

ACTION_PROMPTS = {
    "theory": {
        "en": "Please remind me the key theory and concepts I need for this assignment.",
        "ru": "Пожалуйста, напомни мне ключевую теорию и понятия, нужные для этого задания.",
    },
    "task_help": {
        "en": (
            "Please help me with task {task_number} - explain what it's asking "
            "and give me a hint on how to start, without giving away the final answer."
        ),
        "ru": (
            "Пожалуйста, помоги мне с заданием {task_number} - объясни, что там "
            "нужно сделать, и дай подсказку, с чего начать, не называя итоговый ответ."
        ),
    },
}

SYSTEM_PROMPT = {
    "en": (
        "You are a friendly math tutoring assistant helping a student with one "
        "specific homework assignment, whose problem sheet is attached as "
        "image(s) below. Your job is to help the student think it through "
        "themselves, not to do it for them.\n\n"
        "Rules:\n"
        "- You may explain relevant concepts, ask guiding questions, point out "
        "what a problem is testing, suggest a first step or relevant formula, "
        "and check whether the student's own reasoning or partial work is on "
        "the right track.\n"
        "- Never state the final numeric or algebraic answer to any problem on "
        "this sheet, and never fully solve a problem end-to-end for the "
        "student.\n"
        "- If the student directly asks for 'the answer' or to 'just solve it', "
        "politely decline and offer a hint or a guiding question instead.\n"
        "- Keep responses short and conversational - a couple of sentences, not "
        "an essay.\n"
        "- When writing math notation (fractions, exponents, roots, etc.), wrap "
        "it in inline LaTeX delimiters like \\(x = \\frac{1}{2}\\) so it "
        "renders correctly.\n"
        "- Respond in English."
    ),
    "ru": (
        "Ты - дружелюбный ассистент-репетитор по математике, который помогает "
        "ученику с одним конкретным домашним заданием; лист с задачами приложен "
        "ниже в виде изображений. Твоя задача - помочь ученику самому "
        "разобраться, а не решить задание за него.\n\n"
        "Правила:\n"
        "- Ты можешь объяснять понятия, задавать наводящие вопросы, указывать, "
        "что именно проверяет задача, предлагать первый шаг или нужную формулу, "
        "и проверять, на правильном ли пути рассуждения или черновик ученика.\n"
        "- Никогда не называй итоговый числовой или алгебраический ответ ни к "
        "одной задаче из этого листа и никогда не решай задачу целиком за "
        "ученика.\n"
        "- Если ученик прямо просит 'дай ответ' или 'просто реши', вежливо "
        "откажи и предложи подсказку или наводящий вопрос вместо этого.\n"
        "- Отвечай коротко и по-дружески - пара предложений, не эссе.\n"
        "- При записи математических выражений (дроби, степени, корни и т.д.) "
        "оборачивай их в LaTeX-разделители вида \\(x = \\frac{1}{2}\\), чтобы "
        "они отображались корректно.\n"
        "- Отвечай на русском языке."
    ),
}


class ChatError(Exception):
    pass


def build_user_message(action, task_number, lang="en"):
    """Turns a button press into the actual message sent to the model - the
    student picks from a fixed menu rather than typing free text, so there's
    a small, known set of possible questions rather than an open chat."""
    if action not in ACTION_PROMPTS:
        raise ValueError(f"Unknown action: {action}")
    template = ACTION_PROMPTS[action].get(lang, ACTION_PROMPTS[action]["en"])
    if action == "task_help":
        task_number = (task_number or "").strip()[:20]
        if not task_number:
            raise ValueError("task_number is required for task_help")
        return template.format(task_number=task_number)
    return template


def reply(task_file_paths, history, lang="en"):
    """task_file_paths: list of pathlib.Path to the assignment's problem sheet.
    history: list of {"role": "user"|"assistant", "content": str}, oldest first,
    already including the latest user message. Returns the assistant's reply text.
    """
    client = OpenAI()
    system_prompt = SYSTEM_PROMPT.get(lang, SYSTEM_PROMPT["en"])

    messages = [{"role": "system", "content": system_prompt}]

    trimmed = history[-HISTORY_LIMIT:]
    first_user_index = next((i for i, m in enumerate(trimmed) if m["role"] == "user"), None)

    for i, turn in enumerate(trimmed):
        if i == first_user_index and task_file_paths:
            content = [{"type": "text", "text": turn["content"]}]
            for file_path in task_file_paths:
                for url in file_to_image_data_urls(file_path):
                    content.append({"type": "image_url", "image_url": {"url": url}})
            messages.append({"role": "user", "content": content})
        else:
            messages.append({"role": turn["role"], "content": turn["content"]})

    try:
        response = client.chat.completions.create(model=MODEL, messages=messages)
    except Exception as exc:
        raise ChatError(str(exc)) from exc

    return response.choices[0].message.content
