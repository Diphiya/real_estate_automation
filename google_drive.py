"""
Cirrus Real Estate — Google Drive Uploader (Final Version)

Features:
  - Token refresh (no repeated login)
  - Reuses root/project folders (no duplicates)
  - Uploads files + images
  - Returns structured links (files + images + folder)
  - Dry-run mode
  - Optional sharing

Usage:
    python google_drive.py --auth
    python google_drive.py --address BernauProperty
    python google_drive.py --files expose.pdf data.json
"""

import argparse
import datetime
import mimetypes
import os
import sys

from google.auth.transport.requests import Request
from google.oauth2.credentials import Credentials
from google_auth_oauthlib.flow import InstalledAppFlow
from googleapiclient.discovery import build
from googleapiclient.errors import HttpError
from googleapiclient.http import MediaFileUpload

SCOPES = ['https://www.googleapis.com/auth/drive.file']
TOKEN_PATH = 'token_drive.json'
CREDENTIALS_PATH = 'credentials.json'
ROOT_FOLDER_NAME = 'Cirrus Real Estate — Projects'


# ─────────────────────────────────────────────────────
# AUTH
# ─────────────────────────────────────────────────────

def authenticate(force: bool = False):
    creds = None

    if os.path.exists(TOKEN_PATH) and not force:
        creds = Credentials.from_authorized_user_file(TOKEN_PATH, SCOPES)

    if not creds or not creds.valid:
        if creds and creds.expired and creds.refresh_token:
            print("  Refreshing token…")
            try:
                creds.refresh(Request())
            except Exception:
                creds = None

        if not creds:
            if not os.path.exists(CREDENTIALS_PATH):
                print("\n✗ credentials.json missing")
                sys.exit(1)

            flow = InstalledAppFlow.from_client_secrets_file(CREDENTIALS_PATH, SCOPES)
            creds = flow.run_local_server(port=0)

        with open(TOKEN_PATH, 'w') as f:
            f.write(creds.to_json())

        print(f"  ✓ Token saved → {TOKEN_PATH}")

    return build('drive', 'v3', credentials=creds)


# ─────────────────────────────────────────────────────
# FOLDER MANAGEMENT
# ─────────────────────────────────────────────────────

def find_or_create_folder(service, name, parent_id=None):
    query = f"name='{name}' and mimeType='application/vnd.google-apps.folder' and trashed=false"
    if parent_id:
        query += f" and '{parent_id}' in parents"

    results = service.files().list(q=query, fields="files(id,name)").execute()
    files = results.get("files", [])

    if files:
        folder_id = files[0]["id"]
        print(f"  ↺ Reusing folder: {name}")
        return folder_id

    metadata = {"name": name, "mimeType": "application/vnd.google-apps.folder"}
    if parent_id:
        metadata["parents"] = [parent_id]

    folder = service.files().create(body=metadata, fields="id").execute()
    folder_id = folder.get("id")

    print(f"  + Created folder: {name}")
    return folder_id


# ─────────────────────────────────────────────────────
# FILE UPLOAD
# ─────────────────────────────────────────────────────

def upload_file(service, file_path, folder_id, dry_run=False):
    name = os.path.basename(file_path)
    mime = mimetypes.guess_type(file_path)[0] or "application/octet-stream"

    if dry_run:
        print(f"  [DRY] {name}")
        return None

    media = MediaFileUpload(file_path, mimetype=mime, resumable=True)

    file = service.files().create(
        body={"name": name, "parents": [folder_id]},
        media_body=media,
        fields="id,webViewLink"
    ).execute()

    link = file.get("webViewLink")
    print(f"  ✓ {name}")
    return link


def upload_images_from_folder(service, image_folder, parent_id, dry_run=False):
    if not os.path.exists(image_folder):
        print(f"  ⚠ No image folder: {image_folder}")
        return []

    exts = {'.jpg', '.jpeg', '.png', '.webp'}
    images = [f for f in os.listdir(image_folder)
              if os.path.splitext(f)[1].lower() in exts]

    if not images:
        print("  ⚠ No images found")
        return []

    photos_id = find_or_create_folder(service, "Photos", parent_id)

    results = []
    print(f"  Uploading {len(images)} images…")

    for img in sorted(images):
        path = os.path.join(image_folder, img)
        link = upload_file(service, path, photos_id, dry_run)
        if link:
            results.append({"file": img, "url": link})

    return results


# ─────────────────────────────────────────────────────
# MAIN UPLOAD FUNCTION
# ─────────────────────────────────────────────────────

def upload_all(address, files, image_folder="extracted_photos", dry_run=False, share_with=None):

    service = authenticate()
    today = datetime.date.today().isoformat()

    project_name = f"{address}_{today}"
    print(f"\nCreating project: {project_name}")

    root_id = find_or_create_folder(service, ROOT_FOLDER_NAME)
    project_id = find_or_create_folder(service, project_name, root_id)

    project_url = f"https://drive.google.com/drive/folders/{project_id}"

    result = {
        "project_folder": project_name,
        "project_url": project_url,
        "files": [],
        "images": []
    }

    # Upload files
    print("\nUploading files…")
    for f in files:
        if os.path.exists(f):
            link = upload_file(service, f, project_id, dry_run)
            if link:
                result["files"].append({
                    "file": os.path.basename(f),
                    "url": link
                })

    # Upload images
    result["images"] = upload_images_from_folder(service, image_folder, project_id, dry_run)

    # Share
    if share_with and not dry_run:
        try:
            service.permissions().create(
                fileId=project_id,
                body={"type": "user", "role": "reader", "emailAddress": share_with}
            ).execute()
            print(f"  ✓ Shared with {share_with}")
        except HttpError:
            print("  ⚠ Share failed")

    print("\n✓ Upload complete")
    print(f"📁 {project_url}")

    return result


# ─────────────────────────────────────────────────────
# CLI
# ─────────────────────────────────────────────────────

def main():
    parser = argparse.ArgumentParser()

    parser.add_argument("--auth", action="store_true")
    parser.add_argument("--address", default="Property")
    parser.add_argument("--files", nargs="*")
    parser.add_argument("--images", default="extracted_photos")
    parser.add_argument("--share", default="")
    parser.add_argument("--dry-run", action="store_true")

    args = parser.parse_args()

    if args.auth:
        authenticate(force=True)
        print("✓ Auth complete")
        return

    if not args.files:
        import glob
        xlsx = sorted(glob.glob("Cirrus_BusinessCase*.xlsx"), reverse=True)
        args.files = [
            f for f in [
                "expose.pdf",
                "extracted_data.json",
                xlsx[0] if xlsx else None
            ] if f and os.path.exists(f)
        ]

    upload_all(
        address=args.address,
        files=args.files,
        image_folder=args.images,
        dry_run=args.dry_run,
        share_with=args.share
    )


if __name__ == "__main__":
    main()