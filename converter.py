#!/usr/bin/env python3
import os
import sys
import json
import shutil
import argparse
import pathlib
import re
from datetime import datetime, timezone
from bs4 import BeautifulSoup, NavigableString, Tag
from PIL import Image
import subprocess
import mimetypes
from collections import OrderedDict
from mutagen import File as MutagenFile
import pathlib, shutil, subprocess, json
from tinytag import TinyTag
from moviepy import VideoFileClip, AudioFileClip


# Desired order of keys in each message
KEY_ORDER = [
    "id", "type", "date", "date_unixtime",
    "from", "from_id", "actor",
    "actor_id",
    "action",
    "discard_reason",
    "emoticon", "forwarded_from",
    "file", "file_name", "file_size",
    "thumbnail", "thumbnail_file_size",
    "media_type", "sticker_emoji", "mime_type", 
    "duration_seconds", "photo", "photo_file_size", "width", "height", 
    "reply_to_message_id", "location_information", "latitude", 
    "longitude", "message_id", "text", "text_entities"   
]

def order_message(msg: dict) -> OrderedDict:
    if msg.get("type") == "service" and msg.get("action") == "phone_call":
        key_order = [
            "id", "type", "date", "date_unixtime",
            "from", "from_id", "actor", "actor_id",
            "action", "duration_seconds", "discard_reason",
            "text", "text_entities"
        ]
    elif msg.get("media_type") == "video_file":
        key_order = [
            "id", "type", "date", "date_unixtime",
            "from", "from_id",
            "file", "file_name", "file_size",
            "thumbnail", "thumbnail_file_size",
            "media_type", "mime_type", "duration_seconds",
            "width", "height", "text", "text_entities"
        ]
    else:
        key_order = KEY_ORDER

    od = OrderedDict()
    for k in key_order:
        if k in msg:
            od[k] = msg[k]
    for k, v in msg.items():
        if k not in od:
            od[k] = v
    return od

def get_video_duration_ffprobe(fp: pathlib.Path):
    import subprocess
    import json

    exe = shutil.which("ffprobe")
    if not exe:
        return None

    # We try first through stream
    cmd = [
        exe, "-v", "error",
        "-select_streams", "v:0",
        "-show_entries", "stream=duration",
        "-of", "json",
        str(fp)
    ]
    r = subprocess.run(cmd, capture_output=True, text=True)
    try:
        data = json.loads(r.stdout)
        dur = data.get("streams", [{}])[0].get("duration")
        if dur:
            return int(float(dur))
    except Exception:
        pass

    # If it didn't work, we try through format
    cmd = [
        exe, "-v", "error",
        "-show_entries", "format=duration",
        "-of", "json",
        str(fp)
    ]
    r = subprocess.run(cmd, capture_output=True, text=True)
    try:
        data = json.loads(r.stdout)
        dur = data.get("format", {}).get("duration")
        if dur:
            return int(float(dur))
    except Exception:
        pass

    return None

def find_nearest_date(div):
    # Let's try to take the date from the message itself
    d = div.find("div", class_="pull_right date details")
    if d and d.has_attr("title"):
        dt_str = d["title"]
        dt_obj = datetime.strptime(dt_str, "%d.%m.%Y %H:%M:%S UTC%z")
        return dt_obj.strftime("%Y-%m-%dT%H:%M:%S"), str(int(dt_obj.replace(tzinfo=None).timestamp()))
    # Search in the previous ones
    prev = div.find_previous_sibling("div", class_="message")
    while prev:
        d_prev = prev.find("div", class_="pull_right date details")
        if d_prev and d_prev.has_attr("title"):
            dt_str = d_prev["title"]
            dt_obj = datetime.strptime(dt_str, "%d.%m.%Y %H:%M:%S UTC%z")
            return dt_obj.strftime("%Y-%m-%dT%H:%M:%S"), str(int(dt_obj.replace(tzinfo=None).timestamp()))
        prev = prev.find_previous_sibling("div", class_="message")

    # If you didn’t find it, look in the following (down the DOM)
    next_ = div.find_next_sibling("div", class_="message")
    while next_:
        d_next = next_.find("div", class_="pull_right date details")
        if d_next and d_next.has_attr("title"):
            dt_str = d_next["title"]
            dt_obj = datetime.strptime(dt_str, "%d.%m.%Y %H:%M:%S UTC%z")
            return dt_obj.strftime("%Y-%m-%dT%H:%M:%S"), str(int(dt_obj.replace(tzinfo=None).timestamp()))
        next_ = next_.find_next_sibling("div", class_="message")

    # Didn't find anything at all - let there be empty lines
    return "", ""

def probe_format_duration(path: pathlib.Path) -> float | None:
    exe = shutil.which("ffprobe")
    if not exe:
        return None
    cmd = [
        exe, "-v", "error",
        "-show_entries", "format=duration",
        "-of", "default=noprint_wrappers=1:nokey=1",
        str(path)
    ]
    r = subprocess.run(cmd, capture_output=True, text=True)
    if r.returncode != 0 or not r.stdout.strip():
        return None
    try:
        return float(r.stdout.strip())
    except ValueError:
        return None

def probe_ffprobe(path: pathlib.Path):
    exe = shutil.which("ffprobe")
    if not exe:
        return {}
    cmd = [
        exe, "-v", "error",
        "-select_streams", "v:0",
        "-show_entries", "stream=width,height,duration",
        "-of", "json",
        str(path)
    ]
    r = subprocess.run(cmd, capture_output=True, text=True)
    if r.returncode != 0:
        return {}
    data = json.loads(r.stdout)
    return data.get("streams", [{}])[0]

def div_sticker_emoji(fp: pathlib.Path):
    # TODO: Replace with real reading of emoji from HTML tree
    return "❤️"

def get_file_info(fp: pathlib.Path, export_dir: pathlib.Path):
    if not fp.exists():
        return None
    rel = fp.relative_to(export_dir).as_posix()
    info = {
        "file": rel,
        "file_name": fp.name,
        "file_size": fp.stat().st_size,
    }
    suf = fp.suffix.lower()

    # "thumbnail" we are looking for a file of the type <stem>_thumb*<suffix>
    thumb = next((t for t in fp.parent.glob(f"{fp.name}_thumb*")), None)    
    if thumb:
        info["thumbnail"] = thumb.relative_to(export_dir).as_posix()
        info["thumbnail_file_size"] = thumb.stat().st_size

    # Special processing for the photos folder
    if rel.startswith("photos/") and suf in (".jpg", ".jpeg", ".png", ".bmp"):
        return {
            "photo":           rel,
            "photo_file_size": fp.stat().st_size,
            "width":           Image.open(fp).size[0],
            "height":          Image.open(fp).size[1],
        }

    # Everything else: static images, etc.
    if suf in (".jpg", ".jpeg", ".png", ".bmp"):
        with Image.open(fp) as img:
            info["width"], info["height"] = img.size
        info["mime_type"]  = mimetypes.guess_type(str(fp))[0] or "image/jpeg"

    # Static stickers (.webp in stickers folder)
    elif suf == ".webp" and "stickers" in rel:
        with Image.open(fp) as img:
            info["width"], info["height"] = img.size
        info["mime_type"] = mimetypes.guess_type(str(fp))[0] or "image/webp"
        info["media_type"] = "sticker"
        info["sticker_emoji"] = div_sticker_emoji(fp)

    # Animated Stickers
    elif suf == ".tgs":
        info["mime_type"] = "application/x-tgsticker"
        info["media_type"] = "sticker"
        info["sticker_emoji"] = div_sticker_emoji(fp)
         # For tgs-stickers fixed size 512×512
        info["width"], info["height"] = 512, 512

        # Animated stickers in .webm format (new Telegram format)
    elif suf == ".webm" and ("stickers" in rel or "sticker" in fp.name.lower()):
        info["mime_type"] = "video/webm"
        info["media_type"] = "sticker"
        info["sticker_emoji"] = div_sticker_emoji(fp)
    # We get the size and duration through ffprobe
        try:
            meta = probe_ffprobe(fp)
            if meta.get("width"):
                info["width"] = int(meta["width"])
            if meta.get("height"):
                info["height"] = int(meta["height"])
            if meta.get("duration"):
                info["duration_seconds"] = int(float(meta["duration"]))
            if "duration_seconds" not in info or not info["duration_seconds"]:
                dur = get_video_duration_ffprobe(fp)
                if dur:
                    info["duration_seconds"] = dur
        except Exception as e:
            print("Error getting duration:", e) # ← or just pass

    # GIF
    elif suf == ".gif":
        meta = probe_ffprobe(fp)
        with Image.open(fp) as img:
            info["width"], info["height"] = img.size
        if meta.get("duration"):
            info["duration_seconds"] = int(float(meta["duration"]))
        info["mime_type"] = mimetypes.guess_type(str(fp))[0] or "image/gif"
        info["media_type"] = "animation"

     # Video
    elif suf in (".mp4", ".webm", ".avi", ".mov"):
        # if the file is NOT from the files folder, we get the duration and dimensions
        if not rel.startswith("files/"):
            try:
                clip = VideoFileClip(str(fp))
                # Duration & Size
                info["duration_seconds"] = int(clip.duration)
                info["width"], info["height"] = clip.size
                clip.close()
            except Exception:
                # fallback ffprobe, if MoviePy can't
                meta = probe_ffprobe(fp)
                if meta.get("duration"):
                    info["duration_seconds"] = int(float(meta["duration"]))
                if meta.get("width"):
                    info["width"] = int(meta["width"])
                if meta.get("height"):
                    info["height"] = int(meta["height"])

        # Type of "media_type"
        if "round_video_messages" in rel:
            info["media_type"] = "video_message"
            info["width"], info["height"] = 400, 400
        elif "video_files" in rel:
            info["media_type"] = "video_file"
        else:
            info["media_type"] = "video"

        info["mime_type"] = mimetypes.guess_type(str(fp))[0] or f"video/{suf.lstrip('.')}"

        # If "duration" is still not set, try using ffprobe
        if "duration_seconds" not in info:
            meta = probe_ffprobe(fp)
            dur = meta.get("duration")
            if dur:
                try:
                    info["duration_seconds"] = int(float(dur))
                except (ValueError, TypeError):
                    pass

    # Audio & Voice messages
    elif suf in (".m4a", ".mp3", ".ogg"):
        try:
            clip = AudioFileClip(str(fp))
            info["duration_seconds"] = int(clip.duration)
            clip.close()
        except Exception:
            # fallback ffprobe/Mutagen
            meta = probe_ffprobe(fp)
            duration = meta.get("duration")
            if not duration:
                audio = MutagenFile(str(fp))
                if audio and hasattr(audio.info, "length"):
                    duration = audio.info.length
            if duration:
                info["duration_seconds"] = int(float(duration))

        info["mime_type"] = mimetypes.guess_type(str(fp))[0] or f"audio/{suf.lstrip('.')}"
        info["media_type"] = "voice_message" if "voice" in rel else "audio_file"
        # Do not on file_name for .ogg
        if suf == ".ogg":
            info.pop("file_name", None)

     # zip-fb2
    elif suf == ".zip" and fp.name.lower().endswith(".fb2.zip"):
        info["mime_type"] = "application/x-zip-compressed-fb2"

    if "mime_type" not in info:
        known_types = {
            ".epub": "application/epub+zip",
            ".repf": "application/octet-stream",
            ".exe":  "application/octet-stream",
            ".bin":  "application/octet-stream",
            ".zip":  "application/zip",
            ".xlsx": "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
            ".doc":  "application/msword",
            ".pdf":  "application/pdf",
        }
        info["mime_type"] = known_types.get(suf) or mimetypes.guess_type(str(fp))[0] or "application/octet-stream"

    return info

def extract_location(div, msg):
    loc = div.find("div", class_="location")
    if loc and loc.has_attr("data-lat") and loc.has_attr("data-lng"):
        msg.pop("file", None)
        msg["location_information"] = {
            "latitude": float(loc["data-lat"]),
            "longitude": float(loc["data-lng"]),
        }
        msg["text"] = ""
        msg["text_entities"] = []

def parse_html_to_messages(html_path: pathlib.Path, export_dir: pathlib.Path, last_sender: dict):
    messages = []
    soup = BeautifulSoup(html_path.read_text(encoding="utf-8"), "html.parser")
    sender_map = {
        "User1Name": "user111111111",
        "User2Name": "user222222222"
    }

    for div in soup.find_all("div", class_="message"):
        # ID & Date
        raw_id = div.get("id", "")
        msg_id = int(raw_id.replace("message", "")) if raw_id.startswith("message") else -1

        # Date
        d = div.find("div", class_="pull_right date details")
        dt, dt_unixtime = "", ""
        if d and d.has_attr("title"):
            dt_str = d["title"]
            dt_obj = datetime.strptime(dt_str, "%d.%m.%Y %H:%M:%S UTC%z")
            dt = dt_obj.strftime("%Y-%m-%dT%H:%M:%S")
            dt_unixtime = str(int(dt_obj.replace(tzinfo=None).timestamp()))
            
        # Name sender
        body = div.find("div", class_="body")
        sender_el = body.find("div", class_="from_name", recursive=False)
        if sender_el:
            name = sender_el.get_text(strip=True)
            uid = sender_map.get(name, "Unknown")
            last_sender["name"] = name
            last_sender["from_id"] = uid
        else:
            name = last_sender.get("name", "Unknown")
            uid  = last_sender.get("from_id", "Unknown")

        # Service message
        is_service = "service" in div.get("class", [])
        if is_service:
            dt, dt_unixtime = find_nearest_date(div)
            body = div.find("div", class_="body details")
            service_text = body.get_text(strip=True)
            low_text = service_text.lower()
            msg = {
                "id": msg_id,
                "type": "service",
                "date": dt,
                "date_unixtime": dt_unixtime,
                "actor": name,
                "actor_id": uid,
                "text": "",
                "text_entities": []
            }

            # Clear history
            if "history cleared" in low_text:
                msg["action"] = "clear_history"
                messages.append(msg)
                continue

            # Change of theme
            m = re.match(r"(.+?) changed chat theme to (.+)", service_text)
            if m:
                msg["action"] = "edit_chat_theme"
                actor_name = m.group(1).strip()
                msg["actor"]    = actor_name
                msg["actor_id"] = sender_map.get(actor_name, "Unknown")
                msg["emoticon"] = m.group(2).strip()
                messages.append(msg)
                continue

            # Pinned message
            a = body.find("a", onclick=True)
            pin_re = re.match(r"(.+?) pinned", service_text)
            if a and pin_re:
                msg["action"] = "pin_message"
                msg["actor"] = pin_re.group(1).strip()
                msg["actor_id"] = sender_map.get(msg["actor"], "Unknown")
        # Take message_id from onclick
                if "GoToMessage(" in a["onclick"]:
                    mid = int(a["onclick"].split("GoToMessage(")[1].split(")")[0])
                    msg["message_id"] = mid
                messages.append(msg)
                continue

            # If do not find - ignore 
            continue

        # Call
        call = div.find("div", class_="media_call")
        if call:
            # "actor" alsways from "last_sender"
            actor = name
            actor_id = uid
            call_body = call.find("div", class_="body")
            status_tag = call_body.find("div", class_="status details") if call_body else None
            status = status_tag.get_text(strip=True) if status_tag else ""
            # Duration
            m = re.search(r"\((\d+)\s*seconds\)", status)
            duration = int(m.group(1)) if m else None
            # "discard_reason"
            st = status.lower()
            if "outgoing" in st and m:
                discard_reason = "hangup"
            elif "outgoing" in st:
                discard_reason = "busy"
            elif "cancelled" in st:
                discard_reason = "missed"
            elif "declined" in st:
                discard_reason = "busy"
            elif "missed" in st:
                discard_reason = "missed"
            elif "incoming" in st and m:
                discard_reason = "hangup"
            else:
                discard_reason = st

            call_msg = {
                "id": msg_id,
                "type": "service",
                "date": dt,
                "date_unixtime": dt_unixtime,
                "actor": actor,
                "actor_id": actor_id,
                "action": "phone_call",
                "text": "",
                "text_entities": [],
                "discard_reason": discard_reason
            }
            if duration is not None:
                call_msg["duration_seconds"] = duration
            messages.append(call_msg)
            continue  # Skip simple message if it call

        # Simple message
        msg = {
            "id": msg_id,
            "type": "message",
            "date": dt,
            "date_unixtime": dt_unixtime,
            "from": name,
            "from_id": uid,
            "text": "",
            "text_entities": [],
        }

# Contact or Poll
        contact_div = div.find("div", class_="media_contact")
        poll_div    = div.find("div", class_="media_poll")

        if contact_div:
            # Contact
            title = contact_div.select_one("div.title.bold")
            phone = contact_div.select_one("div.status.details")
            msg["contact_information"] = {
                "first_name": title.get_text(strip=True) if title else "",
                "last_name": "",
                "phone_number": phone.get_text(strip=True) if phone else ""
            }
            messages.append(msg)
            continue

        elif poll_div:
            # Source for forward
            fwd = div.find("div", class_="forwarded body")
            if fwd:
                orig = fwd.find("div", class_="from_name", recursive=False)
                if orig:
                    for span in orig.find_all("span", class_="date details"):
                        span.decompose()
                    msg["forwarded_from"] = orig.get_text(strip=True)

            # Poll
            q_el = poll_div.find("div", class_="question bold")
            question = q_el.get_text(strip=True) if q_el else ""
            total_el = poll_div.find("div", class_="total details")
            total_voters = int(total_el.get_text(strip=True).split()[0]) if total_el else 0

            answers = []
            for ans in poll_div.find_all("div", class_="answer"):
                txt = ans.get_text(strip=True).lstrip("- ").strip()
                answers.append({"text": txt, "voters": 0, "chosen": False})

            msg["poll"] = {
                "question": question,
                "closed": False,
                "total_voters": total_voters,
                "answers": answers
            }
            messages.append(msg)
            continue

        # Text with formatting
        text_div = div.find("div", class_="text")
        if text_div:
            full_text = ""
            entities = []
            TAG_MAP = {"strong": "bold", "em": "italic", "u": "underline", "s": "strikethrough",
                       "blockquote": "blockquote", "pre": "pre", "span": "spoiler", "a": "text_link"}

            def walk(node):
                nonlocal full_text, entities
                if isinstance(node, NavigableString):
                    txt = node.strip().replace("\n", "")
                    if not txt:
                        return
                    full_text += txt
                    entities.append({"type": "plain", "text": txt})
                    return
                elif isinstance(node, Tag):
                    tag = node.name
                    if tag == "span" and node.get("aria-hidden") == "true":
                        etype = "spoiler"
                    else:
                        etype = TAG_MAP.get(tag)
                    txt = node.get_text().replace("\n", "")
                    if not txt:
                        return
                    full_text += txt
                    if etype == "pre":
                        entities.append({"type": "pre", "text": txt, "language": ""})
                        return
                    if etype == "blockquote":
                        entities.append({"type": "blockquote", "text": txt, "collapsed": False})
                        return
                    if etype == "spoiler":
                        entities.append({"type": "spoiler", "text": txt})
                        return
                    if node.name == "a" and node.has_attr("href"):
                        entities.append({"type": "text_link", "text": txt, "href": node["href"]})
                        return
                    else:
                        entities.append({"type": etype or "plain", "text": txt})
                        return

            for child in text_div.contents:
                walk(child)

            has_formatting = any(e["type"] != "plain" for e in entities)

            if has_formatting:
                text_list = [dict(e) for e in entities]
                text_list.append("")  # Required empty element
                msg["text"] = text_list

                te = [dict(e) for e in entities]
                te.append({"type": "plain", "text": ""})
                msg["text_entities"] = te

            else:
                msg["text"] = full_text
                msg["text_entities"] = entities
        else:
            msg["text"] = ""
            msg["text_entities"] = []

        # reply
        rep = div.find("div", class_="reply_to")
        if rep:
            a = rep.find("a", onclick=True)
            if a:
                mid = a["onclick"].split("(")[1].split(")")[0]
                msg["reply_to_message_id"] = int(mid)

        # Location
        loc_a = div.find("a", class_="media_location")
        if loc_a and "q=" in loc_a["href"]:
            coords = loc_a["href"].split("q=")[1].split("&")[0].split(",")
            msg["location_information"] = {
                "latitude": float(coords[0]),
                "longitude": float(coords[1]),
            }
            msg["text"] = ""
            msg["text_entities"] = []
            messages.append(msg)
            continue

        # Forward
        fwd = div.find("div", class_="forwarded body")
        if fwd:
            # Forward name
            orig = fwd.find("div", class_="from_name")
            if orig:
                for span in orig.find_all("span"):
                    span.decompose()
                msg["forwarded_from"] = orig.get_text(strip=True)
                msg["from"]    = name
                msg["from_id"] = uid

            # Forward media
            media_wrap = fwd.find("div", class_="media_wrap")
            if media_wrap:
                link = media_wrap.find("a", href=True)
                if link:
                    href = link["href"]
                    if href.startswith("http"):
                        msg["file"] = href
                    else:
                        fp = export_dir / href
                        info = get_file_info(fp, export_dir)
                        if info:
                            msg.update(info)

            # Forward text with tags (without empty newline)
            txt_div = fwd.find("div", class_="text")
            if txt_div:
                full_text = ""
                entities = []
                TAG_MAP = {
                    "strong": "bold", "em": "italic", "u": "underline", "s": "strikethrough",
                    "blockquote": "blockquote", "pre": "pre", "span": "spoiler", "a": "text_link"
                }

                def walk(node):
                    nonlocal full_text, entities
                    # plain text (hard discard nodes where txt.strip() is empty)
                    if isinstance(node, NavigableString):
                        raw = str(node)
                        txt = raw.replace("\n", "")
                        if not txt.strip():
                            return
                        full_text += txt
                        entities.append({"type": "plain", "text": txt})
                    # <br> skip (or can be converted to \n – optional)
                    elif isinstance(node, Tag) and node.name == "br":
                        # if need comment \n:
                        # full_text += "\n"
                        return
                    # Formatting tags
                    elif isinstance(node, Tag):
                        tag = node.name
                        if tag == "span" and node.get("aria-hidden") == "true":
                            etype = "spoiler"
                        else:
                            etype = TAG_MAP.get(tag)
                        txt = node.get_text().replace("\n", "")
                        if not txt:
                            return
                        full_text += txt
                        if etype == "pre":
                            entities.append({"type": "pre", "text": txt, "language": ""})
                        elif etype == "blockquote":
                            entities.append({"type": "blockquote", "text": txt, "collapsed": False})
                        elif etype == "spoiler":
                            entities.append({"type": "spoiler", "text": txt})
                        elif tag == "a" and node.has_attr("href"):
                            entities.append({"type": "text_link", "text": txt, "href": node["href"]})
                        else:
                            entities.append({"type": etype or "plain", "text": txt})

                for child in txt_div.contents:
                    walk(child)

                # If there is at least one non-plain element, we consider it formatting
                has_fmt = any(e["type"] != "plain" for e in entities)

                if has_fmt:
                    msg["text"] = [dict(e) for e in entities] + [""]
                    msg["text_entities"] = [dict(e) for e in entities] + [{"type": "plain", "text": ""}]
                else:
                    # All plain - one element with text
                    msg["text"] = full_text
                    msg["text_entities"] = [{"type": "plain", "text": full_text}]

            messages.append(msg)
            continue

        # files
        for a in div.find_all("a", href=True):
            if a.find_parent("div", class_="text"):
                continue
            href = a["href"]
            if href.startswith("http"):
                msg["file"] = href
            else:
                fp = export_dir / href
                info = get_file_info(fp, export_dir)
                if info:
                    msg.update(info)

        # Location
        extract_location(div, msg)

        messages.append(msg)
    return messages

def convert(html_file, output_file, export_dir, chat_name, chat_id):
    last_sender = {}
    msgs = parse_html_to_messages(html_file, export_dir, last_sender)
    # No more calls/parse_calls_from_html needed
    msgs_od = [order_message(m) for m in sorted(msgs, key=lambda m: m["id"])]
    data = OrderedDict([
        ("name", chat_name),
        ("type", "personal_chat"),
        ("id", chat_id),
        ("messages", msgs_od),
    ])
    with output_file.open("w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False, indent=4)

def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--path", required=True, help="Path to Telegram export folder")
    parser.add_argument("--chat_id", required=True, type=int, help="Chat ID")
    args = parser.parse_args()

    export_dir = pathlib.Path(args.path)
    soup = BeautifulSoup((export_dir/"messages.html").read_text(encoding="utf-8"), "html.parser")
    chat_name = soup.select_one(".page_header .text.bold").get_text(strip=True)
    for html in sorted(export_dir.glob("messages*.html")):
        out = html.with_suffix(".json")
        convert(html, out, export_dir, chat_name, args.chat_id)
        print(f"✅ {html.name} → {out.name}")

if __name__ == "__main__":
    main()
