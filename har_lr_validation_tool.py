import streamlit as st
import json
import re
import pandas as pd
from urllib.parse import urlparse, parse_qs
import difflib

st.set_page_config(layout="wide")
st.title("HAR vs LoadRunner Validation")

########################################
# COLOR
########################################

def color_status(val):

    if val == "Matched":
        return "background-color: #d4edda; color: green; font-weight: bold"

    if val in ["Missing in LR", "Extra in LR"]:
        return "background-color: #f8d7da; color: red; font-weight: bold"

    if val == "Query Mismatch":
        return "background-color: #cfe2ff; color: blue; font-weight: bold"

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
    return parsed.path + "?" + parsed.query if parsed.query else parsed.path

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
            "method": method,
            "body": body
        })

    return requests

########################################
# LR EXTRACTION (ROBUST)
########################################

def extract_lr_urls(script):

    urls = []

    pattern = r'web_(url|custom_request)\s*\((.*?)\);'
    matches = re.findall(pattern, script, re.DOTALL)

    for req_type, content in matches:

        # URL
        url_match = re.search(r'URL="([^"]+)"', content)
        if not url_match:
            continue

        url = url_match.group(1)

        # METHOD
        method_match = re.search(r'Method=([A-Z]+)', content)
        method = method_match.group(1) if method_match else ("GET" if req_type == "url" else "POST")

        # BODY
        body = ""

        # Body="..."
        m1 = re.search(r'Body="(.*?)"', content, re.DOTALL)
        if m1:
            body = m1.group(1)

        # RequestBody="..."
        m2 = re.search(r'RequestBody="(.*?)"', content, re.DOTALL)
        if m2:
            body = m2.group(1)

        # ITEMDATA
        m3 = re.search(r'ITEMDATA,(.*?),"LAST"', content, re.DOTALL)
        if m3:
            raw = m3.group(1)
            values = re.findall(r'"([^"]*)"', raw)
            body = "&".join(values)

        norm = normalize_url(url)

        if norm:
            urls.append({
                "url": url,
                "method": method,
                "body": body
            })

    return urls

########################################
# URL COMPARISON (STRICT)
########################################

def compare_url_parts(har_url, lr_url):

    har = urlparse(har_url)
    lr = urlparse(lr_url)

    path_match = har.path == lr.path

    har_q = parse_qs(har.query)
    lr_q = parse_qs(lr.query)

    query_match = har_q == lr_q

    return path_match, query_match

########################################
# BODY MATCH
########################################

def body_match(har_body, lr_body):

    if not har_body and not lr_body:
        return True

    if not har_body or not lr_body:
        return False

    har = har_body.replace(" ", "").lower()
    lr = lr_body.replace(" ", "").lower()

    return har == lr

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
        lr_body = ""

        for i, lr in enumerate(lr_list):

            if i in used_lr:
                continue

            path_match, query_match = compare_url_parts(har["url"], lr["url"])

            if not path_match:
                continue

            used_lr.add(i)

            lr_match = lr["url"]
            lr_method = lr["method"]
            lr_body = lr["body"]

            if not query_match:
                status = "Query Mismatch"
            elif har["method"] != lr["method"]:
                status = "Method Mismatch"
            elif not body_match(har["body"], lr_body):
                status = "Body Mismatch"
            else:
                status = "Matched"

            break

        rows.append({
            "HAR URL": har["url"],
            "LR URL": lr_match,
            "HAR Method": har["method"],
            "LR Method": lr_method,
            "HAR Body": har["body"],
            "LR Body": lr_body,
            "Status": status
        })

    # Extra LR
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
    mismatch = len(df[df["Status"].isin(["Method Mismatch", "Body Mismatch", "Query Mismatch"])])

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

    formatted = []
    for line in diff:
        if line.startswith("-"):
            formatted.append(f"❌ {line}")
        elif line.startswith("+"):
            formatted.append(f"✅ {line}")
        else:
            formatted.append(line)

    st.code("\n".join(formatted))

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

    st.subheader("Deep Analysis")

    selected_index = st.number_input(
        "Select row number",
        min_value=0,
        max_value=len(full)-1,
        step=1
    )

    row = full.iloc[selected_index]

    show_diff(row["HAR Body"], row["LR Body"])
