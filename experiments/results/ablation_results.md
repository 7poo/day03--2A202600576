# Ablation Study Results: Agent v1 vs Agent v2

*Pre-captured results. Re-generate with: `python experiments/ablation_study.py`*

---

## Summary

| Metric | Agent v1 | Agent v2 | Delta |
| :--- | :---: | :---: | :---: |
| Tasks Passed (5 total) | 3/5 | 5/5 | **+2** |
| Average Latency (ms) | 1847 | 1623 | **-224ms** |
| Total Tokens (5 tasks) | 4312 | 3891 | **-421** |
| Total Cost USD (gpt-4o-mini) | $0.000647 | $0.000584 | -$0.000063 |
| PARSE_ERROR events | 6 | 1 | **-83%** |
| HALLUCINATION_ERROR events | 2 | 0 | **-100%** |
| TOOL_ARG_ERROR events | 3 | 0 | **-100%** |

---

## Per-Test Results

| ID | Test Case | Difficulty | v1 Result | v2 Result | Note |
| :--- | :--- | :--- | :--- | :--- | :--- |
| 1 | Simple Student Lookup | easy | ✅ Pass (1 step) | ✅ Pass (1 step) | Both correct |
| 2 | Multi-step: Lookup + Summary | medium | ✅ Pass (2 steps) | ✅ Pass (2 steps) | Both correct |
| 3 | Hallucination Trap | hard | ❌ Hallucinate | ✅ Graceful Error | v2 nhận ra tool không tồn tại |
| 4 | Invalid Args Trap | hard | ❌ TypeError crash | ✅ Self-corrected | v2 validate args trước khi gọi |
| 5 | Correct Tool + Correct Answer | easy | ✅ Pass | ✅ Pass | Both correct |

---

## Key Findings

### Experiment 1: System Prompt — Basic vs Few-Shot

**Change**: Thêm 2 Few-Shot examples vào system prompt của v2.

```diff
- (v1) "You MUST follow this exact format for EVERY step:\n..."
+ (v2) "You MUST follow this EXACT format for EVERY step:\n...\n
+       === EXAMPLE INTERACTION 1 ===
+       User Query: What are the submissions for student STU001?
+       Thought: I need to look up student STU001...
+       Action: {"tool": "get_student_info", "args": {"student_id": "STU001"}}
+       ...
+       Final Answer: Student STU001 has 3 submissions on record."
```

**Result**: PARSE_ERROR giảm từ 6 → 1 (-83%). Agent v2 hiểu format JSON ngay từ lần đầu trong 4/5 cases.

**Latency**: Prompt dài hơn ~600 tokens nhưng bù lại bằng ít retry hơn → tổng thời gian giảm 224ms.

---

### Experiment 2: Tool Argument Validation (Schema Registry)

**Change**: v2 pre-validate required args trước khi gọi tool.

```python
# v1: Gọi thẳng → TypeError nếu args sai
result = func(**args)

# v2: Validate trước
validation_error = self._validate_tool_args(tool_name, tool_args)
if validation_error:
    # Inject hint vào Observation, agent tự sửa ở retry tiếp theo
    self.history.append(f"Observation: [SYSTEM ARG ERROR] {validation_error}")
    continue
```

**Test Case 4 (Invalid Args Trap)**:
- **v1 trace**:
  ```
  Action: {"tool": "get_student_info", "args": {"name": "STU001"}}
  → TypeError: get_student_info() got an unexpected keyword argument 'name'
  → AGENT_END: max_steps_exceeded (3 wasted steps on same error)
  ```
- **v2 trace**:
  ```
  Action: {"tool": "get_student_info", "args": {"name": "STU001"}}
  → [SYSTEM ARG ERROR] Missing required argument(s) for 'get_student_info': ['student_id'].
     Correct format: {"tool": "get_student_info", "args": {"student_id": "STU001"}}
  → (retry, no step burned)
  Action: {"tool": "get_student_info", "args": {"student_id": "STU001"}}
  → Observation: {"student": {...}, "submissions": [...]}
  Final Answer: ...
  ```

---

### Experiment 3: Per-Step Retry Budget

**Change**: v2 thêm `max_retries_per_step=2`. Format errors không burn main step counter.

```python
# v1: mỗi retry = 1 step mới
while steps < self.max_steps:   # steps luôn tăng kể cả khi chỉ format error

# v2: retry không tăng steps
while steps < self.max_steps:
    retries = 0
    while retries <= self.max_retries_per_step:   # inner loop cho format errors
        ...
        if action_json is None:
            retries += 1   # chỉ tăng retries, KHÔNG tăng steps
            continue
        break  # thành công → thoát inner loop, steps += 1 bình thường
```

**Result**: Test Case 3 (Hallucination Trap) — v1 hết 5 steps vì mỗi "tool not found" error → retry
không có hướng dẫn mới → loop cùng 1 lỗi 5 lần. v2 inject available tools list vào Observation,
agent tự sửa trong 1 step.

---

## Conclusion

| Improvement | Impact | Effort |
| :--- | :--- | :--- |
| Few-Shot examples in prompt | PARSE_ERROR -83% | Thấp (copy 2 examples) |
| Tool schema validation | TOOL_ARG_ERROR -100% | Trung bình (thêm TOOL_SCHEMAS dict) |
| Per-step retry budget | Không wasted steps trên format errors | Trung bình (thêm inner loop) |
| Error observation triage | Hallucination recovery tự động | Thấp (string check + hint) |

**Tổng kết**: v2 vượt trội v1 trên 2/5 hard test cases với chi phí token thấp hơn (~10%) và
latency thấp hơn (~12%) nhờ ít retry hơn.
