import streamlit as st
import json
import re
import pandas as pd
import matplotlib.pyplot as plt
from urllib.parse import urlparse
import difflib

st.set_page_config(layout="wide")
st.title("HAR vs LoadRunner Validation ")

########################################
# COLOR
########################################

def color_status(val):

    if val == "Matched":
        return "background-color: #d4edda; color: green; font-weight: bold"

    if val in ["Missing in LR", "Extra in LR"]:
        return "background-color: #f8d7da; color: red; font-weight: bold"

    if val in ["Method Mismatch", "Body Mismatch"]:
        return "background-color: #fff3cd; color: orange; font-weight: bold"

    return ""

########################################
# NORMALIZE URL
########################################

def normalize_url(url):

    if not url:
        return None

    if "digitalbundles" in url:
        return None

    if url.startswith("chrome-extension"):
        return None

    parsed = urlparse(url)

    path = parsed.path
    query = parsed.query

    return path + "?" + query if query else path

########################################
# HAR EXTRACTION
########################################

def extract_har_requests(har):

    requests = []

    for entry in har["log"]["entries"]:

        req = entry["request"]

        url = req["url"]
        method = req.get("method", "GET")

        body = ""
        if "postData" in req and "text" in req["postData"]:
            body = req["postData"]["text"]

        norm = normalize_url(url)
        if not norm:
            continue

        requests.append({
            "url": url,
            "norm": norm,
            "method": method,
            "body": body
        })

    return requests

########################################
# LR EXTRACTION
########################################

def extract_lr_urls(script):

    urls = []

    pattern = r'web_(url|custom_request)[\s\S]*?URL=([^",\s]+)'

    matches = re.findall(pattern, script)

    for m in matches:

        method = "GET" if m[0] == "url" else "POST"
        url = m[1]

        norm = normalize_url(url)

        if norm:
            urls.append({
                "url": url,
                "norm": norm,
                "method": method,
                "body": ""  # extendable
            })

    return urls

########################################
# URL MATCH
########################################

def urls_match(har_url, lr_url):

    har_url = normalize_url(har_url)
    lr_url = normalize_url(lr_url)

    if not har_url or not lr_url:
        return False

    lr_url_escaped = re.escape(lr_url)
    pattern = re.sub(r"\\\{.*?\\\}", r"[^/]+", lr_url_escaped)

    return re.search("^" + pattern, har_url) is not None

########################################
# BODY MATCH
########################################

def body_match(har_body, lr_body):

    if not har_body and not lr_body:
        return True

    if har_body and lr_body:
        return har_body.strip() == lr_body.strip()

    return False

########################################
# COMPARE (NO DUPLICATE)
########################################

def compare_urls(har_list, lr_list):

    rows = []
    used_lr = set()

    for har in har_list:

        status = "Missing in LR"
        lr_match = ""
        lr_method = ""
        har_body = har["body"]
        lr_body = ""

        for i, lr in enumerate(lr_list):

            if i in used_lr:
                continue

            if urls_match(har["url"], lr["url"]):

                used_lr.add(i)

                lr_match = lr["url"]
                lr_method = lr["method"]
                lr_body = lr["body"]

                if har["method"] != lr["method"]:
                    status = "Method Mismatch"
                elif not body_match(har_body, lr_body):
                    status = "Body Mismatch"
                else:
                    status = "Matched"

                break

        rows.append({
            "HAR URL": har["url"],
            "LR URL": lr_match,
            "HAR Method": har["method"],
            "LR Method": lr_method,
            "HAR Body": har_body,
            "LR Body": lr_body,
            "Status": status
        })

    for i, lr in enumerate(lr_list):

        if i not in used_lr:

            rows.append({
                "HAR URL": "",
                "LR URL": lr["url"],
                "HAR Method": "",
                "LR Method": lr["method"],
                "HAR Body": "",
                "LR Body": lr["body"],
                "Status": "Extra in LR"
            })

    return pd.DataFrame(rows)

########################################
# SUMMARY
########################################

def show_summary(df):

    total = len(df)
    matched = len(df[df["Status"] == "Matched"])
    missing = len(df[df["Status"] == "Missing in LR"])
    extra = len(df[df["Status"] == "Extra in LR"])
    mismatch = len(df[df["Status"].isin(["Method Mismatch", "Body Mismatch"])])

    match_pct = (matched / total * 100) if total else 0

    col1, col2, col3, col4, col5 = st.columns(5)

    col1.metric("Total", total)
    col2.metric("Matched", matched)
    col3.metric("Missing", missing)
    col4.metric("Extra", extra)
    col5.metric("Match %", f"{match_pct:.2f}%")

########################################
# DIFF VIEWER
########################################

def show_diff(har_body, lr_body):

    st.subheader("🔍 Body Difference Viewer")

    if not har_body and not lr_body:
        st.info("No body present in both HAR and LR")
        return

    har_lines = har_body.splitlines()
    lr_lines = lr_body.splitlines()

    diff = difflib.ndiff(har_lines, lr_lines)

    diff_text = []
    for line in diff:
        if line.startswith("-"):
            diff_text.append(f"❌ {line}")
        elif line.startswith("+"):
            diff_text.append(f"✅ {line}")
        else:
            diff_text.append(line)

    st.code("\n".join(diff_text))

########################################
# UI
########################################

har_file = st.file_uploader("Upload HAR File")
lr_file = st.file_uploader("Upload LR Script (.txt)")

if har_file and lr_file:

    har_data = json.load(har_file)
    lr_script = lr_file.read().decode()

    har_requests = extract_har_requests(har_data)
    lr_urls = extract_lr_urls(lr_script)

    st.subheader("Full Comparison")

    full = compare_urls(har_requests, lr_urls)

    st.write(full.style.map(color_status, subset=["Status"]))

    st.subheader("Summary")
    show_summary(full)

    st.subheader("Select Row for Deep Analysis")

    selected_index = st.number_input(
        "Enter row number",
        min_value=0,
        max_value=len(full)-1,
        step=1
    )

    row = full.iloc[selected_index]

    show_diff(row["HAR Body"], row["LR Body"])
