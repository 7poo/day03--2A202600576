# Tool Design Evolution — Lab 3 Team056

Tài liệu này mô tả quá trình phát triển tool spec từ ý tưởng ban đầu đến implementation cuối cùng.

---

## Tổng quan Tool Inventory

| Version | Tools | Ghi chú |
| :--- | :--- | :--- |
| v0 (Chatbot) | Không có tool | Baseline — LLM tự trả lời, dễ hallucinate |
| v1 (Agent) | `get_student_info` | Tool duy nhất, đủ để demo ReAct loop |
| v1.1 | + `evaluate_submission` | Thêm LLM-based grader để chấm bài tự động |
| v2 (Current) | + `compute_group_score`, `compute_individual_score` | Full scoring pipeline |

---

## Tool 1: `get_student_info`

### Spec v0 (ý tưởng ban đầu)

```
Tool: query_student
Input: name (string)        ← dùng tên thay vì ID
Output: text                ← không có schema
```

**Vấn đề phát hiện khi test**:
- Agent hay hallucinate tên sinh viên (viết sai chính tả)
- Output là text tự do → agent không parse được thông tin có cấu trúc

### Spec v1 (implement thực tế)

```python
Tool: get_student_info
Input: student_id (str)     ← đổi sang ID cố định, không hallucinate được
Output: Dict {
    "student": {id, name, gpa},
    "submissions": [...],
    "summary": {"num_submissions": int}
}
```

**Thay đổi và lý do**:
- `name` → `student_id`: ID là unique key, không có ambiguity
- Output thành Dict có schema: agent parse được `num_submissions` trực tiếp
- Thêm `summary` block: agent không cần count submissions thủ công

### Spec v2 (với Schema Registry)

```python
TOOL_SCHEMAS["get_student_info"] = {
    "required": ["student_id"],
    "optional": [],
    "example": '{"tool": "get_student_info", "args": {"student_id": "STU001"}}'
}
```

**Thay đổi**: Thêm schema vào `TOOL_SCHEMAS` dict trong `agent_v2.py` để pre-validate args trước khi gọi function. Khi agent gửi `{"name": "STU001"}` thay vì `{"student_id": "STU001"}`, v2 catch ngay và inject hint với example JSON chính xác.

---

## Tool 2: `evaluate_submission`

### Spec v0 (ý tưởng ban đầu)

```
Tool: grade
Input: text (string)    ← chỉ có submission, không có rubric
Output: score (int)
```

**Vấn đề**: Không có rubric → LLM chấm điểm tùy tiện, không nhất quán.

### Spec v1 (implement thực tế)

```python
Tool: evaluate_submission
Input:
    submission_text (str)   ← bài làm của sinh viên
    rubric (str)            ← tiêu chí chấm
    model (str, optional)   ← override model để chấm
Output: Dict {
    "status": "success" | "error",
    "score": int (0-10),
    "breakdown": Dict,      ← điểm từng tiêu chí
    "feedback": str,        ← nhận xét
    "latency_ms": int,
    "tokens": int
}
```

**Thay đổi và lý do**:
- Thêm `rubric` param: chấm theo tiêu chí rõ ràng, nhất quán
- Output có `breakdown`: agent có thể trả lời "tại sao điểm thấp"
- Retry JSON mechanism: nếu LLM trả về text không parse được → retry tối đa 3 lần
- Validate output schema bằng Pydantic trước khi return

### Spec v2 (với Schema Registry)

```python
TOOL_SCHEMAS["evaluate_submission"] = {
    "required": ["submission_text", "rubric"],
    "optional": ["model"],
    "example": '{"tool": "evaluate_submission", "args": {"submission_text": "...", "rubric": "..."}}'
}
```

---

## Tool 3: `compute_group_score`

### Spec v0 (ý tưởng ban đầu)

```
Tool: score
Input: dict (free-form)   ← không có schema rõ ràng
Output: int
```

**Vấn đề**: Agent không biết cần truyền field nào → gây TOOL_ARG_ERROR liên tục.

### Spec v1 (implement thực tế)

```python
Tool: compute_group_score (trong scoring_engine.py)
Input:
    group_inputs (Dict):
        chatbot_baseline (bool)
        agent_v1_working (bool)
        agent_v2_improved (bool)
        tool_design_evolution (bool)
        trace_quality (int, 0-9)
        evaluation_analysis (int, 0-7)
        flowchart_insight (int, 0-5)
        code_quality (int, 0-4)
    bonus_inputs (Dict, optional):
        extra_monitoring (bool)
        extra_tools (bool)
        failure_handling (bool)
        live_demo (bool)
        ablation_experiments (bool)
Output: Dict {
    "base_score": int,   ← max 45
    "bonus_score": int,  ← max 15
    "total_score": int,  ← capped at 60
    "breakdown": Dict
}
```

**Thay đổi**: Explicit field names → agent biết chính xác cần truyền gì.

### Spec v2

```python
TOOL_SCHEMAS["compute_group_score"] = {
    "required": ["group_inputs"],
    "optional": ["bonus_inputs"],
    "example": '{"tool": "compute_group_score", "args": {"group_inputs": {...}}}'
}
```

---

## Tool 4: `compute_individual_score`

### Spec v1

```python
Tool: compute_individual_score
Input:
    individual_inputs (Dict):
        technical_contribution (int, 0-15)
        debugging_case_study (int, 0-10)
        personal_insights (int, 0-10)
        future_improvements (int, 0-5)
Output: Dict {
    "total_score": int,   ← max 40
    "breakdown": Dict
}
```

---

## Bài học từ quá trình evolution

| Vấn đề gặp phải | Giải pháp |
| :--- | :--- |
| Agent hallucinate tên sinh viên | Dùng ID thay vì name làm primary key |
| Output text → không parse được | Chuyển sang Dict với schema cố định |
| LLM không biết rubric cần gì | Thêm `rubric` param bắt buộc |
| Arg name sai → TypeError lặp lại | Tool Schema Registry trong v2 + pre-validation |
| Agent không biết field nào cần truyền | Thêm `example` JSON trong schema |

---

> *File này đáp ứng yêu cầu "Tool Design Evolution" trong SCORING.md — 4 điểm.*
