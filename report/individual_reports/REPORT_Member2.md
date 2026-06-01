
## I. Technical Contribution (15 Points)

### Modules Implemented

| Module | Vai trò |
| :--- | :--- |
| `src/tools/data_access.py` | DataAccess class — SQLite + CSV dual backend |
| `src/tools/db_tool.py` | DBTool wrapper — expose `get_student_info` cho agent |
| `src/tools/model_evaluator.py` | LLM-based submission grader với retry JSON |
| `src/tools/scoring_engine.py` | ScoringEngine — tính điểm nhóm + cá nhân |
| `docs/tool_evolution.md` | Tài liệu tiến hóa tool spec v0 → v2 |

### Code Highlights

**1. DataAccess dual backend (`data_access.py`)**

Tự động detect SQLite hoặc CSV tùy môi trường:

```python
class DataAccess:
    def __init__(self, db_path=None, csv_dir=None):
        if db_path and os.path.exists(db_path):
            self.backend = "sqlite"
            self.conn = sqlite3.connect(db_path)
        else:
            self.backend = "csv"
            self.csv_dir = csv_dir
```

**2. Retry JSON trong model_evaluator (`model_evaluator.py`)**

LLM đôi khi trả về malformed JSON khi chấm điểm — retry tối đa 3 lần:

```python
for attempt in range(max_retries):
    response = llm.generate(prompt)
    try:
        result = json.loads(extract_json(response))
        validate_schema(result)   # check required fields
        return result
    except (json.JSONDecodeError, ValidationError):
        if attempt == max_retries - 1:
            return {"status": "error", "score": 0, "feedback": "Parse failed"}
        continue
```

**3. ScoringEngine với weight mapping (`scoring_engine.py`)**

```python
GROUP_WEIGHTS = {
    "chatbot_baseline": 2,
    "agent_v1_working": 7,
    "agent_v2_improved": 7,
    "tool_design_evolution": 4,
    "trace_quality": 9,
    "evaluation_analysis": 7,
    "flowchart_insight": 5,
    "code_quality": 4,
}
```

### Interaction với ReAct Loop

`DBTool.get_student_info()` là tool chính agent dùng để truy vấn data thực. `ModelEvaluator.evaluate_submission()` là advanced tool — agent gọi nó như một "sub-agent" để chấm điểm bài làm mà không cần human reviewer. Kết hợp 2 tools này, agent có thể tự động: lookup → evaluate → summarize trong 3-4 steps.

---

## II. Debugging Case Study (10 Points)

### Problem: ModelEvaluator trả về non-JSON response

**Input**: Agent gọi `evaluate_submission` với rubric dài (>500 tokens).

**Hiện tượng**: LLM chấm điểm trả về prose text thay vì JSON structured output khi rubric quá dài — LLM "quên" format output.

**Log source** — event từ `model_evaluator.py`:

```json
{"event": "EVALUATOR_PARSE_ERROR", "data": {
  "attempt": 1,
  "error": "json.JSONDecodeError: Expecting value: line 1 column 1",
  "raw_response": "Based on the submission, I would give this a score of 7 out of 10..."
}}
```

**Diagnosis**: Prompt của evaluator đặt instruction "return JSON" ở **đầu** prompt, nhưng khi rubric quá dài, instruction bị "drown out" bởi rubric content. LLM ưu tiên follow rubric format hơn output format instruction.

**Solution**: Đặt JSON output instruction ở **cuối** prompt (recency bias của LLM), và thêm explicit reminder:

```python
prompt = f"""
Rubric: {rubric}

Submission: {submission_text}

IMPORTANT: You MUST respond with ONLY valid JSON in this exact format:
{{"score": int, "breakdown": {{}}, "feedback": "string"}}
No prose. No explanation. Only JSON.
"""
```

**Kết quả**: Parse success rate tăng từ ~70% → ~95% trên các rubric dài.

---

## III. Personal Insights: Chatbot vs ReAct (10 Points)

### 1. Reasoning — Thought block giúp gì?

Tools làm cho agent "grounded" — không thể hallucinate kết quả khi kết quả thực được inject vào context qua Observation. Chatbot trả lời câu hỏi về DB bằng cách suy luận từ training data; agent **thực sự query DB** và trả lời từ data thực.

### 2. Reliability — Khi nào Agent tệ hơn Chatbot?

Agent gặp vấn đề với **ambiguous tool selection** — khi query có thể dùng nhiều tools khác nhau, agent đôi khi chọn sai tool ở step đầu và phải backtrack. Chatbot không có vấn đề này vì không có tools để chọn.

Ví dụ: "Sinh viên nào có điểm cao nhất?" — agent có thể dùng `get_student_info(STU001)`, rồi `get_student_info(STU002)`, rồi compare. Không có tool `list_all_students_sorted_by_gpa` → agent phải làm nhiều tool calls không cần thiết. Chatbot chỉ cần 1 call với câu trả lời gần đúng.

### 3. Observation — Feedback ảnh hưởng next step thế nào?

Observation từ `model_evaluator` đặc biệt thú vị — nó là kết quả của **một LLM call khác**. Điều này tạo ra chain: User → Agent LLM → Evaluator LLM → Observation → Agent LLM. Feedback quality của Observation phụ thuộc vào cả 2 LLM, và error từ Evaluator (parse fail, timeout) được propagate ngược lại làm Agent phải handle thêm.

---

## IV. Future Improvements (5 Points)

### Scalability: Multi-Agent với Specialized Roles

Thay vì 1 agent làm tất cả, chia thành specialized agents:
- **Router Agent**: parse query và route đến đúng specialist
- **DB Agent**: chỉ có data access tools
- **Grading Agent**: chỉ có evaluator tools
- **Coordinator**: tổng hợp kết quả

Framework như LangGraph hoặc AutoGen hỗ trợ pattern này natively.

### Safety: Tool Call Rate Limiting

Thêm rate limiter để prevent agent vô tình spam API:

```python
class RateLimitedTool:
    def __init__(self, tool_fn, max_calls_per_minute=10):
        self.tool_fn = tool_fn
        self.calls = []

    def __call__(self, **kwargs):
        self._check_rate_limit()
        return self.tool_fn(**kwargs)
```

### Performance: Caching Tool Results

Nếu agent gọi `get_student_info("STU001")` 2 lần trong cùng session, kết quả giống nhau — cache lại để tránh tốn DB query và tokens:

```python
@lru_cache(maxsize=128)
def cached_get_student_info(student_id: str) -> str:
    return db_tool.get_student_info(student_id)
```

---

> *Nộp file này với tên `REPORT_[TÊN_BẠN].md` vào thư mục `report/individual_reports/`*
