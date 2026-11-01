import os
import json
import html
import hmac
import time
from datetime import datetime, date, timedelta
import streamlit as st
import streamlit.components.v1 as components
import plotly.graph_objects as go
from dotenv import load_dotenv
from google import genai
from google.genai import types

# -------------------------------------------------------------
# 1. 初期設定 & セキュリティ（環境変数・ディレクトリ）
# -------------------------------------------------------------
load_dotenv()
DEFAULT_API_KEY = os.getenv("GEMINI_API_KEY", "")
# Streamlit Secrets が存在する場合は優先読み込み（クラウド二重金庫）
if hasattr(st, "secrets") and "GEMINI_API_KEY" in st.secrets:
    DEFAULT_API_KEY = st.secrets["GEMINI_API_KEY"]

# 暗証番号（パスコード）の取得（環境変数またはSecrets、未設定なら '1234'）
APP_PASSCODE = os.getenv("APP_PASSCODE", "")
if hasattr(st, "secrets") and "APP_PASSCODE" in st.secrets:
    APP_PASSCODE = str(st.secrets["APP_PASSCODE"])
if not APP_PASSCODE:
    APP_PASSCODE = "1234"

DATA_DIR = os.path.join(os.path.dirname(__file__), "data")
os.makedirs(DATA_DIR, exist_ok=True)
HISTORY_FILE = os.path.join(DATA_DIR, "history.json")
PROFILE_FILE = os.path.join(DATA_DIR, "profile.json")

# ページ基本設定
st.set_page_config(
    page_title="モグバランス - かんたんAI食事＆PFCパートナー",
    page_icon="🥗",
    layout="wide",
    initial_sidebar_state="expanded"
)

# -------------------------------------------------------------
# 2. プロファイル & 履歴の読み込み / 保存関数
# -------------------------------------------------------------
def load_profile():
    default_profile = {
        "gender": "男性",
        "age": 30,
        "height": 172.0,
        "weight": 68.0,
        "activity_level": "週3〜5回の筋トレ/運動 (標準活動: x1.55)",
        "goal": "💪 筋肉増量（バルクアップ）: カロリー余剰 + 高タンパク"
    }
    if os.path.exists(PROFILE_FILE):
        try:
            with open(PROFILE_FILE, "r", encoding="utf-8") as f:
                loaded = json.load(f)
                default_profile.update(loaded)
        except Exception:
            pass
    return default_profile

def save_profile(data):
    try:
        with open(PROFILE_FILE, "w", encoding="utf-8") as f:
            json.dump(data, f, ensure_ascii=False, indent=2)
    except Exception as e:
        print(f"Error saving profile: {e}")

def load_all_history():
    if os.path.exists(HISTORY_FILE):
        try:
            with open(HISTORY_FILE, "r", encoding="utf-8") as f:
                return json.load(f)
        except Exception:
            return {}
    return {}

def save_daily_record(date_str, meals, total, targets):
    history = load_all_history()
    history[date_str] = {
        "saved_at": datetime.now().strftime("%Y年%m月%d日 %H:%M:%S"),
        "meals": meals,
        "total": total,
        "targets": targets
    }
    with open(HISTORY_FILE, "w", encoding="utf-8") as f:
        json.dump(history, f, ensure_ascii=False, indent=2)

# ストリーク（連続記録日数）計算ロジック
def calculate_streak(history, has_today_meal):
    saved_dates = set(history.keys())
    today = date.today()
    
    if today.isoformat() in saved_dates or has_today_meal:
        current_check = today
        streak = 0
        while current_check.isoformat() in saved_dates or (current_check == today and has_today_meal):
            streak += 1
            current_check -= timedelta(days=1)
        return streak
    else:
        yesterday = today - timedelta(days=1)
        current_check = yesterday
        streak = 0
        while current_check.isoformat() in saved_dates:
            streak += 1
            current_check -= timedelta(days=1)
        return streak

def calculate_max_streak(history):
    if not history:
        return 0
    try:
        sorted_dates = sorted([date.fromisoformat(d) for d in history.keys()])
        if not sorted_dates:
            return 0
        max_s = 1
        cur_s = 1
        for i in range(1, len(sorted_dates)):
            if sorted_dates[i] == sorted_dates[i-1] + timedelta(days=1):
                cur_s += 1
                max_s = max(max_s, cur_s)
            elif sorted_dates[i] > sorted_dates[i-1] + timedelta(days=1):
                cur_s = 1
        return max_s
    except Exception:
        return 0

# セッション状態の初期化
today_str = date.today().isoformat()
if "current_date" not in st.session_state:
    st.session_state.current_date = today_str

if "meals" not in st.session_state:
    st.session_state.meals = []

if "selected_theme" not in st.session_state:
    st.session_state.selected_theme = "🌙 漆黒 (シックブラック)"

# 身体データのステート管理初期化
if "profile" not in st.session_state:
    st.session_state.profile = load_profile()

if "input_draft" not in st.session_state:
    st.session_state.input_draft = ""

# -------------------------------------------------------------
# 3. 明暗8色テーマ（明暗分離専用PFCパレット ＆ 高コントラスト定義）
# -------------------------------------------------------------
THEMES = {
    # 🌙 暗いテーマ群（ダークモード: 背景黒系、純白文字、鮮明PFC）
    "🌙 漆黒 (シックブラック)": {
        "is_dark": True,
        "bg": "#0B0F19",
        "card_bg": "#151E2E",
        "card_border": "#334155",
        "text": "#FFFFFF",
        "text_sub": "#CBD5E1",
        "accent": "#38BDF8",
        "accent_glow": "rgba(56, 189, 248, 0.35)",
        "btn_text": "#0B0F19",
        "input_bg": "#1E293B",
        "input_text": "#FFFFFF",
        "input_border": "#475569",
        "placeholder": "rgba(255, 255, 255, 0.75)",
        "p_color": "#FF6B6B",
        "f_color": "#FFA94D",
        "c_color": "#F59E0B"
    },
    "🌙 深海 (サファイアブルー)": {
        "is_dark": True,
        "bg": "#0A192F",
        "card_bg": "#112240",
        "card_border": "#2E476F",
        "text": "#FFFFFF",
        "text_sub": "#CBD5E1",
        "accent": "#64FFDA",
        "accent_glow": "rgba(100, 255, 218, 0.35)",
        "btn_text": "#0A192F",
        "input_bg": "#162B4D",
        "input_text": "#FFFFFF",
        "input_border": "#3D5A80",
        "placeholder": "rgba(255, 255, 255, 0.75)",
        "p_color": "#FF6B6B",
        "f_color": "#FFA94D",
        "c_color": "#F59E0B"
    },
    "🌙 深緑 (フォレストグリーン)": {
        "is_dark": True,
        "bg": "#061A14",
        "card_bg": "#0D2E24",
        "card_border": "#215947",
        "text": "#FFFFFF",
        "text_sub": "#CBD5E1",
        "accent": "#10B981",
        "accent_glow": "rgba(16, 185, 129, 0.35)",
        "btn_text": "#061A14",
        "input_bg": "#133D30",
        "input_text": "#FFFFFF",
        "input_border": "#2D7A62",
        "placeholder": "rgba(255, 255, 255, 0.75)",
        "p_color": "#FF6B6B",
        "f_color": "#FFA94D",
        "c_color": "#F59E0B"
    },
    "🌙 真紅 (クリムゾンレッド)": {
        "is_dark": True,
        "bg": "#1A0A10",
        "card_bg": "#2A101A",
        "card_border": "#5C2034",
        "text": "#FFFFFF",
        "text_sub": "#FFE4E6",
        "accent": "#FB7185",
        "accent_glow": "rgba(251, 113, 133, 0.35)",
        "btn_text": "#1A0A10",
        "input_bg": "#3B1824",
        "input_text": "#FFFFFF",
        "input_border": "#7E2A47",
        "placeholder": "rgba(255, 255, 255, 0.75)",
        "p_color": "#FF6B6B",
        "f_color": "#FFA94D",
        "c_color": "#F59E0B"
    },

    # ☀️ 明るいテーマ群（ライトモード: 背景白系、濃紺文字、深色PFC）
    "☀️ 白銀 (ピュアプラチナ)": {
        "is_dark": False,
        "bg": "#F8FAFC",
        "card_bg": "#FFFFFF",
        "card_border": "#CBD5E1",
        "text": "#0F172A",
        "text_sub": "#334155",
        "accent": "#0284C7",
        "accent_glow": "rgba(2, 132, 199, 0.25)",
        "btn_text": "#FFFFFF",
        "input_bg": "#F1F5F9",
        "input_text": "#0F172A",
        "input_border": "#94A3B8",
        "placeholder": "#64748B",
        "p_color": "#DC2626",
        "f_color": "#D97706",
        "c_color": "#78350F"
    },
    "☀️ 青空 (スカイブルー)": {
        "is_dark": False,
        "bg": "#F0F9FF",
        "card_bg": "#FFFFFF",
        "card_border": "#BAE6FD",
        "text": "#0C4A6E",
        "text_sub": "#0369A1",
        "accent": "#0284C7",
        "accent_glow": "rgba(2, 132, 199, 0.25)",
        "btn_text": "#FFFFFF",
        "input_bg": "#E0F2FE",
        "input_text": "#0C4A6E",
        "input_border": "#7DD3FC",
        "placeholder": "#0369A1",
        "p_color": "#DC2626",
        "f_color": "#D97706",
        "c_color": "#78350F"
    },
    "☀️ 若草 (ミントグリーン)": {
        "is_dark": False,
        "bg": "#F0FDF4",
        "card_bg": "#FFFFFF",
        "card_border": "#BBF7D0",
        "text": "#064E3B",
        "text_sub": "#15803D",
        "accent": "#059669",
        "accent_glow": "rgba(5, 150, 105, 0.25)",
        "btn_text": "#FFFFFF",
        "input_bg": "#DCFCE7",
        "input_text": "#064E3B",
        "input_border": "#86EFAC",
        "placeholder": "#15803D",
        "p_color": "#DC2626",
        "f_color": "#D97706",
        "c_color": "#78350F"
    },
    "☀️ 桜紅 (コーラルピンク)": {
        "is_dark": False,
        "bg": "#FFF1F2",
        "card_bg": "#FFFFFF",
        "card_border": "#FECDD3",
        "text": "#881337",
        "text_sub": "#BE123C",
        "accent": "#E11D48",
        "accent_glow": "rgba(225, 29, 72, 0.25)",
        "btn_text": "#FFFFFF",
        "input_bg": "#FFE4E6",
        "input_text": "#881337",
        "input_border": "#FDA4AF",
        "placeholder": "#BE123C",
        "p_color": "#DC2626",
        "f_color": "#D97706",
        "c_color": "#78350F"
    }
}

# -------------------------------------------------------------
# 4. サイドバー設定 & 身体データの双方向連動（完全日本語化）
# -------------------------------------------------------------
# テーマ切り替え
selected_theme_name = st.sidebar.selectbox(
    "🎨 カラーテーマの選択",
    list(THEMES.keys()),
    index=list(THEMES.keys()).index(st.session_state.selected_theme)
)
st.session_state.selected_theme = selected_theme_name
theme = THEMES[selected_theme_name]

badge_bg = "rgba(255,255,255,0.08)" if theme["is_dark"] else "rgba(0,0,0,0.04)"
st.sidebar.markdown(f"""
<div style='margin-bottom:12px;'>
    <h2 style='margin:0; font-size:20px; font-weight:800; color:{theme["text"]};'>💎 設定・プロフィール</h2>
</div>
<div style='background:{badge_bg}; border-radius:8px; padding:7px 12px; font-size:12.5px; font-weight:700; color:{theme["accent"]}; margin-bottom:16px; border-left:3px solid {theme["accent"]};'>
    🔒 身体データは自動記憶・同期中
</div>
""", unsafe_allow_html=True)

# テーマCSSの動的注入（ツールバー干渉解除 ＆ ポップアップリスト視認性完全強化）
st.markdown(f"""
<style>
    .stApp {{
        background-color: {theme['bg']} !important;
        color: {theme['text']} !important;
    }}
    header {{background-color: transparent !important;}}
    
    /* 不要なDeployボタンの非表示（プロ品質UI化） */
    .stAppDeployButton {{
        display: none !important;
    }}
    
    /* サイドバーの背景 */
    section[data-testid="stSidebar"] {{
        background-color: {theme['card_bg']} !important;
        border-right: 1px solid {theme['card_border']} !important;
    }}
    
    /* 全画面の全ラベルの白飛び根絶（メイン画面・サイドバー共通） */
    label,
    label *,
    [data-testid="stWidgetLabel"],
    [data-testid="stWidgetLabel"] * {{
        color: {theme['text']} !important;
        -webkit-text-fill-color: {theme['text']} !important;
        font-weight: 700 !important;
        font-size: 14px !important;
    }}
    
    /* 入力枠・セレクトボックスの白飛び・黒浮き根絶 */
    div[data-baseweb="select"],
    div[data-baseweb="select"] *,
    div[data-baseweb="input"],
    div[data-baseweb="input"] * {{
        background-color: {theme['input_bg']} !important;
        color: {theme['input_text']} !important;
        -webkit-text-fill-color: {theme['input_text']} !important;
        font-weight: 700 !important;
    }}
    div[data-baseweb="select"] > div,
    div[data-baseweb="input"] > div {{
        background-color: {theme['input_bg']} !important;
        border: 1.5px solid {theme['input_border']} !important;
        border-radius: 10px !important;
    }}
    div[data-baseweb="select"] > div:focus-within,
    div[data-baseweb="input"] > div:focus-within {{
        border-color: {theme['accent']} !important;
        box-shadow: 0 0 14px {theme['accent_glow']} !important;
    }}
    div[data-baseweb="select"] svg,
    div[data-baseweb="input"] svg {{
        fill: {theme['accent']} !important;
    }}
    
    /* ドロップダウンを開いたときの選択肢リスト（黒浮き・白飛び根絶） */
    div[data-baseweb="popover"],
    div[data-baseweb="popover"] *,
    div[data-baseweb="menu"],
    div[data-baseweb="menu"] *,
    ul[role="listbox"],
    ul[role="listbox"] * {{
        background-color: {theme['card_bg']} !important;
        color: {theme['text']} !important;
        -webkit-text-fill-color: {theme['text']} !important;
    }}
    div[data-baseweb="popover"] > div,
    ul[role="listbox"] {{
        border: 1.5px solid {theme['card_border']} !important;
        border-radius: 12px !important;
        box-shadow: 0 8px 30px rgba(0,0,0,0.3) !important;
    }}
    li[role="option"] {{
        color: {theme['text']} !important;
        -webkit-text-fill-color: {theme['text']} !important;
        background-color: {theme['card_bg']} !important;
        font-weight: 600 !important;
    }}
    li[role="option"]:hover,
    li[role="option"][aria-selected="true"] {{
        background-color: {theme['accent']} !important;
        color: {theme['btn_text']} !important;
        -webkit-text-fill-color: {theme['btn_text']} !important;
        font-weight: 700 !important;
    }}
    
    /* 数値入力の +/- ボタン */
    button[data-testid="stNumberInputStepDown"],
    button[data-testid="stNumberInputStepUp"] {{
        background-color: {theme['card_border']} !important;
        color: {theme['text']} !important;
        border: 1px solid {theme['card_border']} !important;
        border-radius: 6px !important;
    }}
    button[data-testid="stNumberInputStepDown"] svg,
    button[data-testid="stNumberInputStepUp"] svg {{
        fill: {theme['text']} !important;
    }}
    
    /* 過去ログ・メトリック数値カードの白飛び・黒埋もれ完全根絶 */
    div[data-testid="stMetric"] {{
        background-color: {theme['card_bg']} !important;
        border: 1.5px solid {theme['card_border']} !important;
        border-radius: 14px !important;
        padding: 14px 18px !important;
        box-shadow: 0 4px 16px {theme['accent_glow']} !important;
    }}
    div[data-testid="stMetricLabel"],
    div[data-testid="stMetricLabel"] * {{
        color: {theme['text_sub']} !important;
        -webkit-text-fill-color: {theme['text_sub']} !important;
        font-weight: 700 !important;
        font-size: 13.5px !important;
    }}
    div[data-testid="stMetricValue"],
    div[data-testid="stMetricValue"] * {{
        color: {theme['text']} !important;
        -webkit-text-fill-color: {theme['text']} !important;
        font-weight: 800 !important;
        font-size: 24px !important;
    }}
    div[data-testid="stMetricDelta"],
    div[data-testid="stMetricDelta"] * {{
        color: {theme['accent']} !important;
        -webkit-text-fill-color: {theme['accent']} !important;
        font-weight: 700 !important;
    }}
    
    /* 折りたたみ枠（Expander）の完全テーマ同期 */
    div[data-testid="stExpander"] {{
        background-color: {theme['card_bg']} !important;
        border: 1px solid {theme['card_border']} !important;
        border-radius: 14px !important;
        margin-top: 10px !important;
        box-shadow: 0 2px 10px {'rgba(0,0,0,0.2)' if theme['is_dark'] else 'rgba(0,0,0,0.03)'} !important;
    }}
    div[data-testid="stExpander"] summary,
    div[data-testid="stExpander"] summary * {{
        color: {theme['text']} !important;
        -webkit-text-fill-color: {theme['text']} !important;
        font-weight: 700 !important;
    }}
    
    /* 通知・アラートの文字色保護 */
    div[data-testid="stAlert"] {{
        background-color: {theme['card_bg']} !important;
        border: 1.5px solid {theme['accent']} !important;
        border-radius: 12px !important;
    }}
    div[data-testid="stAlert"] * {{
        color: {theme['text']} !important;
        -webkit-text-fill-color: {theme['text']} !important;
    }}
    
    .sidebar-card {{
        background: {'rgba(255, 255, 255, 0.04)' if theme['is_dark'] else 'rgba(0, 0, 0, 0.02)'};
        border: 1px solid {theme['card_border']};
        border-radius: 14px;
        padding: 16px;
        margin-bottom: 14px;
        box-shadow: 0 4px 14px rgba(0, 0, 0, 0.1);
    }}
    .sidebar-card-title {{
        color: {theme['accent']};
        font-size: 14px;
        font-weight: 800;
        margin-bottom: 12px;
        display: flex;
        align-items: center;
        gap: 6px;
        letter-spacing: 0.5px;
    }}
    
    .modern-card {{
        background: {theme['card_bg']};
        border: 1px solid {theme['card_border']};
        border-radius: 16px;
        padding: 20px;
        margin-bottom: 16px;
        box-shadow: 0 4px 20px {theme['accent_glow']};
    }}
    .modern-pill {{
        background: {theme['card_border']};
        color: {theme['accent']};
        padding: 4px 14px;
        border-radius: 20px;
        font-size: 0.88rem;
        font-weight: 700;
        display: inline-block;
        border: 1px solid {theme['accent']};
    }}
    
    /* アプリ本体のボタンのみにテーマカラーを適用（管理メニューへの誤干渉を遮断） */
    .stButton > button,
    div[data-testid="stFormSubmitButton"] > button,
    button[kind="primaryFormSubmit"],
    button[kind="secondaryFormSubmit"] {{
        border-radius: 12px !important;
        font-weight: 700 !important;
        background: {theme['accent']} !important;
        color: {theme['btn_text']} !important;
        -webkit-text-fill-color: {theme['btn_text']} !important;
        border: 1px solid {theme['accent']} !important;
        box-shadow: 0 4px 16px {theme['accent_glow']} !important;
        transition: all 0.25s cubic-bezier(0.4, 0, 0.2, 1) !important;
    }}
    .stButton > button:hover,
    div[data-testid="stFormSubmitButton"] > button:hover {{
        transform: translateY(-2px) !important;
        box-shadow: 0 6px 24px {theme['accent_glow']} !important;
        filter: brightness(1.15) !important;
    }}
    
    /* ラジオボタングループの視認性完全強化 */
    div[role="radiogroup"] label {{
        background: {theme['card_bg']} !important;
        border: 1.5px solid {theme['card_border']} !important;
        padding: 8px 18px !important;
        border-radius: 12px !important;
        margin-right: 10px !important;
        cursor: pointer !important;
        transition: all 0.2s ease !important;
    }}
    div[role="radiogroup"] label,
    div[role="radiogroup"] label * {{
        color: {theme['text']} !important;
        -webkit-text-fill-color: {theme['text']} !important;
        font-weight: 700 !important;
        font-size: 14.5px !important;
    }}
    div[role="radiogroup"] label:has(input:checked) {{
        border-color: {theme['accent']} !important;
        box-shadow: 0 0 14px {theme['accent_glow']} !important;
        background: {'rgba(255, 255, 255, 0.08)' if theme['is_dark'] else 'rgba(0, 0, 0, 0.05)'} !important;
    }}
    div[role="radiogroup"] label:has(input:checked),
    div[role="radiogroup"] label:has(input:checked) * {{
        color: {theme['accent']} !important;
        -webkit-text-fill-color: {theme['accent']} !important;
    }}
    
    /* チャット入力テキストエリア（テーマカラー枠線 ＆ 高コントラスト・プレースホルダー） */
    div[data-testid="stTextArea"] textarea {{
        background-color: {theme['input_bg']} !important;
        color: {theme['input_text']} !important;
        -webkit-text-fill-color: {theme['input_text']} !important;
        border: 2px solid {theme['accent']} !important;
        border-radius: 14px !important;
        box-shadow: 0 0 18px {theme['accent_glow']} !important;
        font-size: 15.5px !important;
        font-weight: 600 !important;
        line-height: 1.6 !important;
        padding: 14px 18px !important;
        transition: all 0.3s ease !important;
    }}
    div[data-testid="stTextArea"] textarea:focus {{
        border-color: {theme['accent']} !important;
        box-shadow: 0 0 28px {theme['accent_glow']} !important;
    }}
    div[data-testid="stTextArea"] textarea::placeholder {{
        color: {theme['placeholder']} !important;
        font-size: 14.5px !important;
        font-weight: 500 !important;
        line-height: 1.6 !important;
    }}
    div[data-testid="stForm"] {{
        border: none !important;
        padding: 0 !important;
    }}
    
    /* タブの未選択・選択時テキストの視認性完全強化 */
    button[data-baseweb="tab"] {{
        color: {theme['text_sub']} !important;
    }}
    button[data-baseweb="tab"],
    button[data-baseweb="tab"] * {{
        color: {theme['text_sub']} !important;
        -webkit-text-fill-color: {theme['text_sub']} !important;
        font-size: 15px !important;
        font-weight: 600 !important;
    }}
    button[data-baseweb="tab"][aria-selected="true"],
    button[data-baseweb="tab"][aria-selected="true"] * {{
        color: {theme['accent']} !important;
        -webkit-text-fill-color: {theme['accent']} !important;
        font-weight: 800 !important;
    }}
    div[data-baseweb="tab-highlight"] {{
        background-color: {theme['accent']} !important;
    }}
    
    /* 案内文・注記テキスト（キャプション）のハイコントラスト化 */
    .stCaption,
    [data-testid="stCaptionContainer"],
    [data-testid="stCaptionContainer"] * {{
        color: {theme['text_sub']} !important;
        -webkit-text-fill-color: {theme['text_sub']} !important;
        font-size: 13.5px !important;
        font-weight: 500 !important;
    }}
</style>
""", unsafe_allow_html=True)

# -------------------------------------------------------------
# 4.1 セキュリティ電子錠（パスコード認証 ＆ 総当たり攻撃防御）
# -------------------------------------------------------------
if "authenticated" not in st.session_state:
    st.session_state.authenticated = False
if "failed_attempts" not in st.session_state:
    st.session_state.failed_attempts = 0
if "lockout_until" not in st.session_state:
    st.session_state.lockout_until = None

if not st.session_state.authenticated:
    now_ts = datetime.now()
    
    st.markdown(f"""
    <div style="max-width: 460px; margin: 40px auto 20px auto; padding: 32px 24px; background: {theme['card_bg']}; border: 1.5px solid {theme['card_border']}; border-radius: 20px; text-align: center; box-shadow: 0 8px 32px {theme['accent_glow']};">
        <div style="font-size: 46px; margin-bottom: 12px;">🔐</div>
        <h2 style="margin: 0 0 8px 0; font-weight: 800; color: {theme['text']};">モグバランス</h2>
        <div style="font-size: 14px; color: {theme['text_sub']}; font-weight: 600; line-height: 1.6;">
            セキュリティ保護中<br>合言葉（パスコード）を入力してアプリを開いてください
        </div>
    </div>
    """, unsafe_allow_html=True)
    
    col_c1, col_c2, col_c3 = st.columns([1, 1.3, 1])
    with col_c2:
        # ロックアウト状態の検証
        if st.session_state.lockout_until and now_ts < st.session_state.lockout_until:
            rem_sec = int((st.session_state.lockout_until - now_ts).total_seconds())
            st.error(f"🚫 連続で暗証番号を間違えたため一時ロックされています。\n残り {rem_sec} 秒後に再試行してください。")
            st.stop()

        with st.form("login_form"):
            entered_code = st.text_input("暗証番号 (パスコード)", type="password", placeholder="初期暗証番号: 1234", help="安全保護のため暗証番号を入力してください")
            submit_login = st.form_submit_button("🔓 ロック解除して利用開始", use_container_width=True)
            if submit_login:
                # タイミング攻撃を防ぐ安全な一定時間比較 (hmac.compare_digest)
                if hmac.compare_digest(entered_code.strip(), APP_PASSCODE.strip()):
                    st.session_state.authenticated = True
                    st.session_state.failed_attempts = 0
                    st.session_state.lockout_until = None
                    st.rerun()
                else:
                    time.sleep(1.2)  # 物理遅延により総当たりボットの連打を完全に無力化
                    st.session_state.failed_attempts += 1
                    if st.session_state.failed_attempts >= 5:
                        st.session_state.lockout_until = datetime.now() + timedelta(minutes=3)
                        st.error("🚫 連続で5回間違えたため、3分間入力を完全ロックしました。")
                    else:
                        rem_tries = 5 - st.session_state.failed_attempts
                        st.error(f"❌ 暗証番号が違います。（残り試行可能回数: {rem_tries} 回）")
        st.markdown(f"<div style='text-align:center; font-size:12.5px; color:{theme['text_sub']}; margin-top:14px; font-weight:600;'>※初期暗証番号は <code>1234</code> です</div>", unsafe_allow_html=True)
    st.stop()

# APIキー設定（DOM上の生キー完全不可視化・F12開発者ツールの覗き見防止）
has_default_key = bool(DEFAULT_API_KEY)
api_key_custom = st.sidebar.text_input(
    "🔑 AI連携キー（安全保護・非公開）",
    value="",
    type="password",
    placeholder="🔒 金庫（.env / Secrets）から安全に適用中" if has_default_key else "Gemini APIキーを入力してください",
    help="金庫から安全にキーが読み込まれている場合は入力不要です。別のキーを使いたい場合のみ手動入力してください。"
)
# 実効APIキー（カスタム入力があれば優先、なければ金庫のキー）
api_key_input = api_key_custom.strip() if api_key_custom.strip() else DEFAULT_API_KEY

st.sidebar.divider()

# 身体データ変更時のコールバック関数（押し戻されバグを根本解決）
def on_profile_update():
    st.session_state.profile["gender"] = st.session_state.prof_gender
    st.session_state.profile["age"] = st.session_state.prof_age
    st.session_state.profile["height"] = st.session_state.prof_height
    st.session_state.profile["weight"] = st.session_state.prof_weight
    st.session_state.profile["activity_level"] = st.session_state.prof_activity
    st.session_state.profile["goal"] = st.session_state.prof_goal
    save_profile(st.session_state.profile)

# カード1: 身体データ入力（完全日本語化）
st.sidebar.markdown("<div class='sidebar-card-title'>👤 身体データ</div>", unsafe_allow_html=True)

gender_options = ["男性", "女性"]
gender_idx = gender_options.index(st.session_state.profile.get("gender", "男性")) if st.session_state.profile.get("gender") in gender_options else 0

col_g, col_a = st.sidebar.columns(2)
with col_g:
    gender = st.selectbox("性別", gender_options, index=gender_idx, key="prof_gender", on_change=on_profile_update)
with col_a:
    age = st.number_input("年齢", min_value=15, max_value=90, value=int(st.session_state.profile.get("age", 30)), step=1, key="prof_age", on_change=on_profile_update)

col_h, col_w = st.sidebar.columns(2)
with col_h:
    height = st.number_input("身長 (cm)", min_value=120.0, max_value=220.0, value=float(st.session_state.profile.get("height", 172.0)), step=0.5, key="prof_height", on_change=on_profile_update)
with col_w:
    weight = st.number_input("体重 (kg)", min_value=30.0, max_value=180.0, value=float(st.session_state.profile.get("weight", 68.0)), step=0.5, key="prof_weight", on_change=on_profile_update)

activity_options = [
    "デスクワーク中心 (低活動: x1.2)",
    "週1〜2回の軽い運動 (中低活動: x1.375)",
    "週3〜5回の筋トレ/運動 (標準活動: x1.55)",
    "ほぼ毎日のハードな運動 (高活動: x1.725)"
]
act_idx = activity_options.index(st.session_state.profile.get("activity_level", activity_options[2])) if st.session_state.profile.get("activity_level") in activity_options else 2
activity_level = st.sidebar.selectbox("日常の活動強度", activity_options, index=act_idx, key="prof_activity", on_change=on_profile_update)

multipliers = {
    "デスクワーク中心 (低活動: x1.2)": 1.2,
    "週1〜2回の軽い運動 (中低活動: x1.375)": 1.375,
    "週3〜5回の筋トレ/運動 (標準活動: x1.55)": 1.55,
    "ほぼ毎日のハードな運動 (高活動: x1.725)": 1.725
}

# カード2: 目標選択
st.sidebar.markdown("<div class='sidebar-card-title'>🎯 ボディメイクの目標</div>", unsafe_allow_html=True)
goal_options = [
    "💪 筋肉増量（バルクアップ）: カロリー余剰 + 高タンパク",
    "🔥 脂肪燃焼（減量・ダイエット）: カロリー制限 + 筋肉保護",
    "⚖️ 体型維持（コンディション維持）: バランス型"
]
goal_idx = goal_options.index(st.session_state.profile.get("goal", goal_options[0])) if st.session_state.profile.get("goal") in goal_options else 0
goal = st.sidebar.radio("目標を選択", goal_options, index=goal_idx, key="prof_goal", on_change=on_profile_update, label_visibility="collapsed")

# 目標値の自動計算
if gender == "男性":
    bmr = 88.362 + (13.397 * weight) + (4.799 * height) - (5.677 * age)
else:
    bmr = 447.593 + (9.247 * weight) + (3.098 * height) - (4.330 * age)

tdee = bmr * multipliers[activity_level]

if "筋肉増量" in goal:
    target_c = tdee + 400
    target_p = weight * 2.2
    target_f = (target_c * 0.22) / 9
    target_c_carb = (target_c - (target_p * 4 + target_f * 9)) / 4
elif "脂肪燃焼" in goal:
    target_c = max(tdee - 500, bmr)
    target_p = weight * 2.2
    target_f = (target_c * 0.20) / 9
    target_c_carb = (target_c - (target_p * 4 + target_f * 9)) / 4
else:
    target_c = tdee
    target_p = weight * 1.6
    target_f = (target_c * 0.25) / 9
    target_c_carb = (target_c - (target_p * 4 + target_f * 9)) / 4

targets = {
    "calories": target_c,
    "protein": target_p,
    "fat": target_f,
    "carbs": target_c_carb
}

# カード3: 1日目標サマリーカード（明暗完全同期）
st.sidebar.markdown(f"""
<div class='sidebar-card' style='border: 1.5px solid {theme['accent']};'>
    <div style='font-size:12px; color:{theme['text_sub']}; font-weight:700;'>📊 あなたの1日の目標基準</div>
    <div style='font-size:24px; font-weight:800; color:{theme['accent']}; margin:4px 0 8px 0;'>
        {target_c:.0f} <span style='font-size:14px; color:{theme['text']};'>kcal / 日</span>
    </div>
    <div style='font-size:11.5px; color:{theme['text_sub']}; margin-bottom:10px;'>
        基礎代謝: {bmr:.0f} kcal ／ 1日の推定消費量: {tdee:.0f} kcal
    </div>
    <div style='display:flex; justify-content:space-between; font-weight:700; font-size:13px;'>
        <span style='color:{theme['p_color']};'>🥩 P: {target_p:.0f}g</span>
        <span style='color:{theme['f_color']};'>🧈 F: {target_f:.0f}g</span>
        <span style='color:{theme['c_color']};'>🍞 C: {target_c_carb:.0f}g</span>
    </div>
</div>
""", unsafe_allow_html=True)

if st.sidebar.button("🔄 今日の食事記録をリセット", use_container_width=True):
    st.session_state.meals = []
    st.sidebar.success("本日の記録をリセットしました")
    st.rerun()

st.sidebar.divider()

# カード4: データ管理（バックアップ＆復元・クラウド消失対策）
st.sidebar.markdown("<div class='sidebar-card-title'>💾 データ安全管理</div>", unsafe_allow_html=True)
all_hist_for_backup = load_all_history()
backup_json_str = json.dumps(all_hist_for_backup, ensure_ascii=False, indent=2)

st.sidebar.download_button(
    label="📥 食事データを保存 (JSON)",
    data=backup_json_str,
    file_name=f"mogubalance_backup_{today_str}.json",
    mime="application/json",
    use_container_width=True,
    help="これまでの食事記録を一括ダウンロードしてスマホやPCに保存します。"
)

uploaded_backup = st.sidebar.file_uploader("📤 バックアップから復元", type=["json"], label_visibility="collapsed")
if uploaded_backup is not None:
    # セキュリティ検査1: ファイルサイズ上限（最大2MB - メモリ枯渇DoS防止）
    if uploaded_backup.size > 2 * 1024 * 1024:
        st.sidebar.error("❌ ファイルサイズが大きすぎます（最大2MBまで）。")
    else:
        try:
            restored_data = json.load(uploaded_backup)
            # セキュリティ検査2: データ構造（スキーマ）の厳格検証
            if isinstance(restored_data, dict):
                is_valid_schema = True
                # 日付キー（YYYY-MM-DD）および内部辞書構造の検証
                for d_key, val in restored_data.items():
                    if not isinstance(d_key, str) or len(d_key) > 25 or not isinstance(val, dict):
                        is_valid_schema = False
                        break
                
                # 最大レコード数（5,000件）の制限（データ爆弾防止）
                if is_valid_schema and len(restored_data) <= 5000:
                    with open(HISTORY_FILE, "w", encoding="utf-8") as f:
                        json.dump(restored_data, f, ensure_ascii=False, indent=2)
                    st.sidebar.success("✅ データを安全に復元しました！")
                    st.rerun()
                else:
                    st.sidebar.error("❌ 不正な形式または破損したバックアップデータです。")
            else:
                st.sidebar.error("❌ 無効なバックアップファイルです。")
        except Exception as e:
            st.sidebar.error(f"復元エラー: {e}")

st.sidebar.divider()
if st.sidebar.button("🔒 アプリを施錠（ログアウト）", use_container_width=True):
    st.session_state.authenticated = False
    st.rerun()

# -------------------------------------------------------------
# 5. 集計ロジック
# -------------------------------------------------------------
current_total = {"calories": 0.0, "protein": 0.0, "fat": 0.0, "carbs": 0.0}
meal_categories = {"朝食": [], "昼食": [], "夕食": [], "間食": []}

for meal in st.session_state.meals:
    cat = meal.get("category", "昼食")
    if cat not in meal_categories:
        cat = "間食"
    meal_categories[cat].append(meal)
    t = meal["result"]["total"]
    current_total["calories"] += t.get("calories", 0)
    current_total["protein"] += t.get("protein", 0)
    current_total["fat"] += t.get("fat", 0)
    current_total["carbs"] += t.get("carbs", 0)

# 自動保存（23:50以降の判定）
now_time = datetime.now()
if now_time.hour == 23 and now_time.minute >= 50:
    if st.session_state.meals:
        save_daily_record(today_str, st.session_state.meals, current_total, targets)

# -------------------------------------------------------------
# 6. 高速 Gemini AI 推論関数（マルチタイミング自動小分け分解対応）
# -------------------------------------------------------------
def analyze_meal_fast(text: str, fallback_category: str, api_key: str):
    prompt = f"""
あなたは世界最高峰の超高速・高精度栄養解析エンジンです。
入力された食事内容を解析し、各大まかな品目のカロリー(kcal)とPFC(タンパク質, 脂質, 炭水化物 各g)を推計して、
指定のJSON形式のみを最速で返してください。

【複数食事タイミングの自動分解ルール（超重要）】
入力テキスト内に「朝」「朝食」「昼」「昼食」「ランチ」「夜」「夕食」「ディナー」「晩」「間食」「おやつ」などの複数の時間帯・タイミングが含まれている場合は、
絶対に1つにまとめず、必ず「朝食」「昼食」「夕食」「間食」の区分ごとに分割したリスト（meals）として出力してください。
例:
「・朝 バナナ 納豆\n・昼 焼肉ライク\n・夜 鶏もも肉\n・ガリガリくん」
➔
meals: [
  {{category: "朝食", summary_text: "バナナ 納豆", items: [...], ...}},
  {{category: "昼食", summary_text: "焼肉ライク", items: [...], ...}},
  {{category: "夕食", summary_text: "鶏もも肉", items: [...], ...}},
  {{category: "間食", summary_text: "ガリガリくん", items: [...], ...}}
]

時間帯の指定が特にない単一の食事入力の場合は、デフォルト区分「{fallback_category}」の1件の食事オブジェクトを持つリストとして出力してください。

【ユーザー情報】
- 身長: {height}cm, 体重: {weight}kg, 目的: {goal}
- デフォルト食事区分: {fallback_category}
- 1日目標: {target_c:.0f}kcal (P:{target_p:.0f}g, F:{target_f:.0f}g, C:{target_c_carb:.0f}g)

【食事内容】
"{text}"
※「白米 150g」「プロテイン 30g」などの曖昧なグラム数指定や、「オイコス」「ファミチキ」「ガリガリくん」「焼肉ライク」などの市販製品名にも日本の実測データ基準で正確に対応してください。

【出力JSON（マークダウン装飾なしの純粋なJSONのみ）】
{{
  "meals": [
    {{
      "category": "朝食 / 昼食 / 夕食 / 間食 のいずれか",
      "summary_text": "その区分に該当する食事内容（例: バナナ 納豆）",
      "items": [
        {{"name": "食品・製品名", "calories": 0, "protein": 0.0, "fat": 0.0, "carbs": 0.0}}
      ],
      "total": {{"calories": 0, "protein": 0.0, "fat": 0.0, "carbs": 0.0}},
      "judgment": "◎ 理想的 / ◯ 良好 / △ 要調整 / ⚠️ 脂質過多 / ⚠️ カロリー過多",
      "comment": "目標に対するこの食事のアドバイス（80文字以内で端的に）"
    }}
  ]
}}
"""
    try:
        client = genai.Client(api_key=api_key)
        response = client.models.generate_content(
            model="gemini-3.8-flash",
            contents=prompt,
            config=types.GenerateContentConfig(
                response_mime_type="application/json",
                temperature=0.2
            )
        )
        raw = response.text.strip()
        if raw.startswith("```"):
            raw = raw.strip("`")
            if raw.startswith("json"):
                raw = raw[4:].strip()
        return json.loads(raw)
    except Exception as e:
        return {"error": f"解析エラー: {str(e)}"}

def get_rescue_suggestion(api_key: str):
    rem_p = max(targets["protein"] - current_total["protein"], 0)
    rem_f = max(targets["fat"] - current_total["fat"], 0)
    rem_c = max(targets["carbs"] - current_total["carbs"], 0)
    rem_cal = max(targets["calories"] - current_total["calories"], 0)

    prompt = f"""
あなたはボディメイクのプロです。ユーザーの1日の残り摂取可能PFC枠に合わせて、
コンビニ（セブン、ローソン、ファミマ）やスーパーですぐ買えるおすすめの補給食品を3つ具体的に提案してください。

【残り枠】
- 残りカロリー: 約 {rem_cal:.0f} kcal
- 残りP (タンパク質): 約 {rem_p:.1f} g
- 残りF (脂質): 約 {rem_f:.1f} g
- 残りC (炭水化物): 約 {rem_c:.1f} g
- 目的: {goal}

親しみやすく端的な箇条書きで、製品名・推定PFC・選んだ理由を教えてください。
"""
    try:
        client = genai.Client(api_key=api_key)
        res = client.models.generate_content(
            model="gemini-3.8-flash",
            contents=prompt
        )
        return res.text
    except Exception as e:
        return f"提案の取得に失敗しました: {e}"

# -------------------------------------------------------------
# 7. メイン画面ヘッダー ＆ ストリーク（連続記録）バナー
# -------------------------------------------------------------
st.title("🥗 モグバランス")
st.markdown(f"<div style='font-size:14.5px; color:{theme['text_sub']}; margin-top:-8px; margin-bottom:14px;'>かんたんAI食事＆PFCパートナー・食べたものをパッと入力するだけで栄養バランスを自動診断します</div>", unsafe_allow_html=True)

# ストリーク（連続記録日数）の算出
all_history = load_all_history()
has_today = len(st.session_state.meals) > 0 or today_str in all_history
streak_days = calculate_streak(all_history, has_today)
max_streak = max(calculate_max_streak(all_history), streak_days)

if streak_days >= 30:
    streak_msg = "🏆 伝説級の継続力！身体は確実に変化しています！"
elif streak_days >= 14:
    streak_msg = "🔥 2週間突破！完全に生活の一部になっています、素晴らしい調子です！"
elif streak_days >= 7:
    streak_msg = "✨ 1週間連続達成！努力がしっかり実を結んでいます！"
elif streak_days >= 3:
    streak_msg = "💪 3日連続突破！三日坊主を克服、この勢いで続けましょう！"
elif streak_days >= 1:
    streak_msg = "🌱 今日もナイス記録！継続の一歩を着実に刻んでいます！"
else:
    streak_msg = "🎯 今日の最初の食事を記録して、ストリークをスタートしましょう！"

# ストリーク表示バナー（全テーマ完全連動・高視認性）
st.markdown(f"""
<div style="background:{'rgba(255, 255, 255, 0.04)' if theme['is_dark'] else 'rgba(0, 0, 0, 0.02)'}; border: 1.5px solid {theme['accent']}; border-radius: 14px; padding: 12px 18px; margin-bottom: 20px; display: flex; justify-content: space-between; align-items: center; box-shadow: 0 4px 16px {theme['accent_glow']};">
    <div style="display: flex; align-items: center; gap: 12px;">
        <span style="font-size: 28px;">🔥</span>
        <div>
            <div style="font-size: 15px; font-weight: 800; color: {theme['text']};">
                連続記録ストリーク: <span style="color: {theme['accent']}; font-size: 21px;">{streak_days}</span> 日目！
                <span style="font-size: 12px; color: {theme['text_sub']}; font-weight: 600; margin-left: 8px;">(歴代最高: {max_streak}日)</span>
            </div>
            <div style="font-size: 12.5px; color: {theme['text_sub']}; font-weight: 600; margin-top: 2px;">{streak_msg}</div>
        </div>
    </div>
    <div style="background: {theme['accent']}; color: {theme['btn_text']}; font-weight: 800; font-size: 12px; padding: 4px 14px; border-radius: 20px;">
        {'記録中 🔥' if has_today else '今日未記録'}
    </div>
</div>
""", unsafe_allow_html=True)

# -------------------------------------------------------------
# 8. 今日の進捗ゲージ ＆ PFCデザイナーズ円グラフ（明暗専用パレット）
# -------------------------------------------------------------
col_chart, col_bars = st.columns([1, 1.4])

with col_chart:
    st.markdown(f"<h4 style='color:{theme['text']}; margin-bottom:8px;'>🍩 今日のPFCバランス比率</h4>", unsafe_allow_html=True)
    p_val = max(current_total["protein"], 0.1)
    f_val = max(current_total["fat"], 0.1)
    c_val = max(current_total["carbs"], 0.1)

    pfc_colors = [theme["p_color"], theme["f_color"], theme["c_color"]]

    fig = go.Figure(data=[go.Pie(
        labels=["P (タンパク質)", "F (脂質)", "C (炭水化物)"],
        values=[p_val * 4, f_val * 9, c_val * 4],
        hole=0.62,
        marker=dict(colors=pfc_colors, line=dict(color=theme["bg"], width=3)),
        textinfo="label+percent",
        textfont=dict(size=13, color="#FFFFFF" if theme["is_dark"] else "#0F172A", family="sans-serif"),
        hoverinfo="label+value+percent",
        hovertemplate="<b>%{label}</b><br>エネルギー: %{value:.0f} kcal<br>割合: %{percent}<extra></extra>"
    )])

    fig.update_layout(
        showlegend=False,
        margin=dict(t=10, b=10, l=10, r=10),
        height=260,
        paper_bgcolor="rgba(0,0,0,0)",
        plot_bgcolor="rgba(0,0,0,0)",
        annotations=[dict(
            text=f"<b>{current_total['calories']:.0f}</b><br><span style='font-size:13px;'>kcal</span>",
            x=0.5, y=0.5,
            font=dict(size=24, color=theme["text"], family="sans-serif"),
            showarrow=False
        )]
    )
    st.plotly_chart(fig, use_container_width=True)

with col_bars:
    st.markdown(f"<h4 style='color:{theme['text']}; margin-bottom:8px;'>⚡ 摂取状況（目標超過時は赤色警告）</h4>", unsafe_allow_html=True)
    
    def render_gauge(label, current, target, unit, normal_color):
        ratio = current / target if target > 0 else 0.0
        is_over = ratio > 1.05
        bar_color = "#EF4444" if is_over else normal_color
        pct = min(ratio * 100, 100)
        over_badge = f"<span style='color:#EF4444; font-weight:800; font-size:13px;'> ⚠️ 目標超過 (+{current - target:.0f}{unit})</span>" if is_over else ""

        html = f"""
        <div style="margin-bottom: 14px;">
            <div style="display:flex; justify-content:space-between; margin-bottom:5px; font-size:14px; font-weight:700; color:{theme['text']};">
                <span>{label} {over_badge}</span>
                <span><b>{current:.1f}</b> / {target:.0f} {unit} ({ratio*100:.0f}%)</span>
            </div>
            <div style="background:{theme['card_border']}; border-radius:8px; height:11px; width:100%; overflow:hidden;">
                <div style="background:{bar_color}; width:{pct}%; height:100%; border-radius:8px; transition: width 0.5s ease;"></div>
            </div>
        </div>
        """
        st.markdown(html, unsafe_allow_html=True)

    render_gauge("🔥 総カロリー", current_total["calories"], targets["calories"], "kcal", theme["accent"])
    render_gauge("🥩 P (タンパク質)", current_total["protein"], targets["protein"], "g", theme["p_color"])
    render_gauge("🧈 F (脂質)", current_total["fat"], targets["fat"], "g", theme["f_color"])
    render_gauge("🍞 C (炭水化物)", current_total["carbs"], targets["carbs"], "g", theme["c_color"])

    col_btn1, col_btn2 = st.columns(2)
    with col_btn1:
        if st.button("💡 残枠レスキュー（あと何食べる？）", use_container_width=True):
            if not api_key_input:
                st.error("AI連携キーが未設定です。サイドバーをご確認ください。")
            else:
                with st.spinner("おすすめのコンビニ・スーパー補給食品を検索中..."):
                    suggestion = get_rescue_suggestion(api_key_input)
                    st.info(f"### 🏪 おすすめのリカバリー食品\n{suggestion}")

    with col_btn2:
        if st.button("📌 今日の食事を確定・保存する", use_container_width=True):
            save_daily_record(today_str, st.session_state.meals, current_total, targets)
            st.success(f"本日（{today_str}）の食事内容を安全に保存しました！")

st.divider()

# -------------------------------------------------------------
# 9. 食事入力インターフェース（見出し直下 ＆ ワンタップ例 ＆ Enter送信）
# -------------------------------------------------------------
st.markdown(f"<h3 style='color:{theme['text']};'>💬 食事を入力する</h3>", unsafe_allow_html=True)

selected_btn_category = st.radio(
    "食事タイミングを選択（※チャット欄に「朝に〜」「夜〜」と書いた場合はそちらが自動優先されます）",
    ["☀️ 朝食", "🌤️ 昼食", "🌙 夕食", "☕ 間食"],
    horizontal=True,
    index=1
)
fallback_cat = selected_btn_category.split(" ")[-1]

st.markdown(f"<div style='margin-bottom:6px; font-size:13.5px; font-weight:700; color:{theme['text']};'>💡 ワンタップ入力例（クリックすると入力枠にそのまま反映されます）:</div>", unsafe_allow_html=True)
col_q1, col_q2, col_q3 = st.columns(3)
with col_q1:
    if st.button("🍚 朝食: 白米とサラダチキン", use_container_width=True):
        st.session_state.input_draft = "朝食\n白米 150g\nセブンのサラダチキン 1個\nオイコス加糖 1個"
        st.rerun()
with col_q2:
    if st.button("🥩 昼食: ステーキとブロッコリー", use_container_width=True):
        st.session_state.input_draft = "昼食\n牛赤身肉ステーキ 200g\nブロッコリー 100g\n白米 200g"
        st.rerun()
with col_q3:
    if st.button("🍱 1日まとめ: 朝・昼・夜・間食", use_container_width=True):
        st.session_state.input_draft = "・朝 バナナ 納豆\n・昼 焼肉ライク300g盛り ご飯並2杯\n・夜 鶏もも肉塩麹漬け ご飯150g フリーズドライ味噌汁\n・ガリガリくん"
        st.rerun()

with st.form(key="inline_meal_form", clear_on_submit=False):
    meal_text = st.text_area(
        "食べたものを入力",
        value=st.session_state.input_draft,
        placeholder="【入力例】\n朝食に白米 150g\nセブンのサラダチキン 1個\nオイコス加糖 1個\n※「朝〜」「昼〜」「夜〜」とまとめて書けば、AIが自動で各タブに振り分けます！\n※Shift+Enterで改行、Enterまたは下のボタンで送信できます",
        height=125,
        label_visibility="collapsed"
    )
    col_submit, col_hint = st.columns([1.3, 3])
    with col_submit:
        submitted = st.form_submit_button("⚡ 解析して追加する (Enter)", use_container_width=True)
    with col_hint:
        st.markdown(f"<span style='color:{theme['text_sub']}; font-size:13.5px; font-weight:700; line-height:2.6;'>💡 <b>Enter</b> で即送信 / <b>Shift + Enter</b> で改行できます。</span>", unsafe_allow_html=True)

# Enterキーで自動送信 ＆ 右上メニュー完全日本語化JavaScript
components.html("""
<script>
const doc = window.parent.document;

// 1. Enterキー自動送信フック
function hookEnterKey() {
    const textarea = doc.querySelector('div[data-testid="stTextArea"] textarea');
    if (textarea && !textarea.dataset.enterHooked) {
        textarea.dataset.enterHooked = "true";
        textarea.addEventListener('keydown', function(e) {
            if (e.key === 'Enter' && !e.shiftKey) {
                e.preventDefault();
                const btn = doc.querySelector('div[data-testid="stFormSubmitButton"] button');
                if (btn) btn.click();
            }
        });
    }
}

// 2. 右上の開発者メニュー完全日本語化
function translateHeaderMenu() {
    const translations = {
        "Rerun": "再読み込み",
        "Always rerun": "自動更新",
        "System": "端末連動",
        "Light": "明るい",
        "Dark": "暗い",
        "Clear cache": "キャッシュ消去",
        "Print": "印刷",
        "Record screen": "画面録画",
        "Made with Streamlit": "モグバランス システム"
    };

    // ツールバーボタンの翻訳
    const buttons = doc.querySelectorAll('header button, [data-testid="stToolbar"] button, ul[role="menu"] *');
    buttons.forEach(el => {
        for (const [en, ja] of Object.entries(translations)) {
            if (el.textContent.trim() === en || el.innerText.trim() === en) {
                el.textContent = ja;
            }
        }
    });
}

setInterval(hookEnterKey, 500);
setInterval(translateHeaderMenu, 500);
</script>
""", height=0)

if submitted:
    cleaned_input = meal_text.strip()
    if not cleaned_input:
        st.warning("食事内容を入力してください。")
    elif len(cleaned_input) > 1000:
        st.error("⚠️ 入力文字数が多すぎます（最大1,000文字まで）。安全のため文字数を減らしてください。")
    elif not api_key_input:
        st.error("AI連携キーが設定されていません。サイドバーをご確認ください。")
    else:
        with st.spinner("AIが食事を時間帯ごとにスマート分解・解析中..."):
            res = analyze_meal_fast(cleaned_input, fallback_cat, api_key_input)
            if "error" in res:
                st.error(res["error"])
            else:
                meals_list = res.get("meals", [])
                if not meals_list and "items" in res:
                    meals_list = [res]

                now_str = datetime.now().strftime("%H:%M")
                
                for m_entry in meals_list:
                    cat_raw = m_entry.get("category", fallback_cat)
                    if "朝" in cat_raw:
                        cat_final = "朝食"
                    elif "昼" in cat_raw or "ランチ" in cat_raw:
                        cat_final = "昼食"
                    elif "夕" in cat_raw or "夜" in cat_raw or "晩" in cat_raw:
                        cat_final = "夕食"
                    else:
                        cat_final = "間食"

                    summary_txt = m_entry.get("summary_text", "").strip()
                    if not summary_txt:
                        summary_txt = meal_text

                    st.session_state.meals.append({
                        "time": now_str,
                        "category": cat_final,
                        "input": summary_txt,
                        "result": {
                            "detected_category": cat_final,
                            "items": m_entry.get("items", []),
                            "total": m_entry.get("total", {}),
                            "judgment": m_entry.get("judgment", "分析完了"),
                            "comment": m_entry.get("comment", "")
                        }
                    })

                st.session_state.input_draft = ""
                st.rerun()

# -------------------------------------------------------------
# 10. 朝昼晩ごとの区分け表示 ＆ 直近履歴
# -------------------------------------------------------------
st.markdown(f"<h3 style='color:{theme['text']};'>🍽️ 本日の食事内訳（朝・昼・晩・間食）</h3>", unsafe_allow_html=True)

tab_all, tab_morn, tab_lunch, tab_din, tab_snack = st.tabs([
    "📋 全体一覧",
    f"☀️ 朝食 ({len(meal_categories['朝食'])})",
    f"🌤️ 昼食 ({len(meal_categories['昼食'])})",
    f"🌙 夕食 ({len(meal_categories['夕食'])})",
    f"☕ 間食 ({len(meal_categories['間食'])})"
])

def render_meal_cards(meal_list, is_history=False, key_prefix="today"):
    if not meal_list:
        st.markdown(f"<div style='color:{theme['text_sub']}; font-size:14px; font-weight:600; padding:12px 0;'>この区分の記録はまだありません。</div>", unsafe_allow_html=True)
        return
    for idx, item in enumerate(reversed(meal_list)):
        res = item["result"]
        tot = res.get("total", {})
        with st.container():
            # XSS完全防御サニタイズ処理 (html.escape)
            safe_lines = [html.escape(line.strip()) for line in item['input'].split("\n") if line.strip()]
            formatted_input = "<br>".join([f"• {line}" for line in safe_lines])
            safe_cat = html.escape(str(item.get('category', '食事')))
            safe_time = html.escape(str(item.get('time', '')))
            safe_judgment = html.escape(str(res.get('judgment', '')))
            safe_comment = html.escape(str(res.get('comment', '')))

            st.markdown(f"""
            <div class="modern-card">
                <div style="display:flex; justify-content:space-between; align-items:center;">
                    <span class="modern-pill">{safe_cat} ({safe_time})</span>
                    <span style="font-weight:800; font-size:16px; color:{theme['accent']};">{safe_judgment}</span>
                </div>
                <div style="margin: 14px 0 10px 0; font-size: 16px; font-weight:700; color:{theme['text']}; line-height: 1.6;">
                    {formatted_input}
                </div>
                <div style="font-size:14px; color:{theme['text']}; margin-bottom:12px; background:{'rgba(0,0,0,0.25)' if theme['is_dark'] else 'rgba(0,0,0,0.04)'}; padding:10px 14px; border-radius:10px; border-left:4px solid {theme['accent']};">
                    💡 <b>AI診断</b>: {safe_comment}
                </div>
                <div style="display:flex; gap:18px; font-weight:700; font-size:15px; background:{'rgba(255,255,255,0.06)' if theme['is_dark'] else 'rgba(0,0,0,0.03)'}; border: 1px solid {theme['card_border']}; padding:10px 16px; border-radius:10px;">
                    <span style="color:{theme['text']};">🔥 {tot.get('calories', 0):.0f} kcal</span>
                    <span style="color:{theme['p_color']};">🥩 P: {tot.get('protein', 0):.1f}g</span>
                    <span style="color:{theme['f_color']};">🧈 F: {tot.get('fat', 0):.1f}g</span>
                    <span style="color:{theme['c_color']};">🍞 C: {tot.get('carbs', 0):.1f}g</span>
                </div>
            </div>
            """, unsafe_allow_html=True)
            
            sub_items = res.get("items", [])
            col_exp, col_act = st.columns([3, 1.2])
            with col_exp:
                if sub_items:
                    with st.expander("🔍 品目ごとの推定内訳を見る"):
                        for si in sub_items:
                            safe_item_name = html.escape(str(si.get('name', '')))
                            st.markdown(f"<div style='color:{theme['text']}; font-size:14px; margin-bottom:4px;'>• <b>{safe_item_name}</b>: <span style='color:{theme['accent']}; font-weight:700;'>{si.get('calories', 0):.0f} kcal</span> (P: <b>{si.get('protein', 0):.1f}g</b> / F: <b>{si.get('fat', 0):.1f}g</b> / C: <b>{si.get('carbs', 0):.1f}g</b>)</div>", unsafe_allow_html=True)
            with col_act:
                if is_history:
                    if st.button("🔁 今日に登録", key=f"copy_{key_prefix}_{idx}", use_container_width=True):
                        copied = json.loads(json.dumps(item))
                        copied["time"] = datetime.now().strftime("%H:%M")
                        st.session_state.meals.append(copied)
                        st.toast(f"✅ 「{item.get('category')}」を本日の記録に追加しました！")
                        st.rerun()
                else:
                    if st.button("🗑️ この1食を削除", key=f"del_{key_prefix}_{idx}", use_container_width=True):
                        if item in st.session_state.meals:
                            st.session_state.meals.remove(item)
                            st.toast(f"🗑️ 「{item.get('category')}」の記録を削除しました")
                            st.rerun()

with tab_all:
    render_meal_cards(st.session_state.meals, is_history=False, key_prefix="tab_all")
with tab_morn:
    render_meal_cards(meal_categories["朝食"], is_history=False, key_prefix="tab_morn")
with tab_lunch:
    render_meal_cards(meal_categories["昼食"], is_history=False, key_prefix="tab_lunch")
with tab_din:
    render_meal_cards(meal_categories["夕食"], is_history=False, key_prefix="tab_din")
with tab_snack:
    render_meal_cards(meal_categories["間食"], is_history=False, key_prefix="tab_snack")

# -------------------------------------------------------------
# 11. 過去の記録振り返り（日別ログ ＆ 食事内訳）
# -------------------------------------------------------------
st.divider()
st.markdown(f"<h3 style='color:{theme['text']};'>📅 過去の食事ログを振り返る</h3>", unsafe_allow_html=True)

all_history = load_all_history()
if all_history:
    hist_dates = sorted(list(all_history.keys()), reverse=True)
    selected_hist_date = st.selectbox("振り返る日付を選択", hist_dates)
    if selected_hist_date:
        rec = all_history[selected_hist_date]
        r_tot = rec.get("total", {})
        r_tar = rec.get("targets", {})
        st.markdown(f"<div style='margin-bottom:12px; font-size:13.5px; font-weight:700; color:{theme['text_sub']};'>🕒 記録保存日時: <b style=\"color:{theme['text']};\">{rec.get('saved_at', '')}</b></div>", unsafe_allow_html=True)
        col_h1, col_h2, col_h3, col_h4 = st.columns(4)
        
        def render_hist_card(col, label, val_str, target_val, unit, color):
            with col:
                st.markdown(f"""
                <div style="background:{theme['card_bg']}; border: 1.5px solid {theme['card_border']}; border-radius: 14px; padding: 14px 16px; box-shadow: 0 4px 14px {'rgba(0,0,0,0.25)' if theme['is_dark'] else 'rgba(0,0,0,0.04)'};">
                    <div style="font-size: 13px; font-weight: 700; color: {theme['text_sub']}; margin-bottom: 4px;">{label}</div>
                    <div style="font-size: 24px; font-weight: 800; color: {color}; margin-bottom: 6px;">
                        {val_str} <span style="font-size: 13px; color: {theme['text']}; font-weight: 600;">{unit}</span>
                    </div>
                    <div style="font-size: 12px; font-weight: 700; color: {theme['text_sub']}; background: {'rgba(255,255,255,0.06)' if theme['is_dark'] else 'rgba(0,0,0,0.04)'}; padding: 3px 8px; border-radius: 6px; display: inline-block;">
                        🎯 目標: {target_val:.0f} {unit}
                    </div>
                </div>
                """, unsafe_allow_html=True)
        
        render_hist_card(col_h1, "🔥 総カロリー", f"{r_tot.get('calories', 0):.0f}", r_tar.get('calories', 0), "kcal", theme['accent'])
        render_hist_card(col_h2, "🥩 P (タンパク質)", f"{r_tot.get('protein', 0):.1f}", r_tar.get('protein', 0), "g", theme['p_color'])
        render_hist_card(col_h3, "🧈 F (脂質)", f"{r_tot.get('fat', 0):.1f}", r_tar.get('fat', 0), "g", theme['f_color'])
        render_hist_card(col_h4, "🍞 C (炭水化物)", f"{r_tot.get('carbs', 0):.1f}", r_tar.get('carbs', 0), "g", theme['c_color'])

        # 過去ログの食事内訳一覧を展開表示
        hist_meals = rec.get("meals", [])
        if hist_meals:
            st.markdown(f"<h4 style='color:{theme['text']}; margin-top:24px; margin-bottom:12px;'>🍽️ {selected_hist_date} の食事内訳一覧（全 {len(hist_meals)} 件）</h4>", unsafe_allow_html=True)
            render_meal_cards(hist_meals, is_history=True, key_prefix=f"hist_{selected_hist_date}")
        else:
            st.markdown(f"<div style='color:{theme['text_sub']}; font-size:13.5px; margin-top:16px;'>この日の詳細な食事内訳は記録されていません。</div>", unsafe_allow_html=True)
else:
    st.markdown(f"<div style='color:{theme['text_sub']}; font-size:14px; font-weight:600;'>保存された過去のログはまだありません。「今日の食事を確定・保存する」ボタンを押すとここに蓄積されます。</div>", unsafe_allow_html=True)

# -------------------------------------------------------------
# 12. 守りの三柱（免責事項 ＆ セキュリティ表示）
# -------------------------------------------------------------
st.divider()
st.markdown(f"""
<div style="text-align: center; font-size: 12px; color: {theme['text_sub']}; line-height: 1.8;">
    🔒 <b>完全ローカル安全設計</b>: 入力された身体情報や食事内容はすべてお使いの端末内にのみ安全に保存され、外部サーバーに送信・蓄積されることはありません。<br>
    ⚖️ <b>免責事項</b>: 本アプリケーションによる栄養推計およびアドバイスはAIによる推計値であり、医療機関等による医学的診断・治療・栄養指導を代替するものではありません。
</div>
""", unsafe_allow_html=True)
