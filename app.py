import datetime
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
    menu = st.sidebar.radio("Menu", ["대시보드", "프로젝트 설정", "엑셀 업로드", "데이터 관리", "설정"])

    corporates = db.list_corporates()
    projects = db.list_projects()

    if menu == "대시보드":
        st.title("📊 통합 진단 현황")
        st.caption("기업-프로젝트 단위 진행률을 한눈에 모니터링합니다.")

        corp_options = {"전체 기업": None}
        corp_options.update({row["name"]: row["id"] for _, row in corporates.iterrows()})
        corp_name = st.selectbox("기업 필터", list(corp_options.keys()))
        overview = db.get_dashboard_overview(corp_options[corp_name])

        if overview.empty:
            st.info("데이터가 없습니다. 프로젝트를 등록하고 엑셀을 업로드하세요.")
        else:
            total_assignments = int(overview["total_assignments"].sum())
            completed = int(overview["completed_assignments"].sum())
            total_projects = len(overview)
            col1, col2, col3, col4 = st.columns(4)
            col1.metric("기업 수", len(corporates))
            col2.metric("프로젝트 수", total_projects)
            col3.metric("전체 할당", f"{total_assignments}건")
            rate = 0 if total_assignments == 0 else round(completed / total_assignments * 100, 1)
            col4.metric("완료", f"{completed}건 ({rate}%)")

            overview_display = overview.copy()
            overview_display["진행률(%)"] = (overview_display["completion_rate"] * 100).round(1)
            overview_display = overview_display[[
                "corporate_name",
                "project_name",
                "year",
                "evaluator_count",
                "leader_count",
                "total_assignments",
                "completed_assignments",
                "진행률(%)",
            ]]
            overview_display.columns = [
                "기업",
                "프로젝트",
                "연도",
                "평가자 수",
                "리더 수",
                "총 할당",
                "완료",
                "진행률(%)",
            ]
            st.dataframe(overview_display, hide_index=True, use_container_width=True)

            st.bar_chart(overview_display.set_index("프로젝트")["진행률(%)"], height=240)

    elif menu == "프로젝트 설정":
        st.title("🏗 기업/프로젝트 생성")
        st.caption("멀티 테넌트 B2B 구조를 위해 기업과 프로젝트를 분리해 관리합니다.")

        with st.form("project_form"):
            col1, col2 = st.columns(2)
            existing_corp = col1.selectbox(
                "기존 기업 선택",
                options=["신규 기업 생성"] + corporates["name"].tolist(),
            )
            new_corp = col2.text_input("신규 기업명", placeholder="(주)테크컴퍼니")
            col3, col4 = st.columns(2)
            proj_name = col3.text_input("프로젝트명", placeholder="2025 상반기 진단")
            proj_year = col4.number_input("연도", value=datetime.datetime.now().year, step=1)

            submitted = st.form_submit_button("저장")
            if submitted:
                corp_name = new_corp.strip() if new_corp else None
                if not corp_name and existing_corp != "신규 기업 생성":
                    corp_name = existing_corp

                if not corp_name or not proj_name:
                    st.warning("기업명과 프로젝트명을 모두 입력하세요.")
                else:
                    proj_id = db.get_or_create_project(corp_name, proj_name, proj_year)
                    st.success(f"프로젝트가 등록되었습니다. (ID: {proj_id})")

        st.divider()
        st.subheader("등록된 프로젝트")
        if projects.empty:
            st.info("아직 등록된 프로젝트가 없습니다.")
        else:
            st.dataframe(projects.rename(
                columns={
                    "name": "프로젝트",
                    "year": "연도",
                    "status": "상태",
                    "corporate_name": "기업",
                }
            ), use_container_width=True, hide_index=True)

    elif menu == "엑셀 업로드":
        st.title("📤 평가자/리더 매핑 일괄 등록")
        st.caption("평가자, 리더, 관계(상사/동료/부하)를 한 번에 업로드합니다.")

        project_options = {"프로젝트 선택": None}
        for _, row in projects.iterrows():
            label = f"{row['corporate_name']} - {row['name']} ({row['year']})"
            project_options[label] = row["id"]

        with st.form("upload_form"):
            project_label = st.selectbox("적재할 프로젝트", list(project_options.keys()))
            uploaded_file = st.file_uploader(
                "엑셀/CSV 파일 업로드",
                type=["xlsx", "csv"],
                help="컬럼 예시: evaluator_name, evaluator_email, leader_name, relation, project_group",
            )
            submitted = st.form_submit_button("등록 시작")

            if submitted:
                project_id = project_options[project_label]
                if not project_id:
                    st.warning("프로젝트를 먼저 선택하세요.")
                elif not uploaded_file:
                    st.warning("파일을 업로드하세요.")
                else:
                    if uploaded_file.name.endswith(".csv"):
                        df = pd.read_csv(uploaded_file)
                    else:
                        df = pd.read_excel(uploaded_file)

                    success, msg = db.process_bulk_upload(project_id, df)
                    if success:
                        st.success(msg)
                    else:
                        st.error(msg)

        st.divider()
        st.subheader("템플릿 가이드")
        template = pd.DataFrame(
            [
                {
                    "evaluator_name": "홍길동",
                    "evaluator_email": "hong@test.com",
                    "evaluator_code": "E1001",
                    "leader_name": "김철수",
                    "leader_code": "L001",
                    "leader_position": "팀장",
                    "project_group": "영업본부",
                    "relation": "상사",
                }
            ]
        )
        st.dataframe(template, hide_index=True, use_container_width=True)
        st.download_button(
            "샘플 CSV 다운로드",
            data=template.to_csv(index=False).encode("utf-8-sig"),
            file_name="leadership360_template.csv",
            mime="text/csv",
        )

    elif menu == "데이터 관리":
        st.title("🗂 데이터 모니터링")
        st.caption("평가자-리더 매핑과 응답 현황을 프로젝트별로 확인합니다.")

        proj_map = {f"{row['corporate_name']} - {row['name']} ({row['year']})": row["id"] for _, row in projects.iterrows()}
        if not proj_map:
            st.info("먼저 프로젝트와 데이터를 업로드하세요.")
        else:
            project_label = st.selectbox("프로젝트 선택", list(proj_map.keys()))
            project_id = proj_map[project_label]

            snapshot = db.get_project_snapshot(project_id)
            col1, col2, col3, col4 = st.columns(4)
            col1.metric("평가자", snapshot.get("evaluators", 0))
            col2.metric("리더", snapshot.get("leaders", 0))
            col3.metric("할당", snapshot.get("total_assignments", 0))
            rate = 0 if snapshot.get("total_assignments", 0) == 0 else round(snapshot.get("completed_assignments", 0) / snapshot.get("total_assignments") * 100, 1)
            col4.metric("완료", f"{snapshot.get('completed_assignments', 0)}건 ({rate}%)")

            st.subheader("할당 현황")
            assignments = db.get_assignments_with_people(project_id)
            st.dataframe(assignments, hide_index=True, use_container_width=True)

            st.subheader("응답 데이터")
            responses = db.get_responses_with_people(project_id)
            if responses.empty:
                st.info("아직 제출된 응답이 없습니다.")
            else:
                st.dataframe(responses, hide_index=True, use_container_width=True)

    elif menu == "설정":
        st.title("⚙️ 시스템 설정")

        st.warning("⚠️ 데이터 상태가 꼬였을 때만 사용하세요.")

        col1, col2 = st.columns(2)

        with col1:
            if st.button("1. DB 강제 초기화 (Reset)", type="primary"):
                msg = db.reset_database()
                st.toast(msg, icon="🧹")
                st.success(msg)

        with col2:
            if st.button("2. 샘플 데이터 생성하기"):
                msg = db.create_sample_data()
                if "완료" in msg:
                    st.success(msg)
                    st.balloons()
                else:
                    st.warning(msg)

        st.divider()
        st.write("👉 **테스트 링크:**")
        # 실제 Streamlit 배포 주소가 있다면 그걸로 테스트하세요. 로컬용은 아래와 같습니다.
        st.code("https://leadership-360-test.streamlit.app/?token=test1234", language="text")

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
