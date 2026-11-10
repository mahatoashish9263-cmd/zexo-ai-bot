
import os
import re
import asyncio
import logging
import subprocess
import tempfile
from pathlib import Path

from telegram import Update
from telegram.ext import (
    Application,
    CommandHandler,
    MessageHandler,
    ContextTypes,
    filters,
)
from google import genai
from google.genai import types

# =====================================
# ZEXO AI - CONFIGURATION
# =====================================

TELEGRAM_TOKEN = os.environ.get("TELEGRAM_BOT_TOKEN")
GEMINI_API_KEY = os.environ.get("GEMINI_API_KEY")
PUBLIC_URL = os.environ.get("PUBLIC_URL", "").rstrip("/")
WEBHOOK_SECRET = os.environ.get("WEBHOOK_SECRET")
WEBHOOK_PATH = "zexo-webhook"
PORT = int(os.environ.get("PORT", "8080"))

MODEL = os.environ.get(
    "GEMINI_MODEL",
    "gemini-2.5-flash"
)

MAX_VIDEO_SIZE = 20 * 1024 * 1024

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger("zexo-ai")

if not TELEGRAM_TOKEN:
    raise RuntimeError("TELEGRAM_BOT_TOKEN is missing")

if not GEMINI_API_KEY:
    raise RuntimeError("GEMINI_API_KEY is missing")

if not PUBLIC_URL or not WEBHOOK_SECRET:
    raise RuntimeError("Webhook configuration is missing")

client = genai.Client(api_key=GEMINI_API_KEY)

SYSTEM_PROMPT = """
You are Zexo AI, a professional and helpful AI assistant.

Your capabilities include:

1. General AI chat and question answering.
2. YouTube and Instagram content ideas.
3. Video scripts with strong hooks and retention.
4. Titles, descriptions, SEO and hashtags.
5. Captions and social media content.
6. Thumbnail concepts and image prompts.
7. Photo analysis and editing guidance.
8. Video editing guidance.
9. Learning, coding, writing and productivity.

Reply in the user's language.
Understand Hindi, Hinglish and English.
Be accurate, clear, helpful and fast.
Never claim that an action was completed unless it actually was.
"""

# =====================================
# GEMINI AI
# =====================================

def ask_gemini(prompt, image_part=None):

    contents = [SYSTEM_PROMPT, prompt]

    if image_part is not None:
        contents.append(image_part)

    response = client.models.generate_content(
        model=MODEL,
        contents=contents
    )

    return response.text or "Please try again."


# =====================================
# TELEGRAM START
# =====================================

async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):

    await update.message.reply_text(
        "Welcome to ZEXO AI!\n\n"
        "Your AI assistant is ready.\n\n"
        "You can ask me anything.\n\n"
        "Features:\n"
        "• AI Chat\n"
        "• Video Ideas and Scripts\n"
        "• YouTube SEO\n"
        "• Instagram Captions\n"
        "• Photo Analysis\n"
        "• Video Editing\n"
        "• Thumbnail Prompts\n\n"
        "Send a message to get started."
    )


async def help_command(update: Update, context: ContextTypes.DEFAULT_TYPE):

    await update.message.reply_text(
        "ZEXO AI HELP\n\n"
        "Send text: AI Chat\n"
        "Send photo: Photo Analysis\n"
        "Send video with one of these captions:\n\n"
        "/trim 0 30 - Trim 30 seconds from start\n"
        "/compress - Reduce video size\n"
        "/vertical - Convert to 9:16\n"
        "/mute - Remove video audio\n"
        "/audio - Extract MP3 audio\n\n"
        "Send /start to open Zexo AI."
    )


# =====================================
# AI TEXT CHAT
# =====================================

async def handle_text(update: Update, context: ContextTypes.DEFAULT_TYPE):

    message = update.message

    if not message or not message.text:
        return

    prompt = message.text.strip()

    if not prompt:
        return

    status = await message.reply_text(
        "Zexo AI is thinking..."
    )

    try:

        answer = await asyncio.to_thread(
            ask_gemini,
            prompt
        )

        await status.delete()

        for i in range(0, len(answer), 4000):

            await message.reply_text(
                answer[i:i + 4000]
            )

    except Exception:

        logger.exception("Gemini text error")

        await status.edit_text(
            "Sorry! AI service is temporarily unavailable."
        )


# =====================================
# PHOTO ANALYSIS
# =====================================

async def handle_photo(update: Update, context: ContextTypes.DEFAULT_TYPE):

    message = update.message

    if not message or not message.photo:
        return

    status = await message.reply_text(
        "Analyzing your photo..."
    )

    try:

        photo = message.photo[-1]

        photo_file = await photo.get_file()

        image_bytes = await photo_file.download_as_bytearray()

        prompt = message.caption or (
            "Analyze this photo and explain what you see."
        )

        image_part = types.Part.from_bytes(
            data=bytes(image_bytes),
            mime_type="image/jpeg"
        )

        answer = await asyncio.to_thread(
            ask_gemini,
            prompt,
            image_part
        )

        await status.delete()

        for i in range(0, len(answer), 4000):

            await message.reply_text(
                answer[i:i + 4000]
            )

    except Exception:

        logger.exception("Photo analysis error")

        await status.edit_text(
            "Photo analysis failed. Please try again."
        )


# =====================================
# VIDEO EDITING ENGINE - FFMPEG
# =====================================

def edit_video(input_path, output_path, operation, start=0, duration=0):

    base = ["ffmpeg", "-y"]

    if operation == "trim":

        command = base + [
            "-ss", str(start),
            "-i", input_path,
            "-t", str(duration),
            "-c:v", "libx264",
            "-preset", "veryfast",
            "-crf", "23",
            "-c:a", "aac",
            "-movflags", "+faststart",
            output_path
        ]

    elif operation == "compress":

        command = base + [
            "-i", input_path,
            "-vf", "scale=w='min(1280,iw)':h=-2",
            "-c:v", "libx264",
            "-preset", "veryfast",
            "-crf", "28",
            "-c:a", "aac",
            "-b:a", "96k",
            "-movflags", "+faststart",
            output_path
        ]

    elif operation == "vertical":

        command = base + [
            "-i", input_path,
            "-vf",
            "scale=720:1280:force_original_aspect_ratio=increase,crop=720:1280",
            "-c:v", "libx264",
            "-preset", "veryfast",
            "-crf", "23",
            "-c:a", "aac",
            "-movflags", "+faststart",
            output_path
        ]

    elif operation == "mute":

        command = base + [
            "-i", input_path,
            "-an",
            "-c:v", "libx264",
            "-preset", "veryfast",
            "-crf", "23",
            "-movflags", "+faststart",
            output_path
        ]

    elif operation == "audio":

        command = base + [
            "-i", input_path,
            "-vn",
            "-q:a", "4",
            "-y",
            output_path
        ]

    else:
        raise ValueError("Unsupported editing operation")

    subprocess.run(
        command,
        check=True,
        capture_output=True,
        timeout=300
    )

    return output_path


# =====================================
# VIDEO COMMAND DETECTION
# =====================================

def detect_operation(caption):

    text = (caption or "").strip().lower()

    if text.startswith("/trim"):

        match = re.fullmatch(
            r"/trim\s+(\d+(?:\.\d+)?)\s+(\d+(?:\.\d+)?)",
            text
        )

        if not match:
            raise ValueError(
                "Use: /trim 0 30"
            )

        start = float(match.group(1))
        duration = float(match.group(2))

        if duration <= 0 or duration > 300:
            raise ValueError(
                "Trim duration must be between 1 and 300 seconds."
            )

        if start > 3600:
            raise ValueError("Invalid start time.")

        return "trim", start, duration

    if text.startswith("/compress") or "compress" in text:
        return "compress", 0, 0

    if text.startswith("/vertical") or "9:16" in text:
        return "vertical", 0, 0

    if text.startswith("/mute") or "mute" in text:
        return "mute", 0, 0

    if text.startswith("/audio") or "extract audio" in text:
        return "audio", 0, 0

    raise ValueError(
        "Please add a video editing command in its caption.\n\n"
        "Available commands:\n"
        "/trim 0 30\n"
        "/compress\n"
        "/vertical\n"
        "/mute\n"
        "/audio"
    )


# =====================================
# VIDEO HANDLER
# =====================================

async def handle_video(update: Update, context: ContextTypes.DEFAULT_TYPE):

    message = update.message

    if not message or not message.video:
        return

    video = message.video

    if video.file_size and video.file_size > MAX_VIDEO_SIZE:

        await message.reply_text(
            "Video is too large. Please send a video under 20 MB."
        )
        return

    try:

        operation, start, duration = detect_operation(
            message.caption
        )

    except ValueError as error:

        await message.reply_text(str(error))
        return

    status = await message.reply_text(
        "Zexo AI is processing your video..."
    )

    try:

        with tempfile.TemporaryDirectory() as temp_dir:

            input_path = str(
                Path(temp_dir) / "input.mp4"
            )

            output_name = (
                "edited.mp3"
                if operation == "audio"
                else "edited.mp4"
            )

            output_path = str(
                Path(temp_dir) / output_name
            )

            telegram_file = await video.get_file()

            await telegram_file.download_to_drive(
                custom_path=input_path
            )

            await asyncio.to_thread(
                edit_video,
                input_path,
                output_path,
                operation,
                start,
                duration
            )

            await status.edit_text(
                "Editing complete! Sending your file..."
            )

            with open(output_path, "rb") as output_file:

                if operation == "audio":

                    await message.reply_audio(
                        audio=output_file,
                        filename="zexo_audio.mp3"
                    )

                else:

                    await message.reply_video(
                        video=output_file,
                        filename="zexo_edited.mp4",
                        supports_streaming=True
                    )

            await status.delete()

    except Exception:

        logger.exception("Video editing error")

        await status.edit_text(
            "Video editing failed. Try a smaller MP4 video "
            "or a different editing command."
        )


# =====================================
# ERROR HANDLER
# =====================================

async def error_handler(update, context):

    logger.error(
        "Telegram application error: %s",
        context.error
    )


# =====================================
# MAIN APPLICATION
# =====================================

def main():

    application = (
        Application.builder()
        .token(TELEGRAM_TOKEN)
        .build()
    )

    application.add_handler(
        CommandHandler("start", start)
    )

    application.add_handler(
        CommandHandler("help", help_command)
    )

    application.add_handler(
        MessageHandler(
            filters.PHOTO,
            handle_photo
        )
    )

    application.add_handler(
        MessageHandler(
            filters.VIDEO,
            handle_video
        )
    )

    application.add_handler(
        MessageHandler(
            filters.TEXT & ~filters.COMMAND,
            handle_text
        )
    )

    application.add_error_handler(
        error_handler
    )

    logger.info("Zexo AI is starting...")

    application.run_webhook(
        listen="0.0.0.0",
        port=PORT,
        url_path=WEBHOOK_PATH,
        webhook_url=f"{PUBLIC_URL}/{WEBHOOK_PATH}",
        secret_token=WEBHOOK_SECRET,
        drop_pending_updates=True
    )


if __name__ == "__main__":
    main()
  
