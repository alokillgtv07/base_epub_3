#!/usr/bin/env python3
"""
Cập nhật URL trong file JSON dựa theo cấu trúc thư mục THỰC TẾ trên GitHub repo.

Ý tưởng:
  1. Gọi GitHub Trees API để lấy TOÀN BỘ danh sách file trong repo (1 request duy nhất).
  2. Lọc ra các file .epub và map: {filename.epub -> tên thư mục chứa nó}
     Ví dụ: {"dithedaomon.epub": "epub__1", "toahon.epub": "epub__1", ...}
  3. Duyệt JSON, với mỗi item:
     - Lấy filename từ 'cover' (bỏ đuôi ảnh, thêm .epub)
     - Tra trong map xem file đang nằm ở thư mục nào
     - Cập nhật 'url' = RAW_BASE + folder + filename
     - Backup URL cũ vào 'url_2' (nếu chưa có)
  4. Cứ 100 item thì ghi JSON (tránh mất dữ liệu).

Cách chạy:
    cd /storage/emulated/0/Download/GitDownload/
    python update_json_from_github.py
"""

import json
import os
import re
import sys
import time
import requests

# ================== CẤU HÌNH ==================
JSON_FILE_PATH = "/storage/emulated/0/Download/GitDownload/listepub_2_updated.json"

GITHUB_OWNER  = "alokillgtv07"
GITHUB_REPO   = "base_epub_1"
GITHUB_BRANCH = "main"

# URL base để tạo link raw
GITHUB_RAW_BASE = f"https://raw.githack.com/{GITHUB_OWNER}/{GITHUB_REPO}/{GITHUB_BRANCH}"
GITHUB_API_BASE = f"https://api.github.com/repos/{GITHUB_OWNER}/{GITHUB_REPO}"

# Token GitHub (tùy chọn). Để trống nếu không dùng.
# Không có token: giới hạn 60 request/giờ (nhưng script chỉ dùng 1-2 request nên OK).
# Có token: giới hạn 5000 request/giờ.
GITHUB_TOKEN = ""

# Số item xử lý xong thì ghi JSON 1 lần
SAVE_EVERY = 100

HEADERS = {
    'Accept': 'application/vnd.github+json',
    'User-Agent': 'epub-json-updater/1.0',
}
if GITHUB_TOKEN:
    HEADERS['Authorization'] = f'Bearer {GITHUB_TOKEN}'


# ================== HÀM HỖ TRỢ ==================

def extract_items_recursively(data):
    """Trích xuất tất cả dict có 'url' và 'cover' (đệ quy)."""
    items = []
    if isinstance(data, list):
        for x in data:
            items.extend(extract_items_recursively(x))
    elif isinstance(data, dict):
        if 'url' in data and 'cover' in data:
            items.append(data)
        else:
            for v in data.values():
                items.extend(extract_items_recursively(v))
    return items


def extract_epub_filename_from_cover(cover_url):
    """
    Từ cover URL lấy ra tên file epub.
    Ví dụ:
      https://.../book/img2/dithedaomon.jpg   ->   dithedaomon.epub
    """
    if not cover_url:
        return None
    base = cover_url.split('?')[0].split('/')[-1]      # dithedaomon.jpg
    name = os.path.splitext(base)[0]                   # dithedaomon
    if not name:
        return None
    return f"{name}.epub"


def save_json(data, path):
    try:
        with open(path, 'w', encoding='utf-8') as f:
            json.dump(data, f, ensure_ascii=False, indent=2)
        print(f"\n💾 Đã lưu JSON: {path}")
        return True
    except Exception as e:
        print(f"\n❌ Lỗi khi lưu JSON: {e}")
        return False


def get_repo_epub_map():
    """
    Gọi GitHub Trees API 1 lần, trả về dict:
        { "dithedaomon.epub": "epub__1", "toahon.epub": "epub__2", ... }
    Chỉ lấy các file .epub nằm trực tiếp trong 1 thư mục con của repo.
    """
    url = f"{GITHUB_API_BASE}/git/trees/{GITHUB_BRANCH}?recursive=1"
    print(f"🌐 Đang gọi GitHub Trees API: {url}")

    r = requests.get(url, headers=HEADERS, timeout=30)

    if r.status_code == 401:
        print("❌ 401 Unauthorized — token không hợp lệ.")
        sys.exit(1)
    if r.status_code == 404:
        print(f"❌ 404 — Không tìm thấy repo '{GITHUB_OWNER}/{GITHUB_REPO}' "
              f"hoặc branch '{GITHUB_BRANCH}'.")
        sys.exit(1)
    if r.status_code == 403:
        print("❌ 403 Forbidden — có thể bị rate limit. "
              "Thử lại sau hoặc điền GITHUB_TOKEN.")
        sys.exit(1)
    r.raise_for_status()

    payload = r.json()
    tree = payload.get('tree', [])
    truncated = payload.get('truncated', False)
    if truncated:
        print("⚠️ Cảnh báo: kết quả tree bị GitHub cắt ngắn (quá nhiều file).")

    epub_map = {}
    for node in tree:
        if node.get('type') != 'blob':
            continue
        path = node.get('path', '')
        if not path.lower().endswith('.epub'):
            continue
        parts = path.split('/')
        if len(parts) == 2:                             # ví dụ: epub__1/dithedaomon.epub
            folder, filename = parts
            epub_map[filename] = folder

    print(f"📂 Tìm thấy {len(epub_map)} file .epub trên GitHub "
          f"trong {len(set(epub_map.values()))} thư mục.")
    return epub_map


# ================== MAIN ==================

def main():
    print("=" * 60)
    print("🔄 CẬP NHẬT JSON THEO CẤU TRÚC THƯ MỤC TRÊN GITHUB")
    print("=" * 60)

    if not os.path.exists(JSON_FILE_PATH):
        print(f"❌ Không tìm thấy JSON: {JSON_FILE_PATH}")
        sys.exit(1)

    # ---- 1. Lấy bản đồ file .epub từ GitHub ----
    try:
        epub_map = get_repo_epub_map()
    except requests.exceptions.RequestException as e:
        print(f"❌ Lỗi kết nối GitHub API: {e}")
        sys.exit(1)

    if not epub_map:
        print("⚠️ Không tìm thấy file .epub nào trong repo. Thoát.")
        return

    # ---- 2. Đọc JSON ----
    with open(JSON_FILE_PATH, 'r', encoding='utf-8') as f:
        data = json.load(f)

    items = extract_items_recursively(data)
    print(f"📚 Tổng số item trong JSON: {len(items)}")

    # ---- 3. Duyệt và cập nhật ----
    updated   = 0
    not_found = 0
    already   = 0
    error     = 0
    sample_printed = False

    for idx, item in enumerate(items):
        filename = extract_epub_filename_from_cover(item.get('cover', ''))
        if not filename:
            error += 1
            continue

        folder = epub_map.get(filename)
        if not folder:
            not_found += 1
            print(f"  ⚠️ Không thấy trên GitHub: {filename}")
            continue

        new_url = f"{GITHUB_RAW_BASE}/{folder}/{filename}"

        if item.get('url') == new_url:
            already += 1
            continue

        # Backup URL cũ
        if 'url_2' not in item or not item['url_2']:
            item['url_2'] = item.get('url', '')

        item['url'] = new_url
        updated += 1

        if not sample_printed:
            print(f"\n📝 Ví dụ đã cập nhật:")
            print(f"   filename : {filename}")
            print(f"   folder   : {folder}")
            print(f"   new URL  : {new_url}\n")
            sample_printed = True

        # Cứ SAVE_EVERY item thì ghi JSON
        if updated and updated % SAVE_EVERY == 0:
            save_json(data, JSON_FILE_PATH)

    # ---- 4. Ghi JSON lần cuối ----
    save_json(data, JSON_FILE_PATH)

    # ---- 5. Tổng kết ----
    print("\n" + "=" * 60)
    print("📊 TỔNG KẾT")
    print("=" * 60)
    print(f"✅ Đã cập nhật URL       : {updated}")
    print(f"⏭️  Đã đúng từ trước      : {already}")
    print(f"⚠️  Không tìm thấy trên GH: {not_found}")
    print(f"❌ Lỗi lấy filename      : {error}")
    print(f"📝 File JSON             : {JSON_FILE_PATH}")


if __name__ == "__main__":
    main()