import io
import re
import time
from collections import defaultdict
from email.header import Header
from email.utils import formataddr, parseaddr

import streamlit as st
import pandas as pd
import smtplib
from email.mime.text import MIMEText
from email.mime.multipart import MIMEMultipart

st.set_page_config(page_title="Team Niwrutti")

SMTP_SERVER = "smtp.gmail.com"
SMTP_PORT = 587
USE_TLS = True


# ---------------- Helpers ----------------

def clean_value(val):
    if isinstance(val, str):
        return val.replace("\xa0", " ").replace("\u200b", "").strip()
    return val


def clean_email_address(raw_email):
    if not raw_email:
        return None

    raw_email = clean_value(raw_email)
    _, addr = parseaddr(raw_email)

    if not addr:
        addr = re.sub(r"[<>\s\"']", "", raw_email)

    if "@" not in addr:
        return None

    try:
        local, domain = addr.rsplit("@", 1)
    except ValueError:
        return None

    try:
        domain_ascii = domain.encode("idna").decode("ascii")
    except Exception:
        domain_ascii = domain

    return f"{local}@{domain_ascii}"


def safe_format(template: str, mapping: dict):
    return template.format_map(defaultdict(str, mapping))


def clean_display_name(name: str):
    if not name:
        return ""
    return name.replace("\xa0", " ").replace("\u200b", "").strip()


def clean_invisible_unicode(s):
    if not isinstance(s, str):
        return s
    return s.replace('\xa0', '').replace('\u200b', '').strip()


# -------- NEW PREFIX LOGIC --------

def extract_first_name(full_name: str):

    if not full_name:
        return ""

    prefixes = {
        "dr", "dr.",
        "mr", "mr.",
        "mrs", "mrs.",
        "ms", "ms.",
        "prof", "prof."
    }

    parts = full_name.strip().split()

    if not parts:
        return ""

    first_word = parts[0].lower()

    if first_word in prefixes and len(parts) > 1:
        return f"{parts[0]} {parts[1]}"

    return parts[0]


# ---------------- UI ----------------

st.title("Team Niwrutti")
st.subheader("Upload recipient list")

uploaded_file = st.file_uploader("Upload CSV file", type=["csv"])

sample_df = pd.DataFrame({
    "email": ["john@example.com", "jane@example.com"],
    "name": ["Dr John Smith", "Jane Smith"],
    "company": ["Acme", "Globex"]
})

buf = io.StringIO()
sample_df.to_csv(buf, index=False)

st.download_button(
    "Download sample CSV",
    buf.getvalue(),
    "sample_recipients.csv"
)

df = None

if uploaded_file:
    df = pd.read_csv(uploaded_file)
    df = df.map(clean_value)
    st.success("CSV uploaded")
    st.dataframe(df)


# ---------------- Session State ----------------

if "sending" not in st.session_state:
    st.session_state.sending = False

if "stop_sending" not in st.session_state:
    st.session_state.stop_sending = False

if "sent_count" not in st.session_state:
    st.session_state.sent_count = 0


# ---------------- Buttons ----------------

col1, col2 = st.columns(2)

with col1:
    send_clicked = st.button("Send Emails")

with col2:
    stop_clicked = st.button("Stop Sending")

if stop_clicked:
    st.session_state.stop_sending = True


# ---------------- Email Config ----------------

st.subheader("Email configuration")

from_email = clean_invisible_unicode(st.text_input("Your Gmail address"))
app_password = clean_invisible_unicode(st.text_input("App password", type="password"))
from_name = st.text_input("Your name")

cc_raw = clean_invisible_unicode(st.text_input("CC email (optional)"))
cc_email = clean_email_address(cc_raw) if cc_raw else None


# ---------------- Compose ----------------

st.subheader("Compose message")

subject_tpl_1 = st.text_input("Subject Line 1")
subject_tpl_2 = st.text_input("Subject Line 2")

body_tpl_1 = st.text_area("Email Body 1", height=300)
body_tpl_2 = st.text_area("Email Body 2", height=300)


progress = st.progress(0)
sent_counter = st.empty()


# ---------------- SEND EMAILS ----------------

if send_clicked:

    if st.session_state.sending:
        st.warning("Emails already sending")
        st.stop()

    st.session_state.sending = True
    st.session_state.stop_sending = False
    st.session_state.sent_count = 0

    total = len(df)
    sent = 0

    skipped_rows = []
    failed_rows = []

    # -------- OPEN SMTP --------

    try:

        if USE_TLS:
            server = smtplib.SMTP(SMTP_SERVER, SMTP_PORT)
            server.starttls()
        else:
            server = smtplib.SMTP_SSL(SMTP_SERVER, SMTP_PORT)

        server.login(from_email, app_password)

    except Exception as e:
        st.error(f"SMTP connection failed: {e}")
        st.stop()

    # -------- LOOP --------

    for idx, row in df.iterrows():

        if st.session_state.stop_sending:
            st.warning("Stopped by user")
            break

        rowd = row.to_dict()

        recip_addr = clean_email_address(rowd.get("email", ""))

        if not recip_addr:
            skipped_rows.append(rowd)
            continue

        full_name = rowd.get("name", "")
        first_name = extract_first_name(full_name)

        subject_map = dict(rowd)
        body_map = dict(rowd)

        body_map["name"] = first_name

        if sent % 2 == 0:
            subj = safe_format(subject_tpl_1, subject_map)
            body = safe_format(body_tpl_1, body_map)
        else:
            subj = safe_format(subject_tpl_2, subject_map)
            body = safe_format(body_tpl_2, body_map)

        html_body = f"""
        <html>
        <body style="font-family:'Times New Roman';">
        <pre style="white-space:pre-wrap;">{body}</pre>
        </body>
        </html>
        """

        msg = MIMEMultipart()

        msg["From"] = formataddr(
            (str(Header(clean_display_name(from_name), "utf-8")), from_email)
        )

        msg["To"] = formataddr(
            (str(Header(clean_display_name(full_name), "utf-8")), recip_addr)
        )

        if cc_email:
            msg["Cc"] = cc_email

        msg["Subject"] = str(Header(subj, "utf-8"))

        msg.attach(MIMEText(html_body, "html", "utf-8"))

        try:

            server.send_message(msg)

            sent += 1
            st.session_state.sent_count += 1

            sent_counter.metric("Emails sent", st.session_state.sent_count)

            st.success(f"Sent to {recip_addr}")

        except Exception as e:

            st.error(f"Failed to send to {recip_addr}: {e}")
            failed_rows.append(rowd)

        progress.progress((idx + 1) / total)

        # -------- Cooling --------

        if st.session_state.sent_count % 5 == 0:

            cooling = 120
            start = time.time()

            while True:

                remaining = int(cooling - (time.time() - start))

                if remaining <= 0:
                    break

                mins, secs = divmod(remaining, 60)

                st.info(f"Cooling period {mins:02d}:{secs:02d}")

                time.sleep(1)

        # -------- Delay --------

        wait = 22
        start = time.time()

        while True:

            remaining = int(wait - (time.time() - start))

            if remaining <= 0:
                break

            st.info(f"Waiting {remaining}s before next email")

            time.sleep(1)

    # -------- CLOSE SMTP --------

    try:
        server.quit()
    except:
        pass

    st.success(
        f"Finished. Sent {sent}, skipped {len(skipped_rows)}, failed {len(failed_rows)}"
    )

    st.session_state.sending = False
