import json
import os
from functools import lru_cache

from openai import OpenAI


@lru_cache(maxsize=8)
def _load_prompt_template(name):
    prompt_dir = os.path.join(os.path.dirname(os.path.abspath(__file__)), "prompts")
    with open(os.path.join(prompt_dir, name), encoding="utf-8") as f:
        return f.read()


@lru_cache(maxsize=1)
def _get_client():
    return OpenAI(
        api_key=os.getenv("DEEPSEEK_API_KEY"),
        base_url=os.getenv("DEEPSEEK_BASE_URL", "https://api.deepseek.com"),
    )


@lru_cache(maxsize=256)
def review_translation(english_sentence, reference_translation, user_translation):
    template = _load_prompt_template("review_prompt.txt")
    prompt = template.format(
        english_sentence=english_sentence,
        reference_translation=reference_translation,
        user_translation=user_translation,
    )

    client = _get_client()
    resp = client.chat.completions.create(
        model="deepseek-chat",
        max_tokens=512,
        temperature=0.4,
        messages=[{"role": "user", "content": prompt}],
        timeout=60,
    )
    raw = resp.choices[0].message.content.strip()

    # Strip markdown fences if present
    if raw.startswith("```"):
        lines = raw.split("\n")
        raw = "\n".join(lines[1:]) if len(lines) > 1 else raw
    if raw.endswith("```"):
        raw = raw[:-3].strip()

    return json.loads(raw)
