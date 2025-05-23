#!/usr/bin/env python3
"""
Import of a Telegram chat in JSON format via Telethon (Sync API).
Extended import with the latest changes:

    Pinned messages display the text of the pinned message.

    Replies are in the format:
    You replied to the message: "<original>" (<time>)
    <our reply>

    Round videos (video_message) are correctly imported as video messages.

    Forwarded voice messages and other media get a label.

    Forwarded messages from channels retain the text.

    Forwards with attachments display a text caption under the attachment.
"""
import argparse
import json
import math
import mimetypes
import os
import tempfile
import pathlib
import sys
from dateutil.parser import parse as parse_dt
from telethon.sync import TelegramClient
from telethon import functions, types
from tqdm import tqdm


def _fmt_date(msg):
    try:
        dt = parse_dt(msg.get('date', ''))
        return dt.strftime('%d/%m/%y, %H:%M')
    except:
        return ''


def _fmt_text(msg):
    ents = msg.get('text_entities') or []
    if isinstance(ents, list) and ents:
        return ''.join(e.get('text','') for e in ents)
    return msg.get('text','') or ''


def convert_json_to_whatsapp_format(data, only_n=math.inf):
    raw_msgs = data.get('messages', [])
    # Pre-filling citation dictionaries
    id_to_content = {}
    id_to_date = {}
    for m in raw_msgs:
        mid = m.get('id')
        id_to_date[mid] = _fmt_date(m)
        fp = m.get('file') or m.get('photo') or m.get('contact_vcard')
        if fp:
            id_to_content[mid] = pathlib.Path(fp).name
        else:
            id_to_content[mid] = _fmt_text(m)

    msgs = raw_msgs[:int(only_n)] if isinstance(only_n, (int,float)) and math.isfinite(only_n) else raw_msgs
    lines = []
    filelist = {}

    for msg in msgs:
        mtype = msg.get('type')
        # Service-messages
        if mtype == 'service':
            date_str = _fmt_date(msg)
            sender = msg.get('actor') or msg.get('from') or 'Unknown'
            prefix = f"{date_str} - {sender}: "
            action = msg.get('action','')
            if action == 'pin_message':
                pid = msg.get('message_id')
                orig = id_to_content.get(pid,'')
                lines.append(f"{prefix}The message was pinned: '{orig}'\n")
            else:
                svc_map = {
                    'clear_history': 'History cleared',
                    'edit_chat_theme': f"The topic has been changed to {msg.get('emoticon','')}" ,
                    'phone_call': f"Call ({msg.get('discard_reason','')}, duration {msg.get('duration_seconds',0)}s)"
                }
                text = svc_map.get(action, action)
                lines.append(f"{prefix}{text}\n")
            continue

        # Regular messages and media
        date_str = _fmt_date(msg)
        sender = msg.get('from') or msg.get('actor') or 'Unknown'
        prefix = f"{date_str} - {sender}: "

        # Replies
        if rid := msg.get('reply_to_message_id'):
            orig = id_to_content.get(rid,'')
            orig_time = id_to_date.get(rid,'')
            lines.append(f"{prefix}You replied to the message: '{orig}' ({orig_time})\n")
            reply = _fmt_text(msg)
            if reply:
                lines.append(f"{prefix}{reply}\n")
            continue

        # Contact
        if info := msg.get('contact_information'):
            text = f"Contact: {info.get('first_name','')} {info.get('last_name','')} {info.get('phone_number','')}"
            lines.append(f"{prefix}{text}\n")
            continue

        # Poll
        if poll := msg.get('poll'):
            q = poll.get('question','')
            opts = [ans['text'] for ans in poll.get('answers',[])]
            text = f"Poll: {q} [{', '.join(opts)}]"
            lines.append(f"{prefix}{text}\n")
            continue

        # Geolocation
        if loc := msg.get('location_information'):
            url = f"https://www.google.com/maps/search/?api=1&query={loc['latitude']},{loc['longitude']}"
            lines.append(f"{prefix}{url}\n")
            continue

        # Attachments and forward
        fp = msg.get('file') or msg.get('photo') or msg.get('contact_vcard')
        if fp and not (str(fp).startswith('http://') or str(fp).startswith('https://')):
            # Forward label, if any
            if fwd := msg.get('forwarded_from'):
                lines.append(f"{prefix}[Forwarded from {fwd}]\n")
            fn = pathlib.Path(fp).name
            attr = {'filename': fn, 'media_type': msg.get('media_type'), 'is_photo': bool(msg.get('photo'))}
            for a in ('duration_seconds','width','height','file_size','thumbnail','thumbnail_file_size'):
                if a in msg:
                    attr[a] = msg[a]
            filelist[fp] = attr
            # Attachment as a separate message
            lines.append(f"{prefix}{fn} (file attached)\n")
            # Caption for the attachment
            caption = _fmt_text(msg)
            if caption:
                lines.append(f"{prefix}{caption}\n")
            continue

        # Other text and forward in the text
        parts = []
        if fwd := msg.get('forwarded_from'):
            parts.append(f"[Forwarded from {fwd}] ")
        parts.append(_fmt_text(msg))
        text = ''.join(parts).strip()
        if text:
            lines.append(f"{prefix}{text}\n")

    return lines, filelist


def upload_file(client, peer, imp_id, base_path, rel_path, info):
    path = base_path / rel_path
    fn = info['filename']
    mime = info.get('mime_type') or mimetypes.guess_type(fn)[0] or 'application/octet-stream'
    uf = client.upload_file(path)

    # Video note (round message)
    if info.get('media_type') == 'video_message':
        dur = info.get('duration_seconds',0)
        w = info.get('width',0)
        h = info.get('height',0)
        attrs = [types.DocumentAttributeVideo(dur, w, h, round_message=True)]
        media = types.InputMediaUploadedDocument(file=uf, mime_type=mime, attributes=attrs)

    # Photo
    elif info.get('is_photo'):
        media = types.InputMediaUploadedPhoto(file=uf)

    # Other documents
    else:
        attrs = [types.DocumentAttributeFilename(file_name=fn)]
        if 'width' in info and 'height' in info:
            attrs.append(types.DocumentAttributeImageSize(info['width'], info['height']))
        if info.get('media_type') == 'video_file' and 'duration_seconds' in info:
            attrs.append(types.DocumentAttributeVideo(info['duration_seconds'], info.get('width'), info.get('height')))
        if info.get('media_type') == 'animation':
            attrs.append(types.DocumentAttributeAnimated())
        if info.get('media_type') == 'sticker':
            attrs.append(types.DocumentAttributeSticker('', types.InputStickerSetEmpty()))
        if info.get('media_type') in ('audio_file','voice_message') and 'duration_seconds' in info:
            attrs.append(types.DocumentAttributeAudio(info['duration_seconds']))
        media = types.InputMediaUploadedDocument(file=uf, mime_type=mime, attributes=attrs)

    client(functions.messages.UploadImportedMediaRequest(peer=peer, import_id=imp_id, file_name=fn, media=media))


def import_history(path: pathlib.Path, peer_id: str, test_only=False, only_first_n=math.inf):
    json_file = path / 'result.json'
    if not json_file.exists():
        sys.exit('Not found result.json')
    with open(json_file, encoding='utf-8') as f:
        data = json.load(f)

    messages, files = convert_json_to_whatsapp_format(data, only_first_n)
    head = ''.join(messages[:100])

    api_id, api_hash = ID, 'HASH'
    with TelegramClient('telegram_import', api_id, api_hash) as client:
        try:
            peer = client.get_entity(types.PeerChannel(int(peer_id)))
        except:
            peer = peer_id

        client(functions.messages.CheckHistoryImportRequest(import_head=head))
        client(functions.messages.CheckHistoryImportPeerRequest(peer=peer))

        tmp = tempfile.NamedTemporaryFile('w+t', delete=False, encoding='utf-8', prefix='imp_', suffix='.txt')
        tmp.writelines(messages)
        tmp.close()

        up = client.upload_file(tmp.name)
        history = client(functions.messages.InitHistoryImportRequest(peer=peer, file=up, media_count=len(files)))
        os.remove(tmp.name)

        for rel, info in tqdm(files.items(), desc='Uploading media'):
            upload_file(client, peer, history.id, path, rel, info)

        if test_only:
            print('The test mode has ended')
            return
        client(functions.messages.StartHistoryImportRequest(peer=peer, import_id=history.id))


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description='Import JSON chat into Telegram')
    parser.add_argument('--path', required=True, help='The path to the folder with result.json')
    parser.add_argument('--peer', required=True, help='Chat-ID or @username')
    parser.add_argument('--test-only', action='store_true', help='Test mode only')
    parser.add_argument('--only-first', type=float, help='First N messages')
    args = parser.parse_args()
    import_history(pathlib.Path(args.path), args.peer, args.test_only, args.only_first or math.inf)
