import sqlite3
import pandas as pd
import uuid
import datetime

DB_FILE = "leadership_360.db"

def get_connection():
    conn = sqlite3.connect(DB_FILE, check_same_thread=False)
    conn.row_factory = sqlite3.Row
    return conn

def init_db():
    conn = get_connection()
    c = conn.cursor()
    
    # 1. 기업 (Tenant)
    c.execute('''CREATE TABLE IF NOT EXISTS corporates (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        name TEXT NOT NULL UNIQUE,
        created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
    )''')
    
    # 2. 프로젝트
    c.execute('''CREATE TABLE IF NOT EXISTS projects (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        corporate_id INTEGER,
        name TEXT NOT NULL,
        year INTEGER,
        status TEXT DEFAULT 'SETUP',
        created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
        FOREIGN KEY (corporate_id) REFERENCES corporates(id)
    )''')
    
    # 3. 리더
    c.execute('''CREATE TABLE IF NOT EXISTS leaders (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        project_id INTEGER,
        name TEXT NOT NULL,
        leader_code TEXT,
        position TEXT,
        department TEXT,
        email TEXT,
        FOREIGN KEY (project_id) REFERENCES projects(id)
    )''')
    
    # 4. 평가자
    c.execute('''CREATE TABLE IF NOT EXISTS evaluators (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        project_id INTEGER,
        name TEXT NOT NULL,
        evaluator_code TEXT,
        email TEXT NOT NULL,
        access_token TEXT UNIQUE,
        is_active BOOLEAN DEFAULT 1,
        FOREIGN KEY (project_id) REFERENCES projects(id)
    )''')
    
    # 5. 할당
    c.execute('''CREATE TABLE IF NOT EXISTS assignments (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        project_id INTEGER,
        evaluator_id INTEGER,
        leader_id INTEGER,
        relation TEXT,
        project_group TEXT,
        status TEXT DEFAULT 'PENDING',
        completed_at TIMESTAMP,
        FOREIGN KEY (evaluator_id) REFERENCES evaluators(id),
        FOREIGN KEY (leader_id) REFERENCES leaders(id)
    )''')
    
    # 6. 응답
    c.execute('''CREATE TABLE IF NOT EXISTS responses (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        assignment_id INTEGER,
        q1_score INTEGER,
        q2_score INTEGER,
        comment TEXT,
        submitted_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
        FOREIGN KEY (assignment_id) REFERENCES assignments(id)
    )''')
    
    conn.commit()
    conn.close()

# --- 데이터 업로드 및 생성 함수 ---

def get_or_create_project(corp_name, project_name, year):
    conn = get_connection()
    c = conn.cursor()
    try:
        c.execute("SELECT id FROM corporates WHERE name = ?", (corp_name,))
        row = c.fetchone()
        if row:
            corp_id = row['id']
        else:
            c.execute("INSERT INTO corporates (name) VALUES (?)", (corp_name,))
            corp_id = c.lastrowid
            
        c.execute("SELECT id FROM projects WHERE corporate_id = ? AND name = ? AND year = ?", (corp_id, project_name, year))
        row = c.fetchone()
        if row:
            proj_id = row['id']
        else:
            c.execute("INSERT INTO projects (corporate_id, name, year) VALUES (?, ?, ?)", (corp_id, project_name, year))
            proj_id = c.lastrowid
        conn.commit()
        return proj_id
    finally:
        conn.close()

def process_bulk_upload(project_id, df):
    conn = get_connection()
    c = conn.cursor()
    cnt_created = 0
    cnt_skipped = 0
    RELATION_MAP = {'상사': 'BOSS', '동료': 'PEER', '부하': 'SUB', '본인': 'SELF'}

    try:
        for _, row in df.iterrows():
            if pd.isna(row.get('evaluator_email')) or pd.isna(row.get('leader_name')):
                continue

            c.execute("SELECT id FROM evaluators WHERE project_id=? AND email=?", (project_id, row['evaluator_email']))
            ev_row = c.fetchone()
            if ev_row:
                ev_id = ev_row['id']
            else:
                token = uuid.uuid4().hex[:16]
                c.execute("INSERT INTO evaluators (project_id, name, evaluator_code, email, access_token) VALUES (?, ?, ?, ?, ?)", 
                          (project_id, row['evaluator_name'], str(row.get('evaluator_code','')), row['evaluator_email'], token))
                ev_id = c.lastrowid

            leader_code = str(row.get('leader_code', ''))
            c.execute("SELECT id FROM leaders WHERE project_id=? AND name=? AND leader_code=?", (project_id, row['leader_name'], leader_code))
            ld_row = c.fetchone()
            if ld_row:
                ld_id = ld_row['id']
            else:
                c.execute("INSERT INTO leaders (project_id, name, leader_code, department, position) VALUES (?, ?, ?, ?, ?)", 
                          (project_id, row['leader_name'], leader_code, row.get('project_group'), row.get('leader_position', '')))
                ld_id = c.lastrowid

            c.execute("SELECT id FROM assignments WHERE evaluator_id=? AND leader_id=?", (ev_id, ld_id))
            if not c.fetchone():
                rel_code = RELATION_MAP.get(row.get('relation'), row.get('relation'))
                c.execute("INSERT INTO assignments (project_id, evaluator_id, leader_id, relation, project_group) VALUES (?, ?, ?, ?, ?)", 
                          (project_id, ev_id, ld_id, rel_code, row.get('project_group')))
                cnt_created += 1
            else:
                cnt_skipped += 1
        conn.commit()
        return True, f"처리 완료: 신규 {cnt_created}건, 중복 {cnt_skipped}건"
    except Exception as e:
        return False, f"오류 발생: {str(e)}"
    finally:
        conn.close()

def create_sample_data():
    """테스트용 샘플 데이터 생성 (버튼 클릭 시 실행)"""
    conn = get_connection()
    c = conn.cursor()
    
    # 이미 데이터가 있으면 생성하지 않음
    c.execute("SELECT count(*) FROM corporates")
    if c.fetchone()[0] > 0:
        conn.close()
        return "이미 데이터가 존재합니다. 초기화가 필요하면 DB 파일을 삭제하세요."

    # 1. 기업 & 프로젝트
    c.execute("INSERT INTO corporates (name) VALUES ('(주)테스트기업')")
    corp_id = c.lastrowid
    c.execute("INSERT INTO projects (corporate_id, name, year, status) VALUES (?, '2025 리더십 진단', 2025, 'ACTIVE')", (corp_id,))
    proj_id = c.lastrowid
    
    # 2. 평가자 (홍길동, 토큰: test1234)
    c.execute("INSERT INTO evaluators (project_id, name, email, evaluator_code, access_token) VALUES (?, '홍길동', 'hong@test.com', '1001', 'test1234')", (proj_id,))
    ev_id = c.lastrowid
    
    # 3. 리더 2명
    c.execute("INSERT INTO leaders (project_id, name, leader_code, position, department) VALUES (?, '김철수', 'L001', '팀장', '영업팀')", (proj_id,))
    ld1 = c.lastrowid
    c.execute("INSERT INTO leaders (project_id, name, leader_code, position, department) VALUES (?, '이영희', 'L002', '본부장', '전략실')", (proj_id,))
    ld2 = c.lastrowid
    
    # 4. 할당
    c.execute("INSERT INTO assignments (project_id, evaluator_id, leader_id, relation) VALUES (?, ?, ?, 'BOSS')", (proj_id, ev_id, ld1))
    c.execute("INSERT INTO assignments (project_id, evaluator_id, leader_id, relation) VALUES (?, ?, ?, 'PEER')", (proj_id, ev_id, ld2))
    
    conn.commit()
    conn.close()
    return "샘플 데이터 생성 완료! (토큰: test1234)"

# --- 조회 및 저장 함수 ---

def get_evaluator_by_token(token):
    conn = get_connection()
    query = """
        SELECT E.id, E.name, P.name as project_name, C.name as corp_name, E.project_id
        FROM evaluators E
        JOIN projects P ON E.project_id = P.id
        JOIN corporates C ON P.corporate_id = C.id
        WHERE E.access_token = ?
    """
    df = pd.read_sql(query, conn, params=(token,))
    conn.close()
    return df.iloc[0] if not df.empty else None

def get_my_assignments(evaluator_id):
    conn = get_connection()
    query = """
        SELECT A.id, L.name as leader_name, L.position, L.department, A.relation, A.status
        FROM assignments A
        JOIN leaders L ON A.leader_id = L.id
        WHERE A.evaluator_id = ?
    """
    df = pd.read_sql(query, conn, params=(evaluator_id,))
    conn.close()
    return df

def save_response(assignment_id, q1, q2, comment):
    conn = get_connection()
    c = conn.cursor()
    c.execute("INSERT INTO responses (assignment_id, q1_score, q2_score, comment) VALUES (?, ?, ?, ?)", 
              (assignment_id, q1, q2, comment))
    c.execute("UPDATE assignments SET status = 'COMPLETED', completed_at = CURRENT_TIMESTAMP WHERE id = ?", (assignment_id,))
    conn.commit()
    conn.close()
    return True
