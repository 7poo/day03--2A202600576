# Individual Report: Lab 3 - Chatbot vs ReAct Agent

- **Student Name**: [Điền tên thành viên 1]
- **Student ID**: [Điền MSSV]
- **Date**: 2026-06-01

---

## I. Technical Contribution (15 Points)

### Modules Implemented

| Module | Vai trò |
| :--- | :--- |
| `src/agent/agent.py` | ReAct Agent v1 — core Thought-Action-Observation loop |
| `src/agent/agent_v2.py` | ReAct Agent v2 — Few-Shot + Schema Validation + Per-step retry |
| `src/core/llm_provider.py` | Abstract base class cho LLM providers |
| `src/core/openai_provider.py` | OpenAI API integration |

### Code Highlights

**1. JSON Parser với 3 fallback strategies (`agent.py:274–317`)**

Vấn đề thực tế: LLM đôi khi wrap JSON trong markdown fence (\`\`\`json...\`\`\`) hoặc thêm whitespace thừa. 3 strategies đảm bảo parse được mọi trường hợp:

```python
# Strategy 1: raw JSON sau "Action:"
match = re.search(r"Action\s*:\s*(\{.+?\})\s*$", text, re.DOTALL | re.MULTILINE)

# Strategy 2: markdown fence
match = re.search(r"Action\s*:\s*```(?:json)?\s*(\{.+?\})\s*```", text, re.DOTALL)

# Strategy 3: first JSON object sau "Action"
match = re.search(r"Action\s*:.*?(\{[^{}]*\})", text, re.DOTALL)
```

**2. Tool Schema Registry (`agent_v2.py:18–42`)**

Pre-validate required args trước khi gọi function — tránh TypeError lặp lại trong ReAct loop:

```python
TOOL_SCHEMAS = {
    "get_student_info": {
        "required": ["student_id"],
        "example": '{"tool": "get_student_info", "args": {"student_id": "STU001"}}',
    },
    ...
}
```

**3. Per-step retry budget (`agent_v2.py:103–147`)**

Format error không burn main step counter — agent có thêm cơ hội tự sửa:

```python
while steps < self.max_steps:
    steps += 1
    retries = 0
    while retries <= self.max_retries_per_step:   # inner loop
        ...
        if action_json is None:
            retries += 1   # chỉ tăng retries, KHÔNG tăng steps
            continue
        break
```

### Interaction với ReAct Loop

`agent_v2.py` được thiết kế để drop-in replace `agent.py` — cùng interface `run(user_input) -> str`, cùng tool format `{"name": ..., "description": ..., "function": ...}`. Grader chỉ cần thay `create_agent()` → `create_agent_v2()`.

---

## II. Debugging Case Study (10 Points)

### Problem: Agent v1 bị stuck khi tool args sai tên

**Input query**: "Lấy thông tin sinh viên STU001 từ hệ thống."

**Hiện tượng**: Agent v1 gọi đúng tool nhưng dùng `name` thay vì `student_id` → TypeError → lặp lại lỗi đến hết max_steps.

**Log source** — `logs/sample_trace_2026-06-01.log`:

```json
{"event": "TOOL_ARG_ERROR", "data": {
  "tool": "get_student_info",
  "args": {"name": "STU001"},
  "error": "get_student_info() got an unexpected keyword argument 'name'"
}}
```

**Diagnosis**: System prompt v1 liệt kê tool name và description nhưng **không có example JSON cụ thể**. LLM suy luận arg name theo "common sense" (`name` nghe có vẻ hợp lý hơn `student_id`). Observation trả về chỉ là generic error → LLM không biết cần sửa gì.

**Solution**: Implement 2 fixes trong v2:
1. Thêm Few-Shot examples trong system prompt với exact JSON format
2. Thêm `TOOL_SCHEMAS` → khi validate fail, inject hint có example JSON chính xác cho tool đó

**Kết quả**: Test Case 4 (invalid args trap) — v1 timeout sau 5 steps; v2 self-correct trong 1 retry, kết thúc thành công ở step 2. Xem chi tiết tại `experiments/results/ablation_results.md`.

---

## III. Personal Insights: Chatbot vs ReAct (10 Points)

### 1. Reasoning — Thought block giúp gì?

Chatbot trả lời thẳng từ training data: khi hỏi "Macbook Pro M3 còn hàng không?", nó hallucinate một câu trả lời tự tin dù không có thông tin thực tế. Agent buộc LLM viết **Thought trước** — quá trình này expose reasoning ra ngoài. Nếu Thought sai (ví dụ suy nghĩ dùng tool không tồn tại), Observation sẽ ngay lập tức correct nó ở bước tiếp.

Ví dụ cụ thể từ lab:
- **Chatbot**: "Yes, MacBook Pro M3 is available at $1,200 with 10% discount = $1,095 + $15 shipping = $1,110" — sai hoàn toàn, không có tool
- **Agent**: "Thought: I need to use check_stock tool" → Observation: "[ERROR] Tool 'check_stock' does not exist" → tự biết mình không có tool và trả lời trung thực

### 2. Reliability — Khi nào Agent tệ hơn Chatbot?

Agent **tệ hơn** trong 2 trường hợp:
- **Câu hỏi đơn giản không cần tool**: "25 * 4 + 10 = ?" — Agent mất 2 steps và ~$0.00012 để trả lời cái mà Chatbot trả lời đúng ngay lập tức với $0.
- **Slow first response**: Chatbot trả lời trong 1 LLM call; Agent mất ít nhất 2 calls (1 Thought+Action + 1 Final Answer) → latency tối thiểu 2×.

**Trade-off**: Agent đáng giá khi query cần tool (DB lookup, calculation, external API). Với câu hỏi factual đơn giản → Chatbot là lựa chọn tốt hơn.

### 3. Observation — Feedback ảnh hưởng next step thế nào?

Observation là cơ chế quan trọng nhất trong ReAct. Nó hoạt động như **unit test runtime** — nếu tool trả về error, agent không tiếp tục với assumption sai mà phải re-plan. Điều này giống với TDD: code chạy (tool call) → test fail (error observation) → refactor (next Thought).

Ví dụ từ trace: Agent v2 nhận `TOOL_VALIDATION_ERROR` từ system → tự sửa arg name → gọi lại đúng. Không có Observation, agent sẽ tiếp tục với wrong assumption và hallucinate answer.

---

## IV. Future Improvements (5 Points)

### Scalability: Async Tool Execution

Khi agent cần gọi nhiều tools song song (ví dụ: get_student_info cho 10 sinh viên cùng lúc), sequential execution sẽ chậm. Giải pháp: dùng `asyncio` và `AsyncLLMProvider`, cho phép fan-out tool calls:

```python
results = await asyncio.gather(*[
    agent.execute_tool_async(tool, args) for tool, args in tool_queue
])
```

### Safety: Supervisor LLM

Thêm một LLM "supervisor" chạy song song, audit mỗi Action trước khi execute. Nếu Action có khả năng gây hại (SQL DELETE, external API call với side effects), supervisor reject và inject warning vào Observation. Kiến trúc này giống với LangGraph's `interrupt_before`.

### Performance: Tool Retrieval với Vector DB

Khi số lượng tools tăng lên (>20 tools), liệt kê hết trong system prompt tốn quá nhiều tokens và làm loãng signal. Giải pháp: embed tool descriptions vào vector DB (ChromaDB/Pinecone), dùng semantic search để chỉ inject 3-5 tools relevant nhất vào prompt dựa trên user query.

```python
relevant_tools = vector_db.similarity_search(user_query, k=5)
agent = ReActAgentV2(llm, tools=relevant_tools)
```

---

> *Nộp file này với tên `REPORT_[TÊN_BẠN].md` vào thư mục `report/individual_reports/`*
