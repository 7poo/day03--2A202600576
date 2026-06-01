import streamlit as st
import sqlite3
import os
import json
from datetime import datetime

from src.tools.model_evaluator import evaluate_submission
from src.core.openai_provider import OpenAIProvider
from src.agent.agent import ReActAgent

DB_PATH = 'gradebook.db'

st.set_page_config(page_title='Agent Dashboard & Chatbot', layout='wide')

if not os.path.exists(DB_PATH):
    st.title('Agent Dashboard')
    st.error(f"Database not found at {DB_PATH}. Run scripts/init_db.py first.")
    st.stop()

conn = sqlite3.connect(DB_PATH, check_same_thread=False)
cur = conn.cursor()

# ensure evaluations table exists
cur.execute('''CREATE TABLE IF NOT EXISTS evaluations(
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    submission_id TEXT,
    student_id TEXT,
    score REAL,
    breakdown_json TEXT,
    feedback TEXT,
    raw_text TEXT,
    status TEXT,
    created_at TEXT
)
''')
conn.commit()

st.title('Agent Dashboard & Chatbot')

# Sidebar navigation
page = st.sidebar.radio('Navigation', ['Dashboard', 'Tools', 'Chatbot', 'Agent'])

########### Dashboard Page ###########
if page == 'Dashboard':
    st.header('📊 Cohort Dashboard (Sample)')
    cur.execute("SELECT id, nam_tuyensinh, ptxt, diem_trungtuyen FROM students LIMIT 100")
    rows = cur.fetchall()
    st.subheader('Students (sample)')
    for r in rows:
        st.write({'id': r[0], 'year': r[1], 'ptxt': r[2], 'score': r[3]})

    # Show basic evaluation stats
    cur.execute('SELECT COUNT(*) FROM evaluations')
    total_evals = cur.fetchone()[0]
    st.metric('Total Evaluations', total_evals)

    st.subheader('Recent Evaluations')
    cur.execute('SELECT id, student_id, score, status, created_at FROM evaluations ORDER BY id DESC LIMIT 20')
    evs = cur.fetchall()
    st.table([{'id':e[0],'student_id':e[1],'score':e[2],'status':e[3],'created_at':e[4]} for e in evs])


########### Tools Page ###########
elif page == 'Tools':
    st.header('🧰 Tools')
    st.subheader('DB Query')
    sid = st.text_input('Student ID (for DB Query)', '')
    if st.button('Query Student'):
        if not sid:
            st.error('Provide a Student ID')
        else:
            cur.execute('SELECT * FROM students WHERE id = ?', (sid,))
            s = cur.fetchone()
            if not s:
                st.warning('Student not found')
            else:
                cols = [d[0] for d in cur.description]
                st.json(dict(zip(cols, s)))

    st.subheader('Evaluate Submission (manual)')
    student_id = st.text_input('Student ID for evaluation')
    submission_text = st.text_area('Submission Text (paste)')
    rubric_json = st.text_area('Rubric (JSON)', value=json.dumps({'technical':40,'debugging':30,'insights':20,'future':10}))
    if st.button('Run Evaluation (manual)'):
        if not submission_text.strip():
            st.error('Provide submission text')
        else:
            try:
                rubric = json.loads(rubric_json)
            except Exception as e:
                st.error(f'Invalid rubric JSON: {e}')
                rubric = {}
            api_key = os.getenv('OPENAI_API_KEY')
            with st.spinner('Calling evaluator...'):
                res = evaluate_submission(submission_text, rubric, api_key=api_key, model='gpt-4o-mini')
                st.json(res)
                # persist if parsed ok
                if res.get('parse_status') == 'ok':
                    score = res.get('score')
                    breakdown = json.dumps(res.get('breakdown', {}))
                    feedback = res.get('feedback', '')
                    raw = res.get('raw_text', '')
                    status = 'ok'
                else:
                    score = None
                    breakdown = None
                    feedback = ''
                    raw = res.get('raw_text','')
                    status = 'needs_human_review'
                cur.execute('INSERT INTO evaluations(submission_id, student_id, score, breakdown_json, feedback, raw_text, status, created_at) VALUES (?,?,?,?,?,?,?,?)',
                            (None, student_id, score, breakdown, feedback, raw, status, datetime.utcnow().isoformat()))
                conn.commit()
                st.success('Evaluation recorded')


########### Chatbot Page ###########
elif page == 'Chatbot':
    st.header('💬 Chatbot (baseline)')
    model_choice = st.selectbox('Model', ['gpt-4o-mini', 'gpt-4o'], index=0)
    user_msg = st.text_area('User message', height=150)
    if st.button('Send'):
        if not user_msg.strip():
            st.error('Type a message')
        else:
            api_key = os.getenv('OPENAI_API_KEY')
            prov = OpenAIProvider(model_name=model_choice, api_key=api_key)
            resp = prov.generate(user_msg)
            st.subheader('Response')
            st.write(resp.get('content'))
            st.json({'usage': resp.get('usage'), 'latency_ms': resp.get('latency_ms')})


########### Agent Page ###########
elif page == 'Agent':
    st.header('🤖 ReAct Agent')
    model_choice = st.selectbox('Agent Model', ['gpt-4o-mini', 'gpt-4o'], index=0, key='agent_model')
    agent_input = st.text_area('Agent Input (question / task)', height=160)
    max_steps = st.slider('Max steps', 1, 10, 5)
    if st.button('Run Agent'):
        if not agent_input.strip():
            st.error('Provide input for the agent')
        else:
            api_key = os.getenv('OPENAI_API_KEY')
            prov = OpenAIProvider(model_name=model_choice, api_key=api_key)
            # define minimal tools metadata
            tools = [
                {'name':'db_query','description':'Get student info by student_id'},
                {'name':'model_eval','description':'Evaluate submission text against rubric'}
            ]
            agent = ReActAgent(llm=prov, tools=tools, max_steps=max_steps)
            with st.spinner('Running agent...'):
                out = agent.run(agent_input)
                st.subheader('Agent Output')
                st.write(out)

