import streamlit as st
import pandas as pd
import database as db

# 1. 앱 초기화
st.set_page_config(page_title="리더십 다면진단 시스템", layout="wide")
db.init_db()

# 2. URL 파라미터 확인 (토큰)
# Streamlit 최신 버전에서는 st.query_params 사용
token = st.query_params.get("token", None)

# ==========================================
#  [VIEW 1] 관리자 모드 (토큰 없음)
# ==========================================
if not token:
    st.sidebar.title("🔧 관리자 페이지")
    menu = st.sidebar.radio("메뉴", ["대시보드", "데이터 관리", "설정"])
    
    if menu == "대시보드":
        st.title("📊 진단 현황 대시보드")
        
        conn = db.get_connection()
        
        # 통계 데이터 조회
        df_corp = pd.read_sql("SELECT * FROM corporates", conn)
        df_proj = pd.read_sql("SELECT * FROM projects", conn)
        
        # 프로젝트별 진행률 조회
        query_progress = """
            SELECT P.name as Project, 
                   COUNT(A.id) as Total, 
                   SUM(CASE WHEN A.status='COMPLETED' THEN 1 ELSE 0 END) as Completed
            FROM assignments A
            JOIN projects P ON A.project_id = P.id
            GROUP BY P.id
        """
        df_progress = pd.read_sql(query_progress, conn)
        df_progress['Progress(%)'] = (df_progress['Completed'] / df_progress['Total'] * 100).fillna(0).round(1)
        
        conn.close()
        
        # 메트릭 표시
        m1, m2, m3 = st.columns(3)
        m1.metric("등록 기업 수", f"{len(df_corp)}개")
        m2.metric("진행 중 프로젝트", f"{len(df_proj)}개")
        m3.metric("총 응답 수", f"{df_progress['Completed'].sum() if not df_progress.empty else 0}건")
        
        st.divider()
        
        col1, col2 = st.columns([1, 2])
        with col1:
            st.subheader("🏢 기업 목록")
            st.dataframe(df_corp, hide_index=True)
        with col2:
            st.subheader("📈 프로젝트별 진행률")
            if not df_progress.empty:
                st.dataframe(df_progress, hide_index=True, use_container_width=True)
                # 진행률 바 차트
                st.bar_chart(df_progress.set_index("Project")['Progress(%)'])
            else:
                st.info("데이터가 없습니다.")

    elif menu == "데이터 관리":
        st.title("🗂 데이터 조회 및 관리")
        
        conn = db.get_connection()
        table = st.selectbox("테이블 선택", ["evaluators", "leaders", "assignments", "responses", "corporates", "projects"])
        
        df = pd.read_sql(f"SELECT * FROM {table}", conn)
        st.dataframe(df, use_container_width=True)
        conn.close()

    elif menu == "설정":
        st.title("⚙️ 시스템 설정")
        
        st.warning("⚠️ 초기화 주의")
        if st.button("샘플 데이터 생성하기 (초기 세팅용)"):
            msg = db.create_sample_data()
            st.success(msg)
            st.balloons()
            
        st.info("테스트 방법: 아래 링크를 복사해서 새 창에서 열어보세요.")
        st.code("http://localhost:8501/?token=test1234", language="text")

# ==========================================
#  [VIEW 2] 응답자 모드 (토큰 있음)
# ==========================================
else:
    # 토큰 검증
    user = db.get_evaluator_by_token(token)
    
    if user is None:
        st.error("⛔ 유효하지 않거나 만료된 진단 링크입니다. 관리자에게 문의하세요.")
        st.stop()
        
    # 사용자 환영 메시지
    st.markdown(f"### {user['corp_name']} - {user['project_name']}")
    st.write(f"👋 안녕하세요, **{user['name']}**님. 리더십 다면진단에 오신 것을 환영합니다.")
    
    # 할당된 과제 조회
    tasks = db.get_my_assignments(user['id'])
    
    # 진행률 계산
    done_count = len(tasks[tasks['status'] == 'COMPLETED'])
    total_count = len(tasks)
    progress = done_count / total_count if total_count > 0 else 0
    
    st.progress(progress, text=f"진행률: {done_count} / {total_count} 완료")
    
    st.divider()
    
    if total_count == 0:
        st.info("평가할 대상자가 없습니다.")
    elif done_count == total_count:
        st.success("🎉 모든 평가를 완료하셨습니다. 참여해 주셔서 감사합니다!")
        st.balloons()
    
    # 메인 화면 구성 (좌측: 목록, 우측: 설문지)
    col_list, col_form = st.columns([1, 2])
    
    # [좌측] 평가 대상 목록
    selected_task_id = None
    with col_list:
        st.subheader("평가 대상")
        for index, task in tasks.iterrows():
            label = f"{task['leader_name']} {task['position']}"
            if task['status'] == 'COMPLETED':
                st.button(f"✅ {label} (완료)", key=f"btn_{task['id']}", disabled=True, use_container_width=True)
            else:
                # '평가하기' 버튼을 누르면 해당 ID가 선택됨
                if st.button(f"👉 {label}", key=f"btn_{task['id']}", type="primary", use_container_width=True):
                    st.session_state['selected_task'] = task
    
    # [우측] 설문 폼
    with col_form:
        if 'selected_task' in st.session_state and st.session_state['selected_task']['status'] == 'PENDING':
            target = st.session_state['selected_task']
            
            st.markdown(f"""
            #### 📝 평가 대상: {target['leader_name']} {target['position']}
            - **부서:** {target['department']}
            - **관계:** {target['relation']}
            """)
            st.markdown("---")
            
            with st.form(key=f"form_{target['id']}"):
                st.write("**Q1. 이 리더는 조직의 목표와 비전을 명확하게 제시합니까?**")
                q1 = st.slider("점수 (1: 전혀 아니다 ~ 5: 매우 그렇다)", 1, 5, 3, key="q1")
                
                st.write("**Q2. 이 리더는 팀원의 의견을 경청하고 피드백을 수용합니까?**")
                q2 = st.slider("점수 (1: 전혀 아니다 ~ 5: 매우 그렇다)", 1, 5, 3, key="q2")
                
                st.write("**Q3. 리더에게 해주고 싶은 말 (익명 보장)**")
                comment = st.text_area("자유롭게 작성해주세요.", height=100)
                
                submit_btn = st.form_submit_button("평가 제출", type="primary")
                
                if submit_btn:
                    if db.save_response(target['id'], q1, q2, comment):
                        st.success("저장되었습니다!")
                        # 선택 상태 초기화 및 리로드
                        del st.session_state['selected_task']
                        st.rerun()
                    else:
                        st.error("저장 중 오류가 발생했습니다.")
        
        elif 'selected_task' not in st.session_state and total_count > done_count:
            st.info("👈 왼쪽 목록에서 평가할 대상을 선택해주세요.")