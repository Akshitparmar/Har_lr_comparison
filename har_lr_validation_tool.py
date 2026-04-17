
import streamlit as st
import json
import re
import pandas as pd
import matplotlib.pyplot as plt
from datetime import datetime
from urllib.parse import urlparse

st.title("HAR vs LoadRunner Validation ")

########################################
# STATUS COLOR
########################################

def color_status(val):

    if val == "Matched":
        return "color: green; font-weight: bold"

    if val in ["Missing in LR", "Extra in LR"]:
        return "color: red; font-weight: bold"

    return ""

########################################
# URL NORMALIZATION
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

    if query:
        return path + "?" + query

    return path

########################################
# HAR REQUEST EXTRACTION
########################################

def extract_har_requests(har):

    requests = []

    for entry in har["log"]["entries"]:

        url = entry["request"]["url"]

        norm = normalize_url(url)

        if not norm:
            continue

        start = entry["startedDateTime"]

        start_time = datetime.fromisoformat(
            start.replace("Z","+00:00")
        ).timestamp()

        duration = float(entry["time"]) / 1000

        end_time = start_time + duration

        requests.append({
            "url": url,
            "norm": norm,
            "start": start_time,
            "duration": duration,
            "end": end_time
        })

    requests.sort(key=lambda x: x["start"])

    return requests

########################################
# PARALLEL GROUP DETECTION
########################################

def detect_parallel_groups(requests):

    groups = []

    current = []
    current_end = None

    for r in requests:

        if not current:
            current = [r]
            current_end = r["end"]
            continue

        if r["start"] < current_end:

            current.append(r)
            current_end = max(current_end, r["end"])

        else:

            if len(current) >= 2:
                groups.append(current)

            current = [r]
            current_end = r["end"]

    if len(current) >= 2:
        groups.append(current)

    return groups

########################################
# LR URL EXTRACTION
########################################

def extract_lr_urls(script):

    pattern = r'URL=([^",\s]+)'

    matches = re.findall(pattern, script)

    urls = []

    for url in matches:

        norm = normalize_url(url)

        if norm:
            urls.append({
                "url": url,
                "norm": norm
            })

    return urls

########################################
# LR CONCURRENT GROUPS
########################################

def extract_lr_groups(script):

    groups = []
    current = []
    inside = False

    for line in script.split("\n"):

        if "web_concurrent_start" in line:

            inside = True
            current = []
            continue

        if "web_concurrent_end" in line:

            inside = False
            groups.append(current)
            continue

        if '"URL=' in line and inside:

            m = re.search(r'URL=([^",\s]+)', line)

            if m:

                url = m.group(1)

                norm = normalize_url(url)

                if norm:

                    current.append({
                        "url": url,
                        "norm": norm
                    })

    return groups

########################################
# URL MATCHING (FIXED VERSION)
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
# COMPARISON
########################################

def compare_urls(har_list, lr_urls):

    rows = []

    for har in har_list:

        status = "Missing in LR"
        lr_match = ""

        for lr in lr_urls:

            if urls_match(har["url"], lr["url"]):

                status = "Matched"
                lr_match = lr["url"]
                break

        rows.append({
            "HAR URL": har["url"],
            "LR URL": lr_match,
            "Status": status
        })

    return pd.DataFrame(rows)

########################################
# EXTRA LR APIS
########################################

def detect_extra_lr(har_requests, lr_urls):

    extra = []

    for lr in lr_urls:

        found = False

        for har in har_requests:

            if urls_match(har["url"], lr["url"]):

                found = True
                break

        if not found:

            extra.append({
                "HAR URL": "",
                "LR URL": lr["url"],
                "Status": "Extra in LR"
            })

    return pd.DataFrame(extra)

########################################
# WATERFALL GRAPH
########################################

def draw_waterfall(requests):

    starts = [r["start"] for r in requests]
    durations = [r["duration"] for r in requests]

    base = min(starts)
    starts = [s - base for s in starts]

    y = list(range(len(requests)))

    plt.figure()

    plt.barh(y, durations, left=starts)

    plt.xlabel("Time (seconds)")
    plt.ylabel("Requests")

    st.pyplot(plt)

########################################
# STREAMLIT UI
########################################

har_file = st.file_uploader("Upload HAR File")
lr_file = st.file_uploader("Upload LR Script (.txt)")

if har_file and lr_file:

    har_data = json.load(har_file)
    lr_script = lr_file.read().decode()

    har_requests = extract_har_requests(har_data)

    lr_urls = extract_lr_urls(lr_script)

    lr_groups = extract_lr_groups(lr_script)

    st.subheader("HAR Waterfall")

    draw_waterfall(har_requests)

    har_groups = detect_parallel_groups(har_requests)

    st.subheader("Parallel Groups Comparison")

    max_groups = max(len(har_groups), len(lr_groups))

    for i in range(max_groups):

        col1, col2 = st.columns(2)

        with col1:

            st.write(f"HAR Parallel Group {i+1}")

            if i < len(har_groups):

                df = compare_urls(har_groups[i], lr_urls)

                st.dataframe(
                    df.style.applymap(color_status, subset=["Status"])
                )

        with col2:

            st.write(f"LR Concurrent Group {i+1}")

            if i < len(lr_groups):

                df = pd.DataFrame(lr_groups[i])

                st.dataframe(df)

    st.subheader("Full HAR vs LR Comparison")

    full = compare_urls(har_requests, lr_urls)

    st.dataframe(
        full.style.applymap(color_status, subset=["Status"])
    )

    st.subheader("Extra APIs in LR")

    extra = detect_extra_lr(har_requests, lr_urls)

    if not extra.empty:

        st.dataframe(
            extra.style.applymap(color_status, subset=["Status"])
        )

    else:

        st.write("No extra APIs in LR.")
