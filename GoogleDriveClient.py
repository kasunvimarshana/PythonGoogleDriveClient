# from __future__ import print_function
import os
import os.path
import sys
import hashlib
import pickle
import mimetypes
from google.auth.transport.requests import Request
from google.oauth2.credentials import Credentials
from google_auth_oauthlib.flow import InstalledAppFlow
from googleapiclient.discovery import build
from googleapiclient.errors import HttpError
from googleapiclient.http import MediaFileUpload, MediaIoBaseDownload

class GoogleDriveClient():
    # private data members (__)
    # protected data members (_)

    def __init__(self, local_folder, drive_folder):
        self.__api_name = "drive"
        self.__api_version = "v3"
        self.__credential_file = "credentials.json"
        self.__token_file = "token.json"
        self.__hash_file = "file_hashes.pickle"
        self.__scopes = [
            "https://www.googleapis.com/auth/drive"
        ]
        self.__creds = None
        self.__drive_service = None
        self.__local_folder = local_folder
        # self.__drive_folder = drive_folder

        # self.__hashes = self.load_hashes()
        self.authenticate()
        self.__drive_folder = self.get_or_create_drive_folder(drive_folder)

    def authenticate(self):
        # Load credentials from file
        if os.path.exists( self.__token_file ):
            self.__creds = Credentials.from_authorized_user_file(self.__token_file, self.__scopes)
        
        # If no valid credentials are available, request user login
        if not self.__creds or not self.__creds.valid:
            if self.__creds and self.__creds.expired and self.__creds.refresh_token:
                self.__creds.refresh(Request())
            else:
                flow = InstalledAppFlow.from_client_secrets_file(
                    self.__credential_file, 
                    self.__scopes
                )
                self.__creds = flow.run_local_server(port=0)
                # Save the credentials for the next run
                with open(self.__token_file, "w") as token:
                    token.write(self.__creds.to_json())

        self.__drive_service = build(self.__api_name, self.__api_version, credentials=self.__creds)

    def get_drive_file(self, file_name, parent_id):
        try:
            results = self.__drive_service.files().list(
                q=f"name='{file_name}' and '{parent_id}' in parents and trashed != True",
                spaces="drive",
                fields="files(id, name, md5Checksum, mimeType)"
            ).execute()
            items = results.get("files", [])
            if items:
                return items[0]
        except HttpError as e:
            print(f"An error occurred: {e}")
        return None
    
    def create_drive_folder(self, folder_name, parent_id):
        folder_metadata = {
            "name": folder_name,
            "mimeType": "application/vnd.google-apps.folder",
            "parents": [parent_id]
        }
        folder = self.__drive_service.files().create(body=folder_metadata, fields="id").execute()
        return folder.get("id")

    def get_or_create_drive_folder(self, folder_name, parent_id="root"):
        existing_folder = self.get_drive_file(folder_name, parent_id)
        if existing_folder:
            return existing_folder.get("id")
        
        return self.create_drive_folder(folder_name, parent_id)

    @staticmethod
    def get_file_hash(file_path):
        # checksum = hashlib.md5(open(file_path, "rb").read()).hexdigest()
        hash_md5 = hashlib.md5()
        with open(file_path, "rb") as f:
            for chunk in iter(lambda: f.read(4096), b""):
                hash_md5.update(chunk)
        checksum = hash_md5.hexdigest()
        return checksum

    # def load_hashes(self):
    #     if os.path.exists(self.__hash_file):
    #         with open(self.__hash_file, "rb") as f:
    #             return pickle.load(f)
    #     return {}

    # def save_hashes(self):
    #     with open(self.__hash_file, "wb") as f:
    #         pickle.dump(self.__hashes, f)

    # def sync(self):
    #     for root, dirs, files in os.walk(self.__local_folder):
    #         for file in files:
    #             local_path = os.path.join(root, file)
    #             file_hash = self.get_file_hash(local_path)
                
    #             if local_path not in self.__hashes or self.__hashes[local_path] != file_hash:
    #                 drive_file_id = self.upload_file(local_path, self.__drive_folder)
    #                 print(f"Uploaded {local_path} to Drive with file ID {drive_file_id}")
    #                 self.__hashes[local_path] = file_hash

    #     self.save_hashes()

    def upload_file(self, file_path, parent_id):
        file_name = os.path.basename(file_path)
        local_hash = self.get_file_hash(file_path)
        
        drive_file = self.get_drive_file(file_name, parent_id)
        
        if drive_file:
            drive_hash = drive_file.get("md5Checksum")
            if drive_hash == local_hash:
                print(f"{file_name} is up to date.")
                return

            # Update the file if the hash is different
            mime_type, _ = mimetypes.guess_type(file_path)
            file_metadata = {
                "name": file_name, 
                "parents": [parent_id]
            }
            media = MediaFileUpload(file_path, mimetype=mime_type, resumable=True)
            updated_file = self.__drive_service.files().update(fileId=drive_file.get("id"), body=file_metadata, media_body=media, fields="id").execute()
            print(f"Updated {file_name} on Drive with file ID {updated_file.get('id')}")
        else:
            # Upload the file if it does not exist
            mime_type, _ = mimetypes.guess_type(file_path)
            file_metadata = {
                "name": file_name, 
                "parents": [parent_id]
            }
            media = MediaFileUpload(file_path, mimetype=mime_type, resumable=True)
            file = self.__drive_service.files().create(body=file_metadata, media_body=media, fields="id").execute()
            print(f"Uploaded {file_name} to Drive with file ID {file.get('id')}")

    def sync_folder(self, local_folder_path, drive_folder_id):
        for root, dirs, files in os.walk(local_folder_path):
            # Calculate relative path from local folder to current directory
            rel_path = os.path.relpath(root, local_folder_path)
            # Find the correct parent_id on Google Drive
            current_folder_id = drive_folder_id

            if rel_path != ".":
                # Create or get the folder on Google Drive
                folder_names = rel_path.split(os.sep)
                for folder_name in folder_names:
                    current_folder = self.get_drive_file(folder_name, current_folder_id)
                    if not current_folder:
                        current_folder_id = self.create_drive_folder(folder_name, current_folder_id)
                    else:
                        current_folder_id = current_folder.get("id")

            for file_name in files:
                file_path = os.path.join(root, file_name)
                self.upload_file(file_path, current_folder_id)

    def sync(self):
        self.sync_folder(self.__local_folder, self.__drive_folder)


def main():
    local_folder = "C:\\Users\\kasun\\Desktop\\New folder (3)"
    drive_folder = "Share"
    try:
        sync = GoogleDriveClient(local_folder, drive_folder)
        sync.sync()
    except Exception as e:
        print("Error : " + str(e))

if __name__ == "__main__":
    main()

