import streamlit as st
import json
import re
import pandas as pd
from urllib.parse import urlparse
import difflib

st.set_page_config(layout="wide")
st.title("HAR vs LoadRunner Validation")

########################################
# COLOR
########################################

def color_status(val):

    if val == "Matched":
        return "color: green; font-weight: bold"

    if val in ["Missing in LR", "Extra in LR"]:
        return "color: red; font-weight: bold"

    if val in ["Body Mismatch"]:
        return "color: orange; font-weight: bold"

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
# LR EXTRACTION (SAFE FIX)
########################################

def extract_lr_urls(script):

    urls = []

    pattern = r'URL=([^",\s]+)'
    matches = re.findall(pattern, script)

    for url in matches:

        norm = normalize_url(url)

        if norm:
            urls.append({
                "url": url,
                "norm": norm,
                "method": "GET",
                "body": ""
            })

    # 🔧 Minimal body extraction (safe, won't break anything)
    blocks = re.findall(r'web_custom_request\((.*?)\);', script, re.DOTALL)

    for block in blocks:

        block = block.replace('\\"', '"').replace('“', '"').replace('”', '"')

        url_match = re.search(r'URL="([^"]+)"', block)
        if not url_match:
            continue

        url = url_match.group(1)

        body_match = re.search(r'Body=\{(.*?)\}', block, re.DOTALL)

        body = ""
        if body_match:
            body = "{" + body_match.group(1) + "}"

        # Update matching URL entry
        for u in urls:
            if u["url"] == url:
                u["method"] = "POST"
                u["body"] = body

    return urls

########################################
# URL MATCH (KEEP OLD LOGIC)
########################################

def urls_match(har_url, lr_url):

    har_url = normalize_url(har_url)
    lr_url = normalize_url(lr_url)

    if not har_url or not lr_url:
        return False

    lr_url_escaped = re.escape(lr_url)

    pattern = re.sub(r"\\\{.*?\\\}", r"[^/]+", lr_url_escaped)

    pattern = "^" + pattern + ".*"

    return re.search(pattern, har_url) is not None

########################################
# BODY MATCH (SAFE)
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
# COMPARE (FIX DUPLICATE ISSUE)
########################################

def compare_urls(har_list, lr_list):

    rows = []
    used_lr = set()

    for har in har_list:

        status = "Missing in LR"
        lr_match = ""
        lr_body = ""

        for i, lr in enumerate(lr_list):

            if i in used_lr:
                continue

            if urls_match(har["url"], lr["url"]):

                used_lr.add(i)

                lr_match = lr["url"]
                lr_body = lr["body"]

                if not body_match(har["body"], lr_body):
                    status = "Body Mismatch"
                else:
                    status = "Matched"

                break

        rows.append({
            "HAR URL": har["url"],
            "LR URL": lr_match,
            "Status": status,
            "HAR Body": har["body"],
            "LR Body": lr_body
        })

    # Extra LR
    for i, lr in enumerate(lr_list):

        if i not in used_lr:

            rows.append({
                "HAR URL": "",
                "LR URL": lr["url"],
                "Status": "Extra in LR",
                "HAR Body": "",
                "LR Body": lr["body"]
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

    match_pct = (matched / total * 100) if total else 0

    col1, col2, col3, col4 = st.columns(4)

    col1.metric("Total", total)
    col2.metric("Matched", matched)
    col3.metric("Missing", missing)
    col4.metric("Match %", f"{match_pct:.2f}%")

########################################
# DIFF
########################################

def show_diff(har_body, lr_body):

    st.subheader("Body Difference")

    diff = difflib.ndiff(
        har_body.splitlines(),
        lr_body.splitlines()
    )

    st.code("\n".join(diff))

########################################
# UI
########################################

har_file = st.file_uploader("Upload HAR File")
lr_file = st.file_uploader("Upload LR Script")

if har_file and lr_file:

    har_data = json.load(har_file)
    lr_script = lr_file.read().decode()

    har_requests = extract_har_requests(har_data)
    lr_urls = extract_lr_urls(lr_script)

    full = compare_urls(har_requests, lr_urls)

    st.write(full.style.map(color_status, subset=["Status"]))

    st.subheader("Summary")
    show_summary(full)

    idx = st.number_input("Select row", 0, len(full)-1, 0)

    row = full.iloc[idx]

    show_diff(row["HAR Body"], row["LR Body"])
