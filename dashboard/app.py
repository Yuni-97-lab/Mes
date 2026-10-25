"""MES 실시간 대시보드. 실행: streamlit run dashboard/app.py"""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import pandas as pd  # noqa: E402
import streamlit as st  # noqa: E402

from dashboard import queries  # noqa: E402
from mes.db import connect  # noqa: E402

REFRESH_SEC = 5
EMPTY_MSG = "데이터가 없습니다. 시뮬레이터를 실행하세요 (python -m simulator.simulate --speed 60)"
STATUS_COLORS = {"RUN": "#2e7d32", "IDLE": "#9e9e9e", "DOWN": "#c62828"}
BAR_COLOR = "#3b6ea5"

st.set_page_config(page_title="MES 대시보드", layout="wide")


def load_all() -> dict:
    """새로고침마다 짧게 연결을 열고 닫는다."""
    with connect() as conn:
        return {
            "kpi": queries.kpi_summary(conn),
            "oee": queries.oee_by_equipment(conn),
            "wo": queries.wo_progress(conn),
            "defect": queries.defect_by_process(conn),
            "equip": queries.equipment_status(conn),
        }


def has_data(d: dict) -> bool:
    return (not d["oee"].empty or not d["wo"].empty
            or bool(d["defect"]["input_qty"].sum()) or d["kpi"]["running"] > 0)


def render_kpis(kpi: dict) -> None:
    c1, c2, c3 = st.columns(3)
    c1.metric("평균 OEE", "-" if kpi["avg_oee"] is None else f"{kpi['avg_oee']:.1%}")
    c2.metric("전체 불량률", "-" if kpi["defect_rate"] is None else f"{kpi['defect_rate']:.2%}")
    c3.metric("가동 설비 수", f"{kpi['running']} / {kpi['total']}")


def _color_status(val: str) -> str:
    return f"color: white; background-color: {STATUS_COLORS.get(val, '#9e9e9e')}"


def render_equipment(df: pd.DataFrame) -> None:
    st.subheader("설비 상태")
    st.dataframe(df.rename(columns={"equipment_id": "ID", "name": "설비", "status": "상태", "since": "시작 시각"})
                 .style.map(_color_status, subset=["상태"]),
                 hide_index=True, width="stretch")


def render_work_orders(df: pd.DataFrame) -> None:
    st.subheader("작업지시 진행률")
    if df.empty:
        st.caption("작업지시가 없습니다.")
        return
    st.dataframe(
        df.rename(columns={"wo_id": "작업지시", "item_code": "품목", "planned_qty": "계획수량",
                           "good_qty": "양품수량", "progress_pct": "진행률", "status": "상태",
                           "due_date": "납기"}),
        column_config={"진행률": st.column_config.ProgressColumn(
            "진행률", format="%.1f%%", min_value=0, max_value=100)},
        hide_index=True, width="stretch")


def render_defects(df: pd.DataFrame) -> None:
    st.subheader("공정별 불량률")
    chart = (df.set_index("process_code")[["defect_rate"]] * 100).rename(columns={"defect_rate": "불량률(%)"})
    st.bar_chart(chart, color=BAR_COLOR)


def render_oee(df: pd.DataFrame) -> None:
    st.subheader("설비별 OEE")
    if df.empty:
        st.caption("OEE 데이터가 없습니다.")
        return
    chart = (df.groupby("equipment_name")[["oee"]].mean() * 100).rename(columns={"oee": "OEE(%)"})
    st.bar_chart(chart, color=BAR_COLOR)


@st.fragment(run_every=REFRESH_SEC)
def live_section() -> None:
    try:
        d = load_all()
    except Exception as exc:  # DB 일시 장애에도 앱이 죽지 않게
        st.error(f"DB 연결 실패: {exc}")
        return
    render_kpis(d["kpi"])
    if not has_data(d):
        st.info(EMPTY_MSG)
        render_equipment(d["equip"])
        return
    left, right = st.columns(2)
    with left:
        render_equipment(d["equip"])
        render_work_orders(d["wo"])
    with right:
        render_defects(d["defect"])
        render_oee(d["oee"])


def render_lot_trace() -> None:
    st.subheader("LOT 추적")
    col1, col2 = st.columns([2, 1])
    lot_no = col1.text_input("LOT 번호", key="lot_no")
    label = col2.radio("방향", ["정방향 (하위 LOT)", "역방향 (투입 LOT)"], key="direction", horizontal=True)
    if not lot_no.strip():
        return
    direction = "forward" if label.startswith("정") else "backward"
    try:
        with connect() as conn:
            df = queries.lot_trace(conn, lot_no.strip(), direction)
    except Exception as exc:
        st.error(f"조회 실패: {exc}")
        return
    if df.empty:
        st.warning("추적 결과가 없습니다.")
    else:
        st.dataframe(df, hide_index=True, width="stretch")


def main() -> None:
    st.title("MES 생산 현황 대시보드")
    with st.sidebar:
        st.header("설정")
        st.caption("시뮬레이터 속도는 실행 인자(--speed)로 정합니다. "
                   f"화면은 {REFRESH_SEC}초마다 자동 갱신됩니다.")
        st.button("지금 새로고침")
    live_section()
    st.divider()
    render_lot_trace()


main()
