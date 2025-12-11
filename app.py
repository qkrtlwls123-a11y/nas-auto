import streamlit as st
import pandas as pd
import database as db

# 1. 앱 설정 & DB 연결
st.set_page_config(page_title="리더십 다면진단 시스템", layout="wide")

# 상단 헤더 숨기기 (깔끔한 UI)
hide_streamlit_style = """
<style>
    footer {visibility: hidden;}
    .block-container {padding-top: 2rem;}
</style>
"""
st.markdown(hide_streamlit_style, unsafe_allow_html=True)

# DB 초기화
db.init_db()

# 2. 토큰 확인
if "token" in st.query_params:
    token = st.query_params["token"]
else:
    token = None

# ==========================================
#  Scenario A: 관리자 모드 (토큰 없음)
# ==========================================
if not token:
    st.sidebar.title("🔧 관리자 시스템")
    menu = st.sidebar.radio("Menu", ["대시보드", "데이터 등록", "데이터 조회", "설정"])
    
    if menu == "대시보드":
        st.title("📊 통합 진단 현황")
        
        conn = db.get_connection()
        query = """
            SELECT C.name as Corporate, P.name as Project, 
                   COUNT(A.id) as Total,
                   SUM(CASE WHEN A.status='COMPLETED' THEN 1 ELSE 0 END) as Done
            FROM assignments A
            JOIN projects P ON A.project_id = P.id
            JOIN corporates C ON P.corporate_id = C.id
            GROUP BY P.id
        """
        df = pd.read_sql(query, conn)
        conn.close()
        
        if not df.empty:
            df['Progress(%)'] = (df['Done'] / df['Total'] * 100).round(1)
            st.dataframe(df, use_container_width=True, hide_index=True)
            st.bar_chart(df.set_index("Project")['Progress(%)'])
        else:
            st.info("데이터가 없습니다. '데이터 등록'이나 '설정' 탭에서 데이터를 생성하세요.")

    elif menu == "데이터 등록":
        st.title("📤 엑셀 일괄 등록")
        with st.form("upload_form"):
            col1, col2, col3 = st.columns(3)
            corp_input = col1.text_input("기업명", placeholder="(주)테크컴퍼니")
            proj_input = col2.text_input("프로젝트명", placeholder="2025 상반기 진단")
            year_input = col3.number_input("연도", value=2025, step=1)
            uploaded_file = st.file_uploader("파일 선택", type=['xlsx', 'csv'])
            
            if st.form_submit_button("등록 시작"):
                if uploaded_file and corp_input and proj_input:
                    if uploaded_file.name.endswith('.csv'):
                        df = pd.read_csv(uploaded_file)
                    else:
                        df = pd.read_excel(uploaded_file)
                    
                    proj_id = db.get_or_create_project(corp_input, proj_input, year_input)
                    success, msg = db.process_bulk_upload(proj_id, df)
                    if success:
                        st.success(msg)
                    else:
                        st.error(msg)
                else:
                    st.warning("정보를 모두 입력해주세요.")

    elif menu == "데이터 조회":
        st.subheader("🗂 테이블 조회")
        conn = db.get_connection()
        tab = st.selectbox("테이블", ["evaluators", "leaders", "assignments", "responses", "projects"])
        st.dataframe(pd.read_sql(f"SELECT * FROM {tab}", conn), use_container_width=True)
        conn.close()

    elif menu == "설정":
        st.title("⚙️ 시스템 설정")
        st.write("테스트를 위한 초기 데이터를 자동으로 생성합니다.")
        
        if st.button("샘플 데이터 생성하기", type="primary"):
            msg = db.create_sample_data()
            st.success(msg)
            if "완료" in msg:
                st.balloons()
                
        st.markdown("---")
        st.write("👉 **테스트 링크:**")
        st.code("https://leadership-360-jgj2r83.streamlit.app/?token=test1234", language="text")

# ==========================================
#  Scenario B: 응답자 모드 (토큰 있음)
# ==========================================
else:
    user = db.get_evaluator_by_token(token)
    
    # [수정] Pandas Series 에러 방지를 위해 'is None'으로 명확하게 검사
    if user is None:
        st.error("⛔ 유효하지 않은 접속 링크입니다.")
        st.stop()
    
    st.title(f"{user['corp_name']}")
    st.caption(f"프로젝트: {user['project_name']} | 평가자: {user['name']}")
    
    tasks = db.get_my_assignments(user['id'])
    
    # 진척률 표시
    done = len(tasks[tasks['status'] == 'COMPLETED'])
    total = len(tasks)
    if total > 0:
        st.progress(done / total, text=f"진행률: {done}/{total} 완료")
    
    st.divider()
    
    if total == 0:
        st.info("할당된 평가 대상이 없습니다.")
    elif done == total:
        st.success("🎉 모든 평가를 완료했습니다. 감사합니다!")
    else:
        col1, col2 = st.columns([1, 2])
        
        with col1:
            st.subheader("평가 대상")
            for _, task in tasks.iterrows():
                label = f"{task['leader_name']} ({task['relation']})"
                if task['status'] == 'COMPLETED':
                    st.button(f"✅ {label}", key=task['id'], disabled=True, use_container_width=True)
                else:
                    if st.button(f"👉 {label}", key=task['id'], type="secondary", use_container_width=True):
                        st.session_state['task'] = task
        
        with col2:
            if 'task' in st.session_state and st.session_state['task']['status'] == 'PENDING':
                t = st.session_state['task']
                st.subheader(f"📝 {t['leader_name']}님 평가")
                with st.form(f"f_{t['id']}"):
                    q1 = st.slider("Q1. 비전 제시 능력", 1, 5, 3)
                    q2 = st.slider("Q2. 소통 능력", 1, 5, 3)
                    comment = st.text_area("서술형 의견")
                    
                    if st.form_submit_button("제출"):
                        db.save_response(t['id'], q1, q2, comment)
                        st.toast("저장완료!")
                        del st.session_state['task']
                        st.rerun()
            elif total > done:
                st.info("👈 왼쪽에서 평가할 대상을 선택해주세요.")
