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

    # 7. 프로젝트별 진단 문항
    c.execute('''CREATE TABLE IF NOT EXISTS diagnostic_questions (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        project_id INTEGER NOT NULL,
        question_text TEXT NOT NULL,
        keyword TEXT,
        framework TEXT,
        question_type TEXT DEFAULT 'likert',
        sort_order INTEGER DEFAULT 0,
        FOREIGN KEY (project_id) REFERENCES projects(id)
    )''')

    # 8. 문항별 응답
    c.execute('''CREATE TABLE IF NOT EXISTS question_responses (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        assignment_id INTEGER NOT NULL,
        question_id INTEGER NOT NULL,
        score INTEGER,
        submitted_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
        FOREIGN KEY (assignment_id) REFERENCES assignments(id),
        FOREIGN KEY (question_id) REFERENCES diagnostic_questions(id)
    )''')
    
    conn.commit()
    conn.close()


# === 조회 편의 함수 ===


def list_corporates():
    """모든 기업 목록을 반환"""
    conn = get_connection()
    df = pd.read_sql(
        "SELECT id, name, created_at FROM corporates ORDER BY name",
        conn,
    )
    conn.close()
    return df


def list_projects(corporate_id=None):
    """프로젝트 목록 (기업으로 필터 가능)"""
    conn = get_connection()
    query = """
        SELECT P.id, P.name, P.year, P.status, C.name AS corporate_name
        FROM projects P
        JOIN corporates C ON P.corporate_id = C.id
        WHERE (? IS NULL OR C.id = ?)
        ORDER BY P.year DESC, P.id DESC
    """
    df = pd.read_sql(query, conn, params=(corporate_id, corporate_id))
    conn.close()
    return df


def get_dashboard_overview(corporate_id=None):
    """기업/프로젝트 단위 진행 현황 요약"""
    conn = get_connection()
    query = """
        SELECT
            C.id AS corporate_id,
            C.name AS corporate_name,
            P.id AS project_id,
            P.name AS project_name,
            P.year,
            COUNT(DISTINCT A.id) AS total_assignments,
            SUM(CASE WHEN A.status = 'COMPLETED' THEN 1 ELSE 0 END) AS completed_assignments,
            COUNT(DISTINCT E.id) AS evaluator_count,
            COUNT(DISTINCT L.id) AS leader_count
        FROM projects P
        JOIN corporates C ON P.corporate_id = C.id
        LEFT JOIN assignments A ON P.id = A.project_id
        LEFT JOIN evaluators E ON P.id = E.project_id
        LEFT JOIN leaders L ON P.id = L.project_id
        WHERE (? IS NULL OR C.id = ?)
        GROUP BY P.id
        ORDER BY P.year DESC, P.id DESC
    """
    df = pd.read_sql(query, conn, params=(corporate_id, corporate_id))
    conn.close()
    if not df.empty:
        df["completion_rate"] = (
            (df["completed_assignments"] / df["total_assignments"].replace({0: None}))
            .fillna(0)
            .round(3)
        )
    return df


# --- 진단 문항 관리 함수 ---


def replace_project_questions(project_id, questions):
    """해당 프로젝트의 기존 문항을 삭제하고 새로 채워 넣습니다."""
    conn = get_connection()
    c = conn.cursor()
    try:
        c.execute("DELETE FROM diagnostic_questions WHERE project_id = ?", (project_id,))
        for idx, q in enumerate(questions, start=1):
            c.execute(
                """
                INSERT INTO diagnostic_questions (project_id, question_text, keyword, framework, question_type, sort_order)
                VALUES (?, ?, ?, ?, ?, ?)
                """,
                (
                    project_id,
                    q.get("question_text"),
                    q.get("keyword"),
                    q.get("framework"),
                    q.get("question_type", "likert"),
                    q.get("sort_order", idx),
                ),
            )
        conn.commit()
        return True
    finally:
        conn.close()


def get_project_questions(project_id):
    conn = get_connection()
    query = """
        SELECT id, question_text, keyword, framework, question_type, sort_order
        FROM diagnostic_questions
        WHERE project_id = ?
        ORDER BY sort_order ASC, id ASC
    """
    df = pd.read_sql(query, conn, params=(project_id,))
    conn.close()
    return df


def load_sample_questions(project_id):
    sample_data = [
        {"question_text": "진단 대상자는 구성원들이 불편사항이나 우려사항을 솔직하게 표현할 수 있는 환경을 조성한다.", "keyword": "소신표현장려", "framework": "인재육성 및 동기부여"},
        {"question_text": "진단 대상자는 구성원이 어려움을 극복하고 다시 도전할 수 있는 환경을 조성한다.", "keyword": "회복지원", "framework": "인재육성 및 동기부여"},
        {"question_text": "진단 대상자는 예상치 못한 이슈 발생 시 신속하게 상황을 파악하고 적절한 판단을 내린다.", "keyword": "신속판단", "framework": "전략과 변화주도"},
        {"question_text": "진단 대상자는 고객과의 소통에서 신뢰와 공감을 기반으로 긍정적인 관계를 유지한다.", "keyword": "고객신뢰유지", "framework": "자기개발 및 관리"},
        {"question_text": "진단 대상자는 공동 목표 달성을 위해 구성원 각자의 역할과 책임을 명확하게 정의한다.", "keyword": "역할책임정의", "framework": "인재육성 및 동기부여"},
        {"question_text": "진단 대상자는 고객 기대 수준을 선제적으로 파악하고 이를 초과 달성하기 위해 노력한다.", "keyword": "기대수준이상", "framework": "전략과 변화주도"},
        {"question_text": "진단 대상자는 구성원과의 피드백과 면담을 통해 구성원의 자기 인식을 촉진한다.", "keyword": "구성원면담", "framework": "인재육성 및 동기부여"},
        {"question_text": "진단 대상자의 스스로 학습하고 성장하는 모습이 구성원의 롤모델이 된다.", "keyword": "귀감인물", "framework": "자기개발 및 관리"},
        {"question_text": "진단 대상자는 구성원이 불안감을 느낄 수 있는 상황에서 정서적으로 지지하고 안정감을 제공한다.", "keyword": "정서적지지", "framework": "인재육성 및 동기부여"},
        {"question_text": "진단 대상자는 구성원에게 명확한 데드라인을 제시하고 이행 여부를 점검한다.", "keyword": "기한관리", "framework": "실행을 통한 성과창출"},
        {"question_text": "진단 대상자는 구성원이 데이터 기반으로 사고하고 판단할 수 있도록 지도한다.", "keyword": "데이터역량강화", "framework": "인재육성 및 동기부여"},
        {"question_text": "진단 대상자는 관행에 얽매이지 않고 새롭게 요구되는 방식에 유연하게 적응한다.", "keyword": "유연적응", "framework": "전략과 변화주도"},
        {"question_text": "진단 대상자는 조직 변화 방향을 구성원이 이해할 수 있도록 명확히 설명하고 설득한다.", "keyword": "변화설득", "framework": "전략과 변화주도"},
        {"question_text": "진단 대상자는 의사결정 시 직관이나 경험뿐만 아니라 데이터를 활용한다.", "keyword": "데이터의사결정", "framework": "자기개발 및 관리"},
        {"question_text": "진단 대상자는 팀의 목표 달성을 위한 명확한 일정과 실행 계획을 수립한다.", "keyword": "계획수립", "framework": "실행을 통한 성과창출"},
        {"question_text": "진단 대상자는 자신의 전문지식과 노하우를 구성원에게 적극적으로 공유한다.", "keyword": "지식공유", "framework": "자기개발 및 관리"},
        {"question_text": "진단 대상자는 고객 피드백을 반영하여 지속적으로 서비스 품질을 점검하고 개선한다.", "keyword": "품질개선", "framework": "실행을 통한 성과창출"},
        {"question_text": "진단 대상자는 구성원과 동료의 피드백을 수용하여 스스로 변화하는 모습을 보여준다.", "keyword": "피드백반영", "framework": "자기개발 및 관리"},
        {"question_text": "진단 대상자는 업무 변화와 트렌드에 신속히 반응하고 관련 정보를 조직 내에 빠르게 공유한다.", "keyword": "트렌드공유", "framework": "전략과 변화주도"},
        {"question_text": "진단 대상자는 서비스 품질 기준을 명확히 설정하고, 필요시 상향 조정한다.", "keyword": "품질기준설정", "framework": "실행을 통한 성과창출"},
        {"question_text": "진단 대상자는 구성원 각자의 잠재력을 파악하여 이를 개발할 수 있도록 지원한다.", "keyword": "개발지원", "framework": "인재육성 및 동기부여"},
        {"question_text": "진단 대상자는 구성원이 새로운 과제에 도전하고 이를 통해 학습·성장할 수 있도록 심리적 안정감을 조성한다.", "keyword": "안정감조성", "framework": "인재육성 및 동기부여"},
        {"question_text": "진단 대상자는 구성원의 역량과 역할을 고려하여 책임과 과업을 명확하게 배분한다.", "keyword": "과업배분", "framework": "인재육성 및 동기부여"},
        {"question_text": "진단 대상자는 개인의 성과보다 팀과 조직의 성과를 우선하여 판단하고 실행한다.", "keyword": "조직우선", "framework": "자기개발 및 관리"},
        {"question_text": "진단 대상자는 어려운 문제나 이슈가 발생하면 전문성에 기반하여 실질적인 해결책을 제시한다.", "keyword": "문제해결", "framework": "실행을 통한 성과창출"},
        {"question_text": "진단 대상자는 팀의 목표와 계획이 조직의 방향성에 부합하도록 조율한다.", "keyword": "방향조율", "framework": "전략과 변화주도"},
        {"question_text": "진단 대상자는 기존 방식을 고수하지 않고 구성원과 함께 새로운 접근 방식을 시도한다.", "keyword": "혁신시도", "framework": "전략과 변화주도"},
        {"question_text": "진단 대상자는 상황 변화에 따라 구체적이고 명확한 행동 지침을 필요한 시기에 제공한다.", "keyword": "상황지침제공", "framework": "전략과 변화주도"},
        {"question_text": "진단 대상자는 업무의 중요도와 긴급도를 고려하여 우선순위를 설정하고 실행한다.", "keyword": "업무순위결정", "framework": "실행을 통한 성과창출"},
        {"question_text": "진단 대상자는 스트레스 상황에서도 자신의 부정적 감정을 구성원에게 전달하지 않는다.", "keyword": "감정관리", "framework": "자기개발 및 관리"},
        {"question_text": "진단 대상자는 다양한 이해관계자 간 의견 차이를 조율하여 조직 내 신뢰를 형성한다.", "keyword": "의견조율", "framework": "자기개발 및 관리"},
        {"question_text": "진단 대상자는 계획한 목표를 끝까지 추진하여 명확한 결과를 도출한다.", "keyword": "목표완수", "framework": "실행을 통한 성과창출"},
        {"question_text": "진단 대상자는 자신의 약점에 대해 솔직하게 인정하고 보완책을 마련한다.", "keyword": "약점인정", "framework": "자기개발 및 관리"},
        {"question_text": "진단 대상자는 팀의 목표 달성을 위한 실행 전략을 수립하고 이를 구성원과 명확히 공유한다.", "keyword": "전략공유", "framework": "전략과 변화주도"},
        {"question_text": "진단 대상자는 고객의 피드백을 신속히 팀에 공유하고 업무에 반영한다.", "keyword": "고객요구반영", "framework": "실행을 통한 성과창출"},
        {"question_text": "진단 대상자는 구성원이 문제를 해결할 수 있도록 실질적인 도움이나 필요한 자원을 제공한다.", "keyword": "해결지원", "framework": "실행을 통한 성과창출"},
    ]
    replace_project_questions(project_id, sample_data)
    return len(sample_data)

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

    # 5. 샘플 진단 문항
    load_sample_questions(proj_id)

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

def save_response(assignment_id, question_scores, comment=None):
    """문항별 점수를 저장하고 할당 상태를 완료로 변경"""
    conn = get_connection()
    c = conn.cursor()
    try:
        c.execute(
            "INSERT INTO responses (assignment_id, q1_score, q2_score, comment) VALUES (?, ?, ?, ?)",
            (assignment_id, None, None, comment),
        )
        for q_id, score in question_scores.items():
            c.execute(
                "INSERT INTO question_responses (assignment_id, question_id, score) VALUES (?, ?, ?)",
                (assignment_id, q_id, score),
            )
        c.execute(
            "UPDATE assignments SET status = 'COMPLETED', completed_at = CURRENT_TIMESTAMP WHERE id = ?",
            (assignment_id,),
        )
        conn.commit()
        return True
    finally:
        conn.close()


def get_project_snapshot(project_id):
    """프로젝트별 주요 지표 (할당/완료/응답 수)"""
    conn = get_connection()
    data = {}
    try:
        df = pd.read_sql(
            "SELECT status, COUNT(*) as cnt FROM assignments WHERE project_id = ? GROUP BY status",
            conn,
            params=(project_id,),
        )
        total_assignments = df["cnt"].sum() if not df.empty else 0
        completed = int(df.loc[df["status"] == "COMPLETED", "cnt"].sum()) if not df.empty else 0
        data["total_assignments"] = int(total_assignments)
        data["completed_assignments"] = completed
        data["pending_assignments"] = int(total_assignments - completed)

        data["evaluators"] = int(
            pd.read_sql(
                "SELECT COUNT(DISTINCT id) AS cnt FROM evaluators WHERE project_id = ?",
                conn,
                params=(project_id,),
            )["cnt"].iloc[0]
        )
        data["leaders"] = int(
            pd.read_sql(
                "SELECT COUNT(DISTINCT id) AS cnt FROM leaders WHERE project_id = ?",
                conn,
                params=(project_id,),
            )["cnt"].iloc[0]
        )
        data["responses"] = int(
            pd.read_sql(
                "SELECT COUNT(*) AS cnt FROM responses WHERE assignment_id IN (SELECT id FROM assignments WHERE project_id = ?)",
                conn,
                params=(project_id,),
            )["cnt"].iloc[0]
        )
    finally:
        conn.close()
    return data


def get_assignments_with_people(project_id):
    """평가자-피평가자 매핑 상세"""
    conn = get_connection()
    query = """
        SELECT A.id, E.name AS evaluator, E.email, L.name AS leader, L.department, L.position,
               A.relation, A.project_group, A.status, A.completed_at
        FROM assignments A
        JOIN evaluators E ON A.evaluator_id = E.id
        JOIN leaders L ON A.leader_id = L.id
        WHERE A.project_id = ?
        ORDER BY A.id DESC
    """
    df = pd.read_sql(query, conn, params=(project_id,))
    conn.close()
    return df


def get_responses_with_people(project_id):
    """응답 데이터 조회"""
    conn = get_connection()
    query = """
        SELECT QR.id, QR.assignment_id, Q.question_text, Q.keyword, Q.framework, QR.score, QR.submitted_at,
               E.name AS evaluator, L.name AS leader, R.comment
        FROM question_responses QR
        JOIN diagnostic_questions Q ON QR.question_id = Q.id
        JOIN assignments A ON QR.assignment_id = A.id
        JOIN evaluators E ON A.evaluator_id = E.id
        JOIN leaders L ON A.leader_id = L.id
        LEFT JOIN responses R ON R.assignment_id = A.id
        WHERE A.project_id = ?
        ORDER BY QR.submitted_at DESC, QR.id DESC
    """
    df = pd.read_sql(query, conn, params=(project_id,))
    conn.close()
    return df

def reset_database():
    """모든 테이블을 삭제하고 다시 초기화 (강제 리셋)"""
    conn = get_connection()
    c = conn.cursor()
    # 순서 중요: 참조 무결성 때문에 자식 테이블부터 삭제
    tables = [
        "question_responses",
        "responses",
        "assignments",
        "diagnostic_questions",
        "evaluators",
        "leaders",
        "projects",
        "corporates",
    ]
    for table in tables:
        c.execute(f"DROP TABLE IF EXISTS {table}")
    conn.commit()
    conn.close()
    
    # 다시 테이블 생성
    init_db()
    return "DB가 깨끗하게 초기화되었습니다. 이제 샘플 데이터를 생성하세요."
