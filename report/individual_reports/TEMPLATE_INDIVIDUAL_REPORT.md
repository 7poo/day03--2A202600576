# Individual Report: Lab 3 - Chatbot vs ReAct Agent

- **Student Name**: [Điền họ tên đầy đủ]
- **Student ID**: [Điền MSSV]
- **Date**: 2026-06-01

---

## I. Technical Contribution (15 Points)

### Modules Implemented

| Module | Mô tả đóng góp |
| :--- | :--- |
| `src/agent/agent.py` | Implement ReAct Agent v1: Thought-Action-Observation loop, 3-strategy JSON parser, hallucination detection |
| `src/agent/agent_v2.py` | Implement ReAct Agent v2: Few-Shot examples, Tool Schema Registry, per-step retry budget |
| `src/core/llm_provider.py` | Abstract base class `LLMProvider` — interface chung cho tất cả providers |
| `src/core/openai_provider.py` | OpenAI integration — `generate()`, `stream()`, usage tracking |
| `src/telemetry/logger.py` | `IndustryLogger` — structured JSON logging, daily log files |
| `src/telemetry/metrics.py` | `PerformanceTracker` — P50/P95/P99 latency, cost calculation, token efficiency |

### Code Highlights

**1. Robust JSON Parser với 3 Fallback Strategies (`src/agent/agent.py:274–317`)**

LLM thường trả về JSON theo nhiều format khác nhau. Implement 3 strategies theo thứ tự ưu tiên:

```python
# Strategy 1: Action: {"tool": ..., "args": ...}  ← chuẩn nhất
match = re.search(r"Action\s*:\s*(\{.+?\})\s*$", text, re.DOTALL | re.MULTILINE)

# Strategy 2: Action: ```json { ... } ```  ← LLM wrap trong markdown
match = re.search(r"Action\s*:\s*```(?:json)?\s*(\{.+?\})\s*```", text, re.DOTALL)

# Strategy 3: any JSON object after "Action"  ← fallback cuối cùng
match = re.search(r"Action\s*:.*?(\{[^{}]*\})", text, re.DOTALL)
```

Khi cả 3 fail → log `PARSE_ERROR` và inject correction hint vào history để LLM tự sửa ở step tiếp.

**2. Few-Shot Examples trong System Prompt (`src/agent/agent_v2.py:44–64`)**

V2 nhúng 2 interaction examples trực tiếp vào system prompt, giúp LLM hiểu format chính xác ngay từ lần đầu:

```python
FEW_SHOT_EXAMPLES = """
=== EXAMPLE INTERACTION 1 ===
User Query: What are the submissions for student STU001?

Thought: I need to look up student STU001's information.
Action: {"tool": "get_student_info", "args": {"student_id": "STU001"}}
Observation: {"student": {...}, "submissions": [...], "summary": {"num_submissions": 3}}

Thought: I now have all the information needed.
Final Answer: Student STU001 has 3 submissions on record.
"""
```

Kết quả: PARSE_ERROR giảm 83% (từ 6 xuống 1 trên 5 test cases).

**3. Tool Schema Pre-validation (`src/agent/agent_v2.py:118–133`)**

Validate required args trước khi gọi tool — tránh TypeError lặp lại:

```python
def _validate_tool_args(self, tool_name: str, args: Dict) -> Optional[str]:
    schema = TOOL_SCHEMAS.get(tool_name)
    missing = [k for k in schema["required"] if k not in args]
    if missing:
        return f"Missing required argument(s): {missing}. Example: {schema['example']}"
    return None
```

### Cách code tương tác với ReAct Loop

`agent.py` và `agent_v2.py` là core của ReAct loop. Mỗi iteration:
1. `_build_prompt()` — append history vào prompt
2. `LLMProvider.generate()` — gọi OpenAI/Gemini/Local
3. `_parse_action()` — extract JSON từ response
4. `_execute_tool()` — gọi tool function
5. Append `Thought + Action + Observation` vào `self.history`

`telemetry/logger.py` và `metrics.py` được gọi tại mỗi bước, ghi lại toàn bộ trace vào `logs/YYYY-MM-DD.log`.

---

## II. Debugging Case Study (10 Points)

### Problem: Agent v1 loop không thoát được khi tool args sai tên

**Mô tả**: Khi agent gọi `get_student_info` với `{"name": "STU001"}` thay vì `{"student_id": "STU001"}`, v1 nhận TypeError → observation generic → LLM không biết cần sửa gì → lặp lại cùng lỗi đến hết `max_steps`.

**Log Source** — `logs/sample_trace_2026-06-01.log`:

```json
{
  "timestamp": "2026-06-01T08:02:01.625000",
  "event": "TOOL_VALIDATION_ERROR",
  "data": {
    "step": 1, "retry": 1,
    "tool": "get_student_info",
    "args": {"name": "STU001"},
    "error": "Missing required argument(s) for 'get_student_info': ['student_id']. Correct format example: {\"tool\": \"get_student_info\", \"args\": {\"student_id\": \"STU001\"}}"
  }
}
```

**Diagnosis**: Nguyên nhân có 3 lớp:
1. **Prompt**: System prompt v1 chỉ mô tả tool bằng text ("Lấy thông tin sinh viên theo student_id") nhưng không có JSON example → LLM suy diễn arg name theo ngữ nghĩa (`name` nghe tự nhiên hơn `student_id`)
2. **Observation**: Khi TypeError xảy ra, v1 trả về `"[ERROR] Invalid arguments: got unexpected keyword argument 'name'"` — đây là Python error message, LLM không biết arg đúng cần là gì
3. **Loop**: Mỗi retry là 1 main step → 3 lần lỗi = mất 3/5 steps → TIMEOUT

**Solution**: Implement trong v2:
1. `TOOL_SCHEMAS` dict với `"required"` + `"example"` cho từng tool
2. `_validate_tool_args()` check TRƯỚC khi gọi function — fail fast với targeted hint
3. Per-step retry budget: retry không burn main step, agent có 2 cơ hội tự sửa mỗi step

**Kết quả đo được** (từ `experiments/results/ablation_results.md`):
- V1: Test Case 4 → TIMEOUT (step bị burn hết bởi lỗi format)
- V2: Test Case 4 → `final_answer` ở step 2, retry không tính step

---

## III. Personal Insights: Chatbot vs ReAct (10 Points)

### 1. Reasoning — Thought block giúp gì?

Thought block buộc LLM **externalize** reasoning thay vì "thinking in one shot". Khi viết Thought, LLM tự commit vào một hướng suy nghĩ và Observation của bước đó sẽ validate ngay — nếu sai, correction xảy ra ở bước tiếp, không phải sau khi đã trả lời người dùng.

Ví dụ cụ thể từ `chatbot.py` Test Case 3:
- **Chatbot**: Trả lời thẳng với giả định "Macbook Pro M3 is available at $1,200" — hallucinate với 100% confidence
- **Agent**: `Thought: I need to use check_stock tool` → `Observation: [ERROR] Tool 'check_stock' does not exist` → LLM buộc phải acknowledge giới hạn của mình

### 2. Reliability — Khi nào Agent tệ hơn Chatbot?

Agent tệ hơn trong 2 trường hợp rõ ràng:
- **Câu hỏi không cần tool**: "25 * 4 + 10 = ?" — Chatbot trả lời đúng ngay (1 LLM call), Agent mất ít nhất 2 calls và ~2× latency chỉ để kết luận "tôi có thể tính tay được, không cần tool"
- **Khi tool bị down**: Nếu DB tool fail, agent bị stuck loop và cuối cùng TIMEOUT — Chatbot thì vẫn trả lời dù có thể không chính xác

Trade-off rõ ràng: Agent đúng hơn khi cần external data, Chatbot nhanh hơn khi câu hỏi nằm trong training knowledge.

### 3. Observation — Feedback ảnh hưởng next step thế nào?

Observation là "ground truth injection" — nó override hoàn toàn những gì LLM "nghĩ" từ training data. Trong session 3 của sample trace, agent nhận:

```
Observation: [SYSTEM ARG ERROR] Missing required argument(s) for 'get_student_info': ['student_id'].
Correct format example: {"tool": "get_student_info", "args": {"student_id": "STU001"}}
```

Ngay lập tức ở retry tiếp theo, agent gửi đúng args — không cần thêm instruction từ user. Điều này chứng minh rằng **Observation chất lượng cao** (có ví dụ cụ thể, không chỉ error message) là yếu tố quyết định tốc độ self-correction của agent.

---

## IV. Future Improvements (5 Points)

### Scalability: Async Tool Execution với Fan-out

Khi agent cần query nhiều sinh viên cùng lúc, sequential tool calls rất chậm. Giải pháp: `AsyncReActAgent` với `asyncio.gather`:

```python
# Thay vì loop tuần tự
results = await asyncio.gather(*[
    self.execute_tool_async("get_student_info", {"student_id": sid})
    for sid in ["STU001", "STU002", "STU003"]
])
```

Latency giảm từ `N × tool_latency` xuống `max(tool_latency)`.

### Safety: Supervisor LLM Pattern

Thêm một LLM "supervisor" audit mỗi Action trước khi execute — reject nếu action có potential harm (DELETE query, external API call không được authorize):

```python
class SupervisedReActAgent(ReActAgentV2):
    def _execute_tool(self, tool_name, args):
        risk = self.supervisor.assess_risk(tool_name, args)
        if risk.level == "HIGH":
            return f"[BLOCKED] Action rejected by supervisor: {risk.reason}"
        return super()._execute_tool(tool_name, args)
```

### Performance: Dynamic Tool Selection với Vector DB

Khi số tools tăng lên (>20), liệt kê tất cả trong system prompt tốn tokens và loãng signal. Giải pháp: embed tool descriptions, chỉ inject top-K relevant tools:

```python
relevant_tools = vector_db.similarity_search(user_query, k=5)
agent = ReActAgentV2(llm, tools=relevant_tools)
# Thay vì inject tất cả 20+ tools, chỉ inject 5 tools liên quan nhất
```

Giảm ~60% prompt tokens cho queries đơn giản.

---

> [!NOTE]
> Đổi tên file này thành `REPORT_[TÊN_BẠN].md` và đặt vào thư mục `report/individual_reports/` trước khi nộp.
