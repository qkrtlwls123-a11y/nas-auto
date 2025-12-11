import sqlite3
import pandas as pd
import datetime
import uuid

# SQLite 파일명 (NAS나 로컬에 이 파일이 생성됩니다)
DB_FILE = "leadership_360.db"

def get_connection():
    """DB 연결 객체 생성"""
    conn = sqlite3.connect(DB_FILE, check_same_thread=False)
    return conn

def init_db():
    """테이블 초기화 (앱 시작 시 실행)"""
    conn = get_connection()
    c = conn.cursor()
    
    # 1. 기업 정보 (Tenant)
    c.execute('''CREATE TABLE IF NOT EXISTS corporates (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        name TEXT NOT NULL UNIQUE,
        created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
    )''')
    
    # 2. 프로젝트 (연도/차수 관리)
    c.execute('''CREATE TABLE IF NOT EXISTS projects (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        corporate_id INTEGER,
        name TEXT NOT NULL,
        year INTEGER,
        status TEXT DEFAULT 'SETUP', -- SETUP, ACTIVE, CLOSED
        created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
        FOREIGN KEY (corporate_id) REFERENCES corporates(id)
    )''')
    
    # 3. 리더 (피평가자)
    c.execute('''CREATE TABLE IF NOT EXISTS leaders (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        project_id INTEGER,
        name TEXT NOT NULL,
        position TEXT,
        department TEXT,
        FOREIGN KEY (project_id) REFERENCES projects(id)
    )''')
    
    # 4. 평가자 (Access Token 보유)
    c.execute('''CREATE TABLE IF NOT EXISTS evaluators (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        project_id INTEGER,
        name TEXT NOT NULL,
        email TEXT NOT NULL,
        access_token TEXT UNIQUE,
        FOREIGN KEY (project_id) REFERENCES projects(id)
    )''')
    
    # 5. 할당 (Assignment: 누가 누구를 평가하는가)
    c.execute('''CREATE TABLE IF NOT EXISTS assignments (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        project_id INTEGER,
        evaluator_id INTEGER,
        leader_id INTEGER,
        relation TEXT, -- 상사, 동료, 부하, 본인
        status TEXT DEFAULT 'PENDING',
        FOREIGN KEY (evaluator_id) REFERENCES evaluators(id),
        FOREIGN KEY (leader_id) REFERENCES leaders(id)
    )''')
    
    # 6. 응답 결과 (Responses)
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

# --- 데이터 조회 함수들 ---

def get_evaluator_by_token(token):
    """토큰으로 평가자 정보 조회 (로그인 대용)"""
    conn = get_connection()
    query = """
        SELECT E.id, E.name, E.email, P.name as project_name, C.name as corp_name, E.project_id
        FROM evaluators E
        JOIN projects P ON E.project_id = P.id
        JOIN corporates C ON P.corporate_id = C.id
        WHERE E.access_token = ?
    """
    df = pd.read_sql(query, conn, params=(token,))
    conn.close()
    return df.iloc[0] if not df.empty else None

def get_my_assignments(evaluator_id):
    """나에게 할당된 평가 대상 조회"""
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

# --- 데이터 저장 함수들 ---

def save_response(assignment_id, q1, q2, comment):
    """설문 응답 저장"""
    conn = get_connection()
    c = conn.cursor()
    try:
        # 1. 응답 저장
        c.execute("INSERT INTO responses (assignment_id, q1_score, q2_score, comment) VALUES (?, ?, ?, ?)", 
                  (assignment_id, q1, q2, comment))
        # 2. 상태 업데이트
        c.execute("UPDATE assignments SET status = 'COMPLETED' WHERE id = ?", (assignment_id,))
        conn.commit()
        return True
    except Exception as e:
        print(e)
        return False
    finally:
        conn.close()

def create_sample_data():
    """테스트용 샘플 데이터 생성 (관리자 화면에서 버튼으로 실행)"""
    conn = get_connection()
    c = conn.cursor()
    
    # 중복 생성 방지
    c.execute("SELECT count(*) FROM corporates")
    if c.fetchone()[0] > 0:
        conn.close()
        return "이미 데이터가 있습니다."

    # 1. 기업 & 프로젝트 생성
    c.execute("INSERT INTO corporates (name) VALUES ('(주)스타트업')")
    corp_id = c.lastrowid
    c.execute("INSERT INTO projects (corporate_id, name, year, status) VALUES (?, '2025 상반기 리더십 진단', 2025, 'ACTIVE')", (corp_id,))
    proj_id = c.lastrowid
    
    # 2. 리더 생성
    leaders = [('김철수', '팀장', '개발팀'), ('이영희', '본부장', '사업부')]
    leader_ids = []
    for name, pos, dept in leaders:
        c.execute("INSERT INTO leaders (project_id, name, position, department) VALUES (?, ?, ?, ?)", (proj_id, name, pos, dept))
        leader_ids.append(c.lastrowid)
        
    # 3. 평가자 생성 (토큰 자동 생성)
    token = "test1234" # 테스트 편의를 위해 고정, 실제로는 uuid.uuid4().hex 사용
    c.execute("INSERT INTO evaluators (project_id, name, email, access_token) VALUES (?, '홍길동', 'hong@test.com', ?)", (proj_id, token))
    eval_id = c.lastrowid
    
    # 4. 할당 (홍길동이 김철수와 이영희를 평가)
    c.execute("INSERT INTO assignments (project_id, evaluator_id, leader_id, relation) VALUES (?, ?, ?, '상사')", (proj_id, eval_id, leader_ids[0]))
    c.execute("INSERT INTO assignments (project_id, evaluator_id, leader_id, relation) VALUES (?, ?, ?, '동료')", (proj_id, eval_id, leader_ids[1]))
    
    conn.commit()
    conn.close()
    return "샘플 데이터 생성 완료! (토큰: test1234)"