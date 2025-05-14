from flask import Flask, request, send_file, render_template
from youtube_transcript_api import YouTubeTranscriptApi, TranscriptsDisabled, NoTranscriptFound
from googleapiclient.discovery import build
from PyPDF2 import PdfWriter
from reportlab.lib.pagesizes import letter
from reportlab.pdfgen import canvas
from io import BytesIO
import os
import zipfile
import re
import time

app = Flask(__name__)

# مفتاح API ليوتيوب (يجب استبداله بمفتاحك الخاص)
YOUTUBE_API_KEY = os.getenv("AIzaSyC7QTZt8GoCzr5dumrJXLYGqv979O7s_Yo", "AIzaSyC7QTZt8GoCzr5dumrJXLYGqv979O7s_Yo")

def fetch_playlist_transcripts(playlist_url: str, language: str = "en") -> dict:
    try:
        playlist_id = re.search(r"list=([A-Za-z0-9_-]+)", playlist_url)
        if not playlist_id:
            return {}

        playlist_id = playlist_id.group(1)
        youtube = build("youtube", "v3", developerKey=YOUTUBE_API_KEY)

        video_ids = []
        next_page_token = None
        while True:
            req = youtube.playlistItems().list(
                part="contentDetails",
                playlistId=playlist_id,
                maxResults=50,
                pageToken=next_page_token
            )
            res = req.execute()
            video_ids.extend([item["contentDetails"]["videoId"] for item in res["items"]])
            next_page_token = res.get("nextPageToken")
            if not next_page_token:
                break

        transcripts = {}
        for video_id in video_ids:
            try:
                transcript_list = YouTubeTranscriptApi.list_transcripts(video_id)
                transcript = transcript_list.find_transcript([language]) or transcript_list.find_generated_transcript([language])
                transcript_text = " ".join([entry["text"] for entry in transcript.fetch()])
                video_title = youtube.videos().list(part="snippet", id=video_id).execute()["items"][0]["snippet"]["title"]
                transcripts[video_id] = {"title": video_title, "text": transcript_text}
                time.sleep(1)  # لتجنب حدود معدل API
            except (TranscriptsDisabled, NoTranscriptFound):
                transcripts[video_id] = {"title": video_id, "text": "No transcript available."}
            except Exception as e:
                transcripts[video_id] = {"title": video_id, "text": f"Error: {str(e)}"}
        return transcripts
    except Exception as e:
        print(f"Error: {str(e)}")
        return {}

def create_text_file(content: str, filename: str):
    os.makedirs(os.path.dirname(filename), exist_ok=True)
    with open(filename, "w", encoding="utf-8") as f:
        f.write(content)

def create_pdf_file(content: str, title: str, filename: str):
    buffer = BytesIO()
    c = canvas.Canvas(buffer, pagesize=letter)
    c.setFont("Helvetica", 12)
    c.drawString(100, 750, title)
    y = 700
    for line in content.split("\n"):
        if y < 50:
            c.showPage()
            y = 750
        c.drawString(100, y, line)
        y -= 15
    c.save()
    buffer.seek(0)
    os.makedirs(os.path.dirname(filename), exist_ok=True)
    with open(filename, "wb") as f:
        f.write(buffer.read())

def parse_playlist_urls_from_text(content: str) -> list:
    urls = re.findall(r"https?://(?:www\.)?youtube\.com/.*list=([A-Za-z0-9_-]+)", content)
    return [f"https://www.youtube.com/playlist?list={url}" for url in urls]

@app.route("/", methods=["GET"])
def index():
    return render_template("index.html")

@app.route("/extract", methods=["POST"])
def extract_transcripts():
    try:
        playlist_url = request.form.get("playlist_url")
        language = request.form.get("language", "en")
        transcripts = fetch_playlist_transcripts(playlist_url, language)
        if not transcripts:
            return render_template("index.html", error="No transcripts found or invalid playlist URL.")

        output_dir = "transcripts"
        os.makedirs(output_dir, exist_ok=True)
        zip_filename = "transcripts.zip"

        for video_id, transcript in transcripts.items():
            title = transcript.get("title", video_id)
            text_content = transcript.get("text", "No transcript available.")
            create_text_file(text_content, f"{output_dir}/{title}.txt")
            create_pdf_file(text_content, title, f"{output_dir}/{title}.pdf")

        with zipfile.ZipFile(zip_filename, "w", zipfile.ZIP_DEFLATED) as zipf:
            for filename in os.listdir(output_dir):
                zipf.write(os.path.join(output_dir, filename), filename)

        return send_file(zip_filename, as_attachment=True, download_name="transcripts.zip")
    except Exception as e:
        return render_template("index.html", error=f"Error: {str(e)}")

@app.route("/batch-extract", methods=["POST"])
def batch_extract_transcripts():
    try:
        file = request.files.get("file")
        language = request.form.get("language", "en")
        if not file:
            return render_template("index.html", error="No file uploaded.")

        content = file.read().decode("utf-8")
        playlist_urls = parse_playlist_urls_from_text(content)
        if not playlist_urls:
            return render_template("index.html", error="No valid playlist URLs found.")

        output_dir = "batch_transcripts"
        os.makedirs(output_dir, exist_ok=True)
        zip_filename = "batch_transcripts.zip"

        for playlist_url in playlist_urls:
            transcripts = fetch_playlist_transcripts(playlist_url, language)
            for video_id, transcript in transcripts.items():
                title = transcript.get("title", video_id)
                text_content = transcript.get("text", "No transcript available.")
                create_text_file(text_content, f"{output_dir}/{title}.txt")
                create_pdf_file(text_content, title, f"{output_dir}/{title}.pdf")

        with zipfile.ZipFile(zip_filename, "w", zipfile.ZIP_DEFLATED) as zipf:
            for filename in os.listdir(output_dir):
                zipf.write(os.path.join(output_dir, filename), filename)

        return send_file(zip_filename, as_attachment=True, download_name="batch_transcripts.zip")
    except Exception as e:
        return render_template("index.html", error=f"Error: {str(e)}")

if __name__ == "__main__":
    app.run(debug=True, host="0.0.0.0", port=8000)
