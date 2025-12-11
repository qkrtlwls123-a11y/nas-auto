import sqlite3
import pandas as pd
import uuid

DB_FILE = "leadership_360.db"

def get_connection():
    conn = sqlite3.connect(DB_FILE, check_same_thread=False)
    conn.row_factory = sqlite3.Row # 컬럼명으로 접근 가능하게 설정
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
    
    # 3. 리더 (피평가자) - 사번(code) 추가
    c.execute('''CREATE TABLE IF NOT EXISTS leaders (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        project_id INTEGER,
        name TEXT NOT NULL,
        leader_code TEXT, -- 사번 등 고유값
        position TEXT,
        department TEXT,
        email TEXT,
        FOREIGN KEY (project_id) REFERENCES projects(id)
    )''')
    
    # 4. 평가자 - 사번(code) 추가
    c.execute('''CREATE TABLE IF NOT EXISTS evaluators (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        project_id INTEGER,
        name TEXT NOT NULL,
        evaluator_code TEXT, -- 사번
        email TEXT NOT NULL,
        access_token TEXT UNIQUE,
        is_active BOOLEAN DEFAULT 1,
        FOREIGN KEY (project_id) REFERENCES projects(id)
    )''')
    
    # 5. 할당 (Assignment) - 그룹(project_group) 추가
    c.execute('''CREATE TABLE IF NOT EXISTS assignments (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        project_id INTEGER,
        evaluator_id INTEGER,
        leader_id INTEGER,
        relation TEXT, -- 상사(boss), 동료(co), 부하(sub), 본인(self)
        project_group TEXT, -- 부서명이나 그룹명
        status TEXT DEFAULT 'PENDING',
        completed_at TIMESTAMP,
        FOREIGN KEY (evaluator_id) REFERENCES evaluators(id),
        FOREIGN KEY (leader_id) REFERENCES leaders(id)
    )''')
    
    # 6. 응답 결과
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

# --- 엑셀 업로드를 위한 데이터 처리 함수 ---

def get_or_create_project(corp_name, project_name, year):
    """기업과 프로젝트가 없으면 만들고 ID 반환"""
    conn = get_connection()
    c = conn.cursor()
    
    # 1. 기업 조회/생성
    c.execute("SELECT id FROM corporates WHERE name = ?", (corp_name,))
    row = c.fetchone()
    if row:
        corp_id = row['id']
    else:
        c.execute("INSERT INTO corporates (name) VALUES (?)", (corp_name,))
        corp_id = c.lastrowid
        
    # 2. 프로젝트 조회/생성
    c.execute("SELECT id FROM projects WHERE corporate_id = ? AND name = ?", (corp_id, project_name))
    row = c.fetchone()
    if row:
        proj_id = row['id']
    else:
        c.execute("INSERT INTO projects (corporate_id, name, year) VALUES (?, ?, ?)", (corp_id, project_name, year))
        proj_id = c.lastrowid
        
    conn.commit()
    conn.close()
    return proj_id

def process_bulk_upload(project_id, df):
    """
    업로드된 엑셀/CSV 데이터를 DB에 일괄 등록 (기존 route.ts 로직 이식)
    df 컬럼: evaluator_email, evaluator_name, evaluator_code, leader_name, leader_code, relation, project_group
    """
    conn = get_connection()
    c = conn.cursor()
    
    created_count = 0
    skipped_count = 0
    
    # 관계 매핑 (한글 -> 영문 코드)
    RELATION_MAP = {
        '상사': 'boss', 'boss': 'boss',
        '동료': 'co', 'co': 'co',
        '부하': 'sub', '부하직원': 'sub', 'sub': 'sub',
        '본인': 'self', 'self': 'self'
    }

    try:
        for _, row in df.iterrows():
            # 1. 필수값 체크
            if pd.isna(row['evaluator_email']) or pd.isna(row['leader_name']):
                continue

            # 2. 관계 변환
            raw_rel = str(row['relation']).strip()
            relation = RELATION_MAP.get(raw_rel, 'co') # 기본값 동료

            # 3. 평가자(Evaluator) 찾기 또는 생성
            c.execute("SELECT id FROM evaluators WHERE project_id=? AND email=?", (project_id, row['evaluator_email']))
            ev_row = c.fetchone()
            if ev_row:
                ev_id = ev_row['id']
            else:
                token = uuid.uuid4().hex[:16] # 난수 토큰 생성
                c.execute("""
                    INSERT INTO evaluators (project_id, name, evaluator_code, email, access_token)
                    VALUES (?, ?, ?, ?, ?)
                """, (project_id, row['evaluator_name'], row.get('evaluator_code'), row['evaluator_email'], token))
                ev_id = c.lastrowid

            # 4. 리더(Leader) 찾기 또는 생성
            # 리더 구분은 사번(leader_code)이 있으면 사번으로, 없으면 이름+이메일로
            leader_code = row.get('leader_code', '')
            c.execute("SELECT id FROM leaders WHERE project_id=? AND leader_code=?", (project_id, leader_code))
            ld_row = c.fetchone()
            
            if ld_row:
                ld_id = ld_row['id']
            else:
                c.execute("""
                    INSERT INTO leaders (project_id, name, leader_code, department)
                    VALUES (?, ?, ?, ?)
                """, (project_id, row['leader_name'], leader_code, row.get('project_group')))
                ld_id = c.lastrowid

            # 5. 할당(Assignment) 생성 (중복 체크)
            c.execute("SELECT id FROM assignments WHERE evaluator_id=? AND leader_id=?", (ev_id, ld_id))
            if not c.fetchone():
                c.execute("""
                    INSERT INTO assignments (project_id, evaluator_id, leader_id, relation, project_group)
                    VALUES (?, ?, ?, ?, ?)
                """, (project_id, ev_id, ld_id, relation, row.get('project_group')))
                created_count += 1
            else:
                skipped_count += 1
        
        conn.commit()
        return True, f"✅ 처리 완료: 신규 {created_count}건, 중복 제외 {skipped_count}건"
        
    except Exception as e:
        return False, f"⛔ 오류 발생: {str(e)}"
    finally:
        conn.close()

# ... (기존 조회 함수들은 그대로 사용하거나 새 컬럼에 맞춰 수정) ...
# 아래 두 함수는 기존 코드를 유지하되 새 컬럼을 반영했습니다.

def get_evaluator_by_token(token):
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
