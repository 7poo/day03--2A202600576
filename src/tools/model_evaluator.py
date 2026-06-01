"""Safe LLM wrapper to evaluate a submission using provided rubric.

Requires OPENAI_API_KEY in environment or pass api_key param.
"""
import os
import json
import time
import re
from typing import Dict, Any, Optional

try:
    import openai
except Exception:
    openai = None

from src.telemetry.logger import logger


DEFAULT_SCHEMA_KEYS = ["score", "breakdown", "feedback"]


def _extract_json(text: str) -> Optional[Dict[str, Any]]:
    # Try direct load
    try:
        return json.loads(text)
    except Exception:
        pass
    # Extract first JSON object found
    m = re.search(r"\{.*\}", text, flags=re.S)
    if m:
        try:
            return json.loads(m.group(0))
        except Exception:
            return None
    return None


def validate_schema(obj: Dict[str, Any]) -> bool:
    if not isinstance(obj, dict):
        return False
    for k in DEFAULT_SCHEMA_KEYS:
        if k not in obj:
            return False
    # basic numeric check
    try:
        float(obj.get('score'))
    except Exception:
        return False
    return True


def evaluate_submission(submission_text: str, rubric: Dict[str, Any], api_key: Optional[str] = None, model: str = 'gpt-4o-mini') -> Dict[str, Any]:
    """Call LLM to evaluate a submission. Returns structured dict.

    Returns keys: status, score, breakdown, feedback, raw_text, tokens, latency_ms
    """
    logger.log_event("MODEL_EVAL_START", {"model": model})
    if openai is None:
        msg = "openai package not installed"
        logger.log_event("MODEL_EVAL_ERROR", {"error": msg})
        return {"status": "error", "error": msg}

    if api_key:
        openai.api_key = api_key
    else:
        openai.api_key = os.getenv('OPENAI_API_KEY')

    system = (
        "You are an unbiased grader. Given a submission and a rubric, return EXACT JSON with keys: score (0-100), "
        "breakdown (object), feedback (string). Output raw JSON only, no markdown."
    )

    user_prompt = f"RUBRIC:{json.dumps(rubric)}\n\nSUBMISSION:\n{submission_text}\n\nReturn JSON only."

    messages = [
        {"role": "system", "content": system},
        {"role": "user", "content": user_prompt}
    ]

    start = time.time()
    try:
        resp = openai.ChatCompletion.create(
            model=model,
            messages=messages,
            temperature=0.0,
            max_tokens=512
        )
    except Exception as e:
        logger.log_event("MODEL_EVAL_ERROR", {"error": str(e)})
        return {"status": "error", "error": str(e)}

    latency = int((time.time() - start) * 1000)
    raw = resp['choices'][0]['message']['content'] if resp and 'choices' in resp and len(resp['choices'])>0 else ''
    tokens = resp.get('usage') if isinstance(resp, dict) else None

    # Try parse
    parsed = _extract_json(raw)
    parse_status = 'ok' if parsed and validate_schema(parsed) else 'fail'

    if parse_status == 'fail':
        # Retry once with extraction prompt
        logger.log_event('MODEL_EVAL_PARSE_FAIL', {'latency_ms': latency})
        retry_prompt = (
            "The previous response included extra text. PLEASE RETURN ONLY THE RAW JSON OBJECT, nothing else. "
            "If you cannot, return an empty JSON object {}."
        )
        try:
            resp2 = openai.ChatCompletion.create(
                model=model,
                messages=[{"role":"system","content":system},{"role":"user","content":retry_prompt + '\n\n' + user_prompt}],
                temperature=0.0,
                max_tokens=512
            )
            raw2 = resp2['choices'][0]['message']['content']
            parsed = _extract_json(raw2)
            parse_status = 'ok' if parsed and validate_schema(parsed) else 'fail'
            raw = raw2
            tokens = resp2.get('usage')
        except Exception as e:
            logger.log_event('MODEL_EVAL_RETRY_ERROR', {'error': str(e)})

    result = {
        'status': 'ok' if parse_status == 'ok' else 'needs_human_review',
        'raw_text': raw,
        'parse_status': parse_status,
        'latency_ms': latency,
        'usage': tokens
    }

    if parse_status == 'ok':
        # normalize score to 0-100
        score = float(parsed.get('score'))
        if score < 0:
            score = 0.0
        if score > 100:
            score = 100.0
        parsed['score'] = score
        result.update(parsed)

    logger.log_event('MODEL_EVAL_END', {'status': result['status'], 'latency_ms': latency})
    return result


if __name__ == '__main__':
    # Quick local test harness (does not send key) -- set OPENAI_API_KEY env to run
    sample = 'This is a short student essay. The student explains X and Y.'
    rubric = {'technical': 40, 'debugging': 30, 'insights': 20, 'future': 10}
    res = evaluate_submission(sample, rubric, api_key=None, model='gpt-4o-mini')
    print(res)
